//! `calib_export` — trust-calibration exporter for the sealed witness chain.
//!
//! Emits calibration records `{estimate, outcome, ...}` from hestia's
//! SQLCipher-sealed witness chain. `estimate` is the plugin's trust scalar (T3
//! average) that existed *before* the paired event — reconstructed by replaying
//! `EntityTrust::update_from_outcome` in chain order, capturing the pre-update
//! scalar. This is the `(trust-at-decision, outcome)` pair CBP's PRD-4 named.
//!
//! Two modes (`--mode`):
//!   • `outcome` (v1, default): one pair per `outcome` event; label = execution
//!     success. The live outcome stream is all-success (the gate filters failures
//!     upstream), so this axis is degenerate — a selection effect, not absence of
//!     failure.
//!   • `gate` (v2): recover the negatives the gate filters. Positives = outcome
//!     events (cleared the gate → 1); negatives = `policy_decision` warn/deny (0).
//!     The gate is rule-based and never reads trust, so calibrating trust against
//!     the gate decision is non-circular. (`warn` proceeds → also an outcome pair;
//!     that double-representation is tagged via `kind` — strict set = kind ∈
//!     {executed, deny}.)
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
    let mut mode = String::from("outcome");
    let mut wire_risk = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--out" | "-o" => {
                out_path = Some(PathBuf::from(
                    args.next().context("--out requires a path argument")?,
                ));
            }
            "--mode" | "-m" => {
                mode = args.next().context("--mode requires outcome|gate")?;
            }
            // Retrospective counterfactual: apply the daemon's warn/deny->trust
            // penalty (deny 0.5, warn 0.2) DURING replay, so the reconstructed
            // trust trajectory matches the deployed wiring. Falsifiable test of
            // "does feeding the risk signal into trust make it discriminate?".
            "--wire-risk" => {
                wire_risk = true;
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    let out_path = out_path.context("missing required --out <path.jsonl>")?;
    anyhow::ensure!(
        mode == "outcome" || mode == "gate" || mode == "reversal",
        "unknown --mode {mode:?} (expected: outcome | gate | reversal)"
    );

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

    // `outcome` mode (v1): one pair per outcome event, label = execution success.
    // `gate` mode (v2): recover the negatives the gate filters upstream. Positives
    // are the outcome events (the action cleared the gate and executed → label 1);
    // negatives are the `policy_decision` events (warn/deny → label 0), which never
    // become outcome events for a deny (blocked) — but a warn PROCEEDS, so a warned
    // action is ALSO an outcome pair. That double-representation is disclosed and
    // tagged via `kind` so a strict set (kind ∈ {executed, deny}) can drop it.
    // The gate is rule-based (command-pattern) and never reads trust, so
    // "does trust-at-decision predict gate-risk" is a non-circular test.
    let gate = mode == "gate";
    // `reversal` mode (v3): the JUDGMENT axis the gate calibration proved was
    // orthogonal-by-construction. Positives = outcome events (label 1, not
    // reversed); negatives = `reversal` events (label 0) — a delayed judgment that
    // the SUBJECT's work was reverted/rejected. Trust is reconstructed from
    // OUTCOMES ONLY (the reversal is NOT fed back), so the estimate is pure
    // execution-reliability and the test is non-circular: "does execution
    // reliability predict a judgment-reversal?" Unlike the rule-gate, judgment
    // quality is a persistent per-actor trait, so this CAN be predictive.
    let reversal = mode == "reversal";
    let mut n_pairs = 0u64;
    let mut n_exec = 0u64; // outcome events (gate mode: label 1)
    let mut n_success = 0u64; // of those, execution succeeded
    let mut n_warn = 0u64;
    let mut n_deny = 0u64;
    let mut n_reversal = 0u64;
    for e in &all {
        let is_outcome = e.event_type == "outcome";
        let is_decision = e.event_type == "policy_decision";
        let is_reversal = e.event_type == "reversal";
        if !is_outcome && !(gate && is_decision) && !(reversal && is_reversal) {
            continue;
        }
        // Reconstruct the daemon's post-rekey (instance, role) trust grain. Group
        // the replay on the SAME key the daemon uses so the reconstructed estimate
        // matches live role-scoped trust. A `reversal` event names the SUBJECT
        // (whose work was reversed) with `subject_*` fields — attribute to THAT
        // entity, not the reporter. outcome/decision events use the plain fields.
        let (id_key, role_key, instance_key) = if is_reversal {
            ("subject_plugin_id", "subject_role", "subject_instance_lct")
        } else {
            ("plugin_id", "role_lct", "instance_lct")
        };
        let plugin_id = e
            .event_data
            .get(id_key)
            .and_then(|v| v.as_str())
            .unwrap_or("anonymous")
            .to_string();
        let role_lct = e
            .event_data
            .get(role_key)
            .and_then(|v| v.as_str())
            .unwrap_or("role:constellation:member");
        let entity_key = match e.event_data.get(instance_key).and_then(|v| v.as_str()) {
            Some(inst) => format!("{inst}#{role_lct}"),
            None => format!("plugin:{plugin_id}#{role_lct}"),
        };
        let tool = e
            .event_data
            .get("tool_name")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let entry = trust
            .entry(entity_key.clone())
            .or_insert_with(|| EntityTrust::new(entity_key.clone()));

        // CAUSAL HONESTY: the estimate is the trust scalar as it exists BEFORE this
        // event is processed — for outcome events, before update_from_outcome; for
        // decision events, the trust as of this chain position (a decision never
        // mutates trust, matching the daemon).
        let estimate = entry.t3_average();
        let v3_pre = entry.v3_average();

        if is_outcome {
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
            let outcome = if gate || reversal {
                1 // gate: cleared the gate; reversal: this act was not (yet) reversed
            } else if success {
                1
            } else {
                0
            };
            let rec = serde_json::json!({
                "estimate": estimate,
                "outcome": outcome,
                "kind": if gate || reversal { "executed" } else { "outcome" },
                "success": success,
                "plugin": plugin_id,
                "role": role_lct,
                "entity": entity_key,
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
            n_exec += 1;
            if success {
                n_success += 1;
            }
        } else if is_reversal {
            // reversal mode: a JUDGMENT negative about the subject. estimate = the
            // subject's OUTCOMES-ONLY trust at this chain position (the reversal is
            // deliberately NOT fed back into trust → non-circular; the estimate is
            // pure execution-reliability). label 0; no trust update.
            let kind = e
                .event_data
                .get("kind")
                .and_then(|v| v.as_str())
                .unwrap_or("reversal");
            let rec = serde_json::json!({
                "estimate": estimate,
                "outcome": 0,
                "kind": format!("reversal:{kind}"),
                "plugin": plugin_id,
                "role": role_lct,
                "entity": entity_key,
                "ts": e.timestamp.to_rfc3339(),
                "chain_position": e.chain_position,
                "v3_pre": v3_pre,
            });
            writeln!(w, "{}", serde_json::to_string(&rec)?)?;
            n_pairs += 1;
            n_reversal += 1;
        } else {
            // gate mode only: a policy_decision (warn|deny) = a recovered negative.
            // estimate = trust-at-decision; label 0; trust is NOT updated (the
            // daemon only evolves trust on outcome events).
            let decision = e
                .event_data
                .get("decision")
                .and_then(|v| v.as_str())
                .unwrap_or("gated");
            let rec = serde_json::json!({
                "estimate": estimate,
                "outcome": 0,
                "kind": decision,
                "plugin": plugin_id,
                "role": role_lct,
                "entity": entity_key,
                "tool": tool,
                "ts": e.timestamp.to_rfc3339(),
                "chain_position": e.chain_position,
                "v3_pre": v3_pre,
            });
            writeln!(w, "{}", serde_json::to_string(&rec)?)?;
            n_pairs += 1;
            match decision {
                "warn" => n_warn += 1,
                "deny" => n_deny += 1,
                _ => {}
            }
            // Counterfactual replay: mirror the deployed daemon — a gate decision
            // lowers trust (asymmetric), deny stronger than warn. Applied AFTER the
            // estimate for THIS event is captured, so it only affects later events.
            if wire_risk {
                let m = match decision {
                    "deny" => 0.5,
                    "warn" => 0.2,
                    _ => 0.0,
                };
                if m > 0.0 {
                    entry.update_from_outcome(false, m);
                }
            }
        }
    }
    w.flush()?;
    drop(w);

    // Best-effort cleanup of the encrypted copy.
    let _ = std::fs::remove_file(&copy_db);
    let _ = std::fs::remove_dir(&tmp_dir);

    if gate {
        eprintln!(
            "calib_export[gate]: {} entries -> {} pairs across {} plugins: {} executed (label 1, {} exec-success) + {} warn + {} deny (label 0) -> {}",
            total_entries, n_pairs, trust.len(), n_exec, n_success, n_warn, n_deny, out_path.display()
        );
        eprintln!(
            "  NOTE: warn PROCEEDS, so ~{} warned actions are ALSO 'executed' pairs (double-represented). For the no-double-count strict set filter kind in {{executed, deny}}.",
            n_warn
        );
    } else if reversal {
        eprintln!(
            "calib_export[reversal]: {} entries -> {} pairs across {} entities: {} outcomes (label 1) + {} reversals (label 0, judgment negatives) -> {}",
            total_entries, n_pairs, trust.len(), n_exec, n_reversal, out_path.display()
        );
        eprintln!(
            "  NON-CIRCULAR: estimate = subject's OUTCOMES-ONLY trust (reversals NOT fed back). Test: does execution-reliability predict a judgment-reversal? N_reversal={} — treat below ~30 as directional only.",
            n_reversal
        );
    } else {
        eprintln!(
            "calib_export[outcome]: {} entries, {} outcome pairs ({} success / {} fail) across {} plugins -> {}",
            total_entries, n_pairs, n_success, n_pairs - n_success, trust.len(), out_path.display()
        );
    }
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
