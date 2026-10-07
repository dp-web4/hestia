//! Trust state — per-entity `EntityTrust`, each **sealed at rest** — as a PROJECTION OF THE
//! WITNESS CHAIN.
//!
//! Each plugin gets one file under `<HESTIA_HOME>/trust/` named by a hash of its entity id; the
//! content is encrypted with the stable storage key (vault doctrine — no plaintext state). Reuses
//! `web4-trust-core`'s `EntityTrust` math; only the I/O is local + sealed. A legacy plaintext file
//! is read transparently and re-sealed on the next write.
//!
//! THE CHAIN IS THE SOURCE OF TRUTH; THESE FILES ARE A CACHE (#1271, dp/coordinator 2026-10-07).
//! Every trust change follows deterministically from one chain row's content: an `outcome`, a
//! decision row's charge (`ChargeSpec`), an `adjudication`, a `reversal`, or a
//! `decision_charge_settled`. The daemon applies it in the same critical section as the append,
//! in chain order, keyed by the member LCT the row recorded and stamped with the row's timestamp
//! and position. So:
//! - the files are written WITHOUT fsync (atomic rename only, for torn-write safety): a crash loses
//!   only cache, never a fact;
//! - each file records the chain position it is projected through (`through`), so applying a row
//!   is idempotent — a row at or below an entity's `through` is skipped;
//! - `projection.json` records the position every file is current through (written after each
//!   batch); at startup the daemon replays the chain from it through the same update functions,
//!   restoring whatever the cache lost.
//! Requests no longer wait on trust I/O at all: the fact they report is the chain row, which is
//! durable before the reply (group commit).
//!
//! Hestia stores trust by plugin_id with a `plugin:` prefix so it slots into the Web4 entity-type
//! taxonomy (`mcp:`, `lct:`, `role:`, etc).

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use web4_core::vault::crypto::{self, DerivedKey};
use web4_trust_core::EntityTrust;

/// The chain row a trust change is projected from: its position and timestamp.
#[derive(Debug, Clone, Copy)]
pub struct RowAt {
    pub pos: u64,
    pub ts: chrono::DateTime<chrono::Utc>,
}

/// The cache file's on-disk form (v2). A bare `EntityTrust` (v1) is read as `through: None`.
#[derive(serde::Serialize, serde::Deserialize)]
struct EntityFile {
    v: u32,
    through: Option<u64>,
    trust: EntityTrust,
}

const PROJECTION_FILE: &str = "projection.json";

#[derive(Clone)]
struct Cached {
    trust: EntityTrust,
    through: Option<u64>,
}

/// Per-entity sealed trust store (a chain projection; see the module docs).
pub struct TrustStore {
    base_dir: PathBuf,
    key: [u8; 32],
    cache: Mutex<HashMap<String, Cached>>,
    persister: Arc<TrustPersister>,
}

impl TrustStore {
    /// Open (create) a sealed trust store rooted at `base_dir`, keyed by the stable storage key.
    pub fn open(base_dir: impl AsRef<Path>, key: [u8; 32]) -> Result<Self> {
        let base_dir = base_dir.as_ref().to_path_buf();
        std::fs::create_dir_all(&base_dir)
            .with_context(|| format!("creating trust dir {}", base_dir.display()))?;
        let persister = TrustPersister::new(base_dir.clone());
        Ok(Self { base_dir, key, cache: Mutex::new(HashMap::new()), persister })
    }

    pub fn base_dir(&self) -> &Path {
        &self.base_dir
    }

    fn entity_id(plugin_id: &str) -> String {
        // The plugin_id may already include a type prefix (e.g. "mcp:openclaw");
        // pass it through if it does, otherwise namespace it.
        if plugin_id.contains(':') {
            plugin_id.to_string()
        } else {
            format!("plugin:{plugin_id}")
        }
    }

    /// File for an entity id — named by a hash, content sealed.
    fn entity_file(&self, entity_id: &str) -> PathBuf {
        let hash = format!("{:x}", Sha256::digest(entity_id.as_bytes()));
        self.base_dir.join(format!("{}.json", &hash[..16]))
    }

