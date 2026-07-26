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

/// Egress-plane admission cap (r6-routing branch 2). Deliberately its own bound
/// and deliberately much smaller than the local cap: a forward is parked for a
/// drain that runs on a 20s tick against a hub that may be down, so a queue this
/// deep already means the forwarding plane is not working and the honest answer
/// is to tell the next sender so. Enforced by REFUSING admission, never by
/// eviction — see [`InboxStore::enqueue_egress`] for why that asymmetry is not
/// arbitrary.
pub(crate) const MAX_EGRESS_QUEUE: u64 = 200;

/// Per-destination egress cap (S1, CBP 2026-07-26). [`MAX_EGRESS_QUEUE`] above is
/// a RESOURCE bound and is correctly plane-wide. It was also, until this constant,
/// the only bound — so it was doing a second job it cannot do: STALL ISOLATION.
///
/// Those are different questions. "Is this box holding too much undelivered mail?"
/// is about the box, and every parked forward counts. "Is one peer's stall eating
/// everyone else's capacity?" is about a peer, and only that peer's rows count.
/// One predicate answered the first and was read as answering the second, so a
/// single wedged peer accumulating 200 parked forwards refused admission for EVERY
/// peer — a fleet-wide coordination outage sourced from one dead link. (Local
/// member-to-member mail is untouched: that is [`MAX_INBOX_NOTICES`], a separate
/// count on a separate predicate. The failure is "the mesh is down", not "the boxes
/// stop" — McNugget's scope refinement, and the reason the local plane remains a
/// working channel through which to report the egress refusal.)
///
/// Set well below the plane-wide bound on purpose: at 50, a peer that is wedged
/// solid consumes at most a quarter of the plane, so three more peers can wedge
/// before the resource bound is even in play. The retirement seam
/// (`MAX_EGRESS_ATTEMPTS` → retire → report home) then reclaims the stalled rows,
/// which is what downgrades this from terminal to transient — but a bound that
/// only releases on retirement still needs to not take the whole plane hostage in
/// the meantime.
pub(crate) const MAX_EGRESS_QUEUE_PER_PEER: u64 = 50;

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
        // The forwarding plane carries its OWN bound, because it no longer borrows
        // the local plane's (see `enqueue_member`: the TTL prune and the cap used to
        // reach across the seam and delete queued forwards). A bound that EVICTS
        // needs a report path to stay honest, and on this branch the egress seam has
        // none — no `mark_egress_failed`, no attempt counter, nothing that can say a
        // forward was dropped. So this bound REFUSES ADMISSION instead: the caller is
        // live, holds the receipt, and learns immediately. Backpressure to a present
        // sender is attributable; eviction of a parked row is the black hole.
        let queued: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices
              WHERE dest_peer IS NOT NULL AND drained_at IS NULL",
            [],
            |row| row.get(0),
        )?;
        if queued as u64 >= MAX_EGRESS_QUEUE {
            anyhow::bail!(
                "egress queue full ({queued}/{MAX_EGRESS_QUEUE} undrained forwards) — \
                 refusing admission rather than evicting a queued forward"
            );
        }
        // S1. The count above is the RESOURCE bound and is right to be plane-wide.
        // This one is the STALL bound and has to name the peer, because the two
        // questions have different answers: one wedged peer holding 200 parked
        // forwards is not a reason to refuse mail to a peer that is answering
        // fine. Without this clause it was — every forward to every peer, refused
        // by one dead link, with the refusal correctly reporting a full plane and
        // saying nothing about which peer filled it.
        let queued_peer: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices
              WHERE dest_peer = ?1 AND drained_at IS NULL",
            params![dest_peer],
            |row| row.get(0),
        )?;
        if queued_peer as u64 >= MAX_EGRESS_QUEUE_PER_PEER {
            // Names the peer, so the receipt distinguishes "this box is full" from
            // "this one peer is not draining" — the distinction the single bound
            // could not express, and the one an operator acts on.
            anyhow::bail!(
                "egress queue full for peer '{dest_peer}' \
                 ({queued_peer}/{MAX_EGRESS_QUEUE_PER_PEER} undrained forwards to that \
                 peer; the plane as a whole is at {queued}/{MAX_EGRESS_QUEUE}) — \
                 refusing admission for this destination only. Forwards to other peers \
                 are unaffected: this is one stalled link, not a full forwarding plane."
            );
        }
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

    /// Undrained forwards currently parked on the egress plane — the number the
    /// admission bound in [`Self::enqueue_egress`] tests. Exposed so a caller can
    /// report the queue depth without provoking the refusal.
    ///
    /// Plane-wide on purpose: this is the resource bound's view. The per-peer
    /// stall question is [`Self::egress_queued_for`] (S1) — two different
    /// questions that were one predicate before the graft.
    pub fn egress_queued_for(&self, dest_peer: &str) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices
              WHERE dest_peer = ?1 AND drained_at IS NULL",
            params![dest_peer],
            |row| row.get(0),
        )?;
        Ok(n as u64)
    }

    /// Undrained forwards parked on the egress plane as a whole — see
    /// [`Self::egress_queued_for`] for the per-peer count the stall bound tests.
    pub fn egress_queued(&self) -> Result<u64> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let n: i64 = conn.query_row(
            "SELECT COUNT(*) FROM member_notices
              WHERE dest_peer IS NOT NULL AND drained_at IS NULL",
            [],
            |row| row.get(0),
        )?;
        Ok(n as u64)
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
        // `dest_peer IS NULL` = the LOCAL plane. Every statement in this function
        // carries it, because without it a local send reaches across the seam:
        // this prune DELETED queued forwards (hard, no mark, no report, so branch 4
        // can never speak for them), and the cap below evicted them. Both were
        // triggered by traffic between two OTHER members — the forward's sender and
        // recipient are not parties to the send that destroys it. The forwarding
        // plane's own bound lives in `enqueue_egress`.
        // The predicate is `local OR already-forwarded`, not `local` (McNugget T2 on
        // `17a928d`). Scoping the prune to the local plane fixed B1 but took the whole
        // forwarding plane out of the retention policy, including rows that had already
        // been delivered — so `member_notices` grew without bound on any forwarding
        // node, keeping every forward ever made, forever. Only the PARKED part of the
        // plane needs protecting: a queued forward has `drained_at IS NULL`, so it still
        // survives every local send (B1 stays fixed), while a completed one ages out at
        // the same 7d as local mail, which is the behaviour before branch 2 existed.
        //
        // This does NOT give the parked plane an expiry — nothing here can reclaim an
        // undrained forward, and that is T1, which is deliberately not fixed by widening
        // this predicate. An age-based DELETE of a parked forward is exactly the silent
        // loss `dest_peer IS NULL` was added to stop; retiring one honestly needs the
        // report path (attempt counter → dead-letter → report home). In this graft that
        // path is present: `retire_egress` sets `drained_at`, which drops the retired row
        // out of the admission count immediately and hands it to THIS prune at 7d. That
        // is the joint between the two branches — each closes the other's open end
        // through a field neither author coordinated on. T1 is closed by retirement, not
        // by widening this predicate, and the tripwire test below asserts exactly that.
        conn.execute(
            "DELETE FROM member_notices
              WHERE queued_at < ?1 AND (dest_peer IS NULL OR drained_at IS NOT NULL)",
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
        // was scoped to close, reopened across the local/remote seam instead of
        // across recipients.
        //
        // And worse attributed than the original channel: the eviction counter
        // below books the loss under the LOCAL id `m`, so the forensics name a
        // member that was never a party to the send that destroyed the row.
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
    ///
    /// For a row on the FORWARDING plane this returns the ROUTED address
    /// (`peer/member`), not the bare remote member id. An egress row bound for
    /// `thor/claude-code` stores `to_plugin = 'claude-code'`, so returning the bare
    /// column let a local member named `claude-code` bind `in_reply_to` to it and be
    /// told `binding_verified: true` — a witnessed claim to have answered mail
    /// addressed to a different machine. Returning the routed form makes the
    /// caller's equality test fail and its error name the real addressee. Returning
    /// `None` would have been wrong for the reason the paragraph above gives: a
    /// forward is not *unverifiable*, it is verifiably someone else's.
    pub fn member_notice_recipient(&self, id: u64) -> Result<Option<String>> {
        let conn = self.conn.lock().unwrap();
        Self::ensure_member_schema(&conn)?;
        let mut stmt =
            conn.prepare("SELECT to_plugin, dest_peer FROM member_notices WHERE id = ?1")?;
        let mut rows = stmt.query(params![id as i64])?;
        Ok(match rows.next()? {
            Some(row) => {
                let to_plugin: String = row.get(0)?;
                Some(match row.get::<_, Option<String>>(1)? {
                    Some(peer) => format!("{peer}/{to_plugin}"),
                    None => to_plugin,
                })
            }
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
        // `dest_peer IS NULL` here is load-bearing twice over. This UPDATE is broader
        // than the SELECT above (no `queued_at` cutoff), so unfiltered ONE local drain
        // by member `m` marked EVERY parked forward bound for a remote `m` — including
        // rows older than the TTL that the SELECT never returned and nobody was ever
        // shown. And `drained_at` is the exact predicate `pending_egress` reads as
        // "already handed to the fleet mesh", so the mark did not merely mislabel the
        // rows, it cancelled the forwards: accepted, witnessed, enqueued, never sent,
        // never reported, success code — the black hole this branch was built to close,
        // reconstituted one plane up.
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
    ///
    /// `dest_peer IS NULL` matters even though a peek consumes nothing: this is the
    /// SessionStart surface, so without it a local member's session opened holding
    /// the `kind`, `pointer_uri` and `from_plugin` of mail addressed to a member on
    /// another machine. Disclosure needs no drain. README §7.3 is why speculative
    /// forwarding was kept out of v1; the name collision got there without it.
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
               AND dest_peer IS NULL
             ORDER BY id ASC",
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
    ///
    /// Local plane only: this count is what decides whether to WAKE a member, and a
    /// parked forward bound for `peer/m` is not work for local `m`. Unfiltered, a
    /// forward woke the wrong member — which is also how it got consumed, since the
    /// session that was woken then drained.
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
    /// **Local plane only, and this one is not symmetry for its own sake.** The
    /// clearing condition is "some row binds `in_reply_to = n.id`", and for a
    /// forward that condition is UNSATISFIABLE BY CONSTRUCTION: the answering party
    /// is on another machine, `enqueue_egress` carries no `in_reply_to` column to
    /// bind across the seam, and the reply arrives as a watcher FIRE, never as a
    /// local row. Unfiltered, every forward entered its sender's `owed_to_me` and
    /// could never leave — the tool whose job is measuring responsiveness accusing
    /// the fleet of never answering, once per forward, forever. Excluding forwards
    /// makes it silent about them instead of permanently wrong about them; a real
    /// unanswered-forward report needs a far-end evidence channel, and this thread's
    /// finding is that no such channel exists yet (the substrate is negative-only).
    ///
    /// It would also land twice over: an egress row from a local member to a
    /// same-named remote one matches both `to_plugin` and `from_plugin`, so it
    /// would appear in `i_owe` AND `owed_to_me` at once. Cross-machine response
    /// debt is the hub's ledger, not this one's.
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

    /// Row-level probes for the retention tests. `pending_egress` is not usable for
    /// these: it filters on `drained_at IS NULL`, so a DELIVERED row and a DELETED one
    /// are indistinguishable through it — which is exactly the confusion T2 hid in.
    fn row_exists(store: &SqliteInboxStore, id: u64) -> bool {
        store
            .conn
            .lock()
            .unwrap()
            .query_row("SELECT COUNT(*) FROM member_notices WHERE id = ?1",
                       params![id as i64], |r| r.get::<_, i64>(0))
            .unwrap()
            > 0
    }

    fn count_rows(store: &SqliteInboxStore) -> i64 {
        store
            .conn
            .lock()
            .unwrap()
            .query_row("SELECT COUNT(*) FROM member_notices", [], |r| r.get(0))
            .unwrap()
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

    // ---- the local plane must not see the forwarding plane (r6-routing B1) -------
    //
    // `enqueue_egress` stores the REMOTE member id in `to_plugin` with `dest_peer`
    // alongside, so every local-plane query that keys on `to_plugin` alone matched
    // forwards too. `claude-code` and `kimi-code` are the two most common member ids
    // in the fleet, which makes `peer/claude-code` — the address the proposal's own
    // §3 test used — the default case, not a corner. Each test below fails against
    // the unfiltered statement it names.

    /// The whole of B1 in one sequence: a forward must be invisible to the local
    /// member that shares its name, on every local surface, and must SURVIVE that
    /// member's drain still pending on the egress plane.
    #[test]
    fn a_forward_is_not_local_mail_for_the_member_that_shares_its_name() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/for-thor.md#thread=t"), "hash-egress")
            .unwrap();
        let local = store
            .enqueue_member("claude-code", "kimi-code", "role:r", "coordination",
                            Some("forum/for-me.md#thread=t"), "hash-local", None)
            .unwrap();
        // The wake decision, the SessionStart disclosure, and the drain: one row each.
        assert_eq!(store.member_pending("claude-code").unwrap(), 1,
                   "the forward woke the local member");
        let peeked = store.peek_member("claude-code").unwrap();
        assert_eq!(peeked.len(), 1, "SessionStart disclosed another machine's mail");
        assert_eq!(peeked[0].id, local);
        let drained = store.drain_member("claude-code").unwrap();
        assert_eq!(drained.len(), 1, "the local member consumed the forward");
        assert_eq!(drained[0].chain_hash, "hash-local");
        // ...and the forward is still there, still pending, still going to Thor.
        let pending = store.pending_egress(25).unwrap();
        assert_eq!(pending.len(), 1, "the local drain cancelled the forward");
        assert_eq!(pending[0].id, egress);
        assert_eq!(pending[0].dest_peer, "thor");
    }

    /// `drain_member`'s UPDATE is broader than its SELECT (no `queued_at` cutoff),
    /// so one local drain used to mark EVERY forward bound for a remote member of
    /// the same name — including rows the SELECT never returned and nobody saw.
    /// Mass cancel, no log line. Falsifier for the UPDATE specifically: the SELECT
    /// fix alone still fails this.
    #[test]
    fn one_local_drain_cannot_cancel_every_forward_of_that_name() {
        let (_tmp, store) = fresh();
        for peer in ["thor", "mcnugget", "legion"] {
            store
                .enqueue_egress(peer, &format!("lct:{peer}"), "kimi-code", "claude-code", "role:r", "review_done",
                                Some("forum/x.md#thread=t"), "hash-e")
                .unwrap();
        }
        // An empty drain is enough — the UPDATE does not depend on the SELECT.
        assert!(store.drain_member("kimi-code").unwrap().is_empty());
        assert_eq!(store.pending_egress(25).unwrap().len(), 3,
                   "an empty local drain marked the forwards handed to the mesh");
    }

    /// Two paths DELETED forwards outright — a hard loss with no mark and no report,
    /// so branch 4 can never speak for them. Both are triggered by traffic between
    /// two OTHER members: neither the forward's sender nor its recipient is a party
    /// to the send that destroys it.
    #[test]
    fn a_local_send_cannot_delete_a_parked_forward() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/for-thor.md#thread=t"), "hash-egress")
            .unwrap();
        // Path 1 — the cap. Local `claude-code` is flooded past MAX_INBOX_NOTICES by
        // a third party; the eviction takes MIN(id), and the forward is id 1.
        for i in 0..(MAX_INBOX_NOTICES + 3) {
            store
                .enqueue_member("claude-code", "hub-supervisor", "role:r", "coordination",
                                Some(&format!("forum/f{i}.md#t")), "hash-flood", None)
                .unwrap();
        }
        assert_eq!(store.pending_egress(25).unwrap().len(), 1,
                   "a flood at the local member of the same name deleted the forward");
        assert_eq!(store.pending_egress(25).unwrap()[0].id, egress);
        // The eviction ledger must not book the loss under the local id either: the
        // count is the only trace an eviction leaves, and 3 evictions of local mail
        // is a different fact from 4 with a forward among them.
        assert_eq!(store.member_evictions("claude-code").unwrap(), 3);
    }

    /// Path 2 — the TTL prune, which runs on EVERY local enqueue and had no
    /// `dest_peer` clause at all. The row has to be aged past `INBOX_TTL_SECS` for
    /// the prune to reach it, which is the whole point: `pending_egress` has no TTL
    /// filter of its own, so a forward that has been waiting on a down hub longer
    /// than a week was deleted — hard, no mark, nothing branch 4 could report on — by
    /// the next unrelated local send. (Written this way because the first version of
    /// this test used fresh rows and passed against the unfiltered statement: the
    /// mutation check caught it, the assertion did not.)
    #[test]
    fn an_aged_forward_survives_the_local_ttl_prune() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/for-thor.md#thread=t"), "hash-egress")
            .unwrap();
        let stale = (Utc::now() - chrono::Duration::seconds(INBOX_TTL_SECS + 3600)).to_rfc3339();
        store
            .conn
            .lock()
            .unwrap()
            .execute("UPDATE member_notices SET queued_at = ?1 WHERE id = ?2",
                     params![stale, egress as i64])
            .unwrap();
        assert_eq!(store.pending_egress(25).unwrap().len(), 1, "setup: still queued");
        // A send between two OTHER members — neither the forward's sender nor its
        // recipient is a party to it.
        store
            .enqueue_member("codex-cli", "kimi-code", "role:r", "coordination",
                            Some("forum/unrelated.md#t"), "hash-u", None)
            .unwrap();
        assert_eq!(store.pending_egress(25).unwrap().len(), 1,
                   "an unrelated local send deleted the aged forward");
        assert_eq!(store.pending_egress(25).unwrap()[0].id, egress);
    }

    /// The counterpart to the test above, and the reason the prune's predicate is
    /// `local OR already-forwarded` rather than `local` (McNugget T2). Scoping the
    /// prune to the local plane protected PARKED forwards, which was the point, but
    /// it also exempted DELIVERED ones — so a forwarding node kept every forward it
    /// ever made, forever.
    ///
    /// Note what this pins that the sibling test cannot: both tests park an aged row
    /// and assert about the prune, and the sibling passes under BOTH predicates, so it
    /// alone does not distinguish them. The discriminator is `drained_at`.
    #[test]
    fn an_aged_delivered_forward_is_reclaimed_by_the_ttl_prune() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/for-thor.md#thread=t"), "hash-egress")
            .unwrap();
        // Delivered, unlike the sibling test: this is the whole difference.
        store.mark_egress_forwarded(egress).unwrap();
        let stale = (Utc::now() - chrono::Duration::seconds(INBOX_TTL_SECS + 3600)).to_rfc3339();
        store
            .conn
            .lock()
            .unwrap()
            .execute("UPDATE member_notices SET queued_at = ?1 WHERE id = ?2",
                     params![stale, egress as i64])
            .unwrap();
        assert_eq!(count_rows(&store), 1, "setup: the delivered forward is retained");
        // Any local send runs the prune.
        store
            .enqueue_member("codex-cli", "kimi-code", "role:r", "coordination",
                            Some("forum/unrelated.md#t"), "hash-u", None)
            .unwrap();
        assert!(
            !row_exists(&store, egress),
            "a delivered forward aged past the TTL was never reclaimed — \
             member_notices grows without bound on a forwarding node"
        );
    }

    /// T1, CONVERTED. Thor pinned this on `2b70394` as a known gap whose doc said:
    /// "will fail the moment a retirement path exists — at which point it should be
    /// replaced by the assertion that the path works, NOT deleted." The graft is that
    /// moment, so this is that replacement, and it now asserts the joint end to end.
    ///
    /// The half that must NOT change: no age-based `DELETE` may reach a parked
    /// forward. That was B1, and widening the prune is still the wrong fix — an
    /// age-based DELETE of an undelivered forward is exactly the silent loss this
    /// exploration exists to remove.
    ///
    /// The half that is new: a parked forward is no longer immortal either. It is
    /// reclaimed through a path that OWES A REPORT at every step — `expired_egress`
    /// hands the id to a caller who must report home, `retire_egress` then sets
    /// `drained_at`, and only then does Thor's T2 prune (`local OR already-drained`)
    /// reclaim the storage. Neither branch could do this alone: the WIP supplies the
    /// retirement seam, Thor supplies the predicate that reclaims what it retires,
    /// and `drained_at` is the field neither author coordinated on.
    #[test]
    fn t1_a_parked_forward_is_reclaimed_only_through_the_reporting_path() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/for-thor.md#thread=t"), "hash-egress")
            .unwrap();
        let ancient = (Utc::now() - chrono::Duration::days(400)).to_rfc3339();
        store
            .conn
            .lock()
            .unwrap()
            .execute("UPDATE member_notices SET queued_at = ?1 WHERE id = ?2",
                     params![ancient, egress as i64])
            .unwrap();

        // 1. Still no silent expiry. Local sends run the prune; the parked forward
        //    survives all of them, however old it is. This is B1, still fixed.
        for i in 0..3 {
            store
                .enqueue_member("codex-cli", "kimi-code", "role:r", "coordination",
                                Some("forum/unrelated.md#t"), &format!("hash-{i}"), None)
                .unwrap();
        }
        assert!(
            row_exists(&store, egress),
            "an unrelated local send silently deleted a parked forward — B1 has regressed"
        );

        // 2. But it IS visible to the path that owes a report. This is what closes
        //    T1: the row surfaces to a caller, not to a DELETE.
        let expired = store.expired_egress(60, 25).unwrap();
        assert!(expired.contains(&egress),
                "the reporting path cannot see the row it is supposed to retire — T1 is open");

        // 3. Retirement marks it drained. The row leaves the admission count
        //    IMMEDIATELY, which is what downgrades S1's stall from terminal to
        //    transient.
        let before = store.egress_queued_for("thor").unwrap();
        store.retire_egress(egress).unwrap();
        assert_eq!(store.egress_queued_for("thor").unwrap(), before - 1,
                   "a retired row still occupies its peer's admission budget");
        assert_eq!(store.egress_queued().unwrap(), 0,
                   "a retired row still occupies the plane's admission budget");

        // 4. …and only NOW may storage be reclaimed, by Thor's T2 predicate. The
        //    same local send that was harmless in step 1 collects it in step 4.
        //    That difference is the joint: `drained_at` is what makes the delete
        //    legitimate, and it is set by the seam that reported home.
        store
            .enqueue_member("codex-cli", "kimi-code", "role:r", "coordination",
                            Some("forum/unrelated.md#t"), "hash-final", None)
            .unwrap();
        assert!(
            !row_exists(&store, egress),
            "a RETIRED forward aged past the TTL was never reclaimed — member_notices \
             grows without bound on a forwarding node (Thor T2)"
        );
    }

    /// A local member must not be able to claim it answered mail addressed to a
    /// member on another machine. `member_notice_recipient` returned the bare
    /// `to_plugin`, so `claude-code` binding `in_reply_to` to a forward for
    /// `thor/claude-code` was told `binding_verified: true` and the claim was
    /// witnessed. The routed form makes the caller's equality test fail — and,
    /// deliberately, does NOT return `None`: a forward is not unverifiable, it is
    /// verifiably someone else's.
    #[test]
    fn a_forwards_reply_binding_names_the_routed_addressee() {
        let (_tmp, store) = fresh();
        let egress = store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "reply",
                            Some("forum/x.md#thread=t"), "hash-e")
            .unwrap();
        assert_eq!(
            store.member_notice_recipient(egress).unwrap().as_deref(),
            Some("thor/claude-code"),
            "a local member of the same name could bind to another machine's mail"
        );
        let local = store
            .enqueue_member("claude-code", "kimi-code", "role:r", "reply",
                            Some("forum/y.md#t"), "hash-l", None)
            .unwrap();
        assert_eq!(store.member_notice_recipient(local).unwrap().as_deref(),
                   Some("claude-code"), "local rows keep the bare id");
    }

    /// `member_unanswered`'s clearing condition — some row binds
    /// `in_reply_to = n.id` — is unsatisfiable for a forward: the answering party is
    /// on another machine, `enqueue_egress` has no `in_reply_to` column, and the
    /// reply arrives as a watcher fire rather than a local row. So an unfiltered
    /// query accused the fleet of never answering, once per forward, forever.
    #[test]
    fn a_forward_cannot_poison_its_senders_unanswered_report() {
        let (_tmp, store) = fresh();
        store
            .enqueue_egress("thor", "lct:thor", "claude-code", "codex-cli", "role:r", "review_done",
                            Some("forum/x.md#thread=t"), "hash-e")
            .unwrap();
        // `-1` = "older than one second in the future", i.e. include everything.
        let owed = store.member_unanswered("codex-cli", &["review_done"], -1).unwrap();
        assert!(owed.is_empty(), "the forward entered owed_to_me and can never leave");
        // The local plane still reports, or the filter would have bought silence.
        store
            .enqueue_member("kimi-code", "codex-cli", "role:r", "review_done",
                            Some("forum/y.md#t"), "hash-l", None)
            .unwrap();
        assert_eq!(store.member_unanswered("codex-cli", &["review_done"], -1).unwrap().len(), 1);
    }

    /// Removing the local plane's (wrong) bound from the egress plane leaves the
    /// egress plane unbounded, which is Kimi's §4. Its replacement REFUSES admission
    /// rather than evicting, because eviction needs a report path and this branch's
    /// egress seam has none — no `mark_egress_failed`, no attempt counter. The
    /// refused sender is live and holds the receipt; an evicted parked row is not.
    #[test]
    fn the_egress_plane_carries_its_own_bound_and_it_refuses_rather_than_evicts() {
        let (_tmp, store) = fresh();
        // Fill the plane to its RESOURCE bound without tripping the per-peer STALL
        // bound (S1). That takes several peers now; before S1 one peer could fill
        // the whole plane alone, which was exactly the defect.
        let peers = MAX_EGRESS_QUEUE / MAX_EGRESS_QUEUE_PER_PEER;
        let mut first = 0u64;
        for p in 0..peers {
            let peer = format!("peer{p}");
            for i in 0..MAX_EGRESS_QUEUE_PER_PEER {
                let id = store
                    .enqueue_egress(&peer, &format!("lct:{peer}"), "claude-code", "codex-cli",
                                    "role:r", "reply", Some(&format!("forum/f{p}-{i}.md#t")),
                                    "hash-e")
                    .unwrap();
                if p == 0 && i == 0 {
                    first = id;
                }
            }
        }
        assert_eq!(store.egress_queued().unwrap(), MAX_EGRESS_QUEUE);
        // A peer with NOTHING queued is still refused — the plane-wide bound is a
        // statement about this box's capacity, not about that peer.
        let refused = store.enqueue_egress("fresh-peer", "lct:fresh", "claude-code", "codex-cli",
                                           "role:r", "reply", Some("forum/over.md#t"), "hash-o");
        assert!(refused.is_err(), "the egress plane admitted past its cap");
        // The oldest forward is still queued: at the bound we tell the newest sender
        // no, we do not silently destroy the oldest sender's packet.
        assert_eq!(store.pending_egress(1).unwrap()[0].id, first);
        assert_eq!(store.egress_queued().unwrap(), MAX_EGRESS_QUEUE);
        // And the bound is the EGRESS plane's: local mail is unaffected by a full
        // egress queue, which is the same seam this whole block is about.
        store
            .enqueue_member("claude-code", "kimi-code", "role:r", "coordination",
                            Some("forum/local.md#t"), "hash-l", None)
            .unwrap();
        assert_eq!(store.member_pending("claude-code").unwrap(), 1);
    }

    /// S1 (CBP, 2026-07-26). The admission bound was plane-wide only, so it did
    /// resource protection correctly and stall isolation not at all: one peer that
    /// stopped draining accumulated parked forwards until the WHOLE plane was at
    /// its cap, and from then on every send to every OTHER peer was refused. One
    /// dead link, fleet-wide coordination outage.
    ///
    /// Falsifier for the per-peer clause specifically: wedge one peer solid, then
    /// send to a different one. Pre-S1 the second send fails; it must not.
    #[test]
    fn one_wedged_peer_does_not_refuse_admission_for_every_other_peer() {
        let (_tmp, store) = fresh();
        for i in 0..MAX_EGRESS_QUEUE_PER_PEER {
            store
                .enqueue_egress("wedged", "lct:wedged", "claude-code", "codex-cli", "role:r",
                                "reply", Some(&format!("forum/w{i}.md#t")), "hash-w")
                .unwrap();
        }
        assert_eq!(store.egress_queued_for("wedged").unwrap(), MAX_EGRESS_QUEUE_PER_PEER);
        // That peer is now refused, and the refusal names it rather than the plane.
        let refused = store.enqueue_egress("wedged", "lct:wedged", "claude-code", "codex-cli",
                                           "role:r", "reply", Some("forum/w-over.md#t"), "hash-wo");
        let msg = refused.unwrap_err().to_string();
        assert!(msg.contains("wedged"),
                "the refusal must name the stalled peer, not just report a full plane: {msg}");
        // …and a healthy peer is completely unaffected. This is the assertion that
        // fails without the `dest_peer = ?1` clause.
        store
            .enqueue_egress("healthy", "lct:healthy", "claude-code", "codex-cli", "role:r",
                            "reply", Some("forum/h.md#t"), "hash-h")
            .expect("one stalled peer refused admission to an unrelated, draining peer");
        assert_eq!(store.egress_queued_for("healthy").unwrap(), 1);
        // The plane-wide bound is untouched by all this: it is still the resource
        // question, and the plane is nowhere near full.
        assert!(store.egress_queued().unwrap() < MAX_EGRESS_QUEUE);
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
