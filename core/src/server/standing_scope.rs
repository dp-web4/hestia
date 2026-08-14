//! Durable standing scope grants — the operator-made widening that SURVIVES a restart.
//!
//! WHY THIS EXISTS (dp, 2026-08-14: "might as well do the real fix" — Sprint F's R1).
//! The gate consolidation left standing repo scope with NO daemon surface at all: the only
//! durable widening lived in a member-writable `identity.json`, which the certified-replica
//! honor logic (plugins/_shared/hestia_gate_core.py, `AgentPolicy`) rightly refuses — it
//! demands a `generation` and an `expires_at` issued by the authority, and nothing issued
//! them. So after Sprint F a member's reach was launch-cwd + home + /tmp + memory-only live
//! grants, and every one of those died with the daemon. This store is the missing authority
//! surface: operator-decided, daemon-owned, vault-persisted, generation-counted.
//!
//! THE ASYMMETRY, AMENDED — see `POLICY_SCOPE_ASYMMETRY` in `state.rs`. The 2026-08-01
//! doctrine was two rows: tightening is durable (vault), loosening is ephemeral (memory).
//! This adds the deliberately-missing third row, on dp's explicit ruling rather than by
//! drift:
//!
//! | direction           | where it lives                  | survives restart |
//! |---------------------|---------------------------------|------------------|
//! | TIGHTENING          | vault (`instance_overlays`)     | **yes**          |
//! | LIVE loosening      | memory (`instance_grants`,      | **no**           |
//! |                     |  `scope_requests`)              |                  |
//! | STANDING loosening  | vault (`scope/standing` doc)    | **yes**          |
//!
//! What keeps a DURABLE loosening safe where the memory-only rule used restart as the
//! backstop:
//!   * **operator-decided only** — the sole mutation path is the challenge-signed operator
//!     HTTP surface (`POST /api/scope/decide` with `standing: true`, and the revoke
//!     endpoint). No MCP tool can reach it; `no_mcp_tool_can_mutate_standing_scope`
//!     asserts that rather than trusting nobody writes one.
//!   * **vault-held, not a plaintext file** — #133's hole was exactly "widening a member's
//!     authority was a `json.dump` nobody had to ask permission for". The store is an
//!     encrypted vault document, written atomically (the vault's temp-file-and-rename),
//!     never a sidecar a member could edit around the gate. `load_doc`'s legacy-filename
//!     migration keeps a `standing-scope.json` from an older install readable once, then
//!     retires it into the vault.
//!   * **disclosed** — served in `hestia_scope_status` and inside `hestia_operating_law`'s
//!     hashed body, so a standing widening appearing or lapsing MOVES `law_hash`.
//!   * **expirable and revocable** — `expires_at` is honoured at every read (an expired
//!     grant is never served), and revocation is a first-class witnessed verb, because
//!     revocation is precisely the operation a policy authority most needs to work.
//!   * **generation-counted** — a monotonic counter incremented on EVERY mutation. This is
//!     what the plugin gate's certified-replica logic has been waiting for: a snapshot
//!     carrying `generation` + a daemon-issued expiry can be honoured within bounds, and a
//!     copy that cannot say which policy it is grants nothing.

use serde::{Deserialize, Serialize};

/// The CEILING on how long a served standing-scope snapshot may be honoured by a consumer
/// that caches it. The actual `snapshot_expires_at` served by `hestia_scope_status` is
/// `min(now + this, earliest expiry of every grant the response represents)` — a horizon
/// that outlived a grant inside it would keep admitting the grant for hours after the
/// operator's bound passed, and the generation does not move on wall-clock expiry, so
/// nothing else could repair the cached copy (GPT review of #431, blocker 3).
///
/// Same 8 hours as `SCOPE_REQUEST_TTL_SECS`, and for the same reason: the longer the
/// authority has been unreachable, the likelier a revocation the copy cannot know about.
/// Bounded staleness is the only kind that is safe (hestia_gate_core, `AgentPolicy`).
pub const STANDING_SNAPSHOT_TTL_SECS: u64 = 8 * 3600;

