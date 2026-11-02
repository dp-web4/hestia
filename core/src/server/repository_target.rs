//! Explicit remote repository identities for typed scope grants (#1402).
//!
//! This is validation, not authority: callers must still use the existing witnessed
//! grant/decision, expiry and revocation paths. A filesystem path or checkout origin
//! must never be passed through a fallback to construct repository authority.
//! The operator API accepts `repo: "owner/name"`; the policy projection emits
//! `repo:owner/name`. No URL, bare name, wildcard or recursive repository grant exists.

/// A validated, case-insensitive owner/name identity. Private storage prevents callers
/// from constructing an unchecked identity; persisted strings must be parsed again.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RepositoryTarget(String);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidRepositoryTarget;

impl std::fmt::Display for InvalidRepositoryTarget {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("repo must be owner/name with plain ASCII segments (letters, digits, _, ., -); neither segment may be . or ..")
    }
}

impl std::error::Error for InvalidRepositoryTarget {}

impl RepositoryTarget {
    pub fn parse(raw: &str) -> Result<Self, InvalidRepositoryTarget> {
        let (owner, name) = raw.split_once('/').ok_or(InvalidRepositoryTarget)?;
        let plain = |segment: &str| {
            !segment.is_empty()
                && segment != "."
                && segment != ".."
                && segment
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-'))
        };
        if !plain(owner) || !plain(name) {
            return Err(InvalidRepositoryTarget);
        }
        Ok(Self(raw.to_ascii_lowercase()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Only a successfully decided repository grant may call this for projection.
    /// This method does not inspect disk, a working directory, or Git configuration.
    pub fn scope_entry(&self) -> String {
        format!("repo:{}", self.0)
    }
}

impl std::str::FromStr for RepositoryTarget {
    type Err = InvalidRepositoryTarget;

    fn from_str(raw: &str) -> Result<Self, Self::Err> {
        Self::parse(raw)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_owner_and_canonicalizes_case() {
        let target = RepositoryTarget::parse("Dp-Web4/Hestia").unwrap();
        assert_eq!(target.as_str(), "dp-web4/hestia");
        assert_eq!(target.scope_entry(), "repo:dp-web4/hestia");
        assert_eq!(target, "DP-WEB4/HESTIA".parse().unwrap());
        assert_ne!(target, RepositoryTarget::parse("foreign/hestia").unwrap());
    }

    #[test]
    fn accepts_plain_segments_without_git_suffix_rewriting() {
        for raw in ["a/b", "a_b/repo.name-1", "owner/repo.git", "a/...", "_/-"] {
            assert_eq!(RepositoryTarget::parse(raw).unwrap().as_str(), raw);
        }
        assert_ne!(
            RepositoryTarget::parse("a/b"),
            RepositoryTarget::parse("a/b.git")
        );
    }

    #[test]
    fn rejects_unqualified_paths_urls_and_wildcards() {
        for raw in [
            "",
            "hestia",
            "/hestia",
            "owner/",
            "owner/name/extra",
            "owner//name",
            "/home/owner/name",
            "path:owner/name",
            "repo:owner/name",
            "https://github.com/owner/name",
            "git@github.com:owner/name",
            "owner/*",
            "*/name",
            "owner/name/**",
            "./name",
            "../name",
            "owner/.",
            "owner/..",
            "owner%2fname/repo",
            "owner/name?ref=main",
            "owner/name#branch",
            "owner\\name/repo",
            "owner /name",
            " owner/name",
            "owner/name ",
        ] {
            assert!(RepositoryTarget::parse(raw).is_err(), "accepted {raw:?}");
        }
    }

    #[test]
    fn rejects_all_control_bytes_and_non_ascii_without_trimming() {
        for byte in 0..=127u8 {
            if byte.is_ascii_control() || byte == b' ' {
                for raw in [
                    format!("a/b{}", byte as char),
                    format!("a{}/b", byte as char),
                ] {
                    assert!(RepositoryTarget::parse(&raw).is_err(), "accepted {raw:?}");
                }
            }
        }
        for raw in ["é/name", "owner/名", "owner/na\u{200b}me", "owner/name\n"] {
            assert!(RepositoryTarget::parse(raw).is_err(), "accepted {raw:?}");
        }
    }
}
