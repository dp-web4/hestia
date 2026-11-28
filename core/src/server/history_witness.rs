//! `history_witness` v1 — hestia witnesses an entity's append-only JSONL logs (entity accounts
//! S2a; schema agreed in shared-context/forum
//! `legion-to-mcnugget-entity-accounts-witness-entry-schema-2026-11-28.md` and its ack
//! `mcnugget-to-legion-entity-accounts-witness-schema-ack-2026-11-28.md`).
//!
//! One chain row per witnessed log record, on this daemon's chain, under the existing row
//! framing and signature (`hestia:chain-entry-signature:v1`) — nothing new on the chain side.
//! `event_type = "history_witness"`, `event_data`:
//!
//! | field | rule |
//! |---|---|
//! | `schema` | `"hestia:history-witness:v1"` |
//! | `entity_lct` | the entity that owns the log — from the SESSION, never an argument |
//! | `log_name` | one of [`LOG_NAMES`]; closed in v1, a new log is a v2 change |
//! | `seq` | the log's own 0-based record index; hestia keeps no counter of its own |
//! | `entry_sha256` | lowercase hex64, sha256 of the record's line without its LF |
//! | `prev_sha256` | `entry_sha256` of `seq-1`; 64 zeros at `seq = 0` |
//! | `caller_uid` | `null` until the SO_PEERCRED listener (#954) |
//! | `caller_basis` | `"token"` today: the session token was held, nothing about the uid |
//!
//! The append rules, which [`decide`] holds without a daemon:
//!
//! - **The first witness for a log is `seq = 0`.** A first witness at K > 0 is a
//!   [`code::GAP`]: a verifier could not see a rewrite below K.
//! - **Otherwise `seq` is `last + 1`**, else [`code::GAP`] (a gap is an unwitnessed append).
//! - **`prev_sha256` must equal the witnessed `seq-1`'s `entry_sha256`** (zeros at 0), else
//!   [`code::FORK`].
//! - **A repeat is idempotent**: the same `(log_name, seq, entry_sha256, prev_sha256)` returns
//!   the existing row and appends nothing. The same `seq` with a different hash is a
//!   [`code::FORK`].
//! - **Every refusal is its own chain row** ([`REFUSED_EVENT`]), carrying the code and the
//!   offered fields: a refused rewrite is evidence, not a dropped call.
//!
//! **Contiguity is the invariant everything leans on.** Because a row lands only at `0` or at
//! `last + 1`, the witnessed seqs of one `(entity, log)` are always exactly `0..=L`. So "is
//! `seq-1` witnessed" is the whole of the `last + 1` test, and `L` itself is found by a
//! galloping search over the per-seq idempotency keys ([`last_witnessed`]) instead of a scan of
//! a 100k-row chain or an in-RAM index that would need rehydrating after a restart.
//!
//! Each witness row is bound to a durable chain event key ([`event_key`]), so the lookup is an
//! indexed read of `chain_event_keys`, and a crash between the check and the reply cannot land
//! a second row for the same seq.

use crate::storage::chain::ChainEntry;
use serde_json::{Value, json};

pub const SCHEMA: &str = "hestia:history-witness:v1";
/// A witnessed log record. Reserved: `hestia_request_witness` cannot forge it.
pub const WITNESS_EVENT: &str = "history_witness";
/// A refused offer. Reserved, for the same reason.
pub const REFUSED_EVENT: &str = "history_witness_refused";
/// The closed v1 log set. A compacted or rotated log becomes a NEW name (a v2 change).
pub const LOG_NAMES: [&str; 4] = ["settled_log", "self_log", "tune_log", "skills_log"];
/// `prev_sha256` at `seq = 0`.
pub const ZERO_SHA256: &str = "0000000000000000000000000000000000000000000000000000000000000000";
/// The only caller basis v1 can claim. `"peercred"` arrives with the #954 listener.
pub const CALLER_BASIS: &str = "token";
/// Most rows one read returns; the reply says whether more follow.
pub const READ_LIMIT_MAX: u64 = 1000;
/// Bound on each offered string copied onto a refusal row (a hex64 is 64).
pub const OFFERED_FIELD_MAX: usize = 128;

