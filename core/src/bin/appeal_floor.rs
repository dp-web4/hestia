//! `appeal_floor` — report unruled-appeal backlog by chain depth.
//!
//! Filing, discovery, and arbitration are windowless (#610). `DEFAULT_WINDOW` is therefore a
//! reporting bucket, never a ruling boundary: an `aged_unruled` appeal remains open, appears in
//! `hestia_open_appeals`, and can be ruled through `hestia_arbitrate_appeal`. This report exists
//! to prioritize old work, not to pronounce it terminal.
//!
//! ## Method
//!
//! Full-chain scan, ascending. Join `appeal.deny_hash` against
//! `adjudication.about_deny_hash` with `deny_refs_agree`, the one deny-reference rule the
//! queue, the ruling path and `derivation.rs` share (#610 review). An exact join called a
//! legacy prefix ruled under the full hash unruled while the queue had closed it. A legacy
//! reference the ruling path cannot reach (`deny_ref_rulable`: under 8 hex characters) is
//! reported apart, as needing a canonical re-file, not as backlog. Survivors are
//! unruled and are split at `head - reporting_window` to distinguish older backlog from recent
//! work. Legacy nested appeals remain a separate shape diagnostic because their missing flat
//! `deny_hash` genuinely prevents arbitration.
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
use hestia::storage::chain::{deny_ref_rulable, deny_refs_agree};
use hestia::storage::{SqliteChainStore, storage_key};
use hestia::vault::storage::default_hestia_home;

/// Backlog-reporting bucket only. This has no filing, discovery, or arbitration semantics.
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
/// `hestia_request_witness("appeal", ...)` before `hestia_appeal` existed, so its `deny_hash`
/// sits under `data` and the ruling path, queue, and `derivation.rs` all match it FLAT and miss.
///
/// The nested appeal does not block a flat re-file. With whole-chain filing (#610), that remedy
/// remains available whenever the cited deny exists on the chain; chain depth is reporting
/// telemetry, not a deadline. Two historical disputes were re-filed flat and ruled UPHELD on
/// 2026-07-28 (chain 70339/70340), which is the regression fixture below.
struct Nested {
    position: u64,
    plugin_id: String,
    timestamp: String,
    /// `deny_hash` recovered from `data.deny_hash`, if it is there at all.
    recovered_deny: Option<String>,
}

/// What is true of a nested appeal's underlying DISPUTE, as distinct from the nested ENTRY.
/// A known, unruled deny is `Refilable` at any chain depth. `Ruled` closes the dispute but does
/// not heal the nested entry's shape; `Unrecoverable` means no cited deny can be found.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum NestedDisposition {
    /// The cited deny carries an `adjudication`. The dispute was heard. Nobody's
    /// job — and emphatically not a deadline.
    Ruled,
    /// No adjudication, and the deny is still inside the window. THIS is the
    /// deadline: the live, actionable state this bin was built to surface.
    Refilable,
    /// No `deny_hash` survives in the payload, or the deny is not on this chain:
    /// there is nothing to re-file AGAINST. Terminal for a different reason.
    Unrecoverable,
}

impl NestedDisposition {
    fn as_str(self) -> &'static str {
        match self {
            Self::Ruled => "ruled",
            Self::Refilable => "refilable",
            Self::Unrecoverable => "unrecoverable",
        }
    }

    fn needs_refiling(self) -> bool {
        matches!(self, Self::Refilable)
    }
}

/// Position of the latest adjudication whose `about_deny_hash` names the same deny as
/// `deny_ref` under the one deny-reference rule. Linear in the rulings, which is fine for a
/// read-only report; an exact `HashMap` key is what made a ruled legacy prefix read unruled.
fn ruled_position(deny_ref: &str, ruled: &[(String, u64)]) -> Option<u64> {
    ruled
        .iter()
        .filter(|(about, _)| deny_refs_agree(about, deny_ref))
        .map(|&(_, pos)| pos)
        .max()
}