    fn dk(&self) -> DerivedKey {
        DerivedKey::from_bytes(self.key)
    }

    fn cache(&self) -> std::sync::MutexGuard<'_, HashMap<String, Cached>> {
        self.cache.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Decrypt (or read legacy plaintext) and parse either file version.
    fn parse(&self, raw: Vec<u8>) -> Option<Cached> {
        // Sealed blobs are nonce-prefixed ChaCha20-Poly1305 with no magic header, so their first
        // byte is random: decrypt first, fall back to legacy plaintext only when AEAD
        // authentication fails (which it always does for genuine plaintext).
        let json: Vec<u8> = match crypto::open(&self.dk(), &raw) {
            Ok(plain) => plain,
            Err(_) => raw,
        };
        if let Ok(f) = serde_json::from_slice::<EntityFile>(&json) {
            return Some(Cached { trust: f.trust, through: f.through });
        }
        serde_json::from_slice::<EntityTrust>(&json)
            .ok()
            .map(|trust| Cached { trust, through: None })
    }

    /// The cached entity, loading its file on first touch. `None` if it has never existed.
    fn load(&self, entity_id: &str) -> Result<Option<Cached>> {
        if let Some(c) = self.cache().get(entity_id) {
            return Ok(Some(c.clone()));
        }
        let path = self.entity_file(entity_id);
        if !path.exists() {
            return Ok(None);
        }
        let raw =
            std::fs::read(&path).with_context(|| format!("reading trust {}", path.display()))?;
        let c = self
            .parse(raw)
            .with_context(|| format!("parsing trust {}", path.display()))?;
        self.cache().insert(entity_id.to_string(), c.clone());
        Ok(Some(c))
    }

    /// Record a new value in the cache and hand its sealed bytes to the write-behind persister.
    fn store(&self, c: Cached, at: Option<RowAt>) -> Result<()> {
        let file = EntityFile { v: 2, through: c.through, trust: c.trust.clone() };
        let json = serde_json::to_vec_pretty(&file).context("serializing trust")?;
        let sealed = crypto::seal(&self.dk(), &json).context("sealing trust")?;
        let path = self.entity_file(&c.trust.entity_id);
        self.cache().insert(c.trust.entity_id.clone(), c);
        self.persister.enqueue(path, sealed, at.map(|a| a.pos));
        Ok(())
    }

    /// Append `line` to `path` in the same ordered batch as the trust writes before it (the
    /// reputation-delta queue, the legacy settle record). A cache too: written without fsync.
    pub fn append_after_trust(&self, path: &Path, line: String) -> Result<()> {
        self.persister.append(path.to_path_buf(), line);
        Ok(())
    }

    /// The write-behind persister (test hooks, flush).
    pub fn persister(&self) -> &Arc<TrustPersister> {
        &self.persister
    }

    /// The chain position every cache file is current through (`projection.json`), or `None` if
    /// no projection has been recorded (a fresh home, a legacy one, or a deleted cache).
    pub fn projected_through(&self) -> Option<u64> {
        let raw = std::fs::read(self.base_dir.join(PROJECTION_FILE)).ok()?;
        serde_json::from_slice::<serde_json::Value>(&raw).ok()?.get("through")?.as_u64()
    }

    /// The PROJECTION EPOCH: the first chain position from which trust has been a projection of
    /// the chain (0 for a home that never had a legacy cache). Fixed once; unlike `through`, it
    /// never moves. Rows from here on charge exactly when they commit, so the decision ledger
    /// derives their charge from the chain alone.
    pub fn projection_since(&self) -> Option<u64> {
        let raw = std::fs::read(self.base_dir.join(PROJECTION_FILE)).ok()?;
        serde_json::from_slice::<serde_json::Value>(&raw).ok()?.get("since")?.as_u64()
    }

    /// Set the epoch every later `projection.json` carries.
    pub fn set_projection_since(&self, since: u64) {
        self.persister.since.store(since, Ordering::Release);
    }

