import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { GateReport } from "../lib/types";

const gatesVerify = vi.fn();
const gatesRatify = vi.fn();
const operatorStatus = vi.fn();

vi.mock("../lib/tauri", () => ({
  gatesVerify: () => gatesVerify(),
  gatesRatify: (reason: string, expected: Record<string, string | null>) => gatesRatify(reason, expected),
  operatorStatus: () => operatorStatus(),
}));

const { Gates } = await import("./Gates");

const HOOK = "/home/dp/.claude/hooks/hestia/pre_tool_use.py";

function report(installed: string, deployed: string | null, over: Partial<GateReport> = {}): GateReport {
  return {
    status: "FINDINGS",
    findings: 1,
    discovered: 1,
    gates: [{ status: "unratified", path: HOOK }],
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
    expect(screen.queryByRole("button", { name: /ratify/i })).toBeNull();
    expect(gatesVerify).not.toHaveBeenCalled();
  });

  it("UNKNOWN is reported with its reason, never as clean, and cannot be ratified", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue({ status: "UNKNOWN", reason: "no gate-role hooks discovered" });
    render(<Gates />);
    expect(await screen.findByText(/no gate-role hooks discovered/)).toBeTruthy();
    expect(screen.getByText(/not a clean result/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /ratify/i })).toBeNull();
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
    expect(screen.getByText(/this is your decision, not the daemon's/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /ratify/i })).toBeTruthy();
  });

  it("will not ratify without a reason", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    gatesVerify.mockResolvedValue(report("aaaa1111", "aaaa1111"));
    render(<Gates />);
    (await screen.findByRole("button", { name: /ratify/i })).click();
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
    screen.getByRole("button", { name: /ratify/i }).click();

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
    screen.getByRole("button", { name: /ratify/i }).click();

    // The reviewed bytes travel with the reason, so the daemon can refuse if they moved.
    await waitFor(() =>
      expect(gatesRatify).toHaveBeenCalledWith("matches deploy 4d59496", { [HOOK]: "aaaa1111" }),
    );
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
