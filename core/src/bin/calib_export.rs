//! `calib_export` — trust-calibration exporter for the sealed witness chain.
//!
//! Emits calibration records `{estimate, outcome, ...}` from hestia's
//! SQLCipher-sealed witness chain, one per `outcome` event. `estimate` is the
//! plugin's trust scalar (T3 average) that existed *before* the outcome it is
//! paired with — reconstructed by replaying `EntityTrust::update_from_outcome`
//! in chain order, capturing the pre-update scalar. This is the
//! `(trust-at-decision, outcome)` pair CBP's PRD-4 named.
//!
//! CAUSAL HONESTY: the estimate is always the trust value that existed BEFORE
//! the outcome — never post-update or final trust (that would postdate the
//! outcome). This mirrors exactly how the live daemon evolves trust
//! (`TrustStore::update` = get-or-neutral `EntityTrust` + one
//! `update_from_outcome` per outcome event), so the replay is faithful.
//!
//! Sealed-at-rest respected: the chain is opened in-process with the storage
//! key derived from the vault passphrase (same flow as the daemon). To avoid
//! SQLCipher single-writer lock contention with the LIVE daemon, we operate on
//! a byte-copy of the encrypted DB. Only the `{estimate, outcome, ...}`
//! projection is written out — the decrypted chain never touches disk.

use std::io::Write;
use std::path::PathBuf;

use anyhow::{Context, Result};
use hestia::storage::{storage_key, SqliteChainStore};
use hestia::vault::storage::default_hestia_home;
use web4_trust_core::EntityTrust;

fn main() -> Result<()> {
    let mut out_path: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--out" | "-o" => {
                out_path = Some(PathBuf::from(
                    args.next().context("--out requires a path argument")?,
                ));
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    let out_path = out_path.context("missing required --out <path.jsonl>")?;

    // Resolve home (HESTIA_HOME or ~/.hestia) and the passphrase.
    let home = match std::env::var("HESTIA_HOME") {
        Ok(h) if !h.is_empty() => PathBuf::from(h),
        _ => default_hestia_home().context("resolving hestia home")?,
    };
    let passphrase = read_passphrase(&home)?;

    // Derive the storage key from the REAL home (salt lives at <home>/.store-salt).
    let key = storage_key(&home, &passphrase).context("deriving storage key")?;

    // Copy the sealed DB to avoid lock contention with the live daemon
    // (SQLCipher/SQLite is single-writer). The copy is the encrypted bytes;
    // the key never leaves this process, plaintext never hits disk.
    let src_db = home.join("witness.db");
    let tmp_dir = std::env::temp_dir().join(format!("hestia-calib-{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir).context("creating temp copy dir")?;
    let copy_db = tmp_dir.join("witness.db");
    std::fs::copy(&src_db, &copy_db)
        .with_context(|| format!("copying sealed chain {}", src_db.display()))?;

    let store = SqliteChainStore::open(&copy_db, key)
        .context("opening sealed chain copy (wrong passphrase => AEAD/open error)")?;
    let total_entries = store.len().context("counting chain entries")?;

    // Read the full chain, ascending by chain_position. read_since(0, N) is the
    // ascending read path; page through in case of very large chains.
    let mut all: Vec<hestia::storage::ChainEntry> = Vec::new();
    let page = 50_000u64;
    let mut cursor = 0u64;
    loop {
        let batch = store
            .read_since(cursor, page)
            .context("reading chain entries")?;
        if batch.is_empty() {
            break;
        }
        cursor = batch.last().unwrap().chain_position;
        all.extend(batch);
        if all.len() as u64 >= total_entries {
            break;
        }
    }

    // Per-plugin trust replay in chain order. For each `outcome` event:
    //   1. FIRST capture the pre-update scalar (t3_average) as the estimate.
    //   2. THEN apply update_from_outcome(success, magnitude).
    use std::collections::HashMap;
    let mut trust: HashMap<String, EntityTrust> = HashMap::new();

    let mut file = std::fs::File::create(&out_path)
        .with_context(|| format!("creating output {}", out_path.display()))?;
    let mut w = std::io::BufWriter::new(&mut file);

    let mut n_pairs = 0u64;
    let mut n_success = 0u64;
    for e in &all {
        if e.event_type != "outcome" {
            continue;
        }
        let plugin_id = e
            .event_data
            .get("plugin_id")
            .and_then(|v| v.as_str())
            .unwrap_or("anonymous")
            .to_string();
        // Match the daemon's default (handler.rs): success=false, magnitude=0.5
        // when absent, so the reconstructed trajectory is byte-faithful.
        let success = e
            .event_data
            .get("success")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let magnitude = e
            .event_data
            .get("magnitude")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.5);
        let tool = e
            .event_data
            .get("tool_name")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let entry = trust
            .entry(plugin_id.clone())
            .or_insert_with(|| EntityTrust::new(format!("plugin:{plugin_id}")));

        // CAUSAL HONESTY: estimate is the PRE-update trust scalar.
        let estimate = entry.t3_average();
        let v3_pre = entry.v3_average();

        // Emit the projection (never the decrypted chain itself).
        let rec = serde_json::json!({
            "estimate": estimate,
            "outcome": if success { 1 } else { 0 },
            "plugin": plugin_id,
            "magnitude": magnitude,
            "tool": tool,
            "ts": e.timestamp.to_rfc3339(),
            "chain_position": e.chain_position,
            "v3_pre": v3_pre,
        });
        writeln!(w, "{}", serde_json::to_string(&rec)?)?;

        // THEN evolve trust — exactly as the daemon does.
        entry.update_from_outcome(success, magnitude);

        n_pairs += 1;
        if success {
            n_success += 1;
        }
    }
    w.flush()?;
    drop(w);

    // Best-effort cleanup of the encrypted copy.
    let _ = std::fs::remove_file(&copy_db);
    let _ = std::fs::remove_dir(&tmp_dir);

    eprintln!(
        "calib_export: {} chain entries, {} outcome pairs ({} success / {} fail) across {} plugins -> {}",
        total_entries,
        n_pairs,
        n_success,
        n_pairs - n_success,
        trust.len(),
        out_path.display()
    );
    Ok(())
}

/// Read the passphrase the same way the daemon can: `HESTIA_PASSPHRASE` env, or
/// the `<home>/.passphrase` file (the automation path this machine uses).
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
