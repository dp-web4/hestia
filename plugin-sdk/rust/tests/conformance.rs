//! Conformance harness — Rust.
//!
//! Loads the canonical scenarios from
//! `web4-standard/testing/conformance/presence-protocol-conformance.json`
//! and exercises them against a live Hestia daemon.
//!
//! Requires a running Hestia daemon at $HESTIA_ENDPOINT (default
//! `http://127.0.0.1:7711/mcp`). Test is skipped (treated as success)
//! if the daemon isn't reachable unless `RUN_CONFORMANCE=1` is set.
//!
//! Run from `plugin-sdk/rust/`:
//!   `cargo test --test conformance -- --nocapture`

use std::collections::HashMap;
use std::env;
use std::net::TcpStream;
use std::path::PathBuf;
use std::time::Duration;

use chrono::{DateTime, Utc};
use hestia_plugin_sdk::{
    create_hestia_client, HestiaClientConfig, HistoryFilter, Outcome, R6Action, ToolCallSpec,
    VaultGetOptions, VaultSetOptions,
};
use serde_json::{json, Value};
use url::Url;

fn endpoint() -> String {
    env::var("HESTIA_ENDPOINT").unwrap_or_else(|_| "http://127.0.0.1:7711/mcp".to_string())
}

fn daemon_reachable() -> bool {
    let url = match Url::parse(&endpoint()) {
        Ok(u) => u,
        Err(_) => return false,
    };
    let host = url.host_str().unwrap_or("127.0.0.1");
    let port = url
        .port_or_known_default()
        .unwrap_or(if url.scheme() == "https" { 443 } else { 80 });
    TcpStream::connect_timeout(
        &format!("{host}:{port}").parse().unwrap(),
        Duration::from_secs(2),
    )
    .is_ok()
}

fn vectors_path() -> PathBuf {
    if let Ok(p) = env::var("WEB4_STANDARD_CONFORMANCE") {
        return PathBuf::from(p);
    }
    // this test file lives at hestia/plugin-sdk/rust/tests/conformance/conformance.rs
    // ai-agents is 5 levels up from CARGO_MANIFEST_DIR (which is plugin-sdk/rust)
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .map(|ai_agents| {
            ai_agents
                .join("web4")
                .join("web4-standard")
                .join("testing")
                .join("conformance")
                .join("presence-protocol-conformance.json")
        })
        .unwrap_or_else(|| PathBuf::from("presence-protocol-conformance.json"))
}

fn resolve_path(obj: &Value, path: &str) -> Option<Value> {
    let mut current = obj.clone();
    let normalized = path.replace('[', ".").replace(']', "");
    for part in normalized.split('.').filter(|p| !p.is_empty()) {
        if part == "*" {
            return Some(current);
        }
        if let Ok(idx) = part.parse::<usize>() {
            current = current.get(idx)?.clone();
        } else {
            current = current.get(part)?.clone();
        }
    }
    Some(current)
}

fn interpolate(value: &Value, captures: &HashMap<String, HashMap<String, Value>>) -> Value {
    match value {
        Value::String(s) => {
            // Match {{P0-XXX.fieldName}}
            if let Some(rest) = s.strip_prefix("{{").and_then(|s| s.strip_suffix("}}")) {
                if let Some((scenario_id, field)) = rest.split_once('.') {
                    if let Some(scenario_caps) = captures.get(scenario_id) {
                        if let Some(v) = scenario_caps.get(field) {
                            return v.clone();
                        }
                    }
                }
            }
            value.clone()
        }
        Value::Array(arr) => Value::Array(arr.iter().map(|v| interpolate(v, captures)).collect()),
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                out.insert(k.clone(), interpolate(v, captures));
            }
            Value::Object(out)
        }
        _ => value.clone(),
    }
}

