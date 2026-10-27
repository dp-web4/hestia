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
    /// What the holder may DO at the path it reaches: read / write / execute / delete (#1345).
    ///
    /// ALL BY DEFAULT, for the same reason `recursive` defaults to exact: every grant written
    /// before this field existed was effectively rwed, so it loads as rwed and nothing an
    /// operator already read silently changes. An all-modes grant is also WRITTEN without the
    /// field, so the vault document of a society that never narrows a grant is byte-identical
    /// to what it was.
    #[serde(default, skip_serializing_if = "crate::server::grant_modes::is_all")]
    pub modes: crate::server::grant_modes::Modes,
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
    /// **The member's own grant first, the floor for the rest** (`PRD_ALLOWLISTS` AC-1, as
    /// amended 2026-10-23). Where a member's own grant reaches, its modes decide; the floor
    /// applies only where no grant of the member's does (`effective_modes`). dp: *"'floor'
    /// should not override the actual grants."* Before modes this was the union
    /// `floor ∪ member(m)`, and the two readings agreed, because every grant and every floor
    /// entry meant all modes. With modes a union would let one society-wide entry undo an
    /// operator's narrowing of one member's grant. A floor edit still never narrows a member
    /// below its own grants.
    ///
    /// **Why a floor rather than granting each member the same list**: uniformity has to be
    /// structural or it decays. Per-member copies of one list drift the moment somebody is
    /// granted a path the others were not, and then the law differs per seat while looking
    /// identical. One list, consulted for everyone, cannot drift.
    #[serde(default)]
    pub floor: Vec<FloorEntry>,
    /// STANDING REFUSALS (hestia#1417). A refusal used to live only as long as its request's
    /// window (8 h), so a member re-asking for one off-limits path minted a fresh request, and
    /// a fresh operator card, every window: measured 87 refused acts and 17 request ids for
    /// one `(member, path)` in three days. A refusal the operator (or a NOT-SAME peer) marks
    /// standing is durable like a grant: the gate's claim answers `refused` from this row and
    /// opens nothing, `request_scope` for the path is not filed, and the member reads the
    /// closed door in its own scope status. Lifted only by the operator; a later grant that
    /// covers the path answers before it and so lifts it in effect.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub refusals: Vec<StandingRefusal>,
}

/// One standing refusal (hestia#1417): the member's ASK for this path is refused, durably, until
/// the operator lifts it. It refuses the ask, not the reach (nomad on #1418): the gate's claim
/// and `request_scope` answer from it and open nothing, while a grant that covers the path
/// answers before it, and a STANDING grant that covers it lifts it explicitly (`add`). A refusal
/// as a node in the nearest-grant walk (#1386) is the follow-up. Never widens anything, so a
/// NOT-SAME peer may record one, with the reach of the request it was asked to rule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StandingRefusal {
    pub member: String,
    /// Normalised absolute path (`state::normalize_scope_path`).
    pub path: String,
    /// Whether the refusal covers the whole subtree under `path`.
    #[serde(default)]
    pub recursive: bool,
    pub refused_at: u64,
    /// `operator`, or `peer:<member>`.
    #[serde(default)]
    pub refused_by: String,
    /// Why — the deciding seat's words, served back to the member on every re-ask.
    #[serde(default)]
    pub reason: String,
    /// The request this refusal was decided on, for provenance.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    /// What the refused ASK was for (Nova on #1418): `r` when the gate opened it for a read-only
    /// tool, otherwise every mode. A standing grant lifts the refusal only when its modes include
    /// these, so a `w`-only grant over a refused read leaves the refusal standing (the read is
    /// still unauthorized, and the gate still answers it from the record instead of re-asking).
    /// Absent on rows written before this field: read as every mode, the conservative side.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub modes: Option<crate::server::grant_modes::Modes>,
}

impl StandingRefusal {
    pub fn covers(&self, path: &str) -> bool {
        covers_path(&self.path, self.recursive, path)
    }

    /// The modes the refused ask needed (every mode when unrecorded).
    pub fn asked_modes(&self) -> crate::server::grant_modes::Modes {
        self.modes.unwrap_or(crate::server::grant_modes::Modes::ALL)
    }

    /// Whether `grant` opens what this refusal closed: it covers the path AND its modes include
    /// the modes the ask needed. Only such a grant lifts the refusal.
    pub fn lifted_by(&self, grant: &StandingGrant) -> bool {
        grant.member == self.member && grant.covers(&self.path) && grant.modes.includes(self.asked_modes())
    }
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

/// The new shape of a grant in one `edit`: everything the dashboard's Edit row stages.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GrantEdit {
    /// Already normalised and validated by the caller (`state::normalize_scope_path`).
    pub path: String,
    pub recursive: bool,
    pub modes: crate::server::grant_modes::Modes,
}

