//! hestia-core — local-first Web4 trust layer for AI agents.
//!
//! See `docs/ARCHITECTURE.md` in the repo root for the technical shape.
//!
//! Phase 1 scope:
//! - **Vault**: ChaCha20-Poly1305 encrypted credential storage (this session)
//! - **MCP server**: rmcp-backed server exposing the surface in ADR-0005 (next)
//! - **Society state**: Web4 society with witness chain + trust evolution (after that)

pub mod error;
pub mod server;
pub mod vault;

pub use error::{CoreError, Result};
pub use vault::{Vault, VaultEntry};
