//! SQLite-backed hash-linked witness chain.
//!
//! Entries are append-only. Each entry's `hash` is the sha256 of
//! `prev_hash || timestamp_rfc3339 || event_type || event_data_json`,
//! so any tamper to the JSON, timestamp, or type breaks the chain.
//! The genesis entry's `prev_hash` is `"0" * 64`.
//!
//! ## Two predicates, not one (#339, B2)
//!
//! That legacy `hash` deliberately omits `signer_lct` and `chain_position`, so **link
//! integrity** ([`SqliteChainStore::verify_integrity`]) cannot see a row whose named signer or
//! coordinate was rewritten. It is kept unchanged — every receipt, appeal pointer and
//! `deny_hash` addresses rows by it — and a second predicate is layered beside it:
//!
//! - **signature authenticity**: when a [`ChainWitnessSigner`] is installed, each new row is
//!   Ed25519-signed, in the SAME transaction as its insert, over a versioned envelope
//!   ([`hestia_wire::ChainSignatureV1Fields`]) binding chain id, position, row hash, the row's
//!   `signer_lct`, the witness LCT, the witness public key and the policy generation. The
//!   signature lives in the additive `chain_signatures` side table keyed by position; no
//!   existing row is rewritten.
//!
//! [`SqliteChainStore::verify_chain`] reports both. Rows from before signing report
//! `legacy_unsigned`. Once a chain has a signed row, an unsigned row at or after it is a
//! downgrade and fails authenticity, and this store refuses to append one.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};

use hestia_wire::{
    canonical_chain_signature_preimage, ChainSignatureV1Fields, CHAIN_SIGNATURE_VERSION_V1,
};
use web4_core::crypto::{KeyPair, PublicKey, SignatureBytes};

/// One entry in the witness chain. Identical shape to the in-memory
/// `state::ChainEntry`; re-exported via the storage module.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChainEntry {
    pub hash: String,
    pub prev_hash: String,
    pub timestamp: DateTime<Utc>,
    pub event_type: String,
    pub event_data: serde_json::Value,
    pub signer_lct: String,
    pub chain_position: u64,
}

/// One chain row, borrowed for the lifetime of a [`SqliteChainStore::scan_recent`]
/// projection callback.
///
/// `event_data` is deliberately the **raw JSON text**, not a parsed `serde_json::Value`.
/// The whole point of this type is that the caller decides what — if anything — to parse,
/// so a window of ten thousand rows costs ten thousand *projections* rather than ten
/// thousand documents.
#[derive(Debug, Clone, Copy)]
pub struct ChainRowRef<'a> {
    pub chain_position: u64,
    pub hash: &'a str,
    pub prev_hash: &'a str,
    pub event_type: &'a str,
    pub event_data: &'a str,
    pub signer_lct: &'a str,
    pub timestamp: &'a str,
}

impl ChainRowRef<'_> {
    /// Deserialise `event_data` into a projection struct naming only the fields wanted.
    ///
    /// Returns `None` on malformed JSON rather than failing the scan: one unparseable
    /// entry must not cost the other 9,999. A caller that needs to know the difference
    /// should project `Option`-typed fields and count the misses.
    pub fn project<T: serde::de::DeserializeOwned>(&self) -> Option<T> {
        serde_json::from_str(self.event_data).ok()
    }
}

// ------------------------------------------------------------------ B2 signed witness (#339)

/// The policy generation recorded when no policy publication has been bound to the signer
/// (CLI receiver passes, the window before the daemon's first publication). Explicit rather
/// than empty so a reader can tell "witnessed outside any published law" from a bug.
pub const POLICY_GENERATION_NONE: &str = "none";

const CHAIN_ID_PREFIX: &str = "hestia-chain:";
const META_CHAIN_ID: &str = "chain_id";
const META_SIGNED_FROM: &str = "signed_from_position";
const META_SIGNER_ALIAS_PREFIX: &str = "signer_alias:";
/// How many individual signature failures a [`ChainVerification`] lists (all are counted).
const MAX_LISTED_FAILURES: usize = 50;

/// A chain's stable identity: derived from its genesis row's hash, so it needs no minting,
/// survives copies and restarts, cannot be lost from a side table, and is recomputable by an
/// external verifier from the chain alone. Two chains share it only if they share genesis.
pub fn chain_id_for_genesis(genesis_hash: &str) -> String {
    format!("{CHAIN_ID_PREFIX}{genesis_hash}")
}

/// The chain witness: who attests a row's ordering and inclusion (decision 0014 §6.1's
/// chain-witness role, distinct from an actor signature over an act).
///
/// `witness_lct` must be the key-derived LCT of `keypair` (`web4_core::derive_lct_id`), which
/// makes every signature self-certifying: a verifier checks the embedded public key derives the
/// claimed witness LCT, with no registry lookup and no "whatever key the LCT has now" — a
/// later rotation produces a new LCT and leaves old rows verifiable under the key they carry.
pub struct ChainWitnessSigner {
    keypair: KeyPair,
    witness_lct: String,
    public_key_hex: String,
    /// Legacy signer strings recorded as this witness's LCT on new rows (the sovereign's
    /// `phase1-placeholder` anchor). See [`SqliteChainStore::append`].
    signer_aliases: Vec<String>,
    policy_generation: Mutex<String>,
}

impl ChainWitnessSigner {
    /// Fails unless `witness_lct` is the LCT derived from `keypair`'s public key.
    pub fn new(keypair: KeyPair, witness_lct: &str) -> Result<Self> {
        let derived = web4_core::derive_lct_id(&keypair.verifying_key());
        anyhow::ensure!(
            derived == witness_lct,
            "chain witness LCT {witness_lct} is not derived from its signing key ({derived})"
        );
        let public_key_hex = hex::encode(keypair.public_key_bytes());
        Ok(Self {
            keypair,
            witness_lct: witness_lct.to_string(),
            public_key_hex,
            signer_aliases: Vec::new(),
            policy_generation: Mutex::new(POLICY_GENERATION_NONE.to_string()),
        })
    }

    /// Record `alias` as a legacy name for this witness: a row appended with
    /// `signer_lct == alias` is stored (and signed) under `witness_lct` instead.
    pub fn with_signer_alias(mut self, alias: &str) -> Self {
        if !alias.is_empty() && alias != self.witness_lct {
            self.signer_aliases.push(alias.to_string());
        }
        self
    }

    pub fn witness_lct(&self) -> &str {
        &self.witness_lct
    }

    pub fn public_key_hex(&self) -> &str {
        &self.public_key_hex
    }

    pub fn signer_aliases(&self) -> &[String] {
        &self.signer_aliases
    }

    /// Bind the policy generation subsequent rows are witnessed under.
    pub fn set_policy_generation(&self, generation: &str) {
        let g = if generation.is_empty() { POLICY_GENERATION_NONE } else { generation };
        *self.policy_generation.lock().unwrap() = g.to_string();
    }

    pub fn policy_generation(&self) -> String {
        self.policy_generation.lock().unwrap().clone()
    }

    fn canonical_signer(&self, signer_lct: &str) -> String {
        if self.signer_aliases.iter().any(|a| a == signer_lct) {
            self.witness_lct.clone()
        } else {
            signer_lct.to_string()
        }
    }
}

/// One row's chain-witness signature, as stored in `chain_signatures`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChainSignatureRecord {
    pub chain_position: u64,
    /// The legacy `hash` of the row this signature was made for.
    pub row_hash: String,
    pub signature_version: u32,
    pub chain_id: String,
    pub witness_lct: String,
    /// Lowercase hex Ed25519 public key (the signing-time key identity).
    pub witness_public_key: String,
    pub policy_generation: String,
    /// Lowercase hex Ed25519 signature over the v1 preimage.
    pub signature: String,
}

/// The v1 preimage for a row as it stands. Every row-side field comes from the ROW (or the
/// chain), never from the signature record, so rewriting the row breaks the signature.
fn signature_preimage(
    chain_id: &str,
    chain_position: u64,
    row_hash: &str,
    signer_lct: &str,
    witness_lct: &str,
    witness_public_key: &str,
    policy_generation: &str,
) -> Vec<u8> {
    let position = chain_position.to_string();
    canonical_chain_signature_preimage(&ChainSignatureV1Fields {
        chain_id,
        chain_position: &position,
        row_hash,
        signer_lct,
        witness_lct,
        witness_public_key,
        policy_generation,
    })
}

/// Verify one row's signature record against the row it is attached to and the chain's
/// derived id. `Err` carries a human-readable reason. Pure: no store access.
pub fn verify_row_signature(
    chain_id: &str,
    chain_position: u64,
    row_hash: &str,
    signer_lct: &str,
    rec: &ChainSignatureRecord,
) -> std::result::Result<(), String> {
    if rec.signature_version != CHAIN_SIGNATURE_VERSION_V1 {
        return Err(format!("unknown signature_version {}", rec.signature_version));
    }
    if rec.row_hash != row_hash {
        return Err("signature was made for a different row hash".into());
    }
    if rec.chain_id != chain_id {
        return Err(format!("signature names chain {} but the row is in {chain_id}", rec.chain_id));
    }
    let pk_bytes: [u8; 32] = hex::decode(&rec.witness_public_key)
        .ok()
        .and_then(|b| b.try_into().ok())
        .ok_or("witness_public_key is not 32 hex bytes")?;
    let pk = PublicKey::from_bytes(&pk_bytes).map_err(|e| format!("witness_public_key: {e}"))?;
    if web4_core::derive_lct_id(&pk) != rec.witness_lct {
        return Err("witness_lct is not derived from witness_public_key".into());
    }
    let sig_bytes: [u8; 64] = hex::decode(&rec.signature)
        .ok()
        .and_then(|b| b.try_into().ok())
        .ok_or("signature is not 64 hex bytes")?;
    let pre = signature_preimage(
        chain_id,
        chain_position,
        row_hash,
        signer_lct,
        &rec.witness_lct,
        &rec.witness_public_key,
        &rec.policy_generation,
    );
    pk.verify(&pre, &SignatureBytes::from_bytes(sig_bytes))
        .map_err(|_| "Ed25519 signature does not verify over the row's v1 envelope".to_string())
}

/// Per-row authenticity verdict, as [`SqliteChainStore::verify_chain`] classifies it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SignatureState {
    /// Written before signing began; passes link integrity only.
    LegacyUnsigned,
    /// Carries a v1 signature that verifies.
    Valid,
    /// Carries a signature that does not verify.
    Invalid,
    /// No signature at or after the point the chain became signed: a downgrade.
    MissingAfterSigned,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignatureFailure {
    pub chain_position: u64,
    pub state: SignatureState,
    pub reason: String,
}

/// Rows attested by one witness key.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WitnessKeyUse {
    pub witness_lct: String,
    pub rows: u64,
    pub first_position: u64,
    pub last_position: u64,
}

/// Both predicates over one consistent snapshot. Evidence, not a verdict: which witness keys a
/// relying party accepts is theirs to decide (`witnesses` lists every key that signed).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChainVerification {
    pub length: u64,
    /// Derived from the genesis row; `None` for an empty chain.
    pub chain_id: Option<String>,
    /// What `chain_meta` records (informational; a mismatch is reported in `meta_mismatch`).
    pub recorded_chain_id: Option<String>,
    /// Link integrity: the first break, if any (the walk continues past it for signatures).
    pub link_break: Option<String>,
    pub legacy_unsigned: u64,
    pub signed_valid: u64,
    pub signature_failures: u64,
    /// The first [`MAX_LISTED_FAILURES`] failures.
    pub failures: Vec<SignatureFailure>,
    /// First position carrying a signature row.
    pub first_signed_position: Option<u64>,
    /// What `chain_meta` records as the position signing began.
    pub recorded_signed_from: Option<u64>,
    /// Signature rows at positions with no chain row.
    pub orphan_signatures: u64,
    pub meta_mismatch: Option<String>,
    /// Keyed by witness public key hex.
    pub witnesses: BTreeMap<String, WitnessKeyUse>,
}

impl ChainVerification {
    /// Predicate 1: the legacy hash chain links from genesis to tail.
    pub fn link_intact(&self) -> bool {
        self.link_break.is_none()
    }

    /// Predicate 2: every row that should carry a signature carries a valid one.
    pub fn signatures_authentic(&self) -> bool {
        self.signature_failures == 0 && self.orphan_signatures == 0 && self.meta_mismatch.is_none()
    }
}

/// Witness chain persisted to SQLite. Locking is internal so the store
/// is `Send + Sync` from the caller's perspective.
pub struct SqliteChainStore {
    /// Authoritative append connection. Reads that can be long-running belong
    /// on `read_conn` so a display projection never waits on this process-local
    /// mutex before a witness write can begin.
    conn: Mutex<Connection>,
    /// Dedicated query-only connection. WAL mode lets its snapshot coexist
    /// with an append transaction; the mutex serializes display/read
    /// projections with each other, never with the writer.
    read_conn: Mutex<Connection>,
    path: PathBuf,
    /// Cached entry count, so `len()` is O(1) instead of an O(n) `COUNT(*)`.
    ///
    /// WHY THIS IS NOT A MICRO-OPTIMISATION. `len()` sits on the hot path of every
    /// governed tool call: `tool_begin_action` (handler.rs) calls `s.chain_len()` while
    /// holding the daemon's GLOBAL `state.lock()`, purely to fill in the advisory
    /// `chainPosition` echoed back to the caller. So every member's tool call paid a full
    /// index scan of an encrypted 163MB chain — with every page decrypted — before any
    /// other member could get a policy verdict.
    ///
    /// Measured on CBP 2026-08-08 against the live daemon
    /// (`tools/gate_handshake_latency_probe.py`, `tools/gate_lock_contention_test.py`,
    /// 120,789 entries): `begin_action` p50 **18ms** versus `query_policy` p50 **3.2ms** —
    /// counting the ledger cost 5.6x more than evaluating the policy that is the point of
    /// the call. Because the lock serialises members, median handshake latency scaled
    /// linearly with concurrency (29.9 / 52.2 / 101.3 / 202.4 ms at C=1/2/4/8) and at C=8
    /// **19/320 calls exceeded the harness gate's 800ms budget**, each one a fail-closed
    /// deny with `cause=timeout`. That matches the observed refusal class exactly: 73/73
    /// carried `timeout`, `refused` never once occurred.
    ///
    /// EXACT, NOT APPROXIMATE. The count is initialised from `COUNT(*)` at open and
    /// incremented only after a committed append. That is sound because the chain is
    /// strictly append-only: `chain_position` is `INTEGER PRIMARY KEY`, `append()` derives
    /// the next position from the tail row, and there is no `DELETE FROM chain_entries`,
    /// `DROP TABLE` or `VACUUM` anywhere in the crate — a hash chain that dropped rows
    /// would fail its own verification. `chain_len_cache_matches_count` pins that
    /// invariant against the real `COUNT(*)`, so the cache cannot drift silently if a
    /// deletion path is ever added.
    len: std::sync::Arc<AtomicU64>,
    /// Group commit: the fsync that used to run inside every COMMIT (under the daemon's state
    /// lock) runs here, once per group, outside it. See `storage::durability`.
    durability: std::sync::Arc<super::durability::Durability>,
    /// Cached trust derivations, invalidated HERE, on append.
    ///
    /// The store is the one path every chain write takes. An invalidation hook anywhere else
    /// — a handler, the witness helper — is one a future writer can land evidence without
    /// passing, and a cache that silently misses an invalidation shows a member a trust level
    /// its own record has already contradicted. See `derivation_cache`.
    derivations: crate::derivation_cache::DerivationCache,
    /// The highest chain length any read has observed (see `read_high_water`).
    read_high_water: AtomicU64,
    /// The chain witness (#339). `None` = this handle appends unsigned rows, which it may only
    /// do on a chain that has never been signed.
    signer: RwLock<Option<Arc<ChainWitnessSigner>>>,
    /// Cached chain id, once a genesis row exists.
    chain_id: Mutex<Option<String>>,
}

