import { describe, expect, it } from "vitest";
import { scopeAllowedDecisions, scopeAwaitsOperator, scopeDurations, scopeEnumerable, scopeOnceOnly } from "./scope";

// #1287 part 2: the card offers exactly the rulings the daemon's decide endpoint accepts.
describe("scope decisions", () => {
  it("escalates a peer-routed request to the operator once the daemon says the window lapsed", () => {
    expect(scopeAwaitsOperator({ origin: "gate_deny", invited_peers: ["kimi-code"], decided_by_default: "peer" })).toBe(false);
    expect(scopeAwaitsOperator({ origin: "gate_deny", invited_peers: ["kimi-code"], decided_by_default: "operator" })).toBe(true);
    // an older daemon without the field: the routing rule
    expect(scopeAwaitsOperator({ origin: "gate_deny", invited_peers: ["kimi-code"] })).toBe(false);
  });
  it("takes the daemon's allowed_decisions as given", () => {
    expect(scopeAllowedDecisions({ allowed_decisions: ["once", "refuse"] })).toEqual(["once", "refuse"]);
    expect(scopeDurations({ allowed_decisions: ["once", "refuse"] })).toEqual(["once"]);
    expect(scopeDurations({ allowed_decisions: ["session", "standing", "refuse"] })).toEqual([
      "session",
      "standing",
    ]);
    expect(scopeOnceOnly({ allowed_decisions: ["once", "refuse"] })).toBe(true);
    expect(scopeOnceOnly({ allowed_decisions: ["once", "session", "standing", "refuse"] })).toBe(false);
  });

  it("falls back to the older flags when the daemon sends no allowed_decisions", () => {
    expect(scopeAllowedDecisions({ once_available: true, once_only: true })).toEqual(["once", "refuse"]);
    expect(scopeAllowedDecisions({ once_available: true })).toEqual(["once", "session", "standing", "refuse"]);
    expect(scopeAllowedDecisions({ once_available: false })).toEqual(["session", "standing", "refuse"]);
    expect(scopeEnumerable({ once_only: true })).toBe(false);
    expect(scopeEnumerable({ enumerable: true, once_only: true })).toBe(true);
  });
});
