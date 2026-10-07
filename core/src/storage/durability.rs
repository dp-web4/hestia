//! GROUP COMMIT for the witness chain: commit under the state lock, fsync outside it, and reply
//! only once durable.
//!
//! WHY (2026-10-07, measured with the stage-1 lock instrumentation). `record_outcome` was the
//! top holder of the daemon's one global lock at every concurrency level, and ~97% of its hold
//! was `chain.append` — the per-commit WAL fsync, done while every other member waited. Under
//! disk pressure that fsync's p95 was 65-131 ms with single appends past 2 s; the read-only gate
//! snapshot calls (hold < 1 ms) queued behind it for seconds, and the gate fails closed at 8.5 s.
//!
//! THE SHAPE. The write connection runs WAL with `synchronous=NORMAL`: the INSERT and COMMIT
//! still happen synchronously, under the state lock, in lock order — so
//!   - memory and the chain agree on order (commit order IS lock order), and
//!   - every append error surfaces synchronously, exactly as before, to the handler that can
//!     undo its own in-memory change (`undo_decide`, "no committed row, no charge", …).
//! What NORMAL removes is the fsync inside COMMIT. That fsync moves here: one flusher thread
//! fsyncs the WAL file ONCE for every commit made so far (the group), then advances `durable`
//! and wakes every waiter. A request that appended waits — after releasing the state lock —
//! until `durable` covers its last entry, and only then replies ([`durable_scope`]).
//!
//! - No caller is told "recorded" before its entry's fsync returned.
//! - A crash before the fsync loses only unacknowledged entries; one sequential WAL and one
//!   flusher mean a later durable entry implies every earlier one (SQLite discards WAL frames
//!   after the first bad checksum, so recovery is always a prefix).
//! - An fsync FAILURE is fatal ([`Durability::poisoned`]): after EIO the kernel may already have
//!   dropped the dirty pages, so the outcome of every unacknowledged commit is unknown and a
//!   retried fsync proves nothing (PostgreSQL panics on the same condition since 2018,
//!   "fsyncgate"). Waiters get an error, every later append is refused, and the fatal hook
//!   (the daemon: exit, systemd restarts it) rebuilds memory from what the chain actually holds.
//!   Memory is never allowed to run on ahead of the chain.
//!
//! CHECKPOINTS LEAVE THE COMMIT PATH. SQLite's default auto-checkpoint runs INSIDE the commit
//! that pushes the WAL past 1000 pages — i.e. under the state lock, every few hundred appends,
//! copying pages into a 565 MB database and fsyncing it. The write connection disables it
//! (`wal_autocheckpoint=0`); this thread runs a PASSIVE checkpoint on its own connection when
//! the chain is idle (or the WAL passes a size bound), timed as section `chain.checkpoint`.

use std::cell::RefCell;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Result};

/// Checkpoint when the chain has been idle this long…
const CHECKPOINT_IDLE: Duration = Duration::from_secs(2);
/// …or regardless of idleness once the WAL passes this size.
const CHECKPOINT_FORCE_BYTES: u64 = 64 * 1024 * 1024;
/// Below this the WAL is not worth a checkpoint.
const CHECKPOINT_MIN_BYTES: u64 = 1024 * 1024;

/// The durability frontier, published to async waiters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Frontier {
    /// Entries `[0, durable)` are fsynced.
    pub durable: u64,
    pub poisoned: bool,
}

#[derive(Default)]
struct Req {
    /// Highest committed length any waiter has asked to be made durable.
    wanted: u64,
    shutdown: bool,
}

/// One per chain store. Shared with its flusher thread.
pub struct Durability {
    wal_path: PathBuf,
    dir_path: PathBuf,
    db_path: PathBuf,
    key_hex: String,
    /// Committed entry count — the chain store's own `len`, shared.
    committed: Arc<AtomicU64>,
    /// Millis since `epoch` of the last commit, for the idle checkpoint.
    last_commit_ms: AtomicU64,
    epoch: Instant,
    req: Mutex<Req>,
    cv: Condvar,
    /// Serialises fsyncs (flusher vs inline). Never touched from async code: a tokio worker must
    /// not block behind an fsync.
    sync_lock: Mutex<()>,
    frontier: tokio::sync::watch::Sender<Frontier>,
    flusher_started: AtomicBool,
    /// fsyncs performed — a group commit shows far fewer of these than appends.
    pub fsyncs: AtomicU64,
    pub checkpoints: AtomicU64,
    /// Test-only fault injection: the next fsync reports failure.
    fail_next_sync: AtomicBool,
    /// Test-only: while set, nothing becomes durable (holds the window between commit and fsync
    /// open, deterministically).
    hold: AtomicBool,
    last_wal_ino: AtomicU64,
}