    /// Adopt a legacy cache: the files as they stand ARE the state through `pos`, and the
    /// projection starts at `since`.
    pub fn adopt_legacy(&self, through: Option<u64>, since: u64) -> Result<()> {
        self.set_projection_since(since);
        write_atomic(&self.base_dir.join(PROJECTION_FILE),
                     serde_json::json!({"through": through, "since": since}).to_string().as_bytes())
    }

    /// Does this store hold ANY cached entity file?
    pub fn has_entity_files(&self) -> bool {
        std::fs::read_dir(&self.base_dir)
            .map(|rd| {
                rd.flatten().any(|e| {
                    let p = e.path();
                    p.extension().and_then(|s| s.to_str()) == Some("json")
                        && p.file_name().and_then(|s| s.to_str()) != Some(PROJECTION_FILE)
                })
            })
            .unwrap_or(false)
    }

    /// Fetch the entity trust for a plugin; an entity that does not exist yet is returned fresh
    /// and NOT stored (a read creates nothing — creation is a chain-projected change).
    pub fn get(&self, plugin_id: &str) -> Result<EntityTrust> {
        let id = Self::entity_id(plugin_id);
        Ok(match self.load(&id)? {
            Some(c) => c.trust,
            None => EntityTrust::new(&id),
        })
    }

    /// Apply an outcome (no chain position: unit tests and non-daemon callers).
    pub fn update(&self, plugin_id: &str, success: bool, magnitude: f64) -> Result<EntityTrust> {
        Ok(self.update_returning_prior(plugin_id, success, magnitude)?.1)
    }

    /// Apply an outcome, returning `(before, after)` (no chain position).
    pub fn update_returning_prior(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
    ) -> Result<(EntityTrust, EntityTrust)> {
        self.apply(plugin_id, None, |t| {
            t.update_from_outcome(success, magnitude);
            Ok(())
        })
    }

    /// Apply an outcome PROJECTED FROM THE CHAIN ROW `at`: idempotent by position (a row at or
    /// below the entity's `through` is skipped and reported as `None`), timestamped by the row.
    pub fn update_at(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
        at: RowAt,
    ) -> Result<Option<(EntityTrust, EntityTrust)>> {
        self.apply_at(plugin_id, at, |t| {
            t.update_from_outcome(success, magnitude);
            Ok(())
        })
    }

    /// Apply an adjudicated V3 observation (no chain position).
    pub fn update_v3_returning_prior(
        &self,
        plugin_id: &str,
        dimension: web4_core::v3::ValueDimension,
        score: f64,
    ) -> Result<(EntityTrust, EntityTrust)> {
        self.apply(plugin_id, None, |t| {
            t.v3.observe(dimension, score).map_err(|e| anyhow::anyhow!("v3 observe: {e}"))
        })
    }

    /// Apply an adjudicated V3 observation projected from the chain row `at`.
    pub fn update_v3_at(
        &self,
        plugin_id: &str,
        dimension: web4_core::v3::ValueDimension,
        score: f64,
        at: RowAt,
    ) -> Result<Option<(EntityTrust, EntityTrust)>> {
        self.apply_at(plugin_id, at, |t| {
            t.v3.observe(dimension, score).map_err(|e| anyhow::anyhow!("v3 observe: {e}"))
        })
    }

    fn apply(
        &self,
        plugin_id: &str,
        at: Option<RowAt>,
        f: impl FnOnce(&mut EntityTrust) -> Result<()>,
    ) -> Result<(EntityTrust, EntityTrust)> {
        let id = Self::entity_id(plugin_id);
        let current = self.load(&id)?;
        let fresh = current.is_none();
        let mut c = current.unwrap_or(Cached { trust: EntityTrust::new(&id), through: None });
        let before = c.trust.clone();
        f(&mut c.trust)?;
        if let Some(at) = at {
            // The row is the clock: a projection replayed later reproduces these exactly.
            c.trust.last_action = Some(at.ts);
            if fresh {
                c.trust.created_at = at.ts;
            }
            c.through = Some(at.pos);
        }
        let after = c.trust.clone();
        self.store(c, at)?;
        Ok((before, after))
    }

