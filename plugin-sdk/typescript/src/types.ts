/**
 * Type definitions for the Hestia plugin SDK.
 *
 * These types mirror the MCP surface specified in ADR-0005. The wire
 * format is JSON-RPC over StreamableHTTP; these types are the
 * deserialized representations the SDK exposes to plugin authors.
 */

/** Protocol version this SDK targets. */
export const HESTIA_PROTOCOL_VERSION = 0;

/** Configuration when creating a Hestia client. */
export interface HestiaClientConfig {
  /** Stable identifier for this plugin (e.g. "claude-code", "openclaw"). */
  pluginId: string;
  /** Optional semver of the plugin's own code. */
  pluginVersion?: string;
  /** Which agent client this plugin is for ("claude-code", "openclaw", "ruflo", ...). */
  hostAgent: string;
  /** Optional semver of the host agent. */
  hostAgentVersion?: string;
  /** Society role this plugin wants. Defaults to "citizen". */
  requestedRole?: string;
  /**
   * Override Hestia's MCP endpoint. If omitted, the SDK auto-discovers in this order:
   * 1. `HESTIA_ENDPOINT` env var
   * 2. `~/.hestia/endpoint` file
   * 3. `http://127.0.0.1:7711` (default)
   */
  hestiaEndpoint?: string;
}

/** Result of `hestia_connect`. */
export interface ConnectResult {
  sessionId: string;
  softLct: string;
  assignedRole: string;
  protocolVersion: number;
}

/** Tool call spec passed to `beginAction`. */
export interface ToolCallSpec {
  toolName: string;
  target?: string;
  parameters?: Record<string, unknown>;
  /** Declared ATP cost of this action. */
  atpStake?: number;
}

/** Handle for an in-flight R6/R7 action. */
export interface R6Action {
  readonly actionId: string;
  readonly toolName: string;
  readonly startedAt: Date;
  readonly chainPosition: number;
}

/** Outcome of a completed action. */
export interface Outcome {
  success: boolean;
  /** Domain-specific magnitude in [0..1]. */
  magnitude: number;
  error?: string;
  result?: Record<string, unknown>;
}

/** Result of `hestia_record_outcome`. */
export interface OutcomeResult {
  witnessEntryHash: string;
  updatedTrustState: TrustState;
}

/** Policy decision returned by `hestia_query_policy`. */
export type PolicyDecision = "allow" | "deny" | "warn";

export interface PolicyResult {
  decision: PolicyDecision;
  reason: string;
  policyId?: string;
  /** False if Hestia is in dry-run mode (decision returned but not enforced). */
  enforced: boolean;
}

/** Options for `hestia_vault_get`. */
export interface VaultGetOptions {
  scope: string[];
  reason?: string;
}

/** Result of `hestia_vault_get` — the credential value plus optional approval token. */
export interface VaultValue {
  value: string;
  /** If user said "always allow this session", this token caches approval. */
  approvalToken?: string;
}

/** Options for `hestia_vault_set`. */
export interface VaultSetOptions {
  scope: string[];
  tags?: string[];
  allowedConsumers: string[];
}

/** Trust state for a single agent (this plugin's own, or another's). */
export interface TrustState {
  /** Web4 entity id (e.g. "plugin:claude-code"). Carries the entity-type prefix. */
  entityId: string;
  t3: {
    talent: number;
    training: number;
    temperament: number;
  };
  v3: {
    valuation: number;
    veracity: number;
    validity: number;
  };
  /** Categorical T3 level ("low", "medium_low", "medium", "medium_high", "high"). */
  level: string;
  actionCount: number;
  successCount: number;
  successRate: number;
  daysSinceLast: number;
}

/** A single witness chain entry. */
export interface WitnessEntry {
  hash: string;
  prevHash: string;
  timestamp: string;
  eventType: string;
  eventData: Record<string, unknown>;
  signerLct: string;
  chainPosition: number;
}

/** Filter for `hestia_query_history`. */
export interface HistoryFilter {
  toolName?: string;
  targetPattern?: string;
  /** ISO-8601 timestamp or relative ("1h", "30m", "2d"). */
  since?: string;
  limit?: number;
  outcome?: "success" | "failure" | "abandoned";
}

export interface HistoryResult {
  entries: WitnessEntry[];
  hasMore: boolean;
}
