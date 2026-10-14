//! `request_load` — how many requests the gate puts in front of a ruler, and who ends up ruling.
//!
//! ## Why
//!
//! dp, 2026-10-14: "current version of the gate creates a relative flood of scope and act requests
//! ... from human perspective this is a burden and will lead to disengagement. most of those are too
//! specific and too technical to deal with. i already have resorted to asking your local seat which
//! ones i should approve or deny. the human does not need to be in that loop." Before redesigning who
//! rules what, measure the load, per host, from the one record every host has: the witness chain.
//!
//! ## What it counts (AGGREGATE ONLY)
//!
//! For requests OPENED inside the window (`--days N`, default 7):
//!
//! * scope requests (`scope_requested`) and governance escalations (`gate_escalation_opened`):
//!   totals, per member, per rule (scope) or marker CLASS (escalation), per day, gate-opened vs
//!   member-asked, and how many had no admissible peer (so only the operator could rule);
//! * outcome: granted / refused / lapsed (no ruling and past `expires_at`) / withdrawn / open;
//! * who ruled: `operator`, `peer`, `delegate`, `asker` (the asker withdrew its own escalation),
//!   `other` — see [`classify_ruler`];
//! * time to ruling (median, p90) for the ruled ones;
//! * scope request path CLASS (never the path) — see [`classify_path`];
//! * re-asks: requests whose (member, path) was asked more than once in the window.
//!
//! It never prints a command, a path, a reason or a marker name: the cross-seat rule is counts only
//! (dp, 2026-10-14), and the output is meant to be posted fleet-wide.
//!
//! Sealed-at-rest is respected the way `appeal_floor` does it: the encrypted DB is snapshotted to a
//! temp copy, the key never leaves this process, plaintext never hits disk. Read-only: this bin
//! appends nothing to the chain.
//!
//! ```text
//! surface: request_load (read-only report)   act: none (no chain append, no state mutation)
//! S: low/reversible [construct: main — read path only, output is aggregate counts]
//! R: n/a   W: n/a [no act to authorize; passphrase-holder already holds the chain]
//! O: pass [construct: no side effect to order]   A: n/a [records nothing]
//! V: n/a
//! verdict: PASS
//! ```

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use hestia::storage::{SqliteChainStore, storage_key};
use hestia::vault::storage::default_hestia_home;
use serde_json::{Value, json};

/// Mirrors `plugins/_shared/hestia_gate_core.py`'s `UNPRICEABLE_PREFIX`. An unenumerated reach is
/// keyed on `UNENUMERATED_TARGET#<digest16>` (`hestia_single_gate._scope_request_path`).
const UNPRICEABLE_PREFIX: &str = "hestia:unpriceable:";

const TEMP_ROOTS: &[&str] = &["/tmp", "/var/tmp"];
const SYSTEM_ROOTS: &[&str] = &[
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/var", "/proc", "/sys", "/dev",
    "/boot", "/root", "/run", "/srv",
];

/// True when `path` is `root` or below it (a boundary match, not a string prefix).
fn under(path: &str, root: &str) -> bool {
    let root = root.trim_end_matches('/');
    !root.is_empty() && (path == root || path.starts_with(&format!("{root}/")))
}

/// The coarse class of a scope request's path. Order matters: the unenumerated sentinel first,
/// then temp roots (always in scope — a request for one is itself a finding), then the workspace,
/// then home dotdirs, then the rest of home, then system roots.
fn classify_path(path: &str, workspaces: &[String], home: &str) -> &'static str {
    if path.starts_with(UNPRICEABLE_PREFIX) {
        return if path[UNPRICEABLE_PREFIX.len()..].starts_with("unenumerated") {
            "unenumerated"
        } else {
            "unpriceable_other"
        };
    }
    if TEMP_ROOTS.iter().any(|r| under(path, r)) {
        return "temp_root";
    }
    if workspaces.iter().any(|w| under(path, w)) {
        return "workspace";
    }
    if !home.is_empty() && under(path, home) {
        let rest = &path[home.trim_end_matches('/').len()..];
        return if rest.starts_with("/.") { "home_dotdir" } else { "home_other" };
    }
    if path.starts_with("/mnt/") {
        return "mounted_drive";
    }
    if SYSTEM_ROOTS.iter().any(|r| under(path, r)) {
        return "system";
    }
    if !path.starts_with('/') {
        return "relative_or_unresolved";
    }
    "other"
}

