//! SQLite-backed hash-linked witness chain.
//!
//! Entries are append-only. Each entry's `hash` is the sha256 of
//! `prev_hash || timestamp_rfc3339 || event_type || event_data_json`,
//! so any tamper to the JSON, timestamp, or type breaks the chain.
//! The genesis entry's `prev_hash` is `"0" * 64`.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

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

/// Witness chain persisted to SQLite. Locking is internal so the store
/// is `Send + Sync` from the caller's perspective.
pub struct SqliteChainStore {
    conn: Mutex<Connection>,
    path: PathBuf,
}

const GENESIS_PREV_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

impl SqliteChainStore {
    /// Open or create the witness chain database at the given path.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating witness dir {}", parent.display()))?;
        }
        let conn = Connection::open(&path)
            .with_context(|| format!("opening witness chain at {}", path.display()))?;
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
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Number of entries currently in the chain.
    pub fn len(&self) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        let n: i64 = conn.query_row("SELECT COUNT(*) FROM chain_entries", [], |row| row.get(0))?;
        Ok(n as u64)
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

    /// Most-recent "didn't succeed" entries (descending). Includes both
    /// failed outcomes (`event_type='outcome'`, success=false) and
    /// policy denials (`event_type='policy_decision'`, decision='deny').
    /// From an operator's standpoint these are the same category — the
    /// tool call didn't go through, whether because it ran and failed
    /// or because the gate blocked it.
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

    #[test]
    fn empty_store_reports_zero_and_genesis_tail() {
        let dir = TempDir::new().unwrap();
        let store = SqliteChainStore::open(dir.path().join("w.db")).unwrap();
        assert_eq!(store.len().unwrap(), 0);
        assert!(store.is_empty().unwrap());
        assert_eq!(store.tail_hash().unwrap(), GENESIS_PREV_HASH);
    }

    #[test]
    fn append_and_read_round_trip() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("w.db");
        let store = SqliteChainStore::open(&path).unwrap();
        let signer = "lct:web4:hestia:sovereign:test";

        let e1 = store.append("session_started", json!({"plugin": "a"}), signer).unwrap();
        let e2 = store.append("outcome", json!({"success": true}), signer).unwrap();
        let e3 = store.append("outcome", json!({"success": false}), signer).unwrap();

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
            let store = SqliteChainStore::open(&path).unwrap();
            store.append("session_started", json!({"k": 1}), signer).unwrap();
            store.append("outcome", json!({"success": true}), signer).unwrap();
        }
        // Drop and reopen.
        let store = SqliteChainStore::open(&path).unwrap();
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
        let store = SqliteChainStore::open(dir.path().join("w.db")).unwrap();
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
            let store = SqliteChainStore::open(&path).unwrap();
            store.append("evt", json!({"a": 1}), signer).unwrap();
            store.append("evt", json!({"a": 2}), signer).unwrap();
        }
        // Tamper with event_data at chain_position 0.
        let conn = Connection::open(&path).unwrap();
        conn.execute(
            "UPDATE chain_entries SET event_data = ?1 WHERE chain_position = 0",
            params![r#"{"a": 99}"#],
        )
        .unwrap();
        drop(conn);

        let store = SqliteChainStore::open(&path).unwrap();
        let err = store.verify_integrity().unwrap_err();
        let msg = format!("{err}");
        assert!(msg.contains("integrity broken"), "got: {msg}");
    }
}
