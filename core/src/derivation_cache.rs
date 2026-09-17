//! Event-triggered trust derivation.
//!
//! dp, 2026-09-17: "trust derivation should be event-triggered not timed. a negative event
//! would trigger trust derivation for the affected member. all should be derived on start
//! and maybe once a day."
//!
//! WHY THIS EXISTS. Every derived trust level was recomputed from scratch on every read:
//! `derivation::scan_window` decrypts and parses 10,000 outcome rows plus up to 100,000
//! governance rows, and the dashboard asked for it on every 2-second poll. Benched on a
//! 150,000-row chain of CBP's shape that scan took 1.26–1.53 s, and it was most of the
//! daemon's CPU while the operator had the page open (hestia #1040) — to recompute numbers
//! that had not changed, because nothing that could change them had happened.
//!
//! THE RULE. A member's derivation is cached, and it is re-derived when an event lands on
//! the chain that can change it. [`affected_members`] is that rule, one arm per event type
//! `derive` folds, and it is applied in `SqliteChainStore::append` — the one path every
//! chain write takes, so no writer can land evidence without invalidating what it affects.
//! Everyone is derived on first use after start, and again once a day
//! ([`EVERYONE_REDERIVE_EVERY`]) so drift the event rule deliberately ignores (volume
//! windows sliding, ordinary allows accumulating) is bounded.
//!
//! WHAT IS CACHED AND WHAT IS NOT. Only the window half ([`crate::derivation::derive_evidence`]).
//! The volume half ([`crate::derivation::with_volume`]) is applied at read time from the grain's live lifetime totals, so
//! routine outcomes — 78% of the chain, and not evidence `derive` scores — never trigger a
//! re-derivation and never leave the displayed volume stale.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use serde_json::Value;

use crate::derivation::{
    aliased_identities, alias_target, DerivedTrust, IDENTITY_ALIAS_EVENT, RETRY_WINDOW_MINUTES,
};
use crate::storage::chain::{ChainEntry, SqliteChainStore};

/// Everyone is re-derived at least this often, whatever the event rule says.
pub const EVERYONE_REDERIVE_EVERY: Duration = Duration::from_secs(24 * 60 * 60);

/// Events arriving in a burst are coalesced into one derivation.
///
/// A member hitting a boundary repeatedly lands a deny every few seconds, and each one
/// invalidates it. Re-scanning per deny would put the 1.3 s scan back on every poll for as
/// long as the burst lasts — the load this module removes. A member whose cached derivation
/// is invalidated is re-derived at the first read at least this long after the previous
/// scan; the first event after a quiet spell is re-derived at the next read. A grain with NO
/// cached derivation is never held back by this.
pub const EVENT_COALESCE: Duration = Duration::from_secs(10);

/// A cached window-half derivation for one (member, role) grain.
#[derive(Clone)]
pub struct CachedDerivation {
    /// [`crate::derivation::derive_evidence`]'s result. Apply the grain's live totals with
    /// [`crate::derivation::with_volume`] before showing a level.
    pub evidence: Arc<DerivedTrust>,
    /// [`alias_target`] over the same window, for display.
    pub aliased_to: Option<String>,
    everyone_epoch: u64,
    /// Every identity whose evidence folded into this grain (itself plus witnessed
    /// aliases), with the epoch each had when the window was read. An event naming ANY of
    /// them invalidates the grain — an alias's deny is the member's deny.
    member_epochs: Vec<(String, u64)>,
}

#[derive(Default)]
struct Inner {
    everyone_epoch: u64,
    everyone_since: Option<Instant>,
    member_epoch: HashMap<String, u64>,
    /// Latest deny per member, so an allow or outcome inside the retry window — which can
    /// turn that deny into a retry (0.0) or a recast (0.35) — invalidates the member.
    last_deny: HashMap<String, DateTime<Utc>>,
    /// Known grains. `None` = asked for, not yet derived.
    grains: HashMap<(String, String), Option<CachedDerivation>>,
    last_scan: Option<Instant>,
}

impl Inner {
    fn is_current(&self, c: &CachedDerivation) -> bool {
        c.everyone_epoch == self.everyone_epoch
            && c.member_epochs
                .iter()
                .all(|(id, ep)| self.member_epoch.get(id).copied().unwrap_or(0) == *ep)
    }

    fn roll_everyone(&mut self, now: Instant) {
        match self.everyone_since {
            Some(t) if now.saturating_duration_since(t) < EVERYONE_REDERIVE_EVERY => {}
            _ => {
                self.everyone_epoch += 1;
                self.everyone_since = Some(now);
            }
        }
    }

