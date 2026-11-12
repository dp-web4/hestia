import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router";
import type { GateReport } from "../lib/types";

const gatesVerify = vi.fn();
vi.mock("../lib/tauri", () => ({ gatesVerify: () => gatesVerify() }));
const { GateIntegrityBanner } = await import("./GateIntegrityBanner");

function show(report: GateReport) {
  gatesVerify.mockResolvedValue(report);
  return render(<BrowserRouter><GateIntegrityBanner /></BrowserRouter>);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GateIntegrityBanner", () => {
  it("is silent only for a verified set", async () => {
    const { container } = show({
      status: "VERIFIED",
      gates: [{ status: "verified", path: "/g/a.py", plugin_id: "claude-code", sha256: "a" }],
    });
    await waitFor(() => expect(gatesVerify).toHaveBeenCalled());
    expect(container.querySelector("[role=alert]")).toBeNull();
  });

  it("names a deployed unratified gate and links to the remedy", async () => {
    show({
      status: "FINDINGS",
      gates: [{ status: "unratified", path: "/g/a.py", plugin_id: "claude-code", deployment: "match" }],
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("1 deployed, not yet ratified");
    expect(alert.textContent).toContain("claude-code");
    expect(screen.getByRole("link", { name: "Review and ratify in Gates" }).getAttribute("href")).toBe("/gates");
  });

  it("distinguishes modified bytes and a deploy mismatch without double-counting the gate", async () => {
    show({
      status: "MODIFIED",
      gates: [{ status: "modified", path: "/g/b.py", plugin_id: "codex", expected: "a", actual: "b",
              ratified_at: "2026-10-01", deployment: "differs" }],
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("1 gate:");
    expect(alert.textContent).toContain("1 modified since ratification");
    expect(alert.textContent).toContain("1 differs from the deploy");
    expect(alert.textContent).toContain("codex");
  });

  it("shows a verified gate whose deployment differs", async () => {
    show({
      status: "VERIFIED",
      gates: [{ status: "verified", path: "/g/b.py", plugin_id: "codex", sha256: "a", deployment: "differs" }],
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("1 gate: 1 differs from the deploy");
    expect(alert.textContent).toContain("codex");
  });

  it("treats a deregistered gate as a possible bypass even when its bytes verify", async () => {
    show({
      status: "VERIFIED",
      gates: [{ status: "verified", path: "/g/a.py", plugin_id: "claude-code", sha256: "a", not_registered: true }],
    });
    expect((await screen.findByRole("alert")).textContent).toContain("possible bypass");
  });

  it("reports UNKNOWN and a failed read rather than implying a healthy set", async () => {
    const { unmount } = show({ status: "UNKNOWN", reason: "no gate-role hooks discovered" });
    expect((await screen.findByRole("alert")).textContent).toContain("no gate-role hooks discovered");
    unmount();
    gatesVerify.mockRejectedValue(new Error("operator sign-in required"));
    render(<BrowserRouter><GateIntegrityBanner /></BrowserRouter>);
    expect((await screen.findByRole("alert")).textContent).toContain("Gate integrity could not be read");
  });
});
