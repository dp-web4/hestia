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

/// Liveness, compatibility and auth state in one probe, so the UI can tell "daemon down",
/// "daemon speaks a different API" and "signed out" apart. They look identical otherwise,
/// and that ambiguity is what made v0.1.2 read as simply broken.
///
/// The probe is the unauthenticated `GET /api/version` handshake (web4#904). It replaced a
/// `POST /api/operator/challenge`, which proved liveness but minted a nonce on every poll and
/// said nothing about whether the daemon was a release this app can talk to.
#[tauri::command]
pub async fn get_daemon_status(state: State<'_, AppState>) -> Result<Value, String> {
    let url = state.daemon_url();
    // Always fresh here: this is the screen that tells the operator what is on the other end.
    let h = crate::handshake::handshake(&url).await;
    state.store_handshake(&url, &h);
    let status = state.operator_status();
    Ok(serde_json::json!({
        "online": h.state.answered(),
        "url": url,
        "signed_in": status.signed_in,
        "operator_lct": status.lct_id,
        "handshake": h,
    }))
}
