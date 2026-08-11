//! Vault entry type — the cleartext representation of a single credential.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::rules::{PresentationRule, ReleaseRule};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultEntry {
    /// Unique ID; stable across vault rotations
    pub id: Uuid,

    /// Human-readable name (e.g. "anthropic_api_key", "github_pat", "npm_publish_token")
    pub name: String,

    /// Scope tags — `["publish"]`, `["infer"]`, `["billing"]`, etc.
    /// Used by plugins to filter requests by intent.
    pub scope: Vec<String>,

    /// User-applied tags for organization
    pub tags: Vec<String>,

    /// The credential value (in cleartext when entries are in memory;
    /// the vault file as a whole is encrypted on disk).
    pub secret: String,

    /// Plugin IDs allowed to request this credential. Empty list = none.
    ///
    /// The PRIMITIVE release axis. Superseded by `release` below when that is `Some`; kept as
    /// the legacy fallback so existing vaults are unchanged (see `effective_release`).
    pub allowed_consumers: Vec<String>,

    /// §7.1 axis 1 — **the release rule**: who may come to HOLD this credential. `None` means
    /// *unrecorded* (a legacy entry), in which case `allowed_consumers` above still decides —
    /// this field never silently loosens an existing entry. `#[serde(default)]` so every vault
    /// written before schema v2 deserializes with `None` and behaves exactly as before.
    #[serde(default)]
    pub release: Option<ReleaseRule>,

    /// §7.1 axis 2 — **the presentation rule**: to whom this may be SHOWN, what is disclosed,
    /// how many times. `None` means *no rule authored* — presenting it must ESCALATE to the
    /// owner (never a silent release, never a silent deny). This is the axis the vault had no
    /// field for, so §7's rule had nowhere to be recorded and §9 criterion 2's presentation
    /// half had no system under test. `#[serde(default)]` for the same load-unchanged reason.
    #[serde(default)]
    pub presentation: Option<PresentationRule>,

    /// When this entry was first added
    pub created_at: DateTime<Utc>,

    /// When this entry was last rotated (None if never rotated)
    pub last_rotated: Option<DateTime<Utc>>,
}

impl VaultEntry {
    pub fn new(name: impl Into<String>, secret: impl Into<String>) -> Self {
        Self {
            id: Uuid::new_v4(),
            name: name.into(),
            scope: Vec::new(),
            tags: Vec::new(),
            secret: secret.into(),
            allowed_consumers: Vec::new(),
            release: None,
            presentation: None,
            created_at: Utc::now(),
            last_rotated: None,
        }
    }

    pub fn with_scope(mut self, scope: Vec<String>) -> Self {
        self.scope = scope;
        self
    }

    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }

    pub fn with_consumers(mut self, consumers: Vec<String>) -> Self {
        self.allowed_consumers = consumers;
        self
    }

    /// Record the release rule at issuance/upsert (§7.1 axis 1).
    pub fn with_release_rule(mut self, rule: ReleaseRule) -> Self {
        self.release = Some(rule);
        self
    }

    /// Record the presentation rule at issuance/upsert (§7.1 axis 2). A credential with a
    /// presentation-time audience *cannot* be presented without this.
    pub fn with_presentation_rule(mut self, rule: PresentationRule) -> Self {
        self.presentation = Some(rule);
        self
    }

    /// The release rule that actually governs this entry: the explicit `release` when set,
    /// otherwise the legacy `allowed_consumers` list projected onto axis 1. This is where the
    /// migration lands without a flag day — an unrecorded entry keeps its exact old behaviour.
    pub fn effective_release(&self) -> ReleaseRule {
        match &self.release {
            Some(r) => r.clone(),
            None => ReleaseRule::Holders { principals: self.allowed_consumers.clone() },
        }
    }

    /// Is this plugin allowed to read this credential?
    /// Empty `allowed_consumers` = nobody allowed (deny by default).
    pub fn allows(&self, plugin_id: &str) -> bool {
        self.allowed_consumers.iter().any(|p| p == plugin_id)
    }

    /// Is this credential in scope for the requested scope tags?
    /// A credential matches if any of its scope tags appears in the request.
    /// If the credential has no scope tags, it matches anything (open).
    pub fn matches_scope(&self, requested: &[String]) -> bool {
        if self.scope.is_empty() {
            return true;
        }
        requested.iter().any(|r| self.scope.iter().any(|s| s == r))
    }
}

