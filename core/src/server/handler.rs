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
            "hestia_notify" => tool_notify(&self.state, &args).await,
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
        t("hestia_notify", "Receive a hub->citizen notification: open the sealed body, record receipt, return a sealed ACK"),
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
    // The #403 capacity — normalized fail-closed to the published constellation set.
    let constellation_role = crate::reputation::normalize_constellation_role(
        optional_string(args, "role").as_deref().unwrap_or(""),
    )
    .to_string();
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
        constellation_role,
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
    // The accountability WHY — the actor's stated reason, captured at begin.
    let intent = optional_string(args, "intent");
    // The host agent's own stable session id (the real audit grain).
    let host_session_id = optional_string(args, "host_session_id");

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
            intent,
            host_session_id,
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

    let (plugin_id, role_lct) = s
        .sessions
        .get(&action.session_id)
        .map(|sess| (sess.plugin_id.clone(), sess.constellation_role.clone()))
        .unwrap_or_else(|| {
            (
                "anonymous".to_string(),
                crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string(),
            )
        });
    // Accountability WHO: the durable per-instance LCT + the #403 capacity
    // (role_lct) — the trust grain — plus session_id (audit grain), so concurrent
    // same-type sessions are attributed per-(instance, role) and distinguishable
    // per-session, not smeared onto plugin_id.
    let instance_lct = s.member_lct(&plugin_id);

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
            "instance_lct": instance_lct,
            "role_lct": role_lct,
            "session_id": action.session_id,
            "host_session_id": action.host_session_id,
            "intent": action.intent,
        }),
    )?;

    let rep_action_id = action_id.to_string();
    let rep_ctx = crate::reputation::RepContext {
        role_lct: &role_lct,
        action_type: "tool_execution",
        action_target: &action.tool_name,
        action_id: &rep_action_id,
        reason: if success { "outcome:success" } else { "outcome:failure" },
    };
    let trust_state = s.apply_outcome_ctx(&plugin_id, success, magnitude, &rep_ctx)?;

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

    // Role-scoped law (#403): evaluate the base policy, then fold in the session's
    // constellation-role overlay by STRICTEST verdict. A self-declared role can
    // only ever tighten the base (Deny > Warn > Allow), never loosen it — so
    // declaring a permissive role can't be used to escape the base floor.
    let mut evaluation = s.policy_engine.evaluate(&pa);
    let session_role = s
        .sessions
        .get(&action.session_id)
        .map(|sess| sess.constellation_role.clone())
        .unwrap_or_else(|| crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string());
    if let Some(role_engine) = s.role_policy_engines.get(&session_role) {
        let role_eval = role_engine.evaluate(&pa);
        if role_eval.decision.severity() > evaluation.decision.severity() {
            evaluation = role_eval;
        }
    }

    // Witness the policy decision when the verdict is anything other
    // than `allow`. Deny + warn + would-deny (audit-only) are all
    // operationally interesting events — denies in particular block
    // a tool call before it runs, so PostToolUse never fires and the
    // outcome would otherwise never reach the chain. This is the
    // structural place to capture them: any policy gate flow that
    // calls query_policy gets witnessed automatically.
    let (plugin_id_for_chain, role_lct) = s
        .sessions
        .get(&action.session_id)
        .map(|sess| (sess.plugin_id.clone(), sess.constellation_role.clone()))
        .unwrap_or_else(|| {
            (
                "unknown".to_string(),
                crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string(),
            )
        });
    if evaluation.decision != crate::policy::PolicyDecision::Allow {
        // A deny blocks before execution, so this is the ONLY witnessed record of a
        // denied action — carry the full accountability WHO (instance + role +
        // session) and WHY (actor intent) here, or they're lost for everything the
        // gate blocks. Computed inside the gate branch so Allow decisions skip it.
        let instance_lct = s.member_lct(&plugin_id_for_chain);
        let _ = s.append_chain(
            "policy_decision",
            json!({
                "action_id": action_id_str,
                "tool_name": action.tool_name,
                "target": target,
                "plugin_id": plugin_id_for_chain,
                "instance_lct": instance_lct,
                "role_lct": role_lct,
                "session_id": action.session_id,
                "host_session_id": action.host_session_id,
                "intent": action.intent,
                "decision": evaluation.decision.as_str(),
                "enforced": evaluation.enforced,
                "rule_id": evaluation.rule_id,
                "rule_name": evaluation.rule_name,
                "reason": evaluation.reason,
            }),
        );

        // Wire the gate's risk judgment into trust. Before this, trust evolved
        // ONLY on execution outcomes (all success → it saturated at the ceiling)
        // and NEVER on warn/deny, so trust was fully decoupled from gate-risk and
        // could not predict it (calib_export --mode gate showed zero discrimination:
        // warn/deny sat at the same trust as clean passes). A gated action is a
        // real negative signal about the actor, so it feeds `EntityTrust` as one.
        //
        // ASYMMETRIC / fail-safe (CBP's governance rule): a gate decision only
        // LOWERS trust (→ raises future scrutiny), never raises it. `deny` (the
        // action was blocked) is a stronger negative than `warn` (flagged but
        // allowed to proceed — it also gets an execution outcome later, so its
        // weight is intentionally light to avoid over-penalising). Magnitudes are
        // conservative first-cut defaults; tune if the reliability curve warrants.
        let risk_magnitude = match evaluation.decision {
            crate::policy::PolicyDecision::Deny => 0.5,
            crate::policy::PolicyDecision::Warn => 0.2,
            _ => 0.0,
        };
        if risk_magnitude > 0.0 {
            // P3a: emit the gate's trust movement as a role-scoped ReputationDelta
            // to the local bridge sink (the first source of hestia->hub reputation).
            let reason = format!("gate:{}", evaluation.decision.as_str());
            let rep_ctx = crate::reputation::RepContext {
                role_lct: &role_lct,
                action_type: "policy_gate",
                action_target: &action.tool_name,
                action_id: &action_id_str,
                reason: &reason,
            };
            let _ = s.apply_outcome_ctx(&plugin_id_for_chain, false, risk_magnitude, &rep_ctx);
        }
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

    let mut s = state.lock().await;
    // Gate vault access at the DAEMON, not just the client hook — a direct MCP
    // call must hit the same law. Evaluate base + the session's role overlay
    // (strictest wins); an enforced deny refuses the credential and witnesses
    // the decision (the only record of a blocked read). Ratified 2026-07-06:
    // unattended roles (mesh-worker / autonomous-timer) deny credential_access.
    {
        let session_uuid = resolve_session_uuid(&s, session_id_arg.as_deref());
        let (plugin_id, role_lct) = session_uuid
            .and_then(|sid| s.sessions.get(&sid))
            .map(|sess| (sess.plugin_id.clone(), sess.constellation_role.clone()))
            .unwrap_or_else(|| {
                (
                    "unknown".to_string(),
                    crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string(),
                )
            });
        let pa = crate::policy::PolicyAction {
            tool_name: "hestia_vault_get",
            category: "credential_access",
            target: Some(&name),
            full_command: None,
        };
        let mut evaluation = s.policy_engine.evaluate(&pa);
        if let Some(role_engine) = s.role_policy_engines.get(&role_lct) {
            let role_eval = role_engine.evaluate(&pa);
            if role_eval.decision.severity() > evaluation.decision.severity() {
                evaluation = role_eval;
            }
        }
        if evaluation.decision == crate::policy::PolicyDecision::Deny && evaluation.enforced {
            let instance_lct = s.member_lct(&plugin_id);
            let _ = s.append_chain(
                "policy_decision",
                json!({
                    "tool_name": "hestia_vault_get",
                    "target": name,
                    "plugin_id": plugin_id,
                    "instance_lct": instance_lct,
                    "role_lct": role_lct,
                    "session_id": session_uuid,
                    "decision": "deny",
                    "enforced": true,
                    "rule_id": evaluation.rule_id,
                    "rule_name": evaluation.rule_name,
                    "reason": evaluation.reason,
                }),
            );
            return Ok(hestia_error_envelope(
                "hestia.policy_denied",
                &format!("Vault access denied by policy: {}", evaluation.reason),
                Some(json!({"name": name, "rule_id": evaluation.rule_id})),
            ));
        }
    }
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

/// `hestia_notify` — the citizen side of HUB's hub→citizen notification leg.
///
/// A notification is the member↔hub sealed channel *reversed*: the hub sealed a
/// body to this member's pinned pubkey. This tool opens it with the member
/// identity keypair (loaded from the vault — the same identity that backs hub
/// `join`/`push`), records receipt in the witness chain (encrypted at rest;
/// auditable), and returns a sealed [`NotificationAck`](crate::hub::NotificationAck)
/// the hub opens to mark the notice delivered. Args:
/// `{ pair_id, hub_pubkey_hex, sealed, kind?, pointer_uri?, hub_lct_id? }`.
async fn tool_notify(state: &SharedState, args: &Value) -> ToolResult {
    let pair_id = Uuid::parse_str(&require_string(args, "pair_id")?)
        .map_err(|_| anyhow::anyhow!("pair_id is not a UUID"))?;
    let hub_pubkey_hex = require_string(args, "hub_pubkey_hex")?;
    let sealed = require_string(args, "sealed")?;
    let kind = args.get("kind").and_then(Value::as_str).unwrap_or("notify").to_string();
    let pointer_uri = args.get("pointer_uri").and_then(Value::as_str).map(str::to_string);
    let hub_lct_id = args
        .get("hub_lct_id")
        .and_then(Value::as_str)
        .and_then(|s| Uuid::parse_str(s).ok())
        .unwrap_or_else(Uuid::nil);

    let s = state.lock().await;

    // Load the member identity keypair from the vault — its pubkey is what the
    // hub sealed to. (Same path as the hub-callback issuer identity.)
    let secret_hex = s
        .vault
        .get("ai_identity_secret")
        .map(|e| e.secret.clone())
        .ok_or_else(|| anyhow::anyhow!("no member identity — run `hestia init --ai`"))?;
    let secret = hex::decode(&secret_hex)
        .map_err(|_| anyhow::anyhow!("identity secret is not valid hex"))?;
    let arr: [u8; 32] = secret
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("identity secret must be 32 bytes"))?;
    let keypair = web4_core::crypto::KeyPair::from_secret_bytes(&arr);

    // Open the sealed body (member↔hub channel, reversed).
    let channel = crate::hub::HubChannel::new(hub_lct_id, pair_id, &hub_pubkey_hex)?;
    let body = channel.open_notification(&keypair, &sealed)?;

    let act_id = body
        .get("act_id")
        .and_then(Value::as_str)
        .and_then(|s| Uuid::parse_str(s).ok())
        .unwrap_or_else(Uuid::nil);

    // Record receipt in the witness chain (so push and poll share one record).
    let entry = s.append_chain(
        "notify.received",
        json!({
            "kind": kind,
            "pointer_uri": pointer_uri,
            "act_id": act_id,
            "from_hub": hub_lct_id,
        }),
    )?;

    // Seal an ACK the hub opens to mark the notice delivered.
    let ack = crate::hub::NotificationAck { act_id, received_at: Utc::now() };
    let ack_sealed = channel.seal_ack(&keypair, &ack)?;

    Ok(json!({
        "opened": true,
        "kind": kind,
        "pointerUri": pointer_uri,
        "body": body,
        "ackSealed": ack_sealed,
        "witnessEntryHash": entry.hash,
    }))
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
            "talent": trust.talent(),
            "training": trust.training(),
            "temperament": trust.temperament(),
        },
        "v3": {
            "valuation": trust.valuation(),
            "veracity": trust.veracity(),
            "validity": trust.validity(),
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

#[cfg(test)]
mod accountability_tests {
    use super::*;
    use crate::vault::Vault;
    use tempfile::TempDir;

    async fn test_state() -> (TempDir, SharedState) {
        let dir = TempDir::new().unwrap();
        let vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        let state = crate::server::build_state(vault, dir.path(), "p").unwrap();
        (dir, state)
    }

    /// The accountability contract: a completed action's witnessed `outcome`
    /// event carries WHO (per-instance LCT + session_id) and WHY (actor intent),
    /// so concurrent same-type sessions are attributed per-instance and
    /// distinguishable per-session — not smeared onto `plugin_id`.
    #[tokio::test]
    async fn outcome_event_witnesses_who_and_why() {
        let (_dir, state) = test_state().await;

        let connect = tool_connect(
            &state,
            &json!({"plugin_id": "claude-code", "host_agent": "test"}),
        )
        .await
        .unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();

        let begin = tool_begin_action(
            &state,
            &json!({
                "tool_name": "Bash", "target": "ls", "session_id": sid,
                "intent": "list files for the user"
            }),
        )
        .await
        .unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();

        tool_record_outcome(
            &state,
            &json!({"action_id": aid, "success": true, "magnitude": 0.3}),
        )
        .await
        .unwrap();

        let s = state.lock().await;
        let outcome = s
            .recent_chain(20)
            .into_iter()
            .find(|e| e.event_type == "outcome")
            .expect("outcome must be witnessed");
        let d = &outcome.event_data;
        // WHO — durable per-instance LCT (trust grain) + session_id (audit grain).
        assert!(
            d["instance_lct"].as_str().unwrap().starts_with("lct:web4:member:"),
            "instance_lct must be the durable per-instance LCT, got {:?}",
            d["instance_lct"]
        );
        assert_eq!(
            d["session_id"].as_str().unwrap(),
            sid,
            "session_id must distinguish the concurrent session"
        );
        // WHY — the actor's stated intent, captured at begin, stamped on the outcome.
        assert_eq!(d["intent"].as_str().unwrap(), "list files for the user");
    }

    /// Unstated intent is recorded as `null`, never fabricated (transparent-stub).
    #[tokio::test]
    async fn absent_intent_is_null_not_fabricated() {
        let (_dir, state) = test_state().await;
        let connect = tool_connect(&state, &json!({"plugin_id":"claude-code","host_agent":"test"}))
            .await.unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();
        let begin = tool_begin_action(&state, &json!({"tool_name":"Read","session_id":sid}))
            .await.unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        tool_record_outcome(&state, &json!({"action_id":aid,"success":true})).await.unwrap();
        let s = state.lock().await;
        let outcome = s.recent_chain(20).into_iter()
            .find(|e| e.event_type == "outcome").unwrap();
        assert!(outcome.event_data["intent"].is_null(), "unstated intent must be null");
    }

    /// The ratified unattended law has TEETH at the daemon: a mesh-worker session
    /// with a credential_access overlay deny is refused by `vault_get` itself
    /// (direct MCP calls can't bypass the client hook), and the deny is witnessed
    /// with the full WHO. An attended (member) session is not blocked.
    #[tokio::test]
    async fn vault_get_denied_for_overlaid_role_and_witnessed() {
        let (_dir, state) = test_state().await;
        {
            let mut s = state.lock().await;
            let rule = crate::policy::PolicyRule {
                id: "unattended-no-vault".into(),
                name: "unattended no vault reads".into(),
                priority: 0,
                decision: crate::policy::PolicyDecision::Deny,
                reason: Some("unattended".into()),
                r#match: crate::policy::PolicyMatch {
                    categories: Some(vec!["credential_access".into()]),
                    ..Default::default()
                },
            };
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                crate::policy::PolicyEngine::new(crate::policy::PolicyConfig {
                    default_policy: crate::policy::PolicyDecision::Allow,
                    enforce: true,
                    rules: vec![rule],
                }),
            );
        }
        // mesh-worker → denied by the daemon, before the vault is even consulted.
        let mw = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:mesh-worker"
        })).await.unwrap();
        let denied = tool_vault_get(&state, &json!({
            "name":"github-pat","session_id": mw["sessionId"]
        })).await.unwrap();
        assert_eq!(denied["_hestia_error"]["code"], "hestia.policy_denied");
        // The refusal is witnessed with WHO.
        {
            let s = state.lock().await;
            let pd = s.recent_chain(10).into_iter()
                .find(|e| e.event_type == "policy_decision")
                .expect("vault deny must be witnessed");
            assert_eq!(pd.event_data["role_lct"], "role:constellation:mesh-worker");
            assert_eq!(pd.event_data["target"], "github-pat");
            assert_eq!(pd.event_data["enforced"], true);
        }
        // member (attended) → NOT policy-blocked; falls through to not-found.
        let m = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:member"
        })).await.unwrap();
        let ok = tool_vault_get(&state, &json!({
            "name":"github-pat","session_id": m["sessionId"]
        })).await.unwrap();
        assert_eq!(ok["_hestia_error"]["code"], "hestia.vault_not_found");
    }

    /// A declared constellation role flows through `connect` (normalized) onto the
    /// witnessed event's `role_lct` — trust + audit scoped per capacity (#403).
    #[tokio::test]
    async fn declared_role_flows_to_witnessed_event() {
        let (_dir, state) = test_state().await;
        let connect = tool_connect(
            &state,
            &json!({"plugin_id":"claude-code","host_agent":"test","role":"role:constellation:mesh-worker"}),
        ).await.unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();
        let begin = tool_begin_action(&state, &json!({"tool_name":"Bash","session_id":sid}))
            .await.unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        tool_record_outcome(&state, &json!({"action_id":aid,"success":true})).await.unwrap();
        let s = state.lock().await;
        let outcome = s.recent_chain(20).into_iter()
            .find(|e| e.event_type == "outcome").unwrap();
        assert_eq!(outcome.event_data["role_lct"], "role:constellation:mesh-worker");
        // an unknown role would fail closed to the default (normalize covers that unit-side)
    }

    /// The load-bearing case: a **denied** action is blocked *before* it runs,
    /// so no `outcome` event ever fires — the `policy_decision` entry is the
    /// ONLY witnessed record of the blocked act. It must still carry WHO
    /// (per-instance LCT + session_id) and WHY (actor intent), or accountability
    /// is lost for everything the gate stops.
    #[tokio::test]
    async fn denied_policy_decision_witnesses_who_and_why() {
        let (_dir, state) = test_state().await;
        // Pin the safety preset so the destructive-command rule denies
        // deterministically, independent of the fresh vault's default policy.
        {
            let mut s = state.lock().await;
            s.policy_engine = crate::policy::PolicyEngine::new(
                crate::policy::get_preset("safety").unwrap().config,
            );
        }

        let connect = tool_connect(
            &state,
            &json!({"plugin_id": "claude-code", "host_agent": "test"}),
        )
        .await
        .unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();

        // A destructive Bash command outside the scratch whitelist → deny.
        // For Bash the gate matches against the full command (from parameters).
        let begin = tool_begin_action(
            &state,
            &json!({
                "tool_name": "Bash",
                "target": "rm -rf /home/user/data",
                "parameters": {"command": "rm -rf /home/user/data"},
                "session_id": sid,
                "intent": "clean up the workspace"
            }),
        )
        .await
        .unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();

        tool_query_policy(&state, &json!({"action_id": aid}))
            .await
            .unwrap();

        let s = state.lock().await;
        let pd = s
            .recent_chain(20)
            .into_iter()
            .find(|e| e.event_type == "policy_decision")
            .expect("a deny must be witnessed as a policy_decision");
        let d = &pd.event_data;
        assert_eq!(
            d["decision"].as_str().unwrap(),
            "deny",
            "precondition: the action must actually be denied"
        );
        // WHO — durable per-instance LCT (trust grain) + session_id (audit grain).
        assert!(
            d["instance_lct"].as_str().unwrap().starts_with("lct:web4:member:"),
            "instance_lct must be the durable per-instance LCT, got {:?}",
            d["instance_lct"]
        );
        assert_eq!(
            d["session_id"].as_str().unwrap(),
            sid,
            "session_id must distinguish the concurrent session"
        );
        // WHY — the actor's intent survives on the only record a blocked act leaves.
        assert_eq!(d["intent"].as_str().unwrap(), "clean up the workspace");
    }

    /// The host agent's own stable session id is witnessed as the real audit grain.
    #[tokio::test]
    async fn host_session_id_is_witnessed_when_supplied() {
        let (_dir, state) = test_state().await;
        let connect = tool_connect(&state, &json!({"plugin_id":"claude-code","host_agent":"t"}))
            .await.unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();
        let begin = tool_begin_action(&state, &json!({
            "tool_name":"Read","session_id":sid,"host_session_id":"claude-sess-abc"
        })).await.unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        tool_record_outcome(&state, &json!({"action_id":aid,"success":true})).await.unwrap();
        let s = state.lock().await;
        let outcome = s.recent_chain(20).into_iter()
            .find(|e| e.event_type == "outcome").unwrap();
        assert_eq!(outcome.event_data["host_session_id"], "claude-sess-abc");
    }

    /// Role-scoped law (#403): a role overlay can only TIGHTEN, and only for the
    /// role that declared it. A permissive role can't escape the base floor, and a
    /// restricted role's extra denies don't leak onto other roles.
    #[tokio::test]
    async fn role_overlay_tightens_law_only_for_the_declared_role() {
        let (_dir, state) = test_state().await;
        {
            let mut s = state.lock().await;
            let rule = crate::policy::PolicyRule {
                id: "mw-deny-testtool".into(),
                name: "mesh-worker denies TestTool".into(),
                priority: 0,
                decision: crate::policy::PolicyDecision::Deny,
                reason: Some("mesh-worker restricted".into()),
                r#match: crate::policy::PolicyMatch {
                    tools: Some(vec!["TestTool".into()]),
                    ..Default::default()
                },
            };
            let cfg = crate::policy::PolicyConfig {
                default_policy: crate::policy::PolicyDecision::Allow,
                enforce: true,
                rules: vec![rule],
            };
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                crate::policy::PolicyEngine::new(cfg),
            );
        }
        // The role that declared the overlay → TestTool is denied (tightened).
        assert_eq!(decision_for(&state, "role:constellation:mesh-worker").await, "deny");
        // A different role has no overlay → base floor, not denied.
        assert_ne!(decision_for(&state, "role:constellation:interactive-dev").await, "deny");
    }

    async fn decision_for(state: &SharedState, role: &str) -> String {
        let connect = tool_connect(state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":role
        })).await.unwrap();
        let sid = connect["sessionId"].as_str().unwrap().to_string();
        let begin = tool_begin_action(state, &json!({"tool_name":"TestTool","session_id":sid}))
            .await.unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        let q = tool_query_policy(state, &json!({"action_id":aid})).await.unwrap();
        q["decision"].as_str().unwrap().to_string()
    }
}
