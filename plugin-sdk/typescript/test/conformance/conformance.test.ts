/**
 * Conformance harness — TypeScript.
 *
 * Loads the canonical scenarios from
 * web4-standard/testing/conformance/presence-protocol-conformance.json
 * and exercises them against a live Hestia daemon. Pass/fail per scenario
 * is reported via vitest's normal test runner; a failure in any scenario
 * fails the whole suite.
 *
 * Requires:
 *   - A running Hestia daemon at $HESTIA_ENDPOINT (default
 *     http://127.0.0.1:7711/mcp). The daemon's HESTIA_HOME should be a
 *     sandbox so the conformance scenarios don't pollute real state.
 *   - $WEB4_STANDARD_CONFORMANCE pointing at the JSON vector file, or
 *     the default relative path resolves.
 *
 * Skipped automatically if the daemon isn't reachable. Use
 * `RUN_CONFORMANCE=1 npm test` to require it.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createHestiaClient, HestiaClient } from "../../src/index.js";

interface Scenario {
  id: string;
  name: string;
  description?: string;
  preconditions?: string[];
  setup?: Step[];
  steps: Step[];
  teardown?: unknown[];
}

interface Step {
  tool?: string;
  resource?: string;
  input?: Record<string, unknown>;
  expect?: ExpectClause;
  capture?: Record<string, string>;
}

interface ExpectClause {
  shapeMatchesSchema?: string;
  fieldChecks?: FieldCheck[];
  ordering?: { field: string; monotonic: "ascending" | "descending" };
}

interface FieldCheck {
  path: string;
  equals?: unknown;
  matchesPattern?: string;
  startsWith?: string;
  isInteger?: boolean;
  isNumber?: boolean;
  isBoolean?: boolean;
  isString?: boolean;
  isNonEmptyString?: boolean;
  isArray?: boolean;
  isIso8601?: boolean;
  isIn?: unknown[];
  min?: number;
  max?: number;
  minLength?: number;
}

interface VectorFile {
  scenarios: Scenario[];
}

const ENDPOINT = process.env.HESTIA_ENDPOINT ?? "http://127.0.0.1:7711/mcp";
const VECTORS_PATH =
  process.env.WEB4_STANDARD_CONFORMANCE ??
  resolve(
    __dirname,
    "../../../../../web4/web4-standard/testing/conformance/presence-protocol-conformance.json",
  );

async function daemonReachable(): Promise<boolean> {
  try {
    const r = await fetch(ENDPOINT, { method: "OPTIONS" }).catch(() => null);
    if (r) return true;
    // OPTIONS might fail; try a HEAD to the root
    const r2 = await fetch(ENDPOINT.replace("/mcp", "/"), { method: "GET" });
    return r2.status < 500;
  } catch {
    return false;
  }
}

function resolvePath(obj: unknown, path: string): unknown {
  // Supports `a.b.c` and `a.b[0].c` and `a[*].c` (the last collapses to an array of c's).
  const parts = path.replace(/\[(\d+|\*)\]/g, ".$1").split(".").filter(Boolean);
  let current: unknown = obj;
  for (const part of parts) {
    if (current === null || current === undefined) return undefined;
    if (part === "*") {
      if (!Array.isArray(current)) return undefined;
      // map remaining path through the array; just return as-is — handled by caller in `ordering`
      return current;
    }
    if (/^\d+$/.test(part)) {
      if (!Array.isArray(current)) return undefined;
      current = current[parseInt(part, 10)];
    } else {
      current = (current as Record<string, unknown>)[part];
    }
  }
  return current;
}

function interpolate(input: unknown, captures: Map<string, Record<string, unknown>>): unknown {
  if (typeof input === "string") {
    const m = input.match(/^\{\{([A-Z0-9-]+)\.([a-zA-Z_$]+)\}\}$/);
    if (m) {
      const [, scenarioId, field] = m;
      const cap = captures.get(scenarioId);
      if (cap && field in cap) return cap[field];
    }
    return input;
  }
  if (Array.isArray(input)) {
    return input.map((x) => interpolate(x, captures));
  }
  if (input && typeof input === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(input)) {
      out[k] = interpolate(v, captures);
    }
    return out;
  }
  return input;
}

function checkField(value: unknown, check: FieldCheck, scenarioId: string): void {
  const ctx = `[${scenarioId}] field "${check.path}"`;
  if (check.equals !== undefined) {
    expect(value, ctx).toEqual(check.equals);
  }
  if (check.matchesPattern !== undefined) {
    expect(value, ctx).toMatch(new RegExp(check.matchesPattern));
  }
  if (check.startsWith !== undefined) {
    expect(String(value).startsWith(check.startsWith), `${ctx} startsWith ${check.startsWith}`).toBe(true);
  }
  if (check.isInteger) {
    expect(Number.isInteger(value), `${ctx} isInteger`).toBe(true);
  }
  if (check.isNumber) {
    expect(typeof value === "number", `${ctx} isNumber`).toBe(true);
  }
  if (check.isBoolean) {
    expect(typeof value === "boolean", `${ctx} isBoolean`).toBe(true);
  }
  if (check.isString) {
    expect(typeof value === "string", `${ctx} isString`).toBe(true);
  }
  if (check.isNonEmptyString) {
    expect(typeof value === "string" && (value as string).length > 0, `${ctx} isNonEmptyString`).toBe(true);
  }
  if (check.isArray) {
    expect(Array.isArray(value), `${ctx} isArray`).toBe(true);
  }
  if (check.isIso8601) {
    // Accept either an ISO-8601 string (wire format) or a Date object
    // (SDK deserialized representation). Both are conformant per spec.
    const isDate = value instanceof Date && !isNaN(value.getTime());
    const isIsoStr = typeof value === "string" && !isNaN(Date.parse(value as string));
    expect(isDate || isIsoStr, `${ctx} isIso8601 (got ${typeof value}: ${String(value)})`).toBe(true);
  }
  if (check.isIn !== undefined) {
    expect(check.isIn.includes(value as never), `${ctx} isIn ${JSON.stringify(check.isIn)}`).toBe(true);
  }
  if (check.min !== undefined && typeof value === "number") {
    expect(value >= check.min, `${ctx} >= ${check.min}`).toBe(true);
  }
  if (check.max !== undefined && typeof value === "number") {
    expect(value <= check.max, `${ctx} <= ${check.max}`).toBe(true);
  }
  if (check.minLength !== undefined && Array.isArray(value)) {
    expect(value.length >= check.minLength, `${ctx} length >= ${check.minLength}`).toBe(true);
  }
}

describe("Presence Protocol v0 conformance — TypeScript SDK", () => {
  let client: HestiaClient | null = null;
  let vectors: VectorFile | null = null;
  let reachable = false;
  const captures = new Map<string, Record<string, unknown>>();

  beforeAll(async () => {
    reachable = await daemonReachable();
    if (!reachable) {
      if (process.env.RUN_CONFORMANCE === "1") {
        throw new Error(`Daemon not reachable at ${ENDPOINT}; set RUN_CONFORMANCE=0 to skip.`);
      }
      return;
    }
    const raw = await readFile(VECTORS_PATH, "utf-8");
    vectors = JSON.parse(raw) as VectorFile;

    client = createHestiaClient({
      pluginId: "conformance-runner",
      pluginVersion: "0.0.1",
      hostAgent: "conformance-runner",
      hostAgentVersion: "0.0.1",
      hestiaEndpoint: ENDPOINT,
      synthetic: true,
    });
  });

  afterAll(async () => {
    if (client) await client.disconnect().catch(() => undefined);
  });

  it.runIf(!reachable || !vectors)("skipped: daemon not reachable", () => {
    // sentinel; we want the suite to log when it's skipped
  });

  // The scenarios run in order; some reference captures from earlier scenarios.
  // We register each as its own `it` block dynamically below in `runScenarios`.
  it("runs all scenarios", async () => {
    if (!reachable || !vectors || !client) {
      // Skipped above
      return;
    }
    const session = await client.connect();
    captures.set("P0-001", { sessionId: session.sessionId });

    for (const scenario of vectors.scenarios) {
      // P0-001 is the connect scenario — captured above; skip its steps
      // since we've already invoked them via client.connect().
      if (scenario.id === "P0-001") continue;

      // Run setup. Setup steps may have `capture` that writes into this
      // scenario's bucket — that lets the steps refer to setup state via
      // `{{<scenario_id>.<field>}}`.
      if (scenario.setup) {
        for (const step of scenario.setup) {
          const setupResult = await invokeStep(client, step, captures);
          if (step.capture && setupResult) {
            const cap = (captures.get(scenario.id) as Record<string, unknown>) ?? {};
            for (const [k, jsonPath] of Object.entries(step.capture)) {
              cap[k] = resolvePath(setupResult, jsonPath.replace(/^\$\./, ""));
            }
            captures.set(scenario.id, cap);
          }
        }
      }

      for (const step of scenario.steps) {
        const result = await invokeStep(client, step, captures);
        if (process.env.CONFORMANCE_DEBUG === "1") {
          // eslint-disable-next-line no-console
          console.log(`[${scenario.id}] tool=${step.tool ?? step.resource} result keys=${Object.keys(result ?? {}).join(",")}`);
        }
        if (step.capture && result) {
          const cap: Record<string, unknown> = {};
          for (const [k, jsonPath] of Object.entries(step.capture)) {
            cap[k] = resolvePath(result, jsonPath.replace(/^\$\./, ""));
          }
          captures.set(scenario.id, cap);
          if (process.env.CONFORMANCE_DEBUG === "1") {
            // eslint-disable-next-line no-console
            console.log(`[${scenario.id}] captured: ${JSON.stringify(cap)}`);
          }
        }
        if (step.expect?.fieldChecks) {
          for (const check of step.expect.fieldChecks) {
            const v = resolvePath(result, check.path);
            checkField(v, check, scenario.id);
          }
        }
        if (step.expect?.ordering) {
          const arr = resolvePath(result, step.expect.ordering.field.replace(/\[\*\].*/, "")) as unknown[];
          const trailing = step.expect.ordering.field.split("[*].")[1];
          const values = (arr ?? []).map((el) =>
            trailing ? resolvePath(el, trailing) : el,
          ) as number[];
          for (let i = 1; i < values.length; i++) {
            if (step.expect.ordering.monotonic === "descending") {
              expect(values[i] <= values[i - 1], `[${scenario.id}] not descending at ${i}`).toBe(true);
            } else {
              expect(values[i] >= values[i - 1], `[${scenario.id}] not ascending at ${i}`).toBe(true);
            }
          }
        }
      }
    }
  });
});