/// One standing grant: this member may reach this path (a repo root or a file), durably,
/// until it expires or an operator revokes it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StandingGrant {
    /// The member (caller-asserted plugin_id, like every other id here — HST-005).
    pub member: String,
    /// Normalised absolute path (see `state::normalize_scope_path`). A repo ROOT here is
    /// what the plugin gate maps to a repo-name grant; a deeper path stays a file grant.
    pub path: String,
    pub granted_at: u64,
    /// The operator identity from the challenge-signed session that decided it.
    #[serde(default)]
    pub granted_by: String,
    /// Why — the operator's stated rationale, required to grant. A widening whose
    /// rationale is not recorded is indistinguishable afterwards from a misconfiguration.
    #[serde(default)]
    pub reason: String,
    /// Wall-clock expiry. `None` = durable until revoked — which is exactly what makes
    /// this store different from the memory-only channel, and why revocation exists.
    #[serde(default)]
    pub expires_at: Option<u64>,
    /// The scope request this was promoted from, when it came through the ask channel —
    /// provenance pairing the standing widening with the member's original stated need.
    #[serde(default)]
    pub request_id: Option<String>,
}

impl StandingGrant {
    pub fn is_live(&self, now: u64) -> bool {
        self.expires_at.is_none_or(|e| now < e)
    }
}

/// The whole durable store, serialised as one vault document (`scope`/`standing`).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct StandingScopeStore {
    /// Monotonic, incremented on EVERY mutation (grant and revoke alike). This is the
    /// counter the certified-replica honor logic requires: it answers "WHICH policy is
    /// this copy", so two snapshots can be ordered and a stale one refused.
    #[serde(default)]
    pub generation: u64,
    #[serde(default)]
    pub grants: Vec<StandingGrant>,
}

impl StandingScopeStore {
    /// Every live standing grant this member holds, oldest first. Expired grants are
    /// filtered HERE, at the read, so no serving surface can leak one by forgetting to.
    pub fn live_for(&self, member: &str, now: u64) -> Vec<&StandingGrant> {
        let mut live: Vec<&StandingGrant> = self
            .grants
            .iter()
            .filter(|g| g.member == member && g.is_live(now))
            .collect();
        live.sort_by_key(|g| g.granted_at);
        live
    }

    /// Exact-path membership, same comparison discipline as `has_scope_grant`: a grant is
    /// for one path, and prefix matching would silently widen what the operator read.
    pub fn has_live(&self, member: &str, path: &str, now: u64) -> bool {
        self.grants
            .iter()
            .any(|g| g.member == member && g.path == path && g.is_live(now))
    }

    /// Add (or replace, keyed by `(member, path)`) a grant. Replacement rather than
    /// duplication, because two records for one path would make "revoked" ambiguous —
    /// and the superseded grant's history lives in the witness chain, not here.
    pub fn add(&mut self, grant: StandingGrant) {
        self.grants
            .retain(|g| !(g.member == grant.member && g.path == grant.path));
        self.grants.push(grant);
        self.generation += 1;
    }

