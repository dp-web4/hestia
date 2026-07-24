use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn get_policy(state: State<'_, AppState>) -> Result<Value, String> {
    daemon::get(&state, "/api/policy").await
}

#[tauri::command]
pub async fn set_preset(state: State<'_, AppState>, preset: String) -> Result<Value, String> {
    daemon::send(
        &state,
        reqwest::Method::PUT,
        "/api/policy/preset",
        Some(serde_json::json!({ "preset": preset })),
    )
    .await
}
