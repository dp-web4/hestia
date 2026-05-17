//! HestiaClient — Rust plugin SDK for talking to the Hestia daemon.
//!
//! Async client backed by the `rmcp` crate's StreamableHTTP transport.
//! Mirrors the TypeScript and Python references. See ADR-0005 for the
//! MCP surface specification.

use chrono::{DateTime, Utc};
use rmcp::{
    ServiceExt,
    model::{
        CallToolRequestParams, CallToolResult, ClientInfo, RawContent, ReadResourceRequestParams,
        ReadResourceResult,
    },
    service::{RoleClient, RunningService},
    transport::StreamableHttpClientTransport,
};
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::errors::{HestiaError, Result};
use crate::transport::discover_hestia_endpoint;
use crate::types::*;

/// The Hestia plugin client. Construct via `HestiaClient::new(config)`, then
/// `.connect().await` before invoking other methods.
pub struct HestiaClient {
    config: HestiaClientConfig,
    state: Arc<Mutex<Option<ConnectedState>>>,
}

struct ConnectedState {
    service: RunningService<RoleClient, ClientInfo>,
    #[allow(dead_code)]
    connect: ConnectResult,
}

impl HestiaClient {
    pub fn new(config: HestiaClientConfig) -> Self {
        Self {
            config,
            state: Arc::new(Mutex::new(None)),
        }
    }

    /// Establish the MCP connection and the Hestia session.
    pub async fn connect(&self) -> Result<ConnectResult> {
        let endpoint = discover_hestia_endpoint(self.config.hestia_endpoint.as_deref());
        let transport = StreamableHttpClientTransport::from_uri(endpoint.as_str());

        let mut client_info = ClientInfo::default();
        client_info.client_info.name = self.config.plugin_id.clone();
        if let Some(v) = &self.config.plugin_version {
            client_info.client_info.version = v.clone();
        }

        let service = client_info
            .serve(transport)
            .await
            .map_err(|e| HestiaError::Transport(format!("MCP serve failed: {e}")))?;

        // Call hestia_connect
        let mut args = serde_json::Map::new();
        args.insert(
            "plugin_id".into(),
            Value::String(self.config.plugin_id.clone()),
        );
        args.insert(
            "host_agent".into(),
            Value::String(self.config.host_agent.clone()),
        );
        args.insert(
            "requested_role".into(),
            Value::String(self.config.requested_role.clone()),
        );
        args.insert(
            "protocol_version".into(),
            Value::Number(serde_json::Number::from(HESTIA_PROTOCOL_VERSION)),
        );
        if let Some(v) = &self.config.plugin_version {
            args.insert("plugin_version".into(), Value::String(v.clone()));
        }
        if let Some(v) = &self.config.host_agent_version {
            args.insert("host_agent_version".into(), Value::String(v.clone()));
        }
        args.insert("synthetic".into(), Value::Bool(self.config.synthetic));

        let result = invoke_tool::<ConnectResult>(&service, "hestia_connect", args).await?;

        // Warn (don't fail) on protocol-version mismatch. See
        // web4-standard/core-spec/presence-protocol.md §2.
        if result.protocol_version != HESTIA_PROTOCOL_VERSION {
            eprintln!(
                "[hestia-sdk] presence protocol version mismatch: SDK expects v{}, daemon reports v{}. Continuing anyway.",
                HESTIA_PROTOCOL_VERSION, result.protocol_version
            );
        }

        let mut guard = self.state.lock().await;
        *guard = Some(ConnectedState {
            service,
            connect: result.clone(),
        });
        Ok(result)
    }

    /// Close the MCP connection.
    pub async fn disconnect(&self) -> Result<()> {
        let mut guard = self.state.lock().await;
        if let Some(state) = guard.take() {
            let _ = state.service.cancel().await;
        }
        Ok(())
    }

