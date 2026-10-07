//! LOCK-FREE POLICY SNAPSHOTS (stage 2 of the per-member serialisation plan, dp 2026-10-07).
//!
//! Every gate call starts with the member's policy snapshot — `hestia_operating_law` and
//! `hestia_scope_status` — and both are pure reads. Under the single global state lock they
//! queued behind every write in the society (measured: <1 ms of hold, seconds of wait). They now
//! read an immutable [`PolicyPublication`] that the daemon swaps atomically, and never take the
//! state lock at all.
//!
//! HOW STALENESS IS MADE IMPOSSIBLE RATHER THAN UNLIKELY. Every policy input on `ServerState` is a
//! [`Watched`] field: reading it is free, and ANY mutable access (method call, assignment through
//! the deref, `&mut` borrow) sets its dirty bit — the compiler routes every mutation through
//! `DerefMut`, so there is no mutation site to forget. When a state-lock guard is released, a
//! dirty bit (or a moved vault policy-list generation) makes the guard rebuild the publication and
//! swap it in BEFORE the lock is released. So:
//!   - a reader sees either the publication before a write or the one after it, never a mix (one
//!     `Arc` swap under a write lock);
//!   - a write is visible to snapshot readers no later than it is visible to lock takers.
//! Debug builds (and so every test) additionally rebuild the publication on EVERY release and
//! assert it equals the published one: a mutation path that escaped `Watched` fails the whole
//! existing suite loudly instead of serving a stale law. `HESTIA_SKIP_PUBLICATION_CHECK=1` opts out.
//!
//! Session identity (for "who is asking") is served from a [`SessionDirectory`] beside the
//! publication. Its changes are STAGED by [`Sessions`] and applied at the same release, under the
//! same write lock as the publication swap, so resolving a caller and reading its law are one
//! consistent view. The connect REUSE arm (a timestamp bump on a known host session) is served
//! from the directory too, and takes no state lock.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::ops::{Deref, DerefMut};
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::{Arc, Mutex as StdMutex, RwLock};

use chrono::{DateTime, TimeZone, Utc};
use serde_json::{json, Value};
use uuid::Uuid;

use super::state::{InstanceGrant, ScopeRequest, Session};
use super::standing_scope::{AuthorityStatus, ProjectionAudit, StandingGrant, StandingScopeStore};

// ------------------------------------------------------------------------------- Watched<T>

/// A field whose every mutable access is recorded. See the module docs.
pub struct Watched<T> {
    value: T,
    dirty: bool,
}

impl<T> Watched<T> {
    pub fn new(value: T) -> Self {
        Self { value, dirty: true }
    }
    /// Was this field mutably accessed since the last call? Clears the bit.
    pub(crate) fn take_dirty(&mut self) -> bool {
        std::mem::take(&mut self.dirty)
    }
}

impl<T> Deref for Watched<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}

impl<T> DerefMut for Watched<T> {
    fn deref_mut(&mut self) -> &mut T {
        self.dirty = true;
        &mut self.value
    }
}

impl<T: Default> Default for Watched<T> {
    fn default() -> Self {
        Self::new(T::default())
    }
}

impl<T: std::fmt::Debug> std::fmt::Debug for Watched<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.value.fmt(f)
    }
}

// ----------------------------------------------------------------------- engine view

/// The published engines are clones of the daemon's own: `PolicyEngine` clones share their
/// rate-limit state, so evaluating against the publication counts against the same limits.
pub type EngineView = crate::policy::PolicyEngine;

