//! Target + category extraction from tool inputs.
//!
//! Lightweight port of the parts of `target_extraction.py` we
//! actually need at the daemon layer. The richer multi-target
//! extraction (parsing `rm -rf a b c` to extract all of `a`, `b`, `c`)
//! lives in the orchestrator-side plugin; here the daemon just needs
//! the primary target and a tool-class category for rule matching.

use serde_json::Value;

/// Pull the primary target string from tool input arguments. Returns
/// `None` if no recognizable target is present.
///
/// Convention: tools use one of `file_path`, `path`, `url`,
/// `notebook_path` as the keyed target; for Bash/Shell the target is
/// the first token of the `command` (the executable being invoked).
pub fn extract_target(tool_name: &str, input: &Value) -> Option<String> {
    if !input.is_object() {
        return None;
    }
    // A CHANNEL SEND'S TARGET IS NEVER CALLER TEXT (#1344 amendment, item 3). The daemon builds
    // it from the operator's binding, `{channel_id}:{recipient_class}`
    // (`server::channel::ChannelBinding::target`); a caller could put anything in `path` or `url`.
    if is_channel_send(tool_name) {
        return None;
    }

    for key in ["file_path", "path", "url", "notebook_path"] {
        if let Some(v) = input.get(key).and_then(Value::as_str) {
            if !v.is_empty() {
                return Some(v.to_string());
            }
        }
    }

    // Bash / Shell — return the head of the command.
    if matches!(tool_name, "Bash" | "Shell") {
        if let Some(cmd) = input.get("command").and_then(Value::as_str) {
            return cmd
                .split_whitespace()
                .next()
                .map(|s| s.to_string())
                .filter(|s| !s.is_empty());
        }
    }
    None
}

/// Pull the full command (for `command_patterns` rule matching). Only
/// meaningful for shell-class tools.
pub fn extract_full_command(tool_name: &str, input: &Value) -> Option<String> {
    if !matches!(tool_name, "Bash" | "Shell") {
        return None;
    }
    input
        .get("command")
        .and_then(Value::as_str)
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
}

/// `hestia_channel_send` (any MCP prefix) and SAGE's `channel_send` verb (#1344): one category.
pub fn is_channel_send(tool_name: &str) -> bool {
    tool_name == "channel_send" || tool_name.ends_with("hestia_channel_send")
}

/// Map a tool name to a category for rule matching.
///
/// Only `file_read`, `file_write`, `network` and `credential_access` are
/// actually named by a built-in preset rule. The rest — `command`,
/// `task_management`, `witness_append`, `unknown` — are minted here and
/// matched by nothing, so a rule written as `categories: ["command"]` is
/// silently dead law. (This comment previously listed `command` among the
/// preset-referenced set; the safety preset governs the shell through
/// `tools: ["Bash"]` and command patterns, never through the category.)
/// `tests/gate_category_coverage.rs` pins which is which and goes red when
/// it changes.
///
/// A tool can belong to multiple categories — for example `Bash` is
/// both `command` and (potentially) `credential_access` depending on
/// the target. We return the **primary** category here; rule authors
/// should match on `tools:` for specific tool names instead of relying
/// on category for everything.
pub fn classify(tool_name: &str) -> &'static str {
    match tool_name {
        "Bash" | "Shell" => "command",
        "Read" | "Glob" | "Grep" => "file_read",
        "Write" | "Edit" | "MultiEdit" | "NotebookEdit" => "file_write",
        "WebFetch" | "WebSearch" => "network",
        "TodoWrite" => "task_management",
        // Vault credential tools — until this, NOTHING classified as
        // credential_access, so category rules on it were silently dead law
        // (caught by the 2026-07-06 ratified-overlay live check). Suffix match
        // covers host-agent prefixing (Claude Code: `mcp__hestia__hestia_vault_get`).
        t if t.ends_with("hestia_vault_get") || t.ends_with("hestia_vault_set") => {
            "credential_access"
        }
        // Witness-chain appends are their own gateable category: request_witness
        // lets a caller write audit history, so law must be able to deny it for
        // unattended roles the same way it denies credential_access.
        t if t.ends_with("hestia_request_witness") => "witness_append",
        t if is_channel_send(t) => "channel_egress",
        _ => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extracts_file_path() {
        let input = json!({"file_path": "/etc/hosts"});
        assert_eq!(extract_target("Read", &input), Some("/etc/hosts".into()));
    }

    #[test]
    fn extracts_url() {
        let input = json!({"url": "https://example.com/api"});
        assert_eq!(
            extract_target("WebFetch", &input),
            Some("https://example.com/api".into())
        );
    }

    #[test]
    fn bash_target_is_first_token() {
        let input = json!({"command": "rm -rf /tmp/foo"});
        assert_eq!(extract_target("Bash", &input), Some("rm".into()));
    }

    #[test]
    fn bash_full_command_preserved() {
        let input = json!({"command": "rm -rf /tmp/foo"});
        assert_eq!(
            extract_full_command("Bash", &input),
            Some("rm -rf /tmp/foo".into())
        );
    }

    #[test]
    fn no_target_returns_none() {
        let input = json!({});
        assert_eq!(extract_target("Read", &input), None);
    }

    #[test]
    fn classify_known_tools() {
        assert_eq!(classify("Bash"), "command");
        assert_eq!(classify("Read"), "file_read");
        assert_eq!(classify("Write"), "file_write");
        assert_eq!(classify("WebFetch"), "network");
        assert_eq!(classify("Mystery"), "unknown");
        assert_eq!(classify("hestia_vault_set"), "credential_access");
        assert_eq!(classify("hestia_request_witness"), "witness_append");
        assert_eq!(
            classify("mcp__hestia__hestia_request_witness"),
            "witness_append"
        );
    }

    #[test]
    fn both_channel_send_names_classify_to_channel_egress() {
        for t in ["hestia_channel_send", "mcp__hestia__hestia_channel_send", "channel_send"] {
            assert_eq!(classify(t), "channel_egress", "{t}");
        }
        assert_eq!(classify("channel_sender"), "unknown", "a prefix is not the verb");
    }

    #[test]
    fn a_channel_send_target_is_never_caller_text() {
        let input = json!({"path": "/srv/somewhere/else", "url": "mailto:x@example.invalid",
                           "file_path": "x", "channel_id": "dp", "recipient": "someone"});
        for t in ["hestia_channel_send", "mcp__hestia__hestia_channel_send", "channel_send"] {
            assert_eq!(extract_target(t, &input), None, "{t}");
        }
    }
}
