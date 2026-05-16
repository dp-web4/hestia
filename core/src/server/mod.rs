//! MCP server module — implements the Hestia daemon's plugin-facing surface.
//!
//! See `docs/DESIGN_DECISIONS/0005-mcp-surface.md` in the repo root for the
//! tool / resource specification this server exposes.

mod handler;
mod http;
mod state;

pub use handler::HestiaServer;
pub use http::{serve, DEFAULT_BIND};
pub use state::{ServerState, SharedState};

use std::sync::Arc;
use tokio::sync::Mutex;

use crate::vault::Vault;

/// Build the shared server state from an unlocked Vault.
pub fn build_state(vault: Vault) -> SharedState {
    Arc::new(Mutex::new(ServerState::new(vault)))
}