impl GrantEdit {
    /// Would `after` let its holder reach or do anything `before` did not?
    ///
    /// Any one of: a mode added; exact made recursive; or a path no longer inside what the
    /// old grant covered. Narrowing on one axis never cancels widening on another, so this is
    /// an OR, and the operator is shown it before Save.
    pub fn widens(before: &StandingGrant, after: &StandingGrant) -> bool {
        after.modes.widens(before.modes) || Self::widens_reach(before, after)
    }

    /// Does `after` reach any path `before` did not? Modes aside.
    pub fn widens_reach(before: &StandingGrant, after: &StandingGrant) -> bool {
        if after.recursive {
            // a subtree is inside the old reach only when the old grant was a subtree that
            // contains it
            !(before.recursive && covers_path(&before.path, true, &after.path))
        } else {
            !before.covers(&after.path)
        }
    }
}

/// Why `edit` changed nothing. None of them moves the generation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EditRefused {
    /// The store moved since the editor read it.
    Moved { current: u64 },
    NoSuchGrant,
    /// The staged row equals the stored one: Save with nothing changed is not a mutation.
    NoChange,
    /// The member already holds the new path as a separate grant; merging them is the
    /// operator's explicit call (revoke one first).
    DestinationHoldsPath,
}

/// One floor path: every member may reach this, because the society says so.
///
/// It carries its own provenance for the same reason a standing grant does — a widening whose
/// rationale is not recorded is indistinguishable afterwards from a misconfiguration, and this
/// one is wider than any single grant because it binds every seat at once.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FloorEntry {
    /// Normalised absolute path (see `state::normalize_scope_path`).
    pub path: String,
    pub added_at: u64,
    #[serde(default)]
    pub added_by: String,
    #[serde(default)]
    pub reason: String,
    /// The subtree as well as the path itself, by the same `covers_path` rule a standing grant
    /// uses. Absent on entries written before this field existed, which read as exact — the
    /// narrower meaning, so no stored floor widens on upgrade.
    #[serde(default)]
    pub recursive: bool,
    /// What the entry lets a member DO there: the same r/w/e/d `Modes` a grant carries (#1345),
    /// so the floor and a member's grants speak one language. ALL BY DEFAULT and written
    /// without the field when all, so every floor entry stored before this existed loads and
    /// digests exactly as it did. dp's 2026-10-19 "the governed see the law" is one entry with
    /// modes `r` on the governance snapshot. (#1347's first cut had its own `access: all|read`;
    /// dp, 2026-10-23: "we want granularity and edit", one mode model for grants and floor.)
    #[serde(default, skip_serializing_if = "crate::server::grant_modes::is_all")]
    pub modes: crate::server::grant_modes::Modes,
}

impl FloorEntry {
    /// Does this entry reach `path`, by its own rule? Says nothing about mode.
    pub fn covers(&self, path: &str) -> bool {
        covers_path(&self.path, self.recursive, path)
    }

    /// The reach-bearing spelling, keyed by the digests and the divergence report.
    ///
    /// LEGACY (exact, all modes): exactly the path, so a floor written before
    /// `recursive`/`modes` existed digests byte-identically after the upgrade.
    ///
    /// ANY OTHER entry: `\x1f<len>:<path>\x1f<exact|recursive>\x1f<modes>`. It cannot collide
    /// with a legacy spelling, because an admitted floor path is absolute and starts with `/`,
    /// never `\x1f`; and two such spellings cannot collide with each other, because the length
    /// prefix fixes where the path ends whatever characters it contains. (The first cut
    /// appended ` (read)` to the path, which made read-only `/w/law` and an all-access path
    /// literally named `/w/law (read)` one string: Codex HOLD on #1347, P2.)
    pub fn spelling(&self) -> String {
        if !self.recursive && self.modes.is_all() {
            return self.path.clone();
        }
        format!(
            "\u{1f}{}:{}\u{1f}{}\u{1f}{}",
            self.path.len(),
            self.path,
            if self.recursive { "recursive" } else { "exact" },
            self.modes.as_letters()
        )
    }

    /// Do this entry and a grant on `path` (with `recursive`) reach any path in common?
    pub fn overlaps(&self, path: &str, recursive: bool) -> bool {
        self.covers(path) || covers_path(path, recursive, &self.path)
    }
}

/// Why one floor entry is not served to one member's mode-blind gate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FloorWithheld {
    pub path: String,
    pub why: String,
}

/// The floor as one member's gate may enforce it today (`StandingScopeStore::floor_for`).
#[derive(Debug, Clone, Default)]
pub struct FloorForMember<'a> {
    /// All-modes entries: served as reach (`society_floor`).
    pub reach: Vec<&'a FloorEntry>,
    /// Narrowed entries that include read: served for read acts only (`society_floor_read`).
    pub read: Vec<&'a FloorEntry>,
    /// Everything else, each with the reason, so nothing is silently dropped.
    pub withheld: Vec<FloorWithheld>,
}

