//! The daemon's global state lock, instrumented: who waited for it, who held it, for how long.
//!
//! WHY THIS EXISTS (2026-10-07, CBP). The gate refuses with `gate.degraded` when the daemon does
//! not answer a member's policy snapshot inside the gate deadline. Round trips are normally
//! ~0.1 s; during a burst (a 1200-test suite plus several sessions and subagents calling the gate)
//! they stalled for 4.5 s and 8.3 s. A 10-minute idle probe saw zero stalls, so the periodic
//! integrity pass was refuted as the cause. Every handler serialises on ONE
//! `tokio::sync::Mutex<ServerState>` (~520 `state.lock()` sites), so anything awaited or computed
//! while it is held blocks every member — the August `/api/governance/ledger` incident (#482) was
//! the same shape. The fix plan (per-member serialisation, lock-free policy snapshots) needs a
//! measurement first: WHICH holders take the lock long enough to starve the gate. This module is
//! that measurement, and the before/after instrument for every later stage.
//!
//! WHAT IT RECORDS, per (label, call site):
//! - `wait`: from the `lock()` call to acquisition — what a caller paid in queueing.
//! - `hold`: from acquisition to the guard's drop — what a caller cost everyone else.
//!
//! The CALL SITE comes from `#[track_caller]` on [`StateCell::lock`], so none of the ~520 call
//! sites changes: `state.lock().await` keeps its spelling and is attributed to its own file:line.
//! The LABEL is a task-local set by the dispatcher (`mcp:<tool>`, `http:<route>`); a site reached
//! from a background task has no label and reports as `-`, which the site itself disambiguates.
//!
//! COST ON THE HOT PATH: two `Instant::now()` calls, and one short `std::sync::Mutex` section
//! AFTER the state lock is released (a hash lookup and a few integer adds; it allocates only the
//! first time a (label, site) pair is seen). Nothing here runs inside the state lock except
//! recording who currently holds it (a pointer-sized store under the same small mutex).
//!
//! A hold longer than the slow threshold (default 250 ms, `HESTIA_LOCK_SLOW_MS`) is logged at WARN
//! with its label, site, hold and wait, and kept in a bounded ring (the last 64) for the read-only
//! report at `GET /api/debug/locks`.

use std::collections::{HashMap, HashSet, VecDeque};
use std::future::Future;
use std::ops::{Deref, DerefMut};
use std::panic::Location;
use std::sync::{Mutex as StdMutex, OnceLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

/// Log2 histogram width: bucket `i` counts samples in `[2^i, 2^(i+1))` µs (bucket 0 also takes
/// `0`). 32 buckets reach ~71 minutes, which no lock hold should approach.
pub const BUCKETS: usize = 32;
/// How many slow holds the report keeps.
const SLOW_RING: usize = 64;
/// Interned labels are bounded so a caller inventing tool names cannot grow memory; past the cap
/// new names collapse to one label.
const LABEL_CAP: usize = 512;
const LABEL_OVERFLOW: &str = "label-overflow";
/// The label a site reports when no dispatcher set one (a background task).
pub const NO_LABEL: &str = "-";

tokio::task_local! {
    static LOCK_LABEL: &'static str;
}

/// Run `f` with every state-lock acquisition inside it attributed to `label`.
pub async fn with_label<F: Future>(label: &'static str, f: F) -> F::Output {
    LOCK_LABEL.scope(label, f).await
}

/// The label of the current task, or [`NO_LABEL`].
pub fn current_label() -> &'static str {
    LOCK_LABEL.try_with(|l| *l).unwrap_or(NO_LABEL)
}

/// Intern a dynamic label (a tool name, a matched route) as `&'static str`, bounded.
pub fn intern_label(prefix: &str, name: &str) -> &'static str {
    static TABLE: OnceLock<StdMutex<HashSet<&'static str>>> = OnceLock::new();
    let table = TABLE.get_or_init(|| StdMutex::new(HashSet::new()));
    let key = format!("{prefix}{name}");
    let mut t = table.lock().unwrap_or_else(|p| p.into_inner());
    if let Some(found) = t.get(key.as_str()) {
        return found;
    }
    if t.len() >= LABEL_CAP {
        return LABEL_OVERFLOW;
    }
    let leaked: &'static str = Box::leak(key.into_boxed_str());
    t.insert(leaked);
    leaked
}

