//! Wire-compatible target codec for the typed standing-grant migration (#1402).
//!
//! This prerequisite does not change the live store or grant authority. Filesystem
//! normalization remains the caller's responsibility, as in the legacy store.
//! Repository targets never participate in path containment, floor or reroot logic.

use super::repository_target::RepositoryTarget;
use serde::{Deserialize, Serialize};

/// A target's domain is part of its identity, even when its text is identical.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "TargetWire", into = "TargetWire")]
pub enum GrantTarget {
    Path { path: String, recursive: bool },
    Repository(RepositoryTarget),
}

impl GrantTarget {
    /// Resolve the decider's breadth without crossing target domains. Callers
    /// normalize filesystem paths before this check, as for standing grants.
    /// A repository's owner/name is immutable: path breadth is never meaningful
    /// for it, even when the supplied text happens to equal the repository name.
    pub fn decision_reach(
        &self,
        grant_path: Option<&str>,
        recursive: bool,
    ) -> Result<Self, String> {
        match self {
            Self::Repository(_) if recursive || grant_path.is_some() => {
                Err("repository decisions cannot choose path breadth or recursion".into())
            }
            Self::Repository(_) => Ok(self.clone()),
            Self::Path { path, .. } => {
                let reach = grant_path.unwrap_or(path);
                if reach != path {
                    if !reach.starts_with('/')
                        || reach == "/"
                        || !super::standing_scope::covers_path(reach, true, path)
                    {
                        return Err(format!(
                            "grant_path must be the asked path ({path}) or a directory above it (and never the root); got {reach}"
                        ));
                    }
                    if !recursive {
                        return Err("a grant on a directory ABOVE the asked path must be recursive — an exact grant there would not reach what was asked".into());
                    }
                }
                Ok(Self::Path {
                    path: reach.into(),
                    recursive,
                })
            }
        }
    }

    /// Parse a member's narrow ask without treating unrelated request metadata as
    /// target fields. Presence (including null) matters: never discard a second
    /// selector and accidentally ask for a different domain. Breadth is decided
    /// by the operator; this parser cannot request a recursive grant.
    pub fn from_request_args(args: &serde_json::Value) -> Result<Self, String> {
        let object = args.as_object().ok_or("scope request must be an object")?;
        if object.contains_key("path") == object.contains_key("repo") {
            return Err("scope request requires exactly one of path or repo".into());
        }
        if object
            .get("recursive")
            .is_some_and(|v| v != &serde_json::Value::Bool(false))
        {
            return Err("scope request breadth is decided by the operator".into());
        }
        let mut target = serde_json::Map::new();
        for key in ["path", "repo"] {
            if let Some(value) = object.get(key) {
                target.insert(key.into(), value.clone());
            }
        }
        serde_json::from_value(serde_json::Value::Object(target)).map_err(|e| e.to_string())
    }

    /// Identity within one member's grants. Recursion is mutable reach, not a
    /// second identity: replacing an exact grant with a subtree must replace the
    /// same row. Callers must still compare the member separately.
    pub fn same_identity(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Path { path: a, .. }, Self::Path { path: b, .. }) => a == b,
            (Self::Repository(a), Self::Repository(b)) => a == b,
            _ => false,
        }
    }

    /// Explicit path projection for containment, floor and reroot consumers.
    /// A repository name is never converted into filesystem reach.
    pub fn as_path(&self) -> Option<(&str, bool)> {
        match self {
            Self::Path { path, recursive } => Some((path, *recursive)),
            Self::Repository(_) => None,
        }
    }
}

// Separate strict variants are deliberate: Option fields would conflate an absent
// selector with an explicit null, and could silently accept path + repo:null.
#[derive(Serialize, Deserialize)]
#[serde(untagged, deny_unknown_fields)]
enum TargetWire {
    Path {
        path: String,
        #[serde(default)]
        recursive: bool,
    },
    Repository {
        repo: RepositoryTarget,
        #[serde(default)]
        recursive: bool,
    },
}

impl TryFrom<TargetWire> for GrantTarget {
    type Error = &'static str;

    fn try_from(wire: TargetWire) -> Result<Self, Self::Error> {
        match wire {
            TargetWire::Path { path, recursive } => Ok(Self::Path { path, recursive }),
            TargetWire::Repository {
                repo,
                recursive: false,
            } => Ok(Self::Repository(repo)),
            TargetWire::Repository {
                recursive: true, ..
            } => Err("repository grants cannot be recursive"),
        }
    }
}

