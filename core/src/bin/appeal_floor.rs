//! `appeal_floor` — enumerate appeals that fell below the arbitration window.
//!
//! ## Why this is a separate surface, not a flag on the queue
//!
//! `hestia_open_appeals` (PR #67) and `hestia_arbitrate_appeal` share one
//! constant, `APPEAL_CHAIN_WINDOW`, so *listed* and *rulable* are the same
//! predicate by construction. That invariant is the queue's whole value and it
//! must not be weakened. This bin answers the OPPOSITE question — what is
//! **un**rulable — and so wears a different name and lives outside the queue
//! (kimi-code's refinement, `kimi-to-cbp-the-dead-pointer-reproduced-and-one-
//! overstatement-in-s4-2026-07-27.md` §3: the queue measures *approaching*
//! expiry; nothing enumerated what already fell off the edge).
//!
//! ## The failure it measures
//!
//! An appeal is filed. No eligible arbiter finds it (the discovery gap #67
//! repairs). The chain grows by `APPEAL_CHAIN_WINDOW` entries. Now:
//!
//!   * `hestia_arbitrate_appeal` cannot rule on it — it searches only
//!     `recent_chain(APPEAL_CHAIN_WINDOW)` for the `appeal` entry
//!     (handler.rs `tool_arbitrate_appeal`, the `arbitration_no_appeal` arm).
//!   * `hestia_appeal` cannot re-file it — that path first requires the
//!     *deny* entry in the same window, and the deny is strictly OLDER than
//!     the appeal citing it. Both doors close, and the deny's door closes
//!     first.
//!
//! So the state is terminal, not merely stale: the appellant carries the
//! deny's score forever, no `adjudication` is possible, and nothing in the
//! chain marks the transition. Absence is not a state — this bin is the
//! instrument that makes it one.
//!
//! ## Method
//!
//! Full-chain scan (NOT windowed), ascending. Join `appeal.deny_hash` against
//! `adjudication.about_deny_hash` — the exact pair the ruling path matches on.
//! Survivors are unruled; those with `chain_position <= head - window` are
//! expired. Reported separately from the in-window survivors, because the
//! second set is the queue's job and the first set is nobody's.
//!
//! Sealed-at-rest respected the same way `calib_export` does it: the encrypted
//! DB is byte-copied to avoid SQLCipher single-writer contention with the live
//! daemon, the key never leaves this process, and plaintext never hits disk.
//! Read-only: this bin appends nothing to the chain.
//!
//! ```text
//! surface: appeal_floor (read-only report)   act: none (no chain append, no state mutation)
//! S: low/reversible [construct: main — read path only, output is a report]
//! R: n/a   W: n/a [no act to authorize; passphrase-holder already holds the chain]
//! O: pass [construct: no side effect to order]   A: n/a [records nothing]
//! V: n/a
//! verdict: PASS
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{Context, Result};
use hestia::storage::{SqliteChainStore, storage_key};
use hestia::vault::storage::default_hestia_home;

/// Mirrors `handler.rs`'s `APPEAL_CHAIN_WINDOW`. Overridable with `--window` so
/// the margin can be probed, but the DEFAULT MUST TRACK the handler constant —
/// a report computed against a different window than the one that rules is a
/// report about nothing. Checked by `appeal_floor_window_matches_handler`.
const DEFAULT_WINDOW: u64 = 20_000;

struct Appeal {
    deny_hash: String,
    position: u64,
    plugin_id: String,
    role_lct: String,
    timestamp: String,
    entry_hash: String,
}

