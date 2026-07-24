//! SQLCipher-encrypted durable inbound mailbox (the entity-edge inbox).
//!
//! The citizen side of accept-and-defer: `hestia_notify` with `defer: true`
//! parks the still-sealed notice here *before* ACKing the hub, so an
//! ACK-then-crash can no longer lose a work item the hub believes delivered.
//! A local consumer drains it later via the `hestia_inbox` tool.
//!
//! Two distinct persistences by doctrine (witness chain = completion ledger;
//! inbox = durable work queue), expressed as two files: `inbox.db` lives
//! beside `witness.db`, sealed under the same stable storage key. Notices are
//! stored **still channel-sealed to this member's identity** — SQLCipher gives
//! at-rest encryption + tamper-evidence for the queue itself, and the body
//! stays end-to-end sealed inside it (two independent crypto layers). Bodies
//! are only opened at drain time, with the vault identity keypair.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use uuid::Uuid;

/// Notice retention. Mirrors the hub's mailbox TTL: entries older than this
/// are pruned on enqueue and on drain (a stale work item is worse than a
/// missing one — its context is gone and its sender long since timed out).
const INBOX_TTL_SECS: i64 = 7 * 24 * 3600;

/// Queue cap. At the cap the oldest notice is dropped to admit the newest
/// (same policy as the hub's per-member mailbox) — backpressure signalling
/// beyond drop-oldest is a ZAP Q4 question, not settled here.
const MAX_INBOX_NOTICES: u64 = 1000;

/// One deferred inbound notice, exactly as it arrived: `sealed` is still the
/// hub-sealed ciphertext; `pair_id` + `hub_pubkey_hex` are the channel context
/// needed to open it at drain time.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InboxNotice {
    /// Row id assigned at enqueue (drain consumes by id, oldest first).
    pub id: u64,
    pub pair_id: Uuid,
    pub from_hub: Uuid,
    pub hub_pubkey_hex: String,
    pub sealed: String,
    pub kind: String,
    pub pointer_uri: Option<String>,
    pub queued_at: DateTime<Utc>,
}

/// Durable inbound mailbox persisted to SQLCipher. Locking is internal so the
/// store is `Send + Sync` from the caller's perspective (same shape as
/// [`super::SqliteChainStore`]).
pub struct SqliteInboxStore {
    conn: Mutex<Connection>,
    path: PathBuf,
}

