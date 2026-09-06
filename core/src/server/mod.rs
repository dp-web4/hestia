//! MCP server module — implements the Hestia daemon's plugin-facing surface.
//!
//! See `docs/DESIGN_DECISIONS/0005-mcp-surface.md` in the repo root for the
//! tool / resource specification this server exposes.

mod agents;
mod dashboard;
pub mod gate_escalation;
pub mod governance_ledger;
mod handler;
mod http;
mod hub_tab;
pub mod connect_pop;
pub mod operator_auth;
pub mod seat_config;
mod public_identity;
pub mod standing_scope;
mod state;

pub use dashboard::{
    ActivityStats, DashboardSnapshot, DeploymentHealth, RecentEntry, SocietyView, TrustView,
};
pub use handler::HestiaServer;
pub use http::{DEFAULT_BIND, serve, serve_with_callback};
pub use state::{ServerState, SharedState};

use anyhow::Result;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::vault::Vault;

/// Build the shared server state from an unlocked Vault. Opens the
/// SQLite witness chain and the file-backed trust store rooted at `home`.
///
/// The daemon is the normal long-lived vault writer, so it takes the stable
/// writer lease before any startup path can mint or persist authority. The
/// lease lives inside `Vault`, which lives inside `ServerState`, and therefore
/// remains held for the daemon lifetime. A break-glass writer cannot race it.
pub fn build_state(mut vault: Vault, home: &Path, passphrase: &str) -> Result<SharedState> {
    vault.hold_writer_lease()?;
    let state = ServerState::open(vault, home, passphrase)?;

    // `public-identity.json` is a convenience projection for the LOCKED tier,
    // never identity authority. Every successful authoritative open therefore
    // heals a missing/stale/corrupt projection from the vault-backed Society.
    // Failure to write the projection is loud but must not make the daemon
    // unavailable: transparency cannot silently become an execution gate.
    if let Err(e) = public_identity::project(home, &state.sovereign.lct_id()) {
        tracing::warn!("failed to project public identity from authoritative vault state: {e:#}");
    }

    Ok(Arc::new(Mutex::new(state)))
}
