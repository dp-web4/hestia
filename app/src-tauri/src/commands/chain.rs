use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn query_chain(
    state: State<'_, AppState>,
    limit: Option<u32>,
    event_type: Option<String>,
    tool_filter: Option<String>,
) -> Result<Value, String> {
    let mut path = format!("/api/chain?limit={}", limit.unwrap_or(50));
    if let Some(et) = event_type.filter(|s| !s.is_empty()) {
        path.push_str(&format!("&event_type={et}"));
    }
    if let Some(tf) = tool_filter.filter(|s| !s.is_empty()) {
        path.push_str(&format!("&tool={tf}"));
    }
    daemon::get(&state, &path).await
}

/// Chain summary. The daemon has no `/api/chain/stats` route (the old app
/// called one and always 404'd); the numbers live on the dashboard snapshot's
/// `society` block, so read them from there.
#[tauri::command]
pub async fn chain_stats(state: State<'_, AppState>) -> Result<Value, String> {
    let snap = daemon::get(&state, "/api/dashboard").await?;
    Ok(serde_json::json!({
        "chain_length": snap.pointer("/society/chain_length").cloned().unwrap_or(Value::Null),
        "active_sessions": snap.pointer("/society/active_sessions").cloned().unwrap_or(Value::Null),
        "known_plugins": snap.pointer("/society/known_plugins").cloned().unwrap_or(Value::Null),
        "vault_entries": snap.pointer("/society/vault_entries").cloned().unwrap_or(Value::Null),
    }))
}
