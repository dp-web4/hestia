// Independent re-review evidence for #1280 at 16a1d500. The slow-success test
// intentionally fails there: all requests answer, but interval starts discard them.
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
