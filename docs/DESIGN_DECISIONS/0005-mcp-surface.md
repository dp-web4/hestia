# ADR-0005: Hestia MCP surface specification

**Date:** 2026-05-15
**Status:** Accepted (Phase 1 entry)
**Authors:** dp + CBP-Claude (Opus 4.7)

## Context

ADR-0004 established that plugins talk to Hestia over MCP. To make the PAK SDK implementable, the MCP surface Hestia exposes needs to be specified concretely — resource URIs, tool names + parameter schemas, prompt names. This ADR is that spec.

## Decision

Hestia exposes a local MCP server. The server provides resources, tools, and prompts in three groups: **vault**, **society** (identity + trust state + witness chain), and **session** (the plugin's view of itself).

## Resources

URIs use the `hestia://` scheme.

| URI | Returns | Access control |
|---|---|---|
| ~~`hestia://vault/{name}`~~ | *Removed 2026-07-07* | The resource path returned the raw secret without the policy / scope / `allowed_consumers` / witness gates that `hestia_vault_get` enforces (GPT security review HST-001). Credential reads go through `hestia_vault_get` only. |
| `hestia://society/state` | JSON snapshot of the user's society (members, roles, ATP treasury) | Plugin's own role determines depth: Citizens see public state only; Administrators see full state |
| `hestia://society/trust/{agent_id}` | TrustState for the named agent (T3/V3 + level + action count + days-since-last) | Plugins see their own; cross-agent reads require user approval |
| `hestia://witness/recent` | Last N witness chain entries (paginated, default 50) | Plugin sees entries it participated in; broader views require user approval |
| `hestia://context/shared` | The user-populated cross-agent context (key-value map) | All connected plugins read (user controls what's in it) |
| `hestia://session/own` | This plugin's session state (Soft LCT, role, connect time) | Plugin reads its own session info; no cross-plugin access |

## Tools

Tool names are `hestia_<verb>_<noun>`.

### `hestia_connect`

Establishes the plugin's session. Called once at startup. Sets the plugin's identity and gets a Soft LCT.

**Params:**
```json
{
  "plugin_id": "string (required) — stable identifier, e.g. 'claude-code'",
  "plugin_version": "string (optional) — semver of the plugin code",
  "host_agent": "string (required) — which agent client this plugin is for, e.g. 'claude-code', 'openclaw', 'ruflo'",
  "host_agent_version": "string (optional)",
  "requested_role": "string (optional, default 'citizen') — society role this plugin wants"
}
```

**Returns:**
```json
{
  "session_id": "uuid",
  "soft_lct": "string — the Soft LCT URI to use in subsequent calls",
  "assigned_role": "string — the role Hestia actually assigned (may differ from requested)",
  "protocol_version": "number"
}
```

### `hestia_begin_action`

Marks the start of an R6/R7 action. Returns an action handle.

**Params:**
```json
{
  "tool_name": "string (required)",
  "target": "string (optional)",
  "parameters": "object (optional)",
  "atp_stake": "number (optional) — declared cost"
}
```

**Returns:**
```json
{
  "action_id": "uuid",
  "started_at": "ISO-8601 timestamp",
  "chain_position": "number — position in the witness chain"
}
```

### `hestia_record_outcome`

Submits the outcome of a previously-begun R6 action. Hestia updates trust state and appends to the witness chain.

**Params:**
```json
{
  "action_id": "uuid (required) — from begin_action",
  "success": "boolean (required)",
  "magnitude": "number (required, 0..1)",
  "error": "string (optional)",
  "result": "object (optional)",
  "closure_claims": [{
    "claim_id": "stable explicit identifier",
    "statement": "actor-authored claim",
    "scope": "bounded context in which the claim applies",
    "confidence": "number (required, 0..1)",
    "evidence": ["one or more inspectable pointers"],
    "known_limitations": ["optional explicit limitations"]
  }]
}
```

`closure_claims` is optional and uses schema
`hestia.closure-claims/v1`. A generic result or successful execution is never
converted into an implied claim.

**Returns:**
```json
{
  "witness_entry_hash": "hex string — the hash of the witness chain entry",
  "updated_trust_state": "TrustState object — the plugin's new T3/V3"
}
```

### `hestia_query_policy`

Queries the user's policy for an in-flight action. Plugin honors the returned decision.

**Params:**
```json
{
  "action_id": "uuid (required) — from begin_action",
  "context": "object (optional) — additional context for the policy engine"
}
```

**Returns:**
```json
{
  "decision": "string — 'allow' | 'deny' | 'warn'",
  "reason": "string — human-readable",
  "policy_id": "string (optional) — which policy matched",
  "enforced": "boolean — false if user is in dry-run mode"
}
```

### `hestia_vault_get`

Requests a credential by name. May prompt the user for approval.

**Params:**
```json
{
  "name": "string (required)",
  "scope": "array of strings (required) — e.g. ['publish'] or ['infer']",
  "reason": "string (optional) — shown to user during approval prompt"
}
```

**Returns:**
```json
{
  "value": "string — the credential value",
  "approval_token": "string (optional) — if user set 'always allow this session', the token caches approval"
}
```

Errors if denied, missing, or out-of-scope.

### `hestia_vault_set`

Stores a new credential. Always requires user approval.

**Params:**
```json
{
  "name": "string (required)",
  "scope": "array of strings (required)",
  "tags": "array of strings (optional)",
  "value": "string (required)",
  "allowed_consumers": "array of plugin_ids (required) — initial ACL"
}
```

**Returns:**
```json
{
  "stored": "boolean",
  "entry_id": "uuid"
}
```

### `hestia_query_history`

Queries the witness chain.

**Params:**
```json
{
  "filter": {
    "tool_name": "string (optional)",
    "target_pattern": "string (optional)",
    "since": "ISO-8601 timestamp or relative ('1h', '30m', '2d')",
    "limit": "number (default 50, max 500)",
    "outcome": "string (optional) — 'success' | 'failure' | 'abandoned'"
  }
}
```

**Returns:**
```json
{
  "entries": "array of WitnessEntry objects",
  "has_more": "boolean"
}
```

### `hestia_request_witness`

Adds a custom witness chain entry (for events that aren't tool-call outcomes — e.g. session boundaries, configuration changes).

**Params:**
```json
{
  "event_type": "string (required)",
  "event_data": "object (required)"
}
```

**Returns:**
```json
{
  "witness_entry_hash": "hex string"
}
```

## Prompts

Prompts are parameterized templates Hestia exposes for common workflows. Phase 1 ships these stubs; full implementations in Phase 2:

| Prompt | Purpose |
|---|---|
| `hestia_first_run` | First-time setup wizard (identity creation, role assignment, vault import) |
| `hestia_recipe_template` | Generate a society recipe (agent + roles + initial credentials) for sharing |
| `hestia_federation_handshake` | Initiate federation with another Hestia instance (Phase 4) |

## Sequence: plugin lifecycle

```
Plugin                                Hestia
  │                                     │
  │  initialize (MCP protocol)          │
  │  ──────────────────────────────────>│
  │  ←────────────────────────────────  │
  │  protocol caps                      │
  │                                     │
  │  tools/list                         │
  │  ──────────────────────────────────>│
  │  ←────────────────────────────────  │
  │  tools incl. hestia_connect         │
  │                                     │
  │  tools/call hestia_connect(...)     │
  │  ──────────────────────────────────>│
  │  ←────────────────────────────────  │
  │  session_id, soft_lct, role         │
  │                                     │
  │   ─── plugin is now active ───      │
  │                                     │
  │  // host agent calls a tool:        │
  │  tools/call hestia_begin_action()   │
  │  ──────────────────────────────────>│
  │  ←─ action_id ─                     │
  │                                     │
  │  // optional: query policy          │
  │  tools/call hestia_query_policy()   │
  │  ──────────────────────────────────>│
  │  ←─ allow/deny ─                    │
  │                                     │
  │  // optional: request credential    │
  │  tools/call hestia_vault_get()      │
  │  ──────────────────────────────────>│
  │  ←─ value (user-approved) ─         │
  │                                     │
  │  // ... plugin executes the tool ...│
  │                                     │
  │  // record outcome                  │
  │  tools/call hestia_record_outcome() │
  │  ──────────────────────────────────>│
  │  ←─ witness_hash, new trust state ─ │
  │                                     │
  │   ─── repeat for each tool call ─── │
```

## Errors

Hestia tools surface errors via TWO mechanisms depending on the failure mode:

### Mechanism A: typed-error envelope on the success path

When a tool needs to signal a Hestia-specific error (vault miss, policy denial, action not found, etc.), it returns a JSON envelope of this shape on the success path of the call:

```json
{
  "_hestia_error": {
    "code": "hestia.vault_not_found",
    "message": "Credential 'anthropic_api_key' not found",
    "data": { "name": "anthropic_api_key" }
  }
}
```

The SDK detects `_hestia_error` in any tool result and raises the typed error class corresponding to `code`. This is the **primary error path** for tool-execution errors.

**Why an envelope on the success path?** Both major MCP SDK implementations (TypeScript and Python) normalize tool exceptions into `isError=true` results when raised, dropping the `data` field that carries the typed error code. The envelope guarantees the code survives the wire, regardless of which language the server is implemented in.

### Mechanism B: JSON-RPC protocol errors (rare for tools)

Protocol-level failures (malformed requests, transport issues, auth failures) come back as standard JSON-RPC errors with a numeric code + optional `data`. If a JSON-RPC error happens to carry `data.code` starting with `hestia.`, the SDK maps it via the same code table. In practice this path is exercised mostly by initialize / capability negotiation issues.

### Code table

| Code | Meaning |
|---|---|
| `hestia.not_connected` | Plugin must call `hestia_connect` first |
| `hestia.session_expired` | Soft LCT expired; reconnect |
| `hestia.policy_denied` | Action denied by policy; plugin must honor |
| `hestia.vault_denied` | User declined credential request |
| `hestia.vault_not_found` | Credential name not in vault |
| `hestia.vault_scope_mismatch` | Plugin not in allowed_consumers for this credential |
| `hestia.action_not_found` | action_id doesn't reference a known action |
| `hestia.invalid_role` | Requested role not available to plugins |
| `hestia.invalid_response` | SDK couldn't parse a server response (defensive) |
| `hestia.unknown_tool` | Server doesn't recognize the tool (version mismatch) |

## Transport

Hestia runs as a **user-level daemon** (one per user; the Tauri desktop app hosts it). Multiple agent plugins connect to the same Hestia instance:

- **StreamableHTTP** (localhost only) at `http://127.0.0.1:7711` — primary plugin transport. SDK uses `StreamableHTTPClientTransport` from `@modelcontextprotocol/sdk`. Plugins connect directly when they have HTTP capability.

- **stdio bridge binary** (`hestia-mcp-bridge`, Phase 2 deliverable) — for agents that only configure MCP servers as spawned subprocesses (Claude Code's `claude_desktop_config.json` style, Cursor's MCP config). The bridge spawns as a child of the agent, forwards over HTTP to the Hestia daemon, and presents stdio to the agent. This lets every existing MCP-aware agent use Hestia without the agent needing HTTP-client capability.

The SDK auto-discovers Hestia's endpoint in this order:
1. `HESTIA_ENDPOINT` env var (explicit override)
2. `~/.hestia/endpoint` file (written by Hestia daemon on startup, contains the URL)
3. `http://127.0.0.1:7711` (default fallback)

## Versioning

Hestia declares `protocol_version` in `hestia_connect` response. The SDK declares the protocol version it was built against in `hestia_connect` request. Hestia supports current and one prior. Breaking changes get a +1 to `protocol_version` and 30-day deprecation notice.

## Trade-offs accepted

- **HTTP transport is local-only.** No remote MCP. Hestia is a local-first product; cross-machine federation is Phase 4 and uses a different protocol path (inter-society protocol, not MCP).
- **No streaming for `hestia_query_history`.** Returns paginated batches. If history is huge, plugin makes multiple calls. Simpler than streaming for v1.
- **`hestia_vault_set` always prompts.** No "store without prompting" mode. Mitigation: tools like dotfile-importers run as user-confirmed bulk operations through the desktop UI, not via the MCP tool.
- **No per-call subscriptions yet.** MCP supports resource subscriptions (notify on change). Phase 2 deliverable if useful.

## Implementation status

- ✅ ADR (this doc)
- ⏳ TypeScript SDK against this spec (next, this session)
- ⏳ Mock Hestia backend in TypeScript (next, this session — for SDK testing)
- ⏳ Real Hestia Rust core (Phase 1 ongoing)
- ⏳ Python + Rust SDK mirrors (after TypeScript reference stabilizes)
