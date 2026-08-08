//! Operator sign-in commands.
//!
//! The webview drives the handshake but never holds the credential: it may
//! submit an unlock passphrase and ask "am I signed in?" — the key bytes and
//! bearer token stay in the shell (`AppState.operator`).

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{AppHandle, Manager, State};
use zeroize::Zeroizing;

use crate::{identity_vault, operator, AppState};

fn default_vault_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|dir| dir.join("identity.vault"))
        .map_err(|e| format!("resolve app identity-vault directory: {e}"))
}

fn status_with_default_path(
    app: &AppHandle,
    state: &AppState,
) -> Result<operator::OperatorStatus, String> {
    let mut status = state.operator_status();
    if !status.signed_in {
        let path = default_vault_path(app)?;
        status.vault_exists = path.exists();
        status.vault_path = Some(path.to_string_lossy().to_string());
        status.migration_available = operator::default_legacy_key_path().is_some();
    }
    Ok(status)
}

/// Signed-in-ness + principal LCT + encrypted-vault/import availability.
#[tauri::command]
pub async fn operator_status(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<operator::OperatorStatus, String> {
    status_with_default_path(&app, &state)
}

/// Unlock the encrypted identity vault and sign in. On first use only, a
/// legacy `~/.hestia/operator.key` is migrated into the app-owned vault after
/// the encrypted destination has been written, synced, and reopened.
#[tauri::command]
pub async fn operator_sign_in(
    app: AppHandle,
    state: State<'_, AppState>,
    passphrase: String,
    vault_path: Option<String>,
) -> Result<operator::OperatorStatus, String> {
    let passphrase = Zeroizing::new(passphrase);
    if passphrase.is_empty() {
        return Err("enter the identity vault passphrase".into());
    }
    let default_path = default_vault_path(&app)?;
    let path = match vault_path {
        Some(p) if !p.trim().is_empty() => p,
        _ => default_path.to_string_lossy().to_string(),
    };
    let path = PathBuf::from(path);
    let legacy = operator::default_legacy_key_path();
    let vault = if path == default_path && legacy.is_some() {
        identity_vault::migrate_plaintext_operator_key(
            legacy.as_ref().expect("checked above"),
            &path,
            passphrase.as_str(),
        )?
    } else if path.exists() {
        identity_vault::IdentityVault::open(&path, passphrase.as_str())?
    } else {
        return Err(format!(
            "no identity vault at {} and no legacy operator credential is available to import",
            path.display()
        ));
    };
    let session = operator::authenticate(&state.daemon_url(), Arc::new(vault)).await?;
    state.set_operator(session);
    Ok(state.operator_status())
}

#[tauri::command]
pub async fn operator_sign_out(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<operator::OperatorStatus, String> {
    state.clear_operator();
    status_with_default_path(&app, &state)
}
