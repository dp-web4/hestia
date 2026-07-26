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
pub const INBOX_TTL_SECS: i64 = 7 * 24 * 3600;

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
    ///
    /// Two columns were added 2026-07-25 (Kimi ↔ CBP id-binding thread) and are
    /// migrated in place on existing DBs:
    /// - `in_reply_to` — the notice id this send answers. The convention
    ///   (`re: <id>` in forum frontmatter) already existed; this is the schema
    ///   ratifying it, so "queued with no bound response" becomes queryable.
    /// - `drained_at` — consume-once is now expressed as a MARK, not a DELETE.
    ///   Deleting the row destroyed the only evidence that a notice had ever
    ///   been delivered, which is precisely what made "was this answered?"
    ///   unaskable. Retention is unchanged (TTL prune still drops both).
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
                queued_at    TEXT NOT NULL,
                in_reply_to  INTEGER,
                drained_at   TEXT,
                -- Set when the recipient is NOT local: the peer this notice must be
                -- forwarded to (r6-routing branch 2). NULL = local delivery, the
                -- pre-routing behaviour. Nullable ALTER so existing rows stay valid
                -- without a backfill (the snarc capture silent-death lesson).
                dest_peer    TEXT,
                -- The roster-validated LCT the peer NAME resolved to, captured at
                -- enqueue. The transport is LCT-addressed; names are an edge
                -- concern. Resolving once and carrying the LCT means the drain
                -- never re-resolves against a table that may have changed, and
                -- never hands `hub-notify` a bare name for its prefix matcher to
                -- guess at (McNugget, r6-routing review §4).
                dest_peer_lct TEXT,
                -- Egress delivery is not free and not guaranteed. `attempts`
                -- counts hand-offs to the fleet mesh that FAILED; at
                -- MAX_EGRESS_ATTEMPTS the row is retired and an unreachable
                -- report goes back to the sender. Without this, an egress row is
                -- the black hole moved one hop out (Kimi, r6-routing §2.4).
                attempts     INTEGER NOT NULL DEFAULT 0,
                last_error   TEXT
             );
             CREATE INDEX IF NOT EXISTS idx_member_notices_to
                 ON member_notices(to_plugin, queued_at);",
        )
        .context("initializing member_notices schema")?;
        // In-place upgrade for inboxes created before the id-binding columns.
        let mut existing: Vec<String> = Vec::new();
        {
            let mut stmt = conn.prepare("PRAGMA table_info(member_notices)")?;
            let rows = stmt.query_map([], |row| row.get::<_, String>(1))?;
            for r in rows {
                existing.push(r?);
            }
        }
        for (col, decl) in [
            ("in_reply_to", "INTEGER"),
            ("drained_at", "TEXT"),
            ("dest_peer", "TEXT"),
            ("dest_peer_lct", "TEXT"),
            // NOT NULL DEFAULT on an ALTER would be rejected by older SQLite for
            // a non-constant default; a plain nullable INTEGER read as
            // `unwrap_or(0)` is equivalent and needs no backfill.
            ("attempts", "INTEGER"),
            ("last_error", "TEXT"),
        ] {
            if !existing.iter().any(|c| c == col) {
                conn.execute_batch(&format!(
                    "ALTER TABLE member_notices ADD COLUMN {col} {decl}"
                ))
                .with_context(|| format!("adding member_notices.{col}"))?;
            }
        }
        conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_member_notices_reply
                 ON member_notices(in_reply_to);",
        )
        .context("indexing member_notices.in_reply_to")?;
        Self::ensure_touch_schema(conn)?;
        Ok(())
    }

    /// The recipient-liveness record (Kimi ↔ CBP, 2026-07-25).
    ///
    /// The mesh had a dead-letter class: any `to_plugin` with no local watcher
    /// was accepted, witnessed, queued and never delivered, and the send
    /// returned a `queued_id` plus a witness hash — a success-shaped receipt
    /// for an undeliverable act. The fix is NOT to reject unknown recipients:
    /// that conflates *unknown* with *undeliverable* and would silence a member
    /// whose watcher is merely down, which is exactly the case queueing exists
    /// for.
    ///
    /// The signal was already flowing and was being thrown away.
    /// `hestia-watch-member.sh` calls `hestia_member_inbox` every poll interval
    /// (default 60s), empty inbox or not, so the daemon *sees* every
    /// locally-watched member on a cadence. Liveness is not something the mesh
    /// must start measuring — it is something it must start **keeping**.
    ///
    /// One row per member, updated on every attributed mailbox read
    /// ([`Self::drain_member`], [`Self::peek_member`]), hit or miss. Both keys
    /// are the caller's own resolved plugin_id, so a member cannot manufacture
    /// another member's liveness. Deliberately NOT witnessed: one chain entry
    /// per 60s poll per member would make the heartbeat a chain-growth vector,
    /// the same reason the flood guard does not witness its denials. This is a
    /// mark, like `drained_at` — it gates nothing and denies nothing.
    fn ensure_touch_schema(conn: &Connection) -> Result<()> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS member_inbox_touch (
                plugin_id  TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_touch TEXT NOT NULL,
                touches    INTEGER NOT NULL
             );",
        )
        .context("initializing member_inbox_touch schema")?;
        Ok(())
    }

    /// Ensure the eviction-count table exists. Separate from the notices table
    /// on purpose: the count must survive the rows it counts, which are gone.
    fn ensure_eviction_schema(conn: &Connection) -> Result<()> {
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS member_queue_evictions (
                plugin_id      TEXT PRIMARY KEY,
                evicted        INTEGER NOT NULL,
                first_eviction TEXT NOT NULL,
                last_eviction  TEXT NOT NULL
             );",
        )
        .context("initializing member_queue_evictions schema")?;
        Ok(())
    }

    /// How many notices addressed to `plugin_id` were silently dropped by the
    /// queue cap. Zero is a real answer here and means "none since this
    /// counter shipped" — it does NOT mean "none ever", because evictions
    /// before it left no trace of any kind. Reported, never gated on.
    pub fn member_evictions(&self, plugin_id: &str) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_eviction_schema(&conn)?;
        let n: i64 = conn.query_row(
            "SELECT COALESCE((SELECT evicted FROM member_queue_evictions WHERE plugin_id = ?1), 0)",
            params![plugin_id],
            |row| row.get(0),
        )?;
        Ok(n as u64)
    }

    /// Record that `plugin_id` read its own mailbox, now. Idempotent-by-upsert;
    /// never fails a read (a heartbeat that could break a drain would be a
    /// control wearing a mark's coat).
    fn touch_inbox(conn: &Connection, plugin_id: &str, now: &DateTime<Utc>) -> Result<()> {
        let ts = now.to_rfc3339();
        conn.execute(
            "INSERT INTO member_inbox_touch (plugin_id, first_seen, last_touch, touches)
             VALUES (?1, ?2, ?2, 1)
             ON CONFLICT(plugin_id) DO UPDATE SET
                 last_touch = ?2,
                 touches    = touches + 1",
            params![plugin_id, ts],
        )
        .context("recording member inbox touch")?;
        Ok(())
    }

    /// What is on record about `plugin_id` ever having read its mailbox.
    /// `None` = never seen: no evidence any local watcher exists for that name.
    /// That is the dead-letter class, and *only* that is — a member seen before
    /// but not lately is dormant, which is what queueing is for.
    pub fn inbox_touch(&self, plugin_id: &str) -> Result<Option<InboxTouch>> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare(
            "SELECT first_seen, last_touch, touches FROM member_inbox_touch WHERE plugin_id = ?1",
        )?;
        let mut rows = stmt.query(params![plugin_id])?;
        let Some(row) = rows.next()? else {
            return Ok(None);
        };
        let (first_seen, last_touch, touches) = (
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, i64>(2)?,
        );
        Ok(Some(InboxTouch {
            first_seen: DateTime::parse_from_rfc3339(&first_seen)
                .context("parsing inbox touch first_seen")?
                .with_timezone(&Utc),
            last_touch: DateTime::parse_from_rfc3339(&last_touch)
                .context("parsing inbox touch last_touch")?
                .with_timezone(&Utc),
            touches: touches.max(0) as u64,
        }))
    }

    /// Park a member→member notice (pointer-based — the CONTENT lives at the
    /// pointer; the notice is the wake signal, mirroring the fleet hub-mesh).
    /// `chain_hash` is the witnessing `member_notice` chain entry — every
    /// queued notice is anchored to its witnessed act. `in_reply_to` binds this
    /// send to the notice it answers (see [`Self::member_notice_recipient`] for
    /// the check the caller runs first).
    /// Enqueue a notice bound for a member on ANOTHER machine (r6-routing branch 2:
    /// "is it for someone I know? forward it"). Stored in the same table with
    /// `dest_peer` set; the watcher drains these and hands them to the fleet mesh.
    ///
    /// Loop prevention is SPLIT-HORIZON and lives here, not in the packet: only a
    /// notice whose sender is a LOCAL member is ever egressed, so a packet that
    /// arrived from outside can never be forwarded back outside. Thor refuted the
    /// per-packet TTL this proposal originally carried — a hop counter the sender
    /// writes is not a bound (2026-07-26). The sender identity used here is
    /// transport-authenticated, not caller-supplied, so there is no forgeable field
    /// in the loop bound at all. Cost: no third-party transit in v1, which is a
    /// deliberate limit, not an oversight.
    #[allow(clippy::too_many_arguments)]
    pub fn enqueue_egress(
        &self,
        dest_peer: &str,
        dest_peer_lct: &str,
        to_plugin: &str,
        from_plugin: &str,
        from_role: &str,
        kind: &str,
        pointer_uri: Option<&str>,
        chain_hash: &str,
    ) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        conn.execute(
            "INSERT INTO member_notices
                (to_plugin, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at,
                 dest_peer, dest_peer_lct, attempts)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 0)",
            params![to_plugin, from_plugin, from_role, kind, pointer_uri,
                    chain_hash, Utc::now().to_rfc3339(), dest_peer, dest_peer_lct],
        )
        .context("enqueueing egress notice")?;
        Ok(conn.last_insert_rowid() as u64)
    }

    /// Undrained egress rows, oldest first. The watcher marks each forwarded once
    /// the fleet mesh has accepted it, or failed when it has not.
    pub fn pending_egress(&self, limit: u32) -> Result<Vec<EgressRow>> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare(
            "SELECT id, dest_peer, dest_peer_lct, to_plugin, from_plugin, kind, pointer_uri,
                    attempts, last_error
               FROM member_notices
              WHERE dest_peer IS NOT NULL AND drained_at IS NULL
              ORDER BY id ASC LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit], |r| {
            Ok(EgressRow {
                id: r.get::<_, i64>(0)? as u64,
                dest_peer: r.get(1)?,
                dest_peer_lct: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                to_member: r.get(3)?,
                from_plugin: r.get(4)?,
                kind: r.get(5)?,
                pointer_uri: r.get(6)?,
                attempts: r.get::<_, Option<i64>>(7)?.unwrap_or(0),
                last_error: r.get(8)?,
            })
        })?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    /// One egress row by id, forwarded or not — for building the unreachable
    /// report that a retired row owes its sender.
    pub fn egress_row(&self, id: u64) -> Result<Option<EgressRow>> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare(
            "SELECT id, dest_peer, dest_peer_lct, to_plugin, from_plugin, kind, pointer_uri,
                    attempts, last_error
               FROM member_notices WHERE id = ?1 AND dest_peer IS NOT NULL",
        )?;
        let mut rows = stmt.query_map(params![id as i64], |r| {
            Ok(EgressRow {
                id: r.get::<_, i64>(0)? as u64,
                dest_peer: r.get(1)?,
                dest_peer_lct: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                to_member: r.get(3)?,
                from_plugin: r.get(4)?,
                kind: r.get(5)?,
                pointer_uri: r.get(6)?,
                attempts: r.get::<_, Option<i64>>(7)?.unwrap_or(0),
                last_error: r.get(8)?,
            })
        })?;
        match rows.next() {
            Some(r) => Ok(Some(r?)),
            None => Ok(None),
        }
    }

    /// Mark an egress row forwarded. Separate from delivery: this records that the
    /// fleet mesh ACCEPTED it, not that the far member read it. Conflating those is
    /// the "send succeeded != delivered" defect this whole thread is about.
    pub fn mark_egress_forwarded(&self, id: u64) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE member_notices SET drained_at = ?1 WHERE id = ?2 AND dest_peer IS NOT NULL",
            params![Utc::now().to_rfc3339(), id as i64],
        )
        .context("marking egress forwarded")?;
        Ok(())
    }

    /// Record a FAILED hand-off attempt and return the new attempt count.
    ///
    /// Retrying is safe here in a way it is not at the far end: this row has not
    /// been processed by anyone, so a re-send is `undelivered`-class (the gate
    /// refused, nothing ran), never `indeterminate`. That is why egress retries
    /// and drain retries are different questions.
    pub fn record_egress_failure(&self, id: u64, reason: &str) -> Result<i64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        conn.execute(
            "UPDATE member_notices
                SET attempts = COALESCE(attempts, 0) + 1, last_error = ?1
              WHERE id = ?2 AND dest_peer IS NOT NULL AND drained_at IS NULL",
            params![reason, id as i64],
        )
        .context("recording egress failure")?;
        let n: Option<i64> = conn
            .query_row(
                "SELECT COALESCE(attempts, 0) FROM member_notices WHERE id = ?1",
                params![id as i64],
                |r| r.get(0),
            )
            .ok();
        Ok(n.unwrap_or(0))
    }

    /// Retire an egress row that has exhausted its attempts. Marks it drained so
    /// the queue does not grow without bound; the caller is responsible for the
    /// unreachable report that this row now owes its sender. Retiring WITHOUT
    /// reporting would be the silent drop with extra steps.
    pub fn retire_egress(&self, id: u64) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE member_notices SET drained_at = ?1
              WHERE id = ?2 AND dest_peer IS NOT NULL AND drained_at IS NULL",
            params![Utc::now().to_rfc3339(), id as i64],
        )
        .context("retiring egress row")?;
        Ok(())
    }

    /// Egress rows that have outlived the forwarding TTL, oldest first.
    ///
    /// The local TTL prune deliberately skips this plane (see `enqueue_member`),
    /// which would otherwise leave the forwarding queue with no bound at all —
    /// Kimi §4, r6-routing 2026-07-26. So the bound lives here instead, and the
    /// difference is the whole point: the local prune is a silent `DELETE`,
    /// while this returns ids to a caller that owes each one a report. Never
    /// evict a forwarding row quietly — a silently dropped forward is
    /// indistinguishable from a link failure, which is the defect this
    /// exploration exists to remove.
    ///
    /// Called from the drain's read path because that is where a report can
    /// actually be emitted; a store method cannot witness one.
    pub fn expired_egress(&self, older_than_secs: i64, limit: u32) -> Result<Vec<u64>> {
        let cutoff = (Utc::now() - chrono::Duration::seconds(older_than_secs)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare(
            "SELECT id FROM member_notices
              WHERE dest_peer IS NOT NULL AND drained_at IS NULL AND queued_at < ?1
              ORDER BY id ASC LIMIT ?2",
        )?;
        let rows = stmt.query_map(params![cutoff, limit], |r| r.get::<_, i64>(0))?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row? as u64);
        }
        Ok(out)
    }

    pub fn enqueue_member(
        &self,
        to_plugin: &str,
        from_plugin: &str,
        from_role: &str,
        kind: &str,
        pointer_uri: Option<&str>,
        chain_hash: &str,
        in_reply_to: Option<u64>,
    ) -> Result<u64> {
        let now = Utc::now();
        let cutoff = (now - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        // `dest_peer IS NULL` = the LOCAL plane. Egress rows live in this same
        // table with `dest_peer` set, and they are NOT this prune's to delete: a
        // forwarding row that ages out owes its sender a report (the
        // `retire_and_report_egress` path), and a silent DELETE fired by an
        // unrelated local send is precisely the retire-without-a-receipt this
        // exploration exists to remove. Bounding the egress queue is the
        // forwarding plane's job, where a report can actually be emitted.
        conn.execute(
            "DELETE FROM member_notices WHERE queued_at < ?1 AND dest_peer IS NULL",
            params![cutoff],
        )
        .context("pruning expired member notices")?;
        // The cap bounds the QUEUE (undelivered notices), not the retained
        // delivery record — drained rows are forensics, and evicting them to
        // admit a new notice would re-open the hole `drained_at` just closed.
        // They still age out on the TTL prune above.
        //
        // The cap is PER RECIPIENT (Kimi/CBP atp-metabolism amendment 2,
        // 2026-07-25). It was global until this commit, which meant a sender at
        // its own compliant ceiling could evict a third member's mail — a
        // cross-member denial channel whose victims leave no mark, because the
        // eviction is a silent DELETE and the drop is invisible to sender,
        // recipient, and chain alike. Scoping admission and eviction to
        // `to_plugin` removes that channel: a flood now only displaces mail
        // inside the queue of the member the flooder is actually addressing.
        //
        // Two things this deliberately does NOT claim. (1) Storage is now
        // bounded by MAX_INBOX_NOTICES × distinct recipients, not by
        // MAX_INBOX_NOTICES — the previous global bound bought its fairness
        // hole with a tighter storage bound, and this trade is the intended
        // one at fleet scale (single-digit members, 7-day TTL). (2) Within one
        // recipient's queue a flooding sender still displaces a quiet sender's
        // mail to that same recipient. That residual channel is bounded by the
        // flood guard and, unlike the one removed here, requires the attacker
        // to be in a relationship with the victim's counterparty.
        // …and PER PLANE. An egress row's `to_plugin` is the REMOTE member's
        // name, which in this fleet is the same name a local member has. Without
        // `dest_peer IS NULL` the count is inflated by another host's mail and
        // the eviction can delete it — the cross-member denial channel this cap
        // was scoped to close, reopened through the forwarding plane.
        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices
              WHERE to_plugin = ?1 AND drained_at IS NULL AND dest_peer IS NULL",
            params![to_plugin],
            |row| row.get(0),
        )?;
        if count as u64 >= MAX_INBOX_NOTICES {
            conn.execute(
                "DELETE FROM member_notices
                 WHERE id = (SELECT MIN(id) FROM member_notices
                             WHERE to_plugin = ?1 AND drained_at IS NULL
                               AND dest_peer IS NULL)",
                params![to_plugin],
            )
            .context("dropping oldest member notice at cap")?;
            // An eviction is a silent DELETE: no error to the sender, no
            // notice to the recipient, no chain entry. Until this counter the
            // ONLY way to learn the cap had fired was to already know what
            // should have been there. Counting it is what makes the residual
            // (intra-recipient) channel observable at all, and the count is
            // what a retrospective `SELECT COUNT(*)` fundamentally cannot
            // recover — evicted rows are gone, and the id gaps they leave are
            // indistinguishable from the TTL prune's.
            //
            // A mark, not a witness — same call as `drained_at` and the
            // liveness touch: one chain entry per eviction, under exactly the
            // flood where evictions happen, is a chain-growth vector.
            Self::ensure_eviction_schema(&conn)?;
            conn.execute(
                "INSERT INTO member_queue_evictions
                     (plugin_id, evicted, first_eviction, last_eviction)
                 VALUES (?1, 1, ?2, ?2)
                 ON CONFLICT(plugin_id) DO UPDATE SET
                     evicted       = evicted + 1,
                     last_eviction = ?2",
                params![to_plugin, now.to_rfc3339()],
            )
            .context("recording member queue eviction")?;
        }
        conn.execute(
            "INSERT INTO member_notices
                 (to_plugin, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at,
                  in_reply_to)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                to_plugin,
                from_plugin,
                from_role,
                kind,
                pointer_uri,
                chain_hash,
                now.to_rfc3339(),
                in_reply_to.map(|v| v as i64),
            ],
        )
        .context("enqueuing member notice")?;
        Ok(conn.last_insert_rowid() as u64)
    }

    /// Who a notice was addressed to, if it is still on record. `None` means
    /// "no such row" — which is NOT the same as "forged": notices age out on
    /// the TTL, so an honest late binding to a pruned notice is unverifiable
    /// rather than false. Callers must not read the two cases as one.
    pub fn member_notice_recipient(&self, id: u64) -> Result<Option<String>> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt = conn.prepare("SELECT to_plugin FROM member_notices WHERE id = ?1")?;
        let mut rows = stmt.query(params![id as i64])?;
        Ok(match rows.next()? {
            Some(row) => Some(row.get::<_, String>(0)?),
            None => None,
        })
    }

    /// Consume-once drain of the notices addressed to `to_plugin` ONLY —
    /// recipient-scoped (a member can never drain another member's mail).
    /// Same at-least-once failure bias as the hub-notice drain.
    ///
    /// Consume-once is a MARK (`drained_at`), not a DELETE: the notice never
    /// comes back from a second drain, but the fact that it was delivered
    /// survives, so "queued and never answered" stays askable after the wake.
    ///
    /// **An empty drain is no longer a no-op.** It records a sighting
    /// ([`Self::ensure_touch_schema`]) — the watcher polls on a cadence whether
    /// or not there is mail, so the empty drains are precisely where the
    /// liveness evidence lives. This is a semantic change to what an empty
    /// drain *means*, wearing a recording change's clothes; the return value
    /// and consume-once behaviour are untouched.
    pub fn drain_member(&self, to_plugin: &str) -> Result<Vec<MemberNotice>> {
        let now = Utc::now();
        let cutoff = (now - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let mut conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let tx = conn.transaction().context("starting member drain")?;
        let notices = {
            let mut stmt = tx
                .prepare(
                    "SELECT id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at,
                            in_reply_to
                     FROM member_notices
                     WHERE to_plugin = ?1 AND queued_at >= ?2 AND drained_at IS NULL
                       AND dest_peer IS NULL
                     ORDER BY id ASC",
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
                        row.get::<_, Option<i64>>(7)?,
                    ))
                })
                .context("querying member notices")?;
            let mut out = Vec::new();
            for row in rows {
                let (
                    id,
                    from_plugin,
                    from_role,
                    kind,
                    pointer_uri,
                    chain_hash,
                    queued_at,
                    in_reply_to,
                ) = row.context("reading member notice row")?;
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
                    in_reply_to: in_reply_to.map(|v| v as u64),
                });
            }
            out
        };
        tx.execute(
            "UPDATE member_notices SET drained_at = ?2
             WHERE to_plugin = ?1 AND drained_at IS NULL AND dest_peer IS NULL",
            params![to_plugin, now.to_rfc3339()],
        )
        .context("marking drained member notices")?;
        // The heartbeat: recorded whether or not the drain returned anything,
        // and in the same transaction as the delivery mark it accompanies.
        Self::touch_inbox(&tx, to_plugin, &now)?;
        tx.commit().context("committing member drain")?;
        Ok(notices)
    }

    /// Non-consuming list of a recipient's queued notices (oldest first) —
    /// the SessionStart surface: a new session PEEKS so mail survives a session
    /// that dies early; consume happens via drain when the member acts.
    ///
    /// Peeking counts as a sighting for the same reason draining does: the
    /// member reached for its own mailbox. A member that only ever peeks is
    /// still reachable.
    pub fn peek_member(&self, to_plugin: &str) -> Result<Vec<MemberNotice>> {
        let now = Utc::now();
        let cutoff = (now - chrono::Duration::seconds(INBOX_TTL_SECS)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        Self::touch_inbox(&conn, to_plugin, &now)?;
        let mut stmt = conn.prepare(
            "SELECT id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at,
                    in_reply_to
             FROM member_notices
             WHERE to_plugin = ?1 AND queued_at >= ?2 AND drained_at IS NULL
               AND dest_peer IS NULL ORDER BY id ASC",
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
                row.get::<_, Option<i64>>(7)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (id, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at, in_reply_to) =
                row?;
            out.push(MemberNotice {
                id: id as u64, from_plugin, from_role, kind, pointer_uri, chain_hash,
                queued_at: DateTime::parse_from_rfc3339(&queued_at)
                    .context("parsing member notice queued_at")?
                    .with_timezone(&Utc),
                in_reply_to: in_reply_to.map(|v| v as u64),
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
            "SELECT COUNT(*) FROM member_notices
              WHERE to_plugin = ?1 AND drained_at IS NULL AND dest_peer IS NULL",
            params![to_plugin],
            |row| row.get(0),
        )?;
        Ok(n as u64)
    }

    /// Notices involving `plugin` that nothing has bound a response to, older
    /// than `older_than_secs`, restricted to `kinds` (the kinds whose
    /// disposition IS a response — see `MEMBER_KINDS_EXPECTING_RESPONSE`).
    ///
    /// The honest name is **unanswered**, never "undelivered": a notice that
    /// was read and deliberately not answered is indistinguishable here from
    /// one that was never read. This query closes the loop for RESPONSIVENESS,
    /// not for ACTION — a member who woke, worked in a repo, and said nothing
    /// still shows up. Lookback is bounded by the TTL prune (7d).
    ///
    /// **Local plane only** (`dest_peer IS NULL`). An egress row's counterparty
    /// is on another machine, so a reply to it arrives as a *different* notice
    /// over the hub whose `in_reply_to` cannot reference this row's local id —
    /// it could never be bound, and would sit unanswered forever. That is the
    /// standing false-positive class `forum-note`/`coordination`/`handoff` are
    /// excluded to avoid, and it would land twice over: an egress row from a
    /// local member to a same-named remote one matches both `to_plugin` and
    /// `from_plugin`, so it would appear in `i_owe` AND `owed_to_me` at once.
    /// Cross-machine response debt is the hub's ledger, not this one's.
    pub fn member_unanswered(
        &self,
        plugin: &str,
        kinds: &[&str],
        older_than_secs: i64,
    ) -> Result<Vec<UnansweredNotice>> {
        if kinds.is_empty() {
            return Ok(Vec::new());
        }
        let before = (Utc::now() - chrono::Duration::seconds(older_than_secs)).to_rfc3339();
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let placeholders = (0..kinds.len())
            .map(|i| format!("?{}", i + 3))
            .collect::<Vec<_>>()
            .join(",");
        let sql = format!(
            "SELECT id, to_plugin, from_plugin, kind, pointer_uri, queued_at, drained_at
             FROM member_notices n
             WHERE (n.to_plugin = ?1 OR n.from_plugin = ?1)
               AND n.dest_peer IS NULL
               AND n.queued_at < ?2
               AND n.kind IN ({placeholders})
               AND NOT EXISTS (SELECT 1 FROM member_notices r WHERE r.in_reply_to = n.id)
             ORDER BY n.id ASC"
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut binds: Vec<&dyn rusqlite::ToSql> = vec![&plugin, &before];
        for k in kinds {
            binds.push(k);
        }
        let rows = stmt.query_map(binds.as_slice(), |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (id, to_plugin, from_plugin, kind, pointer_uri, queued_at, drained_at) = row?;
            out.push(UnansweredNotice {
                id: id as u64,
                to_plugin,
                from_plugin,
                kind,
                pointer_uri,
                queued_at: DateTime::parse_from_rfc3339(&queued_at)
                    .context("parsing unanswered queued_at")?
                    .with_timezone(&Utc),
                drained_at: match drained_at {
                    Some(d) => Some(
                        DateTime::parse_from_rfc3339(&d)
                            .context("parsing unanswered drained_at")?
                            .with_timezone(&Utc),
                    ),
                    None => None,
                },
            });
        }
        Ok(out)
    }
}

/// One notice awaiting hand-off to the fleet mesh (r6-routing branch 2).
///
/// `attempts` and `last_error` are what make this a queue rather than a second
/// black hole: an egress row that can fail forever without anyone learning is the
/// silent drop moved one hop out (Kimi, r6-routing review §2.4).
#[derive(Debug, Clone, serde::Serialize)]
pub struct EgressRow {
    pub id: u64,
    pub dest_peer: String,
    /// Roster-validated at enqueue. The drain forwards on THIS, not on the name —
    /// re-resolving a name at drain time reintroduces the prefix-matching oracle
    /// this design removed.
    pub dest_peer_lct: String,
    pub to_member: String,
    /// Always a LOCAL member: only local members can call `member_notify`, so the
    /// route-back for an egress failure is always local delivery. The one place
    /// this design is simpler than it looks.
    pub from_plugin: String,
    pub kind: String,
    pub pointer_uri: Option<String>,
    pub attempts: i64,
    pub last_error: Option<String>,
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
    /// The notice id this one answers, when the sender bound it.
    pub in_reply_to: Option<u64>,
}

/// What the daemon has on record about a member reading its own mailbox.
/// The evidence itself — never a verdict. Callers get the timestamps and the
/// count and may classify with whatever window fits their stakes
/// ([`Self::liveness`] is the default reading, not the only permitted one).
#[derive(Debug, Clone, serde::Serialize)]
pub struct InboxTouch {
    /// First time this member was ever seen reading its mailbox. Separates
    /// "watcher started five minutes ago" from "watcher ran for a week".
    pub first_seen: DateTime<Utc>,
    pub last_touch: DateTime<Utc>,
    /// How many mailbox reads are on record. A single touch is a one-shot
    /// manual read; thousands is a polling watcher. Different evidence.
    pub touches: u64,
}

impl InboxTouch {
    /// `live` if seen within `live_within_secs`, else `dormant`. Never
    /// `unknown` — that state is the *absence* of an `InboxTouch`, and keeping
    /// it unrepresentable here is the point: unknown means no row, and a row
    /// can only say how recently, never whether-at-all.
    pub fn liveness(&self, now: DateTime<Utc>, live_within_secs: i64) -> &'static str {
        if (now - self.last_touch).num_seconds() <= live_within_secs {
            "live"
        } else {
            "dormant"
        }
    }
}

/// One notice with nothing bound to it — the row the mesh could not produce
/// before 2026-07-25. `drained_at: None` means it was never even picked up;
/// `Some(_)` means it was delivered and went unanswered, which is a different
/// finding and must not be collapsed into the first.
#[derive(Debug, Clone, serde::Serialize)]
pub struct UnansweredNotice {
    pub id: u64,
    pub to_plugin: String,
    pub from_plugin: String,
    pub kind: String,
    pub pointer_uri: Option<String>,
    pub queued_at: DateTime<Utc>,
    pub drained_at: Option<DateTime<Utc>>,
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
                            "coordination", Some("forum/x.md#thread=t"), "hash-a", None)
            .unwrap();
        store
            .enqueue_member("codex-cli", "claude-code", "role:constellation:interactive-dev",
                            "handoff", None, "hash-b", None)
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

    /// The queue cap must not be a cross-member denial channel: a sender
    /// flooding member A's queue must not evict member B's mail, from a third
    /// party, that B has never read. This is the falsifier for
    /// atp-metabolism amendment 2 (Kimi/CBP 2026-07-25) — it FAILS against
    /// the global cap this replaced, because there the globally-oldest
    /// undrained row is exactly the quiet member's, and it goes first.
    ///
    /// The victim of the old policy left no mark: no error to the sender, no
    /// notice to the recipient, no chain entry. This test is the only place
    /// the channel is observable, which is the whole argument for it existing.
    #[test]
    fn a_flood_at_one_recipient_cannot_evict_a_third_members_mail() {
        let (_tmp, store) = fresh();
        // The quiet member's single unread notice, queued first — under the
        // global cap it is the globally-oldest undrained row and therefore
        // the first thing evicted.
        store
            .enqueue_member("codex-cli", "hub-supervisor", "role:r", "coordination",
                            Some("forum/quiet.md#t"), "hash-quiet", None)
            .unwrap();
        // A sender fills a DIFFERENT recipient's queue to the cap and past it.
        for i in 0..(MAX_INBOX_NOTICES + 5) {
            store
                .enqueue_member("kimi-code", "claude-code", "role:r", "coordination",
                                Some(&format!("forum/flood{i}.md#t")), "hash-flood", None)
                .unwrap();
        }
        assert_eq!(
            store.member_pending("codex-cli").unwrap(),
            1,
            "the quiet member's mail was evicted by a flood addressed to someone else"
        );
        let quiet = store.drain_member("codex-cli").unwrap();
        assert_eq!(quiet.len(), 1);
        assert_eq!(quiet[0].chain_hash, "hash-quiet", "wrong notice survived");
        // The cap still binds — on the flooded queue, where it belongs.
        assert_eq!(
            store.member_pending("kimi-code").unwrap(),
            MAX_INBOX_NOTICES,
            "the per-recipient cap must still bound the queue it applies to"
        );
        // And the drop is no longer silent: the member whose mail was dropped
        // can learn that it was, which is the only way the residual channel is
        // observable at all.
        assert_eq!(store.member_evictions("kimi-code").unwrap(), 5, "evictions uncounted");
        assert_eq!(
            store.member_evictions("codex-cli").unwrap(),
            0,
            "the untouched member must not inherit another queue's eviction count"
        );
    }

    /// The drain must stop returning a notice WITHOUT destroying the evidence
    /// that it was ever delivered — that deletion is what made "was this
    /// answered?" unaskable in the first place.
    #[test]
    fn drain_marks_rather_than_deletes_so_delivery_survives_the_wake() {
        let (_tmp, store) = fresh();
        let id = store
            .enqueue_member("kimi-code", "claude-code", "role:r", "reply",
                            Some("forum/a.md#t"), "hash-a", None)
            .unwrap();
        assert!(!store.drain_member("kimi-code").unwrap().is_empty());
        assert!(store.drain_member("kimi-code").unwrap().is_empty(), "consume-once holds");
        assert_eq!(store.member_pending("kimi-code").unwrap(), 0);
        // ...and the row is still there to be asked about.
        assert_eq!(
            store.member_notice_recipient(id).unwrap().as_deref(),
            Some("kimi-code")
        );
        let un = store.member_unanswered("kimi-code", &["reply"], -1).unwrap();
        assert_eq!(un.len(), 1);
        assert!(un[0].drained_at.is_some(), "delivered, then unanswered");
    }

    /// Binding a response clears the debt; the per-kind filter keeps the
    /// silently-actionable kinds out of the report entirely.
    #[test]
    fn unanswered_clears_on_binding_and_ignores_silent_kinds() {
        let (_tmp, store) = fresh();
        let asked = store
            .enqueue_member("kimi-code", "claude-code", "role:r", "review_request",
                            Some("pr/1"), "h1", None)
            .unwrap();
        store
            .enqueue_member("kimi-code", "claude-code", "role:r", "handoff",
                            Some("repo/state"), "h2", None)
            .unwrap();
        // handoff is legitimately silent — it must never appear.
        let counted: &[&str] = &["review_request", "reply"];
        let before = store.member_unanswered("kimi-code", counted, -1).unwrap();
        assert_eq!(before.len(), 1, "handoff is not an unanswered-report row");
        assert_eq!(before[0].id, asked);
        assert!(before[0].drained_at.is_none(), "never picked up");
        // Kimi answers it: the binding closes the row.
        store
            .enqueue_member("claude-code", "kimi-code", "role:r", "review_done",
                            Some("forum/verdict.md"), "h3", Some(asked))
            .unwrap();
        assert!(
            store.member_unanswered("kimi-code", counted, -1).unwrap().is_empty(),
            "a bound response clears the notice it answers"
        );
    }

    /// Both directions are visible to the party involved, and only that party.
    #[test]
    fn unanswered_is_self_scoped_in_both_directions() {
        let (_tmp, store) = fresh();
        store
            .enqueue_member("kimi-code", "claude-code", "role:r", "reply", None, "h1", None)
            .unwrap();
        store
            .enqueue_member("codex-cli", "thor", "role:r", "reply", None, "h2", None)
            .unwrap();
        let counted: &[&str] = &["reply"];
        let claude = store.member_unanswered("claude-code", counted, -1).unwrap();
        assert_eq!(claude.len(), 1, "sender sees its own unanswered send");
        assert_eq!(claude[0].to_plugin, "kimi-code");
        let kimi = store.member_unanswered("kimi-code", counted, -1).unwrap();
        assert_eq!(kimi.len(), 1, "recipient sees its own debt");
        // Neither sees the thor -> codex thread.
        for row in claude.iter().chain(kimi.iter()) {
            assert_ne!(row.from_plugin, "thor", "no cross-thread visibility");
        }
    }

    /// The load-bearing case for the whole liveness notion: the watcher polls
    /// on a cadence whether or not there is mail, so the sightings that prove a
    /// member reachable are almost all EMPTY drains. If an empty drain stayed a
    /// no-op, `dormant` and `unknown` would be indistinguishable for every
    /// member that happens not to have mail waiting.
    #[test]
    fn an_empty_drain_is_a_sighting() {
        let (_tmp, store) = fresh();
        // Never seen: no row at all. This — and only this — is the dead-letter
        // class. `thor` is the worked example: a fleet member with no local
        // watcher, addressed on the local mesh by mistake.
        assert!(store.inbox_touch("thor").unwrap().is_none());
        assert!(store.inbox_touch("kimi-code").unwrap().is_none());

        // An empty drain — the overwhelmingly common poll — is evidence.
        assert!(store.drain_member("kimi-code").unwrap().is_empty());
        let seen = store.inbox_touch("kimi-code").unwrap().expect("sighting kept");
        assert_eq!(seen.touches, 1);
        assert_eq!(seen.liveness(Utc::now(), 300), "live");
        // The member with no watcher is still unknown: draining one member's
        // mailbox says nothing about another's.
        assert!(store.inbox_touch("thor").unwrap().is_none(), "no cross-member liveness");

        // Peeking counts too, and sightings accumulate (one touch is a manual
        // read; a thousand is a polling watcher — different evidence).
        store.peek_member("kimi-code").unwrap();
        let seen = store.inbox_touch("kimi-code").unwrap().unwrap();
        assert_eq!(seen.touches, 2);
        assert!(seen.first_seen <= seen.last_touch);
    }

    /// `dormant` is seen-before-not-lately, and it is NOT a failure: a watcher
    /// that is down is exactly the case queueing exists for. The classifier
    /// must separate it from `unknown` on evidence, not on recency alone.
    #[test]
    fn dormant_is_distinguishable_from_never_seen() {
        let (_tmp, store) = fresh();
        store.drain_member("kimi-code").unwrap();
        let seen = store.inbox_touch("kimi-code").unwrap().unwrap();
        // Same row, read with a window narrower than its age: dormant.
        assert_eq!(seen.liveness(seen.last_touch + chrono::Duration::seconds(9), 5), "dormant");
        assert_eq!(seen.liveness(seen.last_touch + chrono::Duration::seconds(9), 300), "live");
        // A dormant member is still a member. `unknown` is the absence of the
        // row, which no window can produce.
        assert!(store.inbox_touch("codex-cli").unwrap().is_none());
    }

    /// A pre-id-binding inbox.db must upgrade in place, not fail to open.
    #[test]
    fn member_schema_migrates_from_the_pre_binding_shape() {
        let tmp = tempdir().unwrap();
        let path = tmp.path().join("inbox.db");
        {
            let store = SqliteInboxStore::open(&path, [7u8; 32]).unwrap();
            let conn = store.conn.lock().unwrap();
            conn.execute_batch("DROP TABLE IF EXISTS member_notices").unwrap();
            // The exact shape shipped before 2026-07-25.
            conn.execute_batch(
                "CREATE TABLE member_notices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, to_plugin TEXT NOT NULL,
                    from_plugin TEXT NOT NULL, from_role TEXT NOT NULL, kind TEXT NOT NULL,
                    pointer_uri TEXT, chain_hash TEXT NOT NULL, queued_at TEXT NOT NULL);",
            )
            .unwrap();
            conn.execute(
                "INSERT INTO member_notices
                    (to_plugin, from_plugin, from_role, kind, pointer_uri, chain_hash, queued_at)
                 VALUES ('kimi-code','claude-code','role:r','reply','p','h',?1)",
                params![Utc::now().to_rfc3339()],
            )
            .unwrap();
        }
        let store = SqliteInboxStore::open(&path, [7u8; 32]).unwrap();
        // The legacy row is pending (drained_at NULL) and queryable under the new columns.
        assert_eq!(store.member_pending("kimi-code").unwrap(), 1);
        let drained = store.drain_member("kimi-code").unwrap();
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[0].in_reply_to, None);
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
