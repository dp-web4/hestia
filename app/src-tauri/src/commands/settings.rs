use serde_json::Value;
use tauri::State;

use crate::AppState;

#[tauri::command]
pub async fn get_config(state: State<'_, AppState>) -> Result<Value, String> {
    Ok(serde_json::json!({
        "mode": state.mode(),
        "daemon_url": state.daemon_url(),
        "remotes": state.remotes(),
    }))
}

#[tauri::command]
pub async fn set_mode(state: State<'_, AppState>, mode: String) -> Result<Value, String> {
    match mode.as_str() {
        "sovereign" | "mirror" | "hybrid" => {
            state.set_mode(&mode);
            Ok(serde_json::json!({ "mode": mode }))
        }
        _ => Err(format!("invalid mode: {mode}. expected sovereign|mirror|hybrid")),
    }
}
