# hestia-plugin-sdk (Rust)

Plugin Authoring Kit for Hestia — Rust edition. Mirrors the [`@hestia-tools/plugin-sdk`](../typescript) TypeScript and [`hestia-plugin-sdk`](../python) Python references.

Use this to build Rust plugins for AI agents and agent hosts that want to be Web4-compliant via Hestia. Built on the official `rmcp` crate.

## Status

Phase 1 reference implementation. Compiles clean, 17 unit tests + 1 doc test passing. Full wire-protocol behavior is validated cross-language by the TypeScript and Python SDK test suites (both use the same MCP protocol against the same surface); the Rust SDK uses `rmcp` so its wire behavior matches by construction.

## Install (when published)

```toml
[dependencies]
hestia-plugin-sdk = "0.0.2"
```

For now, from a local clone (relative path).

## Quickstart

```rust
use hestia_plugin_sdk::{
    create_hestia_client, HestiaClientConfig, ToolCallSpec, Outcome, PolicyDecision,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = HestiaClientConfig::new("my-plugin", "my-agent")
        .with_role("citizen");

    let hestia = create_hestia_client(config);
    hestia.connect().await?;

    // Track an action through Hestia
    let action = hestia
        .begin_action(ToolCallSpec::new("file_write").with_target("/tmp/x"))
        .await?;

    // Optionally check policy
    let policy = hestia.query_policy(&action).await?;
    if policy.decision == PolicyDecision::Deny {
        eprintln!("Blocked by policy: {}", policy.reason);
        return Ok(());
    }

    // ... execute the tool ...

    // Record outcome — Hestia appends to witness chain + updates trust state
    hestia.record_outcome(&action, Outcome::success(0.5)).await?;

    hestia.disconnect().await?;
    Ok(())
}
```

## Interface

The Rust SDK exposes the same logical interface as the TypeScript and Python references:

| Method | Returns | What it does |
|---|---|---|
| `connect()` | `ConnectResult` | Establish MCP session + get Soft LCT |
| `disconnect()` | `()` | Clean shutdown |
| `begin_action(spec)` | `R6Action` | Register an in-flight tool call |
| `record_outcome(action, outcome)` | `OutcomeResult` | Submit outcome → witness chain + trust update |
| `query_policy(action)` | `PolicyResult` | Query user's policy: allow / deny / warn |
| `vault_get(name, options)` | `VaultValue` | Request a credential (may prompt user) |
| `vault_set(name, value, options)` | `Value` | Store a credential (always prompts) |
| `query_history(filter)` | `HistoryResult` | Query witness chain |
| `request_witness(event_type, data)` | `Value` | Custom (non-tool-call) witness event |
| `get_shared_context()` | `Value` | Read cross-agent shared context |
| `get_own_trust_state()` | `TrustState` | Read this plugin's T3/V3 in the user's society |

## Errors

The `HestiaError` enum has variants for each typed Hestia error. Match on it to react appropriately:

```rust
use hestia_plugin_sdk::{HestiaError, VaultGetOptions};

match hestia.vault_get("anthropic_api_key", VaultGetOptions { scope: vec!["infer".into()], reason: None }).await {
    Ok(v) => use_credential(v.value),
    Err(HestiaError::VaultNotFound { name }) => prompt_user_to_add(name),
    Err(HestiaError::VaultDenied { .. }) => degrade_gracefully(),
    Err(HestiaError::PolicyDenied { reason, .. }) => surface_policy_error(reason),
    Err(other) => log_and_fail_open(other),
}
```

## Testing

```bash
cargo test
```

17 unit tests covering: config builder ergonomics, outcome/spec builders, endpoint discovery, error envelope mapping (vault_not_found, policy_denied, action_not_found, vault_scope_mismatch, session_expired, unknown-code fallback), wire-format compatibility (camelCase deserialization, defaults, round-trip), and not-connected guard rejection.

Wire-protocol end-to-end validation happens in the TypeScript and Python SDK suites — both speak the same MCP surface (ADR-0005), so cross-language interop is the integration test.

## Error envelope handling

Per ADR-0005, Hestia tools return typed errors via a JSON envelope on the success path:

```json
{"_hestia_error": {"code": "hestia.vault_not_found", "message": "...", "data": {...}}}
```

The Rust SDK detects this envelope and maps to the appropriate `HestiaError` variant. See `tests/unit_tests.rs` for the per-variant coverage.

## License

AGPL-3.0-or-later.
