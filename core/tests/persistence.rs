//! Integration test: ServerState picks up persisted chain + trust after restart.
//!
//! Sessions / in-flight actions are intentionally NOT persisted; only
//! the witness chain (SQLite) and trust (FileStore) survive.

use serde_json::json;
use tempfile::TempDir;

use hestia::server::ServerState;
use hestia::Vault;

#[test]
fn chain_and_trust_survive_daemon_restart() {
    let dir = TempDir::new().unwrap();
    let home = dir.path();
    let vault_path = home.join("vault.enc");

    // --- First daemon lifetime ---
    let vault = Vault::init(vault_path.clone(), "p".into()).unwrap();
    let s1 = ServerState::open(vault, home).unwrap();

    // Record several events + outcomes
    s1.append_chain("session_started", json!({"plugin_id": "claude"})).unwrap();
    s1.append_chain("outcome", json!({"success": true, "tool_name": "Read"})).unwrap();
    s1.append_chain("outcome", json!({"success": false, "tool_name": "Write"})).unwrap();
    s1.apply_outcome("claude", true, 0.8).unwrap();
    s1.apply_outcome("claude", true, 0.6).unwrap();
    s1.apply_outcome("claude", false, 0.4).unwrap();
    s1.apply_outcome("openclaw", true, 0.7).unwrap();

    let chain_len_before = s1.chain_len();
    let claude_before = s1.trust("claude");
    let openclaw_before = s1.trust("openclaw");

    assert_eq!(chain_len_before, 3);
    assert_eq!(claude_before.action_count, 3);
    assert_eq!(claude_before.success_count, 2);
    assert_eq!(openclaw_before.action_count, 1);
    assert_eq!(openclaw_before.success_count, 1);

    drop(s1);

    // --- Second daemon lifetime ---
    let vault2 = Vault::open(vault_path, "p".into()).unwrap();
    let s2 = ServerState::open(vault2, home).unwrap();

    // Sessions and actions are RAM-only — must be empty.
    assert_eq!(s2.sessions.len(), 0);
    assert_eq!(s2.actions.len(), 0);

    // Chain and trust must be intact.
    assert_eq!(s2.chain_len(), chain_len_before);
    let claude_after = s2.trust("claude");
    let openclaw_after = s2.trust("openclaw");

    assert_eq!(claude_after.action_count, claude_before.action_count);
    assert_eq!(claude_after.success_count, claude_before.success_count);
    assert_eq!(openclaw_after.action_count, openclaw_before.action_count);
    assert_eq!(openclaw_after.success_count, openclaw_before.success_count);

    // T3/V3 values should match (within float tolerance — they're persisted).
    assert!((claude_after.t3.training - claude_before.t3.training).abs() < 1e-9);
    assert!((claude_after.v3.veracity - claude_before.v3.veracity).abs() < 1e-9);

    // Most recent chain entry must hash-link to its predecessor.
    let recent = s2.recent_chain(10);
    assert_eq!(recent.len(), 3);
    assert_eq!(recent[0].prev_hash, recent[1].hash);
    assert_eq!(recent[1].prev_hash, recent[2].hash);
    assert_eq!(recent[2].prev_hash, "0".repeat(64));

    // Append after restart continues the chain unbroken.
    let new_entry = s2.append_chain("outcome", json!({"after_restart": true})).unwrap();
    assert_eq!(new_entry.chain_position, 3);
    assert_eq!(new_entry.prev_hash, recent[0].hash);
}
