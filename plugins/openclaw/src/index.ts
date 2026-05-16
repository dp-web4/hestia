/**
 * @hestia/plugin-openclaw — Hestia plugin for OpenClaw (FKA Moltbot).
 *
 * Refactor of `moltbot/extensions/web4-governance` (6,511 lines incl. tests)
 * into a thin observer (~140 lines incl. comments) that emits R6/R7 records
 * to the user's central Hestia instance via @hestia-tools/plugin-sdk.
 *
 * What this plugin does:
 *   1. On OpenClaw startup, connect to the user's Hestia daemon.
 *   2. On every tool call, ask Hestia for a policy decision (allow/deny/warn).
 *   3. If allowed, let OpenClaw execute the tool; emit the outcome record back
 *      to Hestia for the witness chain + trust state update.
 *   4. If denied, block the tool call and surface the reason.
 *
 * What this plugin does NOT do (deliberate — these live in Hestia central):
 *   - Maintain its own R6 chain (Hestia owns the witness chain)
 *   - Run its own policy engine (Hestia evaluates; this plugin queries)
 *   - Store credentials (use `hestia.vaultGet` when needed)
 *   - Manage session state (Hestia issues the Soft LCT on connect)
 *
 * See docs/PLUGIN_AUTHORING_GUIDE.md in the Hestia repo for the contract.
 */

import {
  createHestiaClient,
  HestiaClient,
  PolicyDeniedError,
  type Outcome,
  type R6Action,
} from "@hestia-tools/plugin-sdk";
import type {
  AfterToolCallHandler,
  BeforeToolCallHandler,
  OpenClawPluginApi,
  OpenClawPlugin,
} from "./openclaw-api.js";

/** Maps a tool-call event onto a magnitude in [0..1] for trust scoring. */
function magnitudeFor(toolName: string): number {
  // Higher magnitudes = more consequential outcomes. Plugin authors can
  // tune this; Hestia uses it as a weight on T3/V3 updates.
  switch (toolName) {
    case "Bash":
    case "Shell":
      return 0.8; // arbitrary code execution
    case "Write":
    case "Edit":
    case "MultiEdit":
      return 0.6; // mutating filesystem
    case "WebFetch":
    case "WebSearch":
      return 0.4; // network reads
    case "Read":
    case "Glob":
    case "Grep":
      return 0.2; // read-only filesystem
    default:
      return 0.4;
  }
}

/** Extracts a target (file path / URL / etc.) from arbitrary tool arguments. */
function extractTarget(toolName: string, args: Record<string, unknown>): string | undefined {
  // Common conventions across tool families.
  if (typeof args.file_path === "string") return args.file_path;
  if (typeof args.path === "string") return args.path;
  if (typeof args.url === "string") return args.url;
  if (typeof args.command === "string") return args.command.split(/\s+/)[0]; // first token
  return undefined;
}

export interface PluginOptions {
  /** Override Hestia endpoint discovery */
  hestiaEndpoint?: string;
  /** Society role this plugin requests on connect. Default: "citizen". */
  requestedRole?: string;
  /** Enforce policy decisions (default true). When false, deny → warn-only. */
  enforce?: boolean;
}

/**
 * Build the OpenClaw plugin. Returns the standard `{ name, version, register }`
 * shape OpenClaw expects.
 */
export function createPlugin(options: PluginOptions = {}): OpenClawPlugin {
  return {
    name: "web4-governance",
    version: "0.0.1",
    async register(api: OpenClawPluginApi) {
      const config = (api.pluginConfig ?? {}) as PluginOptions;
      const enforce = config.enforce ?? options.enforce ?? true;
      const hestia: HestiaClient = createHestiaClient({
        pluginId: "openclaw",
        pluginVersion: "0.0.1",
        hostAgent: "openclaw",
        requestedRole: config.requestedRole ?? options.requestedRole ?? "citizen",
        hestiaEndpoint: config.hestiaEndpoint ?? options.hestiaEndpoint,
      });

      try {
        const result = await hestia.connect();
        api.logger.info("hestia connected", {
          sessionId: result.sessionId,
          assignedRole: result.assignedRole,
          softLct: result.softLct,
        });
      } catch (err) {
        api.logger.error("hestia connect failed; plugin disabled for this session", {
          error: String(err),
        });
        return; // gracefully no-op if Hestia isn't running
      }

      // Track in-flight actions by tool-call ID so we can pair before/after.
      const pending = new Map<string, R6Action>();

      const beforeHook: BeforeToolCallHandler = async (event, ctx) => {
        try {
          const action = await hestia.beginAction({
            toolName: event.toolName,
            target: ctx.target ?? extractTarget(event.toolName, event.arguments),
            parameters: event.arguments,
            atpStake: magnitudeFor(event.toolName) * 10, // crude ATP-from-magnitude
          });
          pending.set(event.callId, action);

          const policy = await hestia.queryPolicy(action);
          if (policy.decision === "deny" && (enforce && policy.enforced)) {
            api.logger.warn("policy denied tool call", {
              tool: event.toolName,
              reason: policy.reason,
              policyId: policy.policyId,
            });
            return { proceed: false, reason: `Hestia: ${policy.reason}` };
          }
          if (policy.decision === "warn") {
            api.logger.warn("policy warned on tool call", {
              tool: event.toolName,
              reason: policy.reason,
            });
          }
          return { proceed: true };
        } catch (err) {
          if (err instanceof PolicyDeniedError && enforce) {
            return { proceed: false, reason: err.message };
          }
          // On any other error, fail-open (Hestia issue shouldn't break the agent).
          api.logger.warn("hestia before-hook error; allowing call", { error: String(err) });
          return { proceed: true };
        }
      };

      const afterHook: AfterToolCallHandler = async (result, _ctx) => {
        const action = pending.get(result.callId);
        if (!action) {
          api.logger.debug("after-hook for unknown action; skipping", { callId: result.callId });
          return;
        }
        pending.delete(result.callId);

        const outcome: Outcome = {
          success: result.status === "success",
          magnitude: magnitudeFor(result.toolName),
          error: result.errorMessage,
          result:
            typeof result.output === "object" && result.output !== null
              ? (result.output as Record<string, unknown>)
              : { durationMs: result.durationMs },
        };

        try {
          await hestia.recordOutcome(action, outcome);
        } catch (err) {
          api.logger.warn("hestia recordOutcome failed", { error: String(err) });
        }
      };

      api.on("before_tool_call", beforeHook);
      api.on("after_tool_call", afterHook);
    },
  };
}

const plugin = createPlugin();
export default plugin;