impl Drop for SqliteChainStore {
    /// A clean shutdown leaves nothing committed-but-unsynced behind.
    fn drop(&mut self) {
        let n = self.len.load(Ordering::Acquire);
        let _ = self.durability.wait_durable_blocking(n);
    }
}

/// A store connection inside one read transaction whose snapshot frontier has been registered
/// (see `SqliteChainStore::observed`). Ends the transaction on drop.
struct ObservedConn<'a> {
    guard: std::sync::MutexGuard<'a, Connection>,
}

impl std::ops::Deref for ObservedConn<'_> {
    type Target = Connection;
    fn deref(&self) -> &Connection {
        &self.guard
    }
}

impl Drop for ObservedConn<'_> {
    fn drop(&mut self) {
        if !self.guard.is_autocommit() && self.guard.execute_batch("COMMIT").is_err() {
            let _ = self.guard.execute_batch("ROLLBACK");
        }
    }
}

const GENESIS_PREV_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// Whether `path` is a legacy *plaintext* SQLite DB (header "SQLite format 3").
/// An encrypted SQLCipher DB has a random-looking header instead.
fn is_plaintext_sqlite(path: &Path) -> bool {
    use std::io::Read;
    let mut hdr = [0u8; 16];
    std::fs::File::open(path)
        .and_then(|mut f| f.read_exact(&mut hdr))
        .map(|_| &hdr == b"SQLite format 3\0")
        .unwrap_or(false)
}

/// Migrate a plaintext SQLite witness DB to a SQLCipher-encrypted one in place,
/// preserving every row (hashes + chain order intact). Uses SQLCipher's
/// `sqlcipher_export` to copy the whole schema + data into a freshly-keyed DB,
/// then atomically replaces the original. `key_hex` is the SQLCipher key.
fn migrate_plaintext_to_encrypted(path: &Path, key_hex: &str) -> Result<()> {
    let tmp = path.with_extension("db.enc-migrating");
    let _ = std::fs::remove_file(&tmp);
    // `key_hex` is [0-9a-f] only, so single-quoting it is safe; the temp path
    // is one we control (no quotes).
    {
        let conn = Connection::open(path).context("opening plaintext witness DB for migration")?;
        conn.execute_batch(&format!(
            "ATTACH DATABASE '{}' AS enc KEY '{}'; \
             SELECT sqlcipher_export('enc'); \
             DETACH DATABASE enc;",
            tmp.display(),
            key_hex,
        ))
        .context("exporting plaintext witness chain into an encrypted copy")?;
    }
    std::fs::rename(&tmp, path).context("replacing plaintext witness DB with encrypted")?;
    Ok(())
}

/// Refuse a snapshot destination that is, or would replace, the source database or one of its
/// SQLite side files, however it is spelled (Codex review of #1322). `backup_encrypted` deletes
/// an existing destination before it opens the source, so a lexical comparison is not enough:
/// a parent-directory symlink, a symlinked destination, or a hard link would make that delete
/// unlink the live chain. Every check runs before any destructive step.
fn refuse_snapshot_alias(source: &Path, destination: &Path) -> Result<()> {
    let source_real = std::fs::canonicalize(source)
        .with_context(|| format!("resolving chain snapshot source {}", source.display()))?;
    if let Ok(meta) = std::fs::symlink_metadata(destination) {
        anyhow::ensure!(
            !meta.file_type().is_symlink(),
            "chain snapshot destination {} is a symlink; refusing to replace it",
            destination.display()
        );
    }
    let name = destination
        .file_name()
        .with_context(|| format!("chain snapshot destination {} has no file name", destination.display()))?;
    let parent = match destination.parent() {
        Some(p) if !p.as_os_str().is_empty() => p,
        _ => Path::new("."),
    };
    let destination_real = std::fs::canonicalize(parent)
        .with_context(|| format!("resolving chain snapshot dir {}", parent.display()))?
        .join(name);
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let mut side = source_real.clone().into_os_string();
        side.push(suffix);
        anyhow::ensure!(
            destination_real != Path::new(&side),
            "chain snapshot destination {} resolves to the source {}",
            destination.display(),
            Path::new(&side).display()
        );
    }
    #[cfg(unix)]
    if let Ok(dest_meta) = std::fs::metadata(&destination_real) {
        use std::os::unix::fs::MetadataExt;
        let src_meta = std::fs::metadata(&source_real)?;
        anyhow::ensure!(
            (dest_meta.dev(), dest_meta.ino()) != (src_meta.dev(), src_meta.ino()),
            "chain snapshot destination {} is a hard link to the source {}",
            destination.display(),
            source_real.display()
        );
    }
    Ok(())
}

impl SqliteChainStore {
    /// Copy one consistent encrypted chain snapshot while its live daemon may
    /// continue appending in WAL mode.
    ///
    /// A raw copy of only `witness.db` is not a snapshot once committed frames
    /// may still live in `witness.db-wal`. SQLite's online backup API reads one
    /// transactionally consistent view across both and re-encrypts it through a
    /// separately keyed destination connection. The destination is replaced,
    /// matching `std::fs::copy` semantics used by the callers this supersedes.
    pub fn backup_encrypted(
        source_path: impl AsRef<Path>,
        destination_path: impl AsRef<Path>,
        key: [u8; 32],
    ) -> Result<()> {
        let source_path = source_path.as_ref();
        let destination_path = destination_path.as_ref();
        anyhow::ensure!(
            source_path != destination_path,
            "chain snapshot destination must differ from its source"
        );
        if let Some(parent) = destination_path.parent() {
            std::fs::create_dir_all(parent).with_context(|| {
                format!("creating chain snapshot dir {}", parent.display())
            })?;
        }
        refuse_snapshot_alias(source_path, destination_path)?;
        if destination_path.exists() {
            std::fs::remove_file(destination_path).with_context(|| {
                format!(
                    "removing prior chain snapshot {}",
                    destination_path.display()
                )
            })?;
        }

        let key_hex = hex::encode(key);
        let source = Connection::open(source_path)
            .with_context(|| format!("opening chain snapshot source {}", source_path.display()))?;
        source
            .pragma_update(None, "key", &key_hex)
            .with_context(|| "keying chain snapshot source")?;
        source
            .pragma_update(None, "query_only", true)
            .with_context(|| "making chain snapshot source query-only")?;

        let mut destination = Connection::open(destination_path).with_context(|| {
            format!(
                "opening chain snapshot destination {}",
                destination_path.display()
            )
        })?;
        destination
            .pragma_update(None, "key", &key_hex)
            .with_context(|| "keying chain snapshot destination")?;
        let backup = rusqlite::backup::Backup::new(&source, &mut destination)
            .with_context(|| "starting encrypted chain snapshot")?;
        backup
            .run_to_completion(256, std::time::Duration::from_millis(10), None)
            .with_context(|| "copying encrypted chain snapshot")?;
        Ok(())
    }