fn slow_threshold_us() -> u64 {
    static T: OnceLock<u64> = OnceLock::new();
    *T.get_or_init(|| {
        std::env::var("HESTIA_LOCK_SLOW_MS")
            .ok()
            .and_then(|v| v.trim().parse::<u64>().ok())
            .unwrap_or(250)
            .saturating_mul(1000)
    })
}

fn bucket(us: u64) -> usize {
    if us == 0 {
        0
    } else {
        ((63 - us.leading_zeros()) as usize).min(BUCKETS - 1)
    }
}

/// The upper bound (µs) of the bucket holding the `q`-quantile of `hist`; 0 when empty.
pub fn quantile_us(hist: &[u64; BUCKETS], q: f64) -> u64 {
    let n: u64 = hist.iter().sum();
    if n == 0 {
        return 0;
    }
    let rank = ((n as f64) * q).ceil().max(1.0) as u64;
    let mut seen = 0;
    for (i, c) in hist.iter().enumerate() {
        seen += c;
        if seen >= rank {
            return 1u64 << (i + 1);
        }
    }
    1u64 << BUCKETS
}

#[derive(Clone)]
struct SiteStats {
    label: &'static str,
    site: &'static Location<'static>,
    count: u64,
    wait_sum_us: u64,
    hold_sum_us: u64,
    wait_max_us: u64,
    hold_max_us: u64,
    wait_hist: [u64; BUCKETS],
    hold_hist: [u64; BUCKETS],
}

#[derive(Clone)]
struct SlowHold {
    at_unix_ms: u64,
    label: &'static str,
    site: &'static Location<'static>,
    hold_us: u64,
    wait_us: u64,
}

struct Holder {
    label: &'static str,
    site: &'static Location<'static>,
    since: Instant,
}

#[derive(Default)]
struct StatsInner {
    sites: HashMap<(usize, usize), SiteStats>,
    slow: VecDeque<SlowHold>,
    slow_total: u64,
    holder: Option<Holder>,
    /// Acquisitions currently queued (called `lock()`, not yet acquired).
    waiting: u64,
    started: Option<Instant>,
}

/// Lock statistics for one [`StateCell`].
pub struct LockStats {
    inner: StdMutex<StatsInner>,
    /// What a sample is ("state lock hold", "section"), for the slow-hold log line.
    kind: &'static str,
}

impl LockStats {
    fn new(kind: &'static str) -> Self {
        let inner = StatsInner { started: Some(Instant::now()), ..Default::default() };
        Self { inner: StdMutex::new(inner), kind }
    }

    fn with<R>(&self, f: impl FnOnce(&mut StatsInner) -> R) -> R {
        let mut g = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        f(&mut g)
    }

    fn record(&self, label: &'static str, site: &'static Location<'static>, wait_us: u64, hold_us: u64) {
        let slow = hold_us >= slow_threshold_us();
        self.with(|s| {
            let key = (label.as_ptr() as usize, site as *const Location<'static> as usize);
            let e = s.sites.entry(key).or_insert_with(|| SiteStats {
                label,
                site,
                count: 0,
                wait_sum_us: 0,
                hold_sum_us: 0,
                wait_max_us: 0,
                hold_max_us: 0,
                wait_hist: [0; BUCKETS],
                hold_hist: [0; BUCKETS],
            });
            e.count += 1;
            e.wait_sum_us = e.wait_sum_us.saturating_add(wait_us);
            e.hold_sum_us = e.hold_sum_us.saturating_add(hold_us);
            e.wait_max_us = e.wait_max_us.max(wait_us);
            e.hold_max_us = e.hold_max_us.max(hold_us);
            e.wait_hist[bucket(wait_us)] += 1;
            e.hold_hist[bucket(hold_us)] += 1;
            if slow {
                s.slow_total += 1;
                if s.slow.len() >= SLOW_RING {
                    s.slow.pop_front();
                }
                let at_unix_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_millis() as u64)
                    .unwrap_or(0);
                s.slow.push_back(SlowHold { at_unix_ms, label, site, hold_us, wait_us });
            }
        });
        if slow {
            tracing::warn!(
                label,
                site = %format!("{}:{}", site.file(), site.line()),
                hold_ms = hold_us / 1000,
                wait_ms = wait_us / 1000,
                kind = self.kind,
                "slow past the threshold (state-lock instrumentation)"
            );
        }
    }

