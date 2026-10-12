// Independent continuation-order checks for PR #1280 at 71d7733c.
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
const snapshot = (label: string) => ({ generated_at: label }) as DashboardSnapshot;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: string) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

for (const outcome of ["resolve", "reject"] as const) {
  for (const boundary of ["newer success", "hestia:auth", "hestia:daemon-url"]) {
    it(`ignores an old status ${outcome} after ${boundary}`, async () => {
      const oldStatus = deferred<{ online: boolean; handshake: null }>();
      const nextDashboard = deferred<DashboardSnapshot>();
      const baseline = snapshot("already loaded");
      getDashboard.mockResolvedValueOnce(baseline);
      getDashboard.mockRejectedValueOnce("old request failed");
      getDashboard.mockReturnValueOnce(nextDashboard.promise);
      getDaemonStatus.mockReturnValueOnce(oldStatus.promise);
      const { result } = renderHook(() => useDashboard(60000));
      await act(async () => {});
      expect(result.current.online).toBe(true);
      let failedRefresh!: Promise<void>;
      await act(async () => { failedRefresh = result.current.refresh(); });
      expect(getDaemonStatus).toHaveBeenCalledTimes(1);

      const next = snapshot("new context");
      let refresh: Promise<void> | undefined;
      await act(async () => {
        if (boundary === "newer success") {
          refresh = result.current.refresh();
          nextDashboard.resolve(next);
          await refresh;
        } else {
          window.dispatchEvent(new Event(boundary));
        }
      });
      // The stale status must not change online state, including while the
      // new-context response is still pending and no newer result has applied.
      await act(async () => {
        if (outcome === "resolve") oldStatus.resolve({ online: false, handshake: null });
        else oldStatus.reject("old status failed");
        await failedRefresh;
      });
      expect(result.current.online).toBe(true);
      expect(result.current.handshake).toBeNull();
      expect(result.current.data).toEqual(boundary === "newer success" ? next : baseline);
      if (boundary !== "newer success") {
        await act(async () => { nextDashboard.resolve(next); });
        expect(result.current.data).toEqual(next);
        expect(result.current.online).toBe(true);
        expect(result.current.error).toBeNull();
      }
    });
  }
}

it("invalidates a pre-auth success before a newer response has applied", async () => {
  const old = deferred<DashboardSnapshot>();
  const next = deferred<DashboardSnapshot>();
  getDashboard.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  const { result } = renderHook(() => useDashboard(60000));
  await act(async () => { window.dispatchEvent(new Event("hestia:auth")); });
  await act(async () => { old.resolve(snapshot("old identity")); });
  expect(result.current.data).toBeNull();
  await act(async () => { next.resolve(snapshot("new identity")); });
  expect(result.current.data).toEqual(snapshot("new identity"));
});

it("keeps the newer success when two successful responses arrive out of order", async () => {
  const old = deferred<DashboardSnapshot>();
  getDashboard.mockReturnValueOnce(old.promise).mockResolvedValueOnce(snapshot("newer"));
  const { result } = renderHook(() => useDashboard(60000));
  await act(async () => { await result.current.refresh(); });
  await act(async () => { old.resolve(snapshot("older")); });
  expect(result.current.data).toEqual(snapshot("newer"));
  expect(result.current.online).toBe(true);
});
