// Copyright (c) 2026 MetaLINXX Inc.
// SPDX-License-Identifier: AGPL-3.0-or-later

//! # Compatible orchestrators — detection + one-click connect
//!
//! Hestia knows the orchestrators that have *engaged* it (the trust list). This
//! module adds awareness of orchestrators that are **running on the machine but
//! not yet connected**, so the dashboard can offer to connect them.
//!
//! - [`detect_running`] scans `/proc` for known orchestrator processes.
//! - [`REGISTRY`] is the static list of compatible orchestrators + whether a
//!   hestia plugin is available for each.
//! - [`install`] connects one by installing its plugin (claude-code: merges a
//!   PostToolUse witness hook into `~/.claude/settings.json`).

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

/// A compatible orchestrator hestia can observe.
pub struct KnownOrch {
    /// Stable id; matches the `plugin_id` an engaged orchestrator reports.
    pub id: &'static str,
    /// Display name.
    pub name: &'static str,
    /// Lowercased substrings matched against process `comm` to detect a running
    /// instance.
    pub proc_patterns: &'static [&'static str],
    /// Whether hestia ships a plugin that `install` can connect.
    pub plugin_available: bool,
}

pub const REGISTRY: &[KnownOrch] = &[
    KnownOrch { id: "claude-code", name: "Claude Code", proc_patterns: &["claude"], plugin_available: true },
    KnownOrch { id: "openclaw", name: "OpenClaw", proc_patterns: &["openclaw"], plugin_available: true },
    KnownOrch { id: "cursor", name: "Cursor", proc_patterns: &["cursor"], plugin_available: true },
    KnownOrch { id: "codex", name: "Codex", proc_patterns: &["codex"], plugin_available: true },
];

pub fn lookup(id: &str) -> Option<&'static KnownOrch> {
    REGISTRY.iter().find(|o| o.id == id)
}

/// Ids of registry orchestrators with a process currently running (via `/proc`).
pub fn detect_running() -> HashSet<String> {
    let mut found = HashSet::new();
    let Ok(entries) = std::fs::read_dir("/proc") else { return found };
    for e in entries.flatten() {
        let pid = e.file_name();
        let Some(pid) = pid.to_str() else { continue };
        if !pid.bytes().all(|b| b.is_ascii_digit()) {
            continue;
        }
        let comm = std::fs::read_to_string(format!("/proc/{pid}/comm")).unwrap_or_default();
        let comm = comm.trim().to_lowercase();
        if comm.is_empty() {
            continue;
        }
        for orch in REGISTRY {
            if found.contains(orch.id) {
                continue;
            }
            if orch.proc_patterns.iter().any(|p| comm.contains(p)) {
                found.insert(orch.id.to_string());
            }
        }
    }
    found
}

fn home_dir() -> Result<PathBuf> {
    std::env::var("HOME").map(PathBuf::from).context("HOME not set")
}

/// Connect an orchestrator by installing its hestia plugin. Returns a short
/// human status. Errors if no installer exists for the id, or if the install
/// can't write the orchestrator's config (e.g. the daemon sandbox denies it).
pub fn install(id: &str) -> Result<String> {
    match id {
        "claude-code" => install_claude_code(),
        "codex" => install_codex(),
        "cursor" => install_cursor(),
        other => anyhow::bail!("no installer available for '{other}' yet"),
    }
}

/// Whether an orchestrator already has hestia's witness hook wired into its
/// config. Read-only mirror of the idempotency check in each `install_*`
/// (scans the config for a hestia/witness marker). Lets the dashboard tell a
/// running-but-unwired orchestrator apart from a running-and-connected one: it
/// should offer to connect the former, and show the latter as connected even
/// when it hasn't fired a tool call in the last hour.
pub fn is_installed(id: &str) -> bool {
    let Ok(home) = home_dir() else { return false };
    let path = match id {
        "claude-code" => home.join(".claude/settings.json"),
        "codex" => home.join(".codex/config.toml"),
        "cursor" => home.join(".cursor/hooks.json"),
        _ => return false,
    };
    match std::fs::read_to_string(&path) {
        Ok(s) => s.contains("hestia") || s.contains("witness.py"),
        Err(_) => false,
    }
}

/// Path to an orchestrator's witness hook shipped in this repo (resolved from
/// the build-time crate dir → repo root → plugins/…).
fn repo_hook(orch: &str) -> Result<PathBuf> {
    let p: &str = match orch {
        "claude-code" => concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/claude-code/hooks/witness.py"),
        "codex" => concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/codex/hooks/witness.py"),
        "cursor" => concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/cursor/hooks/witness.py"),
        other => anyhow::bail!("no witness hook for '{other}'"),
    };
    Path::new(p).canonicalize().with_context(|| format!("locating {p}"))
}