/// The coarse class of a governance escalation's marker (a file name the gate protects).
fn classify_marker(marker: &str) -> &'static str {
    let m = marker.to_ascii_lowercase();
    let base = m.rsplit('/').next().unwrap_or(&m);
    if base.starts_with("hestia_") || base.contains("gate") || base.contains("law_inject") {
        "gate_code"
    } else if base.contains("manifest") {
        "gate_manifest"
    } else if base.contains("settings") || base.contains("hooks") || base.ends_with(".toml") {
        "harness_registration"
    } else if base.contains("policy") || base.contains("law") {
        "law_or_policy"
    } else if base.contains("claude.md") || base.contains("agents.md") || base.contains("memory") {
        "instructions_or_memory"
    } else {
        "other"
    }
}

/// Who ruled, from the fields the daemon writes. Scope rulings carry `granted_by` (`operator`,
/// `peer:<member>`, `delegate:<arbiter>`) and `via` (`operator_session`, `peer_not_same`,
/// `delegation`); escalation rulings carry `decided_by` (`operator` or a member id) and sometimes
/// `decided_via`. An escalation "decided" by its own asker is a withdrawal.
fn classify_ruler(by: Option<&str>, via: Option<&str>, asker: Option<&str>) -> &'static str {
    let by = by.unwrap_or("");
    let via = via.unwrap_or("");
    if by == "operator" || by.starts_with("operator ") || via == "operator_session" {
        return "operator";
    }
    if by.starts_with("delegate:") || via == "delegation" {
        return "delegate";
    }
    if by.starts_with("peer:") || via == "peer_not_same" {
        return "peer";
    }
    if !by.is_empty() && Some(by) == asker {
        return "asker";
    }
    if !by.is_empty() && !by.contains(' ') && !by.starts_with("lct:") {
        return "peer";
    }
    "other"
}

#[derive(Default)]
struct Req {
    kind: &'static str, // "scope" | "escalation"
    member: String,
    rule: String,  // scope: rule (gate-opened) or "member_asked"; escalation: marker class
    path_class: &'static str,
    path_key: String, // only for the re-ask join; never printed
    gate_opened: bool,
    no_peer: bool,
    opened: Option<DateTime<Utc>>,
    expires_at: Option<i64>,
    outcome: &'static str, // open | granted | refused | lapsed | withdrawn
    ruler: &'static str,
    ruled_at: Option<DateTime<Utc>>,
}

fn s<'a>(d: &'a Value, k: &str) -> Option<&'a str> {
    d.get(k).and_then(Value::as_str)
}

fn pct(sorted: &[i64], p: f64) -> Option<i64> {
    if sorted.is_empty() {
        return None;
    }
    let i = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    Some(sorted[i.min(sorted.len() - 1)])
}

fn bump(m: &mut BTreeMap<String, u64>, k: &str) {
    *m.entry(k.to_string()).or_default() += 1;
}