/// The keys `hestia_witness_history_append` honours. Anything else — `entity_lct` and
/// `caller_uid` above all — is refused: those come from the session, never from arguments.
pub const APPEND_ACCEPTED_KEYS: &[&str] =
    &["log_name", "seq", "entry_sha256", "prev_sha256", "session_id", "sessionId"];
/// The keys `hestia_history_witnesses` honours.
pub const READ_ACCEPTED_KEYS: &[&str] =
    &["entity_lct", "log_name", "from_seq", "limit", "session_id", "sessionId"];

/// Refusal codes. Each is stable wire vocabulary for the histories side.
pub mod code {
    pub const GAP: &str = "history_witness.gap";
    pub const FORK: &str = "history_witness.fork";
    pub const UNKNOWN_LOG: &str = "history_witness.unknown_log";
    pub const MALFORMED_HEX: &str = "history_witness.malformed_hex";
    pub const MALFORMED_SEQ: &str = "history_witness.malformed_seq";
    pub const UNKNOWN_ARGUMENT: &str = "history_witness.unknown_argument";
    /// No proven session: there is no entity to own a row, so this one is NOT recorded.
    pub const UNATTRIBUTED: &str = "history_witness.unattributed";
    /// The session's member maps to no LCT (a synthetic member). Not recorded, same reason.
    pub const NO_ENTITY: &str = "history_witness.no_entity";
}

/// A well-formed offer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Offer {
    pub log_name: String,
    pub seq: u64,
    pub entry_sha256: String,
    pub prev_sha256: String,
}

/// Why an offer is refused. `detail` rides on the refusal row and the error envelope.
#[derive(Debug, Clone, PartialEq)]
pub struct Refusal {
    pub code: &'static str,
    pub message: String,
    pub detail: Value,
}

impl Refusal {
    fn new(code: &'static str, message: impl Into<String>, detail: Value) -> Self {
        Self { code, message: message.into(), detail }
    }
}

/// One witnessed record, as read back from its row.
#[derive(Debug, Clone, PartialEq)]
pub struct Witnessed {
    pub entry_sha256: String,
    pub prev_sha256: String,
    pub row: ChainEntry,
}

impl Witnessed {
    /// Read a `history_witness` row. `None` for any other row or a malformed one.
    pub fn from_row(row: ChainEntry) -> Option<Self> {
        if row.event_type != WITNESS_EVENT {
            return None;
        }
        let entry_sha256 = row.event_data.get("entry_sha256")?.as_str()?.to_string();
        let prev_sha256 = row.event_data.get("prev_sha256")?.as_str()?.to_string();
        Some(Self { entry_sha256, prev_sha256, row })
    }
}

/// What to do with a well-formed offer.
#[derive(Debug, Clone, PartialEq)]
pub enum Decision {
    /// An exact repeat: answer with this row, append nothing.
    Existing(ChainEntry),
    /// `seq` is the next record: append it.
    Append,
    Refuse(Refusal),
}

pub fn is_log_name(s: &str) -> bool {
    LOG_NAMES.contains(&s)
}

/// Exactly 64 LOWERCASE hex digits — the spelling `hashlib.sha256().hexdigest()` produces.
/// Uppercase is refused rather than folded: a stored hash must be byte-equal to what the
/// verifier recomputes, and accepting two spellings of one hash invites a "mismatch" that is
/// only a case difference.
pub fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// The durable idempotency key binding `(entity, log, seq)` to its one witness row.
pub fn event_key(entity_lct: &str, log_name: &str, seq: u64) -> String {
    format!("history_witness:v1|{entity_lct}|{log_name}|{seq}")
}

/// The offered fields, bounded, as they ride on a refusal row: strings cut to
/// [`OFFERED_FIELD_MAX`] chars, numbers/bools/null kept, anything else named by its type.
pub fn offered_fields(args: &Value) -> Value {
    let mut out = serde_json::Map::new();
    for k in ["log_name", "seq", "entry_sha256", "prev_sha256"] {
        let v = match args.get(k) {
            None => continue,
            Some(Value::String(s)) => Value::String(s.chars().take(OFFERED_FIELD_MAX).collect()),
            Some(v @ (Value::Number(_) | Value::Bool(_) | Value::Null)) => v.clone(),
            Some(Value::Array(_)) => json!("<array>"),
            Some(Value::Object(_)) => json!("<object>"),
        };
        out.insert(k.to_string(), v);
    }
    Value::Object(out)
}

