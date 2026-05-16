//! hestia-plugin-sdk — Phase 0 skeleton.
//!
//! Authoring kit for Hestia plugins written in Rust. A plugin hooks into
//! the host agent's tool-call lifecycle, builds R6/R7 records via this SDK,
//! emits them to the user's local Hestia instance over MCP, and optionally
//! queries for policy decisions and credentials.
//!
//! Status: Phase 0 (skeleton). API will change as Phase 1 implementation
//! lands. Do not depend on this for production yet.
//!
//! See `docs/PLUGIN_AUTHORING_GUIDE.md` in the repo root for the contract.

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum HestiaError {
    #[error("hestia-plugin-sdk: Phase 0 skeleton — implementation lands in Phase 1")]
    NotImplemented,
    #[error("policy denied: {0}")]
    PolicyDenied(String),
    #[error("vault: credential not found or access denied")]
    VaultAccessDenied,
    #[error("transport error: {0}")]
    Transport(String),
}

pub type Result<T> = std::result::Result<T, HestiaError>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HestiaClientConfig {
    pub plugin_id: String,
    pub hestia_endpoint: Option<String>,
    pub protocol_version: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallSpec {
    pub tool_name: String,
    pub target: Option<String>,
    pub parameters: HashMap<String, serde_json::Value>,
    pub atp_stake: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct R6Action {
    pub id: Uuid,
    pub tool_name: String,
    pub started_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Outcome {
    pub success: bool,
    pub magnitude: f64,
    pub error: Option<String>,
    pub result: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PolicyDecision {
    Allow,
    Deny,
    Warn,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyResult {
    pub decision: PolicyDecision,
    pub reason: String,
    pub policy_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultGetOptions {
    pub scope: Vec<String>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrustState {
    pub t3_talent: f64,
    pub t3_training: f64,
    pub t3_temperament: f64,
    pub v3_valuation: f64,
    pub v3_veracity: f64,
    pub v3_validity: f64,
    pub level: String,
    pub action_count: u64,
    pub days_since_last: f64,
}

/// The Hestia plugin client trait.
///
/// Implementations connect to the user's local Hestia instance over MCP.
#[async_trait]
pub trait HestiaClient: Send + Sync {
    async fn connect(&self) -> Result<()>;
    async fn disconnect(&self) -> Result<()>;
    async fn begin_action(&self, spec: ToolCallSpec) -> Result<R6Action>;
    async fn record_outcome(&self, action: &R6Action, outcome: Outcome) -> Result<()>;
    async fn query_policy(&self, action: &R6Action) -> Result<PolicyResult>;
    async fn vault_get(&self, name: &str, options: VaultGetOptions) -> Result<String>;
    async fn get_shared_context(&self) -> Result<HashMap<String, serde_json::Value>>;
    async fn get_own_trust_state(&self) -> Result<TrustState>;
}

/// Create a Hestia client.
///
/// Phase 0: returns a stub that errors on every call.
/// Phase 1: real MCP client backed by the MCP Rust SDK.
pub fn create_hestia_client(_config: HestiaClientConfig) -> Box<dyn HestiaClient> {
    Box::new(StubClient)
}

struct StubClient;

#[async_trait]
impl HestiaClient for StubClient {
    async fn connect(&self) -> Result<()> {
        Err(HestiaError::NotImplemented)
    }
    async fn disconnect(&self) -> Result<()> {
        Err(HestiaError::NotImplemented)
    }
    async fn begin_action(&self, _spec: ToolCallSpec) -> Result<R6Action> {
        Err(HestiaError::NotImplemented)
    }
    async fn record_outcome(&self, _action: &R6Action, _outcome: Outcome) -> Result<()> {
        Err(HestiaError::NotImplemented)
    }
    async fn query_policy(&self, _action: &R6Action) -> Result<PolicyResult> {
        Err(HestiaError::NotImplemented)
    }
    async fn vault_get(&self, _name: &str, _options: VaultGetOptions) -> Result<String> {
        Err(HestiaError::NotImplemented)
    }
    async fn get_shared_context(&self) -> Result<HashMap<String, serde_json::Value>> {
        Err(HestiaError::NotImplemented)
    }
    async fn get_own_trust_state(&self) -> Result<TrustState> {
        Err(HestiaError::NotImplemented)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn skeleton_compiles_and_types_are_consistent() {
        let cfg = HestiaClientConfig {
            plugin_id: "test".into(),
            hestia_endpoint: None,
            protocol_version: 0,
        };
        let _client = create_hestia_client(cfg);
    }
}