fn main() -> Result<()> {
    let mut days: i64 = 7;
    let mut json_path: Option<PathBuf> = None;
    let mut workspaces: Vec<String> = Vec::new();
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--days" => {
                days = args.next().context("--days requires a number")?.parse().context("--days must be an integer")?;
            }
            "--json" => json_path = Some(PathBuf::from(args.next().context("--json requires a path")?)),
            "--workspace" => workspaces.push(args.next().context("--workspace requires a path")?),
            "--help" | "-h" => {
                eprintln!(
                    "request_load [--days N] [--json PATH] [--workspace DIR]...\n\n\
                     Counts the scope requests and governance escalations opened in the last N days\n\
                     (default 7), how they ended and who ruled them. Aggregate counts only: no command,\n\
                     path, reason or marker is printed. Read-only; appends nothing to the chain.\n\
                     --workspace defaults to $HESTIA_WORKSPACE, else $HOME/ai-workspace."
                );
                return Ok(());
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    let home_dir = std::env::var("HOME").unwrap_or_default();
    if workspaces.is_empty() {
        match std::env::var("HESTIA_WORKSPACE") {
            Ok(w) if !w.is_empty() => workspaces.push(w),
            _ if !home_dir.is_empty() => workspaces.push(format!("{home_dir}/ai-workspace")),
            _ => {}
        }
    }

    let home = match std::env::var("HESTIA_HOME") {
        Ok(h) if !h.is_empty() => PathBuf::from(h),
        _ => default_hestia_home().context("resolving hestia home")?,
    };
    let passphrase = read_passphrase(&home)?;
    let key = storage_key(&home, &passphrase).context("deriving storage key")?;
    let src_db = home.join("witness.db");
    let tmp_dir = std::env::temp_dir().join(format!("hestia-request-load-{}", std::process::id()));
    std::fs::create_dir_all(&tmp_dir).context("creating temp copy dir")?;
    let copy_db = tmp_dir.join("witness.db");
    SqliteChainStore::backup_encrypted(&src_db, &copy_db, key)
        .with_context(|| format!("snapshotting sealed chain {}", src_db.display()))?;
    let store = SqliteChainStore::open(&copy_db, key)
        .context("opening sealed chain copy (wrong passphrase => AEAD/open error)")?;

    let now = Utc::now();
    let since = now - chrono::Duration::days(days);
    let mut reqs: HashMap<String, Req> = HashMap::new();
    let mut scanned = 0u64;
    let page = 50_000u64;
    let mut cursor = 0u64;
    loop {
        let batch = store.read_since(cursor, page).context("reading chain entries")?;
        if batch.is_empty() {
            break;
        }
        cursor = batch.last().expect("non-empty batch").chain_position;
        for e in &batch {
            scanned += 1;
            let d = &e.event_data;
            match e.event_type.as_str() {
                "scope_requested" if e.timestamp >= since => {
                    let Some(id) = s(d, "request_id").or_else(|| s(d, "id")) else { continue };
                    let path = s(d, "path").unwrap_or("");
                    let gate_opened = s(d, "origin") == Some("gate_deny");
                    let no_peer = gate_opened
                        && d.get("invited_peers").and_then(Value::as_array).is_some_and(|a| a.is_empty());
                    let member = s(d, "plugin_id").unwrap_or("?").to_string();
                    reqs.entry(format!("s:{id}")).or_insert(Req {
                        kind: "scope",
                        path_key: format!("{member}\u{0}{path}"),
                        member,
                        rule: if gate_opened { s(d, "rule").unwrap_or("?").to_string() } else { "member_asked".into() },
                        path_class: classify_path(path, &workspaces, &home_dir),
                        gate_opened,
                        no_peer,
                        opened: Some(e.timestamp),
                        expires_at: d.get("expires_at").and_then(Value::as_i64),
                        outcome: "open",
                        ruler: "",
                        ruled_at: None,
                    });
                }
                "scope_granted" | "scope_grant_intent" | "scope_refused" => {
                    let Some(id) = s(d, "request_id") else { continue };
                    if let Some(r) = reqs.get_mut(&format!("s:{id}")) {
                        if r.ruled_at.is_none() {
                            r.outcome = if e.event_type == "scope_refused" { "refused" } else { "granted" };
                            r.ruler = classify_ruler(s(d, "granted_by").or_else(|| s(d, "decided_by")),
                                                     s(d, "via").or_else(|| s(d, "decided_via")), None);
                            r.ruled_at = Some(e.timestamp);
                        }
                    }
                }
                "gate_escalation_opened" if e.timestamp >= since => {
                    let Some(id) = s(d, "escalation_id") else { continue };
                    reqs.entry(format!("e:{id}")).or_insert(Req {
                        kind: "escalation",
                        member: s(d, "plugin_id").unwrap_or("?").to_string(),
                        rule: classify_marker(s(d, "marker").unwrap_or("")).to_string(),
                        opened: Some(e.timestamp),
                        expires_at: d.get("expires_at").and_then(Value::as_i64),
                        outcome: "open",
                        gate_opened: true,
                        ..Default::default()
                    });
                }
                "gate_escalation_decided" => {
                    let Some(id) = s(d, "escalation_id") else { continue };
                    if let Some(r) = reqs.get_mut(&format!("e:{id}")) {
                        if r.ruled_at.is_none() {
                            let approved = s(d, "status") == Some("approved");
                            let ruler = classify_ruler(s(d, "decided_by"), s(d, "decided_via"), Some(&r.member));
                            r.outcome = if ruler == "asker" { "withdrawn" } else if approved { "granted" } else { "refused" };
                            r.ruler = ruler;
                            r.ruled_at = Some(e.timestamp);
                        }
                    }
                }
                "gate_escalation_expired" | "gate_escalation_withdrawn" => {
                    let Some(id) = s(d, "escalation_id") else { continue };
                    if let Some(r) = reqs.get_mut(&format!("e:{id}")) {
                        if r.ruled_at.is_none() {
                            r.outcome = if e.event_type == "gate_escalation_expired" { "lapsed" } else { "withdrawn" };
                            if r.outcome == "withdrawn" {
                                r.ruler = "asker";
                                r.ruled_at = Some(e.timestamp);
                            }
                        }
                    }
                }
                _ => {}
            }
        }
    }
    let _ = std::fs::remove_dir_all(&tmp_dir);

    // A request with no ruling and a past expiry lapsed: scope requests emit no expiry event.
    let now_secs = now.timestamp();
    for r in reqs.values_mut() {
        if r.outcome == "open" && r.expires_at.is_some_and(|x| x < now_secs) {
            r.outcome = "lapsed";
        }
    }
    let report = summarize(&reqs, days, scanned, &now, &workspaces);
    print_markdown(&report);
    if let Some(p) = json_path {
        std::fs::write(&p, serde_json::to_string_pretty(&report)?).with_context(|| format!("writing {}", p.display()))?;
        eprintln!("wrote {}", p.display());
    }
    Ok(())
}

