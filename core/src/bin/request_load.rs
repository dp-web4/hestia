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
//! * outcome: granted / refused / incomplete / lapsed / withdrawn / open;
//! * who ruled: `operator`, `peer`, `delegate`, `asker` (the asker withdrew its own escalation),
//!   `other` — see [`classify_ruler`];
//! * time to ruling (median, p90) for the ruled ones;
//! * scope request path CLASS (never the path) — see [`classify_path`];
//! * re-asks: requests whose (member, path) was asked more than once in the window.
//!
//! It does not print commands, paths, reasons or arbitrary marker names. Member identifiers and
//! small counts remain in the output; their suitability for sharing needs a privacy decision.
//! A later refusal lift or grant edit does not change the reported outcome or re-ask split;
//! chain-wide lift/edit counts are not linked to individual requests.
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
const OUTCOME_LIMITATION: &str = "A later refusal lift or grant edit does not change a request's reported outcome or its re-ask classification; chain-wide lift/edit counts are not linked to requests.";
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

/// Only explicitly public product names may leave this process. An arbitrary
/// first component can itself be sensitive; bucket it instead of printing it.
fn home_dotdir_name(path: &str, home: &str) -> Option<String> {
    let home = home.trim_end_matches('/');
    if home.is_empty() || !under(path, home) {
        return None;
    }
    let first = path[home.len()..].trim_start_matches('/').split('/').next().unwrap_or("");
    if !first.starts_with('.') {
        return None;
    }
    const PUBLIC_NAMES: &[&str] = &[".hestia", ".claude", ".codex"];
    Some(if PUBLIC_NAMES.contains(&first) { first } else { "other" }.to_string())
}

/// Governance file and directory names the gate itself publishes (`hestia_governance_closure`'s
/// `LITERAL_FLOOR`: `files_anywhere`, `files_hooks_only`, the basenames of `exact_paths`, and the
/// `dir_markers` as the closure spells them). A marker in the `other` class is broken down by its
/// basename ONLY when it is one of these; anything else stays `other`, so no member-chosen name
/// can reach the report.
const PUBLISHED_GOVERNANCE_NAMES: &[&str] = &[
    "hestia_gate_core.py", "hestia_gate_mechanism.py", "hestia_governance_closure.py",
    "gate_self_protection_test.py", "hestia_single_gate.py", "web4-hub.service",
    "ratified-build.json", "ratify-build.sh", "pre_tool_use.py", "society_pre_tool_use.py",
    "post_tool_use.py", "witness.py", "law_inject.py", "before_tool.py", "hub",
    "install-members.sh", "settings.json", "settings.local.json", "config.toml",
    "plugins/*/hooks", "plugins/_shared", "hestia/hooks",
];

/// The published name a marker matches, or `other`.
fn published_marker_name(marker: &str) -> &'static str {
    let m = marker.trim_end_matches('/');
    if let Some(n) = PUBLISHED_GOVERNANCE_NAMES.iter().find(|n| n.contains('/') && (m == **n || m.ends_with(&format!("/{n}")))) {
        return n;
    }
    let base = m.rsplit('/').next().unwrap_or(m);
    PUBLISHED_GOVERNANCE_NAMES.iter().find(|n| !n.contains('/') && base == **n).copied().unwrap_or("other")
}

