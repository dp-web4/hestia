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
            "hestia_record_reversal" => tool_record_reversal(&self.state, &args).await,
            "hestia_witness_decision" => tool_witness_decision(&self.state, &args).await,
            "hestia_query_policy" => tool_query_policy(&self.state, &args).await,
            "hestia_vault_get" => tool_vault_get(&self.state, &args).await,
            "hestia_vault_set" => tool_vault_set(&self.state, &args).await,
            "hestia_query_history" => tool_query_history(&self.state, &args).await,
            "hestia_request_witness" => tool_request_witness(&self.state, &args).await,
            "hestia_notify" => tool_notify(&self.state, &args).await,
            "hestia_inbox" => tool_inbox(&self.state, &args).await,
            "hestia_pair_inbox" => tool_pair_inbox(&self.state, &args).await,
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
        t("hestia_record_reversal", "Record a reversal/override of a subject's work (judgment signal → trust)"),
        t("hestia_witness_decision", "Witness an externally-adjudicated plugin-gate deny/warn (chain + gate-risk trust)"),
        t("hestia_query_policy", "Query the user's policy for a decision"),
        t("hestia_vault_get", "Request a credential from the vault"),
        t("hestia_vault_set", "Store a credential in the vault"),
        t("hestia_query_history", "Query the witness chain"),
        t("hestia_request_witness", "Append a custom witness chain event"),
        t("hestia_notify", "Receive a hub->citizen notification: open the sealed body, record receipt, return a sealed ACK. Pass defer:true to park it (still sealed) in the durable encrypted inbox and ACK without returning the body"),
        t("hestia_inbox", "Drain the durable inbound mailbox (consume-once): opens deferred notices with the member identity, oldest first"),
        t("hestia_pair_inbox", "Drain SECRETS sent over confirmed paired channels (pull-side): opens each peer pair_message as a SecretEnvelope, advances a per-pair cursor so each is delivered once. Credential-access gated (§7.8.2) — an unattended caller is deferred and the secret waits for an attended drain"),
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
    // Fail-closed synthetic declaration: a client that declares itself synthetic
    // must have that exclusion durably PERSISTED before we admit it — otherwise a
    // restart loses the exclusion and mints durable member labels for a test
    // harness (the write-side mirror of the corrupt-doc load bug). Retry the
    // persist up to a law-settable budget (vault policy, default 3); if every
    // attempt fails, REFUSE the connect rather than admit an unpersisted
    // synthetic member. Done BEFORE the session is inserted so a refusal leaves
    // no half-open session behind.
    if synthetic {
        let max_attempts = s.vault.policy().synthetic_persist_attempts();
        if let Err(e) = s.mark_synthetic(&plugin_id, max_attempts) {
            return Ok(hestia_error_envelope(
                "hestia.internal_error",
                &format!(
                    "refusing connect: could not persist synthetic exclusion for '{plugin_id}' \
                     after {max_attempts} attempt(s) (fail-closed): {e}"
                ),
                None,
            ));
        }
    }

    // First-observation member minting: a non-synthetic member that connects is
    // a real member and gets durable presence (a custodial member LCT), minted
    // once and cheap-looked-up thereafter. Fail-OPEN — a mint that can't persist
    // just isn't published yet; it must never block a connect (presence is not a
    // safety gate, unlike the synthetic exclusion above). Not per-connect work in
    // steady state: the in-memory registry short-circuits an already-known member.
    if !synthetic {
        let sovereign_anchor = s.sovereign_lct.clone();
        let sovereign_id = s.sovereign.lct_id();
        let is_syn = s.is_synthetic(&plugin_id);
        // Split the disjoint field borrows explicitly (the borrow checker can't
        // see through a method call that takes &mut self).
        let super::state::ServerState { vault, member_registry, .. } = &mut *s;
        crate::member_registry::ensure_member(
            vault,
            member_registry,
            &plugin_id,
            is_syn,
            &sovereign_id,
            &sovereign_anchor,
        );
    }

    s.sessions.insert(session_id, session);

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
    let (session_plugin_id, session_role) = s
        .sessions
        .get(&action.session_id)
        .map(|sess| (sess.plugin_id.clone(), sess.constellation_role.clone()))
        .unwrap_or_else(|| {
            (
                "unknown".to_string(),
                crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string(),
            )
        });
    if let Some(role_engine) = s.role_policy_engines.get(&session_role) {
        evaluation = crate::policy::fold_strictest(evaluation, role_engine.evaluate(&pa));
    }
    // Finest grain: the per-(instance, role) overlay for THIS orchestrator, folded
    // AFTER the role overlay so a specific instance can only tighten its role's law.
    if let Some(inst_engine) = s
        .instance_policy_engines
        .get(&(session_plugin_id.clone(), session_role.clone()))
    {
        evaluation = crate::policy::fold_strictest(evaluation, inst_engine.evaluate(&pa));
    }
    // Third fold input (consolidation 2026-07-10): hub law via the
    // canonical web4-policy engine. Strictest-wins like the role overlay —
    // law can only tighten, never loosen.
    if let Some(gate) = &s.law_gate {
        evaluation = crate::policy::fold_strictest(evaluation, gate.evaluate(&pa, &session_role));
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
        // Steering text for the agent that was blocked (deny-as-redirect,
        // thread hestia-lct-concord 2026-07-10). Null except on enforced deny.
        // Clients surface it verbatim on their deny channel and never parse
        // it; `reason`/`ruleName` stay the machine-readable fields.
        "guidance": evaluation.guidance(),
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

/// The WHO behind a direct tool call, resolved from an optional caller-supplied
/// session id (falling back to the latest-connected session, then to the
/// unattributed default — hestia's cooperative-attribution model).
struct CallerWho {
    session_uuid: Option<Uuid>,
    plugin_id: String,
    role_lct: String,
}

fn resolve_caller(s: &super::state::ServerState, session_id_arg: Option<&str>) -> CallerWho {
    let session_uuid = resolve_session_uuid(s, session_id_arg);
    let (plugin_id, role_lct) = session_uuid
        .and_then(|sid| s.sessions.get(&sid))
        .map(|sess| (sess.plugin_id.clone(), sess.constellation_role.clone()))
        .unwrap_or_else(|| {
            (
                "unknown".to_string(),
                crate::reputation::DEFAULT_CONSTELLATION_ROLE.to_string(),
            )
        });
    CallerWho { session_uuid, plugin_id, role_lct }
}

/// Daemon-side policy gate for the direct-call tool surfaces (vault get/set,
/// witness append) — a direct MCP call must hit the same law as the client
/// hook. Evaluates base + the caller's role overlay (strictest wins, enforced
/// breaks ties); an enforced deny witnesses the refusal with full WHO (the
/// only record of a blocked call) and returns the error envelope to send back.
/// Ratified 2026-07-06: unattended roles deny credential_access.
fn gate_direct_tool(
    s: &mut super::state::ServerState,
    who: &CallerWho,
    tool_name: &str,
    category: &'static str,
    target: &str,
) -> Option<Value> {
    let pa = crate::policy::PolicyAction {
        tool_name,
        category,
        target: Some(target),
        full_command: None,
    };
    let mut evaluation = s.policy_engine.evaluate(&pa);
    if let Some(role_engine) = s.role_policy_engines.get(&who.role_lct) {
        evaluation = crate::policy::fold_strictest(evaluation, role_engine.evaluate(&pa));
    }
    // Finest grain: the per-(instance, role) overlay for this caller, folded after
    // the role overlay — the direct-call gate must honor the same instance law.
    if let Some(inst_engine) = s
        .instance_policy_engines
        .get(&(who.plugin_id.clone(), who.role_lct.clone()))
    {
        evaluation = crate::policy::fold_strictest(evaluation, inst_engine.evaluate(&pa));
    }
    // Hub-law third input applies to the vault gate too — a norm that
    // denies secret reads must bind here, not only on tool calls.
    if let Some(gate) = &s.law_gate {
        evaluation = crate::policy::fold_strictest(evaluation, gate.evaluate(&pa, &who.role_lct));
    }
    if evaluation.decision == crate::policy::PolicyDecision::Deny && evaluation.enforced {
        let instance_lct = s.member_lct(&who.plugin_id);
        let _ = s.append_chain(
            "policy_decision",
            json!({
                "tool_name": tool_name,
                "target": target,
                "plugin_id": who.plugin_id,
                "instance_lct": instance_lct,
                "role_lct": who.role_lct,
                "session_id": who.session_uuid,
                "decision": "deny",
                "enforced": true,
                "rule_id": evaluation.rule_id,
                "rule_name": evaluation.rule_name,
                "reason": evaluation.reason,
            }),
        );
        // The envelope message is what the calling agent reads — carry the
        // steering text (guidance is Some here: enforced deny), not the bare
        // reason, so a vault deny redirects the same way a gate deny does.
        let message = evaluation.guidance().unwrap_or_else(|| {
            format!("{} denied by policy: {}", tool_name, evaluation.reason)
        });
        return Some(hestia_error_envelope(
            "hestia.policy_denied",
            &message,
            Some(json!({"target": target, "rule_id": evaluation.rule_id})),
        ));
    }
    None
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
    let who = resolve_caller(&s, session_id_arg.as_deref());
    if let Some(denied) = gate_direct_tool(&mut s, &who, "hestia_vault_get", "credential_access", &name)
    {
        return Ok(denied);
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

    let session_id_arg = optional_string(args, "session_id");

    let mut s = state.lock().await;
    // Credential WRITES are the same tamper surface as reads (malicious
    // replacement, persistence), so they hit the same daemon-side law —
    // GPT 3rd-pass HST-002. classify() already maps hestia_vault_set to
    // credential_access, so the ratified unattended-role deny binds here too.
    let who = resolve_caller(&s, session_id_arg.as_deref());
    if let Some(denied) = gate_direct_tool(&mut s, &who, "hestia_vault_set", "credential_access", &name)
    {
        return Ok(denied);
    }
    let entry = VaultEntry::new(&name, value)
        .with_scope(scope)
        .with_tags(tags)
        .with_consumers(allowed_consumers);
    let entry_id = entry.id;

    s.vault
        .upsert(entry)
        .map_err(|e| anyhow::anyhow!("vault write: {}", e))?;

    // Audit the mutation in the chain (the secret is never written; only the
    // name), attributed to the writing WHO.
    let _ = s.append_chain(
        "vault_set",
        json!({
            "name": name,
            "entry_id": entry_id,
            "plugin_id": who.plugin_id,
            "role_lct": who.role_lct,
            "session_id": who.session_uuid,
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

/// Event types the daemon itself writes. `request_witness` must not be able to
/// forge them — a caller-authored "policy_decision" or "outcome" entry would
/// poison the audit semantics of the whole chain (GPT 3rd-pass HST-003).
const RESERVED_EVENT_TYPES: &[&str] = &[
    "outcome",
    "policy_decision",
    "policy_edit",
    "vault_set",
    "orchestrator_connect",
    "notify.received",
    "reversal",
];

/// Reversal kinds — a JUDGMENT signal about an actor's work, distinct from the
/// execution `outcome` (did the tool run?) and the rule `policy_decision` (did a
/// pattern match?). This is the signal the calibration analysis found missing:
/// the rule-gate is trust-blind by construction, so trust can't predict it —
/// but a reversal IS evidence about the actor's judgment, which trust should
/// (falsifiably) predict. Instrumented 2026-07-07.
///
/// There is deliberately NO `review_reject` kind. Under the judge-disjoint
/// split (calibration-prd4, concurred 2026-07-07): dp's human-gate decisions
/// FEED trust as reversal events; peer review verdicts (MERGE /
/// REQUEST_CHANGES / REJECT) are the HELD-OUT calibration target and must
/// never feed trust, or the circularity the split exists to break returns
/// through the side door. A human-gate rejection is an `override`.
const REVERSAL_KINDS: &[&str] = &["override", "rollback", "incident"];

/// Record a reversal/override of a prior action — a delayed NEGATIVE judgment
/// about the SUBJECT (instance, role), fed into the subject's JUDGMENT-axis
/// trust (never the execution scalar — see [`judgment_entity_key`]) and
/// witnessed. The subject is passed explicitly (`subject_plugin_id`
/// [+ `subject_role`]) because the reverted work is usually attributed after
/// the subject's session has ended (e.g. dp reverting a worker's merged PR).
/// The REPORTER (the caller) must be an attributable live session, is gated by
/// role policy (`reversal_report`), and is witnessed for accountability — a
/// malicious reversal report is traceable and deniable by law.
///
/// [`judgment_entity_key`]: super::state::ServerState::judgment_entity_key
async fn tool_record_reversal(state: &SharedState, args: &Value) -> ToolResult {
    let subject_plugin_id = require_string(args, "subject_plugin_id")?;
    // A cross-actor judgment must land on a real trust grain: an unknown role
    // string is an error here, not a silent fallback to the default role (that
    // would misattribute the penalty AND pollute the calibration stream).
    let declared_role = optional_string(args, "subject_role").unwrap_or_default();
    let subject_role = if declared_role.is_empty() {
        crate::reputation::DEFAULT_CONSTELLATION_ROLE
    } else {
        match crate::reputation::KNOWN_CONSTELLATION_ROLES
            .iter()
            .copied()
            .find(|r| *r == declared_role)
        {
            Some(r) => r,
            None => {
                return Ok(hestia_error_envelope(
                    "hestia.reversal_unknown_role",
                    &format!(
                        "subject_role '{declared_role}' is not a published constellation role"
                    ),
                    Some(json!({"subject_role": declared_role})),
                ))
            }
        }
    };
    let kind = require_string(args, "kind")?;
    if !REVERSAL_KINDS.contains(&kind.as_str()) {
        return Ok(hestia_error_envelope(
            "hestia.reversal_unknown_kind",
            &format!("kind '{}' not in {:?}", kind, REVERSAL_KINDS),
            Some(json!({"kind": kind})),
        ));
    }
    let reason = optional_string(args, "reason");
    // Severity of the reversal → trust penalty. Bounded [0,1]; default moderate.
    let magnitude = args
        .get("magnitude")
        .and_then(Value::as_f64)
        .unwrap_or(0.4)
        .clamp(0.0, 1.0);
    let reference = optional_string(args, "ref");
    let session_id_arg = optional_string(args, "session_id");

    let mut s = state.lock().await;
    let reporter = resolve_caller(&s, session_id_arg.as_deref());
    // A negative judgment from an unattributable reporter must not feed trust:
    // for a calibration instrument, poisoned data is worse than missing data.
    if reporter.session_uuid.is_none() {
        return Ok(hestia_error_envelope(
            "hestia.reversal_unattributed_reporter",
            "no live session resolves for the caller — connect first; \
             an unattributable reporter cannot move another actor's trust",
            None,
        ));
    }
    // Same law as the other direct-call surfaces: role overlays can deny who
    // may report reversals, and an enforced deny is witnessed with full WHO.
    if let Some(denied) =
        gate_direct_tool(&mut s, &reporter, "hestia_record_reversal", "reversal_report", &kind)
    {
        return Ok(denied);
    }
    let subject_instance_lct = s.member_lct(&subject_plugin_id);

    // Witness the reversal — the subject's WHO + the reporter's WHO (accountability
    // for who leveled the judgment) + the pointer to the reverted work.
    let entry = s.append_chain(
        "reversal",
        json!({
            "subject_plugin_id": subject_plugin_id,
            "subject_instance_lct": subject_instance_lct,
            "subject_role": subject_role,
            "kind": kind,
            "reason": reason,
            "ref": reference,
            "magnitude": magnitude,
            "reported_by": {
                "plugin_id": reporter.plugin_id,
                "role_lct": reporter.role_lct,
                "session_id": reporter.session_uuid,
            },
        }),
    )?;

    // Feed the SUBJECT's JUDGMENT-axis trust — a separate entity from the
    // execution scalar, so the ~10³/day execution stream can't refill the dip
    // (measured: a shared t3_average recovers a reversal within minutes and
    // the estimator stays a constant). Distinct `action_type` separates the
    // delta stream too.
    let ref_target = reference.clone().unwrap_or_default();
    let rev_reason = format!("reversal:{kind}");
    let rep_ctx = crate::reputation::RepContext {
        role_lct: subject_role,
        action_type: "reversal",
        action_target: &ref_target,
        action_id: "",
        reason: &rev_reason,
    };
    let judgment_state = s.apply_judgment_ctx(&subject_plugin_id, false, magnitude, &rep_ctx)?;

    Ok(json!({
        "witnessEntryHash": entry.hash,
        "subjectInstanceLct": subject_instance_lct,
        "updatedJudgmentTrust": trust_state_json(&judgment_state),
    }))
}

/// Externally-adjudicated gate decision: a plugin-side gate (the scope/egress
/// membrane that runs INSIDE the member's hook engine, BEFORE the daemon is
/// consulted) reporting a deny/warn it already enforced. Recorded as a
/// `policy_decision` chain entry — the dashboard's warn/deny feed and denied
/// counters consume these — with the adjudicator named, and fed to gate-risk
/// trust with the daemon gate's own asymmetric weights (deny 0.5 / warn 0.2;
/// a gate decision only LOWERS trust). Without this surface, local-gate denies
/// were witnessed only in the plugin's own observe log: invisible to the
/// dashboard, the policy feed, and trust (dp, 2026-07-23: "dashboard still
/// does not show any of the denied calls for codex").
///
/// Trust note: this is loopback-/mcp-reachable like `hestia_record_outcome`,
/// which can already push negative outcomes — no NEW poisoning class; the
/// /mcp caller-auth work (public-release P0-3) gates both together.
async fn tool_witness_decision(state: &SharedState, args: &Value) -> ToolResult {
    let plugin_id = require_string(args, "plugin_id")?;
    let decision = require_string(args, "decision")?;
    if decision != "deny" && decision != "warn" {
        return Ok(hestia_error_envelope(
            "hestia.witness_decision_kind",
            &format!("decision '{decision}' must be 'deny' or 'warn'"),
            Some(json!({"decision": decision})),
        ));
    }
    let adjudicator = require_string(args, "adjudicator")?;
    let reason = optional_string(args, "reason").unwrap_or_default();
    let tool_name = optional_string(args, "tool_name").unwrap_or_default();
    let target = optional_string(args, "target").unwrap_or_default();
    let session_id = optional_string(args, "session_id");
    let payload_sha256 = optional_string(args, "payload_sha256");
    let declared_role = optional_string(args, "role").unwrap_or_default();
    let role_lct = crate::reputation::normalize_constellation_role(&declared_role);

    let s = state.lock().await;
    let instance_lct = s.member_lct(&plugin_id);
    let entry = s.append_chain(
        "policy_decision",
        json!({
            "tool_name": tool_name,
            "target": target,
            "plugin_id": plugin_id,
            "instance_lct": instance_lct,
            "role_lct": role_lct,
            "session_id": session_id,
            "decision": decision,
            "enforced": true,
            "adjudicator": adjudicator,
            "reason": reason,
            "payload_sha256": payload_sha256,
        }),
    )?;
    // Same asymmetric gate-risk trust as the daemon's own gate decisions.
    let risk_magnitude = if decision == "deny" { 0.5 } else { 0.2 };
    let gate_reason = format!("gate:{decision} ({adjudicator})");
    let rep_ctx = crate::reputation::RepContext {
        role_lct,
        action_type: "policy_gate",
        action_target: &tool_name,
        action_id: "",
        reason: &gate_reason,
    };
    let trust_state = s.apply_outcome_ctx(&plugin_id, false, risk_magnitude, &rep_ctx)?;
    Ok(json!({
        "witnessEntryHash": entry.hash,
        "decision": decision,
        "updatedTrust": trust_state_json(&trust_state),
    }))
}

async fn tool_request_witness(state: &SharedState, args: &Value) -> ToolResult {
    let event_type = require_string(args, "event_type")?;
    let event_data = args.get("event_data").cloned().unwrap_or(Value::Null);
    let session_id_arg = optional_string(args, "session_id");

    if RESERVED_EVENT_TYPES.contains(&event_type.as_str()) {
        return Ok(hestia_error_envelope(
            "hestia.witness_reserved_event",
            &format!("event_type '{}' is reserved for daemon-authored events", event_type),
            Some(json!({"event_type": event_type})),
        ));
    }

    let mut s = state.lock().await;
    // The chain is the audit surface, so appending to it is itself a gated,
    // attributed act: law can deny it per role (category witness_append), and
    // what lands on the chain carries the requesting WHO next to the caller's
    // payload — never only caller-supplied data.
    let who = resolve_caller(&s, session_id_arg.as_deref());
    if let Some(denied) =
        gate_direct_tool(&mut s, &who, "hestia_request_witness", "witness_append", &event_type)
    {
        return Ok(denied);
    }
    let entry = s.append_chain(
        &event_type,
        json!({
            "requested_by": {
                "plugin_id": who.plugin_id,
                "role_lct": who.role_lct,
                "session_id": who.session_uuid,
            },
            "data": event_data,
        }),
    )?;
    Ok(json!({"witnessEntryHash": entry.hash}))
}

/// `hestia_notify` — the citizen side of an inbound HUB→citizen sealed notice.
///
/// A notice is a sealed body the **hub** encrypted to this member's pinned pubkey;
/// this tool opens it with the member identity keypair, records receipt in the
/// witness chain, and returns a sealed
/// [`NotificationAck`](crate::hub::NotificationAck). Wire:
/// `{ pair_id, hub_pubkey_hex, sealed, kind?, pointer_uri?, hub_lct_id? }`.
///
/// **Member→member SECRETS do NOT come through here.** They ride confirmed paired
/// channels as `pair_message`s and are drained by [`tool_pair_inbox`]
/// (dp 2026-07-20). The old peer-sealed path — a peer pre-sealing a notice and the
/// receiver resolving the sender's operational key from the registry (`sealed_by`,
/// HUB #545 / ruling B) — was retired once the pairing dogfood landed; the pairing
/// keys make that registry-PKI resolution unnecessary.
async fn tool_notify(state: &SharedState, args: &Value) -> ToolResult {
    let pair_id = Uuid::parse_str(&require_string(args, "pair_id")?)
        .map_err(|_| anyhow::anyhow!("pair_id is not a UUID"))?;
    let sealed = require_string(args, "sealed")?;
    let kind = args.get("kind").and_then(Value::as_str).unwrap_or("notify").to_string();
    let pointer_uri = args.get("pointer_uri").and_then(Value::as_str).map(str::to_string);
    // The HUB is the sealer (hub→citizen notification).
    let hub_lct_id = args
        .get("hub_lct_id")
        .and_then(Value::as_str)
        .and_then(|s| Uuid::parse_str(s).ok())
        .unwrap_or_else(Uuid::nil);
    let hub_pubkey_hex = optional_string(args, "hub_pubkey_hex")
        .ok_or_else(|| anyhow::anyhow!("hub_pubkey_hex required (the hub's channel pubkey that sealed this notice)"))?;

    let mut s = state.lock().await;

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

    let defer_requested = args.get("defer").and_then(Value::as_bool).unwrap_or(false);

    // Law gate on the BODY-RETURNING mode: returning the opened body to the
    // caller is a secret release (`credential_access` — the same category the
    // ratified law already denies for unattended roles). A DENIED open does not
    // reject the notice: it AUTO-DEFERS — the still-sealed notice parks in the
    // durable inbox for an authorized consumer, so failing closed on the
    // release never loses the work item (accept-and-defer is exactly the safe
    // downgrade). The transient in-process open above is not a release: the
    // plaintext never leaves the daemon and never rests.
    let mut denied_open: Option<Value> = None;
    if !defer_requested {
        let session_id_arg = optional_string(args, "session_id");
        let who = resolve_caller(&s, session_id_arg.as_deref());
        denied_open = gate_direct_tool(&mut s, &who, "hestia_notify", "credential_access", &kind);
    }
    let defer = defer_requested || denied_open.is_some();

    // Accept-and-defer (entity-edge inbox): park the STILL-SEALED notice in the
    // durable encrypted inbox BEFORE the receipt record and BEFORE sealing the
    // ACK — the ACK tells the hub "delivered, stop queuing", so the park must
    // be durable first (O: a failed park errors out here and the hub keeps its
    // copy; an ACK-then-crash can no longer lose the work item). The body was
    // opened only transiently above (the ACK needs `act_id`); the plaintext is
    // never persisted.
    if defer {
        s.inbox_store
            .enqueue(pair_id, hub_lct_id, &hub_pubkey_hex, &sealed, &kind, pointer_uri.as_deref())
            .map_err(|e| anyhow::anyhow!("deferring notice to inbox (hub NOT acked): {e}"))?;
    }

    // Record receipt in the witness chain (so push and poll share one record).
    // AFTER the park: the record states `deferred` as a fact that is already
    // durable, never as an intention that might have failed.
    let entry = s.append_chain(
        "notify.received",
        json!({
            "kind": kind,
            "pointer_uri": pointer_uri,
            "act_id": act_id,
            "from_hub": hub_lct_id,
            "deferred": defer,
            "deferred_by_law": denied_open.is_some(),
        }),
    )?;

    // Seal an ACK the hub opens to mark the notice delivered.
    let ack = crate::hub::NotificationAck { act_id, received_at: Utc::now() };
    let ack_sealed = channel.seal_ack(&keypair, &ack)?;

    if defer {
        return Ok(json!({
            "accepted": true,
            "deferred": true,
            // Present iff law denied the body-returning open — the caller sees
            // WHY it got a deferral it didn't ask for (honest, not silent).
            "deferredByLaw": denied_open.is_some(),
            "kind": kind,
            "pointerUri": pointer_uri,
            "queued": s.inbox_store.len().unwrap_or(0),
            "ackSealed": ack_sealed,
            "witnessEntryHash": entry.hash,
        }));
    }

    Ok(json!({
        "opened": true,
        "kind": kind,
        "pointerUri": pointer_uri,
        "body": body,
        "ackSealed": ack_sealed,
        "witnessEntryHash": entry.hash,
    }))
}

/// `hestia_inbox` — drain the durable inbound mailbox (consume-once).
///
/// The consumer side of accept-and-defer: opens each parked notice with the
/// member identity keypair and returns the bodies, oldest first. A body that
/// no longer opens (e.g. identity rotated since it was parked) is returned in
/// its sealed form with an `error` — surfaced, never silently dropped.
///
/// **Law-gated as `credential_access`** (spec §7.8.2: deliver only to the
/// authenticated LCT — the drain RELEASES bodies sealed to the member
/// identity, so it is a secret-release surface, not a plain read). Under the
/// ratified law this denies the unattended roles (mesh-worker,
/// autonomous-timer) without any new rule. The gate runs BEFORE the drain
/// (O: preflight dominates the consume — a denied caller must not consume the
/// queue), and a deny leaves the mailbox bit-identical.
async fn tool_inbox(state: &SharedState, args: &Value) -> ToolResult {
    let session_id_arg = optional_string(args, "session_id");
    let mut s = state.lock().await;
    let who = resolve_caller(&s, session_id_arg.as_deref());
    if let Some(denied) = gate_direct_tool(&mut s, &who, "hestia_inbox", "credential_access", "inbox")
    {
        return Ok(denied);
    }

    let notices = s
        .inbox_store
        .drain()
        .map_err(|e| anyhow::anyhow!("draining inbox: {e}"))?;
    if notices.is_empty() {
        return Ok(json!({ "total": 0, "notices": [] }));
    }

    // Same identity-loading path as `tool_notify`.
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

    let opened: Vec<Value> = notices
        .into_iter()
        .map(|n| {
            let base = json!({
                "kind": n.kind,
                "pointerUri": n.pointer_uri,
                "fromHub": n.from_hub,
                "queuedAt": n.queued_at,
            });
            let mut v = base;
            match crate::hub::HubChannel::new(n.from_hub, n.pair_id, &n.hub_pubkey_hex)
                .and_then(|ch| ch.open_notification(&keypair, &n.sealed))
            {
                Ok(body) => v["body"] = body,
                Err(e) => {
                    v["sealed"] = json!(n.sealed);
                    v["error"] = json!(format!("could not open: {e}"));
                }
            }
            v
        })
        .collect();

    Ok(json!({ "total": opened.len(), "notices": opened }))
}

/// `hestia_pair_inbox` — the pull-side sibling of `hestia_inbox` for the PAIRED
/// channel (dp's authentication-controller model). Secrets ride confirmed pairs
/// as `pair_message`s (not the pushed SealedNotice mailbox), so they must be
/// PULLED (`GET /pairs/:id/messages`) and opened with the pair keys. Same §7.8.2
/// credential_access gate as `hestia_inbox`: an unattended caller is DENIED and
/// the secret stays on the hub for an ATTENDED drain (nothing is released, the
/// cursor doesn't advance). An attended caller gets the opened `SecretEnvelope`s
/// and the per-pair cursor advances so each secret is delivered once.
async fn tool_pair_inbox(state: &SharedState, args: &Value) -> ToolResult {
    let session_id_arg = optional_string(args, "session_id");
    let mut s = state.lock().await;
    let who = resolve_caller(&s, session_id_arg.as_deref());
    if let Some(denied) =
        gate_direct_tool(&mut s, &who, "hestia_pair_inbox", "credential_access", "pair_inbox")
    {
        return Ok(denied); // §7.8.2: deferredByLaw — secret stays for an attended drain
    }

    let mut pairings = crate::pairing::PairingStore::load(&s.vault)?;
    let hub_store = crate::hub::HubStore::load(&s.vault)?;
    let Some(conn) = hub_store.connections.first().cloned() else {
        return Ok(json!({ "total": 0, "secrets": [], "note": "no hub connection" }));
    };

    // Member identity keypair — same load path as tool_inbox.
    let secret_hex = s
        .vault
        .get("ai_identity_secret")
        .map(|e| e.secret.clone())
        .ok_or_else(|| anyhow::anyhow!("no member identity — run `hestia init --ai`"))?;
    let arr: [u8; 32] = hex::decode(&secret_hex)
        .ok()
        .and_then(|b| b.try_into().ok())
        .ok_or_else(|| anyhow::anyhow!("identity secret must be 32-byte hex"))?;
    let keypair = web4_core::crypto::KeyPair::from_secret_bytes(&arr);
    let client = crate::hub::HubClient::new();

    let snapshot: Vec<crate::pairing::Pairing> = pairings.pairings.values().cloned().collect();
    let mut opened: Vec<Value> = Vec::new();
    let mut advanced = false;

    for p in &snapshot {
        // Need the (active) pair detail for the peer ephemeral; skip inactive pairs.
        let detail = match client.get_pair(&conn.rest_endpoint, conn.hub_lct_id, p.pair_id).await {
            Ok(d) if d.is_active() => d,
            _ => continue,
        };
        let peer_lct = match p.peer_lct_pubkey() {
            Ok(k) => k,
            Err(_) => continue,
        };
        let since = pairings.cursor(&p.pair_id);
        let msgs = match client
            .get_pair_messages(&conn.rest_endpoint, conn.hub_lct_id, p.pair_id, since)
            .await
        {
            Ok(m) => m,
            Err(_) => continue,
        };
        for m in &msgs {
            if m.from == conn.our_lct_id {
                // Our own sent message echoed back — advance past it, don't open.
                pairings.set_cursor(p.pair_id, m.seq);
                advanced = true;
                continue;
            }
            let entry = match crate::pairing::open_over_pair(p, &detail, &keypair, &peer_lct, &m.payload)
                .and_then(|plain| crate::pairing::SecretEnvelope::from_opened_bytes(&plain))
            {
                Ok(env) => json!({
                    "pairId": p.pair_id, "seq": m.seq, "from": m.from,
                    "actId": env.act_id, "secretHex": env.secret_hex,
                }),
                Err(e) => json!({
                    "pairId": p.pair_id, "seq": m.seq, "from": m.from,
                    "error": format!("could not open as a secret: {e}"),
                }),
            };
            opened.push(entry);
            pairings.set_cursor(p.pair_id, m.seq);
            advanced = true;
        }
    }

    if advanced {
        pairings.save(&mut s.vault)?;
    }
    Ok(json!({ "total": opened.len(), "secrets": opened }))
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
    // NOTE deliberately NO `hestia://vault/{name}` resource: it served the raw
    // secret with no policy, scope, allowed_consumers, or witness — a sibling
    // path that made the hestia_vault_get gate decorative (GPT 3rd-pass
    // HST-001). Credential reads go through hestia_vault_get, full stop.
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

    fn deny_overlay_for(categories: &[&str]) -> crate::policy::PolicyEngine {
        crate::policy::PolicyEngine::new(crate::policy::PolicyConfig {
            default_policy: crate::policy::PolicyDecision::Allow,
            enforce: true,
            rules: vec![crate::policy::PolicyRule {
                id: "unattended-deny".into(),
                name: "unattended deny".into(),
                priority: 0,
                decision: crate::policy::PolicyDecision::Deny,
                reason: Some("unattended".into()),
                r#match: crate::policy::PolicyMatch {
                    categories: Some(categories.iter().map(|c| c.to_string()).collect()),
                    ..Default::default()
                },
            }],
        })
    }

    /// Regression pin for GPT 3rd-pass HST-001: the `hestia://vault/{name}`
    /// resource path is GONE. It used to hand back the raw secret past every
    /// gate `hestia_vault_get` enforces — a sibling seam that made the ratified
    /// credential_access law decorative.
    #[tokio::test]
    async fn vault_uri_resource_no_longer_serves_secrets() {
        let (_dir, state) = test_state().await;
        {
            let mut s = state.lock().await;
            s.vault.upsert(crate::vault::VaultEntry::new("github-pat", "s3cret")).unwrap();
        }
        let res = read_resource_body(&state, "hestia://vault/github-pat").await;
        let err = res.expect_err("vault URI must no longer resolve");
        assert!(err.contains("unknown resource"), "got: {err}");
        assert!(!err.contains("s3cret"));
    }

    /// Regression pin for GPT 3rd-pass HST-002: credential WRITES hit the same
    /// daemon-side law as reads. An overlaid unattended role is refused before
    /// the vault is touched, the deny is witnessed with WHO, and nothing lands
    /// in the vault. An attended (member) session still writes.
    #[tokio::test]
    async fn vault_set_denied_for_overlaid_role_and_witnessed() {
        let (_dir, state) = test_state().await;
        {
            let mut s = state.lock().await;
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                deny_overlay_for(&["credential_access"]),
            );
        }
        let mw = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:mesh-worker"
        })).await.unwrap();
        let denied = tool_vault_set(&state, &json!({
            "name":"github-pat","value":"evil","session_id": mw["sessionId"]
        })).await.unwrap();
        assert_eq!(denied["_hestia_error"]["code"], "hestia.policy_denied");
        {
            let s = state.lock().await;
            assert!(s.vault.get("github-pat").is_none(), "denied write must not persist");
            let pd = s.recent_chain(10).into_iter()
                .find(|e| e.event_type == "policy_decision")
                .expect("vault_set deny must be witnessed");
            assert_eq!(pd.event_data["tool_name"], "hestia_vault_set");
            assert_eq!(pd.event_data["role_lct"], "role:constellation:mesh-worker");
            assert_eq!(pd.event_data["enforced"], true);
        }
        // member (attended) → the write goes through, attributed on the chain.
        let m = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:member"
        })).await.unwrap();
        let ok = tool_vault_set(&state, &json!({
            "name":"github-pat","value":"real","session_id": m["sessionId"]
        })).await.unwrap();
        assert_eq!(ok["stored"], true);
        let s = state.lock().await;
        assert!(s.vault.get("github-pat").is_some());
        let vs = s.recent_chain(10).into_iter()
            .find(|e| e.event_type == "vault_set")
            .expect("vault_set must be audited");
        assert_eq!(vs.event_data["role_lct"], "role:constellation:member");
    }

    /// Regression pin for GPT 3rd-pass HST-003: `request_witness` is a gated,
    /// attributed act — reserved daemon event types can't be forged, an
    /// overlaid role can be denied the append entirely, and an allowed append
    /// carries the requesting WHO next to (never instead of) the caller data.
    #[tokio::test]
    async fn request_witness_gated_attributed_and_reserved() {
        let (_dir, state) = test_state().await;
        // Forging a daemon-authored event type is refused for anyone.
        let forged = tool_request_witness(&state, &json!({
            "event_type":"policy_decision","event_data":{"decision":"allow"}
        })).await.unwrap();
        assert_eq!(forged["_hestia_error"]["code"], "hestia.witness_reserved_event");

        // An overlaid unattended role is denied the append by law.
        {
            let mut s = state.lock().await;
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                deny_overlay_for(&["witness_append"]),
            );
        }
        let mw = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:mesh-worker"
        })).await.unwrap();
        let denied = tool_request_witness(&state, &json!({
            "event_type":"custom.note","event_data":{"k":"v"},"session_id": mw["sessionId"]
        })).await.unwrap();
        assert_eq!(denied["_hestia_error"]["code"], "hestia.policy_denied");

        // A member append lands, wrapped with the requesting WHO.
        let m = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:member"
        })).await.unwrap();
        let ok = tool_request_witness(&state, &json!({
            "event_type":"custom.note","event_data":{"k":"v"},"session_id": m["sessionId"]
        })).await.unwrap();
        assert!(ok["witnessEntryHash"].is_string());
        let s = state.lock().await;
        let e = s.recent_chain(10).into_iter()
            .find(|e| e.event_type == "custom.note")
            .expect("allowed append must land on the chain");
        assert_eq!(e.event_data["data"]["k"], "v");
        assert_eq!(e.event_data["requested_by"]["role_lct"], "role:constellation:member");
        assert_eq!(e.event_data["requested_by"]["plugin_id"], "claude-code");
    }

    /// A reversal is a JUDGMENT signal: it witnesses the subject + reporter, feeds
    /// the SUBJECT's JUDGMENT-axis trust negatively — and does NOT touch the
    /// execution-axis trust (CBP condition 2: the two axes have separate
    /// dynamics; the execution stream must not be able to refill a judgment dip).
    /// The event type is reserved (a plugin can't forge one via request_witness).
    #[tokio::test]
    async fn reversal_witnesses_subject_and_reporter_and_feeds_judgment_axis() {
        let (_dir, state) = test_state().await;
        // An interactive-dev session reports dp reverted a mesh-worker's merge.
        let dev = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:interactive-dev"
        })).await.unwrap();
        let mw = "role:constellation:mesh-worker";
        // Baselines for the subject: judgment axis AND execution axis.
        let (judgment_before, exec_before) = {
            let s = state.lock().await;
            (
                s.judgment_for_role("worker-agent", mw).talent(),
                s.trust_for_role("worker-agent", mw).talent(),
            )
        };
        let out = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent",
            "subject_role": mw,
            "kind":"override",
            "reason":"dp gate: reverted the merged PR",
            "ref":"PR#123",
            "magnitude":0.5,
            "session_id": dev["sessionId"],
        })).await.unwrap();
        assert!(out.get("_hestia_error").is_none(), "reversal should succeed: {out:?}");

        let s = state.lock().await;
        let ev = s.recent_chain(5).into_iter()
            .find(|e| e.event_type == "reversal").expect("reversal witnessed");
        let d = &ev.event_data;
        assert_eq!(d["subject_plugin_id"], "worker-agent");
        assert_eq!(d["subject_role"], mw);
        assert_eq!(d["kind"], "override");
        // reporter is captured for accountability, distinct from subject
        assert_eq!(d["reported_by"]["role_lct"], "role:constellation:interactive-dev");
        // the SUBJECT's judgment-axis trust dropped (negative judgment)...
        let judgment_after = s.judgment_for_role("worker-agent", mw).talent();
        assert!(judgment_after < judgment_before,
            "judgment trust must drop: {judgment_after} !< {judgment_before}");
        // ...and the execution-axis trust did NOT move (separate timescales).
        let exec_after = s.trust_for_role("worker-agent", mw).talent();
        assert!((exec_after - exec_before).abs() < 1e-12,
            "execution trust must be untouched by a judgment event");
        // an unknown reversal kind is rejected
        drop(s);
        let bad = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent","kind":"vibes"
        })).await.unwrap();
        assert_eq!(bad["_hestia_error"]["code"], "hestia.reversal_unknown_kind");
        // reversal is reserved from request_witness forgery
        let forge = tool_request_witness(&state, &json!({
            "event_type":"reversal","event_data":{"subject_plugin_id":"x"}
        })).await.unwrap();
        assert_eq!(forge["_hestia_error"]["code"], "hestia.witness_reserved_event");
    }

    /// Judge-disjoint split (CBP condition 1): peer review verdicts are the
    /// HELD-OUT calibration target — `review_reject` is not a reversal kind and
    /// must never feed trust. Pinned so it can't quietly return.
    #[tokio::test]
    async fn reversal_rejects_review_reject_kind_judge_disjoint_split() {
        let (_dir, state) = test_state().await;
        let rev = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:reviewer"
        })).await.unwrap();
        let out = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent",
            "kind":"review_reject",
            "session_id": rev["sessionId"],
        })).await.unwrap();
        assert_eq!(out["_hestia_error"]["code"], "hestia.reversal_unknown_kind");
        // and no judgment trust moved, no reversal was witnessed
        let s = state.lock().await;
        assert!(s.recent_chain(5).into_iter().all(|e| e.event_type != "reversal"));
    }

    /// Cross-actor trust injection is guarded: an unattributable reporter (no
    /// live session at all) is rejected, and an unknown subject_role errors
    /// instead of silently falling back to the default grain.
    #[tokio::test]
    async fn reversal_rejects_unattributed_reporter_and_unknown_role() {
        let (_dir, state) = test_state().await;
        // No session connected → resolve_caller yields no session_uuid.
        let out = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent","kind":"override"
        })).await.unwrap();
        assert_eq!(out["_hestia_error"]["code"], "hestia.reversal_unattributed_reporter");

        let dev = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:interactive-dev"
        })).await.unwrap();
        // A typo'd role must not land the penalty on the default grain.
        let bad_role = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent",
            "subject_role":"role:constellation:mesh_worker",
            "kind":"override",
            "session_id": dev["sessionId"],
        })).await.unwrap();
        assert_eq!(bad_role["_hestia_error"]["code"], "hestia.reversal_unknown_role");
        let s = state.lock().await;
        assert!(s.recent_chain(5).into_iter().all(|e| e.event_type != "reversal"));
    }

    /// The reversal surface hits the same law as the other direct-call tools:
    /// a role overlay can deny `reversal_report`, the enforced deny is
    /// witnessed with the REPORTER's WHO, and no trust moves.
    #[tokio::test]
    async fn reversal_denied_by_role_overlay_and_witnessed() {
        let (_dir, state) = test_state().await;
        {
            let mut s = state.lock().await;
            let rule = crate::policy::PolicyRule {
                id: "mw-no-reversal".into(),
                name: "mesh-workers may not report reversals".into(),
                priority: 0,
                decision: crate::policy::PolicyDecision::Deny,
                reason: Some("unattended".into()),
                r#match: crate::policy::PolicyMatch {
                    categories: Some(vec!["reversal_report".into()]),
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
        let mw = tool_connect(&state, &json!({
            "plugin_id":"claude-code","host_agent":"t","role":"role:constellation:mesh-worker"
        })).await.unwrap();
        let denied = tool_record_reversal(&state, &json!({
            "subject_plugin_id":"worker-agent","kind":"override",
            "session_id": mw["sessionId"],
        })).await.unwrap();
        assert_eq!(denied["_hestia_error"]["code"], "hestia.policy_denied");
        let s = state.lock().await;
        // the refusal is witnessed with the reporter's WHO; no reversal event
        let pd = s.recent_chain(10).into_iter()
            .find(|e| e.event_type == "policy_decision")
            .expect("reversal deny must be witnessed");
        assert_eq!(pd.event_data["tool_name"], "hestia_record_reversal");
        assert_eq!(pd.event_data["role_lct"], "role:constellation:mesh-worker");
        assert!(s.recent_chain(10).into_iter().all(|e| e.event_type != "reversal"));
        assert_eq!(
            s.judgment_for_role("worker-agent", "role:constellation:mesh-worker").talent(),
            EntityTrust::new("x".to_string()).talent(),
            "no judgment trust may move on a denied report"
        );
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

    /// Deny-as-redirect on the wire: an enforced deny carries the composed
    /// `guidance` alongside the machine fields, and an allow carries null —
    /// the client contract (GATE_PROFILE §1) is "surface if present, fall
    /// back to reason".
    #[tokio::test]
    async fn query_policy_deny_carries_guidance_allow_does_not() {
        let (_dir, state) = test_state().await;
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

        let begin = tool_begin_action(
            &state,
            &json!({
                "tool_name": "Bash",
                "target": "rm -rf /home/user/data",
                "parameters": {"command": "rm -rf /home/user/data"},
                "session_id": sid,
            }),
        )
        .await
        .unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        let q = tool_query_policy(&state, &json!({"action_id": aid})).await.unwrap();
        assert_eq!(q["decision"], "deny", "precondition: denied");
        let g = q["guidance"].as_str().expect("enforced deny carries guidance");
        assert!(g.contains("boundary, not a failure"));
        assert!(
            g.contains(q["reason"].as_str().unwrap()),
            "guidance embeds the reason so the fallback loses no information"
        );

        let begin = tool_begin_action(
            &state,
            &json!({"tool_name": "Read", "target": "notes.md", "session_id": sid}),
        )
        .await
        .unwrap();
        let aid = begin["actionId"].as_str().unwrap().to_string();
        let q = tool_query_policy(&state, &json!({"action_id": aid})).await.unwrap();
        assert_eq!(q["decision"], "allow", "precondition: allowed");
        assert!(q["guidance"].is_null(), "allow must not carry steering text");
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

#[cfg(test)]
mod inbox_tests {
    use super::*;
    use crate::vault::{Vault, VaultEntry};
    use tempfile::TempDir;
    use web4_core::crypto::{KeyPair, PublicKey};
    use web4_core::pair_channel;

    /// A state whose vault holds a member identity (as `hestia init --ai`
    /// leaves it), plus that identity's keypair so tests can play the hub side.
    fn seeded_home() -> (TempDir, KeyPair) {
        let dir = TempDir::new().unwrap();
        let member_kp = KeyPair::generate();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        vault
            .add(VaultEntry::new("ai_identity_secret", hex::encode(member_kp.secret_key_bytes())))
            .unwrap();
        (dir, member_kp)
    }

    fn open_state(dir: &TempDir) -> SharedState {
        let vault = Vault::open(dir.path().join("v.enc"), "p".into()).unwrap();
        crate::server::build_state(vault, dir.path(), "p").unwrap()
    }

    /// The hub side of the notify wire: seal a body to the member's pinned
    /// pubkey (exactly what `queue_sealed_notice` does hub-side).
    fn hub_seal(hub_kp: &KeyPair, member_kp: &KeyPair, pair_id: Uuid, body: &Value) -> String {
        let member_pub = PublicKey::from_bytes(&member_kp.public_key_bytes()).unwrap();
        pair_channel::seal(hub_kp, &member_pub, pair_id, &serde_json::to_vec(body).unwrap())
            .unwrap()
            .to_base64()
    }

    /// Accept-and-defer end to end: defer parks the still-sealed notice
    /// durably and ACKs without the body; the parked notice survives a daemon
    /// restart; `hestia_inbox` opens and consumes it exactly once.
    #[tokio::test]
    async fn notify_defer_survives_restart_and_inbox_drains_once() {
        let (dir, member_kp) = seeded_home();
        let hub_kp = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let hub_lct_id = Uuid::new_v4();
        let act_id = Uuid::new_v4();
        let body = json!({"act_id": act_id, "task": "review the fleet cartridge"});
        let sealed = hub_seal(&hub_kp, &member_kp, pair_id, &body);

        // --- defer: park before ACK, no body in the response ---
        let state = open_state(&dir);
        let resp = tool_notify(
            &state,
            &json!({
                "pair_id": pair_id, "hub_lct_id": hub_lct_id,
                "hub_pubkey_hex": hex::encode(hub_kp.public_key_bytes()),
                "sealed": sealed, "kind": "notify:task",
                "pointer_uri": "hub://act/1", "defer": true
            }),
        )
        .await
        .unwrap();
        assert_eq!(resp["accepted"], json!(true));
        assert_eq!(resp["deferred"], json!(true));
        assert_eq!(resp["queued"], json!(1));
        assert!(resp.get("body").is_none(), "deferred notify must not return the body");

        // The ACK still opens hub-side (the hub can mark it delivered).
        let member_pub = PublicKey::from_bytes(&member_kp.public_key_bytes()).unwrap();
        let ack_sealed = pair_channel::Sealed::from_base64(resp["ackSealed"].as_str().unwrap()).unwrap();
        let ack_plain = pair_channel::open(&hub_kp, &member_pub, pair_id, &ack_sealed).unwrap();
        let ack: Value = serde_json::from_slice(&ack_plain).unwrap();
        assert_eq!(ack["act_id"], json!(act_id));

        // Receipt was witnessed with the deferred marker.
        {
            let s = state.lock().await;
            let rec = s.recent_chain(10).into_iter()
                .find(|e| e.event_type == "notify.received")
                .expect("receipt must be witnessed");
            assert_eq!(rec.event_data["deferred"], json!(true));
        }
        drop(state); // daemon goes down with the notice still parked

        // --- restart: the parked notice survived, drain opens + consumes it ---
        let state2 = open_state(&dir);
        let drained = tool_inbox(&state2, &json!({})).await.unwrap();
        assert_eq!(drained["total"], json!(1));
        let n = &drained["notices"][0];
        assert_eq!(n["kind"], json!("notify:task"));
        assert_eq!(n["pointerUri"], json!("hub://act/1"));
        assert_eq!(n["body"]["task"], json!("review the fleet cartridge"));
        assert_eq!(n["body"]["act_id"], json!(act_id));

        // Consume-once: a second drain is empty.
        let again = tool_inbox(&state2, &json!({})).await.unwrap();
        assert_eq!(again["total"], json!(0));

        // And the inbox file on disk is encrypted (not plaintext SQLite).
        let hdr_path = dir.path().join("inbox.db");
        let hdr = std::fs::read(&hdr_path).unwrap();
        assert_ne!(&hdr[..16], b"SQLite format 3\0", "inbox must be encrypted at rest");
    }

    /// Without `defer`, the wire is unchanged: body returned, inbox untouched.
    #[tokio::test]
    async fn notify_without_defer_is_backward_compatible() {
        let (dir, member_kp) = seeded_home();
        let hub_kp = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let sealed = hub_seal(&hub_kp, &member_kp, pair_id, &json!({"act_id": Uuid::new_v4()}));

        let state = open_state(&dir);
        let resp = tool_notify(
            &state,
            &json!({
                "pair_id": pair_id,
                "hub_pubkey_hex": hex::encode(hub_kp.public_key_bytes()),
                "sealed": sealed
            }),
        )
        .await
        .unwrap();
        assert_eq!(resp["opened"], json!(true));
        assert!(resp.get("body").is_some(), "immediate notify still returns the body");

        let s = state.lock().await;
        assert!(s.inbox_store.is_empty().unwrap(), "non-deferred notify must not queue");
    }

    /// A law-denied body-returning notify AUTO-DEFERS: fail closed on the
    /// release without losing the work item — the still-sealed notice parks,
    /// the hub gets its ACK, and the caller is told WHY (`deferredByLaw`).
    #[tokio::test]
    async fn notify_denied_open_auto_defers_instead_of_losing_the_notice() {
        let (dir, member_kp) = seeded_home();
        let hub_kp = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let sealed = hub_seal(&hub_kp, &member_kp, pair_id, &json!({"act_id": Uuid::new_v4()}));

        let state = open_state(&dir);
        let sid = Uuid::new_v4();
        {
            let mut s = state.lock().await;
            // The ratified-law shape: unattended role's overlay denies
            // credential_access (see server::handler::tests for the engine).
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                crate::server::handler::tests::deny_credential_access_engine(),
            );
            s.sessions.insert(
                sid,
                crate::server::state::Session {
                    session_id: sid,
                    plugin_id: "watcher".into(),
                    plugin_version: None,
                    host_agent: "test".into(),
                    host_agent_version: None,
                    assigned_role: "citizen".into(),
                    constellation_role: "role:constellation:mesh-worker".into(),
                    soft_lct: "lct:test".into(),
                    connected_at: chrono::Utc::now(),
                },
            );
        }

        let resp = tool_notify(
            &state,
            &json!({
                "pair_id": pair_id,
                "hub_pubkey_hex": hex::encode(hub_kp.public_key_bytes()),
                "sealed": sealed,
                "session_id": sid.to_string()
                // no "defer" — the caller ASKED for the body
            }),
        )
        .await
        .unwrap();

        assert_eq!(resp["accepted"], json!(true));
        assert_eq!(resp["deferred"], json!(true), "deny must downgrade to defer: {resp}");
        assert_eq!(resp["deferredByLaw"], json!(true), "the caller is told why");
        assert!(resp.get("body").is_none(), "denied open must NOT release the body");
        assert!(resp.get("ackSealed").is_some(), "the hub still gets its delivery ACK");

        let s = state.lock().await;
        assert_eq!(s.inbox_store.len().unwrap(), 1, "the notice parked, not lost");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::{PolicyConfig, PolicyDecision, PolicyEngine, PolicyMatch, PolicyRule};
    use crate::vault::Vault;
    use chrono::Utc;
    use tempfile::TempDir;

    fn make_shared_state() -> (TempDir, SharedState) {
        let dir = TempDir::new().unwrap();
        let mut vault = Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        // The drain opens bodies with the member identity (as `hestia init --ai`
        // leaves it) — seed one so the ALLOWED path exercises the full open.
        vault
            .add(crate::vault::VaultEntry::new(
                "ai_identity_secret",
                hex::encode(web4_core::crypto::KeyPair::generate().secret_key_bytes()),
            ))
            .unwrap();
        let state = super::super::state::ServerState::open(vault, dir.path(), "p").unwrap();
        (dir, std::sync::Arc::new(tokio::sync::Mutex::new(state)))
    }

    pub(super) fn deny_credential_access_engine() -> PolicyEngine {
        PolicyEngine::new(PolicyConfig {
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![PolicyRule {
                id: "test-deny-cred".into(),
                name: "deny credential_access (ratified-law shape)".into(),
                priority: 0,
                decision: PolicyDecision::Deny,
                reason: Some("unattended role may not release secrets".into()),
                r#match: PolicyMatch {
                    tools: None,
                    categories: Some(vec!["credential_access".into()]),
                    target_patterns: None,
                    target_patterns_are_regex: false,
                    command_patterns: None,
                    command_patterns_are_regex: false,
                    command_must_not_contain: None,
                    time_window: None,
                    rate_limit: None,
                },
            }],
        })
    }

    fn add_session(s: &mut super::super::state::ServerState, role: &str) -> Uuid {
        let sid = Uuid::new_v4();
        s.sessions.insert(
            sid,
            super::super::state::Session {
                session_id: sid,
                plugin_id: "test-plugin".into(),
                plugin_version: None,
                host_agent: "test".into(),
                host_agent_version: None,
                assigned_role: "citizen".into(),
                constellation_role: role.into(),
                soft_lct: "lct:test".into(),
                connected_at: Utc::now(),
            },
        );
        sid
    }

    #[tokio::test]
    async fn connect_mints_a_member_lct_on_first_sight_not_for_synthetic() {
        let (_dir, shared) = make_shared_state();
        // A real member connect → gets a custodial member LCT.
        let r = tool_connect(&shared, &json!({
            "plugin_id": "claude-code", "host_agent": "cc"
        })).await.unwrap();
        assert!(r.get("sessionId").is_some());
        {
            let s = shared.lock().await;
            assert_eq!(s.member_registry.len(), 1, "first connect minted the member");
            let lct = s.member_registry.get("claude-code").unwrap();
            assert!(lct.verify_binding());
            assert!(lct.legacy_alias.as_ref().unwrap().verify(), "carries its verifiable label alias");
        }
        // Reconnect → idempotent (still one member, no re-mint).
        tool_connect(&shared, &json!({"plugin_id": "claude-code", "host_agent": "cc"}))
            .await.unwrap();
        assert_eq!(shared.lock().await.member_registry.len(), 1);
        // A synthetic connect → NO member LCT (fail-closed domain).
        tool_connect(&shared, &json!({
            "plugin_id": "fuzz-runner", "host_agent": "cc", "synthetic": true
        })).await.unwrap();
        assert_eq!(shared.lock().await.member_registry.len(), 1, "synthetic gets no presence");
    }

    /// Spec §7.8.2 "deliver only to that authenticated LCT" + RWOA O-clause:
    /// a law-denied caller must NOT drain — and the deny leaves the mailbox
    /// bit-identical (the gate dominates the consume).
    #[tokio::test]
    async fn inbox_drain_is_law_gated_and_deny_leaves_queue_intact() {
        let (_dir, shared) = make_shared_state();
        let (unattended, attended) = {
            let mut s = shared.lock().await;
            s.inbox_store
                .enqueue(Uuid::new_v4(), Uuid::nil(), "ab", "sealed-x", "notify:k", None)
                .unwrap();
            // The ratified-law shape: the unattended role's overlay denies
            // credential_access; the attended role has no overlay.
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                deny_credential_access_engine(),
            );
            (
                add_session(&mut s, "role:constellation:mesh-worker"),
                add_session(&mut s, "role:constellation:member"),
            )
        };

        // Unattended: denied, and the queue is untouched.
        let denied = tool_inbox(&shared, &json!({ "session_id": unattended.to_string() }))
            .await
            .unwrap();
        assert!(
            denied.get("_hestia_error").is_some(),
            "mesh-worker drain must be denied by law: {denied}"
        );
        assert_eq!(shared.lock().await.inbox_store.len().unwrap(), 1, "deny must not consume");

        // Attended: drains (consume-once).
        let ok = tool_inbox(&shared, &json!({ "session_id": attended.to_string() }))
            .await
            .unwrap();
        assert_eq!(ok["total"], 1, "member drain succeeds: {ok}");
        assert_eq!(shared.lock().await.inbox_store.len().unwrap(), 0);
    }

    /// §7.8.2 also gates the PAIRED-channel secret drain: an unattended caller is
    /// denied (deferredByLaw), so the secret stays on the hub for an attended
    /// drain. The attended path with no hub connection is a graceful empty result.
    #[tokio::test]
    async fn pair_inbox_is_law_gated() {
        let (_dir, shared) = make_shared_state();
        let (unattended, attended) = {
            let mut s = shared.lock().await;
            s.role_policy_engines.insert(
                "role:constellation:mesh-worker".into(),
                deny_credential_access_engine(),
            );
            (
                add_session(&mut s, "role:constellation:mesh-worker"),
                add_session(&mut s, "role:constellation:member"),
            )
        };
        let denied = tool_pair_inbox(&shared, &json!({ "session_id": unattended.to_string() }))
            .await
            .unwrap();
        assert!(
            denied.get("_hestia_error").is_some(),
            "unattended pair-secret drain must be denied by law: {denied}"
        );
        // Attended, no hub connection → graceful empty (the gate passed).
        let ok = tool_pair_inbox(&shared, &json!({ "session_id": attended.to_string() }))
            .await
            .unwrap();
        assert_eq!(ok["total"], 0, "attended drain with no connection is empty, not an error: {ok}");
    }
}