    fn apply_at(
        &self,
        plugin_id: &str,
        at: RowAt,
        f: impl FnOnce(&mut EntityTrust) -> Result<()>,
    ) -> Result<Option<(EntityTrust, EntityTrust)>> {
        let id = Self::entity_id(plugin_id);
        if let Some(c) = self.load(&id)? {
            if c.through.is_some_and(|t| t >= at.pos) {
                return Ok(None); // already projected: replay is idempotent
            }
        }
        self.apply(plugin_id, Some(at), f).map(Some)
    }

    /// Every cached entity (cache ∪ files), as `(entity_id, trust)` — for audits and the
    /// projection-equivalence test.
    pub fn all(&self) -> Result<Vec<(String, EntityTrust)>> {
        let mut out: HashMap<String, EntityTrust> = HashMap::new();
        if let Ok(rd) = std::fs::read_dir(&self.base_dir) {
            for e in rd.flatten() {
                let p = e.path();
                if p.extension().and_then(|s| s.to_str()) != Some("json")
                    || p.file_name().and_then(|s| s.to_str()) == Some(PROJECTION_FILE)
                {
                    continue;
                }
                if let Some(c) = std::fs::read(&p).ok().and_then(|raw| self.parse(raw)) {
                    out.insert(c.trust.entity_id.clone(), c.trust);
                }
            }
        }
        for (id, c) in self.cache().iter() {
            out.insert(id.clone(), c.trust.clone());
        }
        let mut v: Vec<_> = out.into_iter().collect();
        v.sort_by(|a, b| a.0.cmp(&b.0));
        Ok(v)
    }

    /// List known plugin_ids (without the `plugin:` prefix when applicable).
    pub fn list(&self) -> Result<Vec<String>> {
        let mut out: Vec<String> = self
            .all()?
            .into_iter()
            .map(|(id, _)| id.strip_prefix("plugin:").unwrap_or(&id).to_string())
            .collect();
        out.sort();
        out.dedup();
        Ok(out)
    }
}

