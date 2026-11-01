// Poll-ordering contract for the dashboard (hestia#1280). The slow-success cases come from
// Codex's recheck at 16a1d500: every request answered, yet starts discarded them all.
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { DashboardSnapshot } from "../lib/types";

const getDashboard = vi.fn();
const getDaemonStatus = vi.fn();
vi.mock("../lib/tauri", () => ({
  getDashboard: () => getDashboard(),
  getDaemonStatus: () => getDaemonStatus(),
}));
const { useDashboard } = await import("./useDashboard");
const snapshot = { generated_at: "synthetic-review-snapshot" } as DashboardSnapshot;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

for (const latency of [1500, 2500]) {
  it(`publishes successful ${latency}ms responses during 2000ms polling`, async () => {
    vi.useFakeTimers();
    let completed = 0;
    getDashboard.mockImplementation(() => new Promise(resolve => {
      setTimeout(() => { completed++; resolve(snapshot); }, latency);
    }));
    const { result } = renderHook(() => useDashboard(2000));
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(completed).toBeGreaterThanOrEqual(4);
    expect(getDashboard).toHaveBeenCalledTimes(6);
    expect(result.current.data).toEqual(snapshot);
    expect(result.current.online).toBe(true);
  });
}

it("does not let an older failure overwrite a newer successful refresh", async () => {
  let rejectOld!: (reason: string) => void;
  getDashboard.mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
  getDashboard.mockResolvedValue(snapshot);
  const { result } = renderHook(() => useDashboard(60000));
  await act(async () => { await result.current.refresh(); });
  await act(async () => { rejectOld("incompatible daemon"); });
  expect(result.current.data).toEqual(snapshot);
  expect(result.current.error).toBeNull();
  expect(getDaemonStatus).not.toHaveBeenCalled();
});

it("discards a slow answer from before a daemon URL change, even with nothing newer applied", async () => {
  let resolveOld!: (s: DashboardSnapshot) => void;
  let resolveNew!: (s: DashboardSnapshot) => void;
  const oldSnap = { generated_at: "old-daemon" } as DashboardSnapshot;
  const newSnap = { generated_at: "new-daemon" } as DashboardSnapshot;
  getDashboard.mockImplementationOnce(() => new Promise(r => { resolveOld = r; }));
  getDashboard.mockImplementationOnce(() => new Promise(r => { resolveNew = r; }));
  const { result } = renderHook(() => useDashboard(60000));
  await act(async () => { window.dispatchEvent(new Event("hestia:daemon-url")); });
  await act(async () => { resolveOld(oldSnap); });
  expect(result.current.data).toBeNull();
  await act(async () => { resolveNew(newSnap); });
  expect(result.current.data).toEqual(newSnap);
});

it("does not let an older success overwrite a newer applied failure's status", async () => {
  let resolveOld!: (s: DashboardSnapshot) => void;
  getDashboard.mockImplementationOnce(() => new Promise(r => { resolveOld = r; }));
  getDashboard.mockRejectedValueOnce("daemon unreachable");
  getDaemonStatus.mockResolvedValue({ online: false, handshake: null });
  const { result } = renderHook(() => useDashboard(60000));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.online).toBe(false);
  await act(async () => { resolveOld(snapshot); });
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe("daemon unreachable");
});