impl SqliteInboxStore {
    /// Open or create the SQLCipher-encrypted inbox. `key` is the stable
    /// storage key (see [`crate::storage::storage_key`]) — the same key that
    /// seals the witness chain, applied as the SQLCipher key (hex). No
    /// plaintext-migration path: the inbox never existed unencrypted.
    pub fn open(path: impl AsRef<Path>, key: [u8; 32]) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("creating inbox dir {}", parent.display()))?;
        }
        let conn = Connection::open(&path)
            .with_context(|| format!("opening inbox at {}", path.display()))?;
        // SQLCipher: key the connection before any other access.
        conn.pragma_update(None, "key", hex::encode(key))
            .with_context(|| "applying SQLCipher key to inbox")?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS inbox_notices (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id        TEXT NOT NULL,
                from_hub       TEXT NOT NULL,
                hub_pubkey_hex TEXT NOT NULL,
                sealed         TEXT NOT NULL,
                kind           TEXT NOT NULL,
                pointer_uri    TEXT,
                queued_at      TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_inbox_queued_at ON inbox_notices(queued_at);",
        )
        .context("initializing inbox schema (wrong storage key, or not an inbox DB?)")?;
        Ok(Self {
            conn: Mutex::new(conn),
            path,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Number of notices currently queued.
    pub fn len(&self) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        let n: i64 = conn.query_row("SELECT COUNT(*) FROM inbox_notices", [], |row| row.get(0))?;
        Ok(n as u64)
    }

    pub fn is_empty(&self) -> Result<bool> {
        Ok(self.len()? == 0)
    }

    /// Park one still-sealed notice. Prunes expired entries first, then drops
    /// the oldest if at cap. Returns the assigned row id — the enqueue is
    /// durable when this returns, which is what lets the caller ACK the sender
    /// *afterwards* (O: park before acknowledge).
    pub fn enqueue(
        &self,
        pair_id: Uuid,
        from_hub: Uuid,
        hub_pubkey_hex: &str,
        sealed: &str,
        kind: &str,
        pointer_uri: Option<&str>,
    ) -> Result<u64> {
        let now = Utc::now();
        let cutoff = (now - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "DELETE FROM inbox_notices WHERE queued_at < ?1",
            params![cutoff],
        )
        .context("pruning expired inbox notices")?;
        let count: i64 =
            conn.query_row("SELECT COUNT(*) FROM inbox_notices", [], |row| row.get(0))?;
        if count as u64 >= MAX_INBOX_NOTICES {
            conn.execute(
                "DELETE FROM inbox_notices WHERE id = (SELECT MIN(id) FROM inbox_notices)",
                [],
            )
            .context("dropping oldest inbox notice at cap")?;
        }
        conn.execute(
            "INSERT INTO inbox_notices
                 (pair_id, from_hub, hub_pubkey_hex, sealed, kind, pointer_uri, queued_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                pair_id.to_string(),
                from_hub.to_string(),
                hub_pubkey_hex,
                sealed,
                kind,
                pointer_uri,
                now.to_rfc3339(),
            ],
        )
        .context("enqueuing inbox notice")?;
        Ok(conn.last_insert_rowid() as u64)
    }

    /// Consume-once drain: atomically take every unexpired notice (oldest
    /// first) and delete them. A crash *before* return leaves the transaction
    /// rolled back — the notices survive to the next drain (at-least-once,
    /// the same failure bias as the hub's mailbox).
    pub fn drain(&self) -> Result<Vec<InboxNotice>> {
        let cutoff = (Utc::now() - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction().context("starting inbox drain")?;
        let notices = {
            let mut stmt = tx
                .prepare(
                    "SELECT id, pair_id, from_hub, hub_pubkey_hex, sealed, kind, pointer_uri, queued_at
                     FROM inbox_notices WHERE queued_at >= ?1 ORDER BY id ASC",
                )
                .context("preparing inbox drain SELECT")?;
            let rows = stmt
                .query_map(params![cutoff], |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, Option<String>>(6)?,
                        row.get::<_, String>(7)?,
                    ))
                })
                .context("querying inbox notices")?;
            let mut out = Vec::new();
            for row in rows {
                let (id, pair_id, from_hub, hub_pubkey_hex, sealed, kind, pointer_uri, queued_at) =
                    row.context("reading inbox row")?;
                out.push(InboxNotice {
                    id: id as u64,
                    pair_id: Uuid::parse_str(&pair_id).context("parsing inbox pair_id")?,
                    from_hub: Uuid::parse_str(&from_hub).context("parsing inbox from_hub")?,
                    hub_pubkey_hex,
                    sealed,
                    kind,
                    pointer_uri,
                    queued_at: DateTime::parse_from_rfc3339(&queued_at)
                        .context("parsing inbox queued_at")?
                        .with_timezone(&Utc),
                });
            }
            out
        };
        // Expired entries fall out here too (drain leaves the table empty).
        tx.execute("DELETE FROM inbox_notices", [])
            .context("consuming drained inbox notices")?;
        tx.commit().context("committing inbox drain")?;
        Ok(notices)
    }

    // ---- Local member mesh (dp 2026-07-24: hestia is a fractal mini-fleet; ----
    // ---- members coordinate through the daemon, witnessed, pointer-based) ----

    /// Ensure the member_notices table exists (idempotent; called lazily so
    /// pre-existing inbox DBs upgrade in place).
    fn ensure_member_schema(conn: &Connection) -> Result<()> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS member_notices (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                to_plugin    TEXT NOT NULL,
                from_plugin  TEXT NOT NULL,
                from_role    TEXT NOT NULL,
                kind         TEXT NOT NULL,
                pointer_uri  TEXT,
                chain_hash   TEXT NOT NULL,
                queued_at    TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_member_notices_to
                 ON member_notices(to_plugin, queued_at);",
        )
        .context("initializing member_notices schema")?;
        Ok(())
    }

    /// Park a member→member notice (pointer-based — the CONTENT lives at the
    /// pointer; the notice is the wake signal, mirroring the fleet hub-mesh).
    /// `chain_hash` is the witnessing `member_notice` chain entry — every
    /// queued notice is anchored to its witnessed act.
    pub fn enqueue_member(
        &self,
        to_plugin: &str,
        from_plugin: &str,
        from_role: &str,
        kind: &str,
        pointer_uri: Option<&str>,
        chain_hash: &str,
    ) -> Result<u64> {
        let now = Utc::now();
        let cutoff = (now - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        conn.execute(
            "DELETE FROM member_notices WHERE queued_at < ?1",
            params![cutoff],
        )
        .context("pruning expired member notices")?;
        let count: i64 =
            conn.query_row("SELECT COUNT(*) FROM member_notices", [], |row| row.get(0))?;
        if count as u64 >= MAX_INBOX_NOTICES {
            conn.execute(
                "DELETE FROM member_notices WHERE id = (SELECT MIN(id) FROM member_notices)",
                [],
            )
            .context("dropping oldest member notice at cap")?;
        }
        conn.execute(
            "INSERT INTO member_notices
                 (to_plugin, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                to_plugin,
                from_plugin,
                from_role,
                kind,
                pointer_uri,
                chain_hash,
                now.to_rfc3339(),
            ],
        )
        .context("enqueuing member notice")?;
        Ok(conn.last_insert_rowid() as u64)
    }

    /// Consume-once drain of the notices addressed to `to_plugin` ONLY —
    /// recipient-scoped (a member can never drain another member's mail).
    /// Same at-least-once failure bias as the hub-notice drain.
    pub fn drain_member(&self, to_plugin: &str) -> Result<Vec<MemberNotice>> {
        let cutoff = (Utc::now() - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let mut conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let tx = conn.transaction().context("starting member drain")?;
        let notices = {
            let mut stmt = tx
                .prepare(
                    "SELECT id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at
                     FROM member_notices
                     WHERE to_plugin = ?1 AND queued_at >= ?2 ORDER BY id ASC",
                )
                .context("preparing member drain SELECT")?;
            let rows = stmt
                .query_map(params![to_plugin, cutoff], |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, Option<String>>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, String>(6)?,
                    ))
                })
                .context("querying member notices")?;
            let mut out = Vec::new();
            for row in rows {
                let (id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at) =
                    row.context("reading member notice row")?;
                out.push(MemberNotice {
                    id: id as u64,
                    from_plugin,
                    from_role,
                    kind,
                    pointer_uri,
                    chain_hash,
                    queued_at: DateTime::parse_from_rfc3339(&queued_at)
                        .context("parsing member notice queued_at")?
                        .with_timezone(&Utc),
                });
            }
            out
        };
        tx.execute(
            "DELETE FROM member_notices WHERE to_plugin = ?1",
            params![to_plugin],
        )
        .context("consuming drained member notices")?;
        tx.commit().context("committing member drain")?;
        Ok(notices)
    }

    /// Non-consuming list of a recipient's queued notices (oldest first) —
    /// the SessionStart surface: a new session PEEKS so mail survives a session
    /// that dies early; consume happens via drain when the member acts.
    pub fn peek_member(&self, to_plugin: &str) -> Result<Vec<MemberNotice>> {
        let cutoff = (Utc::now() - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare(
            "SELECT id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at
             FROM member_notices
             WHERE to_plugin = ?1 AND queued_at >= ?2 ORDER BY id ASC",
        )?;
        let rows = stmt.query_map(params![to_plugin, cutoff], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, String>(6)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at) = row?;
            out.push(MemberNotice {
                id: id as u64, from_plugin, from_role, kind, pointer_uri, chain_hash,
                queued_at: DateTime::parse_from_rfc3339(&queued_at)
                    .context("parsing member notice queued_at")?
                    .with_timezone(&Utc),
            });
        }
        Ok(out)
    }

    /// Count queued notices for a recipient without consuming (the watcher's
    /// cheap poll — fire the member only when there is something to read).
    pub fn member_pending(&self, to_plugin: &str) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices WHERE to_plugin = ?1",
            params![to_plugin],
            |row| row.get(0),
        )?;
        Ok(n as u64)
    }
}

