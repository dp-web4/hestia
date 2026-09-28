//! Who is on this box, and is it governed — `GET /api/agents`.
//!
//! Read-only in this sprint (3a). The daemon returns the agent inventory's own report:
//! what is installed, what hestia has an adapter for, what is actually governed, and the
//! gaps between them — beings included since hestia #1076, found by their launcher's
//! `--member` rather than by a config file they do not have.
//!
//! When the inventory cannot run, the daemon answers `status: UNKNOWN` with a reason
//! rather than an empty list, because an empty list reads as "nothing ungoverned here" —
//! the exact inversion the surface exists to prevent. This command passes that through
//! untouched; `pages/Agents.tsx` must render it as the reason, never as a clean table.

use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn agents_inventory(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    daemon::get(&state, "/api/agents").await
}
