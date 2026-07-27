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
use std::path::PathBuf;
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
pub fn inventory() -> Result<Value> {
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

/// Configs we can safely un-wire, and the shape they are in. TOML is deliberately absent:
/// removing a table entry from a hand-maintained TOML without a round-tripping editor
/// risks eating comments and neighbouring settings, and silently mangling an agent's
/// config while claiming to have merely ungoverned it is a worse outcome than declining.
/// Codex and Kimi therefore report unsupported rather than being edited approximately.
fn json_config_for(agent: &str) -> Option<PathBuf> {
    let home = dirs_home()?;
    let p = match agent {
        "claude" | "claude-code" => home.join(".claude/settings.json"),
        "gemini" => home.join(".gemini/settings.json"),
        "cursor" => home.join(".cursor/hooks.json"),
        _ => return None,
    };
    Some(p)
}

/// Remove hestia's hook wiring from an agent's config, keeping a timestamped backup.
///
/// Returns (backup_path, hooks_removed). Reversible by construction: the backup is
/// written and fsync-ordered BEFORE the config is rewritten, so a failure mid-way leaves
/// either the original file or the original plus a copy of itself — never a half-edited
/// config. Ungoverning removes enforcement; it must not also risk the agent's own setup.
pub fn ungovern(agent: &str) -> Result<(String, usize)> {
    let Some(path) = json_config_for(agent) else {
        bail!(
            "ungovern is not supported for '{agent}' from here: its config is TOML and \
             editing it without a round-tripping parser risks its comments and unrelated \
             settings. Remove the hestia hook entries by hand."
        );
    };
    if !path.is_file() {
        bail!("no config at {}", path.display());
    }
    let text = std::fs::read_to_string(&path)?;
    let mut cfg: Value = serde_json::from_str(&text)?;

    // Backup first, and verify it landed. `?` on the write is not enough — a truncated
    // backup that still returned Ok would leave nothing to restore from.
    let stamp = chrono::Utc::now().format("%Y%m%d-%H%M%S");
    let backup = path.with_extension(format!("json.hestia-ungovern.{stamp}"));
    std::fs::write(&backup, &text)?;
    if std::fs::read_to_string(&backup)? != text {
        bail!("backup at {} did not verify; refusing to edit the config", backup.display());
    }

    let mut removed = 0usize;
    if let Some(hooks) = cfg.get_mut("hooks").and_then(Value::as_object_mut) {
        for (_event, groups) in hooks.iter_mut() {
            let Some(arr) = groups.as_array_mut() else { continue };
            for group in arr.iter_mut() {
                let Some(inner) = group.get_mut("hooks").and_then(Value::as_array_mut) else {
                    continue;
                };
                let before = inner.len();
                // Ownership by CONTENT, matching the inventory: hestia deploys gates to
                // paths that never say "hestia" (~/.codex/hooks/pre_tool_use.py), and a
                // path-name test would leave a live gate wired while reporting success.
                inner.retain(|h| !is_hestia_hook(h));
                removed += before - inner.len();
            }
            arr.retain(|g| {
                g.get("hooks").and_then(Value::as_array).map(|a| !a.is_empty()).unwrap_or(true)
            });
        }
    }
    if removed == 0 {
        bail!("no hestia hooks found in {} — nothing to ungovern", path.display());
    }
    std::fs::write(&path, serde_json::to_string_pretty(&cfg)? + "\n")?;
    Ok((backup.display().to_string(), removed))
}

/// Is this hook entry hestia's? Decided by reading the target where we can, because the
/// path is not the owner: a gate whose filename says nothing about hestia can be entirely
/// hestia's, and a path containing "hestia" can belong to something else.
fn is_hestia_hook(h: &Value) -> bool {
    let Some(cmd) = h.get("command").and_then(Value::as_str) else {
        return false;
    };
    if cmd.to_lowercase().contains("hestia") {
        return true;
    }
    for tok in cmd.split_whitespace() {
        if tok.starts_with('/') && std::path::Path::new(tok).is_file() {
            if let Ok(body) = std::fs::read_to_string(tok) {
                if body.contains("hestia") {
                    return true;
                }
            }
        }
    }
    false
}
