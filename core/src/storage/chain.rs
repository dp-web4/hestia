//! SQLite-backed hash-linked witness chain.
//!
//! Entries are append-only. Each entry's `hash` is the sha256 of
//! `prev_hash || timestamp_rfc3339 || event_type || event_data_json`,
//! so any tamper to the JSON, timestamp, or type breaks the chain.
//! The genesis entry's `prev_hash` is `"0" * 64`.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

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

/// Witness chain persisted to SQLite. Locking is internal so the store
/// is `Send + Sync` from the caller's perspective.
pub struct SqliteChainStore {
    conn: Mutex<Connection>,
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
    len: AtomicU64,
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

impl SqliteChainStore {
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
             CREATE INDEX IF NOT EXISTS idx_chain_timestamp  ON chain_entries(timestamp);",
        )?;
        // Pay the O(n) count exactly once, at open, then track it incrementally.
        let n: i64 = conn.query_row("SELECT COUNT(*) FROM chain_entries", [], |row| row.get(0))?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
            len: AtomicU64::new(n as u64),
        })
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
        let conn = self.conn.lock().unwrap();
        let h: Option<String> = conn
            .query_row(
                "SELECT hash FROM chain_entries ORDER BY chain_position DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        Ok(h.unwrap_or_else(|| GENESIS_PREV_HASH.to_string()))
    }

    /// Append a new entry. `signer_lct` is the sovereign LCT for now;
    /// Session 4 may sign with the Ed25519 key bound to it.
    pub fn append(
        &self,
        event_type: &str,
        event_data: serde_json::Value,
        signer_lct: &str,
    ) -> Result<ChainEntry> {
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;
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

        let timestamp = Utc::now();
        let event_json = serde_json::to_string(&event_data)?;
        let hash = compute_hash(&prev_hash, &timestamp, event_type, &event_json);

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
        tx.commit()?;
        // Only after the row is durably committed. Serialised by the `conn` mutex we still
        // hold, so no two appends race; `Release` pairs with the `Acquire` in `len()`.
        self.len.fetch_add(1, Ordering::Release);

        Ok(ChainEntry {
            hash,
            prev_hash,
            timestamp,
            event_type: event_type.to_string(),
            event_data,
            signer_lct: signer_lct.to_string(),
            chain_position,
        })
    }

    /// Most recent `limit` entries in descending chain_position order.
    pub fn read_recent(&self, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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

    /// Most-recent "didn't succeed" entries (descending). Includes both
    /// failed outcomes (`event_type='outcome'`, success=false) and
    /// policy denials (`event_type='policy_decision'`, decision='deny').
    /// From an operator's standpoint these are the same category — the
    /// tool call didn't go through, whether because it ran and failed
    /// or because the gate blocked it.
    /// Fetch one entry by its hash (the chain's stable public identifier —
    /// receipts, claim_refs, and supersedes links all address entries this way).
    pub fn read_by_hash(&self, hash: &str) -> Result<Option<ChainEntry>> {
        let conn = self.conn.lock().unwrap();
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
    pub fn read_by_hash_prefix(&self, prefix: &str, cap: u64) -> Result<Vec<ChainEntry>> {
        validate_hash_pointer(prefix)?;
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM chain_entries WHERE hash LIKE ?1 || '%'",
            params![prefix],
            |r| r.get(0),
        )?;
        Ok(n.max(0) as u64)
    }

    pub fn read_failures(&self, limit: u64) -> Result<Vec<ChainEntry>> {
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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
        let conn = self.conn.lock().unwrap();
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
}