    /// The grains a scan at `now` must derive: the never-derived always, and the stale once
    /// the coalescing interval since the last scan has passed.
    fn due(&self, now: Instant) -> Vec<(String, String)> {
        let coalesced = self
            .last_scan
            .is_some_and(|t| now.saturating_duration_since(t) < EVENT_COALESCE);
        self.grains
            .iter()
            .filter(|(_, c)| match c {
                None => true,
                Some(c) => !coalesced && !self.is_current(c),
            })
            .map(|(k, _)| k.clone())
            .collect()
    }

    fn bump(&mut self, id: &str) {
        *self.member_epoch.entry(id.to_string()).or_insert(0) += 1;
    }
}

/// Which members an appended event can change the derivation of.
#[derive(Debug, PartialEq, Eq)]
pub enum Affects {
    Nobody,
    Members(Vec<String>),
    /// An event whose subject cannot be named from the row itself.
    Everyone,
}

fn flat_or_data<'a>(e: &'a ChainEntry, key: &str) -> Option<&'a str> {
    e.event_data
        .get(key)
        .or_else(|| e.event_data.get("data").and_then(|d| d.get(key)))
        .and_then(Value::as_str)
}

pub struct DerivationCache {
    inner: Mutex<Inner>,
}

impl Default for DerivationCache {
    fn default() -> Self {
        Self::new()
    }
}

impl DerivationCache {
    pub fn new() -> Self {
        Self { inner: Mutex::new(Inner::default()) }
    }

    /// The cache lock, recovered if poisoned.
    ///
    /// `observe` runs inside `SqliteChainStore::append`, after the row has committed. A
    /// panic there would turn a durable write into a failed call, for the sake of a display
    /// cache. Every field here is a counter or a replaceable derivation, so a state left
    /// behind by a panicking holder is at worst stale, and the next event or the daily
    /// re-derivation corrects it.
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// The event rule. One arm per event type `derive` reads; anything else is `Nobody`.
    ///
    /// The arms mirror the joins in `derive_evidence`, key for key, and each names the
    /// member the join credits or debits — NOT the author, since several of these are
    /// written by someone other than the member they change (an adjudicator, the operator,
    /// the gate).
    pub fn affected_members(&self, e: &ChainEntry) -> Affects {
        let inner = self.lock();
        let within_retry_of_a_deny = |pid: &str| {
            inner.last_deny.get(pid).is_some_and(|d| {
                e.timestamp >= *d && e.timestamp - *d <= chrono::Duration::minutes(RETRY_WINDOW_MINUTES)
            })
        };
        let one = |p: Option<&str>| match p {
            Some(p) if !p.is_empty() => Affects::Members(vec![p.to_string()]),
            // `derive` ignores a row it cannot attribute, so it changes nobody.
            _ => Affects::Nobody,
        };
        match e.event_type.as_str() {
            // THE NEGATIVE EVENT. A new temperament observation below the 0.5 prior when it
            // is a retry, a recast, or simply a deny that stands.
            "policy_decision" => {
                let Some(pid) = flat_or_data(e, "plugin_id") else { return Affects::Nobody };
                if flat_or_data(e, "decision") == Some("deny") {
                    return one(Some(pid));
                }
                // An allow is a governed act, and governed acts only move the level through
                // the significance ratio — slowly, so the daily re-derivation carries it.
                // Two exceptions change a verdict: inside a deny's retry window an allow can
                // make that deny a retry (0.0); and a grain derived with NO governed acts has
                // no volume baseline at all, so its first governed act can give it a level.
                let first_governed = inner.grains.iter().any(|((p, _), c)| {
                    p == pid && c.as_ref().is_some_and(|c| c.evidence.governed_acts == 0)
                });
                if within_retry_of_a_deny(pid) || first_governed {
                    one(Some(pid))
                } else {
                    Affects::Nobody
                }
            }
            // An outcome is read at exactly one site: a successful recast inside a deny's
            // retry window (0.35). Outside that window no outcome changes a derivation.
            "outcome" => match flat_or_data(e, "plugin_id") {
                Some(pid) if within_retry_of_a_deny(pid) => one(Some(pid)),
                _ => Affects::Nobody,
            },
            // Rulings and askings: a ruling is what moves an appeal or escalation from 0.85
            // to 1.0, and a member told its appeal was upheld must not see the old number
            // until tomorrow.
            "appeal" | "gate_escalation_opened" | "gate_escalation_decided" | "scope_attestation" => {
                one(flat_or_data(e, "plugin_id"))
            }
            "adjudication" => one(flat_or_data(e, "subject_plugin_id")),
            // Names the alias and the member it belongs to; both grains change.
            t if t == IDENTITY_ALIAS_EVENT => {
                let ids: Vec<String> = ["alias", "alias_of"]
                    .iter()
                    .filter_map(|k| flat_or_data(e, k))
                    .filter(|p| !p.is_empty())
                    .map(str::to_string)
                    .collect();
                if ids.is_empty() { Affects::Nobody } else { Affects::Members(ids) }
            }
            // An exoneration names a deny hash, not its member; an amnesty names a class.
            // Resolving either would need the window this module exists not to read, and both
            // are rare sovereign-scale acts, so they re-derive everyone.
            "exoneration" | "amnesty" => Affects::Everyone,
            _ => Affects::Nobody,
        }
    }