/// THE LAW FOLD, in one place for both the lock holders and the publication: the society base,
/// then the session role's overlay and the (instance, role) overlay folded strictest-wins; then a
/// live operator grant, which SUBSTITUTES its preset for the local layers (the one input allowed
/// to loosen, applied outside the fold); then ratified hub law, folded strictest-wins over all of
/// it so no local grant can reach past an amendment-only baseline.
#[allow(clippy::too_many_arguments)]
pub fn evaluate_folded(
    society: &EngineView,
    roles: &HashMap<String, EngineView>,
    instances: &HashMap<(String, String), EngineView>,
    grants: &HashMap<(String, String), InstanceGrant>,
    law_gate: Option<&crate::policy::LawGate>,
    plugin_id: &str,
    role: &str,
    pa: &crate::policy::PolicyAction,
) -> crate::policy::PolicyEvaluation {
    let mut evaluation = society.evaluate(pa);
    if let Some(e) = roles.get(role) {
        evaluation = crate::policy::fold_strictest(evaluation, e.evaluate(pa));
    }
    if let Some(e) = instances.get(&(plugin_id.to_string(), role.to_string())) {
        evaluation = crate::policy::fold_strictest(evaluation, e.evaluate(pa));
    }
    let now = crate::server::gate_escalation::now_secs();
    if let Some(p) = instance_grant_in(grants, plugin_id, role, now)
        .and_then(|g| crate::policy::get_preset(&g.preset))
    {
        evaluation = crate::policy::PolicyEngine::new(p.config).evaluate(pa);
    }
    if let Some(gate) = law_gate {
        evaluation = crate::policy::fold_strictest(evaluation, gate.evaluate(pa, role));
    }
    evaluation
}

// ------------------------------------------------------------------ shared grant readers
//
// ONE implementation each, used by both `ServerState` (lock holders) and the publication
// (lock-free readers), so the two paths cannot disagree about what is live.

pub fn instance_grant_in<'a>(
    grants: &'a HashMap<(String, String), InstanceGrant>,
    plugin_id: &str,
    role: &str,
    now: u64,
) -> Option<&'a InstanceGrant> {
    grants
        .get(&(plugin_id.to_string(), role.to_string()))
        .or_else(|| grants.get(&(plugin_id.to_string(), "*".to_string())))
        .filter(|g| g.is_live(now))
}

pub fn live_scope_grants_in<'a>(
    requests: &'a HashMap<String, ScopeRequest>,
    plugin_id: &str,
    now: u64,
) -> Vec<&'a ScopeRequest> {
    let mut live: Vec<&ScopeRequest> = requests
        .values()
        .filter(|r| r.plugin_id == plugin_id && r.is_live(now))
        .collect();
    live.sort_by_key(|r| r.requested_at);
    live
}

// ---------------------------------------------------------------------- the publication

/// Who a resolved session is, as the lock-free readers see it.
pub struct CallerIdent {
    pub session_uuid: Uuid,
    pub plugin_id: String,
    pub role_lct: String,
}

/// An immutable copy of every input the published law and scope status read.
pub struct PolicyPublication {
    /// Moves on every republish.
    pub version: u64,
    pub society: EngineView,
    pub roles: HashMap<String, EngineView>,
    pub instances: HashMap<(String, String), EngineView>,
    pub instance_grants: HashMap<(String, String), InstanceGrant>,
    /// Ratified hub law (shared, not copied).
    pub law_gate: Option<Arc<crate::policy::LawGate>>,
    pub policy_lists: crate::vault::policy_lists::PolicyLists,
    pub scope_requests: HashMap<String, ScopeRequest>,
    pub standing_scope: StandingScopeStore,
    pub authority_status: AuthorityStatus,
    pub standing_projection_audit: Option<ProjectionAudit>,
    /// Shared handles (not copies): session identity and gate-capability reports.
    pub sessions: Arc<SessionDirectory>,
    pub gate_capabilities: Arc<GateCapabilities>,
    /// DURABLE READS: the chain length this publication's inputs reflect. A reader replying from
    /// it waits until that much of the chain is durable (`observe`).
    pub chain_durability: Arc<crate::storage::durability::Durability>,
    pub observed_len: u64,
}