/// Witness callers can name non-reserved event types. Do not print arbitrary
/// event names just because they contain `scope`.
fn public_event_type(event: &str) -> Option<&'static str> {
    match event {
        "gate_escalation_opened" => Some("gate_escalation_opened"),
        "scope_requested" => Some("scope_requested"),
        "scope_grant_intent" => Some("scope_grant_intent"),
        "scope_granted" => Some("scope_granted"),
        "scope_refused" => Some("scope_refused"),
        "scope_refusal_lift_intent" => Some("scope_refusal_lift_intent"),
        "scope_refusal_lifted" => Some("scope_refusal_lifted"),
        "scope_grant_edit_intent" => Some("scope_grant_edit_intent"),
        "scope_grant_edited" => Some("scope_grant_edited"),
        "scope_revoked" => Some("scope_revoked"),
        "scope_standing_revoked" => Some("scope_standing_revoked"),
        "scope_standing_promote_intent" => Some("scope_standing_promote_intent"),
        "scope_reach_change_intent" => Some("scope_reach_change_intent"),
        "scope_reach_changed" => Some("scope_reach_changed"),
        "scope_reassign_intent" => Some("scope_reassign_intent"),
        "scope_reassigned" => Some("scope_reassigned"),
        "scope_reroot_intent" => Some("scope_reroot_intent"),
        "scope_rerooted" => Some("scope_rerooted"),
        "scope_once_reserved" => Some("scope_once_reserved"),
        "scope_once_released" => Some("scope_once_released"),
        "scope_once_spent" => Some("scope_once_spent"),
        _ if event.contains("scope") => Some("other_scope_event"),
        _ => None,
    }
}

fn public_scope_rule(rule: &str) -> &'static str {
    match rule {
        "mrh.path" => "mrh.path",
        "mrh.command" => "mrh.command",
        _ => "other",
    }
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
    home_dotdir: Option<String>, // first component under $HOME, for the home_dotdir class only
    other_marker: Option<&'static str>, // published name, for the escalation `other` class only
    gate_opened: bool,
    // None means the opening event did not carry a valid invitation list;
    // absence of evidence must not be counted as an available peer.
    no_peer: Option<bool>,
    opened: Option<DateTime<Utc>>,
    opened_position: Option<u64>,
    expires_at: Option<i64>,
    outcome: &'static str, // open | incomplete | granted | refused | lapsed | withdrawn
    ruler: &'static str,
    ruled_at: Option<DateTime<Utc>>,
    ruled_position: Option<u64>,
}

fn s<'a>(d: &'a Value, k: &str) -> Option<&'a str> {
    d.get(k).and_then(Value::as_str)
}

/// The opening-time invitation list is evidence about that instant only.
/// Missing or malformed historical fields do not establish peer eligibility.
fn no_peer_at_open(gate_opened: bool, data: &Value) -> Option<bool> {
    if !gate_opened {
        return None;
    }
    let invited = data.get("invited_peers")?.as_array()?;
    if !invited.iter().all(|member| member.as_str().is_some_and(|id| !id.trim().is_empty())) {
        return None;
    }
    Some(invited.is_empty())
}

