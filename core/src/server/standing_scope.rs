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
use sha2::{Digest, Sha256};

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

/// How often the runtime projection is re-proved against the vault authority. Short enough
/// that drift is caught inside one working session, long enough that it costs nothing: the
/// check is one vault read and two digests.
pub const PROJECTION_VERIFY_INTERVAL_SECS: u64 = 900;

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
    /// Whether this grant covers the whole SUBTREE under `path`, or exactly `path`.
    ///
    /// EXACT IS THE DEFAULT, on dp's word (2026-09-08): "the exact path is useful, and is
    /// preferred as default. recursive should be an option." Every grant written before
    /// this field existed deserialises as exact, so nothing an operator already read
    /// silently widens. Recursion is a separate, explicit, witnessed act — the operator
    /// reads the word "recursive" and chooses it — which is what makes it safe to have
    /// at all: the concern in `has_live` was never subtrees, it was UNREAD widening.
    #[serde(default)]
    pub recursive: bool,
}

impl StandingGrant {
    pub fn is_live(&self, now: u64) -> bool {
        self.expires_at.is_none_or(|e| now < e)
    }

    /// Does this grant reach `path`? Exact match always; the subtree only when `recursive`.
    /// Containment is at the separator, so `/a/b` never covers `/a/bc`.
    pub fn covers(&self, path: &str) -> bool {
        covers_path(&self.path, self.recursive, path)
    }
}

/// The ONE containment rule for both grant channels (live and standing) — so the daemon
/// never answers "already granted" for a path the other channel would not have covered.
pub fn covers_path(root: &str, recursive: bool, path: &str) -> bool {
    if root == path {
        return true;
    }
    if !recursive {
        return false;
    }
    let root = root.trim_end_matches('/');
    path.starts_with(root) && path[root.len()..].starts_with('/')
}

/// The whole durable store, serialised as one vault document (`scope`/`standing`).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct StandingScopeStore {
    /// Monotonic, incremented on EVERY mutation (grant and revoke alike). This is the
    /// counter the certified-replica honor logic requires: it answers "WHICH policy is
    /// this copy", so two snapshots can be ordered and a stale one refused.
    ///
    /// Covers the FLOOR as well as the per-member grants: both live in this document, so a
    /// floor edit moves the same counter and a replica cannot be current for one and stale
    /// for the other.
    #[serde(default)]
    pub generation: u64,
    #[serde(default)]
    pub grants: Vec<StandingGrant>,
    /// THE SOCIETY FLOOR — paths every member of this society may reach, without any of them
    /// having asked.
    ///
    /// dp, 2026-08-16: *"ideally, we would have society grants. not hardcoded, but specific to
    /// cbp machine"*, and then the reason: *"law has to be applied uniformly to ALL. that is
    /// the only way the law is trusted."*
    ///
    /// **Not hardcoded, by construction.** It lives in THIS instance's vault beside the
    /// per-member grants, so it is per-machine because the vault is, and editing it is an
    /// operator act rather than a release. Nothing in the binary names a path.
    ///
    /// **Additive only** — `effective(m) = floor ∪ member(m)` (`PRD_ALLOWLISTS` AC-1). The
    /// floor is a written MINIMUM, never a ceiling and never a subtraction: a member's own
    /// grants can only widen what the floor already allows. That direction is what makes it
    /// safe to apply to everyone at once — no member can be made *worse* off by a floor edit
    /// than by having no floor at all.
    ///
    /// **Why a floor rather than granting each member the same list**: uniformity has to be
    /// structural or it decays. Per-member copies of one list drift the moment somebody is
    /// granted a path the others were not, and then the law differs per seat while looking
    /// identical. One list, consulted for everyone, cannot drift.
    #[serde(default)]
    pub floor: Vec<FloorEntry>,
}

