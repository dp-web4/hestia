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

use anyhow::Result;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::vault::Vault;

/// Build the shared server state from an unlocked Vault. Opens the
/// SQLite witness chain and the file-backed trust store rooted at `home`.
pub fn build_state(vault: Vault, home: &Path) -> Result<SharedState> {
    let state = ServerState::open(vault, home)?;
    Ok(Arc::new(Mutex::new(state)))
}