/// Validate the arguments into an [`Offer`]. Order: unknown keys, log name, seq, hashes.
pub fn parse_offer(args: &Value) -> Result<Offer, Refusal> {
    if let Some(obj) = args.as_object() {
        let unknown: Vec<&str> = obj
            .keys()
            .map(String::as_str)
            .filter(|k| !APPEND_ACCEPTED_KEYS.contains(k))
            .collect();
        if !unknown.is_empty() {
            return Err(Refusal::new(
                code::UNKNOWN_ARGUMENT,
                format!(
                    "unknown argument key(s): {}. The entity and the caller come from your \
                     session, never from arguments; accepted keys are: {}",
                    unknown.join(", "),
                    APPEND_ACCEPTED_KEYS.join(", ")
                ),
                json!({"unknown_keys": unknown}),
            ));
        }
    }
    let log_name = match args.get("log_name").and_then(Value::as_str) {
        Some(l) if is_log_name(l) => l.to_string(),
        _ => {
            return Err(Refusal::new(
                code::UNKNOWN_LOG,
                format!(
                    "log_name must be one of {} (the v1 set is closed; a compacted or rotated \
                     log is a new name, a v2 change)",
                    LOG_NAMES.join(", ")
                ),
                json!({"log_names": LOG_NAMES}),
            ));
        }
    };
    let Some(seq) = args.get("seq").and_then(Value::as_u64) else {
        return Err(Refusal::new(
            code::MALFORMED_SEQ,
            "seq must be a non-negative integer: the log's own 0-based record index",
            json!({}),
        ));
    };
    let mut hex = |k: &str| -> Result<String, Refusal> {
        match args.get(k).and_then(Value::as_str) {
            Some(h) if is_hex64(h) => Ok(h.to_string()),
            _ => Err(Refusal::new(
                code::MALFORMED_HEX,
                format!("{k} must be exactly 64 lowercase hex digits (a sha256 hexdigest)"),
                json!({"field": k}),
            )),
        }
    };
    let entry_sha256 = hex("entry_sha256")?;
    let prev_sha256 = hex("prev_sha256")?;
    Ok(Offer { log_name, seq, entry_sha256, prev_sha256 })
}

