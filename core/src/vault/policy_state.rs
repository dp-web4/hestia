//! Policy state stored inside the vault.
//!
//! Lives at the same encryption boundary as the credentials — read with
//! the same passphrase, sealed with the same key. The active preset
//! name, any per-rule overrides, and any custom rules layered on top.
//!
//! Backward compatibility: this field is `#[serde(default)]` everywhere
//! in `VaultData`, so v1 vaults (which had no `policy` field) round-trip
//! correctly into the default policy state.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::policy::{PolicyDecision, PolicyRule};

/// Per-rule overrides keyed by `rule_id`. Each entry can override the
/// rule's `decision`, `enforced` flag, or completely disable it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyOverride {
    /// If `Some`, replace the rule's decision with this value.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decision: Option<PolicyDecision>,
    /// If `Some(false)`, the rule no longer fires.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

/// The policy section of the vault. Captures user choices that need to
/// survive daemon restarts and travel with the user (when the vault is
/// portable, i.e. in Hestia consumer mode).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VaultPolicyState {
    /// One of the four built-in preset names (`permissive`, `safety`,
    /// `strict`, `audit-only`) — or any future preset the daemon knows.
    pub active_preset: String,

    /// `rule_id` → override. Empty if the user hasn't touched the
    /// preset's defaults.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub overrides: HashMap<String, PolicyOverride>,

    /// Extra rules layered on top of the preset's rules. Get sorted in
    /// alongside preset rules at evaluation time.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub custom_rules: Vec<PolicyRule>,
}

impl Default for VaultPolicyState {
    fn default() -> Self {
        Self {
            active_preset: "safety".into(),
            overrides: HashMap::new(),
            custom_rules: Vec::new(),
        }
    }
}

impl VaultPolicyState {
    /// Resolve the effective `PolicyConfig` by combining the active
    /// preset with the user's overrides and custom rules.
    pub fn resolve(&self) -> Option<crate::policy::PolicyConfig> {
        let preset = crate::policy::get_preset(&self.active_preset)?;
        let mut cfg = preset.config;

        // Apply per-rule overrides
        cfg.rules.retain_mut(|rule| {
            if let Some(ov) = self.overrides.get(&rule.id) {
                if ov.enabled == Some(false) {
                    return false;
                }
                if let Some(d) = ov.decision {
                    rule.decision = d;
                }
            }
            true
        });

        // Append custom rules
        cfg.rules.extend(self.custom_rules.iter().cloned());
        Some(cfg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::PolicyDecision;

    #[test]
    fn default_state_resolves_to_safety_preset() {
        let s = VaultPolicyState::default();
        assert_eq!(s.active_preset, "safety");
        let cfg = s.resolve().unwrap();
        assert!(cfg.enforce);
        assert_eq!(cfg.rules.len(), 7);
    }

    #[test]
    fn overrides_disable_a_rule() {
        let mut s = VaultPolicyState::default();
        s.overrides.insert(
            "warn-network".into(),
            PolicyOverride {
                enabled: Some(false),
                ..Default::default()
            },
        );
        let cfg = s.resolve().unwrap();
        assert_eq!(cfg.rules.len(), 6);
        assert!(cfg.rules.iter().all(|r| r.id != "warn-network"));
    }

    #[test]
    fn overrides_change_a_rule_decision() {
        let mut s = VaultPolicyState::default();
        s.overrides.insert(
            "warn-network".into(),
            PolicyOverride {
                decision: Some(PolicyDecision::Deny),
                ..Default::default()
            },
        );
        let cfg = s.resolve().unwrap();
        let rule = cfg.rules.iter().find(|r| r.id == "warn-network").unwrap();
        assert_eq!(rule.decision, PolicyDecision::Deny);
    }

    #[test]
    fn unknown_preset_returns_none() {
        let s = VaultPolicyState {
            active_preset: "paranoid".into(),
            ..Default::default()
        };
        assert!(s.resolve().is_none());
    }

    #[test]
    fn serde_round_trip_preserves_shape() {
        let mut s = VaultPolicyState::default();
        s.overrides.insert(
            "warn-network".into(),
            PolicyOverride {
                enabled: Some(false),
                decision: None,
            },
        );
        let json = serde_json::to_string(&s).unwrap();
        let back: VaultPolicyState = serde_json::from_str(&json).unwrap();
        assert_eq!(s, back);
    }

    #[test]
    fn serde_back_compat_no_policy_field() {
        // Simulate a v1-vault JSON that has entries but no policy field —
        // it should deserialize fine into a struct where policy defaults.
        let json = r#"{"version":1,"created_at":"2026-05-16T00:00:00Z","entries":[]}"#;
        let _: super::super::storage::VaultData = serde_json::from_str(json).unwrap();
    }
}