    /// The read-only report: per (label, site) rows sorted by total hold, the same aggregated by
    /// label, the slow ring, and who holds the lock right now. Raw histograms ride along so a
    /// load tool can diff two reports and compute percentiles over just its own window.
    pub fn report(&self) -> Value {
        let (rows, slow, slow_total, holder, waiting, uptime_s) = self.with(|s| {
            let rows: Vec<SiteStats> = s.sites.values().cloned().collect();
            let slow: Vec<SlowHold> = s.slow.iter().cloned().collect();
            let holder = s.holder.as_ref().map(|h| {
                json!({
                    "label": h.label,
                    "site": format!("{}:{}", h.site.file(), h.site.line()),
                    "held_ms": h.since.elapsed().as_millis() as u64,
                })
            });
            let up = s.started.map(|t| t.elapsed().as_secs()).unwrap_or(0);
            (rows, slow, s.slow_total, holder, s.waiting, up)
        });

        let row_json = |label: &str, site: Option<String>, count: u64, wsum: u64, hsum: u64,
                        wmax: u64, hmax: u64, wh: &[u64; BUCKETS], hh: &[u64; BUCKETS]| {
            json!({
                "label": label,
                "site": site,
                "count": count,
                "hold_total_ms": hsum / 1000,
                "wait_total_ms": wsum / 1000,
                "hold_p50_us": quantile_us(hh, 0.50),
                "hold_p95_us": quantile_us(hh, 0.95),
                "hold_max_us": hmax,
                "wait_p50_us": quantile_us(wh, 0.50),
                "wait_p95_us": quantile_us(wh, 0.95),
                "wait_max_us": wmax,
                "hold_hist": hh.to_vec(),
                "wait_hist": wh.to_vec(),
            })
        };

        let mut by_site = rows.clone();
        by_site.sort_by(|a, b| b.hold_sum_us.cmp(&a.hold_sum_us));
        let sites: Vec<Value> = by_site
            .iter()
            .map(|r| {
                row_json(r.label, Some(format!("{}:{}", r.site.file(), r.site.line())), r.count,
                         r.wait_sum_us, r.hold_sum_us, r.wait_max_us, r.hold_max_us,
                         &r.wait_hist, &r.hold_hist)
            })
            .collect();

        let mut agg: HashMap<&'static str, SiteStats> = HashMap::new();
        for r in &rows {
            let e = agg.entry(r.label).or_insert_with(|| SiteStats {
                count: 0,
                wait_sum_us: 0,
                hold_sum_us: 0,
                wait_max_us: 0,
                hold_max_us: 0,
                wait_hist: [0; BUCKETS],
                hold_hist: [0; BUCKETS],
                ..r.clone()
            });
            e.count += r.count;
            e.wait_sum_us += r.wait_sum_us;
            e.hold_sum_us += r.hold_sum_us;
            e.wait_max_us = e.wait_max_us.max(r.wait_max_us);
            e.hold_max_us = e.hold_max_us.max(r.hold_max_us);
            for i in 0..BUCKETS {
                e.wait_hist[i] += r.wait_hist[i];
                e.hold_hist[i] += r.hold_hist[i];
            }
        }
        let mut by_label: Vec<SiteStats> = agg.into_values().collect();
        by_label.sort_by(|a, b| b.hold_sum_us.cmp(&a.hold_sum_us));
        let labels: Vec<Value> = by_label
            .iter()
            .map(|r| {
                row_json(r.label, None, r.count, r.wait_sum_us, r.hold_sum_us, r.wait_max_us,
                         r.hold_max_us, &r.wait_hist, &r.hold_hist)
            })
            .collect();

        json!({
            "schema": "hestia.state_lock_stats.v1",
            "uptime_s": uptime_s,
            "slow_threshold_ms": slow_threshold_us() / 1000,
            "bucket_rule": "hist[i] counts samples in [2^i, 2^(i+1)) microseconds; \
                            p50/p95 are bucket upper bounds",
            "held_now": holder,
            "waiting_now": waiting,
            "slow_total": slow_total,
            "slow_recent": slow.iter().map(|h| json!({
                "at_unix_ms": h.at_unix_ms,
                "label": h.label,
                "site": format!("{}:{}", h.site.file(), h.site.line()),
                "hold_ms": h.hold_us / 1000,
                "wait_ms": h.wait_us / 1000,
            })).collect::<Vec<_>>(),
            "by_label": labels,
            "by_site": sites,
        })
    }
}