    /// Called by `SqliteChainStore::append` after an entry is durably committed.
    ///
    /// Ordering is what makes the cache sound: the invalidation lands AFTER the row is
    /// readable, and [`Self::refresh`] captures epochs BEFORE it scans. So a scan either sees
    /// the row, or its result is recorded under the old epoch and is already stale.
    pub fn observe(&self, e: &ChainEntry) {
        let affects = self.affected_members(e);
        let mut inner = self.lock();
        if e.event_type == "policy_decision" && flat_or_data(e, "decision") == Some("deny") {
            if let Some(pid) = flat_or_data(e, "plugin_id") {
                inner.last_deny.insert(pid.to_string(), e.timestamp);
            }
        }
        match affects {
            Affects::Nobody => {}
            Affects::Members(ids) => ids.iter().for_each(|id| inner.bump(id)),
            Affects::Everyone => {
                inner.everyone_epoch += 1;
            }
        }
    }

    /// The cached derivation for a grain, current or awaiting its re-derivation. `None` if
    /// the grain has never been derived; asking registers it, so the next
    /// [`Self::refresh`] derives it.
    pub fn lookup(&self, plugin_id: &str, role_lct: &str) -> Option<CachedDerivation> {
        let mut inner = self.lock();
        inner
            .grains
            .entry((plugin_id.to_string(), role_lct.to_string()))
            .or_insert(None)
            .clone()
    }

    /// Whether a [`Self::refresh`] now would derive anything.
    pub fn has_due(&self) -> bool {
        let now = Instant::now();
        let mut inner = self.lock();
        inner.roll_everyone(now);
        !inner.due(now).is_empty()
    }

    /// Derive every due grain from ONE window read. Returns how many were derived.
    ///
    /// Never holds the cache lock across the scan: the chain append path takes that lock to
    /// invalidate, and a governance write must not wait on a display derivation.
    pub fn refresh(&self, chain_store: &SqliteChainStore) -> usize {
        let now = Instant::now();
        let (due, everyone_epoch, member_epoch) = {
            let mut inner = self.lock();
            inner.roll_everyone(now);
            let due = inner.due(now);
            if due.is_empty() {
                return 0;
            }
            inner.last_scan = Some(now);
            (due, inner.everyone_epoch, inner.member_epoch.clone())
        };
        // The ONE prefiltered window every fold takes (tests/derivation_declares_what_it_reads).
        let window = crate::derivation::scan_window(chain_store);
        let refs: Vec<&ChainEntry> = window.iter().collect();
        let derived: Vec<((String, String), CachedDerivation)> = due
            .into_iter()
            .map(|(pid, role)| {
                let member_epochs = aliased_identities(&pid, &refs)
                    .into_iter()
                    .map(|id| {
                        let ep = member_epoch.get(&id).copied().unwrap_or(0);
                        (id, ep)
                    })
                    .collect();
                let c = CachedDerivation {
                    evidence: Arc::new(crate::derivation::derive_evidence(&pid, &role, &window)),
                    aliased_to: alias_target(&pid, &window),
                    everyone_epoch,
                    member_epochs,
                };
                ((pid, role), c)
            })
            .collect();
        // A restart forgets `last_deny`; re-learn it from the window, so a retry landing
        // just after startup still invalidates the member it penalises.
        let cutoff = Utc::now() - chrono::Duration::minutes(RETRY_WINDOW_MINUTES);
        let mut inner = self.lock();
        for e in window.iter().filter(|e| {
            e.timestamp >= cutoff
                && e.event_type == "policy_decision"
                && flat_or_data(e, "decision") == Some("deny")
        }) {
            if let Some(pid) = flat_or_data(e, "plugin_id") {
                let slot = inner.last_deny.entry(pid.to_string()).or_insert(e.timestamp);
                if e.timestamp > *slot {
                    *slot = e.timestamp;
                }
            }
        }
        let n = derived.len();
        for (k, c) in derived {
            inner.grains.insert(k, Some(c));
        }
        n
    }