    pub async fn begin_action(&self, spec: ToolCallSpec) -> Result<R6Action> {
        let mut args = serde_json::Map::new();
        args.insert("tool_name".into(), Value::String(spec.tool_name.clone()));
        if let Some(t) = spec.target {
            args.insert("target".into(), Value::String(t));
        }
        if !spec.parameters.is_empty() {
            args.insert(
                "parameters".into(),
                Value::Object(spec.parameters.into_iter().collect()),
            );
        }
        if let Some(s) = spec.atp_stake {
            args.insert(
                "atp_stake".into(),
                Value::Number(serde_json::Number::from_f64(s).unwrap_or(0.into())),
            );
        }

        let raw: Value = self.call_tool_raw("hestia_begin_action", args).await?;
        Ok(R6Action {
            action_id: raw
                .get("actionId")
                .and_then(Value::as_str)
                .and_then(|s| Uuid::parse_str(s).ok())
                .ok_or_else(|| HestiaError::InvalidResponse("missing actionId".into()))?,
            tool_name: spec.tool_name,
            started_at: raw
                .get("startedAt")
                .and_then(Value::as_str)
                .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                .map(|dt| dt.with_timezone(&Utc))
                .ok_or_else(|| HestiaError::InvalidResponse("missing startedAt".into()))?,
            chain_position: raw
                .get("chainPosition")
                .and_then(Value::as_u64)
                .ok_or_else(|| HestiaError::InvalidResponse("missing chainPosition".into()))?,
        })
    }

    pub async fn record_outcome(
        &self,
        action: &R6Action,
        outcome: Outcome,
    ) -> Result<OutcomeResult> {
        let mut args = serde_json::Map::new();
        args.insert(
            "action_id".into(),
            Value::String(action.action_id.to_string()),
        );
        args.insert("success".into(), Value::Bool(outcome.success));
        args.insert(
            "magnitude".into(),
            Value::Number(serde_json::Number::from_f64(outcome.magnitude).unwrap_or(0.into())),
        );
        if let Some(e) = outcome.error {
            args.insert("error".into(), Value::String(e));
        }
        if !outcome.result.is_empty() {
            args.insert(
                "result".into(),
                Value::Object(outcome.result.into_iter().collect()),
            );
        }
        self.call_tool::<OutcomeResult>("hestia_record_outcome", args).await
    }

    pub async fn query_policy(&self, action: &R6Action) -> Result<PolicyResult> {
        let mut args = serde_json::Map::new();
        args.insert(
            "action_id".into(),
            Value::String(action.action_id.to_string()),
        );
        self.call_tool::<PolicyResult>("hestia_query_policy", args).await
    }

    pub async fn vault_get(&self, name: &str, options: VaultGetOptions) -> Result<VaultValue> {
        let mut args = serde_json::Map::new();
        args.insert("name".into(), Value::String(name.to_string()));
        args.insert(
            "scope".into(),
            Value::Array(options.scope.into_iter().map(Value::String).collect()),
        );
        if let Some(r) = options.reason {
            args.insert("reason".into(), Value::String(r));
        }
        self.call_tool::<VaultValue>("hestia_vault_get", args).await
    }

    pub async fn vault_set(
        &self,
        name: &str,
        value: &str,
        options: VaultSetOptions,
    ) -> Result<Value> {
        let mut args = serde_json::Map::new();
        args.insert("name".into(), Value::String(name.to_string()));
        args.insert("value".into(), Value::String(value.to_string()));
        args.insert(
            "scope".into(),
            Value::Array(options.scope.into_iter().map(Value::String).collect()),
        );
        args.insert(
            "tags".into(),
            Value::Array(options.tags.into_iter().map(Value::String).collect()),
        );
        args.insert(
            "allowed_consumers".into(),
            Value::Array(
                options
                    .allowed_consumers
                    .into_iter()
                    .map(Value::String)
                    .collect(),
            ),
        );
        self.call_tool_raw("hestia_vault_set", args).await
    }

    pub async fn query_history(&self, filter: HistoryFilter) -> Result<HistoryResult> {
        let mut args = serde_json::Map::new();
        args.insert("filter".into(), serde_json::to_value(filter).unwrap_or(Value::Null));
        self.call_tool::<HistoryResult>("hestia_query_history", args).await
    }

    pub async fn request_witness(
        &self,
        event_type: &str,
        event_data: serde_json::Map<String, Value>,
    ) -> Result<Value> {
        let mut args = serde_json::Map::new();
        args.insert("event_type".into(), Value::String(event_type.to_string()));
        args.insert("event_data".into(), Value::Object(event_data));
        self.call_tool_raw("hestia_request_witness", args).await
    }

    pub async fn get_shared_context(&self) -> Result<Value> {
        self.read_resource_raw("hestia://context/shared").await
    }