/// Timings for named synchronous SECTIONS that run inside a hold — the chain append, the trust
/// store write, a vault save. The lock report says WHO held the lock long; this says WHAT they
/// were doing. Same histograms, keyed by (section name, call site); `wait` is always 0.
pub fn sections() -> &'static LockStats {
    static S: OnceLock<LockStats> = OnceLock::new();
    S.get_or_init(|| LockStats::new("section"))
}

/// Time `f` as section `name`, attributed to the caller's site (the task label is not used: a
/// section is about the work, not the requester). Logged and ringed like a lock hold when it
/// crosses the slow threshold.
#[track_caller]
pub fn time_section<R>(name: &'static str, f: impl FnOnce() -> R) -> R {
    let site = Location::caller();
    let t = Instant::now();
    let r = f();
    sections().record(name, site, 0, t.elapsed().as_micros() as u64);
    r
}

/// State that publishes an immutable snapshot for lock-free readers (stage 2,
/// `server::published`). `on_release` runs at EVERY guard release, while the lock is still held,
/// and swaps a new snapshot into `slot` when the state's published inputs changed — so a write
/// is never visible to lock takers before it is visible to snapshot readers.
pub trait Publish {
    type Snapshot: Send + Sync + 'static;
    fn initial_snapshot(&mut self) -> Self::Snapshot;
    fn on_release(&mut self, slot: &std::sync::RwLock<std::sync::Arc<Self::Snapshot>>);
}

/// The shared state's lock: a `tokio::sync::Mutex` that measures itself, plus the published
/// snapshot slot readers use without taking it.
pub struct StateCell<T: Publish> {
    inner: tokio::sync::Mutex<T>,
    stats: LockStats,
    published: std::sync::RwLock<std::sync::Arc<T::Snapshot>>,
}

impl<T: Publish> StateCell<T> {
    pub fn new(mut value: T) -> Self {
        let snap = std::sync::Arc::new(value.initial_snapshot());
        Self {
            inner: tokio::sync::Mutex::new(value),
            stats: LockStats::new("state lock hold"),
            published: std::sync::RwLock::new(snap),
        }
    }

    /// The current published snapshot — never takes the state lock. The slot's own lock is held
    /// only for an `Arc` clone (a writer holds it only for the swap).
    pub fn published(&self) -> std::sync::Arc<T::Snapshot> {
        self.published.read().unwrap_or_else(|p| p.into_inner()).clone()
    }

    pub fn stats(&self) -> &LockStats {
        &self.stats
    }

