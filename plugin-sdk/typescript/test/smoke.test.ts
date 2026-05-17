/**
 * End-to-end smoke test for the Hestia plugin SDK.
 *
 * Spins up the mock Hestia server, runs a HestiaClient through its full
 * lifecycle, asserts the round-trip works.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createHestiaClient, HestiaClient, NotConnectedError, VaultNotFoundError } from "../src/index.js";
import { startMockHestiaServer, type MockServerHandle } from "./mock-hestia-server.js";

describe("Hestia SDK — end-to-end against mock server", () => {
  let server: MockServerHandle;
  let client: HestiaClient;

  beforeAll(async () => {
    server = await startMockHestiaServer();
    client = createHestiaClient({
      pluginId: "smoke-test-plugin",
      pluginVersion: "0.0.1",
      hostAgent: "smoke-test-agent",
      requestedRole: "citizen",
      hestiaEndpoint: server.url,
    });
  });

  afterAll(async () => {
    await client.disconnect().catch(() => undefined);
    await server.close();
  });

  it("rejects calls before connect()", async () => {
    const fresh = createHestiaClient({
      pluginId: "no-connect-test",
      hostAgent: "test",
      hestiaEndpoint: server.url,
    });
    await expect(fresh.beginAction({ toolName: "noop" })).rejects.toThrow(NotConnectedError);
  });

  it("connects and gets a Soft LCT", async () => {
    const result = await client.connect();
    expect(result.sessionId).toMatch(/[0-9a-f-]{36}/);
    expect(result.softLct).toMatch(/^lct:web4:session:/);
    expect(result.assignedRole).toBe("citizen");
    expect(result.protocolVersion).toBe(1);
  });

  it("begins an action and gets an action handle", async () => {
    const action = await client.beginAction({
      toolName: "file_write",
      target: "/tmp/smoke.txt",
      parameters: { content: "hello" },
      atpStake: 1,
    });
    expect(action.actionId).toMatch(/[0-9a-f-]{36}/);
    expect(action.toolName).toBe("file_write");
    expect(action.startedAt).toBeInstanceOf(Date);
    expect(typeof action.chainPosition).toBe("number");
  });

  it("queries policy (mock returns allow)", async () => {
    const action = await client.beginAction({ toolName: "noop" });
    const policy = await client.queryPolicy(action);
    expect(policy.decision).toBe("allow");
    expect(policy.enforced).toBe(true);
  });

  it("records an outcome and gets updated trust state", async () => {
    const action = await client.beginAction({ toolName: "file_write", target: "/tmp/x" });
    const result = await client.recordOutcome(action, { success: true, magnitude: 0.5 });
    expect(result.witnessEntryHash).toMatch(/^[0-9a-f]{64}$/);
    expect(result.updatedTrustState.level).toBe("medium");
    expect(result.updatedTrustState.actionCount).toBeGreaterThan(0);
  });

  it("stores and retrieves a credential via the vault", async () => {
    const setResult = await client.vaultSet("test_key", "secret-value-abc", {
      scope: ["test"],
      allowedConsumers: ["smoke-test-plugin"],
    });
    expect(setResult.stored).toBe(true);

    const got = await client.vaultGet("test_key", { scope: ["test"] });
    expect(got.value).toBe("secret-value-abc");
  });

  it("raises VaultNotFoundError for missing credentials", async () => {
    await expect(
      client.vaultGet("nonexistent_key", { scope: ["test"] }),
    ).rejects.toThrow(VaultNotFoundError);
  });

  it("reads the shared cross-agent context", async () => {
    const ctx = await client.getSharedContext();
    expect(ctx).toEqual({ currentProject: "hestia-smoke-test" });
  });

  it("reads its own trust state", async () => {
    const state = await client.getOwnTrustState();
    expect(state.t3).toHaveProperty("talent");
    expect(state.t3).toHaveProperty("training");
    expect(state.t3).toHaveProperty("temperament");
    expect(state.v3).toHaveProperty("valuation");
    expect(state.v3).toHaveProperty("veracity");
    expect(state.v3).toHaveProperty("validity");
    expect(state.level).toBeTypeOf("string");
  });

  it("queries the witness chain", async () => {
    const history = await client.queryHistory({ limit: 10 });
    expect(Array.isArray(history.entries)).toBe(true);
    expect(history.entries.length).toBeGreaterThan(0);
    expect(history.entries[0].hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("requests a custom witness event", async () => {
    const result = await client.requestWitness("config_change", { setting: "test", value: "x" });
    expect(result.witnessEntryHash).toMatch(/^[0-9a-f]{64}$/);
  });
});