    /// Remove a grant. Returns whether anything was removed; the generation moves only
    /// when the store actually changed, so the counter never claims a mutation that did
    /// not happen.
    pub fn revoke(&mut self, member: &str, path: &str) -> bool {
        let before = self.grants.len();
        self.grants
            .retain(|g| !(g.member == member && g.path == path));
        let removed = self.grants.len() != before;
        if removed {
            self.generation += 1;
        }
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vault::Vault;
    use tempfile::TempDir;

    fn grant(member: &str, path: &str, at: u64, expires_at: Option<u64>) -> StandingGrant {
        StandingGrant {
            member: member.into(),
            path: path.into(),
            granted_at: at,
            granted_by: "operator".into(),
            reason: "test".into(),
            expires_at,
            request_id: None,
        }
    }

    /// (c) The counter is monotonic across every mutation — grant, replace, revoke — and
    /// does NOT move on a no-op revoke. A generation that moved without a mutation would
    /// let a stale replica pass as current; one that failed to move on a mutation would
    /// let a revoked policy keep certifying itself.
    #[test]
    fn generation_increments_on_every_mutation_and_only_mutations() {
        let mut s = StandingScopeStore::default();
        assert_eq!(s.generation, 0);
        s.add(grant("kimi-code", "/w/web4", 1, None));
        assert_eq!(s.generation, 1);
        s.add(grant("kimi-code", "/w/hestia", 2, None));
        assert_eq!(s.generation, 2);
        // Replacement of the same (member, path) is a mutation: the policy changed.
        s.add(grant("kimi-code", "/w/web4", 3, Some(100)));
        assert_eq!(s.generation, 3);
        assert_eq!(s.grants.len(), 2, "replace, never duplicate");
        assert!(s.revoke("kimi-code", "/w/web4"));
        assert_eq!(s.generation, 4);
        // A revoke that removed nothing is not a mutation and must not claim one.
        assert!(!s.revoke("kimi-code", "/nowhere"));
        assert_eq!(s.generation, 4);
    }

    /// (d) An expired standing grant is never served — filtered at the read, so every
    /// serving surface inherits the filter instead of re-implementing it.
    #[test]
    fn expired_standing_grant_is_not_served() {
        let mut s = StandingScopeStore::default();
        s.add(grant("codex", "/w/web4", 1, Some(100)));
        s.add(grant("codex", "/w/hestia", 2, None));
        let live = s.live_for("codex", 99);
        assert_eq!(live.len(), 2, "before expiry both serve");
        let live = s.live_for("codex", 100);
        assert_eq!(live.len(), 1, "at expiry the bounded grant is gone");
        assert_eq!(live[0].path, "/w/hestia");
        assert!(!s.has_live("codex", "/w/web4", 100));
        assert!(s.has_live("codex", "/w/hestia", 100));
        // Another member's grants are never mixed in.
        assert!(s.live_for("kimi-code", 99).is_empty());
    }

    /// (a) THE POINT OF THE WHOLE STORE: a standing grant survives a daemon restart.
    /// Simulated the way a restart actually replays it — the store is saved as a vault
    /// document, the vault is dropped, reopened from disk with the passphrase, and the
    /// store loaded back. Grant, expiry, reason, and the generation all survive.
    #[test]
    fn standing_grant_persists_across_store_reload() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        let mut vault = Vault::init(path.clone(), "p".into()).unwrap();

        let mut store = StandingScopeStore::default();
        store.add(grant("kimi-code", "/w/web4", 42, None));
        store.add(grant("kimi-code", "/w/private", 43, Some(9_999_999_999)));
        store.revoke("kimi-code", "/w/private");
        assert_eq!(store.generation, 3);
        crate::vault::save_doc(&mut vault, "scope", "standing", "standing-scope.json", &store)
            .unwrap();
        drop(store);
        drop(vault);

        // "Restart": nothing in memory, everything from disk.
        let vault = Vault::open(path, "p".into()).unwrap();
        let reloaded: StandingScopeStore =
            crate::vault::load_doc(&vault, "scope", "standing", "standing-scope.json").unwrap();
        assert_eq!(
            reloaded.generation, 3,
            "the generation is part of the policy and must survive with it"
        );
        assert_eq!(reloaded.grants.len(), 1);
        assert_eq!(reloaded.grants[0].path, "/w/web4");
        assert_eq!(reloaded.grants[0].granted_at, 42);
        assert_eq!(reloaded.grants[0].expires_at, None);
        assert!(reloaded.has_live("kimi-code", "/w/web4", u64::MAX - 1));
    }

    /// An older install's plaintext `standing-scope.json` (the shape this PR's brief
    /// named) is migrated INTO the vault by `load_doc`'s legacy path rather than left as
    /// an editable sidecar — #133's lesson: authority must not live in a file a
    /// `json.dump` can widen.
    #[test]
    fn legacy_plaintext_sidecar_is_readable_then_retired_by_save() {
        let dir = TempDir::new().unwrap();
        let vpath = dir.path().join("vault.enc");
        let mut vault = Vault::init(vpath, "p".into()).unwrap();
        let legacy = dir.path().join("standing-scope.json");
        std::fs::write(
            &legacy,
            serde_json::to_vec(&StandingScopeStore {
                generation: 7,
                grants: vec![grant("codex", "/w/web4", 1, None)],
            })
            .unwrap(),
        )
        .unwrap();

        let loaded: StandingScopeStore =
            crate::vault::load_doc(&vault, "scope", "standing", "standing-scope.json").unwrap();
        assert_eq!(loaded.generation, 7);
        assert_eq!(loaded.grants.len(), 1);

        // First save migrates: the vault holds it, the sidecar is removed.
        crate::vault::save_doc(&mut vault, "scope", "standing", "standing-scope.json", &loaded)
            .unwrap();
        assert!(!legacy.exists(), "the plaintext sidecar must be retired");
    }
}