/// What the daemon found where the standing authority should be, at launch.
///
/// The distinction exists because an absent vault document means two opposite things, and
/// treating them alike is the #596 outage: a fresh install correctly has no grants, while a
/// society that predates the feature has grants it is entitled to and no record of them.
/// Serving this beside the envelope makes the second case visible instead of silent.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityStatus {
    /// The vault held a standing document; the envelope is whatever it says.
    Loaded,
    /// No document and no history. Empty is correct here.
    Fresh,
    /// No document, but this society has acted. Empty is NOT correct, and nothing in the
    /// binary can invent the operator's intent, so the daemon reports rather than guesses.
    MigrationRequired,
}

impl AuthorityStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            AuthorityStatus::Loaded => "loaded",
            AuthorityStatus::Fresh => "fresh",
            AuthorityStatus::MigrationRequired => "migration_required",
        }
    }
}

/// One periodic proof that the runtime projection still equals the vault's authority.
///
/// dp's ruling, 2026-08-29: "on a clock, compare vault truth to every published/runtime
/// projection, report a freshness timestamp and exact divergence ... Silence is not health."
/// So this carries a timestamp even when it matches, because a verifier that only speaks up
/// on failure is indistinguishable from one that stopped running.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ProjectionAudit {
    pub verified_at: u64,
    pub matches: bool,
    pub runtime_generation: u64,
    pub vault_generation: u64,
    pub runtime_digest: String,
    pub vault_digest: String,
    /// Empty when `matches`. Each entry names one difference and its direction.
    pub divergence: Vec<String>,
}

/// Why `reassign` moved nothing. Each is a distinct answer the caller must give the
/// operator, and none of them moves the generation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReassignRefused {
    /// No grant of record for `(from, path)`.
    NoSuchGrant,
    /// `from == to`: a no-op is not a mutation.
    SameMember,
    /// The destination already holds that path; which reach wins is the operator's call.
    DestinationHoldsPath,
}