fn summarize(reqs: &HashMap<String, Req>, days: i64, scanned: u64, now: &DateTime<Utc>, workspaces: &[String]) -> Value {
    let mut out = serde_json::Map::new();
    out.insert("generated_at".into(), json!(now.to_rfc3339()));
    out.insert("window_days".into(), json!(days));
    out.insert("chain_entries_scanned".into(), json!(scanned));
    out.insert("workspace_roots_counted".into(), json!(workspaces.len()));
    out.insert("ruler_classification".into(), json!(
        "operator: granted_by/decided_by 'operator' or via 'operator_session'; delegate: 'delegate:*' or via 'delegation'; \
         peer: 'peer:*', via 'peer_not_same', or another member id; asker: an escalation ruled by its own asker (a withdrawal); \
         other: anything else"));
    let mut path_key_counts: HashMap<&str, u64> = HashMap::new();
    for r in reqs.values().filter(|r| r.kind == "scope") {
        *path_key_counts.entry(r.path_key.as_str()).or_default() += 1;
    }
    for kind in ["scope", "escalation"] {
        let rs: Vec<&Req> = reqs.values().filter(|r| r.kind == kind).collect();
        let mut by_member = BTreeMap::new();
        let mut by_rule = BTreeMap::new();
        let mut by_day = BTreeMap::new();
        let mut by_outcome = BTreeMap::new();
        let mut by_ruler = BTreeMap::new();
        let mut by_path = BTreeMap::new();
        let mut by_outcome_ruler = BTreeMap::new();
        let mut latencies: Vec<i64> = Vec::new();
        let (mut gate_opened, mut no_peer, mut reasked) = (0u64, 0u64, 0u64);
        for r in &rs {
            bump(&mut by_member, &r.member);
            bump(&mut by_rule, &r.rule);
            if let Some(o) = r.opened {
                bump(&mut by_day, &o.format("%Y-%m-%d").to_string());
            }
            bump(&mut by_outcome, r.outcome);
            if !r.ruler.is_empty() {
                bump(&mut by_ruler, r.ruler);
                bump(&mut by_outcome_ruler, &format!("{}/{}", r.outcome, r.ruler));
            }
            if kind == "scope" {
                bump(&mut by_path, r.path_class);
                if path_key_counts.get(r.path_key.as_str()).copied().unwrap_or(0) > 1 {
                    reasked += 1;
                }
            }
            if let (Some(o), Some(t)) = (r.opened, r.ruled_at) {
                latencies.push((t - o).num_seconds());
            }
            gate_opened += r.gate_opened as u64;
            no_peer += r.no_peer as u64;
        }
        latencies.sort_unstable();
        let mut k = serde_json::Map::new();
        k.insert("total".into(), json!(rs.len()));
        k.insert("gate_opened".into(), json!(gate_opened));
        if kind == "scope" {
            k.insert("gate_opened_with_no_admissible_peer".into(), json!(no_peer));
            k.insert("by_path_class".into(), json!(by_path));
            k.insert("reasked_same_member_and_path".into(), json!(reasked));
        }
        k.insert("by_member".into(), json!(by_member));
        k.insert(if kind == "scope" { "by_rule" } else { "by_marker_class" }.into(), json!(by_rule));
        k.insert("by_day".into(), json!(by_day));
        k.insert("by_outcome".into(), json!(by_outcome));
        k.insert("by_ruler".into(), json!(by_ruler));
        k.insert("by_outcome_and_ruler".into(), json!(by_outcome_ruler));
        k.insert("ruled_count".into(), json!(latencies.len()));
        k.insert("time_to_ruling_secs".into(), json!({
            "median": pct(&latencies, 0.5), "p90": pct(&latencies, 0.9),
        }));
        out.insert(kind.into(), Value::Object(k));
    }
    Value::Object(out)
}