/// One member→member notice (the local-mesh wake signal).
#[derive(Debug, Clone, serde::Serialize)]
pub struct MemberNotice {
    pub id: u64,
    pub from_plugin: String,
    pub from_role: String,
    pub kind: String,
    pub pointer_uri: Option<String>,
    pub chain_hash: String,
    pub queued_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fresh() -> (tempfile::TempDir, SqliteInboxStore) {
        let tmp = tempdir().unwrap();
        let store = SqliteInboxStore::open(tmp.path().join("inbox.db"), [7u8; 32]).unwrap();
        (tmp, store)
    }

    #[test]
    fn member_notices_are_recipient_scoped_and_consume_once() {
        let (_tmp, store) = fresh();
        store
            .enqueue_member("kimi-code", "claude-code", "role:constellation:interactive-dev",
                            "coordination", Some("forum/x.md#thread=t"), "hash-a")
            .unwrap();
        store
            .enqueue_member("codex-cli", "claude-code", "role:constellation:interactive-dev",
                            "handoff", None, "hash-b")
            .unwrap();
        assert_eq!(store.member_pending("kimi-code").unwrap(), 1);
        assert_eq!(store.member_pending("codex-cli").unwrap(), 1);
        // kimi's drain returns ONLY kimi's mail and leaves codex's intact.
        let kimi = store.drain_member("kimi-code").unwrap();
        assert_eq!(kimi.len(), 1);
        assert_eq!(kimi[0].from_plugin, "claude-code");
        assert_eq!(kimi[0].kind, "coordination");
        assert_eq!(kimi[0].chain_hash, "hash-a");
        assert_eq!(store.member_pending("kimi-code").unwrap(), 0);
        assert_eq!(store.member_pending("codex-cli").unwrap(), 1, "other member's mail untouched");
        // consume-once: second drain empty.
        assert!(store.drain_member("kimi-code").unwrap().is_empty());
    }