impl From<GrantTarget> for TargetWire {
    fn from(target: GrantTarget) -> Self {
        match target {
            GrantTarget::Path { path, recursive } => Self::Path { path, recursive },
            GrantTarget::Repository(repo) => Self::Repository {
                repo,
                recursive: false,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};

    #[test]
    fn decision_reach_repository_never_uses_path_breadth() {
        let target = GrantTarget::Repository(RepositoryTarget::parse("OWNER/Repo").unwrap());
        assert_eq!(target.decision_reach(None, false).unwrap(), target);
        assert!(target.decision_reach(None, true).is_err());
        for path in ["owner/repo", "other/repo", "/owner", "", "/"] {
            for recursive in [false, true] {
                assert!(target.decision_reach(Some(path), recursive).is_err());
            }
        }
    }

    #[test]
    fn decision_reach_path_preserves_existing_breadth_contract() {
        let target = GrantTarget::Path {
            path: "/work/tree/file".into(),
            recursive: true,
        };
        // The decider chooses recursion; the request's old flag is not inherited.
        assert_eq!(
            target.decision_reach(None, false).unwrap().as_path(),
            Some(("/work/tree/file", false))
        );
        assert_eq!(
            target
                .decision_reach(Some("/work/tree/file"), true)
                .unwrap()
                .as_path(),
            Some(("/work/tree/file", true))
        );
        assert_eq!(
            target
                .decision_reach(Some("/work/tree"), true)
                .unwrap()
                .as_path(),
            Some(("/work/tree", true))
        );
        assert!(target.decision_reach(Some("/work/tree"), false).is_err());
        for path in [
            "/",
            "/work/tr",
            "/elsewhere",
            "work",
            "/work/tree/file/child",
        ] {
            assert!(
                target.decision_reach(Some(path), true).is_err(),
                "accepted {path}"
            );
        }
    }

    #[test]
    fn member_request_keeps_domain_and_ignores_only_metadata() {
        let path = GrantTarget::from_request_args(&json!({
            "path":"/work/file", "plugin_id":"member", "reason":"need evidence"
        }))
        .unwrap();
        assert_eq!(path.as_path(), Some(("/work/file", false)));
        let repo = GrantTarget::from_request_args(&json!({
            "repo":"OWNER/Repo", "plugin_id":"member", "recursive":false
        }))
        .unwrap();
        assert_eq!(
            repo,
            GrantTarget::Repository(RepositoryTarget::parse("owner/repo").unwrap())
        );
        assert_eq!(repo.as_path(), None);
        assert!(!repo.same_identity(&GrantTarget::Repository(
            RepositoryTarget::parse("other/repo").unwrap()
        )));
    }

    #[test]
    fn member_request_rejects_ambiguous_selectors_and_member_breadth() {
        for args in [
            json!(null),
            json!([]),
            json!({}),
            json!({"repo":null}),
            json!({"path":null}),
            json!({"path":"/a", "repo":null}),
            json!({"path":null, "repo":"owner/repo"}),
            json!({"path":"/a", "repo":"owner/repo"}),
            json!({"repo":"repo"}),
            json!({"repo":"owner/*"}),
            json!({"repo":"https://github.com/owner/repo"}),
            json!({"path":"/a", "recursive":true}),
            json!({"repo":"owner/repo", "recursive":true}),
            json!({"path":"/a", "recursive":null}),
            json!({"path":"/a", "recursive":"false"}),
        ] {
            assert!(
                GrantTarget::from_request_args(&args).is_err(),
                "accepted {args}"
            );
        }
    }

    #[test]
    fn identity_ignores_reach_but_equality_retains_it() {
        let exact = GrantTarget::Path {
            path: "/work/repo".into(),
            recursive: false,
        };
        let subtree = GrantTarget::Path {
            path: "/work/repo".into(),
            recursive: true,
        };
        assert!(exact.same_identity(&subtree));
        assert!(subtree.same_identity(&exact));
        assert_ne!(exact, subtree, "audit equality must retain recursive reach");
        let child = GrantTarget::Path {
            path: "/work/repo/child".into(),
            recursive: false,
        };
        assert!(
            !subtree.same_identity(&child),
            "containment is not row identity"
        );
    }

    #[test]
    fn identity_distinguishes_domains_and_repository_owners() {
        let repo = GrantTarget::Repository(RepositoryTarget::parse("owner/repo").unwrap());
        let normalized = GrantTarget::Repository(RepositoryTarget::parse("OWNER/REPO").unwrap());
        let foreign = GrantTarget::Repository(RepositoryTarget::parse("other/repo").unwrap());
        assert!(repo.same_identity(&normalized));
        assert!(!repo.same_identity(&foreign));
        for recursive in [false, true] {
            let path = GrantTarget::Path {
                path: "owner/repo".into(),
                recursive,
            };
            assert!(!repo.same_identity(&path));
            assert!(!path.same_identity(&repo));
        }
    }

    #[test]
    fn path_projection_preserves_reach_and_excludes_repositories() {
        for recursive in [false, true] {
            let path = GrantTarget::Path {
                path: "/work/repo".into(),
                recursive,
            };
            assert_eq!(path.as_path(), Some(("/work/repo", recursive)));
            let reloaded: GrantTarget =
                serde_json::from_str(&serde_json::to_string(&path).unwrap()).unwrap();
            assert_eq!(reloaded.as_path(), path.as_path());
        }
        let repo: GrantTarget = serde_json::from_str(r#"{"repo":"owner/repo"}"#).unwrap();
        assert_eq!(repo.as_path(), None);
    }

    #[test]
    fn legacy_path_defaults_exact_and_preserves_recursive() {
        for recursive in [false, true] {
            let wire = json!({"path":"/work/repo", "recursive": recursive});
            let target: GrantTarget = serde_json::from_value(wire.clone()).unwrap();
            assert_eq!(
                target,
                GrantTarget::Path {
                    path: "/work/repo".into(),
                    recursive
                }
            );
            assert_eq!(serde_json::to_value(target).unwrap(), wire);
        }
        let target: GrantTarget = serde_json::from_value(json!({"path":"/work/repo"})).unwrap();
        assert_eq!(
            target,
            GrantTarget::Path {
                path: "/work/repo".into(),
                recursive: false
            }
        );
    }

    #[test]
    fn repository_roundtrip_revalidates_and_canonicalizes() {
        let target: GrantTarget = serde_json::from_value(json!({"repo":"OWNER/Repo"})).unwrap();
        let wire = serde_json::to_value(&target).unwrap();
        assert_eq!(wire, json!({"repo":"owner/repo", "recursive":false}));
        assert_eq!(serde_json::from_value::<GrantTarget>(wire).unwrap(), target);
        for raw in [
            "repo",
            "../repo",
            "owner/*",
            "/owner/repo",
            "repo:owner/repo",
        ] {
            assert!(serde_json::from_value::<GrantTarget>(json!({"repo":raw})).is_err());
        }
    }

    #[test]
    fn refuses_ambiguous_null_recursive_and_unknown_targets() {
        for wire in [
            json!({}),
            json!({"path":null}),
            json!({"repo":null}),
            json!({"path":"/work/repo", "repo":"owner/repo"}),
            json!({"path":"/work/repo", "repo":null}),
            json!({"path":null, "repo":"owner/repo"}),
            json!({"repo":"owner/repo", "recursive":true}),
            json!({"repo":"owner/repo", "recursive":null}),
            json!({"repo":"owner/repo", "recusrive":true}),
            json!({"path":"/work/repo", "recursive":"false"}),
        ] {
            assert!(
                serde_json::from_value::<GrantTarget>(wire.clone()).is_err(),
                "accepted {wire}"
            );
        }
        for wire in [
            r#"{"path":"/a","path":"/b"}"#,
            r#"{"repo":"owner/a","repo":"owner/b"}"#,
            r#"{"repo":"owner/a","recursive":false,"recursive":true}"#,
        ] {
            assert!(serde_json::from_str::<GrantTarget>(wire).is_err());
        }
    }

    #[test]
    fn equal_text_never_collapses_target_domains() {
        let path = GrantTarget::Path {
            path: "owner/repo".into(),
            recursive: false,
        };
        let repo = GrantTarget::Repository(RepositoryTarget::parse("owner/repo").unwrap());
        assert_ne!(path, repo);
        assert_ne!(
            serde_json::to_value(&path).unwrap(),
            serde_json::to_value(&repo).unwrap()
        );
        let set: std::collections::HashSet<_> = [path, repo].into_iter().collect();
        assert_eq!(set.len(), 2);
    }

    // Exercise the flattened shape needed by the next durable-row migration.
    // No production store is switched to this fixture by the codec change.
    #[derive(Debug, PartialEq, Serialize, Deserialize)]
    struct Row {
        member: String,
        #[serde(flatten)]
        target: GrantTarget,
        granted_at: u64,
        #[serde(default)]
        expires_at: Option<u64>,
        #[serde(default, skip_serializing_if = "crate::server::grant_modes::is_all")]
        modes: crate::server::grant_modes::Modes,
    }

    #[test]
    fn flattened_rows_preserve_modes_and_expiry() {
        for selector in [json!({"path":"/work/repo"}), json!({"repo":"owner/repo"})] {
            for modes in [None, Some("r"), Some("rw")] {
                let mut wire = json!({"member":"test-member", "granted_at":10, "expires_at":20});
                wire.as_object_mut()
                    .unwrap()
                    .extend(selector.as_object().unwrap().clone());
                if let Some(modes) = modes {
                    wire["modes"] = json!(modes);
                }
                let row: Row = serde_json::from_value(wire).unwrap();
                assert_eq!(row.expires_at, Some(20));
                assert_eq!(row.modes.is_all(), modes.is_none());
                let saved = serde_json::to_value(&row).unwrap();
                assert_eq!(
                    saved.get("modes"),
                    modes.map(|m| Value::String(m.into())).as_ref()
                );
                assert_eq!(serde_json::from_value::<Row>(saved).unwrap(), row);
            }
        }
        for wire in [
            json!({"member":"test", "granted_at":10, "path":"/a", "repo":"owner/repo"}),
            json!({"member":"test", "granted_at":10, "repo":"owner/repo", "recursive":true}),
        ] {
            assert!(serde_json::from_value::<Row>(wire).is_err());
        }
    }
}
