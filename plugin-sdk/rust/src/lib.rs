//! hestia-plugin-sdk — Rust plugin authoring kit for Hestia.
//!
//! See `docs/PLUGIN_AUTHORING_GUIDE.md` in the Hestia repo root for the
//! plugin contract this SDK supports.
//!
//! Quickstart:
//!
//! ```no_run
//! use hestia_plugin_sdk::{create_hestia_client, HestiaClientConfig, ToolCallSpec, Outcome};
//!
//! # async fn ex() -> Result<(), Box<dyn std::error::Error>> {
//! let config = HestiaClientConfig::new("my-plugin", "my-agent");
//! let hestia = create_hestia_client(config);
//! hestia.connect().await?;
//!
//! let action = hestia
//!     .begin_action(ToolCallSpec::new("file_write").with_target("/tmp/x"))
//!     .await?;
//! let policy = hestia.query_policy(&action).await?;
//! // ... honor policy decision ...
//! hestia.record_outcome(&action, Outcome::success(0.5)).await?;
//!
//! hestia.disconnect().await?;
//! # Ok(()) }
//! ```

mod client;
mod errors;
mod transport;
mod types;

pub use client::{HestiaClient, create_hestia_client};
pub use errors::{HestiaError, Result};
pub use transport::{DEFAULT_HESTIA_ENDPOINT, discover_hestia_endpoint};
pub use types::{
    ClosureClaim, ConnectResult, HESTIA_PROTOCOL_VERSION, HestiaClientConfig, HistoryFilter,
    HistoryResult, Outcome, OutcomeResult, PolicyDecision, PolicyResult, R6Action, T3Roots,
    ToolCallSpec, TrustState, V3Roots, VaultGetOptions, VaultSetOptions, VaultValue, WitnessEntry,
};