/// Merge hestia's PostToolUse witness hook into `~/.claude/settings.json`,
/// idempotently. Needs write access to `~/.claude` (the daemon sandbox must
/// allow it — see deploy notes).
fn install_claude_code() -> Result<String> {
    let witness = repo_hook("claude-code")?;
    let command = format!("python3 {}", witness.display());
    let claude_dir = home_dir()?.join(".claude");
    let settings_path = claude_dir.join("settings.json");

    let mut json: serde_json::Value = if settings_path.exists() {
        serde_json::from_str(&std::fs::read_to_string(&settings_path)?)
            .context("parsing existing ~/.claude/settings.json")?
    } else {
        serde_json::json!({})
    };

    let obj = json.as_object_mut().context("~/.claude/settings.json is not a JSON object")?;
    let hooks = obj.entry("hooks").or_insert_with(|| serde_json::json!({}));
    let post = hooks
        .as_object_mut()
        .context("settings.hooks is not an object")?
        .entry("PostToolUse")
        .or_insert_with(|| serde_json::json!([]));
    let arr = post.as_array_mut().context("settings.hooks.PostToolUse is not an array")?;

    // Idempotent: bail out (success) if a hestia witness hook is already present.
    let already = arr.iter().any(|e| e.to_string().contains("hestia") || e.to_string().contains("witness.py"));
    if already {
        return Ok("already connected (hestia hook present)".into());
    }

    arr.push(serde_json::json!({
        "matcher": "*",
        "hooks": [{ "type": "command", "command": command, "timeout": 3 }],
    }));

    std::fs::create_dir_all(&claude_dir).context("creating ~/.claude")?;
    std::fs::write(&settings_path, serde_json::to_string_pretty(&json)?)
        .with_context(|| format!("writing {} (does the daemon have write access?)", settings_path.display()))?;

    Ok(format!("connected — added hestia PostToolUse hook to {}; restart Claude Code", settings_path.display()))
}

/// Merge hestia's witness into `~/.cursor/hooks.json` as afterShellExecution +
/// afterFileEdit command hooks (Cursor's native hook schema), idempotently.
fn install_cursor() -> Result<String> {
    let witness = repo_hook("cursor")?;
    let command = format!("python3 {}", witness.display());
    let cursor_dir = home_dir()?.join(".cursor");
    let hooks_path = cursor_dir.join("hooks.json");

    let mut json: serde_json::Value = if hooks_path.exists() {
        serde_json::from_str(&std::fs::read_to_string(&hooks_path)?)
            .context("parsing ~/.cursor/hooks.json")?
    } else {
        serde_json::json!({ "version": 1, "hooks": {} })
    };
    if json.to_string().contains("witness.py") || json.to_string().contains("hestia") {
        return Ok("already connected (hestia hook present)".into());
    }

    let obj = json.as_object_mut().context("~/.cursor/hooks.json is not a JSON object")?;
    obj.entry("version").or_insert(serde_json::json!(1));
    let hooks = obj.entry("hooks").or_insert_with(|| serde_json::json!({}));
    let hooks_obj = hooks.as_object_mut().context("hooks.json `hooks` is not an object")?;
    let entry = serde_json::json!({ "command": command, "timeout": 5 });
    for event in ["afterShellExecution", "afterFileEdit"] {
        let arr = hooks_obj.entry(event).or_insert_with(|| serde_json::json!([]));
        arr.as_array_mut().with_context(|| format!("hooks.{event} is not an array"))?.push(entry.clone());
    }

    std::fs::create_dir_all(&cursor_dir).context("creating ~/.cursor")?;
    std::fs::write(&hooks_path, serde_json::to_string_pretty(&json)?)
        .with_context(|| format!("writing {} (does the daemon have write access?)", hooks_path.display()))?;
    Ok(format!("connected — added hestia hooks to {}; restart Cursor", hooks_path.display()))
}

/// Append a hestia PostToolUse command hook to `~/.codex/config.toml` (Codex
/// uses Claude Code's hook event schema), idempotently. We append the documented
/// array-of-tables block rather than reparse the whole TOML.
fn install_codex() -> Result<String> {
    let witness = repo_hook("codex")?;
    let command = format!("python3 {}", witness.display());
    let codex_dir = home_dir()?.join(".codex");
    let cfg_path = codex_dir.join("config.toml");

    let existing = std::fs::read_to_string(&cfg_path).unwrap_or_default();
    if existing.contains("witness.py") || existing.contains("hestia") {
        return Ok("already connected (hestia hook present)".into());
    }

    let block = format!(
        "\n# hestia witness — added by dashboard connect\n\
         [[hooks.PostToolUse]]\n\
         [[hooks.PostToolUse.hooks]]\n\
         type = \"command\"\n\
         command = '{command}'\n\
         timeout = 5\n"
    );
    std::fs::create_dir_all(&codex_dir).context("creating ~/.codex")?;
    let mut new = existing;
    new.push_str(&block);
    std::fs::write(&cfg_path, new)
        .with_context(|| format!("writing {} (does the daemon have write access?)", cfg_path.display()))?;
    Ok(format!("connected — added hestia PostToolUse hook to {}; restart Codex", cfg_path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_lookup_and_detect_runs() {
        assert!(lookup("claude-code").is_some());
        assert!(lookup("nope").is_none());
        // detect_running just shouldn't panic on this host.
        let _ = detect_running();
    }

    #[test]
    fn install_unknown_orchestrator_errors() {
        // A genuinely unsupported id errors without touching the filesystem.
        assert!(install("vim").is_err());
        assert!(install("nope-xyz").is_err());
    }

    #[test]
    fn is_installed_unknown_is_false_and_never_panics() {
        // Unknown orchestrators are never "installed"; known ones just read a
        // config file (absent → false) without panicking on this host.
        assert!(!is_installed("nope-xyz"));
        let _ = is_installed("claude-code");
    }
}