impl Drop for TrustStore {
    /// A clean shutdown writes the cache out (best effort; replay restores anything lost).
    fn drop(&mut self) {
        self.persister.flush_blocking();
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    let tmp = path.with_extension("tmp");
    let mut f = std::fs::File::create(&tmp).with_context(|| format!("creating {}", tmp.display()))?;
    f.write_all(bytes)?;
    drop(f);
    std::fs::rename(&tmp, path).with_context(|| format!("renaming into {}", path.display()))?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// WRITE-BEHIND CACHE WRITER. No fsync anywhere: the chain row is the durable fact, these files are
// its projection. Atomic rename keeps a file whole; a lost write is restored by replay.
// ---------------------------------------------------------------------------------------------

#[derive(Default)]
struct PersistQueue {
    /// Latest sealed bytes per file (coalesced).
    files: HashMap<PathBuf, Vec<u8>>,
    /// Ordered line appends (after the batch's files).
    appends: Vec<(PathBuf, String)>,
    /// Highest chain position whose trust change is in memory (and so in this queue or already
    /// written): the batch's projection position.
    max_pos: Option<u64>,
    pending: u64,
    shutdown: bool,
}

pub struct TrustPersister {
    dir: PathBuf,
    queue: Mutex<PersistQueue>,
    cv: Condvar,
    started: AtomicBool,
    hold: AtomicBool,
    fail_next: AtomicBool,
    /// Batches written (tests, diagnostics).
    pub batches: AtomicU64,
    /// The projection epoch (`since`), carried into every `projection.json` written.
    since: AtomicU64,
    /// ONE batch at a time, from taking the queue to the last rename. Without it the thread and a
    /// `flush_blocking` (tests, Drop) could each take a batch and the OLDER value of a file — or
    /// of the projection watermark — could be renamed in last (caught as a flake of
    /// `outcome_updates_persist_across_reopen_sealed`).
    batch_lock: Mutex<()>,
}

impl TrustPersister {
    fn new(dir: PathBuf) -> Arc<Self> {
        let p = Arc::new(Self {
            dir,
            queue: Mutex::new(PersistQueue::default()),
            cv: Condvar::new(),
            started: AtomicBool::new(false),
            hold: AtomicBool::new(false),
            fail_next: AtomicBool::new(false),
            batches: AtomicU64::new(0),
            since: AtomicU64::new(0),
            batch_lock: Mutex::new(()),
        });
        #[cfg(test)]
        TEST_REGISTRY.lock().unwrap_or_else(|e| e.into_inner()).push(Arc::downgrade(&p));
        p
    }

    fn q(&self) -> std::sync::MutexGuard<'_, PersistQueue> {
        self.queue.lock().unwrap_or_else(|p| p.into_inner())
    }

    fn enqueue(self: &Arc<Self>, path: PathBuf, sealed: Vec<u8>, pos: Option<u64>) {
        {
            let mut q = self.q();
            q.files.insert(path, sealed);
            if let Some(p) = pos {
                q.max_pos = Some(q.max_pos.map_or(p, |m| m.max(p)));
            }
            q.pending += 1;
        }
        self.kick();
    }

    fn append(self: &Arc<Self>, path: PathBuf, line: String) {
        {
            let mut q = self.q();
            q.appends.push((path, line));
            q.pending += 1;
        }
        self.kick();
    }

    fn kick(self: &Arc<Self>) {
        if !self.started.swap(true, Ordering::AcqRel) {
            let weak = Arc::downgrade(self);
            if std::thread::Builder::new()
                .name("hestia-trust-cache".into())
                .spawn(move || persister_loop(weak))
                .is_err()
            {
                self.started.store(false, Ordering::Release);
            }
        }
        self.cv.notify_one();
    }

    /// Write everything queued now (shutdown, tests). Best effort: errors are logged.
    pub fn flush_blocking(&self) {
        for _ in 0..1000 {
            // Wait out a batch the thread already took: "the queue is empty" is not "written".
            drop(self.batch_lock.lock().unwrap_or_else(|p| p.into_inner()));
            if self.q().pending == 0 {
                return;
            }
            if self.hold.load(Ordering::Acquire) {
                std::thread::sleep(std::time::Duration::from_millis(2));
                continue;
            }
            if !self.run_batch() {
                return; // best effort: a failing cache write is retried by the thread
            }
        }
    }

    /// One batch; `false` if it failed (and was re-queued).
    fn run_batch(&self) -> bool {
        let _one_at_a_time = self.batch_lock.lock().unwrap_or_else(|p| p.into_inner());
        let (files, appends, max_pos) = {
            let mut q = self.q();
            q.pending = 0;
            (std::mem::take(&mut q.files), std::mem::take(&mut q.appends), q.max_pos)
        };
        if files.is_empty() && appends.is_empty() {
            return true;
        }
        let res = crate::server::state_lock::time_section("trust.cache_write", || {
            self.write_batch(&files, &appends, max_pos)
        });
        self.batches.fetch_add(1, Ordering::Relaxed);
        if let Err(e) = res {
            // A cache write failed: nothing is lost (the chain holds every fact) — put the batch
            // back for the next pass, newer values first, and say so.
            tracing::warn!("trust cache write failed (will retry; replay restores on restart): {e:#}");
            let mut q = self.q();
            for (p, b) in files {
                q.files.entry(p).or_insert(b);
            }
            let mut a = appends;
            a.extend(std::mem::take(&mut q.appends));
            q.appends = a;
            q.pending += 1;
            return false;
        }
        true
    }

    fn write_batch(
        &self,
        files: &HashMap<PathBuf, Vec<u8>>,
        appends: &[(PathBuf, String)],
        max_pos: Option<u64>,
    ) -> Result<()> {
        use std::io::Write;
        if self.fail_next.swap(false, Ordering::AcqRel) {
            anyhow::bail!("injected trust cache write failure");
        }
        for (path, bytes) in files {
            write_atomic(path, bytes)?;
        }
        for (path, line) in appends {
            let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path)
                .with_context(|| format!("appending {}", path.display()))?;
            writeln!(f, "{line}")?;
        }
        // Every file is now current through max_pos (each dirty file was just written with its
        // latest value; a clean one has had no change since). Written LAST: a crash before this
        // only means replay starts earlier, and per-entity `through` keeps it idempotent.
        if let Some(p) = max_pos {
            let since = self.since.load(Ordering::Acquire);
            write_atomic(&self.dir.join(PROJECTION_FILE),
                         serde_json::json!({"through": p, "since": since}).to_string().as_bytes())?;
        }
        Ok(())
    }

