import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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
  vi.useRealTimers();
  gatesVerify.mockReset();
});

const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

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

  it("goes loud as stale when a read after a healthy one never answers (#1575)", async () => {
    vi.useFakeTimers();
    gatesVerify
      .mockResolvedValueOnce({ status: "VERIFIED", gates: [] })
      .mockReturnValue(new Promise(() => {}));
    render(<BrowserRouter><GateIntegrityBanner /></BrowserRouter>);
    await advance(0);
    expect(screen.queryByRole("alert")).toBeNull();
    await advance(15000 + 15000 + 1000);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("unverified");
    expect(alert.textContent).toContain("stale since");
    expect(alert.textContent).toContain("no answer after 15s");
  });

  it("bounds a first read that never answers (#1575)", async () => {
    vi.useFakeTimers();
    gatesVerify.mockReturnValue(new Promise(() => {}));
    render(<BrowserRouter><GateIntegrityBanner /></BrowserRouter>);
    await advance(15000 + 100);
    expect(screen.getByRole("alert").textContent).toContain("Gate integrity could not be read");
  });

  it("re-reads at once when the window becomes visible (#1575)", async () => {
    vi.useFakeTimers();
    gatesVerify
      .mockResolvedValueOnce({ status: "VERIFIED", gates: [] })
      .mockResolvedValue({ status: "MODIFIED", gates: [{ status: "modified", path: "/g/b.py", plugin_id: "codex" }] });
    render(<BrowserRouter><GateIntegrityBanner /></BrowserRouter>);
    await advance(0);
    expect(screen.queryByRole("alert")).toBeNull();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await advance(0);
    expect(gatesVerify).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert").textContent).toContain("1 modified since ratification");
  });
});
