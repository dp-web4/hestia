//! The read list — what agents are on this machine, and which of them we govern.
//!
//! hestia sees only what routes through hestia, so an installed-but-ungoverned agent is
//! structurally invisible to it. agent-atlas's read half is the outside view (dp): the
//! registry says what *could* be here, the filesystem says what *is*, and the delta is
//! the ungoverned set. This module is the daemon-side surface for that delta.
//!
//! WHY IT SHELLS OUT INSTEAD OF REIMPLEMENTING. `agent-inventory` already does this
//! check, and its second cut survived Thor's review — scope chain, structural hook
//! parsing per config format, dead-target stat, executables resolved across version
//! manager roots, `UNKNOWN` rather than `OK` when a scope cannot be established. A Rust
//! reimplementation would be a second thing to keep correct, and the two would agree
//! right up until the moment one of them mattered. `orchestrators::is_installed()` is
//! exactly that hazard already in the tree: it greps a config for the substring "hestia"
//! and so cannot tell a wired gate from a wired-and-dead one, which is the case this
//! whole surface exists to expose.
//!
//! WHY IT IS NOT READ FROM THE CHAIN. The inventory witnesses every run, so the obvious
//! source is the newest `agent_inventory` entry. But the only window available is
//! `read_recent(10_000)`, and on a busy chain an hourly entry falls out of 10k — at
//! which point "checked 40 minutes ago" renders as "never checked". Running it live
//! costs a subprocess and removes the ambiguity entirely.

use anyhow::{Result, bail};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Where the inventory executable lives. Fixed paths only — never anything derived from
/// a request. The ext4 copy is preferred for the same reason the hooks prefer it: the
/// repo lives on 9p on this fleet's WSL boxes and a cold read is slow.
fn inventory_bin() -> Option<PathBuf> {
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Some(home) = dirs_home() {
        cands.push(home.join(".local/bin/hestia-agent-inventory"));
    }
    if let Ok(ws) = std::env::var("HESTIA_WORKSPACE") {
        cands.push(PathBuf::from(ws).join("hestia/plugins/agent-inventory/inventory.py"));
    }
    cands.into_iter().find(|p| p.is_file())
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

/// Run the inventory and return its report verbatim.
///
/// `--no-witness`: this is a *read* driven by someone looking at a dashboard, and
/// witnessing it would let a page-open write to the chain. The scheduled runs (hourly
/// timer, SessionStart, operator CLI) are the ones that belong in the record; a refresh
/// button firing a chain entry per click turns the record into UI telemetry.
/// Private: async code must not call this (it blocks its thread for the child's lifetime);
/// use [`inventory_off_thread`], which is the only way the rest of the daemon can reach it.
fn inventory() -> Result<Value> {
    let Some(bin) = inventory_bin() else {
        // Honest unknown. An empty inventory would render as "nothing ungoverned here",
        // which is the exact inversion this surface exists to prevent.
        return Ok(serde_json::json!({
            "status": "UNKNOWN",
            "reason": "agent-inventory is not installed on this machine — cannot \
                       distinguish 'nothing ungoverned' from 'could not look'. \
                       Install: bash hestia/plugins/agent-inventory/install.sh <workspace>",
        }));
    };
    // Invoke the installed entry point DIRECTLY rather than through `python3`.
    //
    // It is not always a Python file: agent-inventory's installer writes the entry point
    // as a small sh wrapper that pins the workspace it detected, with the script beside it
    // as `.py`. Hardcoding the interpreter meant the daemon ran `python3 <shell script>`
    // and got a syntax error — and because gate coverage is derived from this, the whole
    // integrity check degraded to UNKNOWN. Both halves were mine, landed on separate
    // branches, each correct alone.
    //
    // Executing the file lets its shebang decide, which is the point of having one.
    let out = Command::new(&bin).arg("--no-witness").output()?;
    if !out.status.success() {
        bail!(
            "inventory exited {}: {}",
            out.status,
            String::from_utf8_lossy(&out.stderr).chars().take(300).collect::<String>()
        );
    }
    Ok(serde_json::from_slice(&out.stdout)?)
}

/// [`inventory`] on tokio's blocking pool. Every async caller uses this one (#1183).
///
/// `Command::output()` blocks its thread until the child exits, about 1.1 s on CBP. Called
/// straight from an async handler, it parks a runtime worker for that time: measured as a
/// whole-daemon stall every 20 s while a dashboard tab polled `/api/agents`. Called while
/// holding the state lock (the 300 s gate-watch pass, `/api/gates/*`), it also stalls every
/// member's gate round-trip for that time. Both callers now await this instead, and none
/// holds the state lock while it runs.
pub async fn inventory_off_thread() -> Result<Value> {
    tokio::task::spawn_blocking(inventory)
        .await
        .map_err(|e| anyhow::anyhow!("inventory task failed: {e}"))?
}

#[derive(Debug, Clone)]
pub struct UngovernPlan {
    pub member: String,
    pub registrar: Option<PathBuf>,
    pub owned_targets: Vec<String>,
    /// Hook targets the inventory reads for this member and does NOT attribute to hestia. They
    /// are never removed. They are carried so the act can say what it left in force: "0 hooks
    /// removed" beside a foreign gate line is not an unwired member.
    pub unowned_targets: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct UngovernOutcome {
    pub hooks_removed: usize,
    pub backup: Option<String>,
}

/// Resolve one member's exact owned targets and the already-deployed registrar that can remove
/// them. A missing or ambiguous inventory record stops before any authority or file is changed.
pub fn ungovern_plan_from_inventory(id: &str, report: &Value) -> Result<UngovernPlan> {
    let detail = report.get("detail").and_then(Value::as_array).cloned().unwrap_or_default();
    let matches: Vec<&Value> = detail
        .iter()
        .filter(|rec| {
            ["member", "plugin", "agent"]
                .iter()
                .any(|key| rec.get(*key).and_then(Value::as_str) == Some(id))
        })
        .collect();
    let rec = match matches.as_slice() {
        [one] => *one,
        [] => bail!("'{id}' is not in the current inventory; nothing was changed"),
        _ => bail!("'{id}' names more than one inventory record; nothing was changed"),
    };
    let unknown = rec.get("unknown").and_then(Value::as_array).cloned().unwrap_or_default();
    if !unknown.is_empty() {
        bail!("the inventory could not fully classify '{id}' ({unknown:?}); nothing was changed");
    }
    let member = rec
        .get("plugin")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .ok_or_else(|| anyhow::anyhow!("'{id}' has no hestia registrar; nothing was changed"))?
        .to_string();
    let mut owned_targets: Vec<String> = rec
        .get("hook_targets")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|target| target.get("owned_by_hestia").and_then(Value::as_bool) == Some(true))
        .filter_map(|target| target.get("path").and_then(Value::as_str))
        .map(str::to_string)
        .collect();
    owned_targets.sort();
    owned_targets.dedup();
    let mut unowned_targets: Vec<String> = rec
        .get("hook_targets")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|target| target.get("owned_by_hestia").and_then(Value::as_bool) != Some(true))
        .filter_map(|target| target.get("path").and_then(Value::as_str))
        .map(str::to_string)
        .collect();
    unowned_targets.sort();
    unowned_targets.dedup();
    let registrar = if owned_targets.is_empty() {
        None
    } else {
        let scope = report.get("scope").cloned().unwrap_or(Value::Null);
        let source = scope.get("workspace_source").and_then(Value::as_str).unwrap_or("");
        if !matches!(source, "env" | "argv") {
            bail!("the inventory workspace is not explicitly established; refusing to execute its registrar");
        }
        let workspace = scope
            .get("workspace")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|p| !p.is_empty())
            .ok_or_else(|| anyhow::anyhow!("the inventory names no workspace for the registrar"))?;
        Some(PathBuf::from(workspace).join("hestia/deploy/register-members.py"))
    };
    Ok(UngovernPlan { member, registrar, owned_targets, unowned_targets })
}

