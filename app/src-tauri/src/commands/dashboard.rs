use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn get_dashboard(state: State<'_, AppState>) -> Result<Value, String> {
    daemon::get(&state, "/api/dashboard").await
}

#[tauri::command]
pub async fn get_failures(state: State<'_, AppState>) -> Result<Value, String> {
    daemon::get(&state, "/api/failures").await
}

/// Liveness + auth state in one probe, so the offline screen can tell
/// "daemon down" apart from "signed out" — they look identical otherwise
/// and that ambiguity is what made v0.1.2 read as simply broken.
#[tauri::command]
pub async fn get_daemon_status(state: State<'_, AppState>) -> Result<Value, String> {
    let url = state.daemon_url();
    // The challenge route is unauthenticated by design: reaching it proves
    // the daemon is up without needing a session.
    let online = reqwest::Client::new()
        .post(format!("{url}/api/operator/challenge"))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    let status = state.operator_status();
    Ok(serde_json::json!({
        "online": online,
        "url": url,
        "signed_in": status.signed_in,
        "operator_lct": status.lct_id,
    }))
}