/// Apply one scope event to a tracked request. Kept separate so synthetic
/// sequences exercise the actual report logic without opening a live chain.
fn observe_scope_outcome(r: &mut Req, event: &str, d: &Value, at: DateTime<Utc>, position: u64) {
    if r.ruled_at.is_some() {
        return;
    }
    if event == "scope_grant_intent" {
        // Intent alone proves neither a committed grant nor a failure. A
        // later terminal event can still resolve it, even after expiry.
        r.outcome = "incomplete";
        return;
    }
    if matches!(event, "scope_granted" | "scope_refused") {
        r.outcome = if event == "scope_refused" { "refused" } else { "granted" };
        r.ruler = classify_ruler(s(d, "granted_by").or_else(|| s(d, "decided_by")),
                                 s(d, "via").or_else(|| s(d, "decided_via")), None);
        r.ruled_at = Some(at);
        r.ruled_position = Some(position);
    }
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

fn snapshot_tempdir() -> Result<tempfile::TempDir> {
    let mut builder = tempfile::Builder::new();
    builder.prefix("hestia-request-load-");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().context("creating private temp copy dir")
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
    // An exclusively created directory is ours to clean up; never adopt a
    // predictable existing path that could alias the source or contain data.
    let tmp_dir = snapshot_tempdir()?;
    let copy_db = tmp_dir.path().join("witness.db");
    SqliteChainStore::backup_encrypted(&src_db, &copy_db, key)
        .with_context(|| format!("snapshotting sealed chain {}", src_db.display()))?;
    let store = SqliteChainStore::open(&copy_db, key)
        .context("opening sealed chain copy (wrong passphrase => AEAD/open error)")?;

    let now = Utc::now();
    let since = now - chrono::Duration::days(days);
    let mut reqs: HashMap<String, Req> = HashMap::new();
    // Chain-wide (not windowed): known scope event types and the escalation-opened
    // event, with first/last times. Unknown scope-like names are one bucket because
    // a witness caller may choose an event name containing arbitrary content.
    let mut type_census: BTreeMap<String, (u64, DateTime<Utc>, DateTime<Utc>)> = BTreeMap::new();
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
            if let Some(kind) = public_event_type(&e.event_type) {
                let c = type_census.entry(kind.to_string()).or_insert((0, e.timestamp, e.timestamp));
                c.0 += 1;
                c.1 = c.1.min(e.timestamp);
                c.2 = c.2.max(e.timestamp);
            }
            let d = &e.event_data;
            match e.event_type.as_str() {
                "scope_requested" if e.timestamp >= since => {
                    let Some(id) = s(d, "request_id").or_else(|| s(d, "id")) else { continue };
                    let path = s(d, "path").unwrap_or("");
                    let gate_opened = s(d, "origin") == Some("gate_deny");
                    let no_peer = no_peer_at_open(gate_opened, d);
                    let member = s(d, "plugin_id").unwrap_or("?").to_string();
                    reqs.entry(format!("s:{id}")).or_insert(Req {
                        kind: "scope",
                        path_key: format!("{member}\u{0}{path}"),
                        member,
                        rule: if gate_opened { public_scope_rule(s(d, "rule").unwrap_or("")).into() } else { "member_asked".into() },
                        path_class: classify_path(path, &workspaces, &home_dir),
                        home_dotdir: home_dotdir_name(path, &home_dir),
                        other_marker: None,
                        gate_opened,
                        no_peer,
                        opened: Some(e.timestamp),
                        opened_position: Some(e.chain_position),
                        expires_at: d.get("expires_at").and_then(Value::as_i64),
                        outcome: "open",
                        ruler: "",
                        ruled_at: None,
                        ruled_position: None,
                    });
                }
                "scope_granted" | "scope_grant_intent" | "scope_refused" => {
                    let Some(id) = s(d, "request_id") else { continue };
                    if let Some(r) = reqs.get_mut(&format!("s:{id}")) {
                        observe_scope_outcome(r, &e.event_type, d, e.timestamp, e.chain_position);
                    }
                }
                "gate_escalation_opened" if e.timestamp >= since => {
                    let Some(id) = s(d, "escalation_id") else { continue };
                    let marker = s(d, "marker").unwrap_or("");
                    let class = classify_marker(marker);
                    reqs.entry(format!("e:{id}")).or_insert(Req {
                        kind: "escalation",
                        member: s(d, "plugin_id").unwrap_or("?").to_string(),
                        rule: class.to_string(),
                        other_marker: (class == "other").then(|| published_marker_name(marker)),
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
    // A request with no ruling and a past expiry lapsed: scope requests emit no expiry event.
    let now_secs = now.timestamp();
    for r in reqs.values_mut() {
        if r.outcome == "open" && r.expires_at.is_some_and(|x| x < now_secs) {
            r.outcome = "lapsed";
        }
    }
    let mut report = summarize(&reqs, days, scanned, &now, &workspaces);
    report["chain_wide_event_types"] = json!(type_census.iter().map(|(k, (n, a, b))| {
        (k.clone(), json!({"count": n, "first": a.to_rfc3339(), "last": b.to_rfc3339()}))
    }).collect::<serde_json::Map<_, _>>());
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
    out.insert("outcome_limitation".into(), json!(OUTCOME_LIMITATION));
    out.insert("ruler_classification".into(), json!(
        "operator: granted_by/decided_by 'operator' or via 'operator_session'; delegate: 'delegate:*' or via 'delegation'; \
         peer: 'peer:*', via 'peer_not_same', or another member id; asker: an escalation ruled by its own asker (a withdrawal); \
         other: anything else"));
    let mut groups: HashMap<&str, Vec<&Req>> = HashMap::new();
    for r in reqs.values().filter(|r| r.kind == "scope") {
        groups.entry(r.path_key.as_str()).or_default().push(r);
    }
    let reasks = reask_split(groups.into_values().collect());
    for kind in ["scope", "escalation"] {
        let rs: Vec<&Req> = reqs.values().filter(|r| r.kind == kind).collect();
        let mut by_member = BTreeMap::new();
        let mut by_rule = BTreeMap::new();
        let mut by_day = BTreeMap::new();
        let mut by_outcome = BTreeMap::new();
        let mut by_ruler = BTreeMap::new();
        let mut by_path = BTreeMap::new();
        let mut by_outcome_ruler = BTreeMap::new();
        let mut by_sub = BTreeMap::new();
        let mut latencies: Vec<i64> = Vec::new();
        let (mut gate_opened, mut no_peer, mut peer_invited, mut peer_unknown) = (0u64, 0u64, 0u64, 0u64);
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
            if let Some(h) = r.home_dotdir.as_deref().filter(|_| r.path_class == "home_dotdir") {
                bump(&mut by_sub, h);
            }
            if let Some(n) = r.other_marker {
                bump(&mut by_sub, n);
            }
            if kind == "scope" {
                bump(&mut by_path, r.path_class);
            }
            if let (Some(o), Some(t)) = (r.opened, r.ruled_at) {
                latencies.push((t - o).num_seconds());
            }
            gate_opened += r.gate_opened as u64;
            if r.gate_opened && kind == "scope" {
                match r.no_peer {
                    Some(true) => no_peer += 1,
                    Some(false) => peer_invited += 1,
                    None => peer_unknown += 1,
                }
            }
        }
        latencies.sort_unstable();
        let mut k = serde_json::Map::new();
        k.insert("total".into(), json!(rs.len()));
        k.insert("gate_opened".into(), json!(gate_opened));
        if kind == "scope" {
            k.insert("gate_opened_with_no_admissible_peer".into(), json!(no_peer));
            k.insert("gate_opened_with_peer_invited".into(), json!(peer_invited));
            k.insert("gate_opened_peer_invitation_unknown".into(), json!(peer_unknown));
            k.insert("by_path_class".into(), json!(by_path));
            k.insert("reasked_same_member_and_path".into(), reasks["reasks"].clone());
            k.insert("home_dotdir_by_first_component".into(), json!(by_sub));
            k.insert("reasks".into(), reasks.clone());
        } else {
            k.insert("marker_other_by_published_name".into(), json!(by_sub));
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

/// Re-asks within each (member, path) group, ordered by witnessed opening position, not by a
/// possibly tied or regressing wall clock. Positions establish record order, not when an
/// underlying effect occurred. Missing/duplicate positions make the group order unknown.
/// Time gaps are only reported when they agree with that witnessed order.
fn reask_split(groups: Vec<Vec<&Req>>) -> Value {
    let mut by_first = BTreeMap::new();
    let (mut total, mut within_10m, mut after_unruled, mut timing_unknown) = (0u64, 0u64, 0u64, 0u64);
    for mut g in groups.into_iter().filter(|g| g.len() > 1) {
        g.sort_by_key(|r| r.opened_position);
        let positions_unknown = g.iter().any(|r| r.opened_position.is_none())
            || g.windows(2).any(|w| w[0].opened_position == w[1].opened_position);
        if positions_unknown {
            let count = (g.len() - 1) as u64;
            total += count;
            timing_unknown += count;
            *by_first.entry("unknown".to_string()).or_insert(0u64) += count;
            continue;
        }
        let first = g[0].outcome;
        for w in g.windows(2) {
            total += 1;
            *by_first.entry(first.to_string()).or_insert(0u64) += 1;
            let next_position = w[1].opened_position.expect("validated above");
            match (w[0].opened, w[1].opened) {
                (Some(previous), Some(next)) if next >= previous => {}
                _ => {
                    timing_unknown += 1; // missing clock or clock order contradicts witness order
                    continue;
                }
            }
            if w[0].ruled_position.is_some_and(|p| p <= w[0].opened_position.expect("validated above")) {
                timing_unknown += 1; // a ruling cannot precede its own recorded request
                continue;
            }
            match (w[0].ruled_position, w[0].ruled_at, w[1].opened) {
                (Some(position), Some(ruled), Some(next)) if position < next_position => {
                    if next < ruled {
                        timing_unknown += 1; // witnessed ruling preceded the ask, clock disagrees
                    } else if (next - ruled).num_seconds() <= 600 {
                        within_10m += 1;
                    }
                }
                (Some(position), _, _) if position > next_position => after_unruled += 1,
                (None, None, Some(_)) => after_unruled += 1,
                _ => timing_unknown += 1,
            }
        }
    }
    json!({
        "reasks": total,
        "by_outcome_of_first_ask": by_first,
        "within_10_min_of_previous_ruling": within_10m,
        "previous_request_unruled": after_unruled,
        "previous_ruling_order_unknown": timing_unknown,
    })
}

fn render_markdown(r: &Value) -> String {
    use std::fmt::Write;
    let mut out = String::new();
    writeln!(out, "## Request load — last {} days (aggregate only)\n", r["window_days"]).unwrap();
    writeln!(out, "- generated {}; {} chain entries scanned\n", r["generated_at"].as_str().unwrap_or(""), r["chain_entries_scanned"]).unwrap();
    for kind in ["scope", "escalation"] {
        let k = &r[kind];
        writeln!(out, "### {} ({} opened, {} by the gate)\n", if kind == "scope" { "Scope requests" } else { "Governance escalations" },
                 k["total"], k["gate_opened"]).unwrap();
        if kind == "scope" {
            writeln!(out, "- gate-opened invitation evidence at opening: no peer {}; peer invited {}; unknown {}",
                     k["gate_opened_with_no_admissible_peer"], k["gate_opened_with_peer_invited"],
                     k["gate_opened_peer_invitation_unknown"]).unwrap();
            writeln!(out, "- re-asked after the first (same member and path): {}", k["reasked_same_member_and_path"]).unwrap();
            let ra = &k["reasks"];
            writeln!(out, "- re-asks after the first: {}; by outcome of the first ask: {}; within 10 min of the previous ruling: {}; previous unruled: {}; ruling order unknown: {}",
                     ra["reasks"], ra["by_outcome_of_first_ask"], ra["within_10_min_of_previous_ruling"],
                     ra["previous_request_unruled"], ra["previous_ruling_order_unknown"]).unwrap();
        }
        let t = &k["time_to_ruling_secs"];
        writeln!(out, "- ruled: {}; time to ruling median {} s, p90 {} s", k["ruled_count"], t["median"], t["p90"]).unwrap();
        let facets: &[&str] = if kind == "scope" {
            &["by_outcome", "by_ruler", "by_outcome_and_ruler", "by_path_class", "home_dotdir_by_first_component", "by_rule", "by_member", "by_day"]
        } else {
            &["by_outcome", "by_ruler", "by_outcome_and_ruler", "by_marker_class", "marker_other_by_published_name", "by_member", "by_day"]
        };
        for f in facets {
            let parts: Vec<String> = k[*f].as_object().map(|m| m.iter().map(|(a, b)| format!("{a} {b}")).collect()).unwrap_or_default();
            writeln!(out, "- {}: {}", f.trim_start_matches("by_").replace('_', " "), if parts.is_empty() { "—".into() } else { parts.join(", ") }).unwrap();
        }
        writeln!(out).unwrap();
    }
    writeln!(out, "### Chain-wide event types (whole chain, not the window)\n").unwrap();
    if let Some(m) = r["chain_wide_event_types"].as_object() {
        for (k, v) in m {
            writeln!(out, "- {k}: {} (first {}, last {})", v["count"], v["first"].as_str().unwrap_or(""), v["last"].as_str().unwrap_or("")).unwrap();
        }
    }
    writeln!(out).unwrap();
    writeln!(out, "Who ruled: {}", r["ruler_classification"].as_str().unwrap_or("")).unwrap();
    writeln!(out, "Outcome limitation: {}", r["outcome_limitation"].as_str().unwrap_or("")).unwrap();
    out
}

fn print_markdown(r: &Value) {
    print!("{}", render_markdown(r));
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
    fn a_home_dotdir_is_named_by_its_first_component_only() {
        assert_eq!(home_dotdir_name("/home/u/.claude/projects/x/y.jsonl", HOME).as_deref(), Some(".claude"));
        assert_eq!(home_dotdir_name("/home/u/.hestia", HOME).as_deref(), Some(".hestia"));
        assert_eq!(home_dotdir_name("/home/u/notes/.x", HOME), None);
        assert_eq!(home_dotdir_name("/home/user2/.x", HOME), None);
        assert_eq!(home_dotdir_name("/etc/x", HOME), None);
    }

    #[test]
    fn unknown_home_directory_names_never_leave_the_report() {
        let private = ".synthetic-private-project";
        let bucket = home_dotdir_name("/home/u/.synthetic-private-project/file", HOME);
        assert_eq!(bucket.as_deref(), Some("other"));
        let mut requests = HashMap::new();
        requests.insert("r".to_string(), Req { kind: "scope", path_class: "home_dotdir",
            home_dotdir: bucket, ..Default::default() });
        let report = summarize(&requests, 7, 1, &Utc::now(), &[]);
        assert!(!report.to_string().contains(private));
        assert!(!render_markdown(&report).contains(private));
        assert_eq!(report["scope"]["home_dotdir_by_first_component"]["other"], 1);
    }

    #[test]
    fn unrecognized_event_and_rule_names_do_not_leak_in_report_formats() {
        let secret = "scope_synthetic_private_value";
        assert_eq!(public_event_type(secret), Some("other_scope_event"));
        assert_eq!(public_event_type("scope_granted"), Some("scope_granted"));
        assert_eq!(public_event_type("unrelated"), None);
        assert_eq!(public_scope_rule(secret), "other");
        assert_eq!(public_scope_rule("mrh.path"), "mrh.path");
        let mut requests = HashMap::new();
        requests.insert("r".into(), Req { kind: "scope", rule: public_scope_rule(secret).into(),
            ..Default::default() });
        let mut report = summarize(&requests, 7, 1, &Utc::now(), &[]);
        report["chain_wide_event_types"] = json!({
            (public_event_type(secret).unwrap()): {"count":1, "first":"x", "last":"y"}
        });
        assert!(!report.to_string().contains(secret));
        assert!(!render_markdown(&report).contains(secret));
    }

    #[test]
    fn published_lift_and_edit_events_remain_distinct_and_limitation_is_reported() {
        for event in ["scope_refusal_lift_intent", "scope_refusal_lifted",
                      "scope_grant_edit_intent", "scope_grant_edited"] {
            assert_eq!(public_event_type(event), Some(event));
        }
        let report = summarize(&HashMap::new(), 7, 0, &Utc::now(), &[]);
        assert_eq!(report["outcome_limitation"], OUTCOME_LIMITATION);
        let limitation = report["outcome_limitation"].as_str().unwrap();
        assert!(limitation.contains("refusal lift"));
        assert!(limitation.contains("grant edit"));
        assert!(limitation.contains("not linked to requests"));
        assert!(render_markdown(&report).contains(OUTCOME_LIMITATION));
    }

    #[test]
    fn a_grant_intent_is_not_a_completed_ruling() {
        let mut r = Req { kind: "scope", outcome: "open", ..Default::default() };
        let at = DateTime::<Utc>::from_timestamp(100, 0).unwrap();
        let evidence = json!({"granted_by":"operator"});
        observe_scope_outcome(&mut r, "scope_grant_intent", &evidence, at, 1);
        assert_eq!(r.outcome, "incomplete");
        assert!(r.ruled_at.is_none());
        assert!(r.ruled_position.is_none());
        observe_scope_outcome(&mut r, "scope_granted", &evidence, at, 2);
        assert_eq!(r.outcome, "granted");
        assert_eq!(r.ruled_at, Some(at));
        assert_eq!(r.ruled_position, Some(2));
        let mut refused = Req { kind: "scope", outcome: "open", ..Default::default() };
        observe_scope_outcome(&mut refused, "scope_grant_intent", &evidence, at, 1);
        observe_scope_outcome(&mut refused, "scope_refused", &evidence, at, 2);
        assert_eq!(refused.outcome, "refused");
    }

    #[test]
    fn gate_opening_peer_evidence_keeps_missing_and_malformed_unknown() {
        assert_eq!(no_peer_at_open(true, &json!({"invited_peers": []})), Some(true));
        assert_eq!(no_peer_at_open(true, &json!({"invited_peers": ["peer-a"]})), Some(false));
        for data in [json!({}), json!({"invited_peers": null}),
                     json!({"invited_peers": "peer-a"}), json!({"invited_peers": [null]}),
                     json!({"invited_peers": [""]})] {
            assert_eq!(no_peer_at_open(true, &data), None);
        }
        assert_eq!(no_peer_at_open(false, &json!({"invited_peers": []})), None);

        let mut requests = HashMap::new();
        for (id, evidence) in [("no", Some(true)), ("yes", Some(false)), ("unknown", None)] {
            requests.insert(id.into(), Req { kind: "scope", gate_opened: true,
                no_peer: evidence, ..Default::default() });
        }
        requests.insert("manual".into(), Req { kind: "scope", gate_opened: false,
            no_peer: None, ..Default::default() });
        let report = summarize(&requests, 7, 4, &Utc::now(), &[]);
        let scope = &report["scope"];
        assert_eq!(scope["gate_opened"], 3);
        assert_eq!(scope["gate_opened_with_no_admissible_peer"], 1);
        assert_eq!(scope["gate_opened_with_peer_invited"], 1);
        assert_eq!(scope["gate_opened_peer_invitation_unknown"], 1);
        assert!(render_markdown(&report).contains("no peer 1; peer invited 1; unknown 1"));
    }

    #[cfg(unix)]
    #[test]
    fn snapshot_directories_are_private_distinct_and_owned() {
        use std::os::unix::fs::PermissionsExt;
        let first = snapshot_tempdir().unwrap();
        let second = snapshot_tempdir().unwrap();
        assert_ne!(first.path(), second.path());
        assert_eq!(std::fs::metadata(first.path()).unwrap().permissions().mode() & 0o077, 0);
        let owned = first.path().to_path_buf();
        drop(first);
        assert!(!owned.exists());
        assert!(second.path().exists());
    }

    #[test]
    fn repeated_request_count_excludes_the_first_ask() {
        let mut requests = HashMap::new();
        requests.insert("a".into(), req("same", 100, "refused", Some(200)));
        requests.insert("b".into(), req("same", 300, "open", None));
        requests.insert("c".into(), req("same", 400, "open", None));
        let report = summarize(&requests, 7, 3, &Utc::now(), &[]);
        assert_eq!(report["scope"]["reasked_same_member_and_path"], 2);
        assert_eq!(report["scope"]["reasks"]["reasks"], 2);
    }

    #[test]
    fn only_published_governance_names_leave_the_other_class() {
        assert_eq!(published_marker_name("/home/u/.hestia/hooks/law_inject.py"), "law_inject.py");
        assert_eq!(published_marker_name(".claude/settings.json"), "settings.json");
        assert_eq!(published_marker_name("plugins/_shared"), "plugins/_shared");
        assert_eq!(published_marker_name("/w/hestia/plugins/_shared/"), "plugins/_shared");
        assert_eq!(published_marker_name("my-secret-project.txt"), "other");
        assert_eq!(published_marker_name("hubcap"), "other");
    }

    fn req(key: &str, opened: i64, outcome: &'static str, ruled: Option<i64>) -> Req {
        let t = |x: i64| DateTime::<Utc>::from_timestamp(x, 0);
        Req { kind: "scope", path_key: key.into(), opened: t(opened), opened_position: Some(opened as u64),
              outcome, ruled_at: ruled.and_then(t), ruled_position: ruled.map(|x| x as u64), ..Default::default() }
    }

    #[test]
    fn reasks_split_by_the_first_outcome_and_the_gap() {
        let a = [req("a", 100, "refused", Some(200)), req("a", 500, "granted", Some(600)), req("a", 2000, "lapsed", None)];
        let b = [req("b", 0, "lapsed", None), req("b", 50, "open", None)];
        let c = [req("c", 0, "granted", Some(10))];
        let v = reask_split(vec![a.iter().collect(), b.iter().collect(), c.iter().collect()]);
        assert_eq!(v["reasks"], 3);
        assert_eq!(v["by_outcome_of_first_ask"]["refused"], 2);
        assert_eq!(v["by_outcome_of_first_ask"]["lapsed"], 1);
        // a2 came 300 s after a1's ruling (within); a3 came 1400 s after a2's (not); b2 followed an unruled b1.
        assert_eq!(v["within_10_min_of_previous_ruling"], 1);
        assert_eq!(v["previous_request_unruled"], 1);
    }

    #[test]
    fn reask_timing_uses_ruling_at_the_time_of_the_next_ask() {
        let overlapping = [req("a", 100, "granted", Some(500)), req("a", 300, "open", None)];
        let tied = [req("b", 100, "granted", Some(300)), req("b", 300, "open", None)];
        let after = [req("c", 100, "granted", Some(200)), req("c", 300, "open", None)];
        let v = reask_split(vec![overlapping.iter().collect(), tied.iter().collect(), after.iter().collect()]);
        assert_eq!(v["reasks"], 3);
        assert_eq!(v["previous_request_unruled"], 1);
        assert_eq!(v["previous_ruling_order_unknown"], 1);
        assert_eq!(v["within_10_min_of_previous_ruling"], 1);
    }

    #[test]
    fn reask_order_uses_witness_positions_and_refuses_ambiguous_evidence() {
        let mut first = req("a", 100, "refused", Some(200));
        let mut second = req("a", 100, "granted", Some(300));
        first.opened_position = Some(1);
        first.ruled_position = Some(4); // this ruling was witnessed after the next opening
        second.opened_position = Some(2);
        second.ruled_position = Some(5);
        let forward = reask_split(vec![vec![&first, &second]]);
        let backward = reask_split(vec![vec![&second, &first]]);
        assert_eq!(forward, backward, "input iteration order cannot choose the first ask");
        assert_eq!(forward["by_outcome_of_first_ask"]["refused"], 1);
        assert_eq!(forward["previous_request_unruled"], 1);

        second.opened_position = Some(1); // invalid duplicate opening positions
        let duplicate = reask_split(vec![vec![&first, &second]]);
        assert_eq!(duplicate["by_outcome_of_first_ask"]["unknown"], 1);
        assert_eq!(duplicate["previous_ruling_order_unknown"], 1);
        second.opened_position = None;
        let missing = reask_split(vec![vec![&first, &second]]);
        assert_eq!(missing["by_outcome_of_first_ask"]["unknown"], 1);
        assert_eq!(missing["previous_ruling_order_unknown"], 1);

        let mut earlier = req("b", 200, "granted", Some(250));
        let mut later = req("b", 100, "open", None);
        earlier.opened_position = Some(1);
        earlier.ruled_position = Some(2);
        later.opened_position = Some(3); // wall clock went backwards
        let clock = reask_split(vec![vec![&earlier, &later]]);
        assert_eq!(clock["by_outcome_of_first_ask"]["granted"], 1);
        assert_eq!(clock["previous_ruling_order_unknown"], 1);
        assert_eq!(clock["within_10_min_of_previous_ruling"], 0);
    }

    #[test]
    fn percentiles_are_nearest_rank() {
        assert_eq!(pct(&[], 0.5), None);
        assert_eq!(pct(&[5], 0.9), Some(5));
        assert_eq!(pct(&[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5), Some(6));
        assert_eq!(pct(&[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9), Some(9));
    }
}