impl PolicyPublication {
    pub fn instance_grant(&self, plugin_id: &str, role: &str) -> Option<&InstanceGrant> {
        instance_grant_in(&self.instance_grants, plugin_id, role,
                          crate::server::gate_escalation::now_secs())
    }
    pub fn live_scope_grants(&self, plugin_id: &str) -> Vec<&ScopeRequest> {
        live_scope_grants_in(&self.scope_requests, plugin_id,
                             crate::server::gate_escalation::now_secs())
    }
    pub fn live_standing_grants(&self, plugin_id: &str) -> Vec<&StandingGrant> {
        self.standing_scope.live_for(plugin_id, crate::server::gate_escalation::now_secs())
    }
    /// Register this publication with the current request's durability scope: its reply must not
    /// precede the durability of the chain entries the publication reflects.
    pub fn observe(&self) {
        crate::storage::durability::note_observed(&self.chain_durability, self.observed_len);
    }

    /// Evaluate an action against this publication's law — outside the state lock. Same fold
    /// as the lock holders' (`evaluate_folded`).
    pub fn evaluate(
        &self,
        plugin_id: &str,
        role: &str,
        pa: &crate::policy::PolicyAction,
    ) -> crate::policy::PolicyEvaluation {
        evaluate_folded(&self.society, &self.roles, &self.instances, &self.instance_grants,
                        self.law_gate.as_deref(), plugin_id, role, pa)
    }

    /// Resolve a caller-supplied session id. FAIL-CLOSED like `resolve_attributed_caller`.
    pub fn resolve(&self, session_id: Option<&str>) -> Option<CallerIdent> {
        let uuid = Uuid::parse_str(session_id?).ok()?;
        let id = self.sessions.get(&uuid)?;
        Some(CallerIdent {
            session_uuid: uuid,
            plugin_id: id.plugin_id.clone(),
            role_lct: id.constellation_role.clone(),
        })
    }

    /// Canonical content (everything but `version` and the shared handles), for the debug
    /// staleness check and the equivalence tests. HashMap order is normalised.
    pub fn canonical(&self) -> Value {
        fn eng(e: &EngineView) -> Value {
            json!({"hash": e.content_hash(),
                   "config": serde_json::to_value(e.config()).unwrap_or(Value::Null)})
        }
        let roles: BTreeMap<_, _> = self.roles.iter().map(|(k, v)| (k.clone(), eng(v))).collect();
        let instances: BTreeMap<_, _> = self
            .instances
            .iter()
            .map(|((a, b), v)| (format!("{a}\u{0}{b}"), eng(v)))
            .collect();
        let grants: BTreeMap<_, _> = self
            .instance_grants
            .iter()
            .map(|((a, b), v)| (format!("{a}\u{0}{b}"), serde_json::to_value(v).unwrap_or_default()))
            .collect();
        let lists: BTreeMap<_, _> = self
            .policy_lists
            .iter()
            .map(|(k, v)| (k.clone(), serde_json::to_value(v).unwrap_or_default()))
            .collect();
        let reqs: BTreeMap<_, _> = self
            .scope_requests
            .iter()
            .map(|(k, v)| (k.clone(), serde_json::to_value(v).unwrap_or_default()))
            .collect();
        json!({
            "society": eng(&self.society),
            "law_gate": format!("{:?}", self.law_gate.as_deref()),
            "roles": roles,
            "instances": instances,
            "instance_grants": grants,
            "policy_lists": lists,
            "scope_requests": reqs,
            "standing_scope": serde_json::to_value(&self.standing_scope).unwrap_or_default(),
            "authority_status": self.authority_status.as_str(),
            "standing_projection_audit":
                serde_json::to_value(&self.standing_projection_audit).unwrap_or_default(),
        })
    }
}

// --------------------------------------------------------------------- session directory

/// A session's identity as lock-free readers need it. Immutable after mint (Guard A: a reused
/// session keeps the role, LCT and basis it was minted with) except `last_seen`.
pub struct SessionIdent {
    pub session_id: Uuid,
    pub plugin_id: String,
    pub host_session_id: Option<String>,
    pub soft_lct: String,
    pub assigned_role: String,
    pub constellation_role: String,
    pub role_basis: Option<String>,
    /// Unix millis of the latest connect seen for this session, including lock-free reuses.
    last_seen_ms: AtomicI64,
}