impl StandingScopeStore {
    /// The standing refusal covering `path` for `member`, if any (hestia#1417). Exact match
    /// always; the subtree only when the refusal is recursive, the grants' own rule.
    pub fn refusal_for(&self, member: &str, path: &str) -> Option<&StandingRefusal> {
        self.refusals.iter().find(|r| r.member == member && r.covers(path))
    }

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
        self.has_live_for(member, path, now, crate::server::grant_modes::Modes::ALL)
    }

    /// `has_live`, counting only grants that include every mode in `needed` (#1345).
    ///
    /// `has_live` asks for ALL modes, and that is the safe reading for every caller that does
    /// not know what the act will do: "a grant covers this path" used to mean "the member may
    /// do anything there", and a read-only grant must never answer that question yes.
    pub fn has_live_for(&self, member: &str, path: &str, now: u64,
                        needed: crate::server::grant_modes::Modes) -> bool {
        self.effective_modes(member, path, now).is_some_and(|m| m.includes(needed))
    }

    /// What `member` may do at `path`, or None for nothing.
    ///
    /// THE MEMBER'S OWN GRANTS DECIDE WHERE THEY REACH; THE FLOOR FILLS ONLY WHAT THEY DO NOT
    /// (dp, 2026-10-23: "'floor' should not override the actual grants"). This replaces the
    /// union `effective(m) = floor ∪ member(m)` (AC-1), which was the same thing while every
    /// grant and every floor entry meant "all modes": with modes, a union would let an
    /// all-modes floor entry silently undo an operator's narrowing of one member's grant.
    /// Several of the member's grants covering one path add up (their union); several floor
    /// entries covering it add up the same way. Expired grants never count.
    pub fn effective_modes(&self, member: &str, path: &str, now: u64)
                           -> Option<crate::server::grant_modes::Modes> {
        let own = self
            .grants
            .iter()
            .filter(|g| g.member == member && g.is_live(now) && g.covers(path))
            .map(|g| g.modes)
            .reduce(|a, b| a.union(b));
        own.or_else(|| {
            self.floor
                .iter()
                .filter(|f| f.covers(path))
                .map(|f| f.modes)
                .reduce(|a, b| a.union(b))
        })
    }

    /// Does an ALL-MODES society floor entry reach this path, for anyone?
    ///
    /// No expiry and no member: the floor is what this society has decided its members may
    /// reach, full stop. A path that should lapse is a per-member grant, not a floor entry —
    /// keeping the floor unconditional is what lets a reader answer "may members reach X"
    /// without knowing who is asking or what time it is. A narrowed entry does not answer
    /// "is X granted" (for an act of unknown mode, that question means all modes); whether
    /// a given member may use any entry is `effective_modes`.
    pub fn floor_allows(&self, path: &str) -> bool {
        self.floor.iter().any(|f| f.modes.is_all() && f.covers(path))
    }

    /// The floor as ONE member's mode-blind gate may enforce it, given that member's
    /// NARROWED grants as `(path, recursive)` (live and standing; the caller collects both).
    ///
    /// The gate unions `society_floor` with the member's grants, so an all-modes floor entry
    /// overlapping a narrowed grant would undo the narrowing there: it is WITHHELD for that
    /// member, and named. Fail closed: the member loses the floor's reach over that entry's
    /// whole span, not just the overlap.
    ///
    /// THIS OUTLIVES MODE ENFORCEMENT (#1385). A gate that enforces modes (#1345 part B)
    /// admits a narrowed grant by its own modes, but it still unions `society_floor` with the
    /// member's grants: re-serving the entry would widen the narrowed grant back to all
    /// modes in its subtree. The entry may be served again only once the gate itself caps the
    /// floor by the member's own grants, path by path (dp 2026-10-24, #1386: the nearest
    /// explicit grant decides; the floor applies only where no own grant reaches), and that
    /// change needs its own review. A narrowed entry with read goes to
    /// `read` (admitted for read acts only), unless a narrowed grant overlapping it lacks
    /// read. Every other entry is withheld with its reason.
    pub fn floor_for<'a>(&'a self, narrowed: &[(String, bool, crate::server::grant_modes::Modes)])
                         -> FloorForMember<'a> {
        use crate::server::grant_modes::Mode;
        let mut out = FloorForMember::default();
        for f in &self.floor {
            let clash = narrowed.iter().find(|(p, rec, m)| {
                f.overlaps(p, *rec) && (f.modes.is_all() || !m.contains(Mode::Read))
            });
            if let Some((p, _, m)) = clash {
                out.withheld.push(FloorWithheld {
                    path: f.path.clone(),
                    why: format!("your own grant on {p} allows only {m} there, and the floor does \
                                  not override a member's grant; withheld until your gate caps \
                                  the floor by your own grants (hestia #1386)"),
                });
            } else if f.modes.is_all() {
                out.reach.push(f);
            } else if f.modes.contains(Mode::Read) {
                out.read.push(f);
            } else {
                out.withheld.push(FloorWithheld {
                    path: f.path.clone(),
                    why: format!("this floor entry allows {} without read; a mode-blind gate \
                                  cannot enforce that, so it waits for one that can", f.modes),
                });
            }
        }
        out
    }

    /// A canonical digest of the EFFECTIVE society-wide path set.
    ///
    /// Provenance and insertion order are deliberately excluded: this answers whether two
    /// members received the same enforcing floor, while `generation` answers which complete
    /// policy revision they received. Length-prefixing prevents concatenation ambiguity.
    pub fn floor_digest(&self) -> String {
        // Keyed on the reach-bearing spelling, so a floor that differs only in recursion or
        // access digests differently. An entry with neither spells its bare path, so a floor
        // written before those fields digests exactly as it did.
        let mut paths: Vec<String> = self.floor.iter().map(FloorEntry::spelling).collect();
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
        let row = format!(
            "grant\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}",
            g.member,
            g.path,
            g.granted_at,
            g.expires_at.map(|e| e.to_string()).unwrap_or_default()
        );
        // MODES ARE AUTHORITY (#1345), so the digest must see a narrowed grant. An all-modes
        // grant keeps its pre-#1345 row exactly, so no existing digest moves on upgrade.
        if g.modes.is_all() {
            row
        } else {
            format!("{row}\u{1f}modes={}", g.modes)
        }
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
            .map(|f| format!("floor\u{1f}{}", f.spelling()))
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
                    // WHAT IT MAY DO. A mode the vault never authorised is a widening; a
                    // missing one is a silent narrowing. Either is drift (#1345).
                    if g.modes != v.modes {
                        out.push(format!(
                            "CHANGED grant {} -> {}: modes runtime {} vs vault {}",
                            k.0, k.1, g.modes, v.modes
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
        let runtime_floor: std::collections::BTreeSet<String> =
            self.floor.iter().map(FloorEntry::spelling).collect();
        let vault_floor: std::collections::BTreeSet<String> =
            vault.floor.iter().map(FloorEntry::spelling).collect();
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
    /// The standing refusals that `grant` lifts: the member's, covered by the grant, in the modes
    /// the ask needed (nomad on #1418: the record must not say "closed" while the door is open;
    /// Nova: a `w`-only grant opens no read, so it lifts no refused read).
    pub fn refusals_lifted_by(&self, grant: &StandingGrant) -> Vec<StandingRefusal> {
        self.refusals.iter().filter(|r| r.lifted_by(grant)).cloned().collect()
    }

    pub fn add(&mut self, grant: StandingGrant) {
        // A standing grant that OPENS what a standing refusal closed (path AND modes) LIFTS it in
        // the same act, so the store never says closed where a grant has opened the door.
        // `commit_standing_scope` witnesses each lifted row (`scope_refusal_lifted`, by: grant)
        // after the commit lands. A narrower grant (w-only over a refused read) lifts nothing.
        self.refusals.retain(|r| !r.lifted_by(&grant));
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
    /// destination row with the same `(path, recursive, modes, expires_at)` is added, and the
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
            // Copied with the reach: a reassign moves a grant, it never re-decides one.
            modes: src.modes,
        };
        self.grants.retain(|g| !(g.member == from && g.path == path));
        self.grants.push(moved.clone());
        self.generation += 1;
        Ok(moved)
    }

    /// Edit one grant's path, reach and modes, as ONE mutation (dp, 2026-10-22, #1345).
    ///
    /// The dashboard's Edit workflow stages all three and saves once, so the store must change
    /// all three at once: a path edit done as revoke + add is the partial-transaction class
    /// `reassign` already rejects (an interruption leaves both grants live, or neither), and a
    /// path edit done as a second grant leaves the OLD path reachable, which dp's contract
    /// names directly: "must not ... leave both old and new grants active".
    ///
    /// The row is rewritten IN PLACE, so its provenance (granted_at, granted_by, reason,
    /// request_id, expires_at) is the original grant's. The edit's own operator, reason and
    /// before→after are the witness record's job, which is where every other mutation's
    /// history lives.
    ///
    /// `expected_generation` is the store generation the editor SAW: if anything moved since,
    /// the edit is refused, because the before→after summary the operator approved was
    /// computed against a store that no longer exists.
    pub fn edit(&mut self, member: &str, path: &str, expected_generation: u64,
                change: GrantEdit) -> Result<(StandingGrant, StandingGrant), EditRefused> {
        if self.generation != expected_generation {
            return Err(EditRefused::Moved { current: self.generation });
        }
        let Some(idx) = self.grants.iter().position(|g| g.member == member && g.path == path)
        else {
            return Err(EditRefused::NoSuchGrant);
        };
        let before = self.grants[idx].clone();
        let mut after = before.clone();
        after.path = change.path;
        after.recursive = change.recursive;
        after.modes = change.modes;
        if after == before {
            return Err(EditRefused::NoChange);
        }
        if after.path != before.path
            && self.grants.iter().any(|g| g.member == member && g.path == after.path)
        {
            return Err(EditRefused::DestinationHoldsPath);
        }
        self.grants[idx] = after.clone();
        self.generation += 1;
        Ok((before, after))
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
            modes: crate::server::grant_modes::Modes::ALL,
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
                modes: crate::server::grant_modes::Modes::ALL,
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
        modes: crate::server::grant_modes::Modes::ALL,
        }
    }

    fn floor(path: &str, at: u64) -> FloorEntry {
        FloorEntry {
            path: path.into(),
            added_at: at,
            added_by: "operator".into(),
            reason: "society baseline".into(),
            ..Default::default()
        }
    }

    fn modes(s: &str) -> crate::server::grant_modes::Modes {
        crate::server::grant_modes::Modes::parse(s).unwrap()
    }

    /// dp, 2026-10-19: every member may READ the governance snapshot. A read-only floor entry
    /// is not reach: `floor_allows` (the "is X granted" question, all modes) must not answer
    /// yes for it, and neither may `has_live`; a READ question may.
    #[test]
    fn a_read_only_floor_entry_answers_reads_and_nothing_more() {
        let mut s = StandingScopeStore::default();
        s.floor_add(FloorEntry { recursive: true, modes: modes("r"),
                                 ..floor("/w/governance/hestia", 1) });
        let file = "/w/governance/hestia/core/src/lib.rs";
        assert!(!s.floor_allows("/w/governance/hestia"));
        assert!(!s.floor_allows(file));
        assert!(!s.has_live("anyone", file, 2));
        assert!(s.has_live_for("anyone", file, 2, modes("r")));
        assert!(!s.has_live_for("anyone", file, 2, modes("w")));
        assert_eq!(s.effective_modes("anyone", file, 2), Some(modes("r")));
    }

    /// dp, 2026-10-23: "'floor' should not override the actual grants." Where a member's own
    /// grant reaches, it decides, in BOTH directions: an all-modes floor entry does not widen a
    /// member's read-only grant, and a read-only floor entry does not narrow a member's
    /// all-modes grant. Where the member's grant does not reach, the floor applies.
    #[test]
    fn a_members_own_grant_decides_where_it_reaches_and_the_floor_fills_the_rest() {
        let mut s = StandingScopeStore::default();
        s.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        s.add(StandingGrant { recursive: true, modes: modes("r"),
                              ..grant("kimi-code", "/w/shared/law", 2, None) });
        let law = "/w/shared/law/x.md";
        assert_eq!(s.effective_modes("kimi-code", law, 3), Some(modes("r")),
                   "the floor's rwed does not override kimi's r-only grant");
        assert!(!s.has_live_for("kimi-code", law, 3, modes("w")));
        assert!(s.has_live("codex", law, 3), "codex holds no grant there: the floor applies");
        assert!(s.has_live("kimi-code", "/w/shared/other.md", 3), "outside kimi's grant: floor");

        let mut t = StandingScopeStore::default();
        t.floor_add(FloorEntry { recursive: true, modes: modes("r"), ..floor("/w/gov", 1) });
        t.add(StandingGrant { recursive: true, ..grant("codex", "/w/gov/mine", 2, None) });
        assert!(t.has_live("codex", "/w/gov/mine/a", 3), "a read floor does not narrow a grant");
        assert!(!t.has_live("kimi-code", "/w/gov/mine/a", 3));
        // An expired grant is no grant: the floor applies again.
        let mut u = StandingScopeStore::default();
        u.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        u.add(StandingGrant { recursive: true, modes: modes("r"),
                              ..grant("kimi-code", "/w/shared/law", 2, Some(5)) });
        assert!(u.has_live("kimi-code", law, 6));
    }

    /// What a mode-blind gate is served for one member: an all-modes floor entry that would
    /// undo that member's narrowed grant is withheld from it, by name; read-only entries go
    /// to the read list; an entry without read is never served as reach.
    #[test]
    fn floor_for_withholds_what_would_override_a_narrowed_grant_and_names_it() {
        let mut s = StandingScopeStore::default();
        s.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        s.floor_add(FloorEntry { recursive: true, modes: modes("r"), ..floor("/w/gov", 1) });
        s.floor_add(FloorEntry { modes: modes("w"), ..floor("/w/drop", 1) });
        s.floor_add(floor("/w/plain", 1));
        let none = s.floor_for(&[]);
        let paths = |v: &Vec<&FloorEntry>| v.iter().map(|f| f.path.clone()).collect::<Vec<_>>();
        assert_eq!(paths(&none.reach), vec!["/w/shared", "/w/plain"]);
        assert_eq!(paths(&none.read), vec!["/w/gov"]);
        assert_eq!(none.withheld.len(), 1);
        assert_eq!(none.withheld[0].path, "/w/drop");

        let narrowed = vec![("/w/shared/law".to_string(), true, modes("r"))];
        let kimi = s.floor_for(&narrowed);
        assert_eq!(paths(&kimi.reach), vec!["/w/plain"], "the overlapping rwed entry is withheld");
        assert!(kimi.withheld.iter().any(|w| w.path == "/w/shared" && w.why.contains("/w/shared/law")));
        assert_eq!(paths(&kimi.read), vec!["/w/gov"], "a read entry beside an r grant stays");
        // A narrowed grant without read under a read-only floor entry withholds that too.
        let wonly = vec![("/w/gov/x".to_string(), false, modes("w"))];
        assert!(s.floor_for(&wonly).read.is_empty());
        // An overlap is either direction: a grant ABOVE the floor entry clashes as well.
        let above = vec![("/w".to_string(), true, modes("r"))];
        assert!(s.floor_for(&above).reach.is_empty());
    }

    /// #1385 (Nova re-review of #1383): an all-modes floor entry on a parent and the
    /// member's own r-only grant on a child. The entry is withheld, and the reason it gives
    /// must not promise to end at mode enforcement: a gate that enforces modes still unions
    /// the served floor with the member's grants, so re-serving would let a child write
    /// through. floor_for takes no gate-version input, so nothing here can re-serve on
    /// "modes enforced" alone.
    #[test]
    fn an_all_modes_parent_floor_stays_withheld_over_an_r_only_child_grant() {
        let mut s = StandingScopeStore::default();
        s.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        let child = vec![("/w/shared/forum".to_string(), true, modes("r"))];
        let view = s.floor_for(&child);
        assert!(view.reach.is_empty(), "the parent entry must not reach the child: {:?}",
                view.reach.iter().map(|f| &f.path).collect::<Vec<_>>());
        assert!(view.read.is_empty());
        let w = view.withheld.iter().find(|w| w.path == "/w/shared").expect("named as withheld");
        assert!(w.why.contains("/w/shared/forum") && w.why.contains("#1386"), "{}", w.why);
        assert!(!w.why.contains("when your gate enforces modes"),
                "the reason must not promise re-serving at mode enforcement: {}", w.why);
    }

    #[test]
    fn a_recursive_floor_entry_covers_its_subtree_at_the_separator() {
        let mut s = StandingScopeStore::default();
        s.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        assert!(s.floor_allows("/w/shared"));
        assert!(s.floor_allows("/w/shared/a/b.md"));
        assert!(!s.floor_allows("/w/shared-not"), "containment is at the separator");
        // And an exact entry stays exact: the field defaults to the narrower meaning.
        let mut e = StandingScopeStore::default();
        e.floor_add(floor("/w/shared", 1));
        assert!(!e.floor_allows("/w/shared/a/b.md"));
    }

    /// Upgrading must not move the digest of a floor written before `recursive`/`modes`
    /// existed (a moved digest reads as a changed society baseline), while a floor that
    /// differs only in recursion or modes must digest differently.
    #[test]
    fn floor_digest_is_unchanged_for_legacy_entries_and_sees_reach_and_modes() {
        let mut legacy = StandingScopeStore::default();
        legacy.floor_add(floor("/w/shared", 1));
        let mut hasher = Sha256::new();
        hasher.update(("/w/shared".len() as u64).to_be_bytes());
        hasher.update(b"/w/shared");
        assert_eq!(legacy.floor_digest(), hex::encode(hasher.finalize()));

        let mut rec = StandingScopeStore::default();
        rec.floor_add(FloorEntry { recursive: true, ..floor("/w/shared", 1) });
        let mut ro = StandingScopeStore::default();
        ro.floor_add(FloorEntry { modes: modes("r"), ..floor("/w/shared", 1) });
        let mut rw = StandingScopeStore::default();
        rw.floor_add(FloorEntry { modes: modes("rw"), ..floor("/w/shared", 1) });
        assert_ne!(legacy.floor_digest(), rec.floor_digest());
        assert_ne!(legacy.floor_digest(), ro.floor_digest());
        assert_ne!(rec.floor_digest(), ro.floor_digest());
        assert_ne!(ro.floor_digest(), rw.floor_digest());
        // And the divergence report can name the difference the digest sees.
        assert!(!rec.divergence_from(&legacy).is_empty());
        assert!(!ro.divergence_from(&legacy).is_empty());
        assert!(!ro.divergence_from(&rw).is_empty());
    }

    /// Codex HOLD on #1347, P2: the first spelling appended " (read)" to the path, so a
    /// read-only `/w/law` and an all-access path literally named `/w/law (read)` digested as
    /// one floor. Every pair of distinct (path, recursive, modes) must spell differently.
    #[test]
    fn floor_spellings_never_collide_across_path_recursion_and_modes() {
        let e = |p: &str, recursive: bool, m: &str| FloorEntry {
            path: p.into(),
            recursive,
            modes: modes(m),
            ..Default::default()
        };
        let entries = [
            e("/w/law", false, "rwed"),
            e("/w/law", false, "r"),
            e("/w/law", true, "rwed"),
            e("/w/law", true, "r"),
            e("/w/law (read)", false, "rwed"),
            e("/w/law/**", false, "rwed"),
            e("/w/law/** (read)", false, "rwed"),
            e("/w/law\u{1f}exact\u{1f}r", false, "rwed"),
            e("/w/law\u{1f}exact\u{1f}r", true, "rwed"),
            e("/w", true, "r"),
            e("/w/law", false, "rw"),
            e("/w/law", true, "rwe"),
        ];
        let spelt: std::collections::BTreeSet<String> =
            entries.iter().map(FloorEntry::spelling).collect();
        assert_eq!(spelt.len(), entries.len(), "two distinct entries spelt alike: {spelt:?}");
        for pair in [(1usize, 4usize), (2, 5), (3, 6), (1, 10)] {
            let mut a = StandingScopeStore::default();
            a.floor_add(entries[pair.0].clone());
            let mut b = StandingScopeStore::default();
            b.floor_add(entries[pair.1].clone());
            assert_ne!(a.floor_digest(), b.floor_digest(), "{pair:?}");
            assert_ne!(a.authority_digest(), b.authority_digest(), "{pair:?}");
            assert!(!a.divergence_from(&b).is_empty(), "{pair:?}");
        }
        // Legacy stays the bare path, explicitly.
        assert_eq!(entries[0].spelling(), "/w/law");
    }

    #[test]
    fn a_stored_floor_without_the_new_fields_reads_as_exact_and_all_and_writes_back_unchanged() {
        let raw = r#"{"path":"/w/x","added_at":1,"added_by":"operator","reason":"r"}"#;
        let e: FloorEntry = serde_json::from_str(raw).unwrap();
        assert!(!e.recursive);
        assert!(e.modes.is_all());
        let back = serde_json::to_value(&e).unwrap();
        assert!(back.get("modes").is_none(), "an all-modes entry is written without the field");
        let r: FloorEntry = serde_json::from_str(
            r#"{"path":"/w/x","added_at":1,"recursive":true,"modes":"r"}"#).unwrap();
        assert_eq!(r.modes, modes("r"));
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
                refusals: Vec::new(),
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

/// #1345: per-grant modes (r/w/e/d) and the one-act Edit.
#[cfg(test)]
mod mode_tests {
    use super::*;
    use crate::server::grant_modes::Modes;

    fn g(member: &str, path: &str, recursive: bool, modes: &str) -> StandingGrant {
        StandingGrant {
            member: member.into(), path: path.into(), granted_at: 7, granted_by: "op".into(),
            reason: "because".into(), expires_at: None, request_id: Some("scope-1".into()),
            recursive, modes: Modes::parse(modes).unwrap(),
        }
    }

    #[test]
    fn a_grant_written_before_modes_loads_as_all_four_and_writes_back_unchanged() {
        let old = r#"{"member":"m","path":"/w","granted_at":1,"recursive":true}"#;
        let back: StandingGrant = serde_json::from_str(old).unwrap();
        assert_eq!(back.modes, Modes::ALL, "an unmoded grant narrowed silently");
        let written = serde_json::to_value(&back).unwrap();
        assert!(written.get("modes").is_none(), "an all-modes grant must serialise as before: {written}");
        let narrowed = serde_json::to_value(g("m", "/w", true, "r")).unwrap();
        assert_eq!(narrowed["modes"], "r");
    }

    #[test]
    fn the_digest_is_unchanged_for_all_modes_and_moves_when_a_grant_is_narrowed() {
        let mut st = StandingScopeStore::default();
        st.grants.push(g("m", "/w", false, "rwed"));
        let mut legacy = st.clone();
        // the pre-#1345 row, computed by hand: the same five fields, nothing else
        let row = "grant\u{1f}m\u{1f}/w\u{1f}7\u{1f}".to_string();
        assert_eq!(StandingScopeStore::grant_row(&legacy.grants[0]), row);
        legacy.grants[0].modes = Modes::READ;
        assert_ne!(st.authority_digest(), legacy.authority_digest(), "a narrowed grant must move the digest");
        let d = legacy.divergence_from(&st);
        assert!(d.iter().any(|l| l.contains("modes runtime r vs vault rwed")), "{d:?}");
    }

    #[test]
    fn a_read_only_grant_never_answers_has_live_for_an_unknown_act() {
        let mut st = StandingScopeStore::default();
        st.add(g("m", "/w", true, "r"));
        assert!(!st.has_live("m", "/w/x", 10), "has_live means all modes; r alone must not answer it");
        assert!(st.has_live_for("m", "/w/x", 10, Modes::READ));
        assert!(!st.has_live_for("m", "/w/x", 10, Modes::parse("w").unwrap()));
    }

    #[test]
    fn reassign_carries_the_modes() {
        let mut st = StandingScopeStore::default();
        st.add(g("typo", "/w", true, "re"));
        let moved = st.reassign("typo", "/w", "real", 9, "fix").unwrap();
        assert_eq!(moved.modes.as_letters(), "re");
    }

    #[test]
    fn edit_rewrites_one_row_in_place_and_keeps_its_provenance() {
        let mut st = StandingScopeStore::default();
        st.add(g("m", "/w/a", false, "rwed"));
        st.add(g("other", "/w/a", false, "rwed"));
        let gen = st.generation;
        let (before, after) = st.edit("m", "/w/a", gen, GrantEdit {
            path: "/w/b".into(), recursive: true, modes: Modes::READ }).unwrap();
        assert_eq!(st.generation, gen + 1, "one edit, one generation step");
        assert_eq!((before.path.as_str(), after.path.as_str()), ("/w/a", "/w/b"));
        let mine: Vec<_> = st.grants.iter().filter(|x| x.member == "m").collect();
        assert_eq!(mine.len(), 1, "the old path must not stay live beside the new one");
        assert_eq!((mine[0].granted_at, mine[0].reason.as_str(), mine[0].request_id.as_deref()),
                   (7, "because", Some("scope-1")), "provenance is the original grant's");
        assert!(mine[0].recursive && mine[0].modes == Modes::READ);
        assert!(st.grants.iter().any(|x| x.member == "other" && x.path == "/w/a"),
                "another member's grant on the old path is untouched");
    }

    #[test]
    fn edit_refusals_change_nothing() {
        let mut st = StandingScopeStore::default();
        st.add(g("m", "/w/a", false, "rw"));
        st.add(g("m", "/w/b", false, "rw"));
        let gen = st.generation;
        let snap = st.grants.clone();
        let same = GrantEdit { path: "/w/a".into(), recursive: false, modes: Modes::parse("rw").unwrap() };
        assert_eq!(st.edit("m", "/w/a", gen, same.clone()), Err(EditRefused::NoChange));
        assert_eq!(st.edit("m", "/w/a", gen - 1, GrantEdit { modes: Modes::READ, ..same.clone() }),
                   Err(EditRefused::Moved { current: gen }));
        assert_eq!(st.edit("m", "/w/zz", gen, same.clone()), Err(EditRefused::NoSuchGrant));
        assert_eq!(st.edit("m", "/w/a", gen, GrantEdit { path: "/w/b".into(), ..same }),
                   Err(EditRefused::DestinationHoldsPath));
        assert_eq!((st.generation, st.grants.clone()), (gen, snap));
    }

    #[test]
    fn widening_is_named_on_each_axis() {
        let base = g("m", "/w/a", true, "r");
        let w = |path: &str, rec: bool, modes: &str| g("m", path, rec, modes);
        assert!(!GrantEdit::widens(&base, &w("/w/a/sub", true, "r")), "a subtree of a recursive grant narrows");
        assert!(!GrantEdit::widens(&base, &w("/w/a", false, "r")), "recursive to exact narrows");
        assert!(GrantEdit::widens(&base, &w("/w/a", true, "rw")), "an added mode widens");
        assert!(GrantEdit::widens(&base, &w("/w/b", true, "r")), "a sibling path widens");
        assert!(GrantEdit::widens(&base, &w("/w", true, "r")), "the parent widens");
        let exact = g("m", "/w/a", false, "rw");
        assert!(GrantEdit::widens_reach(&exact, &w("/w/a", true, "rw")), "exact to recursive widens");
        assert!(!GrantEdit::widens(&exact, &w("/w/a", false, "r")), "dropping a mode only narrows");
        assert!(GrantEdit::widens(&exact, &w("/w/a", false, "rd")), "swapping w for d still widens");
    }
}