    /// Test hook: hold every batch until the guard drops.
    #[doc(hidden)]
    pub fn hold_for_test(self: &Arc<Self>) -> PersistHold {
        self.hold.store(true, Ordering::Release);
        PersistHold(self.clone())
    }

    /// Test hook: the next batch fails, as an I/O error would.
    #[doc(hidden)]
    pub fn inject_failure(&self) {
        self.fail_next.store(true, Ordering::Release);
    }

    /// Test hook: forget everything queued, as a crash would.
    #[doc(hidden)]
    pub fn discard_for_test(&self) {
        let mut q = self.q();
        q.files.clear();
        q.appends.clear();
        q.pending = 0;
    }
}

#[cfg(test)]
static TEST_REGISTRY: Mutex<Vec<std::sync::Weak<TrustPersister>>> = Mutex::new(Vec::new());

/// Tests that read a cached side file (the reputation sink) right after a direct tool call
/// flush every live persister first.
#[cfg(test)]
pub fn flush_all_for_test() {
    let live: Vec<Arc<TrustPersister>> = TEST_REGISTRY
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .filter_map(|w| w.upgrade())
        .collect();
    for p in live {
        p.flush_blocking();
    }
}

#[doc(hidden)]
pub struct PersistHold(Arc<TrustPersister>);

impl Drop for PersistHold {
    fn drop(&mut self) {
        self.0.hold.store(false, Ordering::Release);
        self.0.cv.notify_all();
    }
}

impl Drop for TrustPersister {
    fn drop(&mut self) {
        self.q().shutdown = true;
        self.cv.notify_all();
    }
}

