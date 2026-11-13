import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import { MemoryRouter } from "react-router";
import { firstRunState } from "./Start";

vi.mock("../hooks/useDashboard", () => ({
  useDashboard: () => ({
    data: null, online: true, signedIn: false, error: "not signed in",
    handshake: null, refresh: vi.fn(),
  }),
}));

const { Start } = await import("./Start");
afterEach(cleanup);

describe("first-run truthful state", () => {
  const base = { online: false, signedIn: true, hasSnapshot: false, incompatible: false, error: null };
  it("does not describe a refused inventory as healthy", () => {
    expect(firstRunState({ ...base, online: true, signedIn: false, error: "not signed in" })).toBe("sign-in");
    expect(firstRunState({ ...base, error: "connection refused" })).toBe("offline");
    expect(firstRunState(base)).toBe("checking");
  });
  it("incompatibility precedes all positive claims", () => {
    expect(firstRunState({ ...base, incompatible: true, hasSnapshot: true })).toBe("incompatible");
  });
  it("a successful snapshot is the positive evidence", () => {
    expect(firstRunState({ ...base, online: true, hasSnapshot: true })).toBe("ready");
  });
  it("provides a signed-out path but no privileged write control", () => {
    render(<MemoryRouter><Start /></MemoryRouter>);
    expect(screen.getByText(/need to sign in using the sidebar/)).toBeTruthy();
    expect(screen.getByText("Open Agents")).toBeTruthy();
    expect(screen.queryByText(/Grant access now/)).toBeNull();
  });
});
