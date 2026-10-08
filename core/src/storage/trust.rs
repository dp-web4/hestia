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
//!   batch) AND a MANIFEST: every entity file and the `through` it held at that checkpoint. A
//!   checkpoint is a claim about files that were never fsynced, so startup VERIFIES it (every
//!   listed file present, readable, and at least as far as listed) before replaying from it; a
//!   checkpoint that does not verify is ignored and the daemon replays from the EPOCH, which
//!   per-entity `through` makes safe (Codex P1, #1271 review 19153);
//! - the EPOCH (`projection-epoch.json`: the first chain position trust is a projection from) is
//!   written ONCE, fsynced, before any v2 cache file can exist. So "v2 files, no epoch" cannot
//!   arise from a crash, and a legacy cache is told apart from an interrupted v2 projection by
//!   the files' own form (v1 = bare `EntityTrust`), not by the absence of a checkpoint (Codex
//!   P1, #1271 review 19153).
//! - a LEGACY cache's state is pre-epoch: no row rebuilds it. So the migration first copies each
//!   v1 file, sealed and fsynced, into `baseline/` (before the epoch, so an epoch never exists
//!   without its baseline), and an entity whose cache file is missing or set aside is loaded from
//!   its baseline, then replayed from the epoch. A baseline that does not read fails startup
//!   rather than serving fresh trust as a reconstruction (Codex P1, #1271 review 19164).
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
const EPOCH_FILE: &str = "projection-epoch.json";
/// The durable pre-epoch state of a migrated legacy cache: one sealed v1 file per entity.
const BASELINE_DIR: &str = "baseline";

/// An entity cache file (not the checkpoint, the epoch, or a temp file).
fn is_entity_file(p: &Path) -> bool {
    p.extension().and_then(|s| s.to_str()) == Some("json")
        && !matches!(p.file_name().and_then(|s| s.to_str()), Some(PROJECTION_FILE | EPOCH_FILE))
}

