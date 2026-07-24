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

/// An identity authorized to reach the operator (dashboard) surface. The
/// operator proves possession of the matching PRIVATE key by signing a
/// server-issued challenge; hestia only ever holds the PUBLIC key. This is
/// Web4 authenticating with Web4 — a witnessed, key-bound identity (RWOA clause
/// W), not a shared secret. Keys are hardware-bindable (TPM/SE) in production.
///
/// The set of these lives in the *law* (`VaultPolicyState::operator_access`), so
/// who may operate is law-gated and multi-identity by construction — not a single
/// hardcoded credential. Adding an operator is a law amendment, not a code change.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperatorIdentity {
    /// The operator's LCT id (the witnessed identity this key belongs to).
    pub lct_id: String,
    /// Ed25519 public key, 64 lowercase hex chars (32 bytes). The private half
    /// stays with the operator (browser/helper/TPM) and never enters the vault.
    pub public_key_hex: String,
    /// Human label for the operator UI (e.g. "dp — laptop TPM"). Non-authoritative.
    #[serde(default)]
    pub label: String,
}

impl OperatorIdentity {
    /// Reconstruct the Ed25519 public key from the stored hex. `None` if the hex
    /// is malformed (which then can never verify — fail-closed).
    pub fn public_key(&self) -> Option<web4_core::crypto::PublicKey> {
        let raw = hex::decode(self.public_key_hex.trim()).ok()?;
        let arr: [u8; 32] = raw.try_into().ok()?;
        web4_core::crypto::PublicKey::from_bytes(&arr).ok()
    }

    /// Verify `signature` over `challenge` against this operator's public key.
    pub fn verify(&self, challenge: &[u8], signature: &web4_core::crypto::SignatureBytes) -> bool {
        self.public_key()
            .map(|pk| pk.verify(challenge, signature).is_ok())
            .unwrap_or(false)
    }
}

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

    /// Per-constellation-role overlay rules (#403 role-scoped law), keyed by the
    /// canonical `role:constellation:*`. Each role's rules are evaluated as a
    /// SEPARATE policy (default `Allow`) and folded into the base by taking the
    /// STRICTER verdict — so a self-declared role can only ever TIGHTEN law, never
    /// loosen it (the base preset is always the floor). This is the safe design
    /// for self-declared roles: declaring the least-restrictive role gets you the
    /// base, never less. Empty = no role scoping (every session gets the base).
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub role_overlays: HashMap<String, Vec<PolicyRule>>,

    /// Per-`(instance, role)` overlay rules — the FINEST policy grain (stats and
    /// trust already key on `(instance, role)`; this is the matching policy leg).
    /// Nested `plugin_id → role → rules`, so a *specific* orchestrator in a role
    /// (e.g. `kimi-code` as `role:constellation:foreign-kimi`) can carry policy
    /// distinct from the generic role overlay. Folded strictest-wins AFTER the
    /// role overlay — the most specific tightening, never a loosening (the base
    /// preset and role overlay stay the floor). Empty = no per-instance scoping.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub instance_overlays: HashMap<String, HashMap<String, Vec<PolicyRule>>>,

    /// Identities authorized to reach the operator (dashboard) surface — the
    /// law-gated access list (dp: dashboard access is the security boundary, and
    /// it must itself be law-gated, not a single hardcoded credential). Empty on
    /// a fresh vault; the daemon bootstraps exactly one operator on first run
    /// (and refuses to serve the operator surface with an empty list — fail-
    /// closed, no anonymous operator). Each entry is a key-bound witnessed
    /// identity (RWOA clause W).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub operator_access: Vec<OperatorIdentity>,

    /// Law-settable quorum (number of distinct operator signatures) required for
    /// an IRREVERSIBLE operator act — the clause-V escalation made concrete (RWOA
    /// gradient, ratified 2026-07-12: irreversible acts pass a catastrophic-risk
    /// check that can require multiple signatures by law). Reversible acts need a
    /// single operator's strong evidence; irreversible ones (secret release — a
    /// read has no undo — an irreversible law change, an operator-set change that
    /// could lock out) require `operator_irreversible_quorum` distinct signatures.
    /// `None` ⇒ default 2 (bounded below by the number of operators, and by 1
    /// during the bootstrap window); `Some(1)` is a deliberate single-operator
    /// waiver an operator must set in law explicitly.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operator_irreversible_quorum: Option<u32>,

    /// Law-settable number of attempts to persist a synthetic-exclusion write
    /// before `mark_synthetic` gives up and the connect is refused (fail-closed).
    /// `None` ⇒ [`DEFAULT_SYNTHETIC_PERSIST_ATTEMPTS`] (3). An operator can raise
    /// it for flaky storage or lower it to fail faster; it lives here (not a side
    /// config) so it is inspectable and travels with the vault.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub synthetic_persist_max_attempts: Option<u32>,
}

