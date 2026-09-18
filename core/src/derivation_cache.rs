//! Denial-triggered trust derivation.
//!
//! dp, 2026-09-17: "trust derivation should be event-triggered not timed. a negative event
//! would trigger trust derivation for the affected member. all should be derived on start
//! and maybe once a day." And, on a first cut that also re-derived on rulings, appeals,
//! aliases and allows near a deny: "is it on any event? because that's continuous. should be
//! on denials only."
//!
//! WHY THIS EXISTS. Every derived trust level was recomputed from scratch on every read:
//! `derivation::scan_window` decrypts and parses 10,000 outcome rows plus up to 100,000
//! governance rows, and the dashboard asked for it on every 2-second poll. Benched on a
//! 150,000-row chain of CBP's shape that scan took 1.26–1.53 s, and it was most of the
//! daemon's CPU while the operator had the page open (hestia #1040) — to recompute numbers
//! that had not changed, because nothing that could change them had happened.
//!
//! THE RULE. A member's derivation is cached. It is re-derived when a DENY naming that member
//! lands on the chain — and once more when that deny's retry window closes, because what the
//! member did next (retried the act: 0.0; reached the same resource another way: 0.35;
//! adapted: 0.85) is only fully on the chain then. Both are triggered by the denial; nothing
//! else the member or anyone else does triggers anything. The rule is applied in
//! `SqliteChainStore::append`, the one path every chain write takes.
//!
//! Everything a deny does not cover — a ruling on an appeal or escalation, an alias, an
//! exoneration or amnesty, the slow drift of governed volume and of the window itself — is
//! picked up when everyone is re-derived: at start, and once a day
//! ([`EVERYONE_REDERIVE_EVERY`]). That is the stated trade: a member whose appeal is upheld
//! sees the higher number within a day, not within a poll.
//!
//! WHAT IS CACHED AND WHAT IS NOT. Only the window half ([`crate::derivation::derive_evidence`]).
//! The volume half ([`crate::derivation::with_volume`]) is applied at read time from the
//! grain's live lifetime totals, so routine outcomes — 78% of the chain — never trigger a
//! re-derivation and never leave the displayed volume stale.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use chrono::Utc;
use serde_json::Value;

use crate::derivation::{aliased_identities, alias_target, DerivedTrust, RETRY_WINDOW_MINUTES};
use crate::storage::chain::{ChainEntry, SqliteChainStore};

/// Everyone is re-derived at least this often, whatever the denial rule says.
pub const EVERYONE_REDERIVE_EVERY: Duration = Duration::from_secs(24 * 60 * 60);

/// Denials arriving in a burst are coalesced into one derivation.
///
/// A member hitting a boundary repeatedly lands a deny every few seconds, and each one
/// invalidates it. Re-scanning per deny would put the 1.3 s scan back on every poll for as
/// long as the burst lasts — the load this module removes. A member whose cached derivation
/// is invalidated is re-derived at the first read at least this long after the previous
/// scan; the first deny after a quiet spell is re-derived at the next read. A grain with NO
/// cached derivation is never held back by this.
pub const EVENT_COALESCE: Duration = Duration::from_secs(10);

/// How long after a deny its follow-up re-derivation fires: the retry window `derive` scores
/// against, plus a margin so the window is closed on the chain's clock too.
fn recheck_after() -> Duration {
    Duration::from_secs(RETRY_WINDOW_MINUTES as u64 * 60) + Duration::from_secs(5)
}

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
    /// aliases), with the epoch each had when the window was read. A deny naming ANY of
    /// them invalidates the grain — an alias's deny is the member's deny.
    member_epochs: Vec<(String, u64)>,
}

#[derive(Default)]
struct Inner {
    everyone_epoch: u64,
    everyone_since: Option<Instant>,
    member_epoch: HashMap<String, u64>,
    /// Per member, when its latest deny's retry window closes. One entry per member however
    /// many denies it lands: a later deny moves the time, it does not add a second recheck.
    rechecks: HashMap<String, Instant>,
    /// Known grains. `None` = asked for, not yet derived.
    grains: HashMap<(String, String), Option<CachedDerivation>>,
    last_scan: Option<Instant>,
    /// Whether pending follow-ups have been re-learned from the chain since start. Once only:
    /// re-learning on every scan would re-schedule a follow-up that has just fired.
    relearned: bool,
}

impl Inner {
    fn is_current(&self, c: &CachedDerivation) -> bool {
        c.everyone_epoch == self.everyone_epoch
            && c.member_epochs
                .iter()
                .all(|(id, ep)| self.member_epoch.get(id).copied().unwrap_or(0) == *ep)
    }

