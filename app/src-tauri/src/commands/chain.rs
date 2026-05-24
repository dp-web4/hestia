use serde_json::Value;
use tauri::State;

use crate::AppState;

#[tauri::command]
pub async fn query_chain(
    state: State<'_, AppState>,
    limit: Option<u32>,
    event_type: Option<String>,
    tool_filter: Option<String>,
) -> Result<Value, String> {
    let mut url = format!("{}/api/chain?limit={}", state.daemon_url(), limit.unwrap_or(50));
    if let Some(et) = event_type {
        url.push_str(&format!("&event_type={et}"));
    }
    if let Some(tf) = tool_filter {
        url.push_str(&format!("&tool={tf}"));
    }
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn chain_stats(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/chain/stats", state.daemon_url());
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}