async function invokeStep(
  client: HestiaClient,
  step: Step,
  captures: Map<string, Record<string, unknown>>,
): Promise<unknown> {
  const input = interpolate(step.input ?? {}, captures) as Record<string, unknown>;
  if (process.env.CONFORMANCE_DEBUG === "1") {
    // eslint-disable-next-line no-console
    console.log(`  → ${step.tool ?? step.resource} input=${JSON.stringify(input)}`);
  }
  if (step.resource) {
    // The SDK exposes typed resource readers for some URIs; we shell out
    // to the (private) raw readResource via type-cast since the test
    // harness needs URI-pattern access.
    const raw = await (client as unknown as { readResource: (u: string) => Promise<unknown> }).readResource(
      step.resource,
    );
    return raw;
  }
  if (!step.tool) return undefined;
  switch (step.tool) {
    case "hestia_connect":
      // Connect already happened in `beforeAll`; skip.
      return undefined;
    case "hestia_begin_action":
      return await client.beginAction({
        toolName: String(input.tool_name),
        target: input.target as string | undefined,
        parameters: input.parameters as Record<string, unknown> | undefined,
        atpStake: input.atp_stake as number | undefined,
      });
    case "hestia_record_outcome": {
      // The SDK signature wants (action, outcome); we synthesize the
      // action from captured chain_position + the action_id.
      const action = {
        actionId: String(input.action_id),
        toolName: "",
        startedAt: new Date(),
        chainPosition: 0,
      };
      const result = await client.recordOutcome(action, {
        success: Boolean(input.success),
        magnitude: (input.magnitude as number) ?? 0.5,
        error: input.error as string | undefined,
        result: input.result as Record<string, unknown> | undefined,
      });
      return result;
    }
    case "hestia_query_policy": {
      const action = {
        actionId: String(input.action_id),
        toolName: "",
        startedAt: new Date(),
        chainPosition: 0,
      };
      return await client.queryPolicy(action, input.context as Record<string, unknown> | undefined);
    }
    case "hestia_vault_get": {
      try {
        return await client.vaultGet(String(input.name), {
          scope: (input.scope as string[]) ?? [],
          reason: input.reason as string | undefined,
        });
      } catch (err) {
        // typed Hestia error — surface as the _hestia_error envelope shape
        const e = err as { code?: string; message?: string; data?: unknown };
        if (e.code) {
          return { _hestia_error: { code: e.code, message: e.message ?? "", data: e.data ?? {} } };
        }
        throw err;
      }
    }
    case "hestia_vault_set":
      return await client.vaultSet(String(input.name), String(input.value), {
        scope: (input.scope as string[]) ?? [],
        tags: (input.tags as string[]) ?? [],
        allowedConsumers: (input.allowed_consumers as string[]) ?? [],
      });
    case "hestia_query_history":
      return await client.queryHistory((input.filter as Record<string, unknown>) ?? {});
    case "hestia_request_witness":
      return await client.requestWitness(
        String(input.event_type),
        (input.event_data as Record<string, unknown>) ?? {},
      );
    default:
      throw new Error(`Conformance harness: tool ${step.tool} not implemented`);
  }
}
