/**
 * HestiaClient — the MCP client wrapper that plugins use to talk to Hestia.
 *
 * Plugin authors instantiate this once per session via `createHestiaClient(config)`,
 * call `connect()` once at startup, then use `beginAction` / `recordOutcome` /
 * `queryPolicy` / `vaultGet` / etc. throughout the plugin's lifecycle.
 *
 * Under the hood: an MCP client (via @modelcontextprotocol/sdk) connected to
 * Hestia's local HTTP server using StreamableHTTPClientTransport.
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { randomUUID } from "node:crypto";

import {
  HESTIA_PROTOCOL_VERSION,
  type ConnectResult,
  type HestiaClientConfig,
  type HistoryFilter,
  type HistoryResult,
  type Outcome,
  type OutcomeResult,
  type PolicyResult,
  type R6Action,
  type ToolCallSpec,
  type TrustState,
  type VaultGetOptions,
  type VaultSetOptions,
  type VaultValue,
} from "./types.js";
import {
  HestiaError,
  NotConnectedError,
  mapHestiaError,
} from "./errors.js";
import { discoverHestiaEndpoint } from "./transport.js";

/** Internal state for a connected session. */
interface SessionState {
  sessionId: string;
  softLct: string;
  assignedRole: string;
  protocolVersion: number;
}

export class HestiaClient {
  private mcpClient: Client | null = null;
  private transport: StreamableHTTPClientTransport | null = null;
  private session: SessionState | null = null;

  constructor(private readonly config: HestiaClientConfig) {}

  /**
   * Establish the MCP connection and the Hestia session.
   * Must be called before any other method.
   */
  async connect(): Promise<ConnectResult> {
    const endpoint = await discoverHestiaEndpoint(this.config.hestiaEndpoint);
    const url = new URL(endpoint);

    this.mcpClient = new Client(
      { name: this.config.pluginId, version: this.config.pluginVersion ?? "0.0.0" },
      { capabilities: {} },
    );

    this.transport = new StreamableHTTPClientTransport(url);
    await this.mcpClient.connect(this.transport);

    const result = await this.callTool<ConnectResult>("hestia_connect", {
      plugin_id: this.config.pluginId,
      plugin_version: this.config.pluginVersion,
      host_agent: this.config.hostAgent,
      host_agent_version: this.config.hostAgentVersion,
      requested_role: this.config.requestedRole ?? "citizen",
      protocol_version: HESTIA_PROTOCOL_VERSION,
    });

    this.session = {
      sessionId: result.sessionId,
      softLct: result.softLct,
      assignedRole: result.assignedRole,
      protocolVersion: result.protocolVersion,
    };

    return result;
  }

  /** Close the connection. Emits a session-end witness event on the server side. */
  async disconnect(): Promise<void> {
    if (this.mcpClient) {
      await this.mcpClient.close();
      this.mcpClient = null;
      this.transport = null;
      this.session = null;
    }
  }

  /** Begin tracking an R6/R7 action. */
  async beginAction(spec: ToolCallSpec): Promise<R6Action> {
    this.requireSession();
    const result = await this.callTool<{
      actionId: string;
      startedAt: string;
      chainPosition: number;
    }>("hestia_begin_action", {
      tool_name: spec.toolName,
      target: spec.target,
      parameters: spec.parameters,
      atp_stake: spec.atpStake,
    });
    return {
      actionId: result.actionId,
      toolName: spec.toolName,
      startedAt: new Date(result.startedAt),
      chainPosition: result.chainPosition,
    };
  }

  /** Submit the outcome of a previously-begun action. */
  async recordOutcome(action: R6Action, outcome: Outcome): Promise<OutcomeResult> {
    this.requireSession();
    return this.callTool<OutcomeResult>("hestia_record_outcome", {
      action_id: action.actionId,
      success: outcome.success,
      magnitude: outcome.magnitude,
      error: outcome.error,
      result: outcome.result,
    });
  }

  /** Query Hestia's policy engine for a decision on this action. */
  async queryPolicy(
    action: R6Action,
    context?: Record<string, unknown>,
  ): Promise<PolicyResult> {
    this.requireSession();
    return this.callTool<PolicyResult>("hestia_query_policy", {
      action_id: action.actionId,
      context,
    });
  }

  /** Request a credential by name. May prompt the user for approval. */
  async vaultGet(name: string, options: VaultGetOptions): Promise<VaultValue> {
    this.requireSession();
    return this.callTool<VaultValue>("hestia_vault_get", {
      name,
      scope: options.scope,
      reason: options.reason,
    });
  }

