use serde::Deserialize;
use serde_json::Value;
use tauri::State;

use crate::AppState;

#[derive(Deserialize)]
pub struct VaultSetRequest {
    pub name: String,
    pub value: String,
    pub scope: Vec<String>,
    pub tags: Vec<String>,
    pub allowed_consumers: Vec<String>,
}

#[tauri::command]
pub async fn vault_list(state: State<'_, AppState>) -> Result<Value, String> {
    let url = format!("{}/api/vault", state.daemon_url());
    reqwest::get(&url)
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn vault_set(state: State<'_, AppState>, req: VaultSetRequest) -> Result<Value, String> {
    let url = format!("{}/api/vault", state.daemon_url());
    let client = reqwest::Client::new();
    client
        .post(&url)
        .json(&serde_json::json!({
            "name": req.name,
            "value": req.value,
            "scope": req.scope,
            "tags": req.tags,
            "allowed_consumers": req.allowed_consumers,
        }))
        .send()
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}

#[tauri::command]
pub async fn vault_delete(state: State<'_, AppState>, name: String) -> Result<Value, String> {
    let url = format!("{}/api/vault/{name}", state.daemon_url());
    let client = reqwest::Client::new();
    client
        .delete(&url)
        .send()
        .await
        .map_err(|e| format!("daemon unreachable: {e}"))?
        .json::<Value>()
        .await
        .map_err(|e| format!("bad response: {e}"))
}