/// Called once when durability is lost (the daemon sets it to exit so systemd restarts it and
/// state is rebuilt from the chain). Unset in tests and library use: the store still refuses
/// every append once poisoned.
static FATAL_HOOK: OnceLock<Box<dyn Fn(&str) + Send + Sync>> = OnceLock::new();

pub fn set_fatal_hook(f: Box<dyn Fn(&str) + Send + Sync>) {
    let _ = FATAL_HOOK.set(f);
}

impl Durability {
    pub(crate) fn new(db_path: &Path, key_hex: &str, committed: Arc<AtomicU64>) -> Arc<Self> {
        let mut wal = db_path.as_os_str().to_owned();
        wal.push("-wal");
        // Starts at 0: the store's open syncs whatever a previous run left committed.
        let (tx, _rx) = tokio::sync::watch::channel(Frontier { durable: 0, poisoned: false });
        Arc::new(Self {
            wal_path: PathBuf::from(wal),
            dir_path: db_path.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from(".")),
            db_path: db_path.to_path_buf(),
            key_hex: key_hex.to_string(),
            committed,
            last_commit_ms: AtomicU64::new(0),
            epoch: Instant::now(),
            req: Mutex::new(Req::default()),
            cv: Condvar::new(),
            sync_lock: Mutex::new(()),
            frontier: tx,
            flusher_started: AtomicBool::new(false),
            fsyncs: AtomicU64::new(0),
            checkpoints: AtomicU64::new(0),
            fail_next_sync: AtomicBool::new(false),
            hold: AtomicBool::new(false),
            last_wal_ino: AtomicU64::new(0),
        })
    }

    pub fn frontier(&self) -> Frontier {
        *self.frontier.borrow()
    }

    pub fn poisoned(&self) -> bool {
        self.frontier().poisoned
    }

    /// Record a commit that produced committed length `len` (called by the store, under its
    /// connection mutex, right after COMMIT returned).
    pub(crate) fn note_commit(&self) {
        self.last_commit_ms
            .store(self.epoch.elapsed().as_millis() as u64, Ordering::Release);
    }

    /// Test hook: make the next fsync fail, as EIO would.
    #[doc(hidden)]
    pub fn inject_sync_failure(&self) {
        self.fail_next_sync.store(true, Ordering::Release);
    }

    /// Test hook: hold every fsync until the returned guard drops (the commit-to-fsync window,
    /// held open). A guard, so a failing assertion releases it while unwinding instead of leaving
    /// the store's drop-time flush waiting forever.
    #[doc(hidden)]
    pub fn hold_flush_for_test(self: &Arc<Self>) -> FlushHold {
        self.hold.store(true, Ordering::Release);
        FlushHold(self.clone())
    }

    /// Committed entry count (what a flush now would make durable).
    pub fn committed(&self) -> u64 {
        self.committed.load(Ordering::Acquire)
    }

    /// Make everything committed so far durable, synchronously. For writes to ANOTHER durable
    /// store (vault, inbox, lanes, status files) that must never reach disk ahead of the chain.
    pub fn flush_committed_blocking(self: &Arc<Self>) -> Result<()> {
        self.wait_durable_blocking(self.committed())
    }

    fn ensure_flusher(self: &Arc<Self>) {
        if self.flusher_started.swap(true, Ordering::AcqRel) {
            return;
        }
        // The thread holds a Weak: it ends when the store (the only strong owner besides
        // in-flight waiters) is gone, so tests that open thousands of stores leak no threads.
        let weak = Arc::downgrade(self);
        let spawned = std::thread::Builder::new()
            .name("hestia-chain-flusher".into())
            .spawn(move || flusher_loop(weak));
        if spawned.is_err() {
            // No thread: fall back to flushing inline on each wait (correct, just ungrouped).
            self.flusher_started.store(false, Ordering::Release);
        }
    }

    fn request(&self, len: u64) {
        let mut r = self.req.lock().unwrap_or_else(|p| p.into_inner());
        if len > r.wanted {
            r.wanted = len;
        }
        self.cv.notify_one();
    }

    /// Wait until entries `[0, len)` are durable. Errors if durability was lost.
    pub async fn wait_durable(self: &Arc<Self>, len: u64) -> Result<()> {
        let mut rx = self.frontier.subscribe();
        {
            let f = *rx.borrow();
            if f.poisoned {
                return Err(poisoned_error());
            }
            if f.durable >= len {
                return Ok(());
            }
        }
        self.ensure_flusher();
        if !self.flusher_started.load(Ordering::Acquire) {
            return self.flush_inline(len);
        }
        self.request(len);
        let f = rx
            .wait_for(|f| f.poisoned || f.durable >= len)
            .await
            .map_err(|_| anyhow!("chain durability channel closed"))?;
        if f.poisoned { Err(poisoned_error()) } else { Ok(()) }
    }

    /// Blocking variant for synchronous callers (startup, CLI, shutdown).
    pub fn wait_durable_blocking(self: &Arc<Self>, len: u64) -> Result<()> {
        let f = self.frontier();
        if f.poisoned {
            return Err(poisoned_error());
        }
        if f.durable >= len {
            return Ok(());
        }
        self.flush_inline(len)
    }

    fn flush_inline(&self, len: u64) -> Result<()> {
        while self.hold.load(Ordering::Acquire) {
            std::thread::sleep(Duration::from_millis(5));
        }
        let _g = self.sync_lock.lock().unwrap_or_else(|p| p.into_inner());
        let f = self.frontier();
        if f.poisoned {
            return Err(poisoned_error());
        }
        if f.durable >= len {
            return Ok(());
        }
        self.sync_once();
        let f = self.frontier();
        if f.poisoned { Err(poisoned_error()) } else { Ok(()) }
    }

    /// One group fsync covering everything committed when it starts. Updates the frontier.
    fn sync_once(&self) {
        let target = self.committed.load(Ordering::Acquire);
        let res = crate::server::state_lock::time_section("chain.fsync", || self.fsync_files());
        self.fsyncs.fetch_add(1, Ordering::Relaxed);
        match res {
            Ok(()) => {
                self.frontier.send_modify(|f| {
                    if !f.poisoned && target > f.durable {
                        f.durable = target;
                    }
                });
            }
            Err(e) => self.poison(&format!("{e:#}")),
        }
    }

    fn fsync_files(&self) -> Result<()> {
        if self.fail_next_sync.swap(false, Ordering::AcqRel) {
            return Err(anyhow!("injected fsync failure"));
        }
        match std::fs::File::open(&self.wal_path) {
            Ok(f) => {
                f.sync_data()?;
                // A freshly created WAL needs its directory entry durable too.
                #[cfg(unix)]
                {
                    use std::os::unix::fs::MetadataExt;
                    let ino = f.metadata().map(|m| m.ino()).unwrap_or(0);
                    if self.last_wal_ino.swap(ino, Ordering::AcqRel) != ino {
                        std::fs::File::open(&self.dir_path)?.sync_all()?;
                    }
                }
            }
            // No WAL file: everything committed is already in the main database (a
            // checkpoint truncated it); sync that instead.
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                std::fs::File::open(&self.db_path)?.sync_data()?;
            }
            Err(e) => return Err(e.into()),
        }
        Ok(())
    }

    fn poison(&self, why: &str) {
        let first = !self.frontier().poisoned;
        self.frontier.send_modify(|f| f.poisoned = true);
        if first {
            tracing::error!(
                why,
                "witness chain fsync FAILED: durability of unacknowledged entries is unknown; \
                 refusing every further append — the daemon must restart and rebuild from the chain"
            );
            eprintln!("[hestia] FATAL: witness chain fsync failed ({why}); refusing appends");
            if let Some(h) = FATAL_HOOK.get() {
                h(why);
            }
        }
    }

    fn wal_bytes(&self) -> u64 {
        std::fs::metadata(&self.wal_path).map(|m| m.len()).unwrap_or(0)
    }

    fn idle_for(&self) -> Duration {
        let last = self.last_commit_ms.load(Ordering::Acquire);
        let now = self.epoch.elapsed().as_millis() as u64;
        Duration::from_millis(now.saturating_sub(last))
    }

    fn checkpoint(&self, conn: &mut Option<rusqlite::Connection>) {
        if conn.is_none() {
            let c = rusqlite::Connection::open(&self.db_path).and_then(|c| {
                c.pragma_update(None, "key", &self.key_hex)?;
                Ok(c)
            });
            match c {
                Ok(c) => *conn = Some(c),
                Err(e) => {
                    tracing::warn!("chain checkpoint connection failed: {e}");
                    return;
                }
            }
        }
        let c = conn.as_ref().expect("opened above");
        let r = crate::server::state_lock::time_section("chain.checkpoint", || {
            c.query_row("PRAGMA wal_checkpoint(PASSIVE)", [], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, r.get::<_, i64>(2)?))
            })
        });
        self.checkpoints.fetch_add(1, Ordering::Relaxed);
        if let Err(e) = r {
            tracing::warn!("chain checkpoint failed (will retry): {e}");
        }
    }
}

