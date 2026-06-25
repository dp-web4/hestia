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
    KnownOrch { id: "cursor", name: "Cursor", proc_patterns: &["cursor"], plugin_available: false },
    KnownOrch { id: "codex", name: "Codex", proc_patterns: &["codex"], plugin_available: false },
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
        other => anyhow::bail!("no installer available for '{other}' yet"),
    }
}

/// Path to the claude-code witness hook shipped in this repo (resolved from the
/// build-time crate dir → repo root → plugins/…).
fn claude_witness_hook() -> Result<PathBuf> {
    Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/claude-code/hooks/witness.py"))
        .canonicalize()
        .context("locating plugins/claude-code/hooks/witness.py")
}

/// Merge hestia's PostToolUse witness hook into `~/.claude/settings.json`,
/// idempotently. Needs write access to `~/.claude` (the daemon sandbox must
/// allow it — see deploy notes).
fn install_claude_code() -> Result<String> {
    let witness = claude_witness_hook()?;
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
        assert!(install("cursor").is_err());
    }
}