    /// Acquire the lock. Attributed to the CALLER's file:line (`#[track_caller]` is applied to
    /// this synchronous fn, which returns the future — `#[track_caller]` on an `async fn` is not
    /// stable) and to the current task's label.
    #[track_caller]
    pub fn lock(&self) -> impl Future<Output = StateGuard<'_, T>> + '_ {
        let site = Location::caller();
        let label = current_label();
        let called = Instant::now();
        async move {
            self.stats.with(|s| s.waiting += 1);
            // If this future is dropped while queued (a cancelled request), the waiting count
            // must still come back down.
            struct Queued<'a>(&'a LockStats, bool);
            impl Drop for Queued<'_> {
                fn drop(&mut self) {
                    if self.1 {
                        self.0.with(|s| s.waiting = s.waiting.saturating_sub(1));
                    }
                }
            }
            let mut q = Queued(&self.stats, true);
            let g = self.inner.lock().await;
            q.1 = false;
            drop(q);
            let acquired = Instant::now();
            self.stats.with(|s| {
                s.waiting = s.waiting.saturating_sub(1);
                s.holder = Some(Holder { label, site, since: acquired });
            });
            StateGuard { guard: Some(g), cell: self, site, label, acquired, called }
        }
    }

    /// Non-blocking acquisition; `None` when held. A success is attributed like `lock` (wait 0).
    #[track_caller]
    pub fn try_lock(&self) -> Option<StateGuard<'_, T>> {
        let site = Location::caller();
        let label = current_label();
        let g = self.inner.try_lock().ok()?;
        let acquired = Instant::now();
        self.stats.with(|s| s.holder = Some(Holder { label, site, since: acquired }));
        Some(StateGuard { guard: Some(g), cell: self, site, label, acquired, called: acquired })
    }

    /// Blocking acquisition for synchronous test code; attributed the same way.
    #[track_caller]
    pub fn blocking_lock(&self) -> StateGuard<'_, T> {
        let site = Location::caller();
        let label = current_label();
        let called = Instant::now();
        let g = self.inner.blocking_lock();
        let acquired = Instant::now();
        self.stats.with(|s| s.holder = Some(Holder { label, site, since: acquired }));
        StateGuard { guard: Some(g), cell: self, site, label, acquired, called }
    }
}

/// A held state lock. Derefs to the state; records its hold time when dropped.
pub struct StateGuard<'a, T: Publish> {
    guard: Option<tokio::sync::MutexGuard<'a, T>>,
    cell: &'a StateCell<T>,
    site: &'static Location<'static>,
    label: &'static str,
    acquired: Instant,
    called: Instant,
}

impl<T: Publish> Deref for StateGuard<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        self.guard.as_deref().expect("guard present until drop")
    }
}

impl<T: Publish> DerefMut for StateGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        self.guard.as_deref_mut().expect("guard present until drop")
    }
}

