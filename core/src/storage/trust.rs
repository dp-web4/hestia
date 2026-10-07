//! Trust state persistence — per-entity `EntityTrust`, each **sealed at rest**.
//!
//! Each plugin gets one file under `<HESTIA_HOME>/trust/` named by a hash of
//! its entity id; the file content (the `EntityTrust` JSON) is encrypted with
//! the stable storage key (vault doctrine — no plaintext state). Reuses
//! `web4-trust-core`'s `EntityTrust` math (`update_from_outcome`); only the I/O
//! is local + sealed (so we don't depend on the upstream FileStore's plaintext
//! writes). A legacy plaintext file is read transparently and re-sealed on the
//! next write.
//!
//! Hestia stores trust by plugin_id with a `plugin:` prefix so it slots into
//! the Web4 entity-type taxonomy (`mcp:`, `lct:`, `role:`, etc).

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use web4_core::vault::crypto::{self, DerivedKey};
use web4_trust_core::EntityTrust;

/// Per-entity sealed trust store.
pub struct TrustStore {
    base_dir: PathBuf,
    key: [u8; 32],
    /// The current value of every entity read or written by this process (authoritative while
    /// it runs; the files are what a restart rebuilds from).
    cache: Mutex<std::collections::HashMap<String, EntityTrust>>,
    persister: Arc<TrustPersister>,
}