/// One floor path: every member may reach this, because the society says so.
///
/// It carries its own provenance for the same reason a standing grant does — a widening whose
/// rationale is not recorded is indistinguishable afterwards from a misconfiguration, and this
/// one is wider than any single grant because it binds every seat at once.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FloorEntry {
    /// Normalised absolute path (see `state::normalize_scope_path`).
    pub path: String,
    pub added_at: u64,
    #[serde(default)]
    pub added_by: String,
    #[serde(default)]
    pub reason: String,
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

    /// Membership by the grant's OWN rule: exact for an exact grant, subtree for a grant an
    /// operator explicitly made recursive. This used to be exact-only, with the comment
    /// "prefix matching would silently widen what the operator read" — still true, and
    /// still honoured: a recursive grant is one the operator read as recursive.
    pub fn has_live(&self, member: &str, path: &str, now: u64) -> bool {
        // THE UNION, and the floor is checked FIRST because it is the common case and
        // because it is member-independent: if the society allows this path, no per-member
        // lookup can change the answer. `effective(m) = floor ∪ member(m)` (AC-1).
        self.floor_allows(path)
            || self
                .grants
                .iter()
                .any(|g| g.member == member && g.is_live(now) && g.covers(path))
    }

    /// Does the society floor admit this path, for anyone?
    ///
    /// No expiry and no member: the floor is what this society has decided its members may
    /// reach, full stop. A path that should lapse is a per-member grant, not a floor entry —
    /// keeping the floor unconditional is what lets a reader answer "may members reach X"
    /// without knowing who is asking or what time it is.
    pub fn floor_allows(&self, path: &str) -> bool {
        self.floor.iter().any(|f| f.path == path)
    }

    /// A canonical digest of the EFFECTIVE society-wide path set.
    ///
    /// Provenance and insertion order are deliberately excluded: this answers whether two
    /// members received the same enforcing floor, while `generation` answers which complete
    /// policy revision they received. Length-prefixing prevents concatenation ambiguity.
    pub fn floor_digest(&self) -> String {
        let mut paths: Vec<&str> = self.floor.iter().map(|f| f.path.as_str()).collect();
        paths.sort_unstable();
        let mut hasher = Sha256::new();
        for path in paths {
            hasher.update((path.len() as u64).to_be_bytes());
            hasher.update(path.as_bytes());
        }
        hex::encode(hasher.finalize())
    }

    /// The reach-bearing row for one grant, shared by the digest and the divergence report.
    ///
    /// THIS EXISTS SO THE TWO CANNOT DISAGREE (GPT re-review of #728). They each derived
    /// their own before: the digest hashed member, path, granted_at and expires_at, while
    /// the report keyed only on member and path. A grant whose expiry changed therefore
    /// moved the digest while the report stayed silent, breaking the "exact divergence"
    /// contract on the one field that changes authority over time. Anything the digest can
    /// distinguish, the report must be able to name.
    fn grant_row(g: &StandingGrant) -> String {
        format!(
            "grant\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}",
            g.member,
            g.path,
            g.granted_at,
            g.expires_at.map(|e| e.to_string()).unwrap_or_default()
        )
    }

    /// A canonical digest of the ENTIRE authority: floor plus every per-member grant, with
    /// the fields that decide reach. `floor_digest` answers "did two members get the same
    /// society baseline"; this answers "is this projection byte-equivalent to the vault's",
    /// which is the question periodic verification asks. Order-independent and
    /// length-prefixed for the same reasons.
    pub fn authority_digest(&self) -> String {
        let mut rows: Vec<String> = self
            .floor
            .iter()
            .map(|f| format!("floor\u{1f}{}", f.path))
            .chain(self.grants.iter().map(Self::grant_row))
            .collect();
        rows.sort_unstable();
        let mut hasher = Sha256::new();
        hasher.update((self.generation).to_be_bytes());
        for row in rows {
            hasher.update((row.len() as u64).to_be_bytes());
            hasher.update(row.as_bytes());
        }
        hex::encode(hasher.finalize())
    }

    /// Name every way `self` (the runtime projection) differs from `vault` (the authority).
    ///
    /// Direction matters and is not symmetric in meaning: an entry the runtime holds and the
    /// vault does not is a PHANTOM grant, reach nothing durable backs, and it is the failure
    /// mode dp's 2026-08-29 ruling names last ("revoked/absent vault grants must never be
    /// recreated from stale projections"). An entry the vault holds and the runtime does not
    /// is a LOST grant: the operator's decision is not in force. Both are reported, labelled,
    /// and neither is silently repaired here; this function only tells the truth about the
    /// difference.
    pub fn divergence_from(&self, vault: &StandingScopeStore) -> Vec<String> {
        let mut out = Vec::new();
        if self.generation != vault.generation {
            out.push(format!(
                "generation: runtime {} vs vault {}",
                self.generation, vault.generation
            ));
        }
        // Identity is (member, path): that is what "the same grant" means to an operator.
        // Every other field is a property OF that grant, and one that moved is neither a
        // phantom nor a loss but a rewrite, which needs its own name or a reader concludes
        // the grant was untouched.
        fn ident(g: &StandingGrant) -> (&str, &str) {
            (g.member.as_str(), g.path.as_str())
        }
        let runtime_by_ident: std::collections::BTreeMap<(&str, &str), &StandingGrant> =
            self.grants.iter().map(|g| (ident(g), g)).collect();
        let vault_by_ident: std::collections::BTreeMap<(&str, &str), &StandingGrant> =
            vault.grants.iter().map(|g| (ident(g), g)).collect();

        for (k, g) in &runtime_by_ident {
            match vault_by_ident.get(k) {
                None => out.push(format!(
                    "PHANTOM grant in runtime, absent from vault: {} -> {}",
                    k.0, k.1
                )),
                Some(v) => {
                    // REACH OVER TIME. An expiry the vault never authorised is a widening
                    // when it is later and a silent narrowing when it is earlier. Both are
                    // drift, and this is the field the re-review caught the report missing.
                    if g.expires_at != v.expires_at {
                        let show = |e: Option<u64>| {
                            e.map(|x| x.to_string()).unwrap_or_else(|| "never".to_string())
                        };
                        out.push(format!(
                            "CHANGED grant {} -> {}: expires_at runtime {} vs vault {}",
                            k.0,
                            k.1,
                            show(g.expires_at),
                            show(v.expires_at)
                        ));
                    }
                    // PROVENANCE. Not reach, but a rewritten origin means this is not the
                    // record the operator's act produced, and the digest already sees it.
                    if g.granted_at != v.granted_at {
                        out.push(format!(
                            "CHANGED grant {} -> {}: granted_at runtime {} vs vault {}",
                            k.0, k.1, g.granted_at, v.granted_at
                        ));
                    }
                }
            }
        }
        for k in vault_by_ident.keys() {
            if !runtime_by_ident.contains_key(k) {
                out.push(format!(
                    "LOST grant in vault, absent from runtime: {} -> {}",
                    k.0, k.1
                ));
            }
        }
        let runtime_floor: std::collections::BTreeSet<&str> =
            self.floor.iter().map(|f| f.path.as_str()).collect();
        let vault_floor: std::collections::BTreeSet<&str> =
            vault.floor.iter().map(|f| f.path.as_str()).collect();
        for phantom in runtime_floor.difference(&vault_floor) {
            out.push(format!("PHANTOM floor path in runtime: {phantom}"));
        }
        for lost in vault_floor.difference(&runtime_floor) {
            out.push(format!("LOST floor path, in vault only: {lost}"));
        }
        out
    }

    /// Add (or replace, keyed by path) a floor entry. Same replace-not-duplicate rule as
    /// `add`, for the same reason: two records for one path make "removed" ambiguous.
    pub fn floor_add(&mut self, entry: FloorEntry) {
        self.floor.retain(|f| f.path != entry.path);
        self.floor.push(entry);
        self.generation += 1;
    }

    /// Remove a floor path. Returns whether anything was removed; the generation moves only
    /// on a real change, so the counter never claims a mutation that did not happen.
    ///
    /// THIS IS THE ONE TIGHTENING ON THIS SURFACE, and it is society-wide: removing a floor
    /// path narrows every member at once, including any that never asked for it and are
    /// mid-act against it. That is the opposite direction from `floor_add` and deserves the
    /// same ceremony a revoke gets, not less.
    pub fn floor_remove(&mut self, path: &str) -> bool {
        let before = self.floor.len();
        self.floor.retain(|f| f.path != path);
        let removed = self.floor.len() != before;
        if removed {
            self.generation += 1;
        }
        removed
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

    /// Flip a grant's reach between exact and subtree. Returns whether a grant of record
    /// existed AND changed; the generation moves only on a real change, so `law_hash` moves
    /// exactly when what a member may reach moved.
    pub fn set_recursive(&mut self, member: &str, path: &str, recursive: bool) -> bool {
        let mut changed = false;
        for g in self.grants.iter_mut() {
            if g.member == member && g.path == path && g.recursive != recursive {
                g.recursive = recursive;
                changed = true;
            }
        }
        if changed {
            self.generation += 1;
        }
        changed
    }

    /// Move one grant to another member, as ONE mutation: the source row is removed and a
    /// destination row with the same `(path, recursive, expires_at)` is added, and the
    /// generation moves once. The repair for a grant made against a mistyped member id.
    ///
    /// Why one mutation and not `add` + `revoke`: the two-step shape is what the dashboard
    /// first shipped (grant destination, promote recursive, revoke source — three durable
    /// writes) and it recreates the partial-transaction class #920/#987/#1001 rejected. An
    /// interruption leaves both grants present; a failed promotion leaves the destination
    /// with a narrower reach than the source it claims to carry unchanged. Here the store
    /// changes in one call under one lock, `commit_standing_scope` writes it once, and the
    /// reach shape cannot diverge because it is copied, not re-derived.
    ///
    /// Returns the grant that moved, or the reason nothing did. A self-reassign is a no-op
    /// and moves nothing, generation included. A destination that already holds the path is
    /// refused rather than merged: which reach wins is an operator's call, and the operator
    /// has `revoke` and `set_recursive` to make it explicitly.
    pub fn reassign(&mut self, from: &str, path: &str, to: &str, now: u64,
                    reason: &str) -> Result<StandingGrant, ReassignRefused> {
        if from == to {
            return Err(ReassignRefused::SameMember);
        }
        let Some(src) = self.grants.iter().find(|g| g.member == from && g.path == path).cloned()
        else {
            return Err(ReassignRefused::NoSuchGrant);
        };
        if self.grants.iter().any(|g| g.member == to && g.path == path) {
            return Err(ReassignRefused::DestinationHoldsPath);
        }
        let moved = StandingGrant {
            member: to.to_string(),
            path: src.path.clone(),
            granted_at: now,
            granted_by: "operator".into(),
            reason: reason.to_string(),
            expires_at: src.expires_at,
            request_id: None,
            recursive: src.recursive,
        };
        self.grants.retain(|g| !(g.member == from && g.path == path));
        self.grants.push(moved.clone());
        self.generation += 1;
        Ok(moved)
    }

    /// Rewrite every grant at or under `from` to sit under `to`, as ONE mutation.
    ///
    /// The repair for a workspace that moved. Before this, the only route was a revoke and a
    /// re-add per grant: 27 of each, typed by hand, with the member holding neither reach
    /// between the two calls of each pair, and each pair witnessing as two unrelated
    /// decisions — so a half-finished migration left an inconsistent scope set with nothing
    /// on the record saying it was half-finished. Here the whole rewrite is one store
    /// mutation, one commit, one generation step.
    ///
    /// `member` scopes the rewrite to one plugin id; `None` rewrites every member's matching
    /// grants. Returns `(member, old_path, new_path)` for each grant that MOVED, so the
    /// witness record can name every path rather than a count — "27 grants re-rooted" cannot
    /// be checked against anything afterwards.
    ///
    /// A grant whose new path equals its old one does not count as moved, so a re-root onto
    /// the same root is not a mutation and the generation does not step.
    pub fn reroot(&mut self, from: &str, to: &str, member: Option<&str>) -> Vec<(String, String, String)> {
        let mut moved = Vec::new();
        for g in self.grants.iter_mut() {
            if let Some(m) = member {
                if g.member != m {
                    continue;
                }
            }
            let Some(rest) = path_under(&g.path, from) else {
                continue;
            };
            let new_path = if rest.is_empty() {
                to.to_string()
            } else {
                format!("{}/{}", to.trim_end_matches('/'), rest)
            };
            if new_path == g.path {
                continue;
            }
            moved.push((g.member.clone(), g.path.clone(), new_path.clone()));
            g.path = new_path;
        }
        if !moved.is_empty() {
            self.generation += 1;
        }
        moved
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

/// Is `path` at or under `prefix`, judged at a SEGMENT BOUNDARY rather than by raw string
/// prefix?
///
/// A bare `starts_with` is wrong here in the direction that silently widens: with
/// `prefix = "/w/ai-agents"`, a raw prefix test also claims `/w/ai-agents-old/secrets`, and a
/// re-root built on it would rewrite grants belonging to a DIFFERENT tree and hand the member
/// a reach nobody granted. The boundary check is the whole safety of this operation.
///
/// Returns the remainder after the prefix (empty when `path == prefix`), or `None` when the
/// path is not under it.
fn path_under(path: &str, prefix: &str) -> Option<String> {
    let p = prefix.trim_end_matches('/');
    if path == p {
        return Some(String::new());
    }
    let with_sep = format!("{p}/");
    path.strip_prefix(&with_sep).map(|r| r.to_string())
}

#[cfg(test)]
mod reach_tests {
    use super::*;

    fn g(path: &str, recursive: bool) -> StandingGrant {
        StandingGrant {
            member: "m".into(), path: path.into(), granted_at: 1, granted_by: "op".into(),
            reason: "r".into(), expires_at: None, request_id: None, recursive,
        }
    }

    /// A store holding one grant per `(member, path)` pair given.
    fn store_with(paths: &[(&str, &str)]) -> StandingScopeStore {
        let mut st = StandingScopeStore::default();
        for (member, path) in paths {
            st.add(StandingGrant {
                member: (*member).into(), path: (*path).into(), granted_at: 1,
                granted_by: "op".into(), reason: "r".into(), expires_at: None,
                request_id: None, recursive: false,
            });
        }
        st
    }

    /// The workspace moved: every grant under the old root lands under the new one, and the
    /// generation steps ONCE for the whole rewrite rather than once per grant.
    #[test]
    fn reroot_moves_every_grant_under_the_old_root_in_one_generation() {
        let mut st = store_with(&[
            ("claude-code", "/old/ws"),
            ("claude-code", "/old/ws/repo-a"),
            ("codex", "/old/ws/repo-b/sub"),
            ("kimi-code", "/elsewhere/keep"),
        ]);
        let gen0 = st.generation;
        let moved = st.reroot("/old/ws", "/new/ws", None);
        assert_eq!(moved.len(), 3, "the three under the old root moved: {moved:?}");
        assert_eq!(st.generation, gen0 + 1, "one mutation, one generation step");
        let paths: Vec<&str> = st.grants.iter().map(|g| g.path.as_str()).collect();
        assert!(paths.contains(&"/new/ws"), "the root grant itself re-roots: {paths:?}");
        assert!(paths.contains(&"/new/ws/repo-a"), "{paths:?}");
        assert!(paths.contains(&"/new/ws/repo-b/sub"), "depth is preserved: {paths:?}");
        assert!(paths.contains(&"/elsewhere/keep"), "an unrelated grant is untouched: {paths:?}");
    }

    /// THE FALSIFIER FOR THE WHOLE OPERATION. With `starts_with`, re-rooting `/old/ws` also
    /// rewrites `/old/ws-archive/secrets` — a SIBLING tree — handing the member reach nobody
    /// granted, with the grant count unchanged and every path still plausible.
    #[test]
    fn reroot_does_not_touch_a_sibling_that_merely_shares_a_string_prefix() {
        let mut st = store_with(&[
            ("claude-code", "/old/ws"),
            ("claude-code", "/old/ws-archive/secrets"),
            ("claude-code", "/old/wsx"),
        ]);
        let moved = st.reroot("/old/ws", "/new/ws", None);
        assert_eq!(moved.len(), 1, "only the exact root moved: {moved:?}");
        let paths: Vec<&str> = st.grants.iter().map(|g| g.path.as_str()).collect();
        assert!(paths.contains(&"/old/ws-archive/secrets"), "sibling untouched: {paths:?}");
        assert!(paths.contains(&"/old/wsx"), "sibling untouched: {paths:?}");
    }

    /// Scoped to one member, the peers' matching grants stay where they are.
    #[test]
    fn reroot_scoped_to_one_member_leaves_peers_alone() {
        let mut st = store_with(&[
            ("claude-code", "/old/ws/a"),
            ("codex", "/old/ws/a"),
        ]);
        let moved = st.reroot("/old/ws", "/new/ws", Some("claude-code"));
        assert_eq!(moved.len(), 1, "{moved:?}");
        assert_eq!(moved[0].0, "claude-code");
        let codex = st.grants.iter().find(|g| g.member == "codex").unwrap();
        assert_eq!(codex.path, "/old/ws/a", "a peer's identical path is not swept up");
    }

    /// A re-root that matches nothing is NOT a mutation: no generation movement, so a
    /// mistyped prefix cannot report as a bland success that moved the law hash.
    #[test]
    fn reroot_that_matches_nothing_is_not_a_mutation() {
        let mut st = store_with(&[("claude-code", "/old/ws/a")]);
        let gen0 = st.generation;
        let moved = st.reroot("/nowhere", "/new/ws", None);
        assert!(moved.is_empty());
        assert_eq!(st.generation, gen0, "no match, no generation step");
    }

    /// Re-rooting onto the same root changes no path, so it is not a mutation either.
    #[test]
    fn reroot_onto_the_same_root_changes_nothing() {
        let mut st = store_with(&[("claude-code", "/old/ws/a")]);
        let gen0 = st.generation;
        let moved = st.reroot("/old/ws", "/old/ws", None);
        assert!(moved.is_empty(), "{moved:?}");
        assert_eq!(st.generation, gen0);
    }

    #[test]
    fn path_under_judges_at_a_segment_boundary() {
        assert_eq!(path_under("/a/b", "/a/b"), Some(String::new()));
        assert_eq!(path_under("/a/b/c", "/a/b"), Some("c".to_string()));
        assert_eq!(path_under("/a/b/c/d", "/a/b"), Some("c/d".to_string()));
        // A trailing slash on the prefix must not change the verdict.
        assert_eq!(path_under("/a/b/c", "/a/b/"), Some("c".to_string()));
        // The three a raw prefix test gets wrong.
        assert_eq!(path_under("/a/bc", "/a/b"), None);
        assert_eq!(path_under("/a/b-old/c", "/a/b"), None);
        assert_eq!(path_under("/a", "/a/b"), None);
    }

    /// EXACT IS THE DEFAULT (dp, 2026-09-08). A grant on /a reaches /a and nothing else
    /// unless an operator explicitly made it recursive; and even then, containment is at
    /// the separator so /a never fronts for /ab.
    #[test]
    fn exact_by_default_subtree_only_when_asked_never_a_sibling() {
        let exact = g("/w/tree", false);
        assert!(exact.covers("/w/tree"));
        assert!(!exact.covers("/w/tree/sub"), "exact must not reach the subtree");
        assert!(!exact.covers("/w"), "nor the parent");

        let rec = g("/w/tree", true);
        assert!(rec.covers("/w/tree"));
        assert!(rec.covers("/w/tree/sub/deep/file.py"));
        assert!(!rec.covers("/w/treeful"), "a recursive grant never covers a sibling with the same prefix");
        assert!(!rec.covers("/w"), "nor its parent");
        assert!(!rec.covers("/other"));
    }

    /// A grant written before `recursive` existed deserialises as EXACT — nothing an
    /// operator already read silently widens when the daemon upgrades.
    #[test]
    fn a_pre_existing_grant_deserialises_as_exact() {
        let old = r#"{"member":"m","path":"/w/tree","granted_at":1,"granted_by":"op","reason":"r"}"#;
        let grant: StandingGrant = serde_json::from_str(old).unwrap();
        assert!(!grant.recursive);
        assert!(!grant.covers("/w/tree/sub"));
    }

    /// The store's membership honours each grant's OWN rule, and flipping it is a real
    /// change: the generation (hence law_hash) moves, and a no-op flip does not move it.
    /// `reassign` is one mutation: the reach shape travels with the grant, the generation
    /// moves once, and every refusal leaves the store byte-identical.
    #[test]
    fn reassign_carries_the_reach_shape_in_one_mutation_and_refuses_cleanly() {
        let mut st = StandingScopeStore::default();
        st.add(g("/w/tree", true));                       // member "m", recursive
        st.grants[0].expires_at = Some(9_999_999_999);
        let gen0 = st.generation;
        let before = st.clone();

        // Refusals: nothing moves, generation included.
        assert_eq!(st.reassign("m", "/w/tree", "m", 5, "r"), Err(ReassignRefused::SameMember));
        assert_eq!(st.reassign("m", "/w/nope", "n", 5, "r"), Err(ReassignRefused::NoSuchGrant));
        assert_eq!(st.reassign("ghost", "/w/tree", "n", 5, "r"), Err(ReassignRefused::NoSuchGrant));
        assert_eq!(st.grants, before.grants, "a refusal is a pure read");
        assert_eq!(st.generation, gen0, "a refusal moves no generation");

        // The move: one row out, one row in, recursive and expiry copied, generation +1.
        let moved = st.reassign("m", "/w/tree", "n", 5, "typo repair").expect("moves");
        assert_eq!(moved.member, "n");
        assert!(moved.recursive, "a recursive source stays recursive at the destination");
        assert_eq!(moved.expires_at, Some(9_999_999_999), "expiry travels with the grant");
        assert_eq!(moved.reason, "typo repair");
        assert_eq!(st.generation, gen0 + 1, "one mutation, one generation step");
        assert_eq!(st.grants.len(), 1, "no residue on the source member");
        assert!(!st.has_live("m", "/w/tree/child", 5) && st.has_live("n", "/w/tree/child", 5));

        // The destination already holds the path: refused, not merged — even for an exact
        // source under a recursive destination.
        st.add(g("/w/tree", false));                      // member "m" again, exact
        let gen1 = st.generation;
        assert_eq!(st.reassign("m", "/w/tree", "n", 5, "r"), Err(ReassignRefused::DestinationHoldsPath));
        assert_eq!(st.generation, gen1);
        assert!(st.has_live("n", "/w/tree/child", 5), "the destination's reach is untouched");
    }

    #[test]
    fn set_recursive_moves_the_generation_only_on_a_real_change() {
        let mut st = StandingScopeStore::default();
        st.add(g("/w/tree", false));
        let gen0 = st.generation;
        assert!(!st.has_live("m", "/w/tree/x", 5));
        assert!(st.set_recursive("m", "/w/tree", true));
        assert_eq!(st.generation, gen0 + 1);
        assert!(st.has_live("m", "/w/tree/x", 5));
        assert!(!st.set_recursive("m", "/w/tree", true), "already recursive: no change");
        assert_eq!(st.generation, gen0 + 1, "and the generation did not move");
        assert!(!st.set_recursive("m", "/nope", true), "no grant of record: no change");
        assert!(st.set_recursive("m", "/w/tree", false));
        assert!(!st.has_live("m", "/w/tree/x", 5), "back to exact");
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
        recursive: false,
        }
    }

    fn floor(path: &str, at: u64) -> FloorEntry {
        FloorEntry {
            path: path.into(),
            added_at: at,
            added_by: "operator".into(),
            reason: "society baseline".into(),
        }
    }

    #[test]
    fn society_floor_is_one_additive_policy_for_every_member() {
        let mut s = StandingScopeStore::default();
        s.floor_add(floor("/w/shared", 1));
        s.add(grant("kimi-code", "/w/kimi-only", 2, None));

        assert!(s.has_live("kimi-code", "/w/shared", 3));
        assert!(s.has_live("codex", "/w/shared", 3));
        assert!(s.has_live("kimi-code", "/w/kimi-only", 3));
        assert!(!s.has_live("codex", "/w/kimi-only", 3));

        let digest = s.floor_digest();
        assert_eq!(digest.len(), 64);
        assert_ne!(digest, StandingScopeStore::default().floor_digest());

        s.floor_add(floor("/w/shared", 4));
        assert_eq!(s.floor.len(), 1, "replacement cannot fork one floor path");
        assert_eq!(s.generation, 3, "floor add, member add, floor replace");
        assert!(s.floor_remove("/w/shared"));
        assert!(!s.floor_remove("/w/shared"));
        assert_eq!(s.generation, 4, "a no-op removal is not a policy revision");
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
                floor: Vec::new(),
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
