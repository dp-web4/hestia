//! MCP ServerHandler implementation for Hestia.
//!
//! Dispatches `call_tool` / `read_resource` / `list_*` requests against the
//! `ServerState`. Errors that map to typed plugin-side errors are returned
//! via the `_hestia_error` envelope (per ADR-0005 Mechanism A), not as
//! McpError.

use chrono::Utc;
use rmcp::{
    ServerHandler,
    model::{
        CallToolRequestParams, CallToolResult, Content, ErrorData, ListResourcesResult,
        ListToolsResult, PaginatedRequestParams, RawResource, ReadResourceRequestParams,
        ReadResourceResult, Resource, ResourceContents, ServerCapabilities, ServerInfo, Tool,
    },
    service::{RequestContext, RoleServer},
};
use serde_json::{json, Value};
use std::sync::Arc;
use uuid::Uuid;

use super::state::{InFlightAction, Session, SharedState};
use crate::vault::VaultEntry;
use web4_trust_core::EntityTrust;

#[derive(Clone)]
pub struct HestiaServer {
    pub state: SharedState,
}

impl HestiaServer {
    pub fn new(state: SharedState) -> Self {
        Self { state }
    }
}

impl ServerHandler for HestiaServer {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.capabilities = ServerCapabilities::builder()
            .enable_tools()
            .enable_resources()
            .build();
        info.server_info.name = "hestia".into();
        info.server_info.version = env!("CARGO_PKG_VERSION").to_string();
        info
    }

    async fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        let mut result = ListToolsResult::default();
        result.tools = hestia_tools();
        Ok(result)
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResult, ErrorData> {
        let name = request.name.to_string();
        let args: Value = request
            .arguments
            .map(Value::Object)
            .unwrap_or(Value::Object(serde_json::Map::new()));

        let dispatch = match name.as_str() {
            "hestia_connect" => tool_connect(&self.state, &args).await,
            "hestia_begin_action" => tool_begin_action(&self.state, &args).await,
            "hestia_record_outcome" => tool_record_outcome(&self.state, &args).await,
            "hestia_query_policy" => tool_query_policy(&self.state, &args).await,
            "hestia_vault_get" => tool_vault_get(&self.state, &args).await,
            "hestia_vault_set" => tool_vault_set(&self.state, &args).await,
            "hestia_query_history" => tool_query_history(&self.state, &args).await,
            "hestia_request_witness" => tool_request_witness(&self.state, &args).await,
            _ => Ok(hestia_error_envelope(
                "hestia.unknown_tool",
                &format!("Unknown tool: {}", name),
                Some(json!({"tool": name})),
            )),
        };

        let payload = dispatch.unwrap_or_else(|e| {
            hestia_error_envelope(
                "hestia.internal_error",
                &format!("Tool {} failed: {}", name, e),
                None,
            )
        });

        let mut result = CallToolResult::success(vec![Content::text(
            serde_json::to_string(&payload).unwrap_or_default(),
        )]);
        result.structured_content = Some(payload);
        Ok(result)
    }

    async fn list_resources(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, ErrorData> {
        let resources = vec![
            make_resource("hestia://context/shared", "Cross-agent shared context"),
            make_resource("hestia://society/state", "Society state"),
            make_resource("hestia://witness/recent", "Recent witness chain entries"),
            make_resource("hestia://session/own", "This plugin's session state"),
        ];
        let mut result = ListResourcesResult::default();
        result.resources = resources;
        Ok(result)
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResult, ErrorData> {
        let uri = request.uri.clone();
        let body = match read_resource_body(&self.state, &uri).await {
            Ok(b) => b,
            Err(msg) => {
                return Err(ErrorData::invalid_params(msg, None));
            }
        };

        // Build TextResourceContents through serde (non-exhaustive enum variant)
        let contents_value = json!([{
            "uri": uri,
            "mimeType": "application/json",
            "text": body,
        }]);
        let contents: Vec<ResourceContents> = serde_json::from_value(contents_value)
            .map_err(|e| ErrorData::internal_error(format!("contents serialization: {e}"), None))?;
        Ok(ReadResourceResult::new(contents))
    }
}

// =========================================================================
// Tool surface metadata
// =========================================================================

fn hestia_tools() -> Vec<Tool> {
    fn t(name: &'static str, description: &'static str) -> Tool {
        let schema = json!({"type": "object", "additionalProperties": true});
        let schema_obj = match schema {
            Value::Object(m) => m,
            _ => serde_json::Map::new(),
        };
        Tool::new(name, description, Arc::new(schema_obj))
    }

    vec![
        t("hestia_connect", "Establish a plugin session and receive a Soft LCT"),
        t("hestia_begin_action", "Begin tracking an R6/R7 action"),
        t("hestia_record_outcome", "Submit the outcome of an action"),
        t("hestia_query_policy", "Query the user's policy for a decision"),
        t("hestia_vault_get", "Request a credential from the vault"),
        t("hestia_vault_set", "Store a credential in the vault"),
        t("hestia_query_history", "Query the witness chain"),
        t("hestia_request_witness", "Append a custom witness chain event"),
    ]
}

fn make_resource(uri: &str, name: &str) -> Resource {
    let raw = RawResource::new(uri.to_string(), name.to_string());
    Resource::new(raw, None)
}

// =========================================================================
// Tool implementations
// =========================================================================

type ToolResult = Result<Value, anyhow::Error>;

async fn tool_connect(state: &SharedState, args: &Value) -> ToolResult {
    let plugin_id = require_string(args, "plugin_id")?;
    let host_agent = require_string(args, "host_agent")?;
    let plugin_version = optional_string(args, "plugin_version");
    let host_agent_version = optional_string(args, "host_agent_version");
    let requested_role =
        optional_string(args, "requested_role").unwrap_or_else(|| "citizen".to_string());
    let synthetic = args
        .get("synthetic")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let mut s = state.lock().await;
    let session_id = Uuid::new_v4();
    let soft_lct = s.issue_soft_lct(session_id);

    let session = Session {
        session_id,
        plugin_id: plugin_id.clone(),
        plugin_version,
        host_agent,
        host_agent_version,
        assigned_role: requested_role.clone(),
        soft_lct: soft_lct.clone(),
        connected_at: Utc::now(),
    };
    s.sessions.insert(session_id, session);

    if synthetic {
        s.mark_synthetic(&plugin_id);
    }

    // session_started is intentionally NOT written to the witness chain.
    // Sessions are RAM-only by design (transport artifacts); every hook
    // invocation opens its own MCP connection, so writing one chain entry
    // per connect would double the chain for no forensic value. Plugin
    // identity is already captured on every outcome entry. If a presence
    // signal is needed in the future, prefer a first-observation-per-day
    // sentinel over per-connect.

    Ok(json!({
        "sessionId": session_id,
        "softLct": soft_lct,
        "assignedRole": requested_role,
        "protocolVersion": 1,
    }))
}

async fn tool_begin_action(state: &SharedState, args: &Value) -> ToolResult {
    let tool_name = require_string(args, "tool_name")?;
    let target = optional_string(args, "target");
    let session_id_arg = optional_string(args, "session_id");
    let parameters = args.get("parameters").cloned();

    let mut s = state.lock().await;
    let action_id = Uuid::new_v4();
    let chain_position = s.chain_len();

    let session_id = resolve_session_uuid(&s, session_id_arg.as_deref())
        .unwrap_or_else(Uuid::nil);

    let started_at = Utc::now();
    s.actions.insert(
        action_id,
        InFlightAction {
            action_id,
            session_id,
            tool_name: tool_name.clone(),
            target,
            parameters,
            started_at,
            chain_position,
        },
    );

    Ok(json!({
        "actionId": action_id,
        "startedAt": started_at.to_rfc3339(),
        "chainPosition": chain_position,
    }))
}

async fn tool_record_outcome(state: &SharedState, args: &Value) -> ToolResult {
    let action_id_str = require_string(args, "action_id")?;
    let action_id = Uuid::parse_str(&action_id_str)
        .map_err(|_| anyhow::anyhow!("invalid action_id: not a UUID"))?;
    let success = args
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let magnitude = args.get("magnitude").and_then(Value::as_f64).unwrap_or(0.5);
    let error = optional_string(args, "error");

    let mut s = state.lock().await;
    let action = match s.actions.remove(&action_id) {
        Some(a) => a,
        None => {
            return Ok(hestia_error_envelope(
                "hestia.action_not_found",
                &format!("Action {} not found", action_id),
                Some(json!({"action_id": action_id_str})),
            ));
        }
    };

    let plugin_id = s
        .sessions
        .get(&action.session_id)
        .map(|sess| sess.plugin_id.clone())
        .unwrap_or_else(|| "anonymous".to_string());

    let entry = s.append_chain(
        "outcome",
        json!({
            "action_id": action_id,
            "tool_name": action.tool_name,
            "target": action.target,
            "success": success,
            "magnitude": magnitude,
            "error": error,
            "plugin_id": plugin_id,
        }),
    )?;

    let trust_state = s.apply_outcome(&plugin_id, success, magnitude)?;

    Ok(json!({
        "witnessEntryHash": entry.hash,
        "updatedTrustState": trust_state_json(&trust_state),
    }))
}

async fn tool_query_policy(state: &SharedState, args: &Value) -> ToolResult {
    let action_id_str = require_string(args, "action_id")?;
    let action_id = Uuid::parse_str(&action_id_str)
        .map_err(|_| anyhow::anyhow!("invalid action_id"))?;
    let s = state.lock().await;
    let action = match s.actions.get(&action_id) {
        Some(a) => a.clone(),
        None => {
            return Ok(hestia_error_envelope(
                "hestia.action_not_found",
                &format!("Action {} not found", action_id),
                Some(json!({"action_id": action_id_str})),
            ));
        }
    };

    // Build a PolicyAction from the in-flight action + classify the tool.
    // For Bash/Shell, the rule conventions (legacy safety preset) treat
    // `target_patterns` like `rm\s+-` as full-command regexes. So for
    // shell tools we substitute the full command as the target (if we
    // have it) — keeping consistency with the Python reference's
    // observed behavior. For other tools, `target` is the file/url/etc.
    // captured at begin_action time.
    let full_command_owned: Option<String> = action
        .parameters
        .as_ref()
        .and_then(|p| p.get("command"))
        .and_then(|v| v.as_str())
        .map(String::from);
    let full_command: Option<&str> = full_command_owned.as_deref();
    let target: Option<&str> = if action.tool_name == "Bash" || action.tool_name == "Shell" {
        full_command.or_else(|| action.target.as_deref())
    } else {
        action.target.as_deref()
    };
    let category = crate::policy::classify(&action.tool_name);
    let pa = crate::policy::PolicyAction {
        tool_name: &action.tool_name,
        category,
        target,
        full_command,
    };

    let evaluation = s.policy_engine.evaluate(&pa);

    // Witness the policy decision when the verdict is anything other
    // than `allow`. Deny + warn + would-deny (audit-only) are all
    // operationally interesting events — denies in particular block
    // a tool call before it runs, so PostToolUse never fires and the
    // outcome would otherwise never reach the chain. This is the
    // structural place to capture them: any policy gate flow that
    // calls query_policy gets witnessed automatically.
    let plugin_id_for_chain = s
        .sessions
        .get(&action.session_id)
        .map(|sess| sess.plugin_id.clone())
        .unwrap_or_else(|| "unknown".to_string());
    if evaluation.decision != crate::policy::PolicyDecision::Allow {
        let _ = s.append_chain(
            "policy_decision",
            json!({
                "action_id": action_id_str,
                "tool_name": action.tool_name,
                "target": target,
                "plugin_id": plugin_id_for_chain,
                "decision": evaluation.decision.as_str(),
                "enforced": evaluation.enforced,
                "rule_id": evaluation.rule_id,
                "rule_name": evaluation.rule_name,
                "reason": evaluation.reason,
            }),
        );
    }

    Ok(json!({
        "decision": evaluation.decision.as_str(),
        "reason": evaluation.reason,
        "ruleId": evaluation.rule_id,
        "ruleName": evaluation.rule_name,
        "policyId": evaluation.rule_id, // alias kept for backward compat with v0 SDKs
        "enforced": evaluation.enforced,
        "constraints": evaluation.constraints,
        // v1 sync rule engine always settles in one shot. The "evaluating"
        // status is reserved for future LLM-backed engines; orchestrators
        // already handle both branches per spec §3.4.1.
        "status": "decided",
        "nextPollMs": serde_json::Value::Null,
    }))
}

async fn tool_vault_get(state: &SharedState, args: &Value) -> ToolResult {
    let name = require_string(args, "name")?;
    let scope: Vec<String> = args
        .get("scope")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let session_id_arg = optional_string(args, "session_id");

    let s = state.lock().await;
    let entry = match s.vault.get(&name) {
        Some(e) => e.clone(),
        None => {
            return Ok(hestia_error_envelope(
                "hestia.vault_not_found",
                &format!("Credential '{}' not found", name),
                Some(json!({"name": name})),
            ));
        }
    };

    let plugin_id = s
        .resolve_plugin_id(session_id_arg.as_deref())
        .unwrap_or_default();

    if !entry.allowed_consumers.is_empty() && !entry.allows(&plugin_id) {
        return Ok(hestia_error_envelope(
            "hestia.vault_scope_mismatch",
            &format!(
                "Plugin '{}' is not in allowed_consumers for credential '{}'",
                plugin_id, name
            ),
            Some(json!({"name": name, "plugin_id": plugin_id})),
        ));
    }
    if !entry.matches_scope(&scope) {
        return Ok(hestia_error_envelope(
            "hestia.vault_scope_mismatch",
            &format!("Credential '{}' is not in scope {:?}", name, scope),
            Some(json!({"name": name, "requested_scope": scope})),
        ));
    }
    Ok(json!({"value": entry.secret}))
}

async fn tool_vault_set(state: &SharedState, args: &Value) -> ToolResult {
    let name = require_string(args, "name")?;
    let value = require_string(args, "value")?;
    let scope: Vec<String> = args
        .get("scope")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let tags: Vec<String> = args
        .get("tags")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    let allowed_consumers: Vec<String> = args
        .get("allowed_consumers")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    let mut s = state.lock().await;
    let entry = VaultEntry::new(&name, value)
        .with_scope(scope)
        .with_tags(tags)
        .with_consumers(allowed_consumers);
    let entry_id = entry.id;

    s.vault
        .upsert(entry)
        .map_err(|e| anyhow::anyhow!("vault write: {}", e))?;

    // Audit the mutation in the chain (the secret is never written; only the name).
    let _ = s.append_chain(
        "vault_set",
        json!({
            "name": name,
            "entry_id": entry_id,
        }),
    );

    Ok(json!({"stored": true, "entryId": entry_id}))
}

async fn tool_query_history(state: &SharedState, args: &Value) -> ToolResult {
    let filter = args.get("filter").cloned().unwrap_or(Value::Null);
    let limit = filter
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(50)
        .min(500) as usize;
    let tool_filter = filter.get("tool_name").and_then(Value::as_str);

    let s = state.lock().await;
    let mut entries = Vec::new();
    for e in s.recent_chain(limit as u64) {
        if let Some(tname) = tool_filter {
            let in_event = e
                .event_data
                .get("tool_name")
                .and_then(Value::as_str)
                .map(|t| t == tname)
                .unwrap_or(false);
            if !in_event {
                continue;
            }
        }
        entries.push(json!({
            "hash": e.hash,
            "prevHash": e.prev_hash,
            "timestamp": e.timestamp.to_rfc3339(),
            "eventType": e.event_type,
            "eventData": e.event_data,
            "signerLct": e.signer_lct,
            "chainPosition": e.chain_position,
        }));
    }
    Ok(json!({"entries": entries, "hasMore": false}))
}

async fn tool_request_witness(state: &SharedState, args: &Value) -> ToolResult {
    let event_type = require_string(args, "event_type")?;
    let event_data = args.get("event_data").cloned().unwrap_or(Value::Null);
    let s = state.lock().await;
    let entry = s.append_chain(&event_type, event_data)?;
    Ok(json!({"witnessEntryHash": entry.hash}))
}

// =========================================================================
// Resource implementations
// =========================================================================

async fn read_resource_body(state: &SharedState, uri: &str) -> Result<String, String> {
    let s = state.lock().await;

    if uri == "hestia://context/shared" {
        return Ok(serde_json::to_string(&s.shared_context).unwrap_or("{}".into()));
    }
    if uri == "hestia://society/state" {
        return Ok(serde_json::to_string(&json!({
            "sovereign_lct": s.sovereign_lct,
            "session_count": s.sessions.len(),
            "chain_length": s.chain_len(),
            "trust_states_known": s.trust_count(),
        }))
        .unwrap_or("{}".into()));
    }
    if uri == "hestia://witness/recent" {
        let recent: Vec<_> = s
            .recent_chain(50)
            .into_iter()
            .map(|e| {
                json!({
                    "hash": e.hash,
                    "prevHash": e.prev_hash,
                    "timestamp": e.timestamp.to_rfc3339(),
                    "eventType": e.event_type,
                    "eventData": e.event_data,
                    "signerLct": e.signer_lct,
                    "chainPosition": e.chain_position,
                })
            })
            .collect();
        return Ok(serde_json::to_string(&json!({"entries": recent})).unwrap_or("{}".into()));
    }
    if uri == "hestia://session/own" {
        let session = s
            .sessions
            .values()
            .max_by_key(|sess| sess.connected_at)
            .cloned();
        return Ok(serde_json::to_string(&session).unwrap_or("null".into()));
    }
    if let Some(plugin_id) = uri.strip_prefix("hestia://society/trust/") {
        let trust = s.trust(plugin_id);
        return Ok(serde_json::to_string(&trust_state_json(&trust)).unwrap_or("{}".into()));
    }
    if let Some(name) = uri.strip_prefix("hestia://vault/") {
        match s.vault.get(name) {
            Some(e) => {
                return Ok(serde_json::to_string(&json!({"value": e.secret}))
                    .unwrap_or("{}".into()));
            }
            None => return Err(format!("vault: credential '{}' not found", name)),
        }
    }
    Err(format!("unknown resource: {}", uri))
}

// =========================================================================
// Helpers
// =========================================================================

fn trust_state_json(trust: &EntityTrust) -> Value {
    json!({
        "entityId": trust.entity_id,
        "t3": {
            "talent": trust.t3.talent,
            "training": trust.t3.training,
            "temperament": trust.t3.temperament,
        },
        "v3": {
            "valuation": trust.v3.valuation,
            "veracity": trust.v3.veracity,
            "validity": trust.v3.validity,
        },
        "level": trust.trust_level().as_str(),
        "actionCount": trust.action_count,
        "successCount": trust.success_count,
        "successRate": trust.success_rate(),
        "daysSinceLast": trust.days_since_last_action(),
    })
}

fn resolve_session_uuid(state: &super::state::ServerState, session_id: Option<&str>) -> Option<Uuid> {
    if let Some(sid) = session_id {
        return Uuid::parse_str(sid).ok().filter(|u| state.sessions.contains_key(u));
    }
    state
        .sessions
        .values()
        .max_by_key(|sess| sess.connected_at)
        .map(|sess| sess.session_id)
}

fn hestia_error_envelope(code: &str, message: &str, data: Option<Value>) -> Value {
    json!({
        "_hestia_error": {
            "code": code,
            "message": message,
            "data": data.unwrap_or(json!({})),
        }
    })
}

fn require_string(args: &Value, key: &str) -> Result<String, anyhow::Error> {
    args.get(key)
        .and_then(Value::as_str)
        .map(String::from)
        .ok_or_else(|| anyhow::anyhow!("missing or invalid '{key}' argument"))
}

fn optional_string(args: &Value, key: &str) -> Option<String> {
    args.get(key).and_then(Value::as_str).map(String::from)
}