    /// Start of day, and closed retry windows: the two things besides a deny that make a
    /// derivation stale, both settled here before anyone asks what is due.
    fn settle(&mut self, now: Instant) {
        match self.everyone_since {
            Some(t) if now.saturating_duration_since(t) < EVERYONE_REDERIVE_EVERY => {}
            _ => {
                self.everyone_epoch += 1;
                self.everyone_since = Some(now);
            }
        }
        let closed: Vec<String> = self
            .rechecks
            .iter()
            .filter(|(_, at)| **at <= now)
            .map(|(m, _)| m.clone())
            .collect();
        for m in closed {
            self.rechecks.remove(&m);
            self.bump(&m);
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

    fn schedule_recheck(&mut self, member: &str, at: Instant) {
        let slot = self.rechecks.entry(member.to_string()).or_insert(at);
        if at > *slot {
            *slot = at;
        }
    }
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
    /// behind by a panicking holder is at worst stale, and the next deny or the daily
    /// re-derivation corrects it.
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// The trigger: the member a chain entry DENIES, or `None`. Nothing else triggers.
    ///
    /// Deliberately looser than the deny `derive` scores (it also excludes probe sessions,
    /// no-verdict denies and unenforced ones): a re-derivation that changes nothing costs one
    /// scan, while a deny the trigger skipped would show the member a number its record has
    /// already contradicted until tomorrow.
    pub fn denied_member(e: &ChainEntry) -> Option<&str> {
        if e.event_type != "policy_decision" || flat_or_data(e, "decision") != Some("deny") {
            return None;
        }
        flat_or_data(e, "plugin_id").filter(|p| !p.is_empty())
    }

    /// Called by `SqliteChainStore::append` after an entry is durably committed.
    ///
    /// Ordering is what makes the cache sound: the invalidation lands AFTER the row is
    /// readable, and [`Self::refresh`] captures epochs BEFORE it scans. So a scan either sees
    /// the row, or its result is recorded under the old epoch and is already stale.
    pub fn observe(&self, e: &ChainEntry) {
        let Some(member) = Self::denied_member(e) else { return };
        let mut inner = self.lock();
        inner.bump(member);
        inner.schedule_recheck(member, Instant::now() + recheck_after());
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
        inner.settle(now);
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
            inner.settle(now);
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
        // A restart forgets pending rechecks. Re-learn them from the window on the first scan,
        // so a deny whose retry window straddles a restart still gets its follow-up.
        let wall_now = Utc::now();
        let window_len = chrono::Duration::minutes(RETRY_WINDOW_MINUTES);
        let mut inner = self.lock();
        let relearn = !std::mem::replace(&mut inner.relearned, true);
        for e in window.iter().filter(|_| relearn) {
            let Some(member) = Self::denied_member(e) else { continue };
            let closes_in = e.timestamp + window_len - wall_now;
            if let Ok(left) = closes_in.to_std() {
                inner.schedule_recheck(member, now + left + Duration::from_secs(5));
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
    use crate::derivation::IDENTITY_ALIAS_EVENT;
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

    /// The member's retry window, closed now instead of in ten minutes.
    fn close_retry_windows(c: &DerivationCache) {
        let mut inner = c.inner.lock().unwrap();
        let past = Instant::now() - Duration::from_secs(1);
        for at in inner.rechecks.values_mut() {
            *at = past;
        }
    }

    /// dp's rule, end to end through the real append path: a deny re-derives the member it
    /// names, and nobody else; everything else re-derives nobody.
    #[test]
    fn only_a_deny_rederives_and_only_its_member() {
        let (_d, s) = store();
        let cache = s.derivations();
        deny(&s, "kimi-code", "s-k", "/etc/a");
        assert!(cache.lookup("kimi-code", ROLE).is_none(), "never derived");
        assert!(cache.lookup("codex", ROLE).is_none());
        assert_eq!(cache.refresh(&s), 2, "everyone is derived on first use");
        assert_eq!(cache.refresh(&s), 0, "nothing happened: nothing is re-derived");
        assert_eq!(cache.lookup("kimi-code", ROLE).unwrap().evidence.temperament.observations, 1);

        // Everything that is not a deny: routine traffic, allows, the governance acts a first
        // cut also triggered on. None of it re-derives anyone.
        for _ in 0..50 {
            outcome(&s, "codex");
            allow(&s, "codex", "s-c", "/tmp/fine");
        }
        s.append("appeal", json!({"plugin_id": "kimi-code", "deny_hash": "ab"}), "lct:test").unwrap();
        s.append("adjudication", json!({"subject_plugin_id": "kimi-code", "about_deny_hash": "ab", "upheld": true}), "lct:test").unwrap();
        s.append("gate_escalation_decided", json!({"plugin_id": "codex", "status": "approved"}), "lct:test").unwrap();
        s.append(IDENTITY_ALIAS_EVENT, json!({"alias": "codex-cli", "alias_of": "codex"}), "lct:test").unwrap();
        s.append("amnesty", json!({"data": {"class": "deny", "before_position": 0}}), "lct:test").unwrap();
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 0, "no deny, no derivation — however much else happened");

        deny(&s, "kimi-code", "s-k", "/etc/b");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1, "the deny re-derives exactly its member");
        assert_eq!(cache.lookup("kimi-code", ROLE).unwrap().evidence.temperament.observations, 2,
                   "and the re-derivation sees it");
    }

    /// The trigger itself, per event type.
    #[test]
    fn the_trigger_is_a_deny_and_nothing_else() {
        let e = |ty: &str, data: serde_json::Value| ChainEntry {
            hash: "h".into(), prev_hash: "p".into(), timestamp: Utc::now(),
            event_type: ty.into(), event_data: data, signer_lct: String::new(), chain_position: 1,
        };
        assert_eq!(DerivationCache::denied_member(&e("policy_decision", json!({"plugin_id": "kimi-code", "decision": "deny"}))), Some("kimi-code"));
        assert_eq!(DerivationCache::denied_member(&e("policy_decision", json!({"data": {"plugin_id": "codex", "decision": "deny"}}))), Some("codex"));
        for (ty, data) in [
            ("policy_decision", json!({"plugin_id": "kimi-code", "decision": "allow"})),
            ("policy_decision", json!({"plugin_id": "kimi-code", "decision": "warn"})),
            ("policy_decision", json!({"decision": "deny"})),
            ("outcome", json!({"plugin_id": "kimi-code", "success": false})),
            ("adjudication", json!({"subject_plugin_id": "kimi-code", "upheld": false})),
            ("appeal", json!({"plugin_id": "kimi-code"})),
            ("gate_escalation_decided", json!({"plugin_id": "kimi-code", "status": "denied"})),
            ("exoneration", json!({"data": {"deny_hash": "ab"}})),
        ] {
            assert_eq!(DerivationCache::denied_member(&e(ty, data.clone())), None, "{ty} {data}");
        }
    }

    /// What a member does after a deny is scored against the deny — a retry is 0.0 — but
    /// that act is not itself a trigger. The deny's own follow-up, when its retry window
    /// closes, is what picks it up.
    #[test]
    fn a_retry_is_seen_when_the_denys_retry_window_closes() {
        let (_d, s) = store();
        let cache = s.derivations();
        cache.lookup("kimi-code", ROLE);
        deny(&s, "kimi-code", "s-k", "/etc/shadow-copy");
        cache.refresh(&s);
        let score = |c: &DerivationCache| c.lookup("kimi-code", ROLE).unwrap().evidence.temperament.score;
        assert!(score(cache).unwrap() > 0.5, "a deny that stands, not yet retried");

        allow(&s, "kimi-code", "s-k", "/etc/shadow-copy");
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 0, "the retry is an allow: not a trigger");
        assert!(score(cache).unwrap() > 0.5, "so the cached number has not moved yet");

        close_retry_windows(cache);
        past_coalesce(cache);
        assert_eq!(cache.refresh(&s), 1, "the deny's window closed: its member is re-derived");
        assert!(score(cache).unwrap() < 0.5, "and the retry now counts against it");
        assert!(cache.inner.lock().unwrap().rechecks.is_empty(), "one follow-up, then none");
    }

    /// Many denies from one member leave ONE pending follow-up, at the latest window.
    #[test]
    fn repeated_denies_keep_one_follow_up() {
        let (_d, s) = store();
        let cache = s.derivations();
        for i in 0..20 {
            deny(&s, "kimi-code", "s-k", &format!("/etc/{i}"));
        }
        assert_eq!(cache.inner.lock().unwrap().rechecks.len(), 1);
    }

    /// A deny whose retry window straddles a restart still gets its follow-up: a fresh cache
    /// re-learns it from the chain on its first scan.
    #[test]
    fn a_restart_relearns_pending_follow_ups() {
        let (_d, s) = store();
        deny(&s, "kimi-code", "s-k", "/etc/a");
        let fresh = DerivationCache::new();
        fresh.lookup("kimi-code", ROLE);
        fresh.refresh(&s);
        assert!(fresh.inner.lock().unwrap().rechecks.contains_key("kimi-code"));
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

    /// Once a day everyone is re-derived, whatever happened — the path that carries rulings,
    /// aliases and amnesties.
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
