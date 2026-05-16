# ADR-0004: Plugin Authoring Kit extraction from the three existing Web4 governance plugins

**Date:** 2026-05-15
**Status:** Accepted (Phase 0)
**Authors:** dp + CBP-Claude (Opus 4.7)

## Context

Three working Web4 governance plugins exist as of Phase 0:

| Plugin | Location | Status | Lines |
|---|---|---|---|
| Claude Code | `web4/claude-code-plugin/` (open PR [anthropics/claude-code#20448](https://github.com/anthropics/claude-code/pull/20448)) | Upstream PR open | 13,242 |
| OpenClaw (formerly Moltbot) | `moltbot/extensions/web4-governance/` | Released | ~3,500 (TypeScript, w/o tests) |
| ruflo (formerly claude-flow) | `claude-flow/v3/plugins/web4-governance/` | Rejected upstream | ~2,500 (TypeScript) |

All three independently implement the same core surface (R6 records, hash-linked audit chain, Soft LCT session identity, policy engine, witnessing). The Plugin Authoring Kit (PAK) extracts this common pattern into a publishable SDK so future plugins can be ~50-100 lines instead of ~3,000.

## Decision

The PAK SDK exposes a single `HestiaClient` interface (with TypeScript, Python, and Rust editions of the same logical contract) that encapsulates:

1. Connection lifecycle (`connect` / `disconnect`)
2. R6 action lifecycle (`beginAction` / `recordOutcome`)
3. Policy query (`queryPolicy`)
4. Credential vault access (`vaultGet`)
5. Trust state read (`getOwnTrustState`)
6. Shared context read (`getSharedContext`)

Everything else moves OUT of the plugin and INTO the user's central Hestia instance.

## Module-by-module mapping

The OpenClaw plugin is the most complete reference. Here's how each of its modules maps to the new architecture:

| Existing plugin module | Lines | Function | Hestia plugin replacement |
|---|---|---|---|
| `r6.ts` | ~90 | R6Request type + builder; hashes inputs/outputs | **SDK provides `R6Action` types + `beginAction()` builder**. Identical shape. |
| `soft-lct.ts` | ~30 | Generate session identity locally from machine + user | **Replaced.** Hestia issues a Soft LCT to the plugin on `connect()` (so the user's sovereign key signs the LCT, not the plugin's machine context). |
| `audit.ts` | ~300 (with persistence + filtering) | Hash-linked audit chain stored in local file | **Replaced.** SDK's `recordOutcome()` emits to Hestia's witness chain. Plugin doesn't own the chain. |
| `policy.ts` | ~120 | Rule-based policy engine with priority sort, first-match-wins | **Replaced.** SDK's `queryPolicy()` calls Hestia; Hestia's engine evaluates. Plugin honors the decision. |
| `policy-types.ts` | ~70 | PolicyRule, PolicyMatch, RateLimitSpec, PolicyConfig types | **Lives in Hestia.** Plugins receive `PolicyResult` (decision + reason); they don't need to know rule internals. |
| `policy-entity.ts` | ~330 | PolicyEntity as first-class hash-IDed trust participant | **Lives in Hestia.** Each user's society has its own policy entities. |
| `policy-model.ts` + 3 related | ~570 | LLM-based policy evaluation (Phi-4 Mini local inference) | **Hestia premium feature.** Optional advanced policy backend; free tier uses rule-based only. |
| `session-state.ts` | ~60 | Session metadata persistence | **Replaced.** Hestia's society state covers session tracking. |
| `rate-limiter.ts` | ~70 | Per-rule rate limiting | **Lives in Hestia** (server-side, applied during `queryPolicy`); SDK exposes optional client-side helper for plugins that need local backoff. |
| `presets.ts` | ~150 | Bundled policy preset configs ("strict", "balanced", "permissive") | **Lives in Hestia.** SDK exposes preset names for plugins to declare which preset they recommend on first install. |
| `reporter.ts` | ~280 | Surfaces audit status to user (CLI / chat output) | **Replaced.** Hestia's inspection UI is the canonical viewer. Plugins don't surface their own audit UI. |
| `matchers.ts` | ~50 | Glob/regex tool name matching utility | **Pure utility.** SDK exports as a helper for plugins that want client-side filtering. |

## Architectural shift summarized

```
BEFORE (self-contained per plugin):

  ┌────────────────────────────────────────────────┐
  │  Plugin (~3000 lines)                          │
  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
  │  │ R6 build │ │ Audit    │ │ Policy       │    │
  │  │          │ │ chain    │ │ engine       │    │
  │  └──────────┘ └──────────┘ └──────────────┘    │
  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
  │  │ Soft LCT │ │ Session  │ │ Rate limit   │    │
  │  │ (local)  │ │ state    │ │              │    │
  │  └──────────┘ └──────────┘ └──────────────┘    │
  │  ┌────────────────────────────────────────┐    │
  │  │ Local file storage for chain + state   │    │
  │  └────────────────────────────────────────┘    │
  └────────────────────────────────────────────────┘
       (per-agent — N plugins = N independent trust states)

AFTER (thin observer):

  ┌──────────────────────────────┐
  │ Plugin (~50-100 lines)       │
  │  ┌────────────────────────┐  │
  │  │ Hook into agent's      │  │
  │  │ tool-call lifecycle    │  │
  │  └──────────┬─────────────┘  │
  │             │                │
  │  ┌──────────▼─────────────┐  │
  │  │ HestiaClient (SDK)     │  │
  │  └──────────┬─────────────┘  │
  └─────────────┼────────────────┘
                │ MCP
  ┌─────────────▼────────────────┐
  │ Hestia (central, per-user)   │
  │  R6 chain | Policy engine    │
  │  Trust state | Vault          │
  │  Session state | UI          │
  │  ALL plugins emit here       │
  └──────────────────────────────┘

       (one trust state per user, shared across all plugins)
```

## Refactor plan for the three reference plugins (Phase 1)

### OpenClaw (Phase 1 priority)

- Strip `audit.ts`, `policy.ts`, `policy-entity.ts`, `policy-model.ts` (and friends), `session-state.ts`, `rate-limiter.ts`, `presets.ts`, `reporter.ts` from the plugin source tree.
- Keep `r6.ts` (but import types from `@hestia/plugin-sdk` instead of defining them locally).
- Keep `soft-lct.ts` only as a fallback for offline mode (Hestia issues the canonical Soft LCT).
- Keep `matchers.ts` as a client-side utility if useful.
- Rewrite `index.ts` to use `HestiaClient` from `@hestia/plugin-sdk`.
- Expected result: plugin shrinks from ~3500 lines to ~150-300 lines.

### Claude Code (Phase 1.5)

- Same refactor pattern as OpenClaw.
- The current PR (anthropics/claude-code#20448, 13,242 additions) becomes ~1,500-2,000 additions after the refactor.
- Resubmit upstream as a leaner PR with "moved governance to external Hestia service" as the architecture story. Far more likely to merge.

### ruflo (Phase 1.6)

- Same refactor pattern.
- Resubmit to `ruvnet/ruflo` upstream as a second attempt with the leaner architecture.

## SDK interface (lock-in for Phase 1)

The TypeScript reference (Python and Rust mirror this same logical interface):

```typescript
interface HestiaClient {
  // Lifecycle
  connect(): Promise<void>;
  disconnect(): Promise<void>;

  // R6 action lifecycle (the load-bearing pair)
  beginAction(spec: ToolCallSpec): Promise<R6Action>;
  recordOutcome(action: R6Action, outcome: Outcome): Promise<void>;

  // Optional: query before executing
  queryPolicy(action: R6Action): Promise<PolicyResult>;

  // Optional: request credentials when needed
  vaultGet(name: string, options: VaultGetOptions): Promise<string>;

  // Optional: read shared cross-agent context
  getSharedContext(): Promise<Record<string, unknown>>;

  // Optional: read own trust state (for UI display in the plugin's own UX)
  getOwnTrustState(): Promise<TrustState>;
}
```

Phase 0 skeletons already in the repo at `plugin-sdk/{typescript,python,rust}/`. Phase 1 implementation backs each with a real MCP client.

## Open questions to resolve in Phase 1 implementation

1. **Soft LCT issuance protocol.** When a plugin calls `connect()`, how does Hestia verify the plugin's claim about its identity (which agent client it represents)? Phase 1 baseline: per-plugin install token configured at plugin install time. Adversarial scenarios revisit later.

2. **Policy query latency budget.** Each tool call wants `queryPolicy` to return in <50ms (otherwise it adds visible latency to the user's agent interactions). Phase 1: rule-based policies cached client-side per session; LLM-based premium policies require a different latency contract.

3. **Outcome scoring semantics.** `recordOutcome` takes a `magnitude` in [0..1]. What's the canonical interpretation across plugins? Phase 1: define this in the SDK docs (per tool category — e.g. "for file_write, magnitude = log10(file_size) / 10"); plugin authors override as needed.

4. **R6 chain integrity in the central Hestia instance.** With plugins emitting from multiple clients concurrently, who serializes the chain? Phase 1: Hestia core serializes; plugins emit asynchronously and Hestia assigns chain position.

5. **Offline mode.** What if Hestia is not running when a plugin's host agent starts? Phase 1: SDK falls back to local-only R6 (writes to disk; sync to Hestia when it reconnects) — preserves the witness chain without requiring Hestia to be up 100% of the time.

6. **Policy model (premium feature).** OpenClaw plugin ships with local Phi-4 Mini policy evaluation. Hestia premium can host this centrally; the plugin's local copy is redundant. Decision: free tier uses rule-based only; premium tier exposes LLM-policy backend via the same `queryPolicy()` API. Plugin code doesn't change between tiers.

These get answered in later ADRs (Phase 1).

## Trade-offs accepted

- **Plugins lose ability to function entirely offline.** With Hestia central, plugins need to reach Hestia for policy + witness emission. Mitigation: SDK offline fallback (queue locally, sync later). The benefit (one trust state, cross-agent reputation) outweighs the cost.
- **Existing plugin maintainers have to refactor.** The three reference plugins need ~50% rewrite. We do this work (dp-web4 owns all three); for external plugin maintainers we provide migration guides.
- **Hestia becomes a single point of failure for trust evaluation.** Without Hestia running, plugins fall back to offline mode (no policy enforcement, local R6 chain). Documented behavior; acceptable for v1.
- **Plugin attack surface vs sandbox concern.** Each plugin has access to Hestia's vault credentials it's been granted. Plugin compromise = credential compromise within its scope. Standard sandbox concern; Hestia's per-plugin ACL on credentials minimizes blast radius.

## What this enables

Once the PAK ships and the three reference plugins refactor against it:

1. **Plugin authoring becomes accessible.** New plugin = ~50-100 lines of glue + use the SDK. Community contributions become tractable.
2. **Cross-agent reputation becomes real.** Claude Code's outcomes feed the same T3/V3 that OpenClaw and ruflo write to. The user can answer "which agent is most reliable on X?" from real cross-tool data.
3. **Single policy surface.** The user sets policy once; it applies uniformly across all plugged-in agents.
4. **Credential sprawl is solved.** All plugins request from Hestia's vault; no per-agent credential storage.
5. **Upstream PR merges become more tractable.** A 200-line "Hestia integration" plugin PR has a much higher acceptance probability than a 3000-line "Web4 governance" PR.

## Implementation status

- ✅ PAK skeletons in three languages exist (commit `fac87e5`)
- ✅ This ADR documents the extraction plan
- ⏳ Phase 1: real implementation of the SDK clients (Phase 1 deliverable)
- ⏳ Phase 1: refactor OpenClaw plugin against the SDK
- ⏳ Phase 1.5: refactor Claude Code plugin
- ⏳ Phase 1.6: refactor ruflo plugin
