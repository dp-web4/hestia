import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { GateReport } from "../lib/types";

const gatesVerify = vi.fn();
const gatesRatify = vi.fn();
const gatesForget = vi.fn();
const operatorStatus = vi.fn();

vi.mock("../lib/tauri", () => ({
  gatesVerify: () => gatesVerify(),
  gatesRatify: (reason: string, expected: Record<string, string | null>, paths?: string[]) =>
    gatesRatify(reason, expected, paths),
  gatesForget: (reason: string, paths: string[]) => gatesForget(reason, paths),
  operatorStatus: () => operatorStatus(),
}));

const { Gates } = await import("./Gates");

const HOOK = "/home/dp/.claude/hooks/hestia/pre_tool_use.py";

function report(installed: string, deployed: string | null, over: Partial<GateReport> = {}): GateReport {
  return {
    status: "FINDINGS",
    findings: 1,
    discovered: 1,
    gates: [
      {
        status: "unratified",
        path: HOOK,
        discovered: true,
        deployment: deployed === null ? "no-deploy-record" : installed === deployed ? "match" : "differs",
      },
    ],
    bulk_ratify: {
      allowed: deployed !== null && installed === deployed,
      blocked_by:
        deployed !== null && installed === deployed
          ? []
          : [{ path: HOOK, plugin_id: "claude-code", deployment: deployed ? "differs" : "no-deploy-record" }],
    },
    evidence: {
      current: { [HOOK]: installed },
      deployed: deployed
        ? {
            build_id: "v0.0.4-898-g4d59496",
            head_sha: "4d59496fabc",
            installed_at_iso: "2026-09-27T19:17:39Z",
            files: { [HOOK]: deployed },
          }
        : null,
    },
    ...over,
  };
}

