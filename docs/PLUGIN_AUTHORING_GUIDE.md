# Hestia Plugin Authoring Guide

> Phase 0 — the contract a plugin satisfies. Subject to refinement as the first reference plugins ship.

## What a Hestia plugin is

A **Hestia plugin** is a thin observer that lives inside an AI agent client. Its job is to:

1. Hook into the agent's tool-call lifecycle.
2. Build an R6/R7 record for each tool call, using the Hestia Plugin SDK (PAK).
3. Emit the record to Hestia (the user's local Hestia instance) over MCP.
4. *Optionally* query Hestia for a policy decision and honor it (allow / deny / warn).
5. *Optionally* request scoped credentials from the user's vault when the agent needs them.

The plugin **does not** maintain its own trust state, its own audit chain, its own policy engine, or its own credential storage. All that lives in Hestia (where the user can see, control, and reason about it as one coherent system across all their plugged-in agents).

## What the plugin gets from Hestia (the value)

- **Agent gets a cryptographic identity** in the user's Web4 society. Other plugged-in agents can see and respond to its reputation.
- **Agent's actions are witnessed** in a chain the user owns and can audit.
- **Agent can ask for credentials** without the user pasting tokens into every config file.
- **Agent's trust state evolves** from observed outcomes — its "reliability score" reflects actual results.
- **Agent participates in cross-tool context** (the user's shared scratchpad / project state), if the user wants it to.

All of this without the plugin author having to implement governance, trust math, audit chains, or vault crypto. The PAK provides it.

## The PAK (Plugin Authoring Kit)

Three language editions of the same logical SDK:

| Edition | Package | Use when |
|---|---|---|
| **TypeScript / JavaScript** | `@hestia/plugin-sdk` (npm) | Plugin is JS/TS — most modern agents (Claude Code, OpenClaw, Cursor, Cline, ruflo) |
| **Python** | `hestia-plugin-sdk` (PyPI) | Plugin is Python (Aider, custom agents, scripts) |
| **Rust** | `hestia-plugin-sdk` (crates.io) | Plugin embeds in a Rust host (or wants minimum overhead) |

All three editions expose the same logical interface:

```typescript
// TypeScript reference (Python / Rust mirror this)
import { HestiaClient } from '@hestia/plugin-sdk';

const hestia = new HestiaClient({
  pluginId: 'claude-code',          // identifies this plugin instance
  hestiaEndpoint: 'mcp://localhost', // discovered automatically
});

await hestia.connect();
// At this point Hestia knows this plugin is running.
// Hestia issues a Soft LCT for this session.

// Inside the agent's tool-call hook:
const r6 = await hestia.beginAction({
  toolName: 'file_write',
  target: '/tmp/example.txt',
  parameters: { content: 'hello' },
  atpStake: 5,                       // optional: declare the cost
});

const policy = await hestia.queryPolicy(r6);
if (policy.decision === 'deny') {
  // honor the user's policy: don't execute the tool
  return { error: policy.reason };
}

// ...execute the tool...
const success = true;
const magnitude = 0.8;

await hestia.recordOutcome(r6, { success, magnitude });
// Hestia updates trust state, adds to witness chain.

// To request a credential:
const apiKey = await hestia.vaultGet('anthropic_api_key', ['infer']);
// User may be prompted for approval, depending on their settings.
```

## Plugin contract — minimum surface

A Hestia plugin satisfies this contract:

| Contract requirement | What it means |
|---|---|
| **Identifies itself** | At connect time, declare a stable plugin ID and the agent client it represents (e.g. `claude-code`, `openclaw`, `cursor`, `cline`, `ruflo`) |
| **Hooks tool calls** | Intercepts the host agent's tool-call lifecycle (pre-call + post-call). Every tool call gets an R6 record. |
| **Emits R6/R7 records** | Uses `hestia.beginAction()` + `hestia.recordOutcome()` for every tool call — including aborts, errors, and abandoned sessions. |
| **Honors policy decisions** | If `queryPolicy` returns deny or warn, the plugin acts accordingly — at minimum logs the decision; at best blocks the tool call. |
| **Requests credentials through Hestia** | Does NOT read credentials from environment variables, config files, or hardcoded values when a Hestia vault entry exists. |
| **Discloses session role** | On first run, declares what society role this plugin asks for (default: Citizen). User confirms or modifies. |
| **Free under AGPL or compatible** | First-party plugins are AGPL. Third-party plugins may be other open-source licenses as long as they don't extend Hestia core; commercial closed-source plugins go through the commercial-license process. |

That's it. The plugin can be ~50-100 lines of glue code calling into the PAK.

## Reference implementations (Phase 1)

These three plugins are the first PAK consumers and the canonical examples:

| Plugin | Status | Repo |
|---|---|---|
| **OpenClaw** | Phase 1 priority (refactor from `moltbot/extensions/web4-governance` into a thin observer) | `plugins/openclaw/` |
| **Claude Code** | Phase 1.5 (refactor the current 13K-line PR into ~2K-line thin observer) | `plugins/claude-code/` + upstream resubmit |
| **ruflo** (formerly claude-flow) | Phase 1.6 (refactor the rejected `claude-flow/v3/plugins/web4-governance`) | `plugins/ruflo/` + ruvnet upstream attempt |

Each of these is a public worked example. New plugin authors should:

1. Read the closest reference plugin to whatever agent client you're integrating with.
2. Copy the structure; replace the agent-client-specific hooks.
3. Reuse the PAK calls as-is (R6 build / policy query / outcome record / vault request).
4. Submit to the agent's upstream maintainers as a small "Hestia integration" PR.

## Plugin discovery (how Hestia finds them)

When the Hestia desktop app starts, it scans for known plugin-host applications on the system. For each one detected:

- Installed status: detect by checking conventional install paths
- Plugin enabled status: detect by reading the agent's plugin config
- One-click install: write the plugin's configuration to the agent's plugin directory

The discovery rules live in `core/src/plugin_discovery/` (one detector per supported agent).

To add a new agent: implement `PluginDiscoverer` for that agent. Submit as a PR.

## Versioning and compatibility

- PAK editions follow semver (`@hestia/plugin-sdk@0.x.y` etc.)
- The MCP protocol surface Hestia exposes is versioned (`hestia-mcp-protocol-version: 0`)
- Plugins declare which protocol version they require at connect time
- Hestia supports the current and one-prior protocol version

Breaking changes go through an ADR + at least 30-day notice in release notes.

## What plugins can NOT do (security boundaries)

- Read another plugin's credentials (each plugin has its own `allowed_consumers` ACL per credential)
- Write to another plugin's trust state (only Hestia core can update T3/V3)
- Bypass policy decisions (Hestia's MCP surface enforces; plugin compliance is a contract — non-compliance flags the plugin as untrusted)
- Read the witness chain wholesale (read-only access is by query, scoped to entries the plugin is involved in unless the user grants broader access)
- Modify the witness chain (append-only; only Hestia core appends after verifying R6 records)
- Forge another plugin's Soft LCT (Soft LCTs are signed by the user's society sovereign key, which the plugin never sees)

## Cross-plugin context (the differentiator)

Today, vendors don't share context with each other: Claude Code doesn't know what Cursor just did. With Hestia, the user can route shared context through their own machine:

- The user populates `hestia://context/shared` with whatever they want plugins to see (current project, current goal, current scratchpad).
- Plugins read that resource via MCP — they see what the user wants them to see.
- Plugins do NOT see each other's private state. Cross-agent visibility is mediated by the user.

This is what makes Hestia a *cross-vendor* trust layer: the user is the integration point, not any vendor's cloud.

## Authoring quickstart (TypeScript example)

```typescript
// plugins/myagent/src/index.ts
import { HestiaClient, R6Action } from '@hestia/plugin-sdk';

const hestia = new HestiaClient({ pluginId: 'myagent' });
await hestia.connect();

// Hook into your agent's tool-call lifecycle:
myAgent.onToolCall(async (toolCall, executeOriginal) => {
  const r6 = await hestia.beginAction({
    toolName: toolCall.name,
    target: toolCall.target,
    parameters: toolCall.params,
  });

  const policy = await hestia.queryPolicy(r6);
  if (policy.decision === 'deny') {
    return { error: `Hestia policy blocked: ${policy.reason}` };
  }

  try {
    const result = await executeOriginal(toolCall);
    await hestia.recordOutcome(r6, {
      success: true,
      magnitude: 0.5,  // domain-specific scoring
    });
    return result;
  } catch (e) {
    await hestia.recordOutcome(r6, { success: false, magnitude: 0.5, error: e.message });
    throw e;
  }
});

// Optionally hook credential requests:
myAgent.onCredentialNeeded(async (credentialName) => {
  return await hestia.vaultGet(credentialName, ['infer']);
});
```

That's the whole plugin. Most of the surface is in the PAK.

## When to NOT write a Hestia plugin

- The agent has no plugin/extension/hook system, AND you can't wrap it transparently. (E.g. proprietary cloud-only agents with no client-side execution.)
- The agent's tool-call surface is too opaque to observe meaningfully. (Some closed agents abstract tool calls into single LLM calls — there's no per-tool boundary to hook.)
- Your usage is read-only/observational and doesn't need trust accounting. (Then Hestia isn't useful for you.)

## Testing your plugin

(Will be expanded in Phase 1 once the PAK is real.)

```bash
# Once the PAK and Hestia are running:
hestia plugin test ./my-plugin/
```

Will run a battery of:
- MCP protocol compliance checks
- R6 record shape validation
- Policy honoring tests (does the plugin actually deny when told to?)
- Credential request scoping tests
- Witness chain emission completeness

## Contributing your plugin

If you've written a Hestia plugin for an agent that doesn't yet have one (or for a new version of one that does):

1. Open an issue describing the agent and link to its plugin docs.
2. Submit a PR with the plugin under `plugins/<agent-name>/`.
3. We'll iterate on the integration and merge once it satisfies the contract.

Third-party plugins live in this repo at first (to ensure consistency); as the ecosystem matures, we'll factor plugins into their own repos under the `@hestia/` npm scope.
