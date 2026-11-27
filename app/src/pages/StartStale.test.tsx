// A snapshot loaded BEFORE a sign-out, a session expiry or a daemon loss stays in useDashboard's
// state (the failure branch never clears `data`). The first-run page must not keep presenting it
// as "Connected and signed in" (NOVA's hold on #1567; red test from mcnugget-claude's review).
// This drives the real hook over a mocked transport, so it also pins the hook's failure shape.
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { DashboardSnapshot } from "../lib/types";
import appSource from "../App.tsx?raw";

const getDashboard = vi.fn();
const getDaemonStatus = vi.fn();
vi.mock("../lib/tauri", () => ({
  getDashboard: () => getDashboard(),
  getDaemonStatus: () => getDaemonStatus(),
}));
vi.mock("../lib/compat", () => ({ blocksRoutes: () => false }));
const { Start } = await import("./Start");
const snapshot = { generated_at: "synthetic" } as DashboardSnapshot;

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const firstRun = (c: HTMLElement) => c.querySelector("[data-first-run]")?.getAttribute("data-first-run");

for (const [label, err, online, expected] of [
  ["sign-out", "not signed in", true, "sign-in"],
  ["session expiry", "session expired", true, "sign-in"],
  ["daemon down", "connection refused", false, "offline"],
] as const) {
  it(`after ${label}, a cached snapshot is not presented as connected and signed in`, async () => {
    getDashboard.mockResolvedValueOnce(snapshot);
    getDashboard.mockRejectedValue(err);
    getDaemonStatus.mockResolvedValue({ online, handshake: null });
    const { container } = render(<MemoryRouter><Start /></MemoryRouter>);
    await act(async () => { await Promise.resolve(); });
    expect(firstRun(container)).toBe("ready");
    await act(async () => { screen.getByText("Check again").click(); await new Promise(r => setTimeout(r, 0)); });
    expect(firstRun(container)).toBe(expected);
    expect(screen.queryByText(/Connected and signed in/)).toBeNull();
    // The failure is on the page, not hidden behind the earlier success.
    expect(container.querySelector(".error-banner")?.textContent).toContain(err);
  });
}

it("returns to ready when a later poll succeeds", async () => {
  getDashboard.mockResolvedValueOnce(snapshot);
  getDashboard.mockRejectedValueOnce("not signed in");
  getDashboard.mockResolvedValue(snapshot);
  getDaemonStatus.mockResolvedValue({ online: true, handshake: null });
  const { container } = render(<MemoryRouter><Start /></MemoryRouter>);
  await act(async () => { await Promise.resolve(); });
  await act(async () => { screen.getByText("Check again").click(); await new Promise(r => setTimeout(r, 0)); });
  expect(firstRun(container)).toBe("sign-in");
  await act(async () => { screen.getByText("Check again").click(); await new Promise(r => setTimeout(r, 0)); });
  expect(firstRun(container)).toBe("ready");
  expect(container.querySelector(".error-banner")).toBeNull();
});

it("links only to routes the app declares", async () => {
  getDashboard.mockRejectedValue("not signed in");
  getDaemonStatus.mockResolvedValue({ online: true, handshake: null });
  const { container } = render(<MemoryRouter><Start /></MemoryRouter>);
  await act(async () => { await Promise.resolve(); });
  const declared = new Set(
    [...appSource.matchAll(/<Route path="([^"]+)"/g)].map(m => m[1]),
  );
  const linked = [...container.querySelectorAll("a")].map(a => a.getAttribute("href"));
  expect(linked.length).toBeGreaterThan(0);
  for (const href of linked) expect(declared.has(href ?? ""), `no route for ${href}`).toBe(true);
});