impl<T: Publish> Drop for StateGuard<'_, T> {
    fn drop(&mut self) {
        // Republish (if anything published changed) BEFORE the lock is released.
        if let Some(g) = self.guard.as_deref_mut() {
            g.on_release(&self.cell.published);
        }
        // Clear the holder BEFORE releasing, so a report never names a holder that has left.
        self.cell.stats.with(|s| s.holder = None);
        let released = Instant::now();
        drop(self.guard.take());
        let wait_us = self.acquired.duration_since(self.called).as_micros() as u64;
        let hold_us = released.duration_since(self.acquired).as_micros() as u64;
        self.cell.stats.record(self.label, self.site, wait_us, hold_us);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    impl Publish for u32 {
        type Snapshot = u32;
        fn initial_snapshot(&mut self) -> u32 {
            *self
        }
        fn on_release(&mut self, slot: &std::sync::RwLock<std::sync::Arc<u32>>) {
            *slot.write().unwrap() = std::sync::Arc::new(*self);
        }
    }
    impl Publish for () {
        type Snapshot = ();
        fn initial_snapshot(&mut self) {}
        fn on_release(&mut self, _: &std::sync::RwLock<std::sync::Arc<()>>) {}
    }

    /// The published snapshot moves with the release that changed the state, not later.
    #[tokio::test]
    async fn a_release_publishes_before_the_next_reader() {
        let cell = StateCell::new(1u32);
        assert_eq!(*cell.published(), 1);
        {
            let mut g = cell.lock().await;
            *g = 7;
            assert_eq!(*cell.published(), 1, "not visible while the writer still holds the lock");
        }
        assert_eq!(*cell.published(), 7);
    }
    use std::sync::Arc;
    use std::time::Duration;

    fn rows_for<'a>(report: &'a Value, label: &str) -> Vec<&'a Value> {
        report["by_site"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["label"] == label)
            .collect()
    }

    #[test]
    fn buckets_and_quantiles() {
        assert_eq!(bucket(0), 0);
        assert_eq!(bucket(1), 0);
        assert_eq!(bucket(2), 1);
        assert_eq!(bucket(1023), 9);
        assert_eq!(bucket(1024), 10);
        assert_eq!(bucket(u64::MAX), BUCKETS - 1);
        let mut h = [0u64; BUCKETS];
        h[3] = 90; // [8,16) µs
        h[10] = 10; // [1024,2048) µs
        assert_eq!(quantile_us(&h, 0.50), 16);
        assert_eq!(quantile_us(&h, 0.95), 2048);
        assert_eq!(quantile_us(&[0; BUCKETS], 0.5), 0);
    }

    /// Each acquisition is attributed to the line that called `lock()` and to the task's label —
    /// the property that lets one wrapper attribute ~520 unchanged call sites.
    #[tokio::test]
    async fn attributes_to_caller_site_and_task_label() {
        let cell = StateCell::new(0u32);
        let line = line!() + 1;
        with_label("mcp:test_tool", async { *cell.lock().await += 1 }).await;
        *cell.lock().await += 1;
        let r = cell.stats().report();
        let rows = rows_for(&r, "mcp:test_tool");
        assert_eq!(rows.len(), 1, "{r:#}");
        assert_eq!(rows[0]["count"], 1);
        let site = rows[0]["site"].as_str().unwrap();
        assert!(site.ends_with(&format!("state_lock.rs:{line}")), "site {site} vs line {line}");
        assert_eq!(rows_for(&r, NO_LABEL).len(), 1, "an unlabelled caller reports as '-'");
    }

    /// Wait is what the queued caller paid; hold is what the holder cost. A holder that sleeps
    /// 120 ms must show >= 120 ms hold, and the waiter queued behind it >= ~100 ms wait.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn measures_wait_and_hold_separately() {
        let cell = Arc::new(StateCell::new(()));
        let (tx, rx) = tokio::sync::oneshot::channel::<()>();
        let c1 = cell.clone();
        let holder = tokio::spawn(with_label("holder", async move {
            let _g = c1.lock().await;
            tx.send(()).unwrap();
            tokio::time::sleep(Duration::from_millis(120)).await;
        }));
        rx.await.unwrap();
        let c2 = cell.clone();
        let waiter = tokio::spawn(with_label("waiter", async move {
            let _g = c2.lock().await;
        }));
        holder.await.unwrap();
        waiter.await.unwrap();
        let r = cell.stats().report();
        let h = rows_for(&r, "holder")[0];
        let w = rows_for(&r, "waiter")[0];
        assert!(h["hold_max_us"].as_u64().unwrap() >= 120_000, "{h:#}");
        assert!(w["wait_max_us"].as_u64().unwrap() >= 90_000, "{w:#}");
        assert!(w["hold_max_us"].as_u64().unwrap() < 50_000, "{w:#}");
        assert_eq!(r["waiting_now"], 0);
        assert!(r["held_now"].is_null());
    }

    /// A hold past the threshold lands in the slow ring (default threshold 250 ms).
    #[tokio::test]
    async fn a_slow_hold_is_kept_in_the_ring() {
        let cell = StateCell::new(());
        with_label("slowpoke", async {
            let _g = cell.lock().await;
            tokio::time::sleep(Duration::from_millis(slow_threshold_us() / 1000 + 20)).await;
        })
        .await;
        let r = cell.stats().report();
        assert_eq!(r["slow_total"], 1, "{r:#}");
        assert_eq!(r["slow_recent"][0]["label"], "slowpoke");
    }

    /// A cancelled acquisition (the request went away while queued) does not leave the waiting
    /// count stuck high.
    #[tokio::test]
    async fn a_cancelled_wait_is_not_counted_forever() {
        let cell = Arc::new(StateCell::new(()));
        let g = cell.lock().await;
        let c = cell.clone();
        let t = tokio::spawn(async move {
            let _ = c.lock().await;
        });
        tokio::time::sleep(Duration::from_millis(20)).await;
        assert_eq!(cell.stats().report()["waiting_now"], 1);
        t.abort();
        let _ = t.await;
        drop(g);
        assert_eq!(cell.stats().report()["waiting_now"], 0);
    }

    #[test]
    fn interned_labels_are_stable_and_bounded() {
        let a = intern_label("mcp:", "hestia_connect");
        let b = intern_label("mcp:", "hestia_connect");
        assert!(std::ptr::eq(a, b));
        assert_eq!(a, "mcp:hestia_connect");
    }
}
