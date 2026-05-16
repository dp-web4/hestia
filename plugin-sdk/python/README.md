# hestia-plugin-sdk (Python)

Plugin Authoring Kit for Hestia — Python edition. Mirrors the [`@hestia/plugin-sdk`](../typescript) TypeScript reference. Use this to build Python plugins for AI agents (Aider, custom Python agents, scripts) that want to be Web4-compliant via Hestia.

## Status

Phase 1 reference implementation. SDK is real and tested end-to-end against the bundled mock Hestia server (raw `Server` from the Python `mcp` package). Not yet runnable against a real Hestia daemon — that's the Phase 1 follow-on.

## Install (when published)

```bash
pip install hestia-plugin-sdk
```

For now, from a clone:

```bash
pip install -e .
```

## Quickstart

```python
import asyncio
from hestia_plugin_sdk import (
    HestiaClient, HestiaClientConfig, ToolCallSpec, Outcome,
    VaultGetOptions, VaultNotFoundError,
)

async def main():
    config = HestiaClientConfig(
        plugin_id="my-python-plugin",
        host_agent="my-agent",
        requested_role="citizen",
    )
    async with HestiaClient(config) as hestia:
        # Begin tracking an R6 action
        action = await hestia.begin_action(
            ToolCallSpec(tool_name="file_write", target="/tmp/x")
        )

        # Optionally check policy
        policy = await hestia.query_policy(action)
        if policy.decision == "deny":
            return {"error": policy.reason}

        # ... execute the tool ...

        # Record outcome — Hestia appends to witness chain + updates trust state
        await hestia.record_outcome(action, Outcome(success=True, magnitude=0.5))

        # Fetch credentials when needed
        try:
            token = await hestia.vault_get("anthropic_api_key", VaultGetOptions(scope=["infer"]))
        except VaultNotFoundError:
            ...

asyncio.run(main())
```

## Interface

The Python SDK exposes the same logical interface as the TypeScript reference:

| Method | Returns | What it does |
|---|---|---|
| `connect()` | `ConnectResult` | Establish MCP session + get Soft LCT |
| `disconnect()` | None | Clean shutdown |
| `begin_action(spec)` | `R6Action` | Register an in-flight tool call |
| `record_outcome(action, outcome)` | `OutcomeResult` | Submit outcome → witness chain + trust update |
| `query_policy(action)` | `PolicyResult` | Query user's policy: allow / deny / warn |
| `vault_get(name, options)` | `VaultValue` | Request a credential (may prompt user) |
| `vault_set(name, value, options)` | `dict` | Store a credential (always prompts) |
| `query_history(filter)` | `HistoryResult` | Query witness chain |
| `request_witness(event_type, data)` | `dict` | Custom (non-tool-call) witness event |
| `get_shared_context()` | `dict` | Read cross-agent shared context |
| `get_own_trust_state()` | `TrustState` | Read this plugin's T3/V3 in the user's society |

## Errors

Typed errors raised from typed operations:

- `NotConnectedError` — used a method before `connect()`
- `SessionExpiredError` — Soft LCT expired; reconnect
- `PolicyDeniedError` — action blocked by user's policy
- `VaultDeniedError` — user declined credential request
- `VaultNotFoundError` — credential name not in vault
- `VaultScopeMismatchError` — plugin not authorized for this credential
- `ActionNotFoundError` — `record_outcome` for unknown action_id
- `InvalidRoleError` — requested role not available

## Testing

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
```

The test suite (`tests/test_smoke.py`) runs the full SDK lifecycle against a mock Hestia server built on the raw `mcp.server.lowlevel.Server`. Validates that the Python SDK's contract matches the TypeScript reference SDK against the same MCP surface (ADR-0005).

## Notes on Python MCP behavior

The Python `mcp` package normalizes tool exceptions into `isError: True` results with text content, dropping the original `data` field. To preserve typed error metadata, Hestia tools (both mock and real) return a JSON envelope of the form:

```json
{"_hestia_error": {"code": "hestia.vault_not_found", "message": "...", "data": {...}}}
```

The SDK detects this envelope on the success path and raises the appropriate typed error. See `ADR-0005` in the repo root for the full protocol spec.

## License

AGPL-3.0-or-later.