/// An appeal that is unrulable by SHAPE rather than by age: filed through
/// `hestia_request_witness("appeal", ...)` before `hestia_appeal` existed, so
/// its `deny_hash` sits under `data` and every reader that matters — the ruling
/// path, the queue, `derivation.rs` — matches it FLAT and misses.
///
/// `handler.rs`'s own comment records these three (62959/62963/63408, verified
/// by hand 2026-07-27) and stops at "inert". It is worse than inert, and the
/// difference is a deadline: the nested appeal does not block a re-file (the
/// duplicate check is also a flat match), so the dispute is still recoverable
/// through `hestia_appeal` — but only while the DENY it cites is inside the
/// window. The deny is strictly older than the appeal, so the deny's door
/// closes first, and after it closes the dispute is unrecordable forever while
/// the conduct scale goes on reading the member as ordinarily compliant.
///
/// That deadline was real and it was MET: `claude-code` re-filed 62963 and 63408
/// flat through `hestia_appeal`, and `kimi-code` ruled both UPHELD on
/// 2026-07-28T17:42Z (chain 70339/70340, adjudications `eba318fa`/`d36e20d7`,
/// both `judge-by-mention` false positives predating the executable-position fix
/// `2f9a4a5`). Which exposed the reporting defect below.
struct Nested {
    position: u64,
    plugin_id: String,
    timestamp: String,
    /// `deny_hash` recovered from `data.deny_hash`, if it is there at all.
    recovered_deny: Option<String>,
}

/// What is actually true of a nested appeal's underlying DISPUTE — which is not
/// the same question as what is true of the nested ENTRY.
///
/// ## Why a four-state enum and not the boolean it replaces
///
/// The first cut of this bin reported `refilable_now: bool` and never consulted
/// the adjudication set for nested rows at all — it joined `ruled` against flat
/// appeals only. So on 2026-07-28 at 17:42Z two of these disputes were upheld,
/// and at 18:0xZ this report still printed both as open deadlines with ~12,500
/// entries of headroom, instructing a re-file of a grievance that had already
/// won. kimi-code named the class before the fixture existed ("the flat join
/// lies by omission — it needs nested rulings"); the two rulings are the fixture.
///
/// The boolean conflated *action is possible* with *action is needed*. A ruled
/// dispute is still technically re-filable — the shape defect means nothing
/// blocks it — so `refilable_now` stayed honest by its own definition while the
/// report built on it was false. Splitting the states is the repair: `Ruled` and
/// `Refilable` are both "re-file would succeed", and only one of them is anyone's
/// job.
///
/// Note the asymmetry this preserves: a nested entry is inert FOREVER. Ruling
/// the dispute does not make the ruling path see the entry. `Ruled` means the
/// grievance was heard through a flat re-file, not that the shape defect healed.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum NestedDisposition {
    /// The cited deny carries an `adjudication`. The dispute was heard. Nobody's
    /// job — and emphatically not a deadline.
    Ruled,
    /// No adjudication, and the deny is still inside the window. THIS is the
    /// deadline: the live, actionable state this bin was built to surface.
    Refilable,
    /// No adjudication and the deny has aged below the floor. Terminal: the
    /// dispute can no longer be filed OR ruled, and the appellant carries the
    /// deny's score permanently. The failure `expired_unruled` measures for flat
    /// appeals, in its nested form.
    Expired,
    /// No `deny_hash` survives in the payload, or the deny is not on this chain:
    /// there is nothing to re-file AGAINST. Terminal for a different reason.
    Unrecoverable,
}

impl NestedDisposition {
    fn as_str(self) -> &'static str {
        match self {
            Self::Ruled => "ruled",
            Self::Refilable => "refilable",
            Self::Expired => "expired",
            Self::Unrecoverable => "unrecoverable",
        }
    }

    /// Does this dispute still want something from someone? `Ruled` is closed;
    /// `Unrecoverable` and `Expired` are closed by loss, which is worth counting
    /// separately but is nobody's action item either.
    fn is_open_deadline(self) -> bool {
        matches!(self, Self::Refilable)
    }
}

/// The join the first cut omitted. Pure, so the omission is testable without a
/// chain.
///
/// Order matters: `ruled` is consulted BEFORE any position arithmetic. An
/// adjudication is evidence the dispute was heard, and that stays true whether
/// or not the deny it is about can still be located in the window — a ruling
/// does not lapse when the entry it cites ages out.
fn classify_nested(
    recovered_deny: Option<&str>,
    ruled: &HashMap<String, u64>,
    deny_pos: Option<u64>,
    floor: u64,
) -> NestedDisposition {
    let Some(hash) = recovered_deny else {
        return NestedDisposition::Unrecoverable;
    };
    if ruled.contains_key(hash) {
        return NestedDisposition::Ruled;
    }
    match deny_pos {
        // `>` mirrors the flat path's `<= floor` expiry test, inverted.
        Some(p) if p > floor => NestedDisposition::Refilable,
        Some(_) => NestedDisposition::Expired,
        None => NestedDisposition::Unrecoverable,
    }
}