fn print_markdown(r: &Value) {
    println!("## Request load — last {} days (aggregate only)\n", r["window_days"]);
    println!("- generated {}; {} chain entries scanned\n", r["generated_at"].as_str().unwrap_or(""), r["chain_entries_scanned"]);
    for kind in ["scope", "escalation"] {
        let k = &r[kind];
        println!("### {} ({} opened, {} by the gate)\n", if kind == "scope" { "Scope requests" } else { "Governance escalations" },
                 k["total"], k["gate_opened"]);
        if kind == "scope" {
            println!("- gate-opened with no admissible peer (operator only): {}", k["gate_opened_with_no_admissible_peer"]);
            println!("- re-asked (same member and path more than once): {}", k["reasked_same_member_and_path"]);
        }
        let t = &k["time_to_ruling_secs"];
        println!("- ruled: {}; time to ruling median {} s, p90 {} s", k["ruled_count"], t["median"], t["p90"]);
        let facets: &[&str] = if kind == "scope" {
            &["by_outcome", "by_ruler", "by_outcome_and_ruler", "by_path_class", "by_rule", "by_member", "by_day"]
        } else {
            &["by_outcome", "by_ruler", "by_outcome_and_ruler", "by_marker_class", "by_member", "by_day"]
        };
        for f in facets {
            let parts: Vec<String> = k[*f].as_object().map(|m| m.iter().map(|(a, b)| format!("{a} {b}")).collect()).unwrap_or_default();
            println!("- {}: {}", f.trim_start_matches("by_").replace('_', " "), if parts.is_empty() { "—".into() } else { parts.join(", ") });
        }
        println!();
    }
    println!("Who ruled: {}", r["ruler_classification"].as_str().unwrap_or(""));
}