fn check_field(value: &Value, check: &Value, scenario_id: &str) {
    let path = check.get("path").and_then(Value::as_str).unwrap_or("?");
    let ctx = format!("[{scenario_id}] field {path:?}");
    if let Some(expected) = check.get("equals") {
        assert_eq!(value, expected, "{ctx} expected {expected}, got {value}");
    }
    if let Some(pattern) = check.get("matchesPattern").and_then(Value::as_str) {
        let s = value.as_str().unwrap_or("");
        let re = regex::Regex::new(pattern).expect("valid regex");
        assert!(re.is_match(s), "{ctx} doesn't match /{pattern}/ (got {s:?})");
    }
    if let Some(prefix) = check.get("startsWith").and_then(Value::as_str) {
        let s = value.as_str().unwrap_or("");
        assert!(s.starts_with(prefix), "{ctx} doesn't start with {prefix}");
    }
    if check.get("isInteger").and_then(Value::as_bool).unwrap_or(false) {
        assert!(
            value.is_i64() || value.is_u64(),
            "{ctx} not integer (got {value})"
        );
    }
    if check.get("isNumber").and_then(Value::as_bool).unwrap_or(false) {
        assert!(value.is_number(), "{ctx} not number");
    }
    if check.get("isBoolean").and_then(Value::as_bool).unwrap_or(false) {
        assert!(value.is_boolean(), "{ctx} not bool");
    }
    if check.get("isString").and_then(Value::as_bool).unwrap_or(false) {
        assert!(value.is_string(), "{ctx} not string");
    }
    if check.get("isNonEmptyString").and_then(Value::as_bool).unwrap_or(false) {
        assert!(
            value.as_str().map(|s| !s.is_empty()).unwrap_or(false),
            "{ctx} not non-empty string"
        );
    }
    if check.get("isArray").and_then(Value::as_bool).unwrap_or(false) {
        assert!(value.is_array(), "{ctx} not array");
    }
    if check.get("isIso8601").and_then(Value::as_bool).unwrap_or(false) {
        if let Some(s) = value.as_str() {
            assert!(
                DateTime::parse_from_rfc3339(s).is_ok(),
                "{ctx} not ISO-8601 (got {s})"
            );
        } else {
            panic!("{ctx} not ISO-8601 (got non-string)");
        }
    }
    if let Some(arr) = check.get("isIn").and_then(Value::as_array) {
        assert!(arr.contains(value), "{ctx} not in {arr:?}");
    }
    if let Some(min) = check.get("min").and_then(Value::as_f64) {
        let v = value.as_f64().unwrap_or(f64::NEG_INFINITY);
        assert!(v >= min, "{ctx} {v} < min {min}");
    }
    if let Some(max) = check.get("max").and_then(Value::as_f64) {
        let v = value.as_f64().unwrap_or(f64::INFINITY);
        assert!(v <= max, "{ctx} {v} > max {max}");
    }
    if let Some(min_len) = check.get("minLength").and_then(Value::as_u64) {
        let len = value.as_array().map(|a| a.len() as u64).unwrap_or(0);
        assert!(len >= min_len, "{ctx} length {len} < {min_len}");
    }
}

