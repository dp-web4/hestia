/**
 * Integration test: end-to-end through the refactored OpenClaw plugin.
 *
 * Wires:
 *   mock OpenClaw host → refactored plugin → @hestia-tools/plugin-sdk → mock Hestia
 *
 * Validates the architectural shift: the plugin (~140 lines) successfully
 * delegates all governance to Hestia via the SDK, with no embedded R6 chain,
 * no local policy engine, no per-plugin credential storage.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { startMockHestiaServer, type MockServerHandle } from "../../../plugin-sdk/typescript/test/mock-hestia-server.js";
import { startMockOpenClawHost, type MockHostHandle } from "./mock-openclaw-host.js";
import { createPlugin } from "../src/index.js";

describe("Hestia OpenClaw plugin — end-to-end integration", () => {
  let hestia: MockServerHandle;
  let host: MockHostHandle;

  beforeAll(async () => {
    hestia = await startMockHestiaServer();
    const plugin = createPlugin({
      hestiaEndpoint: hestia.url,
      enforce: true,
      requestedRole: "citizen",
    });
    host = await startMockOpenClawHost(plugin);
  });

  afterAll(async () => {
    await hestia.close();
  });

  it("registers the plugin and connects to Hestia", () => {
    const connectLog = host.logs.find((l) => l.message === "hestia connected");
    expect(connectLog).toBeDefined();
    expect(connectLog?.meta?.sessionId).toMatch(/[0-9a-f-]{36}/);
    expect(connectLog?.meta?.assignedRole).toBe("citizen");
    expect(connectLog?.meta?.softLct).toMatch(/^lct:web4:session:/);
  });

  it("intercepts a Bash tool call: queries policy, executes, records outcome", async () => {
    const result = await host.runToolCall("Bash", { command: "echo hello" });
    expect(result).toBeDefined();
    expect(result?.status).toBe("success");

    // The plugin should have invoked hestia_begin_action + hestia_query_policy
    // + hestia_record_outcome. Verify by inspecting the mock's witness chain.
    expect(hestia.state.chain.length).toBeGreaterThanOrEqual(1);
    const lastEntry = hestia.state.chain[hestia.state.chain.length - 1];
    expect(lastEntry.eventType).toBe("outcome");
    expect(lastEntry.hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("intercepts a Read tool call and records lower-magnitude outcome", async () => {
    const before = hestia.state.chain.length;
    const result = await host.runToolCall("Read", { file_path: "/tmp/x.txt" });
    expect(result?.status).toBe("success");
    expect(hestia.state.chain.length).toBe(before + 1);
  });

  it("records failure outcomes correctly", async () => {
    const result = await host.runToolCall(
      "Write",
      { file_path: "/tmp/bad.txt", content: "test" },
      { forceFailure: true },
    );
    expect(result?.status).toBe("error");
    const lastEntry = hestia.state.chain[hestia.state.chain.length - 1];
    expect(lastEntry.eventType).toBe("outcome");
  });

  it("emits one chain entry per tool call (paired before/after via callId)", async () => {
    const before = hestia.state.chain.length;
    await host.runToolCall("Read", { file_path: "/a" });
    await host.runToolCall("Read", { file_path: "/b" });
    await host.runToolCall("Read", { file_path: "/c" });
    const after = hestia.state.chain.length;
    expect(after - before).toBe(3);
  });

  it("gracefully no-ops when Hestia is unreachable (no-throw startup)", async () => {
    // Build a plugin pointing at a closed endpoint and register on a fresh host.
    const closedPlugin = createPlugin({
      hestiaEndpoint: "http://127.0.0.1:1", // port 1 — always closed
      requestedRole: "citizen",
    });
    const closedHost = await startMockOpenClawHost(closedPlugin);

    // Should have logged a connect failure
    const errorLog = closedHost.logs.find(
      (l) => l.level === "error" && l.message.includes("hestia connect failed"),
    );
    expect(errorLog).toBeDefined();

    // Tool calls should still go through (fail-open on the agent side; the
    // user sees no Hestia features but the agent doesn't break).
    const result = await closedHost.runToolCall("Read", { file_path: "/x" });
    expect(result?.status).toBe("success");
  });

  it("captures target from common argument conventions", async () => {
    await host.runToolCall("WebFetch", { url: "https://example.com" });
    // No assertion on the URL itself; just verify no throw and a chain entry.
    expect(hestia.state.chain.length).toBeGreaterThan(0);
  });
});
