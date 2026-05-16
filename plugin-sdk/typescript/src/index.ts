/**
 * @hestia/plugin-sdk — Plugin Authoring Kit for Hestia.
 *
 * Public surface for plugin authors. Import what you need from this entry point.
 *
 * Quickstart:
 * ```ts
 * import { createHestiaClient } from '@hestia/plugin-sdk';
 *
 * const hestia = createHestiaClient({
 *   pluginId: 'my-agent-plugin',
 *   hostAgent: 'my-agent',
 * });
 * await hestia.connect();
 *
 * const action = await hestia.beginAction({ toolName: 'file_write', target: '/tmp/x' });
 * const policy = await hestia.queryPolicy(action);
 * if (policy.decision === 'deny') return { error: policy.reason };
 *
 * // ... execute the tool ...
 *
 * await hestia.recordOutcome(action, { success: true, magnitude: 0.5 });
 * ```
 *
 * See docs/PLUGIN_AUTHORING_GUIDE.md in the Hestia repo for the full contract.
 */

export { HestiaClient, createHestiaClient, actionNonce } from "./client.js";

export {
  HESTIA_PROTOCOL_VERSION,
  type HestiaClientConfig,
  type ConnectResult,
  type ToolCallSpec,
  type R6Action,
  type Outcome,
  type OutcomeResult,
  type PolicyDecision,
  type PolicyResult,
  type VaultGetOptions,
  type VaultValue,
  type VaultSetOptions,
  type TrustState,
  type WitnessEntry,
  type HistoryFilter,
  type HistoryResult,
} from "./types.js";

export {
  HestiaError,
  NotConnectedError,
  SessionExpiredError,
  PolicyDeniedError,
  VaultDeniedError,
  VaultNotFoundError,
  VaultScopeMismatchError,
  ActionNotFoundError,
  InvalidRoleError,
  mapHestiaError,
} from "./errors.js";

export { DEFAULT_HESTIA_ENDPOINT, discoverHestiaEndpoint } from "./transport.js";
