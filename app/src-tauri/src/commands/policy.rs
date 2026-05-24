use serde_json::Value;
use tauri::State;

use crate::AppState;

#[tauri::command]
pub async fn get_policy(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/policy", state.daemon_url());
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn set_preset(state: State<'_, AppState>, preset: String) -> Result<Value, String> {
    let url = format!("{}/api/policy/preset", state.daemon_url());
    let client = reqwest::Client::new();
    client
        .put(&url)
        .json(&serde_json::json!({ "preset": preset }))
        .send()
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}