    /// Open or create the SQLCipher-encrypted witness chain. `key` is the stable
    /// storage key (see [`crate::storage::storage_key`]); it's applied as the
    /// SQLCipher key (hex), so the DB is encrypted at rest. A legacy plaintext
    /// `witness.db` is migrated in place on first open (chain preserved).
    pub fn open(path: impl AsRef<Path>, key: [u8; 32]) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating witness dir {}", parent.display()))?;
        }
        let key_hex = hex::encode(key);

        // One-time migration: re-encrypt a legacy plaintext DB.
        if path.exists() && is_plaintext_sqlite(&path) {
            migrate_plaintext_to_encrypted(&path, &key_hex).with_context(|| {
                format!("migrating plaintext witness chain at {}", path.display())
            })?;
        }

        let conn = Connection::open(&path)
            .with_context(|| format!("opening witness chain at {}", path.display()))?;
        // SQLCipher: key the connection before any other access.
        conn.pragma_update(None, "key", &key_hex)
            .with_context(|| "applying SQLCipher key to witness chain")?;
        // Dashboard and ledger projections must never stand between a
        // governance act and its witness append. One connection mutex cannot
        // provide that property: moving a read outside ServerState would still
        // make append() wait on the store's inner mutex. WAL gives the writer
        // and a stable reader snapshot independent file-level progress. The WAL
        // is encrypted by SQLCipher under the same database key.
        conn.pragma_update(None, "journal_mode", "WAL")
            .with_context(|| "enabling WAL mode for concurrent chain reads")?;
        // GROUP COMMIT (storage::durability). NORMAL keeps COMMIT synchronous and ordered —
        // errors still surface to the appending handler — but drops the fsync from it; the
        // flusher fsyncs the WAL once per group and a request replies only once covered.
        // Auto-checkpoint is OFF here because SQLite runs it INSIDE the commit that crosses
        // 1000 pages, i.e. under the daemon's state lock; the flusher checkpoints at idle.
        conn.pragma_update(None, "synchronous", "NORMAL")
            .with_context(|| "setting synchronous=NORMAL (group commit)")?;
        conn.pragma_update(None, "wal_autocheckpoint", 0)
            .with_context(|| "disabling inline WAL auto-checkpoint")?;
        conn.pragma_update(None, "journal_size_limit", 64 * 1024 * 1024)
            .with_context(|| "bounding the WAL file after checkpoints")?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS chain_entries (
                chain_position INTEGER PRIMARY KEY,
                hash           TEXT NOT NULL UNIQUE,
                prev_hash      TEXT NOT NULL,
                event_type     TEXT NOT NULL,
                event_data     TEXT NOT NULL,
                signer_lct     TEXT NOT NULL,
                timestamp      TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_chain_event_type ON chain_entries(event_type);
             CREATE INDEX IF NOT EXISTS idx_chain_timestamp  ON chain_entries(timestamp);

             -- Idempotency metadata is deliberately OUTSIDE the hashed witness row.
             -- The mapping commits in the same transaction as its row, but changing
             -- this retry index cannot alter what the witness chain says happened.
             CREATE TABLE IF NOT EXISTS chain_event_keys (
                event_key      TEXT PRIMARY KEY,
                chain_position INTEGER NOT NULL,
                entry_hash     TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_chain_event_key_position
                 ON chain_event_keys(chain_position);

             -- B2 (#339): ADDITIVE. Existing rows are never rewritten; a row written before
             -- signing simply has no row here and verifies as legacy_unsigned. The signature
             -- commits in the same transaction as its row (see append_inner).
             CREATE TABLE IF NOT EXISTS chain_signatures (
                chain_position     INTEGER PRIMARY KEY,
                row_hash           TEXT NOT NULL,
                signature_version  INTEGER NOT NULL,
                chain_id           TEXT NOT NULL,
                witness_lct        TEXT NOT NULL,
                witness_public_key TEXT NOT NULL,
                policy_generation  TEXT NOT NULL,
                signature          TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS chain_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
             );",
        )?;
        let genesis: Option<String> = conn
            .query_row(
                "SELECT hash FROM chain_entries ORDER BY chain_position ASC LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()?;
        let chain_id = genesis.as_deref().map(chain_id_for_genesis);
        if let Some(id) = &chain_id {
            conn.execute(
                "INSERT OR IGNORE INTO chain_meta (key, value) VALUES (?1, ?2)",
                params![META_CHAIN_ID, id],
            )?;
        }
        let read_conn = Connection::open(&path).with_context(|| {
            format!(
                "opening witness-chain read connection at {}",
                path.display()
            )
        })?;
        read_conn
            .pragma_update(None, "key", &key_hex)
            .with_context(|| "applying SQLCipher key to witness-chain read connection")?;
        read_conn
            .pragma_update(None, "query_only", true)
            .with_context(|| "making witness-chain read connection query-only")?;
        // Pay the O(n) count exactly once, at open, then track it incrementally.
        let n: i64 = conn.query_row("SELECT COUNT(*) FROM chain_entries", [], |row| row.get(0))?;
        let len = std::sync::Arc::new(AtomicU64::new(n as u64));
        let durability = super::durability::Durability::new(&path, &key_hex, len.clone());
        // What a previous run committed is made durable before anything is served from it.
        durability.wait_durable_blocking(n as u64)
            .with_context(|| "syncing the witness chain at open")?;
        Ok(Self {
            conn: Mutex::new(conn),
            read_conn: Mutex::new(read_conn),
            path,
            len,
            durability,
            derivations: crate::derivation_cache::DerivationCache::new(),
            read_high_water: AtomicU64::new(0),
            signer: RwLock::new(None),
            chain_id: Mutex::new(chain_id),
        })
    }

    /// Install the chain witness: every row appended through this handle from now on is signed
    /// in its own insert transaction. Replaces any previous signer (a rotation: rows already
    /// signed keep verifying under the key they carry). Records the signer's aliases in
    /// `chain_meta` so a reader can resolve legacy `signer_lct` strings on older rows.
    pub fn install_witness_signer(&self, signer: Arc<ChainWitnessSigner>) -> Result<()> {
        {
            let conn = self.conn.lock().unwrap();
            for alias in signer.signer_aliases() {
                conn.execute(
                    "INSERT OR REPLACE INTO chain_meta (key, value) VALUES (?1, ?2)",
                    params![format!("{META_SIGNER_ALIAS_PREFIX}{alias}"), signer.witness_lct()],
                )?;
            }
        }
        *self.signer.write().unwrap() = Some(signer);
        Ok(())
    }

    /// The installed chain witness, if any.
    pub fn witness_signer(&self) -> Option<Arc<ChainWitnessSigner>> {
        self.signer.read().unwrap().clone()
    }

    /// Bind the policy generation the installed witness signs subsequent rows under. A no-op
    /// without a signer.
    pub fn set_policy_generation(&self, generation: &str) {
        if let Some(s) = self.signer.read().unwrap().as_ref() {
            s.set_policy_generation(generation);
        }
    }

    /// The position from which this chain must be signed, if it has ever been signed: the
    /// earlier of the recorded boundary and the first surviving signature row (see
    /// [`signing_boundary`]). Daemon startup and the CLI opener refuse to run without the
    /// witness key when this is `Some`, so it must not trust the metadata row alone.
    pub fn signed_from(&self) -> Result<Option<u64>> {
        let conn = self.conn.lock().unwrap();
        signing_boundary(&conn)
    }

    /// The chain's stable id (`hestia-chain:<genesis hash>`), once it has a genesis row.
    pub fn chain_id(&self) -> Option<String> {
        self.chain_id.lock().unwrap().clone()
    }

    /// The chain-witness signature attached to the row at `chain_position`, if any.
    pub fn signature_for(&self, chain_position: u64) -> Result<Option<ChainSignatureRecord>> {
        let conn = self.observed(&self.read_conn)?;
        conn.query_row(
            "SELECT chain_position, row_hash, signature_version, chain_id, witness_lct,
                    witness_public_key, policy_generation, signature
               FROM chain_signatures WHERE chain_position = ?1",
            params![chain_position as i64],
            row_to_signature,
        )
        .optional()
        .map_err(Into::into)
    }

    /// DURABLE READS: a request that reads chain rows may reply with them, so it must not reply
    /// before every row its read could see is durable.
    ///
    /// The frontier is the read's OWN snapshot, not a length sampled beside it (Codex review
    /// 18933). Sampling `len` before taking the connection let a writer commit in between, and
    /// the SELECT then returned a row the scope never waited for; sampling just after taking
    /// it is not enough on `read_conn`, whose snapshot is fixed only by its first SELECT, and
    /// `len` itself trails COMMIT by an instruction. So every read runs in one read
    /// transaction whose FIRST statement fixes the snapshot and reads its frontier
    /// (`MAX(chain_position) + 1`, an O(log n) primary-key lookup); every later statement of
    /// the read sees exactly that snapshot, so nothing it returns lies beyond the frontier it
    /// registered. The transaction ends when the guard drops (after every statement borrowed
    /// from it). Registration is a no-op outside a request scope; the store-wide
    /// [`Self::read_high_water`] records it regardless, for readers with no scope.
    fn observed<'a>(&'a self, conn: &'a Mutex<Connection>) -> Result<ObservedConn<'a>> {
        let guard = conn.lock().unwrap();
        guard.execute_batch("BEGIN DEFERRED")?;
        let frontier = guard.query_row(
            "SELECT COALESCE(MAX(chain_position) + 1, 0) FROM chain_entries",
            [],
            |r| r.get::<_, i64>(0),
        );
        let frontier = match frontier {
            Ok(f) => f.max(0) as u64,
            Err(e) => {
                let _ = guard.execute_batch("ROLLBACK");
                return Err(e.into());
            }
        };
        self.read_high_water.fetch_max(frontier, Ordering::AcqRel);
        super::durability::note_observed(&self.durability, frontier);
        Ok(ObservedConn { guard })
    }

    /// The highest snapshot frontier any read of this store has observed: a reader outside a
    /// request scope (the dashboard worker, on the blocking pool) waits for this to be durable
    /// before publishing what it read.
    pub fn read_high_water(&self) -> u64 {
        self.read_high_water.load(Ordering::Acquire)
    }

    /// `read_from`, clamped to the DURABLE frontier: for projectors that act outward on what they
    /// read (the disposition lane) and must never act on a row an OS crash could still take back.
    pub fn read_from_durable(&self, from_position: u64, limit: u64) -> Result<Vec<ChainEntry>> {
        let durable = self.durability.frontier().durable;
        let mut rows = self.read_from(from_position, limit)?;
        rows.retain(|e| e.chain_position < durable);
        Ok(rows)
    }

    /// The group-commit durability frontier for this chain (see `storage::durability`).
    pub fn durability(&self) -> &std::sync::Arc<super::durability::Durability> {
        &self.durability
    }

    /// The event-triggered trust derivation cache over this chain.
    pub fn derivations(&self) -> &crate::derivation_cache::DerivationCache {
        &self.derivations
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Number of entries currently in the chain. O(1) — see [`SqliteChainStore::len`]'s
    /// field docs for why this being a `COUNT(*)` cost every member a fail-closed deny.
    ///
    /// Still returns `Result` so the 14 call sites are untouched by the change; the
    /// error arm is now unreachable, which is the point.
    pub fn len(&self) -> Result<u64> {
        Ok(self.len.load(Ordering::Acquire))
    }

    pub fn is_empty(&self) -> Result<bool> {
        Ok(self.len()? == 0)
    }

    /// Most recent entry's hash, or the genesis sentinel if empty.
    pub fn tail_hash(&self) -> Result<String> {
        let conn = self.observed(&self.read_conn)?;
        let h: Option<String> = conn
            .query_row(
                "SELECT hash FROM chain_entries ORDER BY chain_position DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        Ok(h.unwrap_or_else(|| GENESIS_PREV_HASH.to_string()))
    }

    /// Append a new entry.
    ///
    /// With a [`ChainWitnessSigner`] installed, the row is signed in the same transaction as
    /// its insert (#339), and a `signer_lct` equal to one of the signer's recorded aliases (the
    /// sovereign's legacy `phase1-placeholder` anchor) is stored as the witness's real,
    /// key-derived LCT — the alias itself is recorded in `chain_meta`. Without a signer the
    /// row is appended unsigned, which is refused once the chain has any signed row.
    pub fn append(
        &self,
        event_type: &str,
        event_data: serde_json::Value,
        signer_lct: &str,
    ) -> Result<ChainEntry> {
        self.append_inner(None, event_type, event_data, signer_lct)
            .map(|(entry, _inserted)| entry)
    }

    /// Resolve the exact witness already bound to an idempotency key.
    ///
    /// Used when a crash landed the witness but not the queue-side operation
    /// tombstone. The caller can validate immutable application binding against
    /// the first witness instead of rebuilding it with a new session id.
    pub fn event_by_key(&self, event_key: &str) -> Result<Option<ChainEntry>> {
        let conn = self.observed(&self.read_conn)?;
        conn.query_row(
            "SELECT e.chain_position, e.hash, e.prev_hash, e.event_type, e.event_data,
                    e.signer_lct, e.timestamp
               FROM chain_event_keys k
               JOIN chain_entries e
                 ON e.chain_position = k.chain_position AND e.hash = k.entry_hash
              WHERE k.event_key = ?1",
            params![event_key],
            row_to_entry,
        )
        .optional()?
        .transpose()
    }

    /// Append one witnessed fact exactly once for a durable caller-defined key.
    ///
    /// F3 receipt routing crosses the witness DB and inbox DB, so a crash can land
    /// between them. Retrying with the same key returns the existing chain row
    /// instead of appending a duplicate transport fact.
    pub fn append_once(
        &self,
        event_key: &str,
        event_type: &str,
        event_data: serde_json::Value,
        signer_lct: &str,
    ) -> Result<(ChainEntry, bool)> {
        anyhow::ensure!(!event_key.trim().is_empty(), "witness event_key must not be empty");
        self.append_inner(Some(event_key), event_type, event_data, signer_lct)
    }

    fn append_inner(
        &self,
        event_key: Option<&str>,
        event_type: &str,
        event_data: serde_json::Value,
        signer_lct: &str,
    ) -> Result<(ChainEntry, bool)> {
        // Durability lost: nothing more may be acknowledged as witnessed until a restart
        // rebuilds memory from what the chain actually holds.
        anyhow::ensure!(
            !self.durability.poisoned(),
            "witness chain refuses appends: an fsync failed and the daemon must restart"
        );
        let signer = self.signer.read().unwrap().clone();
        let signer_lct: String = match &signer {
            Some(s) => s.canonical_signer(signer_lct),
            None => signer_lct.to_string(),
        };
        let signer_lct = signer_lct.as_str();
        let same_signer = |recorded: &str| match &signer {
            Some(s) => s.canonical_signer(recorded) == signer_lct,
            None => recorded == signer_lct,
        };
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;

        if let Some(key) = event_key {
            let existing = tx
                .query_row(
                    "SELECT e.chain_position, e.hash, e.prev_hash, e.event_type, e.event_data,
                            e.signer_lct, e.timestamp
                       FROM chain_event_keys k
                       JOIN chain_entries e
                         ON e.chain_position = k.chain_position AND e.hash = k.entry_hash
                      WHERE k.event_key = ?1",
                    params![key],
                    row_to_entry,
                )
                .optional()?;
            if let Some(entry) = existing {
                let entry = entry?;
                anyhow::ensure!(
                    entry.event_type == event_type
                        && entry.event_data == event_data
                        && same_signer(&entry.signer_lct),
                    "witness event_key '{key}' was replayed with a different fact"
                );
                // A replay answers with a row that may be committed but not yet fsynced: the
                // retrying request must wait for it exactly as the first one does.
                super::durability::note_appended(&self.durability, entry.chain_position + 1);
                return Ok((entry, false));
            }
        }

        let (prev_hash, chain_position): (String, u64) = {
            let prev: Option<(String, i64)> = tx
                .query_row(
                    "SELECT hash, chain_position FROM chain_entries \
                     ORDER BY chain_position DESC LIMIT 1",
                    [],
                    |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)),
                )
                .optional()?;
            match prev {
                Some((h, pos)) => (h, (pos + 1) as u64),
                None => (GENESIS_PREV_HASH.to_string(), 0),
            }
        };

        // Downgrade refusal: a handle without the witness key must not extend a signed chain
        // with an unsigned row (verification would report it as tampering, correctly). The
        // boundary is read inside this transaction from both evidence sources, so neither a
        // deleted metadata row nor a concurrent writer can slip an unsigned row past it. It is
        // read for signed appends too: a malformed record refuses every append.
        let boundary = signing_boundary(&tx)?;
        if signer.is_none() {
            if let Some(from) = boundary {
                anyhow::bail!(
                    "witness chain refuses an unsigned append: rows from position {from} on are \
                     signed (#339), and this handle has no chain witness signer installed"
                );
            }
        }

        let timestamp = Utc::now();
        let event_json = serde_json::to_string(&event_data)?;
        let hash = compute_hash(&prev_hash, &timestamp, event_type, &event_json);
        let mut new_chain_id: Option<String> = None;

        tx.execute(
            "INSERT INTO chain_entries
                (chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                chain_position as i64,
                hash,
                prev_hash,
                event_type,
                event_json,
                signer_lct,
                timestamp.to_rfc3339(),
            ],
        )?;
        if let Some(key) = event_key {
            tx.execute(
                "INSERT INTO chain_event_keys (event_key, chain_position, entry_hash)
                 VALUES (?1, ?2, ?3)",
                params![key, chain_position as i64, hash],
            )?;
        }
        if let Some(signer) = &signer {
            // The chain id is the genesis hash: this row's own when it IS genesis. Read inside
            // the transaction when not cached, so another handle's genesis is seen.
            let cached = self.chain_id.lock().unwrap().clone();
            let chain_id = match cached {
                Some(id) => id,
                None if chain_position == 0 => chain_id_for_genesis(&hash),
                None => {
                    let g: String = tx.query_row(
                        "SELECT hash FROM chain_entries ORDER BY chain_position ASC LIMIT 1",
                        [],
                        |r| r.get(0),
                    )?;
                    chain_id_for_genesis(&g)
                }
            };
            let policy_generation = signer.policy_generation();
            let pre = signature_preimage(
                &chain_id,
                chain_position,
                &hash,
                signer_lct,
                signer.witness_lct(),
                signer.public_key_hex(),
                &policy_generation,
            );
            let signature = signer.keypair.sign(&pre).to_hex();
            tx.execute(
                "INSERT INTO chain_signatures
                    (chain_position, row_hash, signature_version, chain_id, witness_lct,
                     witness_public_key, policy_generation, signature)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    chain_position as i64,
                    hash,
                    CHAIN_SIGNATURE_VERSION_V1,
                    chain_id,
                    signer.witness_lct(),
                    signer.public_key_hex(),
                    policy_generation,
                    signature,
                ],
            )?;
            // The boundary is recorded only when this row STARTS signing. If signatures already
            // exist but the record is gone, writing this position would forge a later boundary
            // and erase the verifier's evidence of the deletion; leave it missing instead.
            if boundary.is_none() {
                tx.execute(
                    "INSERT OR IGNORE INTO chain_meta (key, value) VALUES (?1, ?2)",
                    params![META_SIGNED_FROM, chain_position.to_string()],
                )?;
            }
            tx.execute(
                "INSERT OR IGNORE INTO chain_meta (key, value) VALUES (?1, ?2)",
                params![META_CHAIN_ID, chain_id],
            )?;
            new_chain_id = Some(chain_id);
        }
        tx.commit()?;
        if let Some(id) = new_chain_id {
            let mut cached = self.chain_id.lock().unwrap();
            if cached.is_none() {
                *cached = Some(id);
            }
        } else if chain_position == 0 {
            let mut cached = self.chain_id.lock().unwrap();
            if cached.is_none() {
                *cached = Some(chain_id_for_genesis(&hash));
            }
        }
        self.len.fetch_add(1, Ordering::Release);
        self.durability.note_commit();
        super::durability::note_appended(&self.durability, chain_position + 1);

        let entry = ChainEntry {
            hash,
            prev_hash,
            timestamp,
            event_type: event_type.to_string(),
            event_data,
            signer_lct: signer_lct.to_string(),
            chain_position,
        };
        self.derivations.observe(&entry);
        Ok((entry, true))
    }
    /// Most recent `limit` entries in descending chain_position order.
    pub fn read_recent(&self, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             ORDER BY chain_position DESC
             LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], row_to_entry)?;
        let mut out = Vec::with_capacity(limit as usize);
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Up to `limit` entries AT-or-after `from_position`, ascending — the
    /// cursor-page read a projector makes (#480 revised review: a work queue is
    /// paged by position, never an absence-inference sweep over the tail).
    ///
    /// `from_position` is the NEXT UNREAD position, not the last processed one:
    /// `chain_position` starts at 0 (`append` genesises at 0), so "last
    /// processed + 1" is the only watermark that has a representation for an
    /// empty chain. The position is the table's INTEGER PRIMARY KEY, so the page
    /// is an index walk, not a scan, and no filter state lives anywhere but the
    /// caller's cursor. Ascending order matters — a projector that walks
    /// newest-first could skip rows forever if appends outpace the page.
    pub fn read_from(&self, from_position: u64, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE chain_position >= ?1
             ORDER BY chain_position ASC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![from_position as i64, limit as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Up to `limit` entries strictly BEFORE `before_position`, newest first —
    /// the backward page for a bounded lookup walking toward a floor (#480
    /// review, defect 3: the pointer resolvers' fallback used to materialize a
    /// 20,000-entry window under the shared-state read path; a lookup by
    /// event_data id has no index, so it pages instead). `before_position` is
    /// EXCLUSIVE; pass a value past the tail to start at the newest entry.
    pub fn read_before(&self, before_position: u64, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        // u64::MAX as i64 would wrap negative — clamp into range.
        let before = i64::try_from(before_position).unwrap_or(i64::MAX);
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE chain_position < ?1
             ORDER BY chain_position DESC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![before, limit as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Most recent entries at-or-after `cutoff_rfc3339` (a calendar window),
    /// descending chain_position, capped at `limit`. `None` = no calendar
    /// filter (plain `read_recent`).
    ///
    /// Why this exists: a count-limited window (`read_recent(50)`) silently
    /// evicts a quiet signer's entries whenever busier signers churn — a
    /// filtered view then reads as "emptied" while the chain is intact (the
    /// filtered-window illusion). A calendar window keeps every signer's
    /// entries for the period, so filters shrink only when time passes.
    /// Timestamps are RFC3339 UTC text written by one code path, so the
    /// lexicographic `>=` matches chronological order for this data.
    pub fn read_recent_window(
        &self,
        cutoff_rfc3339: Option<&str>,
        limit: u64,
    ) -> Result<Vec<ChainEntry>> {
        let Some(cutoff) = cutoff_rfc3339 else {
            return self.read_recent(limit);
        };
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE timestamp >= ?1
             ORDER BY chain_position DESC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![cutoff, limit as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Most-recent entries of specific event types, newest first.
    ///
    /// Exists so the governance ledger can find admin acts without pulling every member act into
    /// memory to throw away. Admin events are rare — a handful a day against thousands of
    /// outcomes — so a scan-then-filter would have to materialise ~100k entries to surface ~50,
    /// and that is the exact bulk-read-retention shape measured on 2026-08-04: RSS 60MB → 526MB
    /// inside one five-minute interval, then flat. Filtering in SQL makes `limit` mean "how many
    /// admin acts", so a wide time range costs what its ANSWER costs rather than what the chain
    /// weighs.
    ///
    /// An empty `event_types` returns no rows rather than everything: a caller that computed an
    /// empty type list is asking for nothing, and widening that to the whole chain would be the
    /// same silent-widening failure the ledger's status filter refuses.
    /// Stream a window and let the caller PROJECT each row, without ever building a
    /// `Vec<ChainEntry>` — which is to say, without holding N parsed `serde_json::Value`
    /// trees alive at once.
    ///
    /// # Why this exists
    ///
    /// `ChainEntry.event_data` is a fully parsed `serde_json::Value`. `row_to_entry`
    /// parses it for every row, so a caller that wants three scalars out of ten thousand
    /// entries pays for ten thousand JSON trees and keeps them all until it drops the Vec.
    ///
    /// Measured on this fleet, 2026-08-06: a single dashboard poll issued
    /// `read_recent(10_000)` for stats plus a windowed read for the feed, and the stats
    /// loop's entire use of `event_data` was `.get("plugin_id")`, `.get("decision")` and
    /// two siblings — top-level scalars. The daemon grew 164 MB → 1.35 GB in twenty-one
    /// minutes of ordinary use, `Anonymous: 1364 MB` of `Rss: 1382 MB`, flat at idle and
    /// stepping on every heavy read. Not a leak by reference: retention by allocator,
    /// driven by materialising trees nobody wanted.
    ///
    /// # What the caller gets
    ///
    /// `event_data` arrives as `&str`, borrowed from the sqlite row and valid only for
    /// the duration of the closure. Deserialise it into a **small struct naming just the
    /// fields you need** — serde skips unknown keys without allocating them, so peak
    /// memory becomes O(projection) per row instead of O(whole document). Returning
    /// `None` drops the row entirely, so a filter costs nothing downstream.
    ///
    /// Prefer this over `read_recent*` for anything windowed. The eager readers remain
    /// for callers that genuinely need whole entries (chain replay, derivation), where
    /// the parse is the point rather than an accident.
    pub fn scan_recent<T>(
        &self,
        cutoff_rfc3339: Option<&str>,
        event_types: Option<&[&str]>,
        limit: u64,
        mut project: impl FnMut(ChainRowRef<'_>) -> Option<T>,
    ) -> Result<Vec<T>> {
        // An empty type list asks for nothing. Same rule as `read_recent_by_types`:
        // widening it to the whole chain would answer a question nobody posed.
        if matches!(event_types, Some(t) if t.is_empty()) {
            return Ok(Vec::new());
        }
        let conn = self.observed(&self.read_conn)?;
        let mut where_parts: Vec<String> = Vec::new();
        if let Some(types) = event_types {
            where_parts.push(format!("event_type IN ({})", vec!["?"; types.len()].join(",")));
        }
        if cutoff_rfc3339.is_some() {
            where_parts.push("timestamp >= ?".to_string());
        }
        let where_sql = if where_parts.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", where_parts.join(" AND "))
        };
        let sql = format!(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries {where_sql}
             ORDER BY chain_position DESC LIMIT ?"
        );
        let mut stmt = conn.prepare(&sql)?;

        let mut binds: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
        if let Some(types) = event_types {
            for t in types {
                binds.push(Box::new(t.to_string()));
            }
        }
        if let Some(c) = cutoff_rfc3339 {
            binds.push(Box::new(c.to_string()));
        }
        binds.push(Box::new(limit as i64));
        let refs: Vec<&dyn rusqlite::ToSql> = binds.iter().map(std::convert::AsRef::as_ref).collect();

        let mut rows = stmt.query(refs.as_slice())?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let row_ref = ChainRowRef {
                chain_position: row.get::<_, i64>(0)? as u64,
                hash: row.get_ref(1)?.as_str()?,
                prev_hash: row.get_ref(2)?.as_str()?,
                event_type: row.get_ref(3)?.as_str()?,
                event_data: row.get_ref(4)?.as_str()?,
                signer_lct: row.get_ref(5)?.as_str()?,
                timestamp: row.get_ref(6)?.as_str()?,
            };
            if let Some(v) = project(row_ref) {
                out.push(v);
            }
        }
        Ok(out)
    }

    pub fn read_recent_by_types(
        &self,
        cutoff_rfc3339: Option<&str>,
        event_types: &[&str],
        limit: u64,
    ) -> Result<Vec<ChainEntry>> {
        if event_types.is_empty() {
            return Ok(Vec::new());
        }
        let conn = self.observed(&self.conn)?;
        let placeholders = vec!["?"; event_types.len()].join(",");
        let (sql, has_cutoff) = match cutoff_rfc3339 {
            Some(_) => (
                format!(
                    "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
                     FROM chain_entries
                     WHERE event_type IN ({placeholders}) AND timestamp >= ?
                     ORDER BY chain_position DESC LIMIT ?"
                ),
                true,
            ),
            None => (
                format!(
                    "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
                     FROM chain_entries
                     WHERE event_type IN ({placeholders})
                     ORDER BY chain_position DESC LIMIT ?"
                ),
                false,
            ),
        };
        let mut stmt = conn.prepare(&sql)?;
        let mut binds: Vec<Box<dyn rusqlite::ToSql>> = event_types
            .iter()
            .map(|t| Box::new(t.to_string()) as Box<dyn rusqlite::ToSql>)
            .collect();
        if has_cutoff {
            binds.push(Box::new(cutoff_rfc3339.unwrap().to_string()));
        }
        binds.push(Box::new(limit as i64));
        let refs: Vec<&dyn rusqlite::ToSql> = binds.iter().map(std::convert::AsRef::as_ref).collect();
        let rows = stmt.query_map(refs.as_slice(), row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Most recent D2 live-shadow parity rows, newest first.
    ///
    /// Uses the event-type index plus JSON presence rather than a global tail
    /// window: fleet chain churn must not make quiet routing evidence disappear
    /// from the report merely because unrelated acts were busy.
    pub fn read_recent_route_shadow(&self, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        // First choose exactly N parity samples. Then pull the legacy transport
        // disposition for successful samples by durable egress row id. Forward
        // events do not consume the sample limit.
        let mut stmt = conn.prepare(
            "WITH shadow AS (
                SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
                  FROM chain_entries
                 WHERE event_type IN ('member_notice_route_shadow', 'member_notice_refused')
                   AND json_type(event_data, '$.f3_shadow') IS NOT NULL
                 ORDER BY chain_position DESC
                 LIMIT ?1
             ),
             routed_rows AS (
                SELECT DISTINCT CAST(json_extract(event_data, '$.legacy_egress_row_id') AS INTEGER) AS row_id
                  FROM shadow
                 WHERE event_type = 'member_notice_route_shadow'
                   AND json_type(event_data, '$.legacy_egress_row_id') IS NOT NULL
             )
             SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
               FROM shadow
             UNION ALL
             SELECT c.chain_position, c.hash, c.prev_hash, c.event_type, c.event_data,
                    c.signer_lct, c.timestamp
               FROM chain_entries c
              WHERE c.event_type = 'egress_forwarded'
                AND CAST(json_extract(c.event_data, '$.row_id') AS INTEGER)
                    IN (SELECT row_id FROM routed_rows)
             ORDER BY chain_position DESC",
        )?;
        let rows = stmt.query_map(params![limit as i64], row_to_entry)?;
        let mut out = Vec::with_capacity((limit as usize).saturating_mul(2));
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Most-recent "didn't succeed" entries (descending). Includes both
    /// failed outcomes (`event_type='outcome'`, success=false) and
    /// policy denials (`event_type='policy_decision'`, decision='deny').
    /// From an operator's standpoint these are the same category — the
    /// tool call didn't go through, whether because it ran and failed
    /// or because the gate blocked it.
    /// Fetch one entry by its hash (the chain's stable public identifier —
    /// receipts, claim_refs, and supersedes links all address entries this way).
    pub fn read_by_hash(&self, hash: &str) -> Result<Option<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries WHERE hash = ?1 LIMIT 1",
        )?;
        let mut rows = stmt.query_map(params![hash], row_to_entry)?;
        match rows.next() {
            Some(r) => Ok(Some(r??)),
            None => Ok(None),
        }
    }

    /// Resolve a hash PREFIX to at most `cap` entries (ascending by position so
    /// the report is stable). Exists because the only place most members ever
    /// see an entry id is prose that abbreviates it — the operating law cites
    /// "adjudication 62cfdffe", eight characters, and a member who wants to read
    /// the ruling behind the rule it is bound by has exactly that. A lookup that
    /// only accepts the full 64 makes the law's own citation undereferenceable.
    ///
    /// Returns every match up to `cap` rather than the first: a prefix collision
    /// must be REPORTED as ambiguous, never silently resolved to whichever row
    /// SQLite reached first. Same discipline as the rest of this store — say what
    /// is known, do not pick for the caller.
    ///
    /// Errors on a non-hex prefix rather than returning empty: `LIKE ?1 || '%'`
    /// treats `%` and `_` in the bound value as wildcards, so a malformed
    /// pointer would otherwise become a scan that reports a real-looking
    /// "ambiguous" or a wrong single hit. Empty would also conflate
    /// *you typed garbage* with *no such entry*, which is the distinction the
    /// caller most needs.
    /// Every `appeal` and `adjudication` row about one deny, with no recency window (#164).
    ///
    /// `ptr` is a deny hash or an appeal entry hash, whole or as a prefix of at least 8 hex
    /// characters (the convention `resolve_appeal_pointer` already accepts). The query goes
    /// through `idx_chain_event_type`, so it touches only the appeal-typed rows and parses
    /// only those — not the 20,000-entry window `APPEAL_CHAIN_WINDOW` used to materialise.
    ///
    /// Why the window had to go for READS. Measured 2026-09-17: cbp-being's nine appeals
    /// were ruled at 04:38Z on 09-16, and by the next evening ~40,000 entries had been
    /// appended after them. `hestia://appeal/<hash>` then answered `appeal_pointer_not_found`
    /// for appeals that WERE ruled, so the appellant's only reader reported its rulings as
    /// nonexistent. A ruling does not stop being true because the fleet was busy (#610).
    /// The filing and ruling paths keep their window deliberately: acting on an aged-out
    /// deny is refused. Knowing what happened to one is not.
    pub fn appeal_rows_for_pointer(&self, ptr: &str) -> Result<Vec<ChainEntry>> {
        let ptr = validate_hash_pointer(ptr)?;
        // Hex only (validated), so `%` cannot occur in `ptr` and needs no escaping.
        let pattern = if ptr.len() >= 8 { format!("{ptr}%") } else { ptr };
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE event_type IN ('appeal', 'adjudication')
               AND (json_extract(event_data, '$.deny_hash') LIKE ?1
                    OR json_extract(event_data, '$.about_deny_hash') LIKE ?1
                    OR (event_type = 'appeal' AND hash LIKE ?1))
             ORDER BY chain_position ASC",
        )?;
        let rows = stmt.query_map(params![pattern], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Every witnessed entry about ONE gate escalation, oldest first, with no recency window
    /// (#1014): its `gate_escalation_opened`, any decided / withdrawn / expired settlement, and
    /// any `gate_escalation_claimed` spend.
    ///
    /// The escalation pointer used to page backward over the newest 1,000 chain entries, and
    /// escalation events are under 1% of the chain, so a real ask became unreadable a median of
    /// 7.3 hours after it opened (measured on CBP 2026-09-09) while the invitations and
    /// disposition notices that carry its pointer live for days. Index-restricted to the five
    /// event types, like `appeal_rows_for_pointer`; on the read connection, so a reader never
    /// waits on the writer.
    pub fn escalation_rows(&self, escalation_id: &str) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.read_conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE event_type IN ('gate_escalation_opened', 'gate_escalation_decided',
                                  'gate_escalation_withdrawn', 'gate_escalation_expired',
                                  'gate_escalation_claimed')
               AND json_extract(event_data, '$.escalation_id') = ?1
             ORDER BY chain_position ASC",
        )?;
        let rows = stmt.query_map(params![escalation_id], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// One member's appeals and the rulings on them, oldest first, with no recency window
    /// (#164): `appeal` rows whose `plugin_id` is the member and `adjudication` rows whose
    /// `subject_plugin_id` is. Index-restricted to the two event types, like
    /// `appeal_rows_for_pointer`. `cap` bounds the rows returned (newest kept) so a member with
    /// a long appeal history cannot drag it all into memory in one read.
    pub fn appeal_rows_for_member(&self, plugin_id: &str, cap: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT * FROM (
                SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
                FROM chain_entries
                WHERE (event_type = 'appeal' AND json_extract(event_data, '$.plugin_id') = ?1)
                   OR (event_type = 'adjudication' AND json_extract(event_data, '$.subject_plugin_id') = ?1)
                ORDER BY chain_position DESC
                LIMIT ?2
             ) ORDER BY chain_position ASC",
        )?;
        let rows = stmt.query_map(params![plugin_id, cap as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    pub fn read_by_hash_prefix(&self, prefix: &str, cap: u64) -> Result<Vec<ChainEntry>> {
        validate_hash_pointer(prefix)?;
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries WHERE hash LIKE ?1 || '%'
             ORDER BY chain_position ASC LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![prefix, cap as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// How many entries a prefix ACTUALLY matches, uncapped.
    ///
    /// `read_by_hash_prefix` is capped so an over-short prefix cannot drag the
    /// chain into memory — but the cap then lands in the ambiguity report, where
    /// `matches.len()` is a count of what we chose to fetch, not a count of what
    /// matched. A member told "matches 8 entries" over a true 40 lengthens the
    /// prefix by one character, gets told 8 again, and has no way to see it is
    /// converging; the number is doing the opposite of what an ambiguity report
    /// is for. Kimi's review of #60 (mesh notice 181) named this; it is the same
    /// class as the bug the resolver exists to fix — a saturated count and a real
    /// count render identically — one level in from the pointer itself.
    ///
    /// Separate query rather than fetching `cap + 1`: a boolean "there are more"
    /// still cannot tell 9 from 900, and COUNT over the `hash` index never
    /// materializes a row.
    pub fn count_by_hash_prefix(&self, prefix: &str) -> Result<u64> {
        validate_hash_pointer(prefix)?;
        let conn = self.observed(&self.conn)?;
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM chain_entries WHERE hash LIKE ?1 || '%'",
            params![prefix],
            |r| r.get(0),
        )?;
        Ok(n.max(0) as u64)
    }

    /// Every escalation row for one (member, marker), oldest first, with NO recency window.
    ///
    /// The prior-decisions half of `PRD_ADJUDICATOR_LADDER` §3.3 — "escalations on the same
    /// marker, with their outcomes", listed there as *"the thing a human cannot hold in their
    /// head"*. It is also the thing a WINDOW cannot hold: a marker's history is exactly what
    /// scrolls out of a tail first, and #610 is what that costs (a member told "no entry in
    /// the last 20000" concluded, in writing, that its own filings had never happened).
    ///
    /// Restricted to the escalation event types so the `idx_chain_event_type` index does the
    /// work and only those rows are parsed. `cap` keeps the NEWEST rows for a marker with a
    /// long history, then returns them oldest-first, because a decider reads a history
    /// forwards but cares most about its recent end.
    pub fn escalation_rows_for_marker(
        &self,
        plugin_id: &str,
        marker: &str,
        cap: u64,
    ) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT * FROM (
               SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
               FROM chain_entries
               WHERE event_type IN ('gate_escalation_opened', 'gate_escalation_decided',
                                    'gate_escalation_claimed', 'gate_escalation_withdrawn')
                 AND json_extract(event_data, '$.plugin_id') = ?1
                 AND json_extract(event_data, '$.marker') = ?2
               ORDER BY chain_position DESC
               LIMIT ?3
             ) ORDER BY chain_position ASC",
        )?;
        let rows = stmt.query_map(params![plugin_id, marker, cap as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// One member's refusals, newest first — §3.3's "the member's history … including prior
    /// denies and their rules".
    ///
    /// `policy_decision` rows only. A deny is the record of a refusal that ALREADY happened,
    /// so this is history, never a prediction: the bundle presents it as what the member has
    /// been refused for, and leaves the inference to whoever is deciding.
    pub fn denies_for_member(&self, plugin_id: &str, cap: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE event_type = 'policy_decision'
               AND json_extract(event_data, '$.decision') = 'deny'
               AND json_extract(event_data, '$.plugin_id') = ?1
             ORDER BY chain_position DESC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![plugin_id, cap as i64], row_to_entry)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    pub fn read_failures(&self, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE (event_type = 'outcome' AND json_extract(event_data, '$.success') = 0)
                OR (event_type = 'policy_decision' AND json_extract(event_data, '$.decision') = 'deny')
             ORDER BY chain_position DESC
             LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], row_to_entry)?;
        let mut out = Vec::with_capacity(limit as usize);
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Entries since (exclusive of) `chain_position`, ascending.
    pub fn read_since(&self, chain_position: u64, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries
             WHERE chain_position > ?1
             ORDER BY chain_position ASC
             LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![chain_position as i64, limit as i64], row_to_entry)?;
        let mut out = Vec::with_capacity(limit as usize);
        for r in rows {
            out.push(r??);
        }
        Ok(out)
    }

    /// Verify hash linkage walks correctly from genesis to tail.
    /// Returns the chain length on success, or an error describing the break.
    pub fn verify_integrity(&self) -> Result<u64> {
        let conn = self.observed(&self.conn)?;
        let mut stmt = conn.prepare(
            "SELECT chain_position, hash, prev_hash, event_type, event_data, signer_lct, timestamp
             FROM chain_entries ORDER BY chain_position ASC",
        )?;
        let rows = stmt.query_map([], row_to_entry)?;
        let mut prev = GENESIS_PREV_HASH.to_string();
        let mut count: u64 = 0;
        for r in rows {
            let entry = r??;
            anyhow::ensure!(
                entry.prev_hash == prev,
                "chain integrity broken at position {}: prev_hash mismatch",
                entry.chain_position
            );
            let recomputed = compute_hash(
                &entry.prev_hash,
                &entry.timestamp,
                &entry.event_type,
                &serde_json::to_string(&entry.event_data)?,
            );
            anyhow::ensure!(
                recomputed == entry.hash,
                "chain integrity broken at position {}: hash mismatch",
                entry.chain_position
            );
            prev = entry.hash;
            count += 1;
        }
        Ok(count)
    }

    /// Both predicates — link integrity and signature authenticity (#339) — over one read
    /// snapshot, streamed (no `event_data` is parsed). Unlike [`Self::verify_integrity`] it does
    /// not stop at the first problem: a link break is recorded and the signature walk
    /// continues, so a report says everything wrong with the chain, not only the first thing.
    ///
    /// Downgrade rule: once a row carrying a signature has been seen — or from the position
    /// `chain_meta` records signing began, whichever is earlier — every later row must carry a
    /// valid signature. Stripping signatures from the TAIL together with the meta record is
    /// not detectable from inside the chain; that needs an external checkpoint of a signed
    /// head (#328).
    pub fn verify_chain(&self) -> Result<ChainVerification> {
        let conn = self.observed(&self.read_conn)?;
        let recorded_chain_id = meta_string(&conn, META_CHAIN_ID)?;
        let recorded_signed_from = meta_u64(&conn, META_SIGNED_FROM)?;
        let orphan_signatures: i64 = conn.query_row(
            "SELECT COUNT(*) FROM chain_signatures s
              WHERE NOT EXISTS (SELECT 1 FROM chain_entries e
                                 WHERE e.chain_position = s.chain_position)",
            [],
            |r| r.get(0),
        )?;
        let mut stmt = conn.prepare(
            "SELECT e.chain_position, e.hash, e.prev_hash, e.event_type, e.event_data,
                    e.signer_lct, e.timestamp,
                    s.chain_position, s.row_hash, s.signature_version, s.chain_id, s.witness_lct,
                    s.witness_public_key, s.policy_generation, s.signature
               FROM chain_entries e
               LEFT JOIN chain_signatures s ON s.chain_position = e.chain_position
              ORDER BY e.chain_position ASC",
        )?;
        let mut rows = stmt.query([])?;
        let mut v = ChainVerification {
            length: 0,
            chain_id: None,
            recorded_chain_id,
            link_break: None,
            legacy_unsigned: 0,
            signed_valid: 0,
            signature_failures: 0,
            failures: Vec::new(),
            first_signed_position: None,
            recorded_signed_from,
            orphan_signatures: orphan_signatures.max(0) as u64,
            meta_mismatch: None,
            witnesses: BTreeMap::new(),
        };
        let fail = |v: &mut ChainVerification, pos: u64, state: SignatureState, reason: String| {
            v.signature_failures += 1;
            if v.failures.len() < MAX_LISTED_FAILURES {
                v.failures.push(SignatureFailure { chain_position: pos, state, reason });
            }
        };
        let mut prev = GENESIS_PREV_HASH.to_string();
        let mut seen_signed = false;
        while let Some(row) = rows.next()? {
            let pos = row.get::<_, i64>(0)? as u64;
            let hash: String = row.get(1)?;
            let prev_hash: String = row.get(2)?;
            let event_type: String = row.get(3)?;
            let event_data: String = row.get(4)?;
            let signer_lct: String = row.get(5)?;
            let timestamp: String = row.get(6)?;
            if v.chain_id.is_none() {
                v.chain_id = Some(chain_id_for_genesis(&hash));
            }
            v.length += 1;

            // Predicate 1: link integrity (the legacy formula, unchanged).
            if v.link_break.is_none() {
                if prev_hash != prev {
                    v.link_break = Some(format!("position {pos}: prev_hash mismatch"));
                } else {
                    match DateTime::parse_from_rfc3339(&timestamp) {
                        Ok(ts) => {
                            let recomputed = compute_hash(
                                &prev_hash,
                                &ts.with_timezone(&Utc),
                                &event_type,
                                &event_data,
                            );
                            if recomputed != hash {
                                v.link_break = Some(format!("position {pos}: hash mismatch"));
                            }
                        }
                        Err(e) => {
                            v.link_break = Some(format!("position {pos}: bad timestamp: {e}"));
                        }
                    }
                }
            }
            prev = hash.clone();

            // Predicate 2: signature authenticity.
            let sig_pos: Option<i64> = row.get(7)?;
            if sig_pos.is_some() {
                let rec = ChainSignatureRecord {
                    chain_position: pos,
                    row_hash: row.get(8)?,
                    signature_version: row.get::<_, i64>(9)?.try_into().unwrap_or(u32::MAX),
                    chain_id: row.get(10)?,
                    witness_lct: row.get(11)?,
                    witness_public_key: row.get(12)?,
                    policy_generation: row.get(13)?,
                    signature: row.get(14)?,
                };
                seen_signed = true;
                v.first_signed_position.get_or_insert(pos);
                let chain_id = v.chain_id.clone().unwrap_or_default();
                match verify_row_signature(&chain_id, pos, &hash, &signer_lct, &rec) {
                    Ok(()) => {
                        v.signed_valid += 1;
                        let w = v
                            .witnesses
                            .entry(rec.witness_public_key.clone())
                            .or_insert_with(|| WitnessKeyUse {
                                witness_lct: rec.witness_lct.clone(),
                                rows: 0,
                                first_position: pos,
                                last_position: pos,
                            });
                        w.rows += 1;
                        w.last_position = pos;
                    }
                    Err(reason) => fail(&mut v, pos, SignatureState::Invalid, reason),
                }
            } else if seen_signed || recorded_signed_from.is_some_and(|from| pos >= from) {
                fail(
                    &mut v,
                    pos,
                    SignatureState::MissingAfterSigned,
                    "unsigned row at or after the point this chain became signed (downgrade)"
                        .into(),
                );
            } else {
                v.legacy_unsigned += 1;
            }
        }
        if let (Some(derived), Some(recorded)) = (&v.chain_id, &v.recorded_chain_id) {
            if derived != recorded {
                v.meta_mismatch = Some(format!(
                    "chain_meta records chain id {recorded}, genesis derives {derived}"
                ));
            }
        }
        if v.meta_mismatch.is_none() {
            match (v.first_signed_position, v.recorded_signed_from) {
                (Some(first), Some(recorded)) if first != recorded => {
                    v.meta_mismatch = Some(format!(
                        "chain_meta records signing from position {recorded}, first signature is at {first}"
                    ));
                }
                // The record is written in the same transaction as the first signature, so
                // signatures without it mean the record was removed.
                (Some(first), None) => {
                    v.meta_mismatch = Some(format!(
                        "chain_meta has no signed_from_position, but signatures begin at {first}"
                    ));
                }
                _ => {}
            }
        }
        Ok(v)
    }
}

fn meta_string(conn: &Connection, key: &str) -> Result<Option<String>> {
    conn.query_row("SELECT value FROM chain_meta WHERE key = ?1", params![key], |r| r.get(0))
        .optional()
        .map_err(Into::into)
}

fn meta_u64(conn: &Connection, key: &str) -> Result<Option<u64>> {
    match meta_string(conn, key)? {
        None => Ok(None),
        Some(v) => v
            .parse::<u64>()
            .map(Some)
            .with_context(|| format!("chain_meta {key} is not a u64: {v:?}")),
    }
}

/// The position from which this chain must be signed, derived from BOTH persisted sources of
/// evidence: the `signed_from_position` record and the signature rows themselves (Codex review
/// of #1322). Either one alone is enough to make signing mandatory, so losing the metadata row
/// while signatures survive (or the reverse) cannot reopen unsigned appends. The earlier of the
/// two wins, because that is the conservative answer when they disagree. A malformed record is
/// an error, never "unsigned".
fn signing_boundary(conn: &Connection) -> Result<Option<u64>> {
    let recorded = meta_u64(conn, META_SIGNED_FROM)?;
    let first_signature: Option<i64> =
        conn.query_row("SELECT MIN(chain_position) FROM chain_signatures", [], |r| r.get(0))?;
    let first_signature = first_signature
        .map(|p| u64::try_from(p).context("chain_signatures holds a negative position"))
        .transpose()?;
    Ok(match (recorded, first_signature) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    })
}

fn row_to_signature(row: &rusqlite::Row) -> rusqlite::Result<ChainSignatureRecord> {
    Ok(ChainSignatureRecord {
        chain_position: row.get::<_, i64>(0)? as u64,
        row_hash: row.get(1)?,
        signature_version: row.get::<_, i64>(2)?.try_into().unwrap_or(u32::MAX),
        chain_id: row.get(3)?,
        witness_lct: row.get(4)?,
        witness_public_key: row.get(5)?,
        policy_generation: row.get(6)?,
        signature: row.get(7)?,
    })
}

fn row_to_entry(row: &rusqlite::Row) -> rusqlite::Result<Result<ChainEntry>> {
    let chain_position: i64 = row.get(0)?;
    let hash: String = row.get(1)?;
    let prev_hash: String = row.get(2)?;
    let event_type: String = row.get(3)?;
    let event_data: String = row.get(4)?;
    let signer_lct: String = row.get(5)?;
    let timestamp: String = row.get(6)?;
    Ok((|| -> Result<ChainEntry> {
        let ts = DateTime::parse_from_rfc3339(&timestamp)?.with_timezone(&Utc);
        let data: serde_json::Value = serde_json::from_str(&event_data)?;
        Ok(ChainEntry {
            hash,
            prev_hash,
            timestamp: ts,
            event_type,
            event_data: data,
            signer_lct,
            chain_position: chain_position as u64,
        })
    })())
}

/// The single gate every hash-pointer lookup passes, full-length or abbreviated.
///
/// It exists because the two paths disagreed. `read_by_hash_prefix` checked hex;
/// `read_by_hash` is an equality match and checked nothing, so a 64-character
/// pointer that was not a hash at all — `"z" * 64`, a base64 blob, a truncated
/// UUID — matched no row and came back **not found**. That reads as *this entry
/// is not on the chain*, and a member holding a garbled pointer would go looking
/// for a ruling that was in fact sitting right there under the real hash. It is
/// the resolver's own defect class turned inward: a malformed input and a real
/// absence rendering identically. Kimi's review of #60 (mesh notice 181) found
/// it by feeding the resolver a 64-char non-hex string.
///
/// Case is normalized here for the same reason and not one level up: SQLite's
/// `LIKE` is ASCII-case-insensitive by default while `=` is not, so before this
/// an UPPERCASE 8-char prefix resolved and the UPPERCASE full hash of the very
/// same entry reported not-found. Hashes are written lowercase (`compute_hash`),
/// so lowercasing an all-hex pointer is lossless.
pub(crate) fn validate_hash_pointer(pointer: &str) -> Result<String> {
    if pointer.is_empty() || !pointer.bytes().all(|b| b.is_ascii_hexdigit()) {
        anyhow::bail!("chain hash pointer must be non-empty ASCII hex: {pointer:?}");
    }
    if pointer.len() > 64 {
        anyhow::bail!(
            "chain hash pointer is {} chars; a chain hash is 64 (sha256): {pointer:?}",
            pointer.len()
        );
    }
    Ok(pointer.to_ascii_lowercase())
}

fn compute_hash(
    prev_hash: &str,
    timestamp: &DateTime<Utc>,
    event_type: &str,
    event_data_json: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(prev_hash.as_bytes());
    hasher.update(timestamp.to_rfc3339().as_bytes());
    hasher.update(event_type.as_bytes());
    hasher.update(event_data_json.as_bytes());
    let digest = hasher.finalize();
    digest.iter().map(|b| format!("{:02x}", b)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    const TEST_KEY: [u8; 32] = [7u8; 32];

    /// Codex review 18933, P1 (read frontier): a read must wait for every row it RETURNS, not
    /// for a length sampled before its SQL ran. The probe is Codex's, inverted into the
    /// contract: the reader is parked on its connection, a row is appended and left in the
    /// commit-to-fsync window, then the connection is released. Whatever the reader returns
    /// while the window is held must already be durable; once released, it returns the row.
    ///
    /// The bounded wait for the scope's Arc is what made the old shape fail deterministically
    /// (it registered its frontier BEFORE blocking on the connection); the fixed shape registers
    /// after its snapshot is taken, so the wait simply times out.
    #[test]
    fn a_read_waits_for_every_row_it_returns() {
        use std::sync::Arc;
        use std::time::{Duration, Instant};
        let dir = TempDir::new().unwrap();
        let store = Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let hold = store.durability().hold_flush_for_test();
        let read_guard = store.read_conn.lock().unwrap();
        let baseline = Arc::strong_count(store.durability());
        let reader_store = store.clone();
        let (tx, rx) = std::sync::mpsc::channel();
        let reader = std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread().build().unwrap();
            let (hash, status) = rt.block_on(crate::storage::durability::durable_scope(async {
                reader_store.tail_hash().unwrap()
            }));
            let durable_at_return = reader_store.durability().frontier().durable;
            tx.send((hash, status, durable_at_return)).unwrap();
        });
        let deadline = Instant::now() + Duration::from_millis(300);
        while Arc::strong_count(store.durability()) == baseline && Instant::now() < deadline {
            std::thread::yield_now();
        }
        let row = store.append("review_fact", json!({"n": 1}), "lct:test").unwrap();
        drop(read_guard);
        let early = rx.recv_timeout(Duration::from_millis(1500));
        drop(hold);
        let (hash, status, durable_at_return) = match early {
            Ok(r) => r,
            Err(_) => rx.recv_timeout(Duration::from_secs(10)).expect("reader returns once durable"),
        };
        reader.join().unwrap();
        status.unwrap();
        assert!(
            hash != row.hash || durable_at_return > row.chain_position,
            "a read returned position {} while the durable length was {durable_at_return}",
            row.chain_position
        );
        assert_eq!(hash, row.hash, "the reader's snapshot was taken after the append");
    }

    /// The same contract for an aggregate (a count is a chain fact too) and for a read on the
    /// WRITE connection: every read reports the snapshot frontier it actually read, and the
    /// store's read high-water covers it (the dashboard worker waits on that).
    #[test]
    fn every_read_registers_the_frontier_of_its_own_snapshot() {
        use std::sync::Arc;
        let dir = TempDir::new().unwrap();
        let store = Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let _hold = store.durability().hold_flush_for_test();
        let row = store.append("review_fact", json!({"n": 1}), "lct:test").unwrap();
        assert_eq!(store.read_high_water(), 0, "nothing has been read yet");
        let prefix = &row.hash[..8];
        assert_eq!(store.count_by_hash_prefix(prefix).unwrap(), 1);
        assert_eq!(store.read_high_water(), row.chain_position + 1, "count_by_hash_prefix");
        let row2 = store.append("review_fact", json!({"n": 2}), "lct:test").unwrap();
        assert_eq!(store.read_recent(10).unwrap().len(), 2);
        assert_eq!(store.read_high_water(), row2.chain_position + 1, "read_recent (write connection)");
    }

    /// A read's frontier is its snapshot, so it can be past this store's own `committed` count
    /// (a row another handle appended to the same file). The wait must still end: the fsync
    /// that follows the request covers every row the reader saw.
    #[test]
    fn a_read_past_this_handles_committed_count_still_completes() {
        use std::sync::Arc;
        use std::time::Duration;
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let reader = Arc::new(SqliteChainStore::open(&path, TEST_KEY).unwrap());
        let other = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let row = other.append("review_fact", json!({"n": 1}), "lct:other").unwrap();
        assert_eq!(reader.durability().committed(), 0, "setup: the reader's handle did not append");
        let (tx, rx) = std::sync::mpsc::channel();
        let r = reader.clone();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread().build().unwrap();
            let out = rt.block_on(crate::storage::durability::durable_scope(async { r.tail_hash().unwrap() }));
            let _ = tx.send(out);
        });
        let (hash, status) = rx.recv_timeout(Duration::from_secs(10))
            .expect("a read whose snapshot ran past `committed` never completed");
        status.unwrap();
        assert_eq!(hash, row.hash);
        assert!(reader.durability().frontier().durable >= 1);
    }

    // ------------------------------------------------------------- group commit (durability)

    /// The commit path is fsync-free and checkpoint-free: both moved to the flusher.
    #[test]
    fn the_write_connection_commits_without_fsync_or_inline_checkpoint() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap();
        let conn = store.conn.lock().unwrap();
        let sync: i64 = conn.query_row("PRAGMA synchronous", [], |r| r.get(0)).unwrap();
        let auto: i64 = conn.query_row("PRAGMA wal_autocheckpoint", [], |r| r.get(0)).unwrap();
        assert_eq!(sync, 1, "NORMAL: COMMIT does not fsync; the flusher does");
        assert_eq!(auto, 0, "no auto-checkpoint inside a commit (it ran under the state lock)");
    }

    /// A request scope returns only once its own entry is durable, and an append made outside
    /// any scope is not waited for (background tasks reply to no one).
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn a_scope_returns_only_after_its_entry_is_durable() {
        let dir = TempDir::new().unwrap();
        let store = std::sync::Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let s2 = store.clone();
        let (entry, res) = crate::storage::durability::durable_scope(async move {
            s2.append("t", json!({"n": 1}), "lct:x").unwrap()
        })
        .await;
        res.unwrap();
        assert!(store.durability().frontier().durable >= entry.chain_position + 1);
    }

    /// GROUP commit: many concurrent requests, far fewer fsyncs, and every one of them
    /// acknowledged only once covered.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn one_fsync_covers_many_concurrent_appends() {
        let dir = TempDir::new().unwrap();
        let store = std::sync::Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let before = store.durability().fsyncs.load(Ordering::Relaxed);
        let mut set = tokio::task::JoinSet::new();
        for i in 0..64u64 {
            let st = store.clone();
            set.spawn(async move {
                let (e, res) = crate::storage::durability::durable_scope(async {
                    st.append("t", json!({"i": i}), "lct:x").unwrap()
                })
                .await;
                res.unwrap();
                assert!(st.durability().frontier().durable > e.chain_position);
            });
        }
        while let Some(r) = set.join_next().await {
            r.unwrap();
        }
        let fsyncs = store.durability().fsyncs.load(Ordering::Relaxed) - before;
        assert!(fsyncs < 64, "64 appends took {fsyncs} fsyncs: not grouped");
        assert_eq!(store.durability().frontier().durable, store.len().unwrap());
        assert_eq!(store.verify_integrity().unwrap(), 64);
    }

    /// An fsync FAILURE: the unacknowledged request gets an error (never "recorded"), every
    /// later append is refused, and a reopen — the restart — serves exactly a chain that holds
    /// everything acknowledged before the failure and verifies end to end. (The unacknowledged
    /// entry's fate is UNKNOWN by definition — after EIO it may or may not have reached disk —
    /// so it is neither required nor forbidden.)
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn an_fsync_failure_poisons_refuses_and_reopens_to_the_acknowledged_chain() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let store = std::sync::Arc::new(SqliteChainStore::open(&path, TEST_KEY).unwrap());
        let mut acked = Vec::new();
        for i in 0..3 {
            let st = store.clone();
            let (e, res) = crate::storage::durability::durable_scope(async move {
                st.append("acked", json!({"i": i}), "lct:x").unwrap()
            })
            .await;
            res.expect("acknowledged");
            acked.push(e.hash);
        }
        store.durability().inject_sync_failure();
        let st = store.clone();
        let (_e, res) = crate::storage::durability::durable_scope(async move {
            st.append("unacked", json!({}), "lct:x").unwrap()
        })
        .await;
        assert!(res.is_err(), "an entry whose fsync failed must not be acknowledged");
        assert!(store.durability().poisoned());
        let refused = store.append("after", json!({}), "lct:x");
        assert!(refused.is_err(), "a poisoned chain accepts nothing more");
        drop(store);

        let reopened = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        for h in &acked {
            assert!(reopened.read_by_hash(h).unwrap().is_some(), "acknowledged entry {h} lost");
        }
        assert!(reopened.read_recent(10).unwrap().iter().all(|e| e.event_type != "after"),
                "a refused append must not exist");
        assert_eq!(reopened.verify_integrity().unwrap(), reopened.len().unwrap());
        assert!(!reopened.durability().poisoned(), "the restart starts clean");
        reopened.append("post-restart", json!({}), "lct:x").expect("a restarted chain appends");
    }

    /// A retried `append_once` answers with the row the first attempt committed. While that row
    /// is still in the commit-to-fsync window, the retry must not be acknowledged either.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn a_replayed_key_is_acknowledged_only_once_its_row_is_durable() {
        use crate::storage::durability::durable_scope;
        let dir = TempDir::new().unwrap();
        let store = std::sync::Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let hold = store.durability().hold_flush_for_test();
        let st = store.clone();
        let first = tokio::spawn(async move {
            durable_scope(async { st.append_once("k1", "t", json!({"a": 1}), "lct:x").unwrap() }).await.1
        });
        for _ in 0..200 {
            if store.len().unwrap() == 1 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }
        assert_eq!(store.len().unwrap(), 1, "the first attempt committed");
        let st = store.clone();
        let replay = tokio::spawn(async move {
            let ((_, inserted), res) = durable_scope(async {
                st.append_once("k1", "t", json!({"a": 1}), "lct:x").unwrap()
            })
            .await;
            assert!(!inserted, "a replay, not a second row");
            res
        });
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
        assert!(!replay.is_finished(),
                "a replay was acknowledged while the row it returned was not yet durable");
        assert!(!first.is_finished());
        drop(hold);
        replay.await.unwrap().unwrap();
        first.await.unwrap().unwrap();
        assert!(store.durability().frontier().durable >= 1);
    }

    /// The checkpoint runs on the flusher, at idle — never inside an append.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn the_wal_is_checkpointed_at_idle_off_the_commit_path() {
        let dir = TempDir::new().unwrap();
        let store = std::sync::Arc::new(SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap());
        let blob = "x".repeat(8 * 1024);
        let st = store.clone();
        let (_, res) = crate::storage::durability::durable_scope(async move {
            for i in 0..300 {
                st.append("bulk", json!({"i": i, "pad": blob}), "lct:x").unwrap();
            }
        })
        .await;
        res.unwrap();
        let ck = || store.durability().checkpoints.load(Ordering::Relaxed);
        for _ in 0..60 {
            if ck() > 0 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        assert!(ck() > 0, "no idle checkpoint ran within 6 s of a >1 MiB WAL going quiet");
    }

    #[test]
    fn empty_store_reports_zero_and_genesis_tail() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap();
        assert_eq!(store.len().unwrap(), 0);
        assert!(store.is_empty().unwrap());
        assert_eq!(store.tail_hash().unwrap(), GENESIS_PREV_HASH);
    }

    /// `len()` is a CACHE now, so it can lie in a way a `COUNT(*)` could not. This pins it
    /// against the ground truth it replaced, at every step and across a reopen.
    ///
    /// The negative control is the last block: it deletes a row behind the cache's back and
    /// asserts the two DISAGREE. That is deliberate — it proves this test can fail. Without
    /// it, the assertions above pass just as happily against an implementation that computed
    /// both sides the same way, and the guard would certify nothing. If a deletion path is
    /// ever added to the chain, that control is the thing that goes red first.
    #[test]
    fn chain_len_cache_matches_count() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let signer = "lct:web4:hestia:sovereign:test";

        let true_count = |store: &SqliteChainStore| -> u64 {
            let conn = store.conn.lock().unwrap();
            let n: i64 = conn
                .query_row("SELECT COUNT(*) FROM chain_entries", [], |r| r.get(0))
                .unwrap();
            n as u64
        };

        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.len().unwrap(), true_count(&store), "empty store");

        for i in 0..25u64 {
            store
                .append("policy_decision", json!({ "n": i }), signer)
                .unwrap();
            assert_eq!(
                store.len().unwrap(),
                true_count(&store),
                "cache drifted after append {i}"
            );
            assert_eq!(store.len().unwrap(), i + 1);
        }
        drop(store);

        // Reopen: the cache must be re-seeded from disk, not restarted at zero.
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.len().unwrap(), 25, "cache lost across reopen");
        assert_eq!(store.len().unwrap(), true_count(&store));

        // NEGATIVE CONTROL — make the cache wrong on purpose and prove we would see it.
        {
            let conn = store.conn.lock().unwrap();
            conn.execute("DELETE FROM chain_entries WHERE chain_position = 0", [])
                .unwrap();
        }
        assert_eq!(store.len().unwrap(), 25, "cache should be stale by construction");
        assert_ne!(
            store.len().unwrap(),
            true_count(&store),
            "control failed: a row vanished and the cache still agreed — this test cannot fail, \
             so it certifies nothing"
        );
    }

    #[test]
    fn legacy_plaintext_db_migrates_to_encrypted_preserving_rows() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("witness.db");
        let signer = "lct:web4:hestia:sovereign:test";

        // Build a legacy PLAINTEXT witness DB (no key) with two entries —
        // exactly what an older install / the live daemon has on disk.
        {
            let conn = Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE chain_entries (
                    chain_position INTEGER PRIMARY KEY, hash TEXT NOT NULL UNIQUE,
                    prev_hash TEXT NOT NULL, event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL, signer_lct TEXT NOT NULL, timestamp TEXT NOT NULL);",
            )
            .unwrap();
            for i in 0..2u64 {
                conn.execute(
                    "INSERT INTO chain_entries VALUES (?1,?2,?3,?4,?5,?6,?7)",
                    params![
                        i as i64,
                        format!("h{i}"),
                        format!("p{i}"),
                        "evt",
                        format!("{{\"n\":{i}}}"),
                        signer,
                        "2026-06-16T00:00:00Z"
                    ],
                )
                .unwrap();
            }
        }
        assert!(is_plaintext_sqlite(&path), "precondition: plaintext DB");

        // Opening with a key migrates it in place, preserving the rows.
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.len().unwrap(), 2);
        assert!(!is_plaintext_sqlite(&path), "DB should now be encrypted");
        drop(store);

        // Reopen with the right key works; the wrong key fails.
        assert_eq!(
            SqliteChainStore::open(&path, TEST_KEY)
                .unwrap()
                .len()
                .unwrap(),
            2
        );
        assert!(
            SqliteChainStore::open(&path, [9u8; 32]).is_err(),
            "wrong key must fail"
        );
    }

    #[test]
    fn scan_recent_projects_without_materialising_and_matches_the_eager_read() {
        // The optimisation is only safe if it is INVISIBLE. Same rows, same order, same
        // field values as the eager path — the difference must be memory, never meaning.
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(&dir.path().join("w.db"), TEST_KEY).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";
        for i in 0..5 {
            store
                .append(
                    if i % 2 == 0 { "outcome" } else { "policy_decision" },
                    json!({"plugin_id": format!("m{i}"), "success": i % 2 == 0,
                           "big": "x".repeat(4096), "nested": {"a": {"b": [1,2,3]}}}),
                    signer,
                )
                .unwrap();
        }

        #[derive(serde::Deserialize)]
        struct Proj { plugin_id: Option<String>, success: Option<bool> }

        let eager = store.read_recent(10).unwrap();
        let projected = store
            .scan_recent(None, None, 10, |r| {
                let f: Proj = r.project().unwrap_or(Proj { plugin_id: None, success: None });
                Some((r.chain_position, r.event_type.to_string(), f.plugin_id, f.success))
            })
            .unwrap();

        assert_eq!(eager.len(), projected.len(), "same row count");
        for (e, p) in eager.iter().zip(projected.iter()) {
            assert_eq!(e.chain_position, p.0, "same order");
            assert_eq!(e.event_type, p.1);
            assert_eq!(e.event_data.get("plugin_id").and_then(|v| v.as_str()).map(String::from), p.2);
            assert_eq!(e.event_data.get("success").and_then(|v| v.as_bool()), p.3);
        }

        // Unparseable event_data must drop to the projection default rather than killing
        // the scan: one bad row must not cost the other 9,999.
        let n = store
            .scan_recent(None, Some(&["outcome"]), 10, |r| {
                r.project::<Proj>().map(|f| f.plugin_id)
            })
            .unwrap();
        assert_eq!(n.len(), 3, "type filter still applies inside the scan");

        // An empty type list asks for nothing — same rule as read_recent_by_types.
        assert!(store.scan_recent(None, Some(&[]), 10, |_| Some(())).unwrap().is_empty());
    }

    /// A dashboard projection is allowed to be slow; it is not allowed to
    /// become part of governance-write finality. Hold a live SELECT snapshot
    /// open inside the projection callback and prove an append commits before
    /// that reader is released. A second connection without WAL fails this
    /// control at commit; one shared connection mutex fails before the write can
    /// begin.
    #[test]
    fn scan_recent_snapshot_does_not_block_append() {
        let dir = TempDir::new().unwrap();
        let store = std::sync::Arc::new(
            SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap(),
        );
        let signer = "lct:web4:hestia:sovereign:test";
        store
            .append("seed", json!({"n": 1}), signer)
            .unwrap();

        let (entered_tx, entered_rx) = std::sync::mpsc::sync_channel(0);
        let (release_tx, release_rx) = std::sync::mpsc::sync_channel(0);
        let reader_store = store.clone();
        let reader = std::thread::spawn(move || {
            reader_store
                .scan_recent(None, None, 1, |row| {
                    entered_tx.send(()).unwrap();
                    release_rx.recv().unwrap();
                    Some(row.chain_position)
                })
                .unwrap()
        });
        entered_rx
            .recv_timeout(std::time::Duration::from_secs(2))
            .expect("reader reached a live SQLite row");

        let (appended_tx, appended_rx) = std::sync::mpsc::sync_channel(0);
        let writer_store = store.clone();
        let writer = std::thread::spawn(move || {
            let result = writer_store.append("concurrent", json!({"n": 2}), signer);
            appended_tx.send(result).unwrap();
        });
        let append_while_reader_is_live =
            appended_rx.recv_timeout(std::time::Duration::from_secs(2));

        // Always release and join before asserting, so a broken implementation
        // fails rather than leaving a permanently blocked test thread behind.
        release_tx.send(()).unwrap();
        assert_eq!(reader.join().unwrap(), vec![0]);
        writer.join().unwrap();
        append_while_reader_is_live
            .expect("a display snapshot must not delay a witness append")
            .expect("concurrent witness append succeeds");
        assert_eq!(store.len().unwrap(), 2);
    }

    #[test]
    fn online_backup_includes_wal_frames_and_stays_encrypted() {
        let dir = TempDir::new().unwrap();
        let source_path = dir.path().join("live.db");
        let snapshot_path = dir.path().join("snapshot.db");
        let store = SqliteChainStore::open(&source_path, TEST_KEY).unwrap();
        {
            let conn = store.conn.lock().unwrap();
            conn.pragma_update(None, "wal_autocheckpoint", 0).unwrap();
        }
        store
            .append(
                "committed-in-wal",
                json!({"visible": true}),
                "lct:web4:hestia:sovereign:test",
            )
            .unwrap();
        let wal_path = source_path.with_extension("db-wal");
        assert!(
            wal_path.metadata().map(|m| m.len() > 0).unwrap_or(false),
            "negative-control precondition: committed WAL frames exist"
        );

        SqliteChainStore::backup_encrypted(&source_path, &snapshot_path, TEST_KEY).unwrap();
        assert!(
            !is_plaintext_sqlite(&snapshot_path),
            "snapshot bytes remain encrypted at rest"
        );
        let snapshot = SqliteChainStore::open(&snapshot_path, TEST_KEY).unwrap();
        let rows = snapshot.read_recent(10).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].event_type, "committed-in-wal");
        drop(snapshot);
        assert!(
            SqliteChainStore::open(&snapshot_path, [9u8; 32]).is_err(),
            "snapshot must require the original key"
        );
    }

    #[test]
    fn read_recent_by_types_selects_only_the_named_types() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(&dir.path().join("w.db"), TEST_KEY).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";
        store.append("outcome", json!({"success": true}), signer).unwrap();
        store.append("gate_escalation_opened", json!({"escalation_id": "a"}), signer).unwrap();
        store.append("outcome", json!({"success": true}), signer).unwrap();
        store.append("policy_edit", json!({"change": "set_preset"}), signer).unwrap();

        let got = store
            .read_recent_by_types(None, &["gate_escalation_opened", "policy_edit"], 100)
            .unwrap();
        assert_eq!(got.len(), 2, "member traffic must not reach the admin ledger");
        // Newest first — an operator opens the ledger to see what is waiting.
        assert_eq!(got[0].event_type, "policy_edit");
        assert_eq!(got[1].event_type, "gate_escalation_opened");
    }

    /// An empty type list asks for NOTHING. Widening it to the whole chain would hand a caller
    /// every member act under a query that requested none — the silent-widening failure the
    /// ledger's status filter refuses for the same reason.
    #[test]
    fn read_recent_by_types_with_no_types_returns_nothing_not_everything() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(&dir.path().join("w.db"), TEST_KEY).unwrap();
        store
            .append("outcome", json!({"success": true}), "lct:web4:hestia:sovereign:test")
            .unwrap();
        assert!(store.read_recent_by_types(None, &[], 100).unwrap().is_empty());
    }

    #[test]
    fn read_recent_by_types_honours_the_time_cutoff() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(&dir.path().join("w.db"), TEST_KEY).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";
        store.append("policy_edit", json!({"change": "a"}), signer).unwrap();
        // A cutoff in the future excludes everything already written; the past includes it. This
        // proves the cutoff is bound and applied, not accepted and ignored.
        let future = (chrono::Utc::now() + chrono::Duration::days(1)).to_rfc3339();
        let past = (chrono::Utc::now() - chrono::Duration::days(1)).to_rfc3339();
        assert!(store.read_recent_by_types(Some(&future), &["policy_edit"], 100).unwrap().is_empty());
        assert_eq!(store.read_recent_by_types(Some(&past), &["policy_edit"], 100).unwrap().len(), 1);
    }

    #[test]
    fn append_and_read_round_trip() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";

        let e1 = store
            .append("session_started", json!({"plugin": "a"}), signer)
            .unwrap();
        let e2 = store
            .append("outcome", json!({"success": true}), signer)
            .unwrap();
        let e3 = store
            .append("outcome", json!({"success": false}), signer)
            .unwrap();

        assert_eq!(e1.prev_hash, GENESIS_PREV_HASH);
        assert_eq!(e2.prev_hash, e1.hash);
        assert_eq!(e3.prev_hash, e2.hash);
        assert_eq!(e1.chain_position, 0);
        assert_eq!(e3.chain_position, 2);

        let recent = store.read_recent(10).unwrap();
        assert_eq!(recent.len(), 3);
        assert_eq!(recent[0].chain_position, 2);
        assert_eq!(recent[2].chain_position, 0);

        let since = store.read_since(0, 10).unwrap();
        assert_eq!(since.len(), 2);
        assert_eq!(since[0].chain_position, 1);
    }

    #[test]
    fn survives_reopen() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let signer = "lct:web4:hestia:sovereign:test";

        {
            let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
            store
                .append("session_started", json!({"k": 1}), signer)
                .unwrap();
            store
                .append("outcome", json!({"success": true}), signer)
                .unwrap();
        }
        // Drop and reopen.
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.len().unwrap(), 2);
        let entries = store.read_recent(10).unwrap();
        assert_eq!(entries[0].event_type, "outcome");
        assert_eq!(entries[1].event_type, "session_started");
        // Hash linkage holds across reopen.
        assert_eq!(entries[0].prev_hash, entries[1].hash);
    }

    #[test]
    fn verify_integrity_on_clean_chain_returns_length() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(dir.path().join("w.db"), TEST_KEY).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";
        for i in 0..5 {
            store.append("evt", json!({"i": i}), signer).unwrap();
        }
        assert_eq!(store.verify_integrity().unwrap(), 5);
    }

    #[test]
    fn verify_integrity_detects_tampering() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let signer = "lct:web4:hestia:sovereign:test";
        {
            let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
            store.append("evt", json!({"a": 1}), signer).unwrap();
            store.append("evt", json!({"a": 2}), signer).unwrap();
        }
        // Tamper with event_data at chain_position 0.
        let conn = Connection::open(&path).unwrap();
        conn.pragma_update(None, "key", hex::encode(TEST_KEY))
            .unwrap();
        conn.execute(
            "UPDATE chain_entries SET event_data = ?1 WHERE chain_position = 0",
            params![r#"{"a": 99}"#],
        )
        .unwrap();
        drop(conn);

        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let err = store.verify_integrity().unwrap_err();
        let msg = format!("{err}");
        assert!(msg.contains("integrity broken"), "got: {msg}");
    }

    // ------------------------------------------------------------ B2 signed witness (#339)

    fn witness(seed: u8) -> Arc<ChainWitnessSigner> {
        let kp = KeyPair::from_secret_bytes(&[seed; 32]);
        let lct = web4_core::derive_lct_id(&kp.verifying_key());
        Arc::new(
            ChainWitnessSigner::new(kp, &lct)
                .unwrap()
                .with_signer_alias("lct:web4:hestia:sovereign:phase1-placeholder"),
        )
    }

    fn raw(path: &Path) -> Connection {
        let conn = Connection::open(path).unwrap();
        conn.pragma_update(None, "key", hex::encode(TEST_KEY)).unwrap();
        conn
    }

    fn signed_store(dir: &TempDir) -> (PathBuf, SqliteChainStore, Arc<ChainWitnessSigner>) {
        let path = dir.path().join("w.db");
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let w = witness(1);
        store.install_witness_signer(w.clone()).unwrap();
        (path, store, w)
    }

    /// A witness LCT that is not derived from the key is refused at construction.
    #[test]
    fn a_witness_lct_must_derive_from_its_key() {
        let kp = KeyPair::from_secret_bytes(&[1; 32]);
        assert!(ChainWitnessSigner::new(kp, "lct:web4:mb32:bnotmine").is_err());
    }

    /// #339 test 1: a signed row passes link integrity AND signature authenticity, and the
    /// sovereign's placeholder anchor is recorded as the witness's real LCT.
    #[test]
    fn signed_rows_pass_both_predicates_and_name_the_real_lct() {
        let dir = TempDir::new().unwrap();
        let (_path, store, w) = signed_store(&dir);
        w.set_policy_generation("policy:sha256:abc");
        let e0 = store
            .append("evt", json!({"i": 0}), "lct:web4:hestia:sovereign:phase1-placeholder")
            .unwrap();
        let e1 = store.append("evt", json!({"i": 1}), "lct:web4:mb32:brouter").unwrap();
        assert_eq!(e0.signer_lct, w.witness_lct(), "the anchor alias is stored as the real LCT");
        assert_eq!(e1.signer_lct, "lct:web4:mb32:brouter", "other signers are left as named");
        assert_eq!(store.verify_integrity().unwrap(), 2, "legacy link hash is unchanged");

        let v = store.verify_chain().unwrap();
        assert!(v.link_intact() && v.signatures_authentic(), "{v:?}");
        assert_eq!((v.length, v.signed_valid, v.legacy_unsigned), (2, 2, 0));
        assert_eq!(v.chain_id.as_deref(), Some(chain_id_for_genesis(&e0.hash).as_str()));
        assert_eq!(v.witnesses[w.public_key_hex()].rows, 2);
        let rec = store.signature_for(1).unwrap().unwrap();
        assert_eq!(rec.policy_generation, "policy:sha256:abc");
        assert_eq!(rec.row_hash, e1.hash);
        assert_eq!(store.signed_from().unwrap(), Some(0));
    }

    fn tamper(path: &Path, sql: &str) {
        raw(path).execute_batch(sql).unwrap();
    }

    fn failure_states(store: &SqliteChainStore) -> Vec<(u64, SignatureState)> {
        store.verify_chain().unwrap().failures.iter().map(|f| (f.chain_position, f.state)).collect()
    }

    /// #339 test 2 — the regression this issue exists for: rewriting ONLY `signer_lct` leaves
    /// the legacy hash valid, and the signature must fail.
    #[test]
    fn rewriting_signer_lct_breaks_the_signature_but_not_the_link() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        tamper(&path, "UPDATE chain_entries SET signer_lct = 'lct:forged' WHERE chain_position = 1");
        let v = store.verify_chain().unwrap();
        assert!(v.link_intact(), "the legacy hash does not cover signer_lct");
        assert!(!v.signatures_authentic());
        assert_eq!(failure_states(&store), vec![(1, SignatureState::Invalid)]);
    }

    /// #339 test 3: moving a signed row to another coordinate fails its signature. Moving the
    /// tail row (and its signature) to position 7 keeps prev-hash order intact, so only the
    /// signature can see it.
    #[test]
    fn rewriting_chain_position_breaks_the_signature() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        tamper(
            &path,
            "UPDATE chain_entries SET chain_position = 7 WHERE chain_position = 1;
             UPDATE chain_signatures SET chain_position = 7 WHERE chain_position = 1;",
        );
        let v = store.verify_chain().unwrap();
        assert!(v.link_intact(), "order is unchanged, so the link walk passes");
        assert_eq!(failure_states(&store), vec![(7, SignatureState::Invalid)]);
    }

    /// #339 test 4: an event_data edit fails link integrity, and the signature (whose row_hash
    /// field is the stored hash) is reported on the same walk rather than hidden behind it.
    #[test]
    fn rewriting_event_data_breaks_the_link() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        tamper(&path, r#"UPDATE chain_entries SET event_data = '{"i":99}' WHERE chain_position = 0"#);
        let v = store.verify_chain().unwrap();
        assert!(!v.link_intact());
        assert!(v.link_break.as_deref().unwrap().contains("hash mismatch"));
    }

    /// #339 test 5: a signed row carried into a different chain fails — its envelope bound the
    /// genesis-derived id of the chain it was signed in.
    #[test]
    fn a_signed_row_moved_to_another_chain_fails() {
        let dir = TempDir::new().unwrap();
        let (_p, a, _w) = signed_store(&dir);
        a.append("evt", json!({"chain": "a"}), "lct:a").unwrap();
        let row = a.append("evt", json!({"i": 1}), "lct:a").unwrap();
        let rec = a.signature_for(1).unwrap().unwrap();
        let other_chain = chain_id_for_genesis(&"f".repeat(64));
        assert!(verify_row_signature(&a.chain_id().unwrap(), 1, &row.hash, "lct:a", &rec).is_ok());
        assert!(verify_row_signature(&other_chain, 1, &row.hash, "lct:a", &rec).is_err());
        // Even if the record is relabelled to claim the other chain, the signature fails.
        let relabelled = ChainSignatureRecord { chain_id: other_chain.clone(), ..rec };
        let err = verify_row_signature(&other_chain, 1, &row.hash, "lct:a", &relabelled).unwrap_err();
        assert!(err.contains("Ed25519"), "{err}");
    }

    /// #339 test 6: key rotation. Rows keep verifying under the key they carry; a witness key
    /// swapped into a record (or a key that does not derive the claimed LCT) fails.
    #[test]
    fn rotation_keeps_old_rows_and_key_mismatch_is_detected() {
        let dir = TempDir::new().unwrap();
        let (path, store, w1) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        let w2 = witness(2);
        store.install_witness_signer(w2.clone()).unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        let v = store.verify_chain().unwrap();
        assert!(v.signatures_authentic(), "{v:?}");
        assert_eq!(v.witnesses.len(), 2);
        assert_eq!(v.witnesses[w1.public_key_hex()].last_position, 0);
        assert_eq!(v.witnesses[w2.public_key_hex()].first_position, 1);

        // Swap row 1's key for w1's: the key no longer derives the claimed witness LCT.
        tamper(&path, &format!(
            "UPDATE chain_signatures SET witness_public_key = '{}' WHERE chain_position = 1",
            w1.public_key_hex()));
        let f = store.verify_chain().unwrap().failures;
        assert!(f[0].reason.contains("not derived"), "{f:?}");
        // Swap key AND LCT consistently: the signature was made by w2, so it fails.
        tamper(&path, &format!(
            "UPDATE chain_signatures SET witness_lct = '{}' WHERE chain_position = 1",
            w1.witness_lct()));
        let f = store.verify_chain().unwrap().failures;
        assert!(f[0].reason.contains("Ed25519"), "{f:?}");
    }

    /// #339 test 7: an unsigned historical chain stays readable as legacy_unsigned with its
    /// hashes unchanged, and signing begins at the next append.
    #[test]
    fn legacy_rows_stay_legacy_and_signing_begins_after_them() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let legacy: Vec<String> = {
            let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
            (0..3).map(|i| store.append("evt", json!({"i": i}), "lct:old").unwrap().hash).collect()
        };
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let v = store.verify_chain().unwrap();
        assert_eq!((v.legacy_unsigned, v.signed_valid), (3, 0));
        assert!(v.link_intact() && v.signatures_authentic());
        store.install_witness_signer(witness(1)).unwrap();
        store.append("evt", json!({"i": 3}), "lct:new").unwrap();
        let v = store.verify_chain().unwrap();
        assert_eq!((v.legacy_unsigned, v.signed_valid, v.first_signed_position), (3, 1, Some(3)));
        assert!(v.signatures_authentic(), "{v:?}");
        let now: Vec<String> = store.read_from(0, 3).unwrap().into_iter().map(|e| e.hash).collect();
        assert_eq!(now, legacy, "no historical row was rewritten");
        assert_eq!(store.chain_id(), Some(chain_id_for_genesis(&legacy[0])));
    }

    /// Downgrade, two ways: a handle without the key refuses to append to a signed chain, and an
    /// unsigned row planted after a signed one (with a correct legacy hash, so the link walk
    /// passes) is reported as MissingAfterSigned. Stripping a mid-chain signature likewise.
    #[test]
    fn a_downgrade_to_unsigned_rows_is_refused_and_detected() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        let tail = store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        drop(store);

        let unsigned = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let err = unsigned.append("evt", json!({"i": 2}), "lct:a").unwrap_err();
        assert!(format!("{err}").contains("refuses an unsigned append"), "{err}");
        assert_eq!(unsigned.len().unwrap(), 2, "the refused append left nothing behind");

        // Plant a correctly-linked unsigned row at position 2.
        let last = unsigned.read_from(1, 1).unwrap().remove(0);
        let ts = Utc::now();
        let data = r#"{"i":2}"#;
        let h = compute_hash(&last.hash, &ts, "evt", data);
        raw(&path).execute(
            "INSERT INTO chain_entries VALUES (2, ?1, ?2, 'evt', ?3, 'lct:a', ?4)",
            params![h, last.hash, data, ts.to_rfc3339()],
        ).unwrap();
        let v = unsigned.verify_chain().unwrap();
        assert!(v.link_intact(), "{v:?}");
        assert_eq!(failure_states(&unsigned), vec![(2, SignatureState::MissingAfterSigned)]);

        // Strip the signature from the genesis row too: the meta record still says position 0.
        tamper(&path, "DELETE FROM chain_signatures WHERE chain_position = 0");
        let states = failure_states(&unsigned);
        assert!(states.contains(&(0, SignatureState::MissingAfterSigned)), "{states:?}");
        let _ = tail;
    }

    /// Losing only boundary metadata must not enable unsigned appends while signed rows
    /// still exist. The verifier already recognizes this evidence; append must do so too.
    #[test]
    fn missing_boundary_metadata_does_not_allow_unsigned_extension() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        drop(store);
        tamper(&path, "DELETE FROM chain_meta WHERE key = 'signed_from_position'");

        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        let before = store.verify_chain().unwrap();
        assert_eq!(before.recorded_signed_from, None);
        assert_eq!(before.signed_valid, 1);
        // The record is written with the first signature, so its absence is reported.
        assert!(before.meta_mismatch.as_deref().is_some_and(|m| m.contains("no signed_from_position")));
        assert!(!before.signatures_authentic());
        // The predicate daemon startup and the CLI opener use sees the surviving signature.
        assert_eq!(store.signed_from().unwrap(), Some(0));
        let result = store.append("evt", json!({"i": 1}), "lct:a");
        let after = store.verify_chain().unwrap();
        assert!(result.is_err(), "unsigned append succeeded after metadata loss; verification: {after:?}");
        assert_eq!(store.len().unwrap(), 1, "refusal must leave no additional row");
    }

    /// The reverse loss: signature rows gone, record intact. The record alone still refuses.
    #[test]
    fn missing_signature_rows_with_a_boundary_record_still_refuse_unsigned_appends() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        drop(store);
        tamper(&path, "DELETE FROM chain_signatures");
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.signed_from().unwrap(), Some(0));
        assert!(store.append("evt", json!({"i": 1}), "lct:a").is_err());
        assert_eq!(store.len().unwrap(), 1);
    }

    /// A malformed record is an error for every handle and every append, never "unsigned".
    #[test]
    fn malformed_boundary_metadata_refuses_every_append() {
        let dir = TempDir::new().unwrap();
        let (path, store, w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        drop(store);
        tamper(&path, "UPDATE chain_meta SET value = 'zero' WHERE key = 'signed_from_position'");

        let unsigned = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert!(unsigned.signed_from().is_err());
        assert!(unsigned.append("evt", json!({"i": 1}), "lct:a").is_err());
        drop(unsigned);
        let signed = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        signed.install_witness_signer(w).unwrap();
        assert!(signed.append("evt", json!({"i": 1}), "lct:a").is_err());
        assert_eq!(signed.len().unwrap(), 1);
    }

    /// Record and signatures disagree: the earlier position wins, and the mismatch is reported.
    #[test]
    fn inconsistent_boundary_metadata_takes_the_earlier_position() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        drop(store);
        tamper(&path, "UPDATE chain_meta SET value = '5' WHERE key = 'signed_from_position'");
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.signed_from().unwrap(), Some(0));
        assert!(store.verify_chain().unwrap().meta_mismatch.is_some());
        assert!(store.append("evt", json!({"i": 2}), "lct:a").is_err());
        assert_eq!(store.len().unwrap(), 2);
    }

    /// A signed append after the record was deleted must not write a new, later boundary:
    /// that would forge the record and erase the verifier's evidence of the deletion.
    #[test]
    fn a_signed_append_does_not_rewrite_a_deleted_boundary() {
        let dir = TempDir::new().unwrap();
        let (path, store, w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        drop(store);
        tamper(&path, "DELETE FROM chain_meta WHERE key = 'signed_from_position'");
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        store.install_witness_signer(w).unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        let v = store.verify_chain().unwrap();
        assert_eq!((v.signed_valid, v.recorded_signed_from), (2, None));
        assert!(v.meta_mismatch.is_some());
        assert_eq!(store.signed_from().unwrap(), Some(0));
    }

    /// chain-verify uses a predictable temporary directory. If its parent is a symlink
    /// to the source directory, the snapshot helper must not unlink the source database.
    #[cfg(unix)]
    #[test]
    fn snapshot_parent_alias_must_not_replace_source_chain() {
        let dir = TempDir::new().unwrap();
        let source_dir = dir.path().join("source");
        std::fs::create_dir(&source_dir).unwrap();
        let source = source_dir.join("witness.db");
        let expected_hash = {
            let store = SqliteChainStore::open(&source, TEST_KEY).unwrap();
            store.append("evt", json!({"keep": true}), "lct:a").unwrap().hash
        };
        let alias = dir.path().join("snapshot-alias");
        std::os::unix::fs::symlink(&source_dir, &alias).unwrap();
        // Without the alias refusal the helper unlinks the source and then backs the recreated
        // file up onto itself, which never completes: bound the call so a regression FAILS.
        let (tx, rx) = std::sync::mpsc::channel();
        let (src, dst) = (source.clone(), alias.join("witness.db"));
        std::thread::spawn(move || {
            let _ = tx.send(SqliteChainStore::backup_encrypted(&src, dst, TEST_KEY));
        });
        let result = rx
            .recv_timeout(std::time::Duration::from_secs(30))
            .expect("snapshot through a parent alias hung: the source was likely unlinked");
        let preserved = raw(&source).query_row(
            "SELECT hash FROM chain_entries WHERE chain_position = 0", [],
            |row| row.get::<_, String>(0),
        );
        assert_eq!(preserved.ok().as_deref(), Some(expected_hash.as_str()),
            "snapshot replaced its source through a parent alias; backup result: {result:?}");
        assert!(result.is_err(), "aliased source/destination must be refused");
    }

    /// The same refusal for a symlinked destination file, a hard link, and the source's WAL.
    #[cfg(unix)]
    #[test]
    fn snapshot_refuses_file_symlink_hard_link_and_side_file_destinations() {
        let dir = TempDir::new().unwrap();
        let source = dir.path().join("witness.db");
        let expected_hash = {
            let store = SqliteChainStore::open(&source, TEST_KEY).unwrap();
            store.append("evt", json!({"keep": true}), "lct:a").unwrap().hash
        };
        let link = dir.path().join("link.db");
        std::os::unix::fs::symlink(&source, &link).unwrap();
        let hard = dir.path().join("hard.db");
        std::fs::hard_link(&source, &hard).unwrap();
        for dest in [link, hard, dir.path().join("witness.db-wal")] {
            let result = SqliteChainStore::backup_encrypted(&source, &dest, TEST_KEY);
            assert!(result.is_err(), "{} was accepted as a destination", dest.display());
        }
        let preserved: String = raw(&source)
            .query_row("SELECT hash FROM chain_entries WHERE chain_position = 0", [], |r| r.get(0))
            .unwrap();
        assert_eq!(preserved, expected_hash);
    }

    /// #339 test 8: reopen preserves signatures, chain id, and signed-from.
    #[test]
    fn reopen_preserves_signatures_and_chain_id() {
        let dir = TempDir::new().unwrap();
        let (path, store, w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        let id = store.chain_id().unwrap();
        drop(store);
        let store = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        assert_eq!(store.chain_id(), Some(id.clone()));
        store.install_witness_signer(w).unwrap();
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        let v = store.verify_chain().unwrap();
        assert_eq!(v.recorded_chain_id, Some(id));
        assert_eq!((v.signed_valid, v.recorded_signed_from), (2, Some(0)));
        assert!(v.signatures_authentic(), "{v:?}");
    }

    /// #339 test 9: the signature commits with its row or not at all. A failing signature
    /// insert rolls the row back, and the cached length does not move.
    #[test]
    fn a_failed_signature_insert_leaves_no_row_behind() {
        let dir = TempDir::new().unwrap();
        let (path, store, _w) = signed_store(&dir);
        store.append("evt", json!({"i": 0}), "lct:a").unwrap();
        tamper(&path, "CREATE TRIGGER no_sig BEFORE INSERT ON chain_signatures
                       BEGIN SELECT RAISE(ABORT, 'injected'); END;");
        assert!(store.append("evt", json!({"i": 1}), "lct:a").is_err());
        assert_eq!(store.len().unwrap(), 1);
        let n: i64 = raw(&path).query_row("SELECT COUNT(*) FROM chain_entries", [], |r| r.get(0)).unwrap();
        assert_eq!(n, 1, "the row must not commit without its signature");
        tamper(&path, "DROP TRIGGER no_sig;");
        store.append("evt", json!({"i": 1}), "lct:a").unwrap();
        assert!(store.verify_chain().unwrap().signatures_authentic());
    }

    /// An idempotent replay across the upgrade: a key first witnessed under the placeholder
    /// anchor replays cleanly once the signer maps that anchor to the real LCT.
    #[test]
    fn append_once_replay_treats_the_anchor_alias_as_the_same_signer() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let anchor = "lct:web4:hestia:sovereign:phase1-placeholder";
        let first = {
            let s = SqliteChainStore::open(&path, TEST_KEY).unwrap();
            s.append_once("k1", "evt", json!({"n": 1}), anchor).unwrap().0
        };
        let s = SqliteChainStore::open(&path, TEST_KEY).unwrap();
        s.install_witness_signer(witness(1)).unwrap();
        let (again, inserted) = s.append_once("k1", "evt", json!({"n": 1}), anchor).unwrap();
        assert!(!inserted);
        assert_eq!(again.hash, first.hash);
    }

    /// #339 test 10: a pinned signature from a fixed key over the wire golden fields. Ed25519 is
    /// deterministic, so this pins the "sign the preimage directly" choice end to end.
    #[test]
    fn the_chain_signature_golden_signature_is_pinned() {
        let kp = KeyPair::from_secret_bytes(&[0x42; 32]);
        let pre = signature_preimage(
            &format!("hestia-chain:{}", "1".repeat(64)),
            42,
            &"2".repeat(64),
            "lct:web4:mb32:bsigner",
            "lct:web4:mb32:bwitness",
            &"3".repeat(64),
            &format!("policy:sha256:{}", "4".repeat(64)),
        );
        assert_eq!(
            hex::encode(Sha256::digest(&pre)),
            "4264c2847d2326043dffd34d94946c1d334abddd1c9b9791caca69e12c6eab8d",
            "must equal hestia-wire's golden vector"
        );
        // Reproduced independently (Python `cryptography`, Ed25519 over the same bytes).
        assert_eq!(
            kp.sign(&pre).to_hex(),
            "dbfb719edc9ccc95830dd8cf0e37bff4bb05f700f099e73acb942ec6f176bbab\
             6eb7b9e9bb0b72c66fe933ccaa40b65df3e9ef1c9cf9992478a2f083d03d4a0c"
        );
    }
}