/// The caller holds the daemon's state lock across the registrar (the act must not interleave
/// with another change to the same seat), so a registrar that never returns would stop every
/// gate on the machine. It gets this long.
const REGISTRAR_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

/// `Command::output` with a deadline. On the deadline the child is killed and the error says the
/// outcome is NOT known: the registrar writes its edit by an atomic rename, so the config is
/// either as it was or fully edited, and only a fresh inventory can say which.
fn output_within(mut command: Command, limit: std::time::Duration) -> Result<std::process::Output> {
    use std::io::Read;
    use std::process::Stdio;
    let mut child = command.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()?;
    // Drain both pipes off-thread so a chatty child cannot block on a full pipe while we wait.
    let drain = |pipe: Option<Box<dyn Read + Send>>| {
        std::thread::spawn(move || {
            let mut bytes = Vec::new();
            if let Some(mut pipe) = pipe {
                let _ = pipe.read_to_end(&mut bytes);
            }
            bytes
        })
    };
    let stdout = drain(child.stdout.take().map(|p| Box::new(p) as Box<dyn Read + Send>));
    let stderr = drain(child.stderr.take().map(|p| Box::new(p) as Box<dyn Read + Send>));
    let started = std::time::Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if started.elapsed() >= limit {
            let _ = child.kill();
            let _ = child.wait();
            bail!(
                "the registrar did not finish within {limit:?} and was stopped; whether the harness \
                 config was edited is NOT known — run the inventory before anything else"
            );
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    };
    Ok(std::process::Output {
        status,
        stdout: stdout.join().unwrap_or_default(),
        stderr: stderr.join().unwrap_or_default(),
    })
}

/// Execute the same ownership-proved registrar the operator installer uses, rather than keeping a
/// second, JSON-only removal implementation in the daemon.
pub fn ungovern(plan: &UngovernPlan, hestia_home: &Path) -> Result<UngovernOutcome> {
    let operator_home = dirs_home().ok_or_else(|| anyhow::anyhow!("HOME is not set; nothing was changed"))?;
    ungovern_at(plan, hestia_home, &operator_home)
}