/// The last witnessed seq of one log, or `None` when nothing is witnessed. Relies on
/// contiguity (see the module doc): `exists(i)` is true exactly for `i <= L`, so a gallop
/// then a bisection finds `L` in O(log L) indexed reads.
pub fn last_witnessed<F>(mut exists: F) -> anyhow::Result<Option<u64>>
where
    F: FnMut(u64) -> anyhow::Result<bool>,
{
    if !exists(0)? {
        return Ok(None);
    }
    // Invariant: exists(lo), and hi is None (unbounded) or !exists(hi).
    let mut lo: u64 = 0;
    let mut step: u64 = 1;
    let hi = loop {
        match lo.checked_add(step) {
            None => {
                if exists(u64::MAX)? {
                    return Ok(Some(u64::MAX));
                }
                break u64::MAX;
            }
            Some(probe) => {
                if exists(probe)? {
                    lo = probe;
                    step = step.saturating_mul(2);
                } else {
                    break probe;
                }
            }
        }
    };
    let mut hi = hi;
    while hi - lo > 1 {
        let mid = lo + (hi - lo) / 2;
        if exists(mid)? {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    Ok(Some(lo))
}

/// Rule a well-formed offer against what is already witnessed. `lookup(seq)` returns the
/// witness at `seq` for the offer's `(entity, log)`, if any.
pub fn decide<F>(offer: &Offer, mut lookup: F) -> anyhow::Result<Decision>
where
    F: FnMut(u64) -> anyhow::Result<Option<Witnessed>>,
{
    if let Some(w) = lookup(offer.seq)? {
        if w.entry_sha256 == offer.entry_sha256 && w.prev_sha256 == offer.prev_sha256 {
            return Ok(Decision::Existing(w.row));
        }
        let reason = if w.entry_sha256 != offer.entry_sha256 {
            "same_seq_different_hash"
        } else {
            "same_seq_different_prev"
        };
        return Ok(Decision::Refuse(Refusal::new(
            code::FORK,
            format!(
                "seq {} of {} is already witnessed with different content: a rewrite of a \
                 witnessed record is a fork, and the witness stands",
                offer.seq, offer.log_name
            ),
            json!({
                "reason": reason,
                "witnessed_entry_sha256": w.entry_sha256,
                "witnessed_prev_sha256": w.prev_sha256,
                "witness_row": w.row.hash,
            }),
        )));
    }
    if offer.seq == 0 {
        if offer.prev_sha256 != ZERO_SHA256 {
            return Ok(Decision::Refuse(Refusal::new(
                code::FORK,
                "seq 0 has no predecessor: its prev_sha256 is 64 zeros",
                json!({"reason": "seq0_prev_not_zero", "expected_prev_sha256": ZERO_SHA256}),
            )));
        }
        return Ok(Decision::Append);
    }
    match lookup(offer.seq - 1)? {
        None => {
            let last = last_witnessed(|i| Ok(lookup(i)?.is_some()))?;
            let expected = last.map_or(0, |l| l.saturating_add(1));
            let message = match last {
                None => format!(
                    "{} has no witness yet, so the first witness must be seq 0 (backfill from \
                     0); a first witness at {} would hide any rewrite below it",
                    offer.log_name, offer.seq
                ),
                Some(l) => format!(
                    "{} is witnessed through seq {l}; seq {} would leave an unwitnessed gap. \
                     Witness seq {expected} next",
                    offer.log_name, offer.seq
                ),
            };
            Ok(Decision::Refuse(Refusal::new(
                code::GAP,
                message,
                json!({
                    "first_witness": last.is_none(),
                    "last_witnessed_seq": last,
                    "expected_seq": expected,
                }),
            )))
        }
        Some(p) if p.entry_sha256 != offer.prev_sha256 => Ok(Decision::Refuse(Refusal::new(
            code::FORK,
            format!(
                "prev_sha256 does not match the witnessed entry at seq {} of {}: the log \
                 forked below the offered record",
                offer.seq - 1,
                offer.log_name
            ),
            json!({
                "reason": "prev_mismatch",
                "witnessed_prev_entry_sha256": p.entry_sha256,
                "witness_row": p.row.hash,
            }),
        ))),
        Some(_) => Ok(Decision::Append),
    }
}

/// The `event_data` of a witness row — exactly the v1 table, nothing else.
pub fn witness_data(entity_lct: &str, offer: &Offer) -> Value {
    json!({
        "schema": SCHEMA,
        "entity_lct": entity_lct,
        "log_name": offer.log_name,
        "seq": offer.seq,
        "entry_sha256": offer.entry_sha256,
        "prev_sha256": offer.prev_sha256,
        "caller_uid": Value::Null,
        "caller_basis": CALLER_BASIS,
    })
}

/// The `event_data` of a refusal row: the code, the bounded offered fields, and the detail
/// the ruling relied on (the witnessed hash a fork contradicts, the last seq a gap skips).
pub fn refusal_data(entity_lct: &str, refusal: &Refusal, offered: Value) -> Value {
    json!({
        "schema": SCHEMA,
        "entity_lct": entity_lct,
        "code": refusal.code,
        "message": refusal.message,
        "offered": offered,
        "detail": refusal.detail,
        "caller_uid": Value::Null,
        "caller_basis": CALLER_BASIS,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn h(c: char) -> String {
        c.to_string().repeat(64)
    }

    fn row(seq: u64, entry: &str, prev: &str) -> ChainEntry {
        ChainEntry {
            hash: format!("row-{seq}"),
            prev_hash: String::new(),
            timestamp: chrono::Utc::now(),
            event_type: WITNESS_EVENT.into(),
            event_data: witness_data(
                "lct:test",
                &Offer {
                    log_name: "self_log".into(),
                    seq,
                    entry_sha256: entry.into(),
                    prev_sha256: prev.into(),
                },
            ),
            signer_lct: String::new(),
            chain_position: seq,
        }
    }

    /// A contiguous witnessed log 0..n whose entry at i is the hex digit i (mod 10).
    fn log(n: u64) -> BTreeMap<u64, Witnessed> {
        let mut m = BTreeMap::new();
        let mut prev = ZERO_SHA256.to_string();
        for i in 0..n {
            let e = h(char::from_digit((i % 10) as u32, 10).unwrap());
            m.insert(i, Witnessed::from_row(row(i, &e, &prev)).unwrap());
            prev = e;
        }
        m
    }

    fn offer(seq: u64, entry: &str, prev: &str) -> Offer {
        Offer { log_name: "self_log".into(), seq, entry_sha256: entry.into(), prev_sha256: prev.into() }
    }

    fn rule(m: &BTreeMap<u64, Witnessed>, o: &Offer) -> Decision {
        decide(o, |i| Ok(m.get(&i).cloned())).unwrap()
    }

    fn refusal_code(d: &Decision) -> &'static str {
        match d {
            Decision::Refuse(r) => r.code,
            other => panic!("expected a refusal, got {other:?}"),
        }
    }

    #[test]
    fn hex64_is_exact_lowercase_only() {
        assert!(is_hex64(&h('a')));
        assert!(is_hex64(ZERO_SHA256));
        assert!(!is_hex64(&h('A')), "uppercase is a second spelling of one hash");
        assert!(!is_hex64(&h('g')));
        assert!(!is_hex64(&"a".repeat(63)));
        assert!(!is_hex64(&"a".repeat(65)));
        assert!(!is_hex64(""));
    }

    #[test]
    fn the_log_set_is_closed() {
        for l in LOG_NAMES {
            assert!(is_log_name(l));
        }
        for bad in ["", "settled", "Self_log", "self_log ", "other_log"] {
            assert!(!is_log_name(bad), "{bad:?}");
        }
    }

    #[test]
    fn parse_refuses_each_malformation_with_its_own_code() {
        let good = json!({"log_name": "tune_log", "seq": 3, "entry_sha256": h('a'), "prev_sha256": h('b')});
        assert_eq!(parse_offer(&good).unwrap(), Offer {
            log_name: "tune_log".into(), seq: 3, entry_sha256: h('a'), prev_sha256: h('b'),
        });
        let with = |k: &str, v: Value| {
            let mut a = good.clone();
            a[k] = v;
            parse_offer(&a).unwrap_err().code
        };
        assert_eq!(with("log_name", json!("other_log")), code::UNKNOWN_LOG);
        assert_eq!(with("log_name", json!(7)), code::UNKNOWN_LOG);
        assert_eq!(with("seq", json!(-1)), code::MALFORMED_SEQ);
        assert_eq!(with("seq", json!(1.5)), code::MALFORMED_SEQ);
        assert_eq!(with("seq", json!("3")), code::MALFORMED_SEQ);
        assert_eq!(with("entry_sha256", json!(h('A'))), code::MALFORMED_HEX);
        assert_eq!(with("prev_sha256", json!("abc")), code::MALFORMED_HEX);
        // The entity and caller come from the session; offering them is refused.
        assert_eq!(with("entity_lct", json!("lct:someone-else")), code::UNKNOWN_ARGUMENT);
        assert_eq!(with("caller_uid", json!(0)), code::UNKNOWN_ARGUMENT);
        let mut missing = good.clone();
        missing.as_object_mut().unwrap().remove("prev_sha256");
        assert_eq!(parse_offer(&missing).unwrap_err().code, code::MALFORMED_HEX);
    }

    #[test]
    fn the_first_witness_is_seq_zero_with_a_zero_prev() {
        let empty = log(0);
        assert_eq!(rule(&empty, &offer(0, &h('0'), ZERO_SHA256)), Decision::Append);
        let d = rule(&empty, &offer(0, &h('0'), &h('1')));
        assert_eq!(refusal_code(&d), code::FORK, "seq 0 has no predecessor");
    }

    #[test]
    fn a_first_witness_at_k_is_a_gap() {
        let d = rule(&log(0), &offer(5, &h('5'), &h('4')));
        assert_eq!(refusal_code(&d), code::GAP);
        let Decision::Refuse(r) = d else { unreachable!() };
        assert_eq!(r.detail["first_witness"], true);
        assert_eq!(r.detail["expected_seq"], 0);
        assert_eq!(r.detail["last_witnessed_seq"], Value::Null);
    }

    #[test]
    fn next_is_last_plus_one_and_a_skip_is_a_gap() {
        let m = log(3); // 0..=2
        assert_eq!(rule(&m, &offer(3, &h('3'), &h('2'))), Decision::Append);
        let d = rule(&m, &offer(4, &h('4'), &h('3')));
        assert_eq!(refusal_code(&d), code::GAP);
        let Decision::Refuse(r) = d else { unreachable!() };
        assert_eq!((r.detail["last_witnessed_seq"].clone(), r.detail["expected_seq"].clone()), (json!(2), json!(3)));
        assert_eq!(r.detail["first_witness"], false);
    }

    #[test]
    fn a_prev_that_disagrees_with_the_witness_is_a_fork() {
        let d = rule(&log(3), &offer(3, &h('3'), &h('f')));
        assert_eq!(refusal_code(&d), code::FORK);
        let Decision::Refuse(r) = d else { unreachable!() };
        assert_eq!(r.detail["reason"], "prev_mismatch");
        assert_eq!(r.detail["witnessed_prev_entry_sha256"], json!(h('2')));
        assert_eq!(r.detail["witness_row"], "row-2");
    }

    #[test]
    fn a_repeat_is_idempotent_and_a_rewrite_is_a_fork() {
        let m = log(3);
        assert_eq!(
            rule(&m, &offer(1, &h('1'), &h('0'))),
            Decision::Existing(m[&1].row.clone())
        );
        let d = rule(&m, &offer(1, &h('e'), &h('0')));
        assert_eq!(refusal_code(&d), code::FORK);
        let Decision::Refuse(r) = d else { unreachable!() };
        assert_eq!(r.detail["reason"], "same_seq_different_hash");
        assert_eq!(r.detail["witnessed_entry_sha256"], json!(h('1')));
        // Same entry, different predecessor: not an exact repeat, and not a fresh record.
        let d = rule(&m, &offer(1, &h('1'), &h('e')));
        assert_eq!(refusal_code(&d), code::FORK);
        let Decision::Refuse(r) = d else { unreachable!() };
        assert_eq!(r.detail["reason"], "same_seq_different_prev");
    }

    #[test]
    fn last_witnessed_is_exact_for_every_length() {
        for n in 0..300u64 {
            let calls = std::cell::Cell::new(0u32);
            let got = last_witnessed(|i| {
                calls.set(calls.get() + 1);
                Ok(i < n)
            })
            .unwrap();
            assert_eq!(got, n.checked_sub(1), "n={n}");
            assert!(calls.get() <= 2 * 64 + 2, "O(log n) reads, n={n}: {}", calls.get());
        }
        assert_eq!(last_witnessed(|_| Ok(true)).unwrap(), Some(u64::MAX));
        assert_eq!(last_witnessed(|i| Ok(i <= 1_000_000_007)).unwrap(), Some(1_000_000_007));
    }

    #[test]
    fn offered_fields_are_bounded_and_carry_only_the_four() {
        let long = "z".repeat(10_000);
        let v = offered_fields(&json!({
            "log_name": long, "seq": -4, "entry_sha256": {"x": 1}, "prev_sha256": [1],
            "entity_lct": "never copied",
        }));
        assert_eq!(v["log_name"].as_str().unwrap().len(), OFFERED_FIELD_MAX);
        assert_eq!(v["seq"], -4);
        assert_eq!(v["entry_sha256"], "<object>");
        assert_eq!(v["prev_sha256"], "<array>");
        assert!(v.get("entity_lct").is_none());
    }

    #[test]
    fn a_witness_row_is_exactly_the_v1_table() {
        let d = witness_data("lct:e", &offer(0, &h('a'), ZERO_SHA256));
        let mut keys: Vec<&str> = d.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            ["caller_basis", "caller_uid", "entity_lct", "entry_sha256", "log_name", "prev_sha256", "schema", "seq"]
        );
        assert_eq!(d["schema"], SCHEMA);
        assert_eq!(d["caller_uid"], Value::Null);
        assert_eq!(d["caller_basis"], "token");
    }
}