fn main() -> Result<()> {
    let mut window = DEFAULT_WINDOW;
    let mut json_out = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--window" | "-w" => {
                window = args
                    .next()
                    .context("--window requires an entry count")?
                    .parse()
                    .context("--window must be a positive integer")?;
            }
            "--json" => json_out = true,
            "--help" | "-h" => {
                eprintln!(
                    "appeal_floor [--window N] [--json]\n\n\
                     Enumerates appeals with no adjudication, split by whether they are\n\
                     still inside the arbitration window (rulable — the queue's job) or\n\
                     below it (UNRULABLE and unrefilable — nobody's job until now).\n\
                     Read-only; appends nothing to the chain."
                );
                return Ok(());
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }

    let home = match std::env::var("HESTIA_HOME") {
        Ok(h) if !h.is_empty() => PathBuf::from(h),
        _ => default_hestia_home().context("resolving hestia home")?,
    };
    let passphrase = read_passphrase(&home)?;
    let key = storage_key(&home, &passphrase).context("deriving storage key")?;

    let src_db = home.join("witness.db");
    let tmp_dir = std::env::temp_dir().join(format!("hestia-appeal-floor-{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir).context("creating temp copy dir")?;
    let copy_db = tmp_dir.join("witness.db");
    SqliteChainStore::backup_encrypted(&src_db, &copy_db, key)
        .with_context(|| format!("snapshotting sealed chain {}", src_db.display()))?;

    let store = SqliteChainStore::open(&copy_db, key)
        .context("opening sealed chain copy (wrong passphrase => AEAD/open error)")?;
    let total = store.len().context("counting chain entries")?;

    // Full ascending scan. Only the two event types are retained, so a chain of
    // any size costs a bounded amount of memory in the join.
    let mut appeals: Vec<Appeal> = Vec::new();
    let mut nested: Vec<Nested> = Vec::new();
    let mut ruled: HashMap<String, u64> = HashMap::new();
    // Position of every chain entry, so a nested appeal's recovered deny_hash
    // can be located and its re-file headroom computed.
    let mut positions: HashMap<String, u64> = HashMap::new();
    let mut head = 0u64;
    let mut scanned = 0u64;
    let page = 50_000u64;
    let mut cursor = 0u64;
    loop {
        let batch = store
            .read_since(cursor, page)
            .context("reading chain entries")?;
        if batch.is_empty() {
            break;
        }
        cursor = batch.last().expect("non-empty batch").chain_position;
        for e in &batch {
            scanned += 1;
            head = head.max(e.chain_position);
            positions.insert(e.hash.clone(), e.chain_position);
            match e.event_type.as_str() {
                "appeal" => {
                    let Some(deny_hash) = e.event_data.get("deny_hash").and_then(|v| v.as_str())
                    else {
                        // Unrulable by SHAPE. Classified, not skipped: an appeal
                        // nothing can read is a stronger finding than one that is
                        // merely old, and unlike an expired one it may still be
                        // recoverable. `requested_by.plugin_id` is the witness
                        // wrapper's attribution — the whole reason the payload is
                        // one level too deep.
                        nested.push(Nested {
                            position: e.chain_position,
                            plugin_id: e
                                .event_data
                                .pointer("/requested_by/plugin_id")
                                .and_then(|v| v.as_str())
                                .unwrap_or("(unattributed)")
                                .to_string(),
                            timestamp: e.timestamp.to_rfc3339(),
                            recovered_deny: e
                                .event_data
                                .pointer("/data/deny_hash")
                                .and_then(|v| v.as_str())
                                .map(str::to_string),
                        });
                        continue;
                    };
                    appeals.push(Appeal {
                        deny_hash: deny_hash.to_string(),
                        position: e.chain_position,
                        plugin_id: e
                            .event_data
                            .get("plugin_id")
                            .and_then(|v| v.as_str())
                            .unwrap_or("(unattributed)")
                            .to_string(),
                        role_lct: e
                            .event_data
                            .get("role_lct")
                            .and_then(|v| v.as_str())
                            .unwrap_or("(no role)")
                            .to_string(),
                        timestamp: e.timestamp.to_rfc3339(),
                        entry_hash: e.hash.clone(),
                    });
                }
                "adjudication" => {
                    if let Some(about) = e
                        .event_data
                        .get("about_deny_hash")
                        .and_then(|v| v.as_str())
                    {
                        ruled.insert(about.to_string(), e.chain_position);
                    }
                }
                _ => {}
            }
        }
        if scanned >= total {
            break;
        }
    }

    let _ = std::fs::remove_file(&copy_db);
    let _ = std::fs::remove_dir(&tmp_dir);

    let floor = head.saturating_sub(window);
    let unruled: Vec<&Appeal> = appeals
        .iter()
        .filter(|a| !ruled.contains_key(&a.deny_hash))
        .collect();
    // `<=` not `<`: the ruling path matches over `recent_chain(window)`, whose
    // oldest retained position is head - window + 1. An appeal AT the floor is
    // already out.
    let (expired, live): (Vec<&&Appeal>, Vec<&&Appeal>) =
        unruled.iter().partition(|a| a.position <= floor);

    // Nested appeals. The disposition — NOT the headroom — is the answer: a
    // ruled dispute has headroom too, and reporting only the headroom is what
    // made the first cut print discharged deadlines as live ones.
    let nested_dispositions: Vec<NestedDisposition> = nested
        .iter()
        .map(|nn| {
            let deny_pos = nn
                .recovered_deny
                .as_ref()
                .and_then(|h| positions.get(h).copied());
            classify_nested(nn.recovered_deny.as_deref(), &ruled, deny_pos, floor)
        })
        .collect();
    let nested_rows: Vec<_> = nested
        .iter()
        .zip(&nested_dispositions)
        .map(|(nn, &disp)| {
            let deny_pos = nn
                .recovered_deny
                .as_ref()
                .and_then(|h| positions.get(h).copied());
            serde_json::json!({
                "chain_position": nn.position,
                "appellant": nn.plugin_id,
                "filed_at": nn.timestamp,
                "recovered_deny_hash": nn.recovered_deny,
                "deny_position": deny_pos,
                // None = the deny_hash was absent or the deny is not on this
                // chain: nothing to re-file against, already unrecoverable.
                "refile_headroom": deny_pos.map(|p| p.saturating_sub(floor)),
                "disposition": disp.as_str(),
                // The adjudication's own position, so "ruled" is a claim the
                // reader can follow to an entry rather than take on trust.
                "ruled_at_position": nn
                    .recovered_deny
                    .as_ref()
                    .and_then(|h| ruled.get(h).copied()),
                "open_deadline": disp.is_open_deadline(),
            })
        })
        .collect();
    let nested_open = nested_dispositions
        .iter()
        .filter(|d| d.is_open_deadline())
        .count();

    if json_out {
        let rows: Vec<_> = expired
            .iter()
            .map(|a| {
                serde_json::json!({
                    "deny_hash": a.deny_hash,
                    "appeal_entry": a.entry_hash,
                    "chain_position": a.position,
                    "appellant": a.plugin_id,
                    "role_lct": a.role_lct,
                    "filed_at": a.timestamp,
                    "positions_below_floor": floor.saturating_sub(a.position),
                })
            })
            .collect();
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "chain_entries": total,
                "head": head,
                "window": window,
                "floor": floor,
                "appeals_total": appeals.len(),
                "adjudications_total": ruled.len(),
                "unruled_total": unruled.len(),
                "unruled_in_window": live.len(),
                "expired_unruled": rows,
                "nested_inert": nested_rows,
                "nested_total": nested_rows.len(),
                "nested_open_deadlines": nested_open,
            }))?
        );
        return Ok(());
    }

    println!("appeal_floor — unwindowed scan of {total} chain entries");
    println!("  head position:        {head}");
    println!("  arbitration window:   {window}  (floor at {floor})");
    println!("  appeal entries:       {}", appeals.len());
    println!("  adjudications:        {}", ruled.len());
    println!("  unruled appeals:      {}", unruled.len());
    println!(
        "    still rulable:      {}  (inside the window — hestia_open_appeals' set)",
        live.len()
    );
    println!(
        "    EXPIRED:            {}  (below the floor — unrulable AND unrefilable)",
        expired.len()
    );
    if expired.is_empty() {
        println!(
            "\nNo appeal has expired unruled on this chain. The predicted failure is\n\
             UNTESTED-CLEAN, not refuted: the window has simply never been outrun by an\n\
             unruled appeal yet. Re-run this after any period of heavy chain traffic."
        );
    } else {
        println!("\nEXPIRED UNRULED APPEALS — each one a member stuck at its deny's score:");
        for a in &expired {
            println!(
                "  pos {:>7} ({:>6} below floor)  {}  appellant={} role={}  filed={}",
                a.position,
                floor.saturating_sub(a.position),
                &a.deny_hash[..a.deny_hash.len().min(16)],
                a.plugin_id,
                a.role_lct,
                a.timestamp,
            );
        }
    }
    if !live.is_empty() {
        let nearest = live.iter().map(|a| a.position).min().unwrap_or(head);
        println!(
            "\nNearest expiry: appeal at {nearest}, {} entries of headroom.",
            nearest.saturating_sub(floor)
        );
    }

    if !nested.is_empty() {
        println!(
            "\nNESTED INERT APPEALS: {}  (unrulable by SHAPE — deny_hash one level deep\n\
             under `data`, so the ruling path, the queue and derivation.rs all miss it)",
            nested.len()
        );
        for ((nn, row), &disp) in nested
            .iter()
            .zip(&nested_rows)
            .zip(&nested_dispositions)
        {
            let deny_pos = row.get("deny_position").and_then(|v| v.as_u64());
            let head_room = row.get("refile_headroom").and_then(|v| v.as_u64());
            let ruled_at = row.get("ruled_at_position").and_then(|v| v.as_u64());
            print!(
                "  pos {:>7}  appellant={}  filed={}\n\x20   ",
                nn.position, nn.plugin_id, nn.timestamp
            );
            match disp {
                NestedDisposition::Ruled => println!(
                    "DISPUTE RULED at {} — heard via a flat re-file. Not a deadline.\n\
                     \x20   (the nested entry at {} stays inert forever; ruling the dispute \
                     does not heal the shape)",
                    ruled_at.map_or("?".to_string(), |p| p.to_string()),
                    nn.position,
                ),
                NestedDisposition::Refilable => println!(
                    "OPEN DEADLINE — deny at {} is still in window, re-filable via \
                     hestia_appeal, {} entries of headroom",
                    deny_pos.map_or("?".to_string(), |p| p.to_string()),
                    head_room.unwrap_or(0),
                ),
                NestedDisposition::Expired => println!(
                    "deny at {} is BELOW THE FLOOR and unruled — no longer re-filable; \
                     the dispute is now unrecordable",
                    deny_pos.map_or("?".to_string(), |p| p.to_string()),
                ),
                NestedDisposition::Unrecoverable => println!(
                    "no recoverable deny_hash in the payload — nothing to re-file against"
                ),
            }
        }
        println!(
            "\n  OPEN DEADLINES: {nested_open} of {}.\n\
             \x20 A nested appeal does NOT block a re-file: the duplicate check is a flat\n\
             match too, so it does not see these either. That is what leaves a window open\n\
             — and the window closes when the DENY ages out, not the appeal.\n\
             \x20 A `ruled` row is closed because the dispute was heard through a re-file,\n\
             NOT because the nested entry became legible to the ruling path. It did not.",
            nested.len()
        );
    }
    Ok(())
}

