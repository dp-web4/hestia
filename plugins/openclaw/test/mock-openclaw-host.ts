/**
 * Mock OpenClaw plugin host for testing the refactored Hestia plugin.
 *
 * Implements just enough of the OpenClaw plugin API surface (register +
 * on() for before/after tool-call hooks) to drive the plugin through its
 * lifecycle in tests.
 */

import { randomUUID } from "node:crypto";
import type {
  AfterToolCallHandler,
  BeforeToolCallHandler,
  OpenClawPluginApi,
  OpenClawPlugin,
  ToolCallEvent,
  ToolCallResult,
} from "../src/openclaw-api.js";

export interface MockHostHandle {
  /**
   * Simulate a tool call going through the OpenClaw lifecycle:
   * 1. Invoke before-hooks. If any return proceed:false, block.
   * 2. If allowed, the caller can do the actual work; we synthesize a result.
   * 3. Invoke after-hooks with the result.
   *
   * Returns the synthesized ToolCallResult, or undefined if blocked.
   */
  runToolCall(
    toolName: string,
    args: Record<string, unknown>,
    options?: {
      target?: string;
      forceFailure?: boolean;
      forceDurationMs?: number;
    },
  ): Promise<ToolCallResult | undefined>;

  /** Capture of all log entries the plugin emitted. */
  logs: Array<{ level: string; message: string; meta?: Record<string, unknown> }>;
}

export async function startMockOpenClawHost(
  plugin: OpenClawPlugin,
  pluginConfig?: unknown,
): Promise<MockHostHandle> {
  const logs: MockHostHandle["logs"] = [];
  const beforeHooks: BeforeToolCallHandler[] = [];
  const afterHooks: AfterToolCallHandler[] = [];

  const api: OpenClawPluginApi = {
    pluginConfig,
    logger: {
      info: (message, meta) => logs.push({ level: "info", message, meta }),
      warn: (message, meta) => logs.push({ level: "warn", message, meta }),
      error: (message, meta) => logs.push({ level: "error", message, meta }),
      debug: (message, meta) => logs.push({ level: "debug", message, meta }),
    },
    on(event: "before_tool_call" | "after_tool_call", handler: BeforeToolCallHandler | AfterToolCallHandler) {
      if (event === "before_tool_call") {
        beforeHooks.push(handler as BeforeToolCallHandler);
      } else {
        afterHooks.push(handler as AfterToolCallHandler);
      }
    },
  };

  await plugin.register(api);

  return {
    logs,
    async runToolCall(toolName, args, options = {}) {
      const callId = randomUUID();
      const sessionId = "mock-session";
      const event: ToolCallEvent = {
        callId,
        toolName,
        arguments: args,
        startedAt: new Date().toISOString(),
      };
      const ctx = { sessionId, target: options.target };

      // Run before-hooks
      for (const hook of beforeHooks) {
        const ret = await hook(event, ctx);
        if (ret && ret.proceed === false) {
          // Blocked — emit a "blocked" result to after-hooks then return undefined
          const blockedResult: ToolCallResult = {
            callId,
            toolName,
            status: "blocked",
            finishedAt: new Date().toISOString(),
            errorMessage: ret.reason ?? "blocked by before-hook",
            durationMs: 0,
          };
          for (const ah of afterHooks) {
            await ah(blockedResult, ctx);
          }
          return undefined;
        }
      }

      // Synthesize execution result
      const result: ToolCallResult = {
        callId,
        toolName,
        status: options.forceFailure ? "error" : "success",
        finishedAt: new Date().toISOString(),
        output: { mock: true },
        errorMessage: options.forceFailure ? "synthesized failure" : undefined,
        durationMs: options.forceDurationMs ?? 42,
      };
      for (const ah of afterHooks) {
        await ah(result, ctx);
      }
      return result;
    },
  };
}