#[cfg(test)]
mod schema_v2_tests {
    use super::*;
    use crate::vault::rules::{Disclosure, PresentationAudience, PresentationRule, ReleaseRule};

    /// THE COMPAT GUARANTEE the additive design rests on: a vault written BEFORE schema v2 —
    /// one whose JSON has neither `release` nor `presentation` — must deserialize with both as
    /// `None` and behave exactly as before. If this fails, every existing vault on disk fails
    /// to load, which is the worst possible regression on a credential store.
    #[test]
    fn a_pre_schema_v2_entry_json_loads_with_none_and_legacy_behaviour() {
        let legacy = r#"{
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "github_pat",
            "scope": ["publish"],
            "tags": [],
            "secret": "ghp_xxx",
            "allowed_consumers": ["claude-code"],
            "created_at": "2026-01-01T00:00:00Z",
            "last_rotated": null
        }"#;
        let e: VaultEntry = serde_json::from_str(legacy).expect("legacy entry must still load");
        assert!(e.release.is_none(), "release must default to None for a legacy entry");
        assert!(e.presentation.is_none(), "presentation must default to None for a legacy entry");
        // The legacy release semantics are preserved through the fallback, unchanged.
        assert_eq!(
            e.effective_release(),
            ReleaseRule::Holders { principals: vec!["claude-code".into()] },
        );
        assert!(e.allows("claude-code") && !e.allows("kimi-code"));
    }

    /// `None` presentation is UNRECORDED (→ escalate), which is not the same object as an
    /// authored `disclose_nothing()` rule (→ owner's explicit "not presentable"). The schema
    /// must keep them distinguishable, because §9 criterion 2 tests exactly that difference.
    #[test]
    fn unrecorded_presentation_is_distinct_from_authored_disclose_nothing() {
        let unrecorded = VaultEntry::new("k", "s");
        assert!(unrecorded.presentation.is_none(), "new entry: no rule authored → escalate");

        let authored = VaultEntry::new("k", "s")
            .with_presentation_rule(PresentationRule::disclose_nothing());
        assert!(authored.presentation.is_some(), "authored 'not presentable' is a recorded rule");
        assert_ne!(unrecorded.presentation, authored.presentation);
    }

    /// A recorded entry with both axes round-trips through serde and keeps its rules — the
    /// `hestia_vault_set`-records-at-issuance contract, pinned at the storage boundary.
    #[test]
    fn a_schema_v2_entry_round_trips_both_axes() {
        let e = VaultEntry::new("mtls", "priv-key-bytes")
            .with_release_rule(ReleaseRule::ConsumerOnly)
            .with_presentation_rule(PresentationRule {
                audience: PresentationAudience::Fixed { verifier: "github.com".into() },
                disclose: Disclosure::Derived,
                max_uses: None,
            });
        let j = serde_json::to_string(&e).unwrap();
        let back: VaultEntry = serde_json::from_str(&j).unwrap();
        assert_eq!(back.release, Some(ReleaseRule::ConsumerOnly));
        assert_eq!(
            back.presentation.unwrap().audience,
            PresentationAudience::Fixed { verifier: "github.com".into() },
        );
    }

    /// An explicit `release` supersedes the legacy list — the migration path — and never the
    /// other way round: setting the rule does not touch `allowed_consumers`, so nothing is
    /// silently loosened.
    #[test]
    fn explicit_release_supersedes_the_legacy_list() {
        let e = VaultEntry::new("k", "s")
            .with_consumers(vec!["old-plugin".into()])
            .with_release_rule(ReleaseRule::Holders { principals: vec!["new-holder".into()] });
        assert_eq!(
            e.effective_release(),
            ReleaseRule::Holders { principals: vec!["new-holder".into()] },
        );
        assert_eq!(e.allowed_consumers, vec!["old-plugin".to_string()], "legacy list untouched");
    }
}
