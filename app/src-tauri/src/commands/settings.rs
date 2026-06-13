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
pub async fn set_mode(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    mode: String,
) -> Result<Value, String> {
    match mode.as_str() {
        "sovereign" | "mirror" | "hybrid" => {
            state.set_mode(&mode);
            crate::persist_config(&app, &state);
            Ok(serde_json::json!({ "mode": mode }))
        }
        _ => Err(format!("invalid mode: {mode}. expected sovereign|mirror|hybrid")),
    }
}

#[tauri::command]
pub async fn set_daemon_url(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    url: String,
) -> Result<Value, String> {
    let url = url.trim().trim_end_matches('/').to_string();
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err(format!(
            "invalid daemon url: {url}. expected http(s)://host:port"
        ));
    }
    state.set_daemon_url(&url);
    crate::persist_config(&app, &state);
    Ok(serde_json::json!({ "daemon_url": url }))
}