impl SessionIdent {
    fn of(s: &Session) -> Self {
        Self {
            session_id: s.session_id,
            plugin_id: s.plugin_id.clone(),
            host_session_id: s.host_session_id.clone(),
            soft_lct: s.soft_lct.clone(),
            assigned_role: s.assigned_role.clone(),
            constellation_role: s.constellation_role.clone(),
            role_basis: s.role_basis.clone(),
            last_seen_ms: AtomicI64::new(s.connected_at.timestamp_millis()),
        }
    }
    /// Guard A liveness bump: the only mutation a reuse makes.
    pub fn touch(&self) {
        self.last_seen_ms.fetch_max(Utc::now().timestamp_millis(), Ordering::AcqRel);
    }
    pub fn last_seen(&self) -> DateTime<Utc> {
        Utc.timestamp_millis_opt(self.last_seen_ms.load(Ordering::Acquire))
            .single()
            .unwrap_or_else(Utc::now)
    }
}

#[derive(Default)]
struct DirInner {
    by_id: HashMap<Uuid, Arc<SessionIdent>>,
    /// The reuse key: (claimed member, host session id) — never the host id alone (Guard C).
    by_reuse_key: HashMap<(String, String), Uuid>,
}

#[derive(Default)]
pub struct SessionDirectory {
    inner: RwLock<DirInner>,
}

impl SessionDirectory {
    pub fn get(&self, id: &Uuid) -> Option<Arc<SessionIdent>> {
        self.inner.read().unwrap_or_else(|p| p.into_inner()).by_id.get(id).cloned()
    }
    pub fn find_reuse(&self, plugin_id: &str, host_session_id: &str) -> Option<Arc<SessionIdent>> {
        let g = self.inner.read().unwrap_or_else(|p| p.into_inner());
        let id = g.by_reuse_key.get(&(plugin_id.to_string(), host_session_id.to_string()))?;
        g.by_id.get(id).cloned()
    }
    fn apply(&self, ops: Vec<DirOp>) {
        let mut g = self.inner.write().unwrap_or_else(|p| p.into_inner());
        for op in ops {
            match op {
                DirOp::Put(ident) => {
                    let ident = match g.by_id.get(&ident.session_id) {
                        // Keep the later of the two liveness readings.
                        Some(old) => {
                            ident.last_seen_ms.fetch_max(old.last_seen_ms.load(Ordering::Acquire),
                                                         Ordering::AcqRel);
                            ident
                        }
                        None => ident,
                    };
                    if let Some(h) = &ident.host_session_id {
                        g.by_reuse_key.insert((ident.plugin_id.clone(), h.clone()), ident.session_id);
                    }
                    g.by_id.insert(ident.session_id, Arc::new(ident));
                }
                DirOp::Remove(id) => {
                    if let Some(old) = g.by_id.remove(&id) {
                        if let Some(h) = &old.host_session_id {
                            let key = (old.plugin_id.clone(), h.clone());
                            if g.by_reuse_key.get(&key) == Some(&id) {
                                g.by_reuse_key.remove(&key);
                            }
                        }
                    }
                }
            }
        }
    }
}

enum DirOp {
    Put(SessionIdent),
    Remove(Uuid),
}

/// The session map. Reads deref to the `HashMap`; every mutation goes through a method here, so
/// the directory can never miss one (there is no `DerefMut`).
pub struct Sessions {
    map: HashMap<Uuid, Session>,
    dir: Arc<SessionDirectory>,
    pending: Vec<DirOp>,
}

impl Default for Sessions {
    fn default() -> Self {
        Self { map: HashMap::new(), dir: Arc::new(SessionDirectory::default()), pending: Vec::new() }
    }
}

