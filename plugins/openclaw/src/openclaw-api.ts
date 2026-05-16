/**
 * Minimal type definitions for the OpenClaw (formerly Moltbot) plugin API.
 *
 * Mirrors the surface the original `moltbot/extensions/web4-governance` plugin
 * consumed. We define our own copy here rather than importing from openclaw
 * itself so the plugin can be developed and tested independently of the
 * OpenClaw codebase.
 *
 * When OpenClaw is actually present, the real `clawdbot/plugin-sdk` import
 * substitutes structurally for these types — they're compatible by shape.
 */

export interface OpenClawLogger {
  info(message: string, meta?: Record<string, unknown>): void;
  warn(message: string, meta?: Record<string, unknown>): void;
  error(message: string, meta?: Record<string, unknown>): void;
  debug(message: string, meta?: Record<string, unknown>): void;
}

export interface ToolCallEvent {
  /** Unique per tool invocation */
  callId: string;
  /** Tool name (e.g. "Bash", "Write", "Read", "WebFetch") */
  toolName: string;
  /** Arbitrary tool-specific arguments */
  arguments: Record<string, unknown>;
  /** ISO-8601 timestamp the host began the call */
  startedAt: string;
}

export interface ToolCallContext {
  sessionId: string;
  /** Resolved target for path-style tools (file path, URL, etc.) */
  target?: string;
  /** Host-provided cancel signal */
  signal?: AbortSignal;
}

export interface ToolCallResult {
  callId: string;
  toolName: string;
  status: "success" | "error" | "blocked";
  /** ISO-8601 timestamp */
  finishedAt: string;
  /** Optional structured output */
  output?: unknown;
  /** Error message if status=error */
  errorMessage?: string;
  /** Duration in ms */
  durationMs: number;
}

/**
 * Pre-tool-call hook return value:
 *   - `undefined` or `{ proceed: true }` — let the call execute
 *   - `{ proceed: false, reason?: string }` — block the call
 */
export type BeforeToolCallReturn =
  | undefined
  | { proceed: true }
  | { proceed: false; reason?: string };

export type BeforeToolCallHandler = (
  event: ToolCallEvent,
  ctx: ToolCallContext,
) => Promise<BeforeToolCallReturn> | BeforeToolCallReturn;

export type AfterToolCallHandler = (
  result: ToolCallResult,
  ctx: ToolCallContext,
) => Promise<void> | void;

export interface OpenClawPluginApi {
  /** Plugin-level config provided by the user's openclaw config file */
  pluginConfig?: unknown;
  /** Host-provided logger scoped to this plugin */
  logger: OpenClawLogger;
  /** Subscribe to the typed before/after tool-call hooks */
  on(event: "before_tool_call", handler: BeforeToolCallHandler): void;
  on(event: "after_tool_call", handler: AfterToolCallHandler): void;
}

export interface OpenClawPlugin {
  name: string;
  version: string;
  register(api: OpenClawPluginApi): void | Promise<void>;
}