  /** Store a new credential (always requires user approval). */
  async vaultSet(
    name: string,
    value: string,
    options: VaultSetOptions,
  ): Promise<{ stored: boolean; entryId: string }> {
    this.requireSession();
    return this.callTool<{ stored: boolean; entryId: string }>("hestia_vault_set", {
      name,
      value,
      scope: options.scope,
      tags: options.tags,
      allowed_consumers: options.allowedConsumers,
    });
  }

  /** Query the witness chain. */
  async queryHistory(filter: HistoryFilter): Promise<HistoryResult> {
    this.requireSession();
    return this.callTool<HistoryResult>("hestia_query_history", { filter });
  }

  /** Add a custom witness chain entry (for non-tool events). */
  async requestWitness(
    eventType: string,
    eventData: Record<string, unknown>,
  ): Promise<{ witnessEntryHash: string }> {
    this.requireSession();
    return this.callTool<{ witnessEntryHash: string }>("hestia_request_witness", {
      event_type: eventType,
      event_data: eventData,
    });
  }

  /** Read the user's optional shared cross-agent context. */
  async getSharedContext(): Promise<Record<string, unknown>> {
    this.requireSession();
    return this.readResource<Record<string, unknown>>("hestia://context/shared");
  }

  /** Read this plugin's own trust state in the user's society. */
  async getOwnTrustState(): Promise<TrustState> {
    this.requireSession();
    // The plugin's own agent_id is the SDK-side echo of the session's plugin_id.
    return this.readResource<TrustState>(
      `hestia://society/trust/${encodeURIComponent(this.config.pluginId)}`,
    );
  }

  // ------- internals -------

  private requireSession(): SessionState {
    if (!this.mcpClient || !this.session) {
      throw new NotConnectedError();
    }
    return this.session;
  }

  /** Invoke an MCP tool and unwrap the structured result, mapping errors. */
  private async callTool<T>(toolName: string, args: Record<string, unknown>): Promise<T> {
    if (!this.mcpClient) {
      throw new NotConnectedError();
    }
    try {
      const result = await this.mcpClient.callTool({ name: toolName, arguments: args });
      // MCP tool results have either structuredContent or text content blocks.
      // Hestia tools always return structured JSON in the first content block's text.
      const content = (result as { content?: Array<{ type: string; text?: string }> }).content;
      const structured = (result as { structuredContent?: unknown }).structuredContent;
      if (structured !== undefined) return structured as T;
      if (content && content[0]?.type === "text" && content[0].text) {
        return JSON.parse(content[0].text) as T;
      }
      throw new HestiaError(
        "hestia.invalid_response",
        `Tool ${toolName} returned no parseable content`,
      );
    } catch (err) {
      // MCP errors arrive as McpError with a numeric JSON-RPC code and
      // hestia-specific code carried in `data.code` (since JSON-RPC error
      // codes are reserved integers, custom error codes go in `data`).
      if (err && typeof err === "object" && "data" in err) {
        const e = err as { message?: string; data?: unknown };
        if (
          typeof e.data === "object" &&
          e.data !== null &&
          "code" in e.data
        ) {
          const data = e.data as { code: unknown };
          if (typeof data.code === "string" && data.code.startsWith("hestia.")) {
            throw mapHestiaError(data.code, e.message ?? "", e.data);
          }
        }
      }
      throw err;
    }
  }

  /** Read an MCP resource and parse it as JSON. */
  private async readResource<T>(uri: string): Promise<T> {
    if (!this.mcpClient) {
      throw new NotConnectedError();
    }
    const result = await this.mcpClient.readResource({ uri });
    // Resources can have text or blob contents; we expect text/JSON.
    const contents = (result as { contents: Array<{ uri: string; mimeType?: string; text?: string }> }).contents;
    if (!contents || contents.length === 0 || !contents[0].text) {
      throw new HestiaError(
        "hestia.invalid_resource",
        `Resource ${uri} returned no text content`,
      );
    }
    return JSON.parse(contents[0].text) as T;
  }
}

/** Factory function — the canonical way to construct a HestiaClient. */
export function createHestiaClient(config: HestiaClientConfig): HestiaClient {
  return new HestiaClient(config);
}

/** Convenience generator for a tool-call-spec's input hash (Phase 1 placeholder). */
export function actionNonce(): string {
  return randomUUID();
}
