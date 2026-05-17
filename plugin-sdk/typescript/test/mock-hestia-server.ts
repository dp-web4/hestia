/**
 * Mock Hestia MCP server for SDK testing.
 *
 * Implements just enough of the Hestia MCP surface (ADR-0005) to exercise
 * the SDK end-to-end without needing the real Rust core. Not for
 * production — for tests only.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import {
  CallToolRequestSchema,
  ReadResourceRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  McpError,
  ErrorCode,
} from "@modelcontextprotocol/sdk/types.js";
import express from "express";
import { randomUUID, createHash } from "node:crypto";
import type { Server as HttpServer } from "node:http";

interface MockState {
  sessions: Map<
    string,
    { pluginId: string; assignedRole: string; softLct: string }
  >;
  actions: Map<
    string,
    { sessionId: string; toolName: string; chainPosition: number }
  >;
  vault: Map<
    string,
    { value: string; scope: string[]; allowedConsumers: string[] }
  >;
  chain: Array<{ hash: string; prevHash: string; eventType: string; chainPosition: number }>;
}

export interface MockServerHandle {
  /** Endpoint URL plugins should connect to. */
  url: string;
  /** Shut down the mock cleanly. */
  close: () => Promise<void>;
  /** The mutable mock state — tests can pre-populate the vault, etc. */
  state: MockState;
}