fn persister_loop(weak: std::sync::Weak<TrustPersister>) {
    loop {
        let Some(p) = weak.upgrade() else { return };
        {
            let mut q = p.q();
            if q.shutdown {
                return;
            }
            if q.pending == 0 {
                let (g, _) = p
                    .cv
                    .wait_timeout(q, std::time::Duration::from_millis(500))
                    .unwrap_or_else(|e| e.into_inner());
                q = g;
                if q.shutdown {
                    return;
                }
            }
        }
        if p.hold.load(Ordering::Acquire) {
            std::thread::sleep(std::time::Duration::from_millis(5));
            continue;
        }
        let ok = p.run_batch();
        drop(p);
        if !ok {
            std::thread::sleep(std::time::Duration::from_secs(1));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const KEY: [u8; 32] = [3u8; 32];

    fn at(pos: u64) -> RowAt {
        RowAt { pos, ts: chrono::DateTime::from_timestamp(1_800_000_000 + pos as i64, 0).unwrap() }
    }

    /// A chain-projected update is idempotent by position, and takes its clock from the row.
    #[test]
    fn a_projected_update_is_idempotent_by_position() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert!(store.update_at("claude-code", true, 0.8, at(5)).unwrap().is_some());
        assert!(store.update_at("claude-code", true, 0.8, at(5)).unwrap().is_none(), "same row twice");
        assert!(store.update_at("claude-code", false, 0.5, at(4)).unwrap().is_none(), "an older row");
        let (_, after) = store.update_at("claude-code", false, 0.5, at(6)).unwrap().unwrap();
        assert_eq!(after.action_count, 2);
        assert_eq!(after.last_action, Some(at(6).ts), "the row is the clock");
        assert_eq!(after.created_at, at(5).ts, "created by its first row");
    }

    /// The cache records how far it is projected; a reopen sees the same idempotence.
    #[test]
    fn the_cache_records_its_projection_and_survives_reopen() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.projected_through(), None);
        store.update_at("claude-code", true, 0.8, at(7)).unwrap();
        store.persister().flush_blocking();
        assert_eq!(store.projected_through(), Some(7));
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert!(reopened.update_at("claude-code", true, 0.8, at(7)).unwrap().is_none());
        assert_eq!(reopened.get("claude-code").unwrap().action_count, 1);
    }

    /// A read creates nothing: an entity exists only once a chain row changed it.
    #[test]
    fn a_read_creates_nothing() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.get("ghost").unwrap().action_count, 0);
        store.persister().flush_blocking();
        assert!(store.list().unwrap().is_empty());
        assert!(!store.has_entity_files());
    }

    /// A failed cache write loses nothing: it is retried, and the value stays served from memory.
    #[test]
    fn a_failed_cache_write_is_retried_not_fatal() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.persister().inject_failure();
        store.update_at("claude-code", true, 0.8, at(3)).unwrap();
        store.persister().flush_blocking();
        assert_eq!(store.get("claude-code").unwrap().action_count, 1);
        assert!(store.update_at("claude-code", true, 0.8, at(4)).unwrap().is_some(), "not poisoned");
        store.persister().flush_blocking();
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.get("claude-code").unwrap().action_count, 2);
    }

    #[test]
    fn outcome_updates_persist_across_reopen_sealed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.get("claude-code").unwrap().action_count, 0);
        store.update("claude-code", true, 0.8).unwrap();
        let t = store.update("claude-code", false, 0.5).unwrap();
        assert_eq!(t.action_count, 2);
        assert_eq!(t.success_count, 1);

        // On disk the file is sealed (not plaintext JSON).
        //
        // This assertion WAS `raw.first() != b'{'`, the same 1/256 brace-sniff proxy that
        // #61 removed from `legacy_plaintext_is_read_then_resealed` — and left standing
        // here, in its twin. A sealed blob is `nonce(12) || ciphertext` with a random
        // nonce, so it begins with 0x7b by chance once in 256 runs, and the suite goes red
        // for a reason that means nothing. It cost a full-suite red on 2026-07-27, one run
        // after #61 landed claiming the class was fixed.
        //
        // The lesson #61 already wrote down, arriving again from the file it was written
        // in: a flake that clears on rerun trains rerun-until-green, and *broken* and
        // *unlucky* render identically. Fixing one instance of a bug class and not grepping
        // for its siblings is how the class survives its own fix.
        //
        // Deterministic and stronger: the bytes must not parse as trust JSON (they are
        // ciphertext), and the value must still come back through the decrypt path below.
        let f = store.entity_file(&TrustStore::entity_id("claude-code"));
        store.persister().flush_blocking();
        let raw = std::fs::read(&f).unwrap();
        assert!(
            serde_json::from_slice::<serde_json::Value>(&raw).is_err(),
            "trust file should be sealed ciphertext, not parseable plaintext JSON"
        );

        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        let t = reopened.get("claude-code").unwrap();
        assert_eq!(t.action_count, 2);
        assert_eq!(t.success_count, 1);
    }

    #[test]
    fn distinct_plugins_listed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.update("alice", true, 0.6).unwrap();
        store.update("bob", false, 0.6).unwrap();
        let listed = store.list().unwrap();
        assert_eq!(listed.len(), 2);
        assert!(listed.contains(&"alice".to_string()));
        assert!(listed.contains(&"bob".to_string()));
    }

    /// NOTE ON THE ASSERTION BELOW — it used to be `first() != b'{'`, and that
    /// made this test fail about 1 run in 256.
    ///
    /// A sealed blob is `nonce(12) || ciphertext` with no magic header, and the
    /// nonce is random, so a correctly sealed file starts with `0x7b` by chance
    /// 1/256 of the time. The test was using *starts with a brace* as a proxy for
    /// *is plaintext* — which is the exact sniff heuristic
    /// `sealed_blob_starting_with_brace_byte_still_loads` (directly below) exists
    /// to prove wrong. The bug had been removed from the code and left standing in
    /// the test that guards it, so the suite carried a rare red that meant nothing
    /// and, worse, would have been read as a real regression by whoever hit it.
    ///
    /// Caught 2026-07-27 on a full-suite run for #60 — a 366/1 that passed on
    /// rerun. A flake that clears on rerun is the same conflation this codebase
    /// keeps finding: *broken* and *unlucky* rendered identically, and rerun-until-
    /// green is how a real intermittent bug gets trained into background noise.
    ///
    /// Asserting the round-trip instead is both stronger and deterministic: the
    /// bytes on disk must not parse as trust JSON (they are ciphertext), and the
    /// value must come back through the decrypt path with the update applied.

    #[test]
    fn legacy_plaintext_is_read_then_resealed() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        // Write a plaintext trust file as an old install would.
        let t = EntityTrust::new("plugin:legacy");
        let f = store.entity_file("plugin:legacy");
        let plaintext = serde_json::to_vec_pretty(&t).unwrap();
        std::fs::write(&f, &plaintext).unwrap();
        assert!(
            serde_json::from_slice::<EntityTrust>(&std::fs::read(&f).unwrap()).is_ok(),
            "precondition: the file starts out as parseable plaintext"
        );

        // get() reads the plaintext; update() re-seals it.
        assert_eq!(store.get("legacy").unwrap().action_count, 0);
        store.update("legacy", true, 0.5).unwrap();

        store.persister().flush_blocking();
        let raw = std::fs::read(&f).unwrap();
        assert_ne!(raw, plaintext, "the file must have been rewritten");
        assert!(
            serde_json::from_slice::<EntityTrust>(&raw).is_err(),
            "should be re-sealed after write — the bytes on disk still parse as trust JSON"
        );
        assert_eq!(
            store.get("legacy").unwrap().action_count,
            1,
            "and the resealed file must still decrypt back to the updated value"
        );
    }

    /// Regression for the first-byte sniff bug: a sealed blob is nonce-prefixed
    /// with no magic header, so ~1/256 sealed files start with 0x7b ('{') by
    /// chance. The old `raw.first()=='{'` heuristic misread those as plaintext,
    /// skipped decryption, and failed to parse the ciphertext ("parsing trust").
    /// Here we deterministically forge that exact condition — a real sealed blob
    /// whose first byte is '{' — and assert it round-trips. Fails (panics in
    /// get().unwrap()) against the old sniff; passes with decrypt-first.
    #[test]
    fn sealed_blob_starting_with_brace_byte_still_loads() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();

        // Non-default trust state so a successful load can't be confused with a
        // freshly auto-created entity (which would have action_count == 0).
        let mut t = EntityTrust::new("plugin:brace");
        t.update_from_outcome(true, 0.8);
        let json = serde_json::to_vec_pretty(&t).unwrap();

        // Seal it by hand with a nonce whose first byte is '{', reproducing the
        // collision. seal() == nonce(12) || encrypt(nonce, plaintext); open()
        // reads it back regardless of that first byte.
        let mut nonce = [0u8; 12];
        nonce[0] = b'{';
        let ct = crypto::encrypt(&store.dk(), &nonce, &json).unwrap();
        let mut blob = nonce.to_vec();
        blob.extend_from_slice(&ct);
        assert_eq!(
            blob.first(),
            Some(&b'{'),
            "must reproduce the 0x7b-first condition"
        );

        std::fs::write(store.entity_file("plugin:brace"), &blob).unwrap();

        let loaded = store.get("brace").unwrap();
        assert_eq!(
            loaded.action_count, 1,
            "sealed trust must be decrypted, not parsed as plaintext"
        );
        assert_eq!(loaded.success_count, 1);
    }
}
