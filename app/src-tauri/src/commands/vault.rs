use serde::Deserialize;
use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

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
    daemon::get(&state, "/api/vault").await
}

#[tauri::command]
pub async fn vault_set(state: State<'_, AppState>, req: VaultSetRequest) -> Result<Value, String> {
    daemon::send(
        &state,
        reqwest::Method::POST,
        "/api/vault",
        Some(serde_json::json!({
            "name": req.name,
            "value": req.value,
            "scope": req.scope,
            "tags": req.tags,
            "allowed_consumers": req.allowed_consumers,
        })),
    )
    .await
}

#[tauri::command]
pub async fn vault_delete(state: State<'_, AppState>, name: String) -> Result<Value, String> {
    daemon::send(
        &state,
        reqwest::Method::DELETE,
        &format!("/api/vault/{name}"),
        None,
    )
    .await
}