async fn invoke_step(
    client: &hestia_plugin_sdk::HestiaClient,
    step: &Value,
    captures: &HashMap<String, HashMap<String, Value>>,
) -> Option<Value> {
    let raw_input = step.get("input").cloned().unwrap_or(Value::Object(serde_json::Map::new()));
    let input = interpolate(&raw_input, captures);

    if let Some(resource) = step.get("resource").and_then(Value::as_str) {
        let v = client
            .read_resource_raw(resource)
            .await
            .unwrap_or_else(|e| panic!("read_resource {resource} failed: {e}"));
        return Some(v);
    }

    let tool = step.get("tool")?.as_str()?;
    let get = |k: &str| input.get(k).cloned().unwrap_or(Value::Null);
    let get_str = |k: &str| input.get(k).and_then(Value::as_str).map(String::from);
    let get_str_or_default = |k: &str| get_str(k).unwrap_or_default();

    let result: Value = match tool {
        "hestia_connect" => return None, // already done
        "hestia_begin_action" => {
            let mut spec = ToolCallSpec::new(get_str_or_default("tool_name"));
            if let Some(t) = get_str("target") {
                spec = spec.with_target(t);
            }
            if let Some(s) = input.get("atp_stake").and_then(Value::as_f64) {
                spec.atp_stake = Some(s);
            }
            if let Some(params) = input.get("parameters").and_then(Value::as_object) {
                for (k, v) in params {
                    spec.parameters.insert(k.clone(), v.clone());
                }
            }
            let action = client.begin_action(spec).await.expect("begin_action");
            json!({
                "actionId": action.action_id.to_string(),
                "toolName": action.tool_name,
                "startedAt": action.started_at.to_rfc3339(),
                "chainPosition": action.chain_position,
            })
        }
        "hestia_record_outcome" => {
            let action = R6Action {
                action_id: uuid::Uuid::parse_str(&get_str_or_default("action_id")).unwrap(),
                tool_name: String::new(),
                started_at: Utc::now(),
                chain_position: 0,
            };
            let outcome = Outcome {
                success: get("success").as_bool().unwrap_or(false),
                magnitude: get("magnitude").as_f64().unwrap_or(0.5),
                error: get_str("error"),
                result: HashMap::new(),
            };
            let r = client.record_outcome(&action, outcome).await.expect("record_outcome");
            serde_json::to_value(&r).unwrap()
        }
        "hestia_query_policy" => {
            let action = R6Action {
                action_id: uuid::Uuid::parse_str(&get_str_or_default("action_id")).unwrap(),
                tool_name: String::new(),
                started_at: Utc::now(),
                chain_position: 0,
            };
            let r = client.query_policy(&action).await.expect("query_policy");
            serde_json::to_value(&r).unwrap()
        }
        "hestia_vault_get" => {
            let opts = VaultGetOptions {
                scope: input
                    .get("scope")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                    .unwrap_or_default(),
                reason: get_str("reason"),
            };
            match client.vault_get(&get_str_or_default("name"), opts).await {
                Ok(v) => serde_json::to_value(&v).unwrap(),
                Err(e) => {
                    let code = format!("{}", e);
                    // Heuristic mapping: the Rust SDK errors should provide a typed code.
                    // For now we expose them as the envelope shape so field checks work.
                    json!({
                        "_hestia_error": {
                            "code": map_error_code(&format!("{e:?}")),
                            "message": code,
                            "data": {},
                        }
                    })
                }
            }
        }
        "hestia_vault_set" => {
            let opts = VaultSetOptions {
                scope: input
                    .get("scope")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                    .unwrap_or_default(),
                tags: input
                    .get("tags")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                    .unwrap_or_default(),
                allowed_consumers: input
                    .get("allowed_consumers")
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                    .unwrap_or_default(),
            };
            let _ = client
                .vault_set(&get_str_or_default("name"), &get_str_or_default("value"), opts)
                .await
                .expect("vault_set");
            json!({"stored": true})
        }
        "hestia_query_history" => {
            let filt_v = input.get("filter").cloned().unwrap_or(Value::Null);
            let limit = filt_v.get("limit").and_then(Value::as_u64).unwrap_or(50) as u32;
            let filter = HistoryFilter {
                tool_name: filt_v.get("tool_name").and_then(Value::as_str).map(String::from),
                target_pattern: filt_v.get("target_pattern").and_then(Value::as_str).map(String::from),
                since: filt_v.get("since").and_then(Value::as_str).map(String::from),
                limit: Some(limit),
                outcome: filt_v.get("outcome").and_then(Value::as_str).map(String::from),
            };
            let r = client.query_history(filter).await.expect("query_history");
            serde_json::to_value(&r).unwrap()
        }
        "hestia_request_witness" => {
            let event_type = get_str_or_default("event_type");
            let event_data = input
                .get("event_data")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            // SDK returns the raw daemon response: {"witnessEntryHash": "<hex>"}
            client.request_witness(&event_type, event_data).await.expect("request_witness")
        }
        _ => panic!("unsupported tool: {tool}"),
    };
    Some(result)
}

