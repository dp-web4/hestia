use serde_json::Value;
use tauri::State;

use crate::AppState;

#[tauri::command]
pub async fn get_dashboard(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/dashboard", state.daemon_url());
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn get_failures(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/failures", state.daemon_url());
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn get_daemon_status(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/dashboard", state.daemon_url());
    match reqwest::get(&url).await {
        Ok(resp) if resp.status().is_success() => {
            Ok(serde_json::json!({
                "online": true,
                "url": state.daemon_url(),
            }))
        }
        _ => {
            Ok(serde_json::json!({
                "online": false,
                "url": state.daemon_url(),
            }))
        }
    }
}
