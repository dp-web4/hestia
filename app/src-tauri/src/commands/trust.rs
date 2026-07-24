//! Trust derivation receipts.
//!
//! `GET /api/trust/derivation?plugin_id&role` returns the receipt for one
//! grain: the derived scores, the formula that produced them, and the
//! evidence list with chain positions (including entries EXCLUDED by
//! exoneration or amnesty). The app renders it; it never recomputes it —
//! the daemon derives, the app displays.

use serde_json::Value;
use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn get_derivation(
    state: State<'_, AppState>,
    plugin_id: String,
    role: Option<String>,
) -> Result<Value, String> {
    let mut path = format!("/api/trust/derivation?plugin_id={}", urlencode(&plugin_id));
    if let Some(r) = role.filter(|r| !r.is_empty()) {
        path.push_str(&format!("&role={}", urlencode(&r)));
    }
    daemon::get(&state, &path).await
}

/// Minimal percent-encoding for query values (plugin ids and role LCTs carry
/// `:` and `#`). Avoids pulling a dependency for three characters.
fn urlencode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            _ => c
                .to_string()
                .as_bytes()
                .iter()
                .map(|b| format!("%{b:02X}"))
                .collect(),
        })
        .collect()
}