pub(crate) fn ungovern_at(
    plan: &UngovernPlan,
    hestia_home: &Path,
    operator_home: &Path,
) -> Result<UngovernOutcome> {
    if plan.owned_targets.is_empty() {
        return Ok(UngovernOutcome { hooks_removed: 0, backup: None });
    }
    let registrar = plan
        .registrar
        .as_ref()
        .filter(|path| path.is_file())
        .ok_or_else(|| anyhow::anyhow!("the member registrar is not installed; nothing was changed"))?;
    let mut command = Command::new("python3");
    command
        .arg(registrar)
        .arg("--remove")
        .arg("--member")
        .arg(&plan.member)
        .arg("--json")
        .arg("--home")
        .arg(operator_home)
        .args(plan.owned_targets.iter().flat_map(|target| ["--owned-target", target.as_str()]))
        .env("HESTIA_HOME", hestia_home);
    let out = output_within(command, REGISTRAR_TIMEOUT)?;
    let value: Value = serde_json::from_slice(&out.stdout).map_err(|e| {
        anyhow::anyhow!(
            "the registrar returned no readable result ({e}): {}",
            String::from_utf8_lossy(&out.stderr).chars().take(300).collect::<String>()
        )
    })?;
    let status = value.get("status").and_then(Value::as_str).unwrap_or("");
    if !out.status.success() || !matches!(status, "ok" | "unregistered") {
        bail!(
            "{}",
            value
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("the registrar refused the removal; nothing was changed")
        );
    }
    let outcome: UngovernOutcome = serde_json::from_value(value)?;
    if outcome.hooks_removed == 0 {
        bail!("the registrar removed none of the inventory's owned targets; nothing was changed");
    }
    Ok(outcome)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_ungovern_plan_uses_only_inventory_owned_targets_and_an_explicit_workspace() {
        let mut report = serde_json::json!({
            "status": "UNGOVERNED_PRESENT",
            "scope": {"workspace": "/w", "workspace_source": "env"},
            "detail": [{
                "agent": "kimi", "plugin": "kimi", "member": "kimi-code",
                "hook_targets": [
                    {"path": "/h/.kimi-code/hooks/pre_tool_use.py", "owned_by_hestia": true},
                    {"path": "/h/.kimi-code/hooks/witness.py", "owned_by_hestia": true},
                    {"path": "/h/.kimi-code/hooks/pre_tool_use.py", "owned_by_hestia": true},
                    {"path": "/elsewhere/foreign.py", "owned_by_hestia": false},
                    {"path": "/also-mine-but-not-inventoried.py"}
                ]
            }]
        });
        let plan = ungovern_plan_from_inventory("kimi-code", &report).unwrap();
        assert_eq!(plan.member, "kimi");
        assert_eq!(plan.owned_targets, [
            "/h/.kimi-code/hooks/pre_tool_use.py".to_string(),
            "/h/.kimi-code/hooks/witness.py".to_string(),
        ]);
        assert_eq!(plan.registrar.unwrap(), PathBuf::from("/w/hestia/deploy/register-members.py"));
        assert_eq!(plan.unowned_targets, [
            "/also-mine-but-not-inventoried.py".to_string(),
            "/elsewhere/foreign.py".to_string(),
        ], "what is not proved owned is reported as left in place, never as removable");
        report["detail"][0]["unknown"] = serde_json::json!(["config scope is incomplete"]);
        assert!(ungovern_plan_from_inventory("kimi-code", &report).is_err());
    }

    #[test]
    fn a_registrar_that_never_returns_is_stopped_and_reported_as_unknown() {
        let mut command = Command::new("sleep");
        command.arg("30");
        let started = std::time::Instant::now();
        let error = output_within(command, std::time::Duration::from_millis(150)).unwrap_err();
        assert!(started.elapsed() < std::time::Duration::from_secs(5), "{:?}", started.elapsed());
        assert!(error.to_string().contains("NOT known"), "{error}");
        // control: a child that finishes is read in full
        let mut command = Command::new("sh");
        command.args(["-c", "printf out; printf err >&2; exit 3"]);
        let out = output_within(command, std::time::Duration::from_secs(5)).unwrap();
        assert_eq!((out.status.code(), out.stdout.as_slice(), out.stderr.as_slice()),
                   (Some(3), b"out".as_slice(), b"err".as_slice()));
    }

    #[test]
    fn an_ungovern_with_no_owned_targets_never_executes_a_registrar() {
        let plan = UngovernPlan {
            member: "codex".into(),
            registrar: None,
            owned_targets: Vec::new(),
            unowned_targets: Vec::new(),
        };
        let outcome = ungovern(&plan, Path::new("/not-read")).unwrap();
        assert_eq!(outcome.hooks_removed, 0);
        assert_eq!(outcome.backup, None);
    }
}