    pub async fn get_own_trust_state(&self) -> Result<TrustState> {
        let uri = format!("hestia://society/trust/{}", self.config.plugin_id);
        let raw = self.read_resource_raw(&uri).await?;
        serde_json::from_value(raw)
            .map_err(|e| HestiaError::InvalidResponse(format!("trust state parse: {e}")))
    }

    // ----- internals ----------------------------------------------------

    async fn call_tool_raw(
        &self,
        name: &str,
        args: serde_json::Map<String, Value>,
    ) -> Result<Value> {
        let guard = self.state.lock().await;
        let state = guard.as_ref().ok_or(HestiaError::NotConnected)?;
        invoke_tool_raw(&state.service, name, args).await
    }

    async fn call_tool<T: DeserializeOwned>(
        &self,
        name: &str,
        args: serde_json::Map<String, Value>,
    ) -> Result<T> {
        let value = self.call_tool_raw(name, args).await?;
        serde_json::from_value(value)
            .map_err(|e| HestiaError::InvalidResponse(format!("tool {name}: {e}")))
    }

    /// Read an arbitrary `hestia://...` resource URI and return its JSON body.
    ///
    /// Most users want the typed wrappers (`get_shared_context`,
    /// `get_own_trust_state`); this is the raw escape hatch for resources
    /// the SDK doesn't expose typed accessors for (society/state,
    /// witness/recent, vault/{name}, society/trust/{plugin_id}, etc.).
    pub async fn read_resource_raw(&self, uri: &str) -> Result<Value> {
        let guard = self.state.lock().await;
        let state = guard.as_ref().ok_or(HestiaError::NotConnected)?;
        let result: ReadResourceResult = state
            .service
            .peer()
            .read_resource(ReadResourceRequestParams::new(uri.to_string()))
            .await
            .map_err(|e| HestiaError::Transport(format!("read_resource {uri}: {e}")))?;
        let contents = result.contents;
        let first = contents
            .into_iter()
            .next()
            .ok_or_else(|| HestiaError::InvalidResponse(format!("resource {uri} empty")))?;
        let text = match first {
            rmcp::model::ResourceContents::TextResourceContents { text, .. } => text,
            _ => {
                return Err(HestiaError::InvalidResponse(format!(
                    "resource {uri} has no text content"
                )))
            }
        };
        serde_json::from_str(&text)
            .map_err(|e| HestiaError::InvalidResponse(format!("resource {uri} parse: {e}")))
    }
}

async fn invoke_tool_raw(
    service: &RunningService<RoleClient, ClientInfo>,
    name: &str,
    args: serde_json::Map<String, Value>,
) -> Result<Value> {
    let mut params = CallToolRequestParams::new(std::borrow::Cow::Owned(name.to_string()));
    params.arguments = Some(args);
    let result: CallToolResult = service
        .peer()
        .call_tool(params)
        .await
        .map_err(|e| HestiaError::Transport(format!("tool {name}: {e}")))?;

    // Prefer structuredContent
    if let Some(structured) = result.structured_content {
        return parse_or_envelope(structured);
    }

    // Fall back to text content
    for block in &result.content {
        if let RawContent::Text(t) = &block.raw {
            let parsed: Value = serde_json::from_str(&t.text).map_err(|e| {
                HestiaError::InvalidResponse(format!("tool {name} text parse: {e}"))
            })?;
            return parse_or_envelope(parsed);
        }
    }

    Err(HestiaError::InvalidResponse(format!(
        "tool {name} returned no parseable content"
    )))
}

async fn invoke_tool<T: DeserializeOwned>(
    service: &RunningService<RoleClient, ClientInfo>,
    name: &str,
    args: serde_json::Map<String, Value>,
) -> Result<T> {
    let value = invoke_tool_raw(service, name, args).await?;
    serde_json::from_value(value)
        .map_err(|e| HestiaError::InvalidResponse(format!("tool {name} deserialize: {e}")))
}

/// Detect the `_hestia_error` envelope and map to typed error; otherwise return value.
fn parse_or_envelope(value: Value) -> Result<Value> {
    if let Some(env) = value.get("_hestia_error") {
        let code = env
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or("hestia.unknown");
        let message = env.get("message").and_then(Value::as_str).unwrap_or("");
        return Err(HestiaError::from_envelope(code, message, env.get("data")));
    }
    Ok(value)
}

/// Convenience constructor.
pub fn create_hestia_client(config: HestiaClientConfig) -> HestiaClient {
    HestiaClient::new(config)
}