/// Releases a test flush hold when dropped.
#[doc(hidden)]
pub struct FlushHold(Arc<Durability>);

impl Drop for FlushHold {
    fn drop(&mut self) {
        self.0.hold.store(false, Ordering::Release);
        self.0.cv.notify_all();
    }
}

fn poisoned_error() -> anyhow::Error {
    anyhow!(
        "the witness chain's fsync failed: durability of this entry is UNKNOWN (it may or may \
         not survive), the daemon refuses further appends and must restart to rebuild from the \
         chain. Retry after the restart."
    )
}

fn flusher_loop(weak: std::sync::Weak<Durability>) {
    let mut ckpt_conn: Option<rusqlite::Connection> = None;
    loop {
        let Some(d) = weak.upgrade() else { return };
        // Wait for a flush request, or time out to consider an idle checkpoint.
        let wanted = {
            let mut r = d.req.lock().unwrap_or_else(|p| p.into_inner());
            if r.shutdown {
                return;
            }
            if r.wanted <= d.frontier().durable {
                let (g, _) = d
                    .cv
                    .wait_timeout(r, Duration::from_millis(500))
                    .unwrap_or_else(|p| p.into_inner());
                r = g;
                if r.shutdown {
                    return;
                }
            }
            r.wanted
        };
        if d.poisoned() {
            // Nothing more to make durable; just wake anyone still waiting (they see poisoned).
            std::thread::sleep(Duration::from_millis(200));
            continue;
        }
        if d.hold.load(Ordering::Acquire) {
            std::thread::sleep(Duration::from_millis(5));
            continue;
        }
        if wanted > d.frontier().durable {
            let _g = d.sync_lock.lock().unwrap_or_else(|p| p.into_inner());
            d.sync_once();
            continue;
        }
        // Idle: make durable whatever background tasks committed, then maybe checkpoint.
        if d.committed.load(Ordering::Acquire) > d.frontier().durable {
            let _g = d.sync_lock.lock().unwrap_or_else(|p| p.into_inner());
            d.sync_once();
        }
        let wal = d.wal_bytes();
        if wal >= CHECKPOINT_FORCE_BYTES || (wal >= CHECKPOINT_MIN_BYTES && d.idle_for() >= CHECKPOINT_IDLE) {
            d.checkpoint(&mut ckpt_conn);
        }
        drop(d);
    }
}