impl Deref for Sessions {
    type Target = HashMap<Uuid, Session>;
    fn deref(&self) -> &Self::Target {
        &self.map
    }
}

impl Sessions {
    pub fn directory(&self) -> Arc<SessionDirectory> {
        self.dir.clone()
    }
    pub fn insert(&mut self, id: Uuid, s: Session) -> Option<Session> {
        self.pending.push(DirOp::Put(SessionIdent::of(&s)));
        self.map.insert(id, s)
    }
    pub fn remove(&mut self, id: &Uuid) -> Option<Session> {
        self.pending.push(DirOp::Remove(*id));
        self.map.remove(id)
    }
    /// Mutable access to one session; the directory is resynced from it when the guard drops.
    pub fn get_mut(&mut self, id: &Uuid) -> Option<SessionMut<'_>> {
        if !self.map.contains_key(id) {
            return None;
        }
        Some(SessionMut { sessions: self, id: *id })
    }
    /// The session minted for this (member, host session), if any — the connect reuse key.
    pub fn find_reuse_id(&self, plugin_id: &str, host_session_id: &str) -> Option<Uuid> {
        self.map
            .values()
            .find(|s| s.plugin_id == plugin_id && s.host_session_id.as_deref() == Some(host_session_id))
            .map(|s| s.session_id)
    }
    /// Liveness as every reader should see it: the later of the locked map's `connected_at` and
    /// any lock-free reuse bump since.
    pub fn last_seen(&self, s: &Session) -> DateTime<Utc> {
        match self.dir.get(&s.session_id) {
            Some(id) => id.last_seen().max(s.connected_at),
            None => s.connected_at,
        }
    }
    pub(crate) fn has_pending(&self) -> bool {
        !self.pending.is_empty()
    }
    /// Apply staged directory changes. Called at guard release under the publication write lock.
    pub(crate) fn apply_pending(&mut self) {
        let ops = std::mem::take(&mut self.pending);
        if !ops.is_empty() {
            self.dir.apply(ops);
        }
    }
}

pub struct SessionMut<'a> {
    sessions: &'a mut Sessions,
    id: Uuid,
}

impl Deref for SessionMut<'_> {
    type Target = Session;
    fn deref(&self) -> &Session {
        &self.sessions.map[&self.id]
    }
}

impl DerefMut for SessionMut<'_> {
    fn deref_mut(&mut self) -> &mut Session {
        self.sessions.map.get_mut(&self.id).expect("checked at get_mut")
    }
}

impl Drop for SessionMut<'_> {
    fn drop(&mut self) {
        if let Some(s) = self.sessions.map.get(&self.id) {
            let ident = SessionIdent::of(s);
            self.sessions.pending.push(DirOp::Put(ident));
        }
    }
}

// ------------------------------------------------------------------- gate capabilities

/// Per-member gate capability self-reports (#481 evidence, A1). Written by every connect —
/// including the lock-free reuse arm — so it lives outside the state lock, behind its own short
/// mutex that is never held across anything.
#[derive(Default)]
pub struct GateCapabilities {
    inner: StdMutex<HashMap<String, HashSet<String>>>,
}

impl GateCapabilities {
    fn g(&self) -> std::sync::MutexGuard<'_, HashMap<String, HashSet<String>>> {
        self.inner.lock().unwrap_or_else(|p| p.into_inner())
    }
    pub fn insert(&self, member: String, caps: HashSet<String>) {
        self.g().insert(member, caps);
    }
    pub fn remove(&self, member: &str) -> Option<HashSet<String>> {
        self.g().remove(member)
    }
    pub fn get(&self, member: &str) -> Option<HashSet<String>> {
        self.g().get(member).cloned()
    }
    pub fn contains_key(&self, member: &str) -> bool {
        self.g().contains_key(member)
    }
    pub fn keys(&self) -> Vec<String> {
        self.g().keys().cloned().collect()
    }
}
