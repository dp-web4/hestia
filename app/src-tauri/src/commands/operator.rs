//! Operator sign-in commands.
//!
//! The webview drives the handshake but never holds its secrets: it may say
//! "sign in with the key at this path" and ask "am I signed in?" — the key
//! bytes and the bearer token stay in the shell (`AppState.operator`).

use tauri::State;

use crate::{operator, AppState};

/// Signed-in-ness + which LCT + the default key path (so the UI can offer a
/// one-click sign-in instead of a file picker).
#[tauri::command]
pub async fn operator_status(
    state: State<'_, AppState>,
) -> Result<operator::OperatorStatus, String> {
    Ok(state.operator_status())
}

/// Sign in. `key_path` defaults to `~/.hestia/operator.key` when omitted.
#[tauri::command]
pub async fn operator_sign_in(
    state: State<'_, AppState>,
    key_path: Option<String>,
) -> Result<operator::OperatorStatus, String> {
    let path = match key_path {
        Some(p) if !p.trim().is_empty() => p,
        _ => operator::default_key_path()
            .map(|p| p.to_string_lossy().to_string())
            .ok_or("no operator key found at ~/.hestia/operator.key — choose a key file")?,
    };
    let session = operator::authenticate(&state.daemon_url(), &path).await?;
    state.set_operator(session);
    Ok(state.operator_status())
}

#[tauri::command]
pub async fn operator_sign_out(
    state: State<'_, AppState>,
) -> Result<operator::OperatorStatus, String> {
    state.clear_operator();
    Ok(state.operator_status())
}