const signedIn = { signed_in: true, lct_id: "lct:x" };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Gates", () => {
  it("signed out: no ratify control, and says why the page is empty", async () => {
    // Every /api/* route is operator-gated. An empty table here would read as "nothing is
    // wrong"; the page must say it could not look.
    operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
    render(<Gates />);
    expect(await screen.findByText(/not the same as nothing being wrong/)).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /ratify/i })).toHaveLength(0);
    expect(gatesVerify).not.toHaveBeenCalled();
  });

  it("UNKNOWN is reported with its reason, never as clean, and cannot be ratified", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue({ status: "UNKNOWN", reason: "no gate-role hooks discovered" });
    render(<Gates />);
    expect(await screen.findByText(/no gate-role hooks discovered/)).toBeTruthy();
    expect(screen.getByText(/not a clean result/)).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /ratify/i })).toHaveLength(0);
  });

  it("says when the installed bytes are exactly what the deploy wrote", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("aaaa1111", "aaaa1111"));
    render(<Gates />);
    expect(await screen.findByText(/matches what v0.0.4-898-g4d59496 installed/)).toBeTruthy();
    expect(screen.queryByText(/DIFFERS/)).toBeNull();
  });

  it("flags bytes that changed after install, and still leaves the decision to the operator", async () => {
    // Evidence, not a verdict: the mismatch is loud, and ratify is still offered.
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("bbbb2222", "aaaa1111"));
    render(<Gates />);
    expect(await screen.findByText(/DIFFERS from what the deploy installed/)).toBeTruthy();
    // The gate can still be ratified ON ITS OWN; ratify-all is not offered over a mismatch.
    expect(screen.getByText(/the one case\s+this check exists to make you look at/)).toBeTruthy();
    expect(screen.getByRole("button", { name: `ratify ${HOOK}` })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Ratify all" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(new RegExp(`${HOOK} — differs`))).toBeTruthy();
  });

  it("will not ratify without a reason", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("aaaa1111", "aaaa1111"));
    render(<Gates />);
    (await screen.findByRole("button", { name: `ratify ${HOOK}` })).click();
    expect(await screen.findByText(/Ratifying requires a reason/)).toBeTruthy();
    expect(gatesRatify).not.toHaveBeenCalled();
  });

  it("will not ratify bytes the operator has not seen", async () => {
    // Last edit wins: ratifying replaces the expectations. If the gates moved between the
    // read and the click, stop — the operator was looking at different bytes.
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify
      .mockResolvedValueOnce(report("aaaa1111", "aaaa1111"))
      .mockResolvedValueOnce(report("cccc3333", "aaaa1111"));
    render(<Gates />);
    const input = await screen.findByPlaceholderText(/why these bytes/);
    // React listens for the native input event on controlled inputs.
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "matches the deploy");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    screen.getByRole("button", { name: `ratify ${HOOK}` }).click();

    expect(await screen.findByText(/changed since you looked\. Nothing was ratified/)).toBeTruthy();
    expect(gatesRatify).not.toHaveBeenCalled();
  });

  it("ratifies with the reason when the bytes are the ones the operator saw", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("aaaa1111", "aaaa1111"));
    gatesRatify.mockResolvedValue({ ok: true });
    render(<Gates />);
    const input = await screen.findByPlaceholderText(/why these bytes/);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "  matches deploy 4d59496  ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    screen.getByRole("button", { name: `ratify ${HOOK}` }).click();

    // The reviewed bytes travel with the reason, so the daemon can refuse if they moved.
    await waitFor(() =>
      expect(gatesRatify).toHaveBeenCalledWith("matches deploy 4d59496", { [HOOK]: "aaaa1111" }, [HOOK]),
    );
  });

  it("ratify-all is offered only when every gate is the deployed bytes, and sends no paths", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("aaaa1111", "aaaa1111"));
    gatesRatify.mockResolvedValue({ ok: true });
    render(<Gates />);
    const input = await screen.findByPlaceholderText(/why these bytes/);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "clean deploy");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const all = screen.getByRole("button", { name: "Ratify all" }) as HTMLButtonElement;
    expect(all.disabled).toBe(false);
    all.click();
    await waitFor(() => expect(gatesRatify).toHaveBeenCalledWith("clean deploy", { [HOOK]: "aaaa1111" }, undefined));
  });

  it("a per-gate ratify binds and names only that gate", async () => {
    const OTHER = "/home/dp/.codex/hooks/pre_tool_use.py";
    operatorStatus.mockResolvedValue(signedIn);
    const two = report("aaaa1111", "aaaa1111", {
      gates: [
        { status: "unratified", path: HOOK, discovered: true, deployment: "match" },
        { status: "unratified", path: OTHER, discovered: true, deployment: "not-deployed" },
      ],
    });
    two.evidence!.current[OTHER] = "eeee5555";
    gatesVerify.mockResolvedValue(two);
    gatesRatify.mockResolvedValue({ ok: true });
    render(<Gates />);
    const input = await screen.findByPlaceholderText(/why these bytes/);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "reviewed codex");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    screen.getByRole("button", { name: `ratify ${OTHER}` }).click();
    await waitFor(() => expect(gatesRatify).toHaveBeenCalledWith("reviewed codex", { [OTHER]: "eeee5555" }, [OTHER]));
  });

  it("a stale expectation is offered for forget, not ratify", async () => {
    const STALE = "/home/dp/ai-workspace/snarc/dist/hooks/handlers/pre-tool-use.js";
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(
      report("aaaa1111", "aaaa1111", {
        gates: [
          { status: "unratified", path: HOOK, discovered: true, deployment: "match" },
          { status: "verified", path: STALE, plugin_id: "retired-seat", sha256: "ssss", discovered: false, forgettable: true },
        ],
      }),
    );
    gatesForget.mockResolvedValue({ ok: true });
    render(<Gates />);
    const input = await screen.findByPlaceholderText(/why these bytes/);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "snarc is not a gate");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(screen.queryByRole("button", { name: `ratify ${STALE}` })).toBeNull();
    screen.getByRole("button", { name: `forget ${STALE}` }).click();
    await waitFor(() => expect(gatesForget).toHaveBeenCalledWith("snarc is not a gate", [STALE]));
  });

  it("a de-registered gate is badged as a possible bypass and cannot be forgotten (#1156)", async () => {
    // Its member still declares a gate; the registration was re-pointed and the ratified file
    // left on disk. Forget would delete the only record that a gate belongs there.
    const BYPASSED = "/home/dp/.claude/hooks/hestia/pre_tool_use.py";
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(
      report("aaaa1111", "aaaa1111", {
        gates: [
          { status: "unratified", path: "/other/gate.py", discovered: true, deployment: "match" },
          {
            status: "verified", path: BYPASSED, plugin_id: "claude-code", sha256: "aaaa", discovered: false,
            forgettable: false, not_registered: true,
            forget_blocked_reason: "claude-code still declares a gate; a ratified gate that is no longer registered is a bypass or a miswire",
          },
        ],
      }),
    );
    render(<Gates />);
    expect(await screen.findByText(/NOT REGISTERED — possible bypass/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: `forget ${BYPASSED}` })).toBeNull();
    expect(screen.getByText(/still declares a gate/)).toBeTruthy();
  });

  it("an old daemon without per-gate support gets no ratify controls", async () => {
    // It would ignore `paths` and ratify every gate from a per-gate click.
    operatorStatus.mockResolvedValue(signedIn);
    const old = report("aaaa1111", "aaaa1111");
    delete old.bulk_ratify;
    gatesVerify.mockResolvedValue(old);
    render(<Gates />);
    expect(await screen.findByText(/predates per-gate ratification/)).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: /ratify/i })).toHaveLength(0);
  });

  it("a not-deployed gate says so, distinct from a missing deploy record", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    const r = report("aaaa1111", "aaaa1111");
    r.gates = [{ status: "unratified", path: HOOK, discovered: true, deployment: "not-deployed" }];
    gatesVerify.mockResolvedValue(r);
    render(<Gates />);
    expect(await screen.findByText(/not deployed: the deploy record names no such file/)).toBeTruthy();
    expect(screen.queryByText(/no deploy record is readable/)).toBeNull();
  });

  it("shows the digest being replaced", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(
      report("bbbb22223333", "bbbb22223333", {
        status: "MODIFIED",
        gates: [
          {
            status: "modified",
            path: HOOK,
            plugin_id: "claude-code",
            expected: "aaaa11112222",
            actual: "bbbb22223333",
            ratified_at: "2026-09-01T00:00:00Z",
          },
        ],
      }),
    );
    render(<Gates />);
    // "last ratified" is the column a ratify replaces.
    expect(await screen.findByText("aaaa11112222")).toBeTruthy();
  });
});