fn file_name(p: &Path) -> String {
    p.file_name().and_then(|s| s.to_str()).unwrap_or_default().to_string()
}

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
        self.parse_versioned(raw).map(|(c, _)| c)
    }

    /// As [`parse`](Self::parse), and whether the file is the v2 projection form.
    fn parse_versioned(&self, raw: Vec<u8>) -> Option<(Cached, bool)> {
        // Sealed blobs are nonce-prefixed ChaCha20-Poly1305 with no magic header, so their first
        // byte is random: decrypt first, fall back to legacy plaintext only when AEAD
        // authentication fails (which it always does for genuine plaintext).
        let json: Vec<u8> = match crypto::open(&self.dk(), &raw) {
            Ok(plain) => plain,
            Err(_) => raw,
        };
        if let Ok(f) = serde_json::from_slice::<EntityFile>(&json) {
            return Some((Cached { trust: f.trust, through: f.through }, true));
        }
        serde_json::from_slice::<EntityTrust>(&json)
            .ok()
            .map(|trust| (Cached { trust, through: None }, false))
    }

    /// The cached entity, loading its file on first touch. `None` if it has never existed.
    fn load(&self, entity_id: &str) -> Result<Option<Cached>> {
        if let Some(c) = self.cache().get(entity_id) {
            return Ok(Some(c.clone()));
        }
        let mut path = self.entity_file(entity_id);
        if !path.exists() {
            // No cache file: the entity's pre-epoch baseline, if it had one (replay supplies the rest).
            path = self.base_dir.join(BASELINE_DIR).join(file_name(&path));
            if !path.exists() {
                return Ok(None);
            }
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
        let through = c.through;
        let file = EntityFile { v: 2, through, trust: c.trust.clone() };
        let json = serde_json::to_vec_pretty(&file).context("serializing trust")?;
        let sealed = crypto::seal(&self.dk(), &json).context("sealing trust")?;
        let path = self.entity_file(&c.trust.entity_id);
        self.cache().insert(c.trust.entity_id.clone(), c);
        self.persister.enqueue(path, sealed, through, at.map(|a| a.pos));
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
    /// derives their charge from the chain alone. Read from the durable epoch file; a home from
    /// before that file carried it in `projection.json`.
    pub fn projection_since(&self) -> Option<u64> {
        let read = |name: &str| -> Option<u64> {
            let raw = std::fs::read(self.base_dir.join(name)).ok()?;
            serde_json::from_slice::<serde_json::Value>(&raw).ok()?.get("since")?.as_u64()
        };
        read(EPOCH_FILE).or_else(|| read(PROJECTION_FILE))
    }

    /// Set the epoch every later `projection.json` carries.
    pub fn set_projection_since(&self, since: u64) {
        self.persister.since.store(since, Ordering::Release);
    }

    /// Does this store hold ANY cached entity file?
    pub fn has_entity_files(&self) -> bool {
        std::fs::read_dir(&self.base_dir)
            .map(|rd| rd.flatten().any(|e| is_entity_file(&e.path())))
            .unwrap_or(false)
    }

    /// Every entity file on disk: its name, and — if it reads — whether it is v2 and its `through`.
    fn scan(&self) -> HashMap<String, Option<(bool, Option<u64>)>> {
        let mut out = HashMap::new();
        if let Ok(rd) = std::fs::read_dir(&self.base_dir) {
            for e in rd.flatten() {
                let p = e.path();
                if !is_entity_file(&p) {
                    continue;
                }
                let parsed = std::fs::read(&p).ok().and_then(|raw| self.parse_versioned(raw));
                out.insert(file_name(&p), parsed.map(|(c, v2)| (v2, c.through)));
            }
        }
        out
    }

    /// STARTUP RECOVERY: fix the epoch (durably, once) and decide where replay starts. Returns
    /// `(since, from)`: `since` is the projection epoch, `from` the first chain position replay
    /// must visit. `chain_len` is the chain's length now.
    ///
    /// - The epoch: the recorded one; else a cache of ONLY v1 files is a LEGACY cache — it IS the
    ///   state as of now, so the epoch is the chain head; else (fresh, deleted, or a v2 cache whose
    ///   first checkpoint never landed) 0. Recorded with fsync before any v2 file can be written,
    ///   so a later crash cannot make a v2 cache look legacy.
    /// - The start: the checkpoint's `through + 1` ONLY if its manifest verifies against the
    ///   files; otherwise the epoch. A file that does not read is set aside (`.corrupt`) so the
    ///   replay rebuilds it from the chain.
    pub fn recover(&self, chain_len: u64) -> Result<(u64, u64)> {
        let mut files = self.scan();
        // A file projected through a position the chain does not hold is AHEAD of the chain (a
        // cache written before the barrier existed, or a chain restored from an older copy). It
        // holds changes no row witnesses, so it cannot be a replay base: treat it like a file
        // that does not read — set aside, rebuilt from the chain (Codex, #1271 review 19161).
        for f in files.values_mut() {
            if matches!(f, Some((_, Some(t))) if *t >= chain_len) {
                *f = None;
            }
        }
        let any_v2 = files.values().any(|f| matches!(f, Some((true, _))));
        let any_v1 = files.values().any(|f| matches!(f, Some((false, _))));
        let recorded = self.projection_since();
        let legacy = recorded.is_none() && any_v1 && !any_v2;
        let since = match recorded {
            Some(s) => s,
            None if legacy => chain_len,
            None => 0,
        };
        if std::fs::metadata(self.base_dir.join(EPOCH_FILE)).is_err() {
            if legacy {
                self.write_baseline(&files)?;
            }
            write_durable(&self.base_dir.join(EPOCH_FILE),
                          serde_json::json!({ "since": since }).to_string().as_bytes())?;
        }
        self.set_projection_since(since);
        self.check_baseline(since)?;

        let checkpoint: Option<serde_json::Value> = std::fs::read(self.base_dir.join(PROJECTION_FILE))
            .ok()
            .and_then(|raw| serde_json::from_slice(&raw).ok());
        let through = checkpoint.as_ref().and_then(|c| c.get("through")?.as_u64());
        let verified = !legacy && through.is_some_and(|t| t < chain_len) && checkpoint
            .as_ref()
            .and_then(|c| c.get("entities")?.as_object().cloned())
            .is_some_and(|manifest| {
                manifest.iter().all(|(name, listed)| {
                    let listed = listed.as_u64();
                    matches!(files.get(name), Some(Some((_, t))) if *t >= listed)
                })
            });
        let from = match through {
            Some(p) if verified => p + 1,
            _ => since,
        };
        if through.is_some() && !verified {
            tracing::warn!("trust cache checkpoint does not match its files; replaying from the epoch {since}");
        }
        // A file that does not read cannot be a replay base: set it aside so the chain rebuilds it.
        // (Only a pre-epoch — legacy — part of its state is beyond the chain's reach.)
        for name in files.iter().filter(|(_, p)| p.is_none()).map(|(n, _)| n) {
            let p = self.base_dir.join(name);
            tracing::warn!("trust cache file {} does not read or is ahead of the chain; set aside, rebuilt from the chain", p.display());
            std::fs::rename(&p, p.with_extension("corrupt"))
                .with_context(|| format!("setting aside {}", p.display()))?;
        }
        files.retain(|_, p| p.is_some());
        *self.persister.manifest() =
            files.into_iter().map(|(n, p)| (n, p.and_then(|(_, t)| t))).collect();
        Ok((since, from))
    }

    /// Copy every readable v1 file, sealed and fsynced, into `baseline/`: the pre-epoch state no
    /// chain row can rebuild. Called before the epoch is recorded, so a crash here re-runs it.
    fn write_baseline(&self, files: &HashMap<String, Option<(bool, Option<u64>)>>) -> Result<()> {
        let dir = self.base_dir.join(BASELINE_DIR);
        std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;
        for name in files.iter().filter(|(_, f)| matches!(f, Some((false, _)))).map(|(n, _)| n) {
            let src = self.base_dir.join(name);
            let c = std::fs::read(&src)
                .ok()
                .and_then(|raw| self.parse(raw))
                .with_context(|| format!("re-reading legacy trust {}", src.display()))?;
            let json = serde_json::to_vec(&c.trust).context("serializing trust baseline")?;
            let sealed = crypto::seal(&self.dk(), &json).context("sealing trust baseline")?;
            write_durable(&dir.join(name), &sealed)?;
        }
        std::fs::File::open(&self.base_dir)
            .and_then(|d| d.sync_all())
            .with_context(|| format!("syncing {}", self.base_dir.display()))
    }

    /// A migrated home's baseline must read in full: an entity whose cache is lost would otherwise
    /// be rebuilt over FRESH trust and served as if reconstructed (Codex P1, #1271 review 19164).
    fn check_baseline(&self, since: u64) -> Result<()> {
        let dir = self.base_dir.join(BASELINE_DIR);
        let Ok(rd) = std::fs::read_dir(&dir) else {
            if since > 0 {
                tracing::warn!("trust epoch {since} has no baseline (migrated before #1271 review 19164): \
                                an entity whose cache file is lost loses its pre-epoch state");
            }
            return Ok(());
        };
        for e in rd.flatten() {
            let p = e.path();
            if !is_entity_file(&p) {
                continue;
            }
            let ok = std::fs::read(&p).ok().and_then(|raw| self.parse_versioned(raw));
            anyhow::ensure!(matches!(ok, Some((_, false))),
                "trust baseline {} does not read: pre-epoch trust cannot be reconstructed \
                 (restore it from a backup of {}, or move it aside to accept the loss)",
                p.display(), dir.display());
        }
        Ok(())
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
        // Baselines first: an entity's cache file, where it has one, supersedes its baseline.
        for dir in [self.base_dir.join(BASELINE_DIR), self.base_dir.clone()] {
            let Ok(rd) = std::fs::read_dir(&dir) else { continue };
            for e in rd.flatten() {
                let p = e.path();
                if !is_entity_file(&p) {
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

/// [`write_atomic`] made durable: the data, then the rename (the directory), are fsynced. For the
/// write-once epoch only — the cache files stay unsynced by design.
fn write_durable(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    let tmp = path.with_extension("tmp");
    let mut f = std::fs::File::create(&tmp).with_context(|| format!("creating {}", tmp.display()))?;
    f.write_all(bytes)?;
    f.sync_all().with_context(|| format!("syncing {}", tmp.display()))?;
    drop(f);
    std::fs::rename(&tmp, path).with_context(|| format!("renaming into {}", path.display()))?;
    if let Some(dir) = path.parent() {
        std::fs::File::open(dir)
            .and_then(|d| d.sync_all())
            .with_context(|| format!("syncing {}", dir.display()))?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// WRITE-BEHIND CACHE WRITER. No fsync anywhere: the chain row is the durable fact, these files are
// its projection. Atomic rename keeps a file whole; a lost write is restored by replay.
// ---------------------------------------------------------------------------------------------

#[derive(Default)]
struct PersistQueue {
    /// Latest sealed bytes per file (coalesced), with the `through` they carry.
    files: HashMap<PathBuf, (Vec<u8>, Option<u64>)>,
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
    /// Every entity file written (or found at startup) and the `through` it holds: the manifest
    /// each checkpoint carries, so startup can verify the checkpoint against the files.
    manifest: Mutex<HashMap<String, Option<u64>>>,
    /// Runs before any cache file is written (the daemon: make the witness chain durable first),
    /// so a file can never reach disk ahead of the row it projects (Codex, #1271 review 19161).
    barrier: std::sync::OnceLock<crate::storage::inbox::PreWriteBarrier>,
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
            manifest: Mutex::new(HashMap::new()),
            barrier: std::sync::OnceLock::new(),
        });
        #[cfg(test)]
        TEST_REGISTRY.lock().unwrap_or_else(|e| e.into_inner()).push(Arc::downgrade(&p));
        p
    }

    fn q(&self) -> std::sync::MutexGuard<'_, PersistQueue> {
        self.queue.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Install the pre-write barrier (the daemon: make the witness chain durable first).
    pub fn set_pre_write_barrier(&self, barrier: crate::storage::inbox::PreWriteBarrier) {
        let _ = self.barrier.set(barrier);
    }

    fn manifest(&self) -> std::sync::MutexGuard<'_, HashMap<String, Option<u64>>> {
        self.manifest.lock().unwrap_or_else(|p| p.into_inner())
    }

    fn enqueue(self: &Arc<Self>, path: PathBuf, sealed: Vec<u8>, through: Option<u64>, pos: Option<u64>) {
        {
            let mut q = self.q();
            q.files.insert(path, (sealed, through));
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
        files: &HashMap<PathBuf, (Vec<u8>, Option<u64>)>,
        appends: &[(PathBuf, String)],
        max_pos: Option<u64>,
    ) -> Result<()> {
        use std::io::Write;
        if self.fail_next.swap(false, Ordering::AcqRel) {
            anyhow::bail!("injected trust cache write failure");
        }
        // The rows this batch projects are committed but maybe not yet durable: a file written
        // ahead of its row survives a crash that loses the row, and holds a charge the chain does
        // not (Codex, #1271 review 19161). A failed barrier fails the batch; it is retried.
        if let Some(b) = self.barrier.get() {
            b().map_err(|e| anyhow::anyhow!("chain durability barrier: {e}"))?;
        }
        for (path, (bytes, through)) in files {
            write_atomic(path, bytes)?;
            self.manifest().insert(file_name(path), *through);
        }
        for (path, line) in appends {
            let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path)
                .with_context(|| format!("appending {}", path.display()))?;
            writeln!(f, "{line}")?;
        }
        // Every file is now current through max_pos (each dirty file was just written with its
        // latest value; a clean one has had no change since). Nothing here is fsynced, so the
        // write order is NOT a durability order: the checkpoint carries the manifest it claims,
        // and startup trusts it only where the files bear it out (`TrustStore::recover`).
        if let Some(p) = max_pos {
            let since = self.since.load(Ordering::Acquire);
            let entities: serde_json::Map<String, serde_json::Value> =
                self.manifest().iter().map(|(n, t)| (n.clone(), serde_json::json!(t))).collect();
            write_atomic(&self.dir.join(PROJECTION_FILE),
                         serde_json::json!({"through": p, "since": since, "entities": entities})
                             .to_string().as_bytes())?;
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

    /// Review 19164: v1 history is not a disposable projection. Codex's reproductions, now
    /// asserting the contract: a lost or set-aside migrated cache is rebuilt over its durable
    /// baseline. The chain positions are modeled; only rows at or after the epoch replay.
    fn review_19164_legacy_fixture() -> (TempDir, TrustStore, PathBuf) {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        let mut legacy = EntityTrust::new("plugin:old");
        for _ in 0..7 {
            legacy.update_from_outcome(true, 0.8);
        }
        let path = store.entity_file("plugin:old");
        write_durable(&path, &crypto::seal(&store.dk(), &serde_json::to_vec(&legacy).unwrap()).unwrap()).unwrap();
        assert_eq!(store.recover(10).unwrap(), (10, 10));
        assert_eq!(store.get("old").unwrap().action_count, 7);
        store.update_at("old", false, 0.5, at(10)).unwrap();
        store.persister().flush_blocking();
        assert_eq!(store.get("old").unwrap().action_count, 8);
        (dir, store, path)
    }

    #[test]
    fn review_19164_a_missing_migrated_cache_keeps_its_legacy_baseline() {
        let (dir, store, path) = review_19164_legacy_fixture();
        drop(store);
        // Model a lost unsynced cache file. The modeled chain still contains row 10;
        // neither a chain rollback nor a cache-ahead condition is needed.
        std::fs::remove_file(path).unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(11).unwrap(), (10, 10));
        reopened.update_at("old", false, 0.5, at(10)).unwrap();
        assert_eq!(reopened.get("old").unwrap().action_count, 8,
                   "the 7-action baseline plus row 10");
    }

    #[test]
    fn review_19164_an_ahead_migrated_cache_keeps_its_legacy_baseline() {
        let (dir, store, path) = review_19164_legacy_fixture();
        store.update_at("old", false, 0.5, at(11)).unwrap();
        store.persister().flush_blocking();
        drop(store);
        // Model a restored chain prefix retaining row 10, but not row 11.
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(11).unwrap(), (10, 10));
        assert!(path.with_extension("corrupt").exists());
        reopened.update_at("old", false, 0.5, at(10)).unwrap();
        assert_eq!(reopened.get("old").unwrap().action_count, 8,
                   "rejecting row 11 keeps the 7-action baseline");
    }

    /// An entity with no post-epoch row and a lost cache file is still listed and read.
    #[test]
    fn review_19164_baseline_only_entity_is_read_and_listed() {
        let (dir, store, _) = review_19164_legacy_fixture();
        let quiet = EntityTrust::new("plugin:quiet");
        let path = store.entity_file("plugin:quiet");
        drop(store);
        // A second legacy entity, migrated with the first, never touched after the epoch.
        std::fs::write(dir.path().join(BASELINE_DIR).join(file_name(&path)),
                       crypto::seal(&DerivedKey::from_bytes(KEY), &serde_json::to_vec(&quiet).unwrap()).unwrap()).unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        reopened.recover(11).unwrap();
        assert!(!path.exists());
        let ids: Vec<_> = reopened.all().unwrap().into_iter().map(|(id, _)| id).collect();
        assert_eq!(ids, ["plugin:old", "plugin:quiet"]);
        assert_eq!(reopened.list().unwrap(), ["old", "quiet"]);
    }

    /// The migration writes the baseline before the epoch; a baseline that does not read fails
    /// startup instead of serving fresh trust as a reconstruction.
    #[test]
    fn review_19164_an_unreadable_baseline_fails_recovery() {
        let (dir, store, path) = review_19164_legacy_fixture();
        let baseline = dir.path().join(BASELINE_DIR).join(file_name(&path));
        assert!(baseline.exists(), "the migration wrote the baseline");
        drop(store);
        std::fs::write(&baseline, b"not sealed trust").unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        let err = reopened.recover(11).unwrap_err().to_string();
        assert!(err.contains("does not read"), "{err}");
    }

    #[test]
    fn review_19164_failed_barrier_publishes_nothing_and_retries() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.recover(0).unwrap();
        let held = store.persister().hold_for_test();
        let fail = Arc::new(AtomicBool::new(true));
        let barrier_fail = fail.clone();
        store.persister().set_pre_write_barrier(Arc::new(move || {
            if barrier_fail.load(Ordering::Acquire) { Err("test barrier failure".into()) }
            else { Ok(()) }
        }));
        let append = dir.path().join("deltas.jsonl");
        store.update_at("a", true, 0.8, at(0)).unwrap();
        store.append_after_trust(&append, "test delta".into()).unwrap();
        assert!(!store.persister().run_batch());
        assert!(!store.entity_file("plugin:a").exists());
        assert!(!append.exists());
        assert_eq!(store.projected_through(), None);
        fail.store(false, Ordering::Release);
        assert!(store.persister().run_batch());
        assert!(store.entity_file("plugin:a").exists());
        assert_eq!(std::fs::read_to_string(append).unwrap(), "test delta\n");
        assert_eq!(store.projected_through(), Some(0));
        drop(held);
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

    /// A checkpoint is trusted only where its manifest verifies against the files (Codex 19153).
    #[test]
    fn recovery_trusts_a_checkpoint_only_where_its_files_bear_it_out() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.recover(0).unwrap(), (0, 0), "fresh home: epoch 0");
        store.update_at("a", true, 0.8, at(3)).unwrap();
        store.update_at("b", true, 0.8, at(5)).unwrap();
        store.persister().flush_blocking();
        let lose = store.entity_file("plugin:b");
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(9).unwrap(), (0, 6), "every listed file present: from through+1");
        drop(reopened);
        std::fs::remove_file(&lose).unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(9).unwrap(), (0, 0), "a listed file lost: from the epoch");
    }

    /// A stale file (older than its checkpoint lists) and an unreadable one both fail verification;
    /// the unreadable one is set aside so the replay rebuilds it.
    #[test]
    fn recovery_sets_aside_a_file_ahead_of_the_chain() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.recover(0).unwrap();
        store.update_at("a", true, 0.8, at(2)).unwrap();
        store.update_at("b", true, 0.8, at(5)).unwrap();
        store.persister().flush_blocking();
        let (a, b) = (store.entity_file("plugin:a"), store.entity_file("plugin:b"));
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(4).unwrap(), (0, 0), "checkpoint at 5 is past a 4-row chain");
        assert!(!b.exists() && b.with_extension("corrupt").exists(), "b (through 5) set aside");
        assert!(a.exists(), "a (through 2) kept");
        assert!(reopened.update_at("b", true, 0.8, at(3)).unwrap().is_some(), "rebuilt from the chain");
    }

    #[test]
    fn recovery_replays_over_a_stale_or_unreadable_file() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.recover(0).unwrap();
        store.update_at("a", true, 0.8, at(2)).unwrap();
        store.persister().flush_blocking();
        let path = store.entity_file("plugin:a");
        let old = std::fs::read(&path).unwrap();
        store.update_at("a", true, 0.8, at(4)).unwrap();
        store.persister().flush_blocking();
        drop(store);
        std::fs::write(&path, &old).unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(9).unwrap(), (0, 0), "stale file: from the epoch");
        drop(reopened);
        std::fs::write(&path, b"").unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(9).unwrap(), (0, 0));
        assert!(!path.exists() && path.with_extension("corrupt").exists(), "set aside");
        assert!(reopened.update_at("a", true, 0.8, at(2)).unwrap().is_some(), "rebuilt from the chain");
    }

    /// Only a cache of v1 files is legacy; v2 files without an epoch are a projection from 0.
    #[test]
    fn recovery_tells_legacy_from_an_interrupted_v2_projection() {
        let dir = TempDir::new().unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        store.update_at("a", true, 0.8, at(1)).unwrap();
        store.persister().flush_blocking();
        drop(store);
        // The first batch's entity rename landed; its checkpoint did not.
        std::fs::remove_file(dir.path().join(PROJECTION_FILE)).unwrap();
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(7).unwrap(), (0, 0), "v2 files, no epoch, no checkpoint");
        assert_eq!(reopened.projection_since(), Some(0), "the epoch is now recorded");
        drop(reopened);

        let dir = TempDir::new().unwrap();
        let legacy = EntityTrust::new("plugin:old");
        std::fs::write(dir.path().join("0000000000000000.json"), serde_json::to_vec(&legacy).unwrap()).unwrap();
        let store = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(store.recover(7).unwrap(), (7, 7), "v1 only: legacy, adopted at the head");
        drop(store);
        let reopened = TrustStore::open(dir.path(), KEY).unwrap();
        assert_eq!(reopened.recover(9).unwrap(), (7, 7), "the epoch is durable and fixed");
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
