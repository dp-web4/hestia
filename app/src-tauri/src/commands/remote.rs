use serde::Deserialize;
use serde_json::Value;
use tauri::State;

use crate::AppState;

#[derive(Deserialize)]
pub struct RemoteConfig {
    pub name: String,
    pub url: String,
}

#[tauri::command]
pub async fn add_remote(state: State<'_, AppState>, remote: RemoteConfig) -> Result<Value, String> {
    state.add_remote(&remote.name, &remote.url);
    Ok(serde_json::json!({ "added": remote.name, "url": remote.url }))
}

#[tauri::command]
pub async fn remove_remote(state: State<'_, AppState>, name: String) -> Result<Value, String> {
    state.remove_remote(&name);
    Ok(serde_json::json!({ "removed": name }))
}

#[tauri::command]
pub async fn list_remotes(state: State<'_, AppState>) -> Result<Value, String> {
    Ok(serde_json::json!({ "remotes": state.remotes() }))
}

#[tauri::command]
pub async fn get_remote_dashboard(
    _state: State<'_, AppState>,
    url: String,
) -> Result<Value, String> {
    let api_url = format!("{url}/api/dashboard");
    match reqwest::get(&api_url).await {
        Ok(resp) => resp
            .json::<Value>()
            .await
            .map_err(|e| format!("bad response from {url}: {e}")),
        Err(e) => Ok(serde_json::json!({
            "online": false,
            "error": e.to_string(),
            "url": url,
        })),
    }
}