    /// One grain, derived now if it is due: the API's per-member read.
    pub fn get(&self, chain_store: &SqliteChainStore, plugin_id: &str, role_lct: &str) -> CachedDerivation {
        if let Some(c) = self.lookup(plugin_id, role_lct) {
            if !self.has_due() {
                return c;
            }
        }
        self.refresh(chain_store);
        self.lookup(plugin_id, role_lct)
            .expect("refresh derives every registered grain that has no derivation")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const ROLE: &str = "role:constellation:member";

    fn store() -> (tempfile::TempDir, SqliteChainStore) {
        let dir = tempfile::tempdir().unwrap();
        let s = SqliteChainStore::open(dir.path().join("w.db"), [3u8; 32]).unwrap();
        (dir, s)
    }

    fn deny(s: &SqliteChainStore, pid: &str, session: &str, target: &str) -> ChainEntry {
        s.append(
            "policy_decision",
            json!({"plugin_id": pid, "role_lct": ROLE, "decision": "deny", "enforced": true,
                   "session_id": session, "tool_name": "Bash", "target": target}),
            "lct:test",
        )
        .unwrap()
    }

    fn allow(s: &SqliteChainStore, pid: &str, session: &str, target: &str) -> ChainEntry {
        s.append(
            "policy_decision",
            json!({"plugin_id": pid, "role_lct": ROLE, "decision": "allow", "enforced": true,
                   "session_id": session, "tool_name": "Bash", "target": target}),
            "lct:test",
        )
        .unwrap()
    }

    fn outcome(s: &SqliteChainStore, pid: &str) -> ChainEntry {
        s.append("outcome", json!({"plugin_id": pid, "role_lct": ROLE, "success": true, "tool_name": "Bash"}), "lct:test")
            .unwrap()
    }

    /// Scans are coalesced; tests that assert on the NEXT derivation step past the interval.
    fn past_coalesce(c: &DerivationCache) {
        c.inner.lock().unwrap().last_scan = None;
    }

    /// dp's rule, end to end through the real append path: a negative event re-derives the
    /// member it is about, and nobody else; routine traffic re-derives nobody.
    #[test]
    fn a_deny_rederives_its_member_and_routine_traffic_rederives_nobody() {
        let (_d, s) = store();
        let cache = s.derivations();
        deny(&s, "kimi-code", "s-k", "/etc/a");
        assert!(cache.lookup("kimi-code", ROLE).is_none(), "never derived");
        assert!(cache.lookup("codex", ROLE).is_none());
        assert_eq!(cache.refresh(&s), 2, "everyone is derived on first use");
        assert_eq!(cache.refresh(&s), 0, "nothing happened: nothing is re-derived");
        let before = cache.lookup("kimi-code", ROLE).unwrap();
        assert_eq!(before.evidence.temperament.observations, 1);

        // Routine traffic, well away from any deny's retry window for codex.
        for _ in 0..50 {
            outcome(&s, "codex");
        }
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 0, "fifty outcomes changed no derivation and scanned nothing");

        deny(&s, "kimi-code", "s-k", "/etc/b");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1, "the deny re-derives exactly its member");
        let after = cache.lookup("kimi-code", ROLE).unwrap();
        assert_eq!(after.evidence.temperament.observations, 2, "and the re-derivation sees it");
    }

    /// The retry window: an allow that turns a deny into a retry (0.0) is a negative event
    /// even though it is an allow. Without this arm the member would keep its comply 0.85
    /// until the daily re-derivation.
    #[test]
    fn an_allow_inside_a_denys_retry_window_is_a_negative_event() {
        let (_d, s) = store();
        let cache = s.derivations();
        cache.lookup("kimi-code", ROLE);
        deny(&s, "kimi-code", "s-k", "/etc/shadow-copy");
        allow(&s, "kimi-code", "s-other", "/elsewhere/entirely"); // first governed act already seen below
        cache.refresh(&s);
        let score = |c: &DerivationCache| c.lookup("kimi-code", ROLE).unwrap().evidence.temperament.score;
        assert!(score(cache).unwrap() > 0.5, "a deny that stands, not yet retried");

        allow(&s, "kimi-code", "s-k", "/etc/shadow-copy");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1);
        assert!(score(cache).unwrap() < 0.5, "the retry lowered the member, and the cache shows it");
    }

    /// A ruling is written by the ADJUDICATOR and changes the SUBJECT. Keyed on the author,
    /// the member told its appeal was upheld would keep the old number for a day.
    #[test]
    fn a_ruling_invalidates_its_subject_not_its_author() {
        let cache = DerivationCache::new();
        let e = ChainEntry {
            hash: "h".into(),
            prev_hash: "p".into(),
            timestamp: Utc::now(),
            event_type: "adjudication".into(),
            event_data: json!({"plugin_id": "codex", "subject_plugin_id": "cbp-being", "upheld": true}),
            signer_lct: String::new(),
            chain_position: 1,
        };
        assert_eq!(cache.affected_members(&e), Affects::Members(vec!["cbp-being".into()]));
    }

    /// An alias's conduct IS the member's: a deny recorded under the alias invalidates the
    /// member whose grain folds it.
    #[test]
    fn a_deny_under_an_alias_rederives_the_member_it_folds_into() {
        let (_d, s) = store();
        let cache = s.derivations();
        s.append(IDENTITY_ALIAS_EVENT, json!({"alias": "codex-cli", "alias_of": "codex"}), "lct:test").unwrap();
        cache.lookup("codex", ROLE);
        cache.refresh(&s);
        deny(&s, "codex-cli", "s-c", "/etc/x");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1, "codex re-derived on its alias's deny");
        assert_eq!(cache.lookup("codex", ROLE).unwrap().evidence.temperament.observations, 1);
    }

    /// A burst of denies is one derivation, not one per deny; the grain is re-derived once
    /// the burst has been coalesced.
    #[test]
    fn a_burst_of_denies_is_coalesced() {
        let (_d, s) = store();
        let cache = s.derivations();
        cache.lookup("kimi-code", ROLE);
        cache.refresh(&s);
        deny(&s, "kimi-code", "s-k", "/etc/a");
        assert_eq!(cache.refresh(&s), 0, "inside the coalescing interval: served from cache");
        deny(&s, "kimi-code", "s-k", "/etc/b");
        assert!(cache.lookup("kimi-code", ROLE).is_some(), "the stale derivation is still served meanwhile");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1);
        assert_eq!(cache.lookup("kimi-code", ROLE).unwrap().evidence.temperament.observations, 2);
    }

    /// Once a day everyone is re-derived, whatever happened.
    #[test]
    fn everyone_is_rederived_daily() {
        let (_d, s) = store();
        let cache = s.derivations();
        cache.lookup("kimi-code", ROLE);
        cache.lookup("codex", ROLE);
        assert_eq!(cache.refresh(&s), 2);
        {
            let mut inner = cache.inner.lock().unwrap();
            inner.everyone_since = Some(Instant::now() - EVERYONE_REDERIVE_EVERY);
            inner.last_scan = None;
        }
        assert_eq!(cache.refresh(&s), 2);
    }

    /// The cached half plus live totals is exactly a fresh full derivation.
    #[test]
    fn cached_evidence_with_live_volume_equals_a_fresh_derivation() {
        let (_d, s) = store();
        let cache = s.derivations();
        deny(&s, "kimi-code", "s-k", "/etc/a");
        allow(&s, "kimi-code", "s-k2", "/tmp/fine");
        let vol = crate::derivation::WitnessedVolume { total_acts: 5_000, success_acts: 4_900 };
        let cached = cache.get(&s, "kimi-code", ROLE);
        let from_cache = crate::derivation::with_volume((*cached.evidence).clone(), Some(vol));
        let fresh = crate::derivation::derive_with_volume("kimi-code", ROLE, &crate::derivation::scan_window(&s), Some(vol));
        assert_eq!(from_cache.level, fresh.level);
        assert_eq!(from_cache.level_basis, fresh.level_basis);
        assert_eq!(from_cache.baseline_acts, fresh.baseline_acts);
        assert_eq!(from_cache.governed_acts, fresh.governed_acts);
        assert_eq!(from_cache.temperament.score, fresh.temperament.score);
    }
}