impl TrustStore {
    /// Open (create) a sealed trust store rooted at `base_dir`, keyed by the
    /// stable storage key.
    pub fn open(base_dir: impl AsRef<Path>, key: [u8; 32]) -> Result<Self> {
        let base_dir = base_dir.as_ref().to_path_buf();
        std::fs::create_dir_all(&base_dir)
            .with_context(|| format!("creating trust dir {}", base_dir.display()))?;
        let persister = TrustPersister::new(base_dir.clone());
        Ok(Self { base_dir, key, cache: Mutex::new(Default::default()), persister })
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

    /// Read + decrypt one entity file. `None` if the file is absent.
    ///
    /// Sealed blobs are nonce-prefixed ChaCha20-Poly1305 with no magic header,
    /// so their first byte is random. The old `first()=='{'` sniff therefore
    /// misread ~1/256 sealed files (those whose nonce starts with 0x7b) as
    /// plaintext, skipped decryption, and failed to parse the ciphertext.
    /// Instead: decrypt first, and only fall back to legacy plaintext when AEAD
    /// authentication fails — which it always does for genuine plaintext, so the
    /// fallback is safe and unambiguous.
    fn load(&self, entity_id: &str) -> Result<Option<EntityTrust>> {
        if let Some(t) = self.cache.lock().unwrap_or_else(|p| p.into_inner()).get(entity_id) {
            return Ok(Some(t.clone()));
        }
        let path = self.entity_file(entity_id);
        if !path.exists() {
            return Ok(None);
        }
        let raw =
            std::fs::read(&path).with_context(|| format!("reading trust {}", path.display()))?;
        let json: Vec<u8> = match crypto::open(&self.dk(), &raw) {
            Ok(plain) => plain,
            Err(_) => raw, // legacy plaintext JSON (predates at-rest encryption)
        };
        let trust: EntityTrust = serde_json::from_slice(&json)
            .with_context(|| format!("parsing trust {}", path.display()))?;
        self.cache
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .insert(entity_id.to_string(), trust.clone());
        Ok(Some(trust))
    }

    /// Seal one entity's trust and hand it to the persister (WRITE-BEHIND: no I/O here; the
    /// request waits for the write before replying). Refused once persistence has failed.
    fn store(&self, trust: &EntityTrust) -> Result<()> {
        let json = serde_json::to_vec_pretty(trust).context("serializing trust")?;
        let sealed = crypto::seal(&self.dk(), &json).context("sealing trust")?;
        let path = self.entity_file(&trust.entity_id);
        self.persister.enqueue(|q, seq| {
            q.trust.insert(path, (sealed, seq));
        })?;
        self.cache
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .insert(trust.entity_id.clone(), trust.clone());
        Ok(())
    }

    /// Append `line` to `path` only AFTER every trust write enqueued before it is durable — for
    /// records that claim a trust change happened (the decision settle record, reputation deltas).
    pub fn append_after_trust(&self, path: &Path, line: String) -> Result<()> {
        let path = path.to_path_buf();
        self.persister.enqueue(|q, seq| q.appends.push((path, line, seq)))?;
        Ok(())
    }

    /// The write-behind persister (frontier, test hooks).
    pub fn persister(&self) -> &Arc<TrustPersister> {
        &self.persister
    }

    /// Fetch (or auto-create) the entity trust for a plugin.
    pub fn get(&self, plugin_id: &str) -> Result<EntityTrust> {
        let id = Self::entity_id(plugin_id);
        match self.load(&id)? {
            Some(t) => Ok(t),
            None => {
                let t = EntityTrust::new(&id);
                self.store(&t)?;
                Ok(t)
            }
        }
    }

    /// Apply an outcome and persist. Returns the updated entity trust.
    pub fn update(&self, plugin_id: &str, success: bool, magnitude: f64) -> Result<EntityTrust> {
        Ok(self
            .update_returning_prior(plugin_id, success, magnitude)?
            .1)
    }

    /// Apply an outcome and persist, returning `(before, after)` so the caller can
    /// diff the tensor movement into a `ReputationDelta` (the trust-tensor bridge,
    /// P3a). One read + one write, same as `update`.
    pub fn update_returning_prior(
        &self,
        plugin_id: &str,
        success: bool,
        magnitude: f64,
    ) -> Result<(EntityTrust, EntityTrust)> {
        let before = self.get(plugin_id)?;
        let mut after = before.clone();
        after.update_from_outcome(success, magnitude);
        self.store(&after)?;
        Ok((before, after))
    }

    /// Apply an adjudicated V3 observation to an entity (the T3-from-V3 arc's
    /// `#adjudicated` grain — NEVER the execution entity, whose stored V3 is a
    /// saturating action counter). Returns `(before, after)` for the delta
    /// bridge, same shape as [`Self::update_returning_prior`].
    pub fn update_v3_returning_prior(
        &self,
        plugin_id: &str,
        dimension: web4_core::v3::ValueDimension,
        score: f64,
    ) -> Result<(EntityTrust, EntityTrust)> {
        let before = self.get(plugin_id)?;
        let mut after = before.clone();
        after
            .v3
            .observe(dimension, score)
            .map_err(|e| anyhow::anyhow!("v3 observe: {e}"))?;
        self.store(&after)?;
        Ok((before, after))
    }

    /// List known plugin_ids (without the `plugin:` prefix when applicable).
    /// The filename is a hash, so we read each file to recover its entity id.
    pub fn list(&self) -> Result<Vec<String>> {
        let mut out = Vec::new();
        let rd = match std::fs::read_dir(&self.base_dir) {
            Ok(rd) => rd,
            Err(_) => return Ok(out),
        };
        for entry in rd.flatten() {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let Ok(raw) = std::fs::read(&path) else {
                continue;
            };
            // Decrypt-first, fall back to legacy plaintext on AEAD failure (see load()).
            let json = match crypto::open(&self.dk(), &raw) {
                Ok(b) => b,
                Err(_) => raw,
            };
            if let Ok(t) = serde_json::from_slice::<EntityTrust>(&json) {
                out.push(
                    t.entity_id
                        .strip_prefix("plugin:")
                        .unwrap_or(&t.entity_id)
                        .to_string(),
                );
            }
        }
        // Entities created by this process whose first write is still queued.
        for id in self.cache.lock().unwrap_or_else(|p| p.into_inner()).keys() {
            let name = id.strip_prefix("plugin:").unwrap_or(id).to_string();
            if !out.contains(&name) {
                out.push(name);
            }
        }
        out.sort();
        Ok(out)
    }
}

impl Drop for TrustStore {
    /// A clean shutdown leaves nothing queued unwritten.
    fn drop(&mut self) {
        let _ = self.persister.flush_blocking();
    }
}

// ---------------------------------------------------------------------------------------------
// WRITE-BEHIND PERSISTENCE (trust off the state lock, #1266 follow-up).
//
// Measured on #1266: `trust_store.update` — read, decrypt, update, re-seal and TRUNCATING rewrite
// of a per-member file — became the global lock's top holder once the chain fsync left it (up to
// 626 ms under disk pressure; ext4 forces writeback on truncate-and-rewrite). Trust is rebuilt at
// startup from these files, so they stay authoritative; what moves is WHEN they are written.
//
// Under the lock the store now only updates an in-memory cache and enqueues the sealed bytes. A
// persister thread drains the queue in batches: every trust file in the batch is written
// atomically (tmp + fsync + rename, then one directory fsync), and only THEN are the batch's
// ordered appends written (the decision settle record, reputation deltas) — so no settle line or
// emitted delta can ever be on disk for a trust change that is not. A request waits (after the
// lock) until everything it enqueued is durable, and only then replies.
//
// A persistence FAILURE is fatal, the same rule as the chain fsync: the store is poisoned, waiters
// get an error (never "recorded"), every later trust write is refused, and the daemon's fatal hook
// restarts it so memory is rebuilt from the files. Exactly-once survives: a charge whose trust
// write never landed has no settle line, so it reads as OWED after the restart and settles once.
// ---------------------------------------------------------------------------------------------

use crate::storage::durability::{Frontier, FrontierCell};
use std::collections::HashMap as PersistMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};