    #[test]
    fn enqueue_drain_consume_once() {
        let (_tmp, store) = fresh();
        assert!(store.is_empty().unwrap());
        let pair = Uuid::new_v4();
        let hub = Uuid::new_v4();
        store
            .enqueue(
                pair,
                hub,
                "aa".repeat(32).as_str(),
                "sealed-1",
                "notify:x",
                Some("hub://act/1"),
            )
            .unwrap();
        store
            .enqueue(
                pair,
                hub,
                "aa".repeat(32).as_str(),
                "sealed-2",
                "notify:y",
                None,
            )
            .unwrap();
        assert_eq!(store.len().unwrap(), 2);

        let drained = store.drain().unwrap();
        assert_eq!(drained.len(), 2);
        assert_eq!(drained[0].sealed, "sealed-1"); // oldest first
        assert_eq!(drained[0].pointer_uri.as_deref(), Some("hub://act/1"));
        assert_eq!(drained[1].sealed, "sealed-2");
        assert_eq!(drained[1].pair_id, pair);
        assert_eq!(drained[1].from_hub, hub);

        // Consume-once: a second drain is empty.
        assert!(store.drain().unwrap().is_empty());
        assert!(store.is_empty().unwrap());
    }

    #[test]
    fn survives_reopen_and_needs_the_key() {
        let tmp = tempdir().unwrap();
        let path = tmp.path().join("inbox.db");
        let pair = Uuid::new_v4();
        {
            let store = SqliteInboxStore::open(&path, [7u8; 32]).unwrap();
            store
                .enqueue(pair, Uuid::nil(), "ab", "sealed-durable", "notify:z", None)
                .unwrap();
        } // dropped: simulates daemon exit

        // Wrong key: SQLCipher must refuse (extraction + tamper resistance).
        assert!(SqliteInboxStore::open(&path, [9u8; 32]).is_err());

        // Right key: the notice survived the restart.
        let store = SqliteInboxStore::open(&path, [7u8; 32]).unwrap();
        let drained = store.drain().unwrap();
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[0].sealed, "sealed-durable");

        // And the file on disk is not plaintext SQLite.
        let hdr = &std::fs::read(&path).unwrap()[..16];
        assert_ne!(hdr, b"SQLite format 3\0", "inbox must be encrypted at rest");
    }

    #[test]
    fn cap_drops_oldest() {
        let (_tmp, store) = fresh();
        for i in 0..(MAX_INBOX_NOTICES + 2) {
            store
                .enqueue(
                    Uuid::nil(),
                    Uuid::nil(),
                    "ab",
                    &format!("sealed-{i}"),
                    "k",
                    None,
                )
                .unwrap();
        }
        assert_eq!(store.len().unwrap(), MAX_INBOX_NOTICES);
        let drained = store.drain().unwrap();
        // The two oldest were dropped to admit the two newest.
        assert_eq!(drained.first().unwrap().sealed, "sealed-2");
        assert_eq!(
            drained.last().unwrap().sealed,
            format!("sealed-{}", MAX_INBOX_NOTICES + 1)
        );
    }
}
