/**
 * @hestia/plugin-sdk — Phase 0 skeleton
 *
 * Authoring kit for Hestia plugins. A plugin hooks into the host agent's
 * tool-call lifecycle, builds R6/R7 records via this SDK, emits them to
 * the user's local Hestia instance over MCP, and optionally queries for
 * policy decisions and credentials.
 *
 * Status: Phase 0 (skeleton). API will change as Phase 1 implementation
 * lands. Do not depend on this for production yet.
 *
 * See docs/PLUGIN_AUTHORING_GUIDE.md in the repo root for the contract.
 */

export interface HestiaClientConfig {
  /** Stable identifier for this plugin (e.g. "claude-code", "openclaw") */
  pluginId: string;
  /** Hestia MCP endpoint. Defaults to local stdio or discovered http endpoint. */
  hestiaEndpoint?: string;
  /** MCP protocol version this plugin targets. */
  protocolVersion?: number;
}

export interface ToolCallSpec {
  toolName: string;
  target?: string;
  parameters?: Record<string, unknown>;
  /** Optional ATP stake — declared cost of the action */
  atpStake?: number;
}

export interface R6Action {
  /** Opaque handle used to record outcome later */
  readonly id: string;
  readonly toolName: string;
  readonly startedAt: Date;
}

export interface Outcome {
  success: boolean;
  /** Domain-specific magnitude in [0..1]. 0 = trivial, 1 = highly consequential. */
  magnitude: number;
  /** Optional error description on failure */
  error?: string;
  /** Optional structured result for the witness chain */
  result?: Record<string, unknown>;
}

export type PolicyDecision = 'allow' | 'deny' | 'warn';

export interface PolicyResult {
  decision: PolicyDecision;
  /** Human-readable explanation */
  reason: string;
  /** ID of the policy that produced this decision */
  policyId?: string;
}

export interface VaultGetOptions {
  /** Scope tags (e.g. ["publish"], ["infer"]) — Hestia narrows allowed credentials by scope */
  scope: string[];
  /** Optional reason shown to the user when prompting for approval */
  reason?: string;
}

export interface HestiaClient {
  /** Establish MCP connection + obtain Soft LCT for this session */
  connect(): Promise<void>;

  /** Close the connection cleanly (emits a session-end witness event) */
  disconnect(): Promise<void>;

  /**
   * Begin tracking a tool call. Returns an R6Action handle the caller passes
   * back to recordOutcome().
   */
  beginAction(spec: ToolCallSpec): Promise<R6Action>;

  /**
   * Submit the outcome of an R6 action. Hestia updates the calling plugin's
   * trust state and appends a witness chain entry.
   */
  recordOutcome(action: R6Action, outcome: Outcome): Promise<void>;

  /**
   * Query Hestia's policy engine for an allow/deny/warn decision for an
   * in-flight R6 action. Plugin is responsible for honoring the decision.
   */
  queryPolicy(action: R6Action): Promise<PolicyResult>;

  /**
   * Request a credential from the user's vault by name. Hestia may prompt
   * the user for approval; result depends on the user's vault settings.
   * Throws if denied or if the credential doesn't exist.
   */
  vaultGet(name: string, options: VaultGetOptions): Promise<string>;

  /**
   * Read the user's optional shared cross-agent context. Returns whatever
   * the user has populated; may be empty.
   */
  getSharedContext(): Promise<Record<string, unknown>>;

  /** Read this plugin's current trust state (its T3/V3 in the user's society). */
  getOwnTrustState(): Promise<TrustState>;
}

export interface TrustState {
  /** T3: Talent / Training / Temperament — root averages */
  t3: { talent: number; training: number; temperament: number };
  /** V3: Valuation / Veracity / Validity — root averages */
  v3: { valuation: number; veracity: number; validity: number };
  /** Human-readable trust level (e.g. "medium", "high") */
  level: string;
  /** Number of recorded actions */
  actionCount: number;
  /** Days since most recent action */
  daysSinceLast: number;
}

/**
 * Create a Hestia client. Phase 0: returns a stub that throws on every call.
 * Phase 1: real MCP client backed by @modelcontextprotocol/sdk.
 */
export function createHestiaClient(_config: HestiaClientConfig): HestiaClient {
  throw new Error(
    '@hestia/plugin-sdk: Phase 0 skeleton — implementation lands in Phase 1. ' +
      'See https://github.com/dp-web4/hestia for status.',
  );
}