#[derive(Default)]
struct PersistQueue {
    /// Latest sealed bytes per trust file (coalesced), with the seq that produced them.
    trust: PersistMap<PathBuf, (Vec<u8>, u64)>,
    /// Ordered line appends that must follow the trust writes enqueued before them.
    appends: Vec<(PathBuf, String, u64)>,
    next_seq: u64,
    shutdown: bool,
}

pub struct TrustPersister {
    dir: PathBuf,
    queue: Mutex<PersistQueue>,
    cv: Condvar,
    frontier: FrontierCell,
    started: AtomicBool,
    hold: AtomicBool,
    fail_next: AtomicBool,
}

impl TrustPersister {
    fn new(dir: PathBuf) -> Arc<Self> {
        let (tx, _rx) = tokio::sync::watch::channel(Frontier { durable: 0, poisoned: false });
        let p = Arc::new(Self {
            dir,
            queue: Mutex::new(PersistQueue { next_seq: 1, ..Default::default() }),
            cv: Condvar::new(),
            frontier: Arc::new(tx),
            started: AtomicBool::new(false),
            hold: AtomicBool::new(false),
            fail_next: AtomicBool::new(false),
        });
        #[cfg(test)]
        TEST_REGISTRY.lock().unwrap_or_else(|e| e.into_inner()).push(Arc::downgrade(&p));
        p
    }

    pub fn frontier(&self) -> Frontier {
        *self.frontier.borrow()
    }

    fn poisoned(&self) -> bool {
        self.frontier().poisoned
    }

    fn q(&self) -> std::sync::MutexGuard<'_, PersistQueue> {
        self.queue.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Enqueue; registers the seq with the current request's durability scope.
    fn enqueue(self: &Arc<Self>, f: impl FnOnce(&mut PersistQueue, u64)) -> Result<u64> {
        anyhow::ensure!(
            !self.poisoned(),
            "trust persistence failed earlier: trust writes are refused until the daemon restarts"
        );
        let seq = {
            let mut q = self.q();
            let seq = q.next_seq;
            q.next_seq += 1;
            f(&mut q, seq);
            seq
        };
        self.ensure_thread();
        self.cv.notify_one();
        crate::storage::durability::note_frontier(&self.frontier, seq);
        Ok(seq)
    }

    fn ensure_thread(self: &Arc<Self>) {
        if self.started.swap(true, Ordering::AcqRel) {
            return;
        }
        let weak = Arc::downgrade(self);
        if std::thread::Builder::new()
            .name("hestia-trust-persister".into())
            .spawn(move || persister_loop(weak))
            .is_err()
        {
            self.started.store(false, Ordering::Release);
        }
    }