export async function startMockHestiaServer(port = 0): Promise<MockServerHandle> {
  const state: MockState = {
    sessions: new Map(),
    actions: new Map(),
    vault: new Map(),
    chain: [],
  };

  const server = new Server(
    { name: "hestia-mock", version: "0.0.2" },
    { capabilities: { tools: {}, resources: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      { name: "hestia_connect", description: "Establish plugin session", inputSchema: { type: "object" } },
      { name: "hestia_begin_action", description: "Begin R6 action", inputSchema: { type: "object" } },
      { name: "hestia_record_outcome", description: "Record outcome", inputSchema: { type: "object" } },
      { name: "hestia_query_policy", description: "Query policy", inputSchema: { type: "object" } },
      { name: "hestia_vault_get", description: "Get credential", inputSchema: { type: "object" } },
      { name: "hestia_vault_set", description: "Set credential", inputSchema: { type: "object" } },
      { name: "hestia_query_history", description: "Query witness chain", inputSchema: { type: "object" } },
      { name: "hestia_request_witness", description: "Custom witness event", inputSchema: { type: "object" } },
    ],
  }));

  server.setRequestHandler(ListResourcesRequestSchema, async () => ({
    resources: [
      { uri: "hestia://context/shared", name: "shared context", mimeType: "application/json" },
      { uri: "hestia://session/own", name: "own session", mimeType: "application/json" },
    ],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const args = (request.params.arguments ?? {}) as Record<string, unknown>;

    const respond = (data: unknown) => ({
      content: [{ type: "text" as const, text: JSON.stringify(data) }],
      structuredContent: data,
    });

    switch (request.params.name) {
      case "hestia_connect": {
        const sessionId = randomUUID();
        const softLct = `lct:web4:session:${createHash("sha256")
          .update(sessionId)
          .digest("hex")
          .slice(0, 16)}`;
        const pluginId = (args.plugin_id as string) ?? "unknown";
        const assignedRole = (args.requested_role as string) ?? "citizen";
        state.sessions.set(sessionId, { pluginId, assignedRole, softLct });
        return respond({ sessionId, softLct, assignedRole, protocolVersion: 0 });
      }

      case "hestia_begin_action": {
        const actionId = randomUUID();
        const chainPosition = state.chain.length;
        const sessionId = [...state.sessions.keys()][0] ?? "anon"; // mock — first session
        state.actions.set(actionId, {
          sessionId,
          toolName: args.tool_name as string,
          chainPosition,
        });
        return respond({
          actionId,
          startedAt: new Date().toISOString(),
          chainPosition,
        });
      }

      case "hestia_record_outcome": {
        const action = state.actions.get(args.action_id as string);
        if (!action) {
          throw new McpError(
            ErrorCode.InvalidParams,
            `Action ${args.action_id} not found`,
            { code: "hestia.action_not_found", actionId: args.action_id },
          );
        }
        const prev = state.chain[state.chain.length - 1]?.hash ?? "0".repeat(64);
        const hash = createHash("sha256")
          .update(`${prev}|${action.toolName}|${args.success}|${args.magnitude}`)
          .digest("hex");
        state.chain.push({
          hash,
          prevHash: prev,
          eventType: "outcome",
          chainPosition: state.chain.length,
        });
        return respond({
          witnessEntryHash: hash,
          updatedTrustState: {
            entityId: "plugin:smoke",
            t3: { talent: 0.55, training: 0.6, temperament: 0.5 },
            v3: { valuation: 0.5, veracity: 0.55, validity: 0.5 },
            level: "medium",
            actionCount: state.chain.length,
            successCount: state.chain.length,
            successRate: 1.0,
            daysSinceLast: 0,
          },
        });
      }

      case "hestia_query_policy": {
        return respond({
          decision: "allow",
          reason: "mock: default-allow",
          enforced: true,
        });
      }

      case "hestia_vault_get": {
        const name = args.name as string;
        const entry = state.vault.get(name);
        if (!entry) {
          throw new McpError(
            ErrorCode.InvalidParams,
            `Credential '${name}' not found`,
            { code: "hestia.vault_not_found", name },
          );
        }
        return respond({ value: entry.value });
      }

      case "hestia_vault_set": {
        const name = args.name as string;
        state.vault.set(name, {
          value: args.value as string,
          scope: (args.scope as string[]) ?? [],
          allowedConsumers: (args.allowed_consumers as string[]) ?? [],
        });
        return respond({ stored: true, entryId: randomUUID() });
      }

      case "hestia_query_history": {
        return respond({
          entries: state.chain.map((e) => ({
            hash: e.hash,
            prevHash: e.prevHash,
            timestamp: new Date().toISOString(),
            eventType: e.eventType,
            eventData: {},
            signerLct: "lct:web4:mock:sovereign",
            chainPosition: e.chainPosition,
          })),
          hasMore: false,
        });
      }

      case "hestia_request_witness": {
        const prev = state.chain[state.chain.length - 1]?.hash ?? "0".repeat(64);
        const hash = createHash("sha256")
          .update(`${prev}|${args.event_type}|${JSON.stringify(args.event_data)}`)
          .digest("hex");
        state.chain.push({
          hash,
          prevHash: prev,
          eventType: (args.event_type as string) ?? "custom",
          chainPosition: state.chain.length,
        });
        return respond({ witnessEntryHash: hash });
      }

      default:
        throw new Error(`Unknown tool: ${request.params.name}`);
    }
  });

  server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
    const uri = request.params.uri;
    if (uri === "hestia://context/shared") {
      return {
        contents: [
          {
            uri,
            mimeType: "application/json",
            text: JSON.stringify({ currentProject: "hestia-smoke-test" }),
          },
        ],
      };
    }
    if (uri.startsWith("hestia://society/trust/")) {
      const pluginId = uri.split("/").pop() ?? "";
      return {
        contents: [
          {
            uri,
            mimeType: "application/json",
            text: JSON.stringify({
              entityId: `plugin:${pluginId}`,
              t3: { talent: 0.5, training: 0.5, temperament: 0.5 },
              v3: { valuation: 0.5, veracity: 0.5, validity: 0.5 },
              level: "medium",
              actionCount: 0,
              successCount: 0,
              successRate: 0.5,
              daysSinceLast: 0,
            }),
          },
        ],
      };
    }
    return { contents: [] };
  });

  // HTTP transport — stateless mode (each request independent).
  // For tests we don't need session persistence; each call to the mock
  // gets a fresh transport. State lives in the shared `state` object
  // captured by the request handlers above.
  const app = express();
  app.use(express.json());

  app.post("/mcp", async (req, res) => {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // stateless
      enableJsonResponse: true,
    });
    await server.connect(transport);
    try {
      await transport.handleRequest(req, res, req.body);
    } finally {
      transport.close().catch(() => undefined);
    }
  });

  app.get("/mcp", (_req, res) => {
    // GET is for the optional SSE notification stream. Stateless mode
    // doesn't support this; respond with 405.
    res.status(405).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Method Not Allowed (stateless mock)" },
      id: null,
    });
  });

  return new Promise<MockServerHandle>((resolve, reject) => {
    const httpServer: HttpServer = app.listen(port, "127.0.0.1", () => {
      const addr = httpServer.address();
      if (!addr || typeof addr === "string") {
        reject(new Error("failed to bind mock server"));
        return;
      }
      resolve({
        url: `http://127.0.0.1:${addr.port}/mcp`,
        state,
        close: () =>
          new Promise<void>((resolveClose) => {
            httpServer.close(() => resolveClose());
          }),
      });
    });
  });
}