/// Same passphrase resolution as `calib_export`: `HESTIA_PASSPHRASE` env, or
/// `<home>/.passphrase` (the automation path).
fn read_passphrase(home: &std::path::Path) -> Result<String> {
    if let Ok(pp) = std::env::var("HESTIA_PASSPHRASE") {
        if !pp.is_empty() {
            return Ok(pp);
        }
    }
    let pf = home.join(".passphrase");
    let raw = std::fs::read_to_string(&pf)
        .with_context(|| format!("reading passphrase file {}", pf.display()))?;
    let pp = raw.trim_end_matches(['\n', '\r']).to_string();
    anyhow::ensure!(!pp.is_empty(), "passphrase file is empty");
    Ok(pp)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The two denies kimi-code ruled on 2026-07-28T17:42Z, and the nested
    /// appeals that cite them. Real hashes and real positions: this is the
    /// fixture the first cut of the bin got wrong, not an invented one.
    const DENY_A: &str = "0329c5c589f427db948312a157940eda42fec2357371ba46685e8805138ec0da";
    const DENY_B: &str = "eb84d2541ae51204be926392f18897b7fc72cb9f54db148ec5c9ddc1c1557136";

    fn live_fixture() -> (HashMap<String, u64>, HashMap<String, u64>) {
        // adjudication.about_deny_hash -> adjudication position
        let ruled = HashMap::from([
            (DENY_A.to_string(), 70339), // eba318fa, upheld
            (DENY_B.to_string(), 70340), // d36e20d7, upheld
        ]);
        // deny_hash -> deny position
        let positions = HashMap::from([(DENY_A.to_string(), 62958), (DENY_B.to_string(), 63406)]);
        (ruled, positions)
    }

    /// THE REGRESSION. Before the join, both of these classified as a live
    /// deadline with ~12,500 entries of headroom — 35 minutes after they were
    /// upheld. The report told the appellant to re-file a grievance it had
    /// already won.
    #[test]
    fn a_ruled_dispute_is_not_an_open_deadline() {
        let (ruled, positions) = live_fixture();
        let floor = 50_377; // head 70,377 - window 20,000, the 2026-07-28 run

        for (deny, appeal_pos) in [(DENY_A, 62963u64), (DENY_B, 63408)] {
            let disp = classify_nested(Some(deny), &ruled, positions.get(deny).copied(), floor);
            assert_eq!(
                disp,
                NestedDisposition::Ruled,
                "nested appeal at {appeal_pos} cites deny {} which HAS an adjudication; \
                 classifying it any other way re-opens a settled dispute",
                &deny[..16]
            );
            assert!(
                !disp.is_open_deadline(),
                "a ruled dispute must never be counted as an open deadline"
            );
        }
    }

    /// The state the bin exists to surface must survive the fix. If the join
    /// were written to swallow everything, this is what would go quiet.
    #[test]
    fn an_unruled_deny_in_window_is_still_the_deadline() {
        let (_, positions) = live_fixture();
        let empty = HashMap::new();
        let disp = classify_nested(Some(DENY_A), &empty, positions.get(DENY_A).copied(), 50_377);
        assert_eq!(disp, NestedDisposition::Refilable);
        assert!(disp.is_open_deadline(), "this is the actionable state");
    }

    /// Below the floor and unruled: the nested form of `expired_unruled`. It is
    /// terminal, and it must NOT be reported as an open deadline — nobody can
    /// act on it — but it is also not `ruled`. Three-way, not two.
    #[test]
    fn an_unruled_deny_below_the_floor_is_expired_not_refilable() {
        let empty = HashMap::new();
        let disp = classify_nested(Some(DENY_A), &empty, Some(40_000), 50_377);
        assert_eq!(disp, NestedDisposition::Expired);
        assert!(!disp.is_open_deadline());
    }

    /// Entry 62959: `deny_hash` absent from the payload entirely. Nothing to
    /// re-file against, ruled or not.
    #[test]
    fn no_recoverable_deny_hash_is_unrecoverable() {
        let (ruled, _) = live_fixture();
        assert_eq!(
            classify_nested(None, &ruled, None, 50_377),
            NestedDisposition::Unrecoverable
        );
        // ...and a deny that is not on this chain at all is the same verdict.
        assert_eq!(
            classify_nested(Some("deadbeef"), &ruled, None, 50_377),
            NestedDisposition::Unrecoverable
        );
    }

    /// A ruling does not lapse when the entry it is about ages out of the
    /// window. `ruled` is consulted before any position arithmetic, and this
    /// pins that ordering: deny below the floor, but adjudicated.
    #[test]
    fn a_ruling_outlives_the_window_of_the_deny_it_is_about() {
        let (ruled, _) = live_fixture();
        assert_eq!(
            classify_nested(Some(DENY_A), &ruled, Some(1), 50_377),
            NestedDisposition::Ruled,
            "an adjudication is evidence the dispute was heard; the deny's age \
             cannot un-hear it"
        );
    }
}