    /// Drain everything queued now, synchronously (shutdown, no-thread fallback, tests).
    pub fn flush_blocking(&self) -> Result<()> {
        loop {
            if self.poisoned() {
                anyhow::bail!("trust persistence failed");
            }
            let target = self.q().next_seq - 1;
            if self.frontier().durable >= target {
                return Ok(());
            }
            if !self.started.load(Ordering::Acquire) {
                self.run_batch();
            } else {
                self.cv.notify_one();
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
        }
    }

    /// One batch: trust files atomically, directory fsync, then the ordered appends.
    fn run_batch(&self) {
        let (trust, appends, top) = {
            let mut q = self.q();
            let top = q.next_seq - 1;
            (std::mem::take(&mut q.trust), std::mem::take(&mut q.appends), top)
        };
        if trust.is_empty() && appends.is_empty() {
            return;
        }
        let res = crate::server::state_lock::time_section("trust.persist", || {
            self.write_batch(&trust, &appends)
        });
        match res {
            Ok(()) => self.frontier.send_modify(|f| {
                if !f.poisoned && top > f.durable {
                    f.durable = top;
                }
            }),
            Err(e) => {
                let why = format!("{e:#}");
                self.frontier.send_modify(|f| f.poisoned = true);
                tracing::error!(why, "trust persistence FAILED: refusing every further trust write");
                eprintln!("[hestia] FATAL: trust persistence failed ({why})");
                crate::storage::durability::trigger_fatal(&why);
            }
        }
    }

    fn write_batch(
        &self,
        trust: &PersistMap<PathBuf, (Vec<u8>, u64)>,
        appends: &[(PathBuf, String, u64)],
    ) -> Result<()> {
        use std::io::Write;
        if self.fail_next.swap(false, Ordering::AcqRel) {
            anyhow::bail!("injected trust persistence failure");
        }
        for (path, (bytes, _)) in trust {
            let tmp = path.with_extension("json.tmp");
            let mut f = std::fs::File::create(&tmp)
                .with_context(|| format!("creating {}", tmp.display()))?;
            f.write_all(bytes)?;
            f.sync_all()?;
            std::fs::rename(&tmp, path).with_context(|| format!("renaming into {}", path.display()))?;
        }
        if !trust.is_empty() {
            std::fs::File::open(&self.dir)?.sync_all()?;
        }
        let mut touched: Vec<&Path> = Vec::new();
        for (path, line, _) in appends {
            let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path)
                .with_context(|| format!("appending {}", path.display()))?;
            writeln!(f, "{line}")?;
            if !touched.contains(&path.as_path()) {
                touched.push(path.as_path());
            }
        }
        for p in touched {
            std::fs::OpenOptions::new().append(true).open(p)?.sync_all()?;
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
}

#[cfg(test)]
static TEST_REGISTRY: Mutex<Vec<std::sync::Weak<TrustPersister>>> = Mutex::new(Vec::new());

/// Tests that read a persisted side file (the reputation sink, the settle record) right after a
/// direct tool call flush every live persister first: the write-behind is real, the read waits.
#[cfg(test)]
pub fn flush_all_for_test() {
    let live: Vec<Arc<TrustPersister>> = TEST_REGISTRY
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .filter_map(|w| w.upgrade())
        .collect();
    for p in live {
        let _ = p.flush_blocking();
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
            if q.trust.is_empty() && q.appends.is_empty() {
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
        if p.hold.load(Ordering::Acquire) || p.poisoned() {
            std::thread::sleep(std::time::Duration::from_millis(5));
            continue;
        }
        p.run_batch();
        drop(p);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const KEY: [u8; 32] = [3u8; 32];

    /// Write-behind: a trust update returns at once (no I/O under the caller's lock), the request
    /// waiting on it does not finish until the file is durable, and a reopen sees the value.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn a_trust_update_is_acknowledged_only_once_its_file_is_durable() {
        let dir = TempDir::new().unwrap();
        let store = Arc::new(TrustStore::open(dir.path(), KEY).unwrap());
        let hold = store.persister().hold_for_test();
        let st = store.clone();
        let mut req = tokio::spawn(async move {
            crate::storage::durability::durable_scope(async { st.update("claude-code", true, 0.8).unwrap() }).await
        });
        if tokio::time::timeout(std::time::Duration::from_millis(400), &mut req).await.is_ok() {
            panic!("a trust update was acknowledged before its file was durable");
        }
        assert_eq!(store.get("claude-code").unwrap().action_count, 1, "memory moved at once");
        drop(hold);
        let (t, res) = req.await.unwrap();
        res.unwrap();
        assert_eq!(t.action_count, 1);
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.get("claude-code").unwrap().action_count, 1);
    }

    /// A settle/delta line is written only after the trust writes queued before it are durable,
    /// so a failed trust write leaves no line claiming it happened; and the store then refuses.
    #[test]
    fn a_line_never_reaches_disk_for_a_trust_write_that_did_not() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        let side = dir.path().join("settled.jsonl");
        // Queue both into ONE batch (held), then let that batch fail.
        let hold = store.persister().hold_for_test();
        store.update("claude-code", false, 0.5).unwrap();
        store.append_after_trust(&side, "{\"settled\":1}".into()).unwrap();
        store.persister().inject_failure();
        drop(hold);
        assert!(store.persister().flush_blocking().is_err(), "the batch failed");
        assert!(!side.exists(), "a line claims a trust change that never reached disk");
        assert!(store.update("claude-code", true, 0.5).is_err(), "poisoned: later writes refused");
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
        store.persister().flush_blocking().unwrap();
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

        store.persister().flush_blocking().unwrap();
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