fn map_error_code(rust_dbg: &str) -> &'static str {
    // Best-effort mapping. The Rust SDK's errors carry their own codes;
    // the harness just needs *some* code string to put in the envelope.
    if rust_dbg.contains("VaultScopeMismatch") {
        "hestia.vault_scope_mismatch"
    } else if rust_dbg.contains("VaultNotFound") {
        "hestia.vault_not_found"
    } else if rust_dbg.contains("ActionNotFound") {
        "hestia.action_not_found"
    } else if rust_dbg.contains("PolicyDenied") {
        "hestia.policy_denied"
    } else {
        "hestia.internal_error"
    }
}

#[tokio::test]
async fn presence_protocol_v0_conformance() {
    if !daemon_reachable() {
        if env::var("RUN_CONFORMANCE").as_deref() == Ok("1") {
            panic!("daemon not reachable at {}", endpoint());
        }
        eprintln!("skipping: daemon not reachable at {}", endpoint());
        return;
    }
    let vectors_file = vectors_path();
    if !vectors_file.exists() {
        eprintln!("skipping: vectors not found at {}", vectors_file.display());
        return;
    }
    let vectors: Value =
        serde_json::from_slice(&std::fs::read(&vectors_file).expect("read vectors")).expect("parse vectors");

    let client = create_hestia_client(
        HestiaClientConfig::new("conformance-runner-rust", "conformance-runner-rust")
            .with_endpoint(endpoint()),
    );
    let session = client.connect().await.expect("connect");
    let mut captures: HashMap<String, HashMap<String, Value>> = HashMap::new();
    captures.insert(
        "P0-001".into(),
        HashMap::from([("sessionId".into(), Value::String(session.session_id))]),
    );

    let scenarios = vectors
        .get("scenarios")
        .and_then(Value::as_array)
        .expect("scenarios array");

    for scenario in scenarios {
        let id = scenario.get("id").and_then(Value::as_str).unwrap_or("?");
        if id == "P0-001" {
            continue;
        }
        // setup steps (may write into this scenario's bucket via `capture`)
        if let Some(setup) = scenario.get("setup").and_then(Value::as_array) {
            for step in setup {
                if let Some(result) = invoke_step(&client, step, &captures).await {
                    if let Some(cap_spec) = step.get("capture").and_then(Value::as_object) {
                        let bucket = captures.entry(id.into()).or_default();
                        for (k, jp) in cap_spec {
                            let jp_str = jp.as_str().unwrap_or("");
                            let cleaned = jp_str.trim_start_matches("$.").trim_start_matches('$');
                            if let Some(v) = resolve_path(&result, cleaned) {
                                bucket.insert(k.clone(), v);
                            }
                        }
                    }
                }
            }
        }
        let steps = scenario.get("steps").and_then(Value::as_array).unwrap_or(&Vec::new()).clone();
        for step in &steps {
            let result = invoke_step(&client, step, &captures).await;
            // capture
            if let (Some(result), Some(cap_spec)) = (
                result.as_ref(),
                step.get("capture").and_then(Value::as_object),
            ) {
                let bucket = captures.entry(id.into()).or_default();
                for (k, jp) in cap_spec {
                    let jp_str = jp.as_str().unwrap_or("");
                    let cleaned = jp_str.trim_start_matches("$.").trim_start_matches('$');
                    if let Some(v) = resolve_path(result, cleaned) {
                        bucket.insert(k.clone(), v);
                    }
                }
            }
            // field checks
            if let Some(expect) = step.get("expect") {
                if let Some(checks) = expect.get("fieldChecks").and_then(Value::as_array) {
                    let result_ref = result.as_ref().cloned().unwrap_or(Value::Null);
                    for check in checks {
                        let path = check.get("path").and_then(Value::as_str).unwrap_or("");
                        if let Some(v) = resolve_path(&result_ref, path) {
                            check_field(&v, check, id);
                        } else {
                            panic!("[{id}] field {path:?} not found in result");
                        }
                    }
                }
            }
        }
    }
    client.disconnect().await.ok();
}
