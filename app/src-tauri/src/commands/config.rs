//! Vault-authored seat config (#944 phase 0): list, inspect, edit.
//!
//! The daemon is the only party that opens the governance vault. These commands go through the
//! same authed transport as every other `/api/*` call, so the operator bearer stays in the Rust
//! shell and the webview sees data or "sign in" — never the token, never the vault. The app is
//! a window onto the daemon's operator surface, not a second implementation of it.
//!
//! No delete. Deleting a seat's authoritative config is the fat-finger lockout primitive this
//! surface exists to make unnecessary; removing a VARIABLE is an edit and goes through PUT.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

#[derive(Deserialize)]
pub struct SeatConfigGetRequest {
    pub plugin_id: String,
}

#[derive(Deserialize)]
pub struct SeatConfigPutRequest {
    pub plugin_id: String,
    /// Ordered so the request body is byte-stable; the daemon renders from a `BTreeMap` too.
    pub env: BTreeMap<String, String>,
    #[serde(default)]
    pub note: String,
}

/// The daemon validates the id as a filename; this is the same rule, applied before the id is
/// spliced into a URL path, so a separator cannot become a different route.
fn seat_id_is_a_plain_name(id: &str) -> Result<(), String> {
    if id.is_empty()
        || id.contains('/')
        || id.contains('\\')
        || id.contains("..")
        || id.starts_with('.')
        || id.chars().any(|c| c.is_whitespace() || c == '?' || c == '#')
    {
        return Err(format!("'{id}' is not a seat id: one plain name, no separators"));
    }
    Ok(())
}

/// Keys, note, health and digests for every seat the daemon would check. No values.
#[tauri::command]
pub async fn config_seat_list(state: State<'_, AppState>) -> Result<Value, String> {
    daemon::get(&state, "/api/config/seat").await
}

/// The authoritative env map for one seat, values included, plus its projection verdict.
/// The daemon witnesses this read by member and keys.
#[tauri::command]
pub async fn config_seat_get(
    state: State<'_, AppState>,
    req: SeatConfigGetRequest,
) -> Result<Value, String> {
    seat_id_is_a_plain_name(&req.plugin_id)?;
    daemon::get(&state, &format!("/api/config/seat/{}", req.plugin_id)).await
}

/// Replace one seat's config in the vault. The daemon validates, witnesses the intent (keys,
/// not values), writes, renders in the same act, and returns the verdict of that render.
#[tauri::command]
pub async fn config_seat_put(
    state: State<'_, AppState>,
    req: SeatConfigPutRequest,
) -> Result<Value, String> {
    seat_id_is_a_plain_name(&req.plugin_id)?;
    daemon::send(
        &state,
        reqwest::Method::PUT,
        "/api/config/seat",
        Some(serde_json::json!({
            "plugin_id": req.plugin_id,
            "config": { "env": req.env, "note": req.note },
        })),
    )
    .await
}
