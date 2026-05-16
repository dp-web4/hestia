# @hestia/plugin-openclaw

Hestia plugin for [OpenClaw](https://github.com/getclawdbot/) (formerly Moltbot). A thin observer that emits R6/R7 records to the user's Hestia daemon via [`@hestia/plugin-sdk`](../../plugin-sdk/typescript).

## Status

Phase 1 reference implementation. **Not yet runnable against a real OpenClaw installation** — pending Hestia daemon implementation (the real Rust core) and OpenClaw publishing a stable plugin SDK. The plugin is fully tested end-to-end against the mock Hestia server in this repo, and the architectural refactor is validated.

## What this plugin replaces

The original `moltbot/extensions/web4-governance` plugin (the predecessor to this one) implemented all of Web4 governance inside OpenClaw itself: its own R6 chain, its own audit storage, its own policy engine (including a local Phi-4 Mini LLM-based policy evaluator), its own Soft LCT generator, its own session state persistence, its own credential management.

This refactor strips all of that out. The plugin now delegates everything to the user's central Hestia instance via MCP.

## The numbers (refactor scorecard)

| | Original (`moltbot/extensions/web4-governance/`) | Refactored (`@hestia/plugin-openclaw`) |
|---|---:|---:|
| Production source lines (excl. tests) | **4,504** | **272** |
| Modules | 11 | 2 |
| Embedded R6 chain | yes | no (Hestia owns it) |
| Embedded policy engine | yes (rule-based + LLM-based) | no (queries Hestia) |
| Embedded Soft LCT generator | yes | no (Hestia issues it) |
| Embedded credential storage | partial | no (uses Hestia vault) |
| Embedded session persistence | yes | no (Hestia tracks) |
| Local Phi-4 Mini model file | yes (618 lines + GGUF runtime) | no (premium Hestia feature) |

**93.96% reduction in production code.** What's left is the integration glue between OpenClaw's plugin API and the Hestia SDK.

## What this means for the user

| User concern | Before (self-contained plugin) | After (Hestia plugin) |
|---|---|---|
| Trust state | Per-plugin (N plugins = N states) | Single, central (cross-agent reputation works) |
| Policy | Per-plugin rules | User sets once; applies to all plugins |
| Credentials | Scattered across `.env` / config | Single Hestia vault, scoped per plugin |
| Audit chain | Per-plugin file | One chain per user, queryable across all agents |
| Hardware binding | N/A | Available via Hestia premium tier |
| Federation | N/A | Available via Hestia inter-society protocol (Phase 4) |

## Architecture

```
┌──────────────────────────┐
│  OpenClaw host process   │
│                          │
│  ┌────────────────────┐  │
│  │ This plugin        │  │
│  │ (~185 lines)       │  │
│  │                    │  │
│  │  before_tool_call  │──────┐
│  │  after_tool_call   │──────┤
│  └────────────────────┘  │   │
│                          │   │ HestiaClient
│                          │   │ (via @hestia/plugin-sdk)
└──────────────────────────┘   │
                               ▼
                  ┌─────────────────────────┐
                  │   Hestia daemon         │
                  │   (per-user, local)     │
                  │                         │
                  │  R6 chain (witness)     │
                  │  Policy engine          │
                  │  Vault                  │
                  │  Society state          │
                  │  Trust evolution        │
                  └─────────────────────────┘
```

## Plugin flow

For every tool call OpenClaw is about to execute:

1. `before_tool_call` fires.
2. Plugin calls `hestia.beginAction({ toolName, target, parameters, atpStake })` to register the in-flight action.
3. Plugin calls `hestia.queryPolicy(action)`. If Hestia returns `deny`, the plugin returns `{ proceed: false, reason }` and OpenClaw blocks the call. If `allow` or `warn`, the call proceeds.
4. OpenClaw executes the tool.
5. `after_tool_call` fires.
6. Plugin calls `hestia.recordOutcome(action, { success, magnitude, error?, result? })`. Hestia appends a witness chain entry and updates the plugin's T3/V3 trust state.

## Configuration

The plugin accepts options via OpenClaw's `pluginConfig`:

```jsonc
{
  "plugins": {
    "web4-governance": {
      // Override Hestia endpoint (default: auto-discover via env var
      // → ~/.hestia/endpoint → http://127.0.0.1:7711)
      "hestiaEndpoint": "http://127.0.0.1:7711",

      // Society role this plugin requests on connect
      "requestedRole": "citizen",

      // When true (default), policy 'deny' decisions block tool calls.
      // When false, deny is logged as warning but the call proceeds (dry-run).
      "enforce": true
    }
  }
}
```

## Graceful degradation

If Hestia is not running or unreachable:

- Plugin logs an error at startup
- Returns silently from `register()` without subscribing to hooks
- OpenClaw continues to function normally, just without Hestia features
- No crashes, no agent slowdown

This is the "fail-open on the agent side" property: Hestia adds value when present; its absence doesn't break the agent. Verified by the `gracefully no-ops when Hestia is unreachable` integration test.

## Testing

```bash
npm install
npm test
```

The test suite (`test/integration.test.ts`) wires:

```
mock OpenClaw host → this plugin → @hestia/plugin-sdk → mock Hestia server
```

7 tests cover: plugin registration + Hestia connection, Bash tool call lifecycle, Read tool with lower magnitude, failure outcome recording, paired before/after via `callId`, graceful no-op when Hestia is unreachable, common target-extraction conventions.

## Building

```bash
npm run build  # tsc → dist/
```

Outputs `dist/index.js` + `dist/index.d.ts` for consumption by OpenClaw.

## Installing in OpenClaw

(Once OpenClaw publishes its plugin loader)

```bash
npm install @hestia/plugin-openclaw
```

Then in OpenClaw config:

```jsonc
{
  "plugins": {
    "web4-governance": {}
  }
}
```

OpenClaw discovers the plugin from its `package.json` keywords and registers it.

## License

AGPL-3.0-or-later. See LICENSE at repo root.