fn read_passphrase(home: &std::path::Path) -> Result<String> {
    if let Ok(pp) = std::env::var("HESTIA_PASSPHRASE") {
        if !pp.is_empty() {
            return Ok(pp);
        }
    }
    let pf = home.join(".passphrase");
    let raw = std::fs::read_to_string(&pf).with_context(|| format!("reading passphrase file {}", pf.display()))?;
    let pp = raw.trim_end_matches(['\n', '\r']).to_string();
    anyhow::ensure!(!pp.is_empty(), "passphrase file is empty");
    Ok(pp)
}

#[cfg(test)]
mod tests {
    use super::*;

    const WS: &str = "/home/u/ai-workspace";
    const HOME: &str = "/home/u";

    fn pc(p: &str) -> &'static str {
        classify_path(p, &[WS.to_string()], HOME)
    }

    #[test]
    fn paths_fall_in_their_coarse_class() {
        assert_eq!(pc("hestia:unpriceable:unenumerated#0123456789abcdef"), "unenumerated");
        assert_eq!(pc("hestia:unpriceable:something"), "unpriceable_other");
        assert_eq!(pc("/tmp/x"), "temp_root");
        assert_eq!(pc("/var/tmp"), "temp_root");
        assert_eq!(pc("/home/u/ai-workspace/hestia/x.py"), "workspace");
        assert_eq!(pc("/home/u/ai-workspace"), "workspace");
        assert_eq!(pc("/home/u/.hestia/deploy.hold"), "home_dotdir");
        assert_eq!(pc("/home/u/notes.txt"), "home_other");
        assert_eq!(pc("/mnt/c/exe"), "mounted_drive");
        assert_eq!(pc("/etc/hostname"), "system");
        assert_eq!(pc("/var/log/syslog"), "system");
        assert_eq!(pc("relative/x"), "relative_or_unresolved");
        assert_eq!(pc("/nix/store"), "other");
    }

    #[test]
    fn a_root_matches_on_a_boundary_not_a_prefix() {
        assert_eq!(pc("/tmpfoo/x"), "other");
        assert_eq!(pc("/home/u/ai-workspace2/x"), "home_other");
        assert_eq!(pc("/home/user2/x"), "other");
    }

    #[test]
    fn rulers_are_classified_from_the_daemons_fields() {
        assert_eq!(classify_ruler(Some("operator"), Some("operator_session"), None), "operator");
        assert_eq!(classify_ruler(Some("operator"), None, Some("codex")), "operator");
        assert_eq!(classify_ruler(Some("peer:codex"), Some("peer_not_same"), None), "peer");
        assert_eq!(classify_ruler(Some("delegate:legion-claude"), Some("delegation"), None), "delegate");
        assert_eq!(classify_ruler(Some("codex"), None, Some("claude-code")), "peer");
        assert_eq!(classify_ruler(Some("claude-code"), None, Some("claude-code")), "asker");
        assert_eq!(classify_ruler(Some("operator (k)"), None, None), "operator");
        assert_eq!(classify_ruler(Some("lct:web4:x"), None, None), "other");
        assert_eq!(classify_ruler(None, None, None), "other");
        assert_eq!(classify_ruler(Some("a b"), None, None), "other");
    }

    #[test]
    fn markers_fall_in_their_coarse_class() {
        assert_eq!(classify_marker("hestia_gate_core.py"), "gate_code");
        assert_eq!(classify_marker("law_inject.py"), "gate_code");
        assert_eq!(classify_marker("hooks-gt/_shared/manifest.json"), "gate_manifest");
        assert_eq!(classify_marker("settings.json"), "harness_registration");
        assert_eq!(classify_marker("config.toml"), "harness_registration");
        assert_eq!(classify_marker("CLAUDE.md"), "instructions_or_memory");
        assert_eq!(classify_marker("whatever.bin"), "other");
    }

    #[test]
    fn percentiles_are_nearest_rank() {
        assert_eq!(pct(&[], 0.5), None);
        assert_eq!(pct(&[5], 0.9), Some(5));
        assert_eq!(pct(&[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5), Some(6));
        assert_eq!(pct(&[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9), Some(9));
    }
}