/// Default persist attempts for a synthetic-exclusion write when the vault policy
/// doc does not set one. Bounded retry, then fail-closed (refuse the connect).
pub const DEFAULT_SYNTHETIC_PERSIST_ATTEMPTS: u32 = 3;

impl Default for VaultPolicyState {
    fn default() -> Self {
        Self {
            active_preset: "safety".into(),
            overrides: HashMap::new(),
            custom_rules: Vec::new(),
            role_overlays: HashMap::new(),
            instance_overlays: HashMap::new(),
            operator_access: Vec::new(),
            operator_irreversible_quorum: None,
            synthetic_persist_max_attempts: None,
        }
    }
}

impl VaultPolicyState {
    /// Effective synthetic-persist attempt budget (>= 1), law-settable with a
    /// default of [`DEFAULT_SYNTHETIC_PERSIST_ATTEMPTS`].
    pub fn synthetic_persist_attempts(&self) -> u32 {
        self.synthetic_persist_max_attempts
            .unwrap_or(DEFAULT_SYNTHETIC_PERSIST_ATTEMPTS)
            .max(1)
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

    /// Build a per-role overlay `PolicyConfig` for each role that declares one.
    /// Each defaults to `Allow` — a no-match means the role adds no restriction —
    /// so folding it into the base by strictest-verdict can only tighten, never
    /// loosen. Empty map when no role overlays are configured.
    ///
    /// Overlays ENFORCE unconditionally (`enforce: true`), independent of the
    /// base preset's mode. Rationale (attendance-scaled law, ratified
    /// 2026-07-06): the base preset's `enforce=false` (permissive/audit-only)
    /// expresses the *observation phase* for attended sessions, while an overlay
    /// rule is EXPLICIT operator-authored law for an unattended capacity — the
    /// operator wrote `deny`, not `would-deny`. Inheriting the base's flag made
    /// ratified unattended law silently observational on a permissive base.
    pub fn role_configs(&self) -> HashMap<String, crate::policy::PolicyConfig> {
        let enforce = true;
        self.role_overlays
            .iter()
            .map(|(role, rules)| {
                // Surface misconfig loudly: sessions normalize their declared role
                // fail-closed to the published set, so an overlay keyed to an
                // unpublished role can never be selected — it would be silently
                // dead law. Still built (harmless), but warn so the operator sees it.
                if !crate::reputation::KNOWN_CONSTELLATION_ROLES.contains(&role.as_str()) {
                    eprintln!(
                        "[policy] WARNING: role_overlays key '{role}' is not in the \
                         published constellation-role set — no session can select this \
                         overlay (declared roles normalize fail-closed to known roles)"
                    );
                }
                (
                    role.clone(),
                    crate::policy::PolicyConfig {
                        default_policy: crate::policy::PolicyDecision::Allow,
                        enforce,
                        rules: rules.clone(),
                    },
                )
            })
            .collect()
    }

    /// Per-`(instance, role)` overlay engines, keyed by `(plugin_id, role)`. Each
    /// is a default-`Allow` config folded strictest-wins into the base + role
    /// overlay, so it can only tighten. Mirrors [`role_configs`] one grain finer.
    pub fn instance_configs(&self) -> HashMap<(String, String), crate::policy::PolicyConfig> {
        let mut out = HashMap::new();
        for (plugin_id, by_role) in &self.instance_overlays {
            for (role, rules) in by_role {
                out.insert(
                    (plugin_id.clone(), role.clone()),
                    crate::policy::PolicyConfig {
                        default_policy: crate::policy::PolicyDecision::Allow,
                        enforce: true,
                        rules: rules.clone(),
                    },
                );
            }
        }
        out
    }

    /// The rules currently set for one `(plugin_id, role)` grain — for the
    /// dashboard to display/seed the editor. `None` if none set.
    pub fn instance_overlay(&self, plugin_id: &str, role: &str) -> Option<&Vec<PolicyRule>> {
        self.instance_overlays
            .get(plugin_id)
            .and_then(|m| m.get(role))
    }

    /// Required distinct operator signatures for an irreversible act (clause V).
    /// Law setting, default 2, floored at 1. If it exceeds the number of
    /// authorized operators the act fails closed (needs more operators) — the
    /// law deliberately forcing multi-party control over the irreversible tail.
    pub fn irreversible_quorum(&self) -> u32 {
        self.operator_irreversible_quorum.unwrap_or(2).max(1)
    }

    /// Is the operator surface bootstrapped (at least one authorized operator)?
    /// An empty list means no one may operate — the surface fails closed until
    /// first-run bootstrap seeds one, so there is never an anonymous operator.
    pub fn operator_access_bootstrapped(&self) -> bool {
        !self.operator_access.is_empty()
    }

    /// Verify a signed operator challenge against the law's authorized set.
    /// Returns the authorized `OperatorIdentity` iff `lct_id` is in
    /// `operator_access` AND `signature` is a valid signature over `challenge`
    /// by that identity's key. Fail-closed: unknown id, bad key, or bad
    /// signature all yield `None`. Reachability plays no part — only the
    /// signature (RWOA: R excluded, W enforced).
    pub fn authorize_operator(
        &self,
        lct_id: &str,
        challenge: &[u8],
        signature: &web4_core::crypto::SignatureBytes,
    ) -> Option<&OperatorIdentity> {
        self.operator_access
            .iter()
            .find(|op| op.lct_id == lct_id && op.verify(challenge, signature))
    }

    /// Set (replace) the overlay rules for one `(plugin_id, role)` grain. An empty
    /// `rules` clears the grain — never leaves an empty map behind (so
    /// `skip_serializing_if` keeps absent-stays-absent). Returns `true` if the
    /// stored state changed.
    pub fn set_instance_overlay(
        &mut self,
        plugin_id: &str,
        role: &str,
        rules: Vec<PolicyRule>,
    ) -> bool {
        if rules.is_empty() {
            let changed = self
                .instance_overlays
                .get_mut(plugin_id)
                .map(|m| m.remove(role).is_some())
                .unwrap_or(false);
            // prune an emptied plugin_id map so absence stays absence
            if self
                .instance_overlays
                .get(plugin_id)
                .is_some_and(HashMap::is_empty)
            {
                self.instance_overlays.remove(plugin_id);
            }
            return changed;
        }
        let prev = self
            .instance_overlays
            .entry(plugin_id.to_string())
            .or_default()
            .insert(role.to_string(), rules.clone());
        prev.as_ref() != Some(&rules)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::PolicyDecision;

    fn deny_rule(id: &str, tool: &str) -> PolicyRule {
        use crate::policy::types::{PolicyMatch, PolicyRule};
        PolicyRule {
            id: id.into(),
            name: id.into(),
            priority: 0,
            decision: PolicyDecision::Deny,
            reason: None,
            r#match: PolicyMatch {
                tools: Some(vec![tool.into()]),
                ..Default::default()
            },
        }
    }

    #[test]
    fn operator_auth_is_key_bound_and_fail_closed() {
        use web4_core::crypto::KeyPair;

        // an empty operator_access = no one may operate (fail-closed until bootstrap)
        let mut s = VaultPolicyState::default();
        assert!(!s.operator_access_bootstrapped());

        // bootstrap one operator: hestia stores only the PUBLIC key
        let kp = KeyPair::generate();
        let op_lct = "lct:web4:operator:dp";
        s.operator_access.push(OperatorIdentity {
            lct_id: op_lct.into(),
            public_key_hex: hex::encode(kp.public_key_bytes()),
            label: "dp — test".into(),
        });
        assert!(s.operator_access_bootstrapped());

        let challenge = b"hestia-operator-challenge:nonce-abc123";
        let good_sig = kp.sign(challenge);

        // the authorized operator's valid signature authorizes
        assert!(s.authorize_operator(op_lct, challenge, &good_sig).is_some());

        // wrong key (a different keypair signing) → refused
        let attacker = KeyPair::generate();
        let bad_sig = attacker.sign(challenge);
        assert!(s.authorize_operator(op_lct, challenge, &bad_sig).is_none());

        // right key but wrong challenge (replay of a signature over other bytes) → refused
        let other_sig = kp.sign(b"a different challenge");
        assert!(
            s.authorize_operator(op_lct, challenge, &other_sig)
                .is_none()
        );

        // unknown lct_id, even with a valid signature by its own key → refused
        assert!(
            s.authorize_operator("lct:web4:operator:stranger", challenge, &good_sig)
                .is_none()
        );

        // malformed stored pubkey → fail-closed (can never verify)
        s.operator_access[0].public_key_hex = "not-hex".into();
        assert!(s.authorize_operator(op_lct, challenge, &good_sig).is_none());
    }

    #[test]
    fn operator_access_serde_back_compat() {
        // older vault doc without the field → empty (surface fails closed), no error
        let old = r#"{"active_preset":"safety"}"#;
        let s: VaultPolicyState = serde_json::from_str(old).unwrap();
        assert!(s.operator_access.is_empty());
        assert!(!s.operator_access_bootstrapped());
    }

    #[test]
    fn instance_overlay_set_get_clear_and_configs_keying() {
        let mut s = VaultPolicyState::default();
        let (pid, role) = ("kimi-code", "role:constellation:foreign-kimi");
        assert!(s.instance_overlay(pid, role).is_none());

        // set → present, and instance_configs keys on (plugin_id, role)
        assert!(s.set_instance_overlay(pid, role, vec![deny_rule("no-bash", "Bash")]));
        assert_eq!(s.instance_overlay(pid, role).map(Vec::len), Some(1));
        let cfgs = s.instance_configs();
        assert!(cfgs.contains_key(&(pid.to_string(), role.to_string())));
        assert_eq!(cfgs[&(pid.to_string(), role.to_string())].rules.len(), 1);
        // another instance in the SAME role is a distinct grain (unset)
        assert!(!cfgs.contains_key(&("claude-code".to_string(), role.to_string())));

        // idempotent set of the same rules reports no change
        assert!(!s.set_instance_overlay(pid, role, vec![deny_rule("no-bash", "Bash")]));

        // clear via empty rules → gone, and the plugin_id map is pruned (absence stays absent)
        assert!(s.set_instance_overlay(pid, role, vec![]));
        assert!(s.instance_overlay(pid, role).is_none());
        assert!(
            s.instance_overlays.is_empty(),
            "emptied plugin map is pruned"
        );
    }

    #[test]
    fn instance_overlays_serde_back_compat() {
        // older vault doc without the field → empty, no error
        let old = r#"{"active_preset":"safety"}"#;
        let s: VaultPolicyState = serde_json::from_str(old).unwrap();
        assert!(s.instance_overlays.is_empty());
        // round-trips when set
        let mut s2 = VaultPolicyState::default();
        s2.set_instance_overlay("kimi-code", "role:x", vec![deny_rule("d", "Bash")]);
        let round: VaultPolicyState =
            serde_json::from_str(&serde_json::to_string(&s2).unwrap()).unwrap();
        assert_eq!(
            round.instance_overlay("kimi-code", "role:x").map(Vec::len),
            Some(1)
        );
    }

    #[test]
    fn synthetic_persist_attempts_is_law_settable_default_three() {
        // default (unset) => 3
        let mut s = VaultPolicyState::default();
        assert_eq!(s.synthetic_persist_max_attempts, None);
        assert_eq!(s.synthetic_persist_attempts(), 3);
        // operator-set value is honored
        s.synthetic_persist_max_attempts = Some(5);
        assert_eq!(s.synthetic_persist_attempts(), 5);
        // floored at 1 — a 0 in the vault can never mean "never persist / never refuse"
        s.synthetic_persist_max_attempts = Some(0);
        assert_eq!(s.synthetic_persist_attempts(), 1);
    }

    #[test]
    fn synthetic_attempts_survives_serde_roundtrip_and_back_compat() {
        // absent field in an older vault doc deserializes to the default
        let old = r#"{"active_preset":"safety"}"#;
        let s: VaultPolicyState = serde_json::from_str(old).unwrap();
        assert_eq!(s.synthetic_persist_attempts(), 3);
        // an explicit value round-trips
        let mut s2 = VaultPolicyState::default();
        s2.synthetic_persist_max_attempts = Some(7);
        let round: VaultPolicyState =
            serde_json::from_str(&serde_json::to_string(&s2).unwrap()).unwrap();
        assert_eq!(round.synthetic_persist_attempts(), 7);
    }

    #[test]
    fn default_state_resolves_to_safety_preset() {
        let s = VaultPolicyState::default();
        assert_eq!(s.active_preset, "safety");
        let cfg = s.resolve().unwrap();
        assert!(cfg.enforce);
        assert_eq!(cfg.rules.len(), 6); // was 7; warn-git-push-no-pat removed 2026-07-18
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
        assert_eq!(cfg.rules.len(), 5); // base 6 minus the disabled warn-network
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

    /// Ratified attendance-scaled law: an overlay deny ENFORCES even when the
    /// base preset is observational (permissive, enforce=false). Inheriting the
    /// base flag turned ratified unattended law into silent would-deny audit —
    /// caught live on 2026-07-06 (mesh-worker force-push exit=0).
    #[test]
    fn role_overlay_enforces_even_on_permissive_base() {
        use crate::policy::types::{PolicyMatch, PolicyRule};
        let mut s = VaultPolicyState {
            active_preset: "permissive".into(),
            ..Default::default()
        };
        assert!(
            !s.resolve().unwrap().enforce,
            "precondition: permissive base is audit-only"
        );
        s.role_overlays.insert(
            "role:constellation:mesh-worker".into(),
            vec![PolicyRule {
                id: "r".into(),
                name: "n".into(),
                priority: 0,
                decision: PolicyDecision::Deny,
                reason: None,
                r#match: PolicyMatch {
                    tools: Some(vec!["X".into()]),
                    ..Default::default()
                },
            }],
        );
        let cfg = s.role_configs();
        assert!(
            cfg["role:constellation:mesh-worker"].enforce,
            "operator-authored role law must enforce regardless of base mode"
        );
    }

    #[test]
    fn role_configs_are_allow_default_and_carry_only_declared_roles() {
        use crate::policy::types::{PolicyMatch, PolicyRule};
        let mut s = VaultPolicyState::default();
        s.role_overlays.insert(
            "role:constellation:mesh-worker".into(),
            vec![PolicyRule {
                id: "r".into(),
                name: "n".into(),
                priority: 0,
                decision: PolicyDecision::Deny,
                reason: None,
                r#match: PolicyMatch {
                    tools: Some(vec!["X".into()]),
                    ..Default::default()
                },
            }],
        );
        let cfgs = s.role_configs();
        let cfg = cfgs.get("role:constellation:mesh-worker").unwrap();
        // Allow-default so a no-match adds nothing → the base decides via strictest.
        assert_eq!(cfg.default_policy, PolicyDecision::Allow);
        assert_eq!(cfg.rules.len(), 1);
        assert_eq!(cfg.rules[0].decision, PolicyDecision::Deny);
        // A role with no overlay isn't present → it falls through to the base engine.
        assert!(!cfgs.contains_key("role:constellation:interactive-dev"));

        // Default (no overlays) → empty map → every session gets the base.
        assert!(VaultPolicyState::default().role_configs().is_empty());
    }
}