/// Pure so the distinction between a malformed nested entry and its underlying dispute is
/// testable without a chain.
fn classify_nested(
    recovered_deny: Option<&str>,
    ruled: &[(String, u64)],
    deny_pos: Option<u64>,
) -> NestedDisposition {
    let Some(hash) = recovered_deny else {
        return NestedDisposition::Unrecoverable;
    };
    if ruled_position(hash, ruled).is_some() {
        return NestedDisposition::Ruled;
    }
    match deny_pos {
        Some(_) => NestedDisposition::Refilable,
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
                     Enumerates appeals with no adjudication, split into older and recent\n\
                     backlog by a reporting-only chain-depth window. Every listed flat appeal\n\
                     remains open and rulable; the window is not an arbitration boundary.\n\
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
    let mut ruled: Vec<(String, u64)> = Vec::new();
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
                        ruled.push((about.to_string(), e.chain_position));
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
    // A legacy reference the ruling path cannot reach is not backlog: it is excluded from the
    // open queue by the same rule, and its remedy is a canonical re-file.
    let (unruled, not_rulable): (Vec<&Appeal>, Vec<&Appeal>) = appeals
        .iter()
        .filter(|a| ruled_position(&a.deny_hash, &ruled).is_none())
        .partition(|a| deny_ref_rulable(&a.deny_hash));
    // The partition is only a backlog-reporting bucket. Both sets remain open and rulable.
    let (aged, recent): (Vec<&&Appeal>, Vec<&&Appeal>) =
        unruled.iter().partition(|a| a.position <= floor);

    let nested_dispositions: Vec<NestedDisposition> = nested
        .iter()
        .map(|nn| {
            let deny_pos = nn
                .recovered_deny
                .as_ref()
                .and_then(|h| positions.get(h).copied());
            classify_nested(nn.recovered_deny.as_deref(), &ruled, deny_pos)
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
                "deny_entries_from_head": deny_pos.map(|p| head.saturating_sub(p)),
                "disposition": disp.as_str(),
                // The adjudication's own position, so "ruled" is a claim the
                // reader can follow to an entry rather than take on trust.
                "ruled_at_position": nn
                    .recovered_deny
                    .as_ref()
                    .and_then(|h| ruled_position(h, &ruled)),
                "needs_refiling": disp.needs_refiling(),
            })
        })
        .collect();
    let nested_open = nested_dispositions
        .iter()
        .filter(|d| d.needs_refiling())
        .count();

    if json_out {
        let rows: Vec<_> = aged
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
                "reporting_window": window,
                "reporting_floor": floor,
                "ruling_window": null,
                "appeals_total": appeals.len(),
                "adjudications_total": ruled.len(),
                "unruled_total": unruled.len(),
                "recent_unruled": recent.len(),
                "aged_unruled": rows,
                "aged_unruled_remain_rulable": true,
                "legacy_ref_not_rulable": not_rulable
                    .iter()
                    .map(|a| serde_json::json!({
                        "deny_hash": a.deny_hash,
                        "appeal_entry": a.entry_hash,
                        "chain_position": a.position,
                        "appellant": a.plugin_id,
                        "remedy": "re-file with hestia_appeal and the deny's full hash",
                    }))
                    .collect::<Vec<_>>(),
                "nested_inert": nested_rows,
                "nested_total": nested_rows.len(),
                "nested_needing_refiling": nested_open,
            }))?
        );
        return Ok(());
    }

    println!("appeal_floor — whole-chain backlog scan of {total} entries");
    println!("  head position:        {head}");
    println!("  reporting window:     {window}  (older backlog below {floor}; NOT a ruling boundary)");
    println!("  appeal entries:       {}", appeals.len());
    println!("  adjudications:        {}", ruled.len());
    println!("  unruled appeals:      {}  (all remain rulable)", unruled.len());
    println!("    recent backlog:     {}", recent.len());
    println!("    older backlog:      {}", aged.len());
    println!(
        "  legacy refs under {} hex chars: {}  (not rulable; re-file with the full hash)",
        hestia::storage::chain::MIN_LEGACY_DENY_PREFIX,
        not_rulable.len()
    );
    if !aged.is_empty() {
        println!("\nOLDER UNRULED APPEALS — still discoverable and rulable:");
        for a in &aged {
            println!(
                "  pos {:>7} ({:>6} beyond reporting floor)  {}  appellant={} role={}  filed={}",
                a.position,
                floor.saturating_sub(a.position),
                &a.deny_hash[..a.deny_hash.len().min(16)],
                a.plugin_id,
                a.role_lct,
                a.timestamp,
            );
        }
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
            let deny_depth = row.get("deny_entries_from_head").and_then(|v| v.as_u64());
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
                    "NEEDS RE-FILING — deny at {} is on the chain and remains actionable via \
                     hestia_appeal at any depth (currently {} entries from head)",
                    deny_pos.map_or("?".to_string(), |p| p.to_string()),
                    deny_depth.unwrap_or(0),
                ),
                NestedDisposition::Unrecoverable => println!(
                    "no recoverable deny_hash in the payload — nothing to re-file against"
                ),
            }
        }
        println!(
            "\n  NEEDING RE-FILING: {nested_open} of {}.\n\
             \x20 A nested appeal does NOT block a flat re-file; whole-chain filing keeps that\n\
             remedy available whenever the cited deny exists, regardless of chain depth.\n\
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

    fn live_fixture() -> (Vec<(String, u64)>, HashMap<String, u64>) {
        // adjudication.about_deny_hash -> adjudication position
        let ruled = vec![
            (DENY_A.to_string(), 70339), // eba318fa, upheld
            (DENY_B.to_string(), 70340), // d36e20d7, upheld
        ];
        // deny_hash -> deny position
        let positions = HashMap::from([(DENY_A.to_string(), 62958), (DENY_B.to_string(), 63406)]);
        (ruled, positions)
    }

    #[test]
    fn a_ruled_dispute_never_needs_refiling() {
        let (ruled, positions) = live_fixture();
        for (deny, appeal_pos) in [(DENY_A, 62963u64), (DENY_B, 63408)] {
            let disp = classify_nested(Some(deny), &ruled, positions.get(deny).copied());
            assert_eq!(
                disp,
                NestedDisposition::Ruled,
                "nested appeal at {appeal_pos} cites an adjudicated deny"
            );
            assert!(!disp.needs_refiling());
        }
    }

    #[test]
    fn an_unruled_deny_on_the_chain_needs_refiling() {
        let (_, positions) = live_fixture();
        let empty = Vec::new();
        let disp = classify_nested(Some(DENY_A), &empty, positions.get(DENY_A).copied());
        assert_eq!(disp, NestedDisposition::Refilable);
        assert!(disp.needs_refiling());
    }

    #[test]
    fn chain_depth_does_not_make_an_unruled_deny_unrecoverable() {
        let empty = Vec::new();
        let disp = classify_nested(Some(DENY_A), &empty, Some(1));
        assert_eq!(disp, NestedDisposition::Refilable, "#610: depth is not a deadline");
        assert!(disp.needs_refiling());
    }

    #[test]
    fn no_recoverable_deny_hash_is_unrecoverable() {
        let (ruled, _) = live_fixture();
        assert_eq!(classify_nested(None, &ruled, None), NestedDisposition::Unrecoverable);
        assert_eq!(
            classify_nested(Some("deadbeef"), &ruled, None),
            NestedDisposition::Unrecoverable
        );
    }

    #[test]
    fn a_ruling_outlives_the_reporting_window() {
        let (ruled, _) = live_fixture();
        assert_eq!(classify_nested(Some(DENY_A), &ruled, Some(1)), NestedDisposition::Ruled);
    }

    /// NOVA's #610 review, finding (c): a lower-case legacy prefix ruled under the full hash
    /// was closed by the queue SQL but reported unruled here by an exact join. The join is now
    /// the one deny-reference rule, in both directions and either case.
    #[test]
    fn nova_610_c_a_ruled_legacy_prefix_is_ruled_here_too() {
        let (ruled, _) = live_fixture();
        assert_eq!(ruled_position(&DENY_A[..12], &ruled), Some(70339), "legacy prefix, full ruling");
        assert_eq!(ruled_position(&DENY_A[..12].to_ascii_uppercase(), &ruled), Some(70339));
        let prefix_ruling = vec![(DENY_B[..10].to_string(), 9)];
        assert_eq!(ruled_position(DENY_B, &prefix_ruling), Some(9), "full appeal, legacy ruling");
        assert_eq!(ruled_position(&DENY_A[..6], &ruled), None, "under 8 chars is not honoured");
        assert!(!deny_ref_rulable(&DENY_A[..6]) && deny_ref_rulable(&DENY_A[..8]));
    }
}