impl Drop for Durability {
    fn drop(&mut self) {
        let mut r = self.req.lock().unwrap_or_else(|p| p.into_inner());
        r.shutdown = true;
        self.cv.notify_all();
    }
}

/// Request-scoped durability: everything a request appends is waited for before it replies.
struct ScopeState {
    target: Option<(Arc<Durability>, u64)>,
}

tokio::task_local! {
    static SCOPE: RefCell<ScopeState>;
}

/// Called by the chain store after each committed append: the current request (if it runs in a
/// [`durable_scope`]) must not reply before committed length `len` is durable.
pub(crate) fn note_appended(d: &Arc<Durability>, len: u64) {
    let _ = SCOPE.try_with(|s| {
        let mut s = s.borrow_mut();
        match &mut s.target {
            Some((_, t)) if *t >= len => {}
            Some((existing, t)) if Arc::ptr_eq(existing, d) => *t = len,
            _ => s.target = Some((d.clone(), len)),
        }
    });
}

/// Run `f`; then, before returning its output, wait until every chain entry it appended is
/// durable. `Err` means durability was lost: the caller must NOT report the act as recorded.
pub async fn durable_scope<F: Future>(f: F) -> (F::Output, Result<()>) {
    let (out, target) = SCOPE
        .scope(RefCell::new(ScopeState { target: None }), async {
            let out = f.await;
            let t = SCOPE.with(|s| s.borrow_mut().target.take());
            (out, t)
        })
        .await;
    let res = match target {
        Some((d, len)) => d.wait_durable(len).await,
        None => Ok(()),
    };
    (out, res)
}
