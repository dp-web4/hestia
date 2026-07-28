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
struct Nested {
    position: u64,
    plugin_id: String,
    timestamp: String,
    /// `deny_hash` recovered from `data.deny_hash`, if it is there at all.
    recovered_deny: Option<String>,
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
    std::fs::copy(&src_db, &copy_db)
        .with_context(|| format!("copying sealed chain {}", src_db.display()))?;

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

    // Nested appeals, with the re-file headroom that makes them a deadline
    // rather than a fact. `> floor` is the ruling/filing path's own test.
    let nested_rows: Vec<_> = nested
        .iter()
        .map(|nn| {
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
                "refilable_now": deny_pos.map_or(false, |p| p > floor),
            })
        })
        .collect();

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
        for (nn, row) in nested.iter().zip(&nested_rows) {
            let deny_pos = row.get("deny_position").and_then(|v| v.as_u64());
            let head_room = row.get("refile_headroom").and_then(|v| v.as_u64());
            match deny_pos {
                Some(dp) if head_room.is_some_and(|h| h > 0) => println!(
                    "  pos {:>7}  appellant={}  filed={}\n\
                     \x20   deny at {dp} is STILL IN WINDOW — re-filable via hestia_appeal, \
                     {} entries of headroom",
                    nn.position,
                    nn.plugin_id,
                    nn.timestamp,
                    head_room.unwrap_or(0),
                ),
                Some(dp) => println!(
                    "  pos {:>7}  appellant={}  filed={}\n\
                     \x20   deny at {dp} is BELOW THE FLOOR — no longer re-filable; \
                     the dispute is now unrecordable",
                    nn.position, nn.plugin_id, nn.timestamp,
                ),
                None => println!(
                    "  pos {:>7}  appellant={}  filed={}\n\
                     \x20   no recoverable deny_hash in the payload — nothing to re-file against",
                    nn.position, nn.plugin_id, nn.timestamp,
                ),
            }
        }
        println!(
            "\n  A nested appeal does NOT block a re-file: the duplicate check is a flat\n\
             match too, so it does not see these either. That is what leaves a window open\n\
             — and the window closes when the DENY ages out, not the appeal."
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
