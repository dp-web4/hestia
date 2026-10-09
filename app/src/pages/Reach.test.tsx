import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ScopeGrantRow } from "../lib/types";

const getDashboard = vi.fn();
const operatorStatus = vi.fn();
const grantReach = vi.fn();
const revokeReach = vi.fn();
const promoteGrant = vi.fn();
const setReach = vi.fn();
const reassignGrant = vi.fn();

vi.mock("../lib/tauri", () => ({
  getDashboard: () => getDashboard(),
  operatorStatus: () => operatorStatus(),
  grantReach: (...a: unknown[]) => grantReach(...a),
  revokeReach: (...a: unknown[]) => revokeReach(...a),
  promoteGrant: (...a: unknown[]) => promoteGrant(...a),
  setReach: (...a: unknown[]) => setReach(...a),
  reassignGrant: (...a: unknown[]) => reassignGrant(...a),
}));

const { Reach, replacedBy } = await import("./Reach");

const live: ScopeGrantRow = {
  lifetime: "live", plugin_id: "hub-being", path: "/w/notes", reason: "asked for notes",
  request_id: "r1", origin: "member_request", recursive: false, secs_remaining: 7200,
};
const standing: ScopeGrantRow = {
  lifetime: "standing", plugin_id: "hub-being", path: "/w/home", reason: "its home",
  granted_by: "operator", request_id: null, recursive: true, expires_at: null,
};

const signedIn = { signed_in: true, lct_id: "lct:x" };
const snapshot = (over: Record<string, unknown> = {}) => ({
  members: ["claude-code", "hub-being", "caude-code"],
  retired: ["caude-code"],
  scope_grants: [live, standing],
  standing_generation: 7,
  ...over,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function fillGrant(member: string, path: string, reason: string) {
  const selects = screen.getAllByRole("combobox");
  fireEvent.change(selects[0], { target: { value: member } });
  fireEvent.change(screen.getByPlaceholderText("/absolute/path"), { target: { value: path } });
  fireEvent.change(screen.getByPlaceholderText("why this member needs this reach"), {
    target: { value: reason },
  });
}

describe("Reach", () => {
  it("says every row's lifetime, and that a live one dies at restart", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    render(<Reach />);
    expect(await screen.findByText(/dies at the next restart · 2h left/)).toBeTruthy();
    expect(screen.getByText("standing")).toBeTruthy();
    expect(screen.getByText("this path and everything below")).toBeTruthy();
    expect(screen.getByText(/standing store generation 7/)).toBeTruthy();
  });

  it("a failed read is a failed read, not 'no grants'", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockRejectedValue(new Error("daemon unreachable"));
    render(<Reach />);
    expect(await screen.findByText(/could not read the grants/)).toBeTruthy();
    expect(screen.queryByText(/No grants are in force/)).toBeNull();
  });

  it("signed out: no grant or revoke control exists", async () => {
    operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
    getDashboard.mockResolvedValue(snapshot());
    render(<Reach />);
    await screen.findByText(/only readable here/);
    expect(screen.queryByRole("button", { name: /Revoke|Grant/ })).toBeNull();
  });

  it("offers only recorded, unretired members — ids are chosen, not typed", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    render(<Reach />);
    await screen.findByText("Grant reach");
    const opts = [...screen.getAllByRole("combobox")[0].querySelectorAll("option")].map((o) => o.value);
    expect(opts).toEqual(["", "claude-code", "hub-being"]);
  });

  it("a grant without a reason never reaches the daemon", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    render(<Reach />);
    await screen.findByText("Grant reach");
    await fillGrant("claude-code", "/w/repo", "");
    fireEvent.click(screen.getByRole("button", { name: "Grant" }));
    expect(await screen.findByText(/requires a reason/)).toBeTruthy();
    expect(grantReach).not.toHaveBeenCalled();
  });

  it("shows what a grant replaces, and binds the write to that row", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    grantReach.mockResolvedValue({ outcome: "granted", result: { ok: true }, replaced: standing });
    render(<Reach />);
    await screen.findByText("Grant reach");
    await fillGrant("hub-being", "/w/home/", "narrower home");
    expect(await screen.findByText(/This REPLACES the standing grant/)).toBeTruthy();
    expect(screen.getByText(/reason "its home"/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Replace grant" }));
    await waitFor(() => expect(grantReach).toHaveBeenCalled());
    expect(grantReach.mock.calls[0][0]).toBe("hub-being");
    expect(grantReach.mock.calls[0][3].seen).toEqual(standing);
    expect(await screen.findByText(/replaced the standing grant whose reason was "its home"/)).toBeTruthy();
  });

  it("a row changed by another view since it was shown stops the write and says so", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    grantReach.mockResolvedValue({ outcome: "moved", current: { ...standing, reason: "changed on the dashboard" } });
    render(<Reach />);
    await screen.findByText("Grant reach");
    await fillGrant("hub-being", "/w/home", "mine");
    fireEvent.click(screen.getByRole("button", { name: "Replace grant" }));
    expect(await screen.findByText(/changed since you looked .*changed on the dashboard.*Nothing was granted/)).toBeTruthy();
  });

  it("a new path replaces nothing and says nothing about replacing", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    grantReach.mockResolvedValue({ outcome: "granted", result: { ok: true }, replaced: null });
    render(<Reach />);
    await screen.findByText("Grant reach");
    await fillGrant("claude-code", "/w/repo", "needs the repo");
    expect(screen.queryByText(/This REPLACES/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Grant" }));
    await waitFor(() => expect(grantReach).toHaveBeenCalled());
    expect(grantReach.mock.calls[0][3].seen).toBeNull();
  });

  it("a revoke with no reason is SENT, and a vanished grant is an outcome", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue(snapshot());
    revokeReach.mockResolvedValue({ outcome: "already_revoked", detail: "not a live grant: nothing to revoke" });
    render(<Reach />);
    await screen.findByText(/dies at the next restart/);
    fireEvent.click(screen.getAllByRole("button", { name: "Revoke…" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revokeReach).toHaveBeenCalledWith(live, null));
    expect(await screen.findByText(/already gone — not a live grant/)).toBeTruthy();
  });

  it("replacedBy looks up the key the store holds", () => {
    expect(replacedBy([live, standing], "hub-being", " /w/./home/ ")).toEqual(standing);
    expect(replacedBy([live, standing], "hub-being", "/w/notes")).toBeNull(); // live is not replaced
    expect(replacedBy([live, standing], "claude-code", "/w/home")).toBeNull();
  });

  describe("Sprint 4b — make standing, reach, reassign", () => {
    const row = (sel: string) => document.querySelector(`[data-grant="${sel}"]`) as HTMLElement;
    const within = (sel: string, name: string | RegExp) =>
      [...row(sel).querySelectorAll("button")].find((b) =>
        typeof name === "string" ? b.textContent === name : name.test(b.textContent ?? ""),
      ) as HTMLButtonElement | undefined;

    it("offers each act only on the rows it applies to", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      getDashboard.mockResolvedValue(snapshot());
      render(<Reach />);
      await screen.findByText(/dies at the next restart/);
      expect(within("live:hub-being:/w/notes", "Make standing…")).toBeTruthy();
      expect(within("live:hub-being:/w/notes", "Reassign…")).toBeUndefined();
      expect(within("standing:hub-being:/w/home", "Reassign…")).toBeTruthy();
      expect(within("standing:hub-being:/w/home", "Make standing…")).toBeUndefined();
      expect(within("standing:hub-being:/w/home", "Make exact…")).toBeTruthy(); // it is recursive
      expect(within("live:hub-being:/w/notes", "Include below…")).toBeTruthy(); // it is exact
    });

    it("make standing shows the standing grant it replaces and is bound to it", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      const liveHome: ScopeGrantRow = { ...live, path: "/w/home", request_id: "r2", recursive: true };
      getDashboard.mockResolvedValue(snapshot({ scope_grants: [live, liveHome, standing] }));
      promoteGrant.mockResolvedValue({ outcome: "done", result: { ok: true } });
      render(<Reach />);
      await screen.findAllByText(/dies at the next restart/);
      fireEvent.click(within("live:hub-being:/w/home", "Make standing…")!);
      expect(await screen.findByText(/This REPLACES the standing grant on this path/)).toBeTruthy();
      fireEvent.click(within("live:hub-being:/w/home", /^Make standing \(replaces/)!);
      await waitFor(() => expect(promoteGrant).toHaveBeenCalled());
      expect(promoteGrant.mock.calls[0][2]).toEqual(standing);
      expect(await screen.findByText(/now standing — it survives restarts/)).toBeTruthy();
    });

    it("widening needs a reason; narrowing is sent without one", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      getDashboard.mockResolvedValue(snapshot());
      setReach.mockResolvedValue({ outcome: "done", result: {} });
      render(<Reach />);
      await screen.findByText(/dies at the next restart/);
      fireEvent.click(within("live:hub-being:/w/notes", "Include below…")!);
      fireEvent.click(within("live:hub-being:/w/notes", "Include everything below")!);
      expect(await screen.findByText(/requires a reason: it widens one path into a tree/)).toBeTruthy();
      expect(setReach).not.toHaveBeenCalled();
      fireEvent.click(within("standing:hub-being:/w/home", "Make exact…")!);
      fireEvent.click(within("standing:hub-being:/w/home", "Make exact")!);
      await waitFor(() => expect(setReach).toHaveBeenCalledWith(standing, false, null));
    });

    it("reassign chooses a recorded, unretired other member, needs a reason, and reports a moved row", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      getDashboard.mockResolvedValue(snapshot());
      reassignGrant.mockResolvedValue({ outcome: "moved", current: { ...standing, reason: "edited elsewhere" } });
      render(<Reach />);
      await screen.findByText(/dies at the next restart/);
      fireEvent.click(within("standing:hub-being:/w/home", "Reassign…")!);
      const select = row("standing:hub-being:/w/home").querySelector("select") as HTMLSelectElement;
      expect([...select.options].map((o) => o.value)).toEqual(["", "claude-code"]); // not itself, not retired
      fireEvent.change(select, { target: { value: "claude-code" } });
      fireEvent.click(within("standing:hub-being:/w/home", "Move to claude-code")!);
      expect(await screen.findByText(/requires a reason/)).toBeTruthy();
      expect(reassignGrant).not.toHaveBeenCalled();
      const input = row("standing:hub-being:/w/home").querySelector("input[type=text]") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "granted to the wrong seat" } });
      fireEvent.click(within("standing:hub-being:/w/home", "Move to claude-code")!);
      await waitFor(() => expect(reassignGrant).toHaveBeenCalledWith(standing, "claude-code", "granted to the wrong seat"));
      expect(await screen.findByText(/nothing was done — the standing grant changed since you looked \(it now reads "edited elsewhere"\)/)).toBeTruthy();
    });

    it("signed out: no act on any row", async () => {
      operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
      getDashboard.mockResolvedValue(snapshot());
      render(<Reach />);
      await screen.findByText(/only readable here/);
      expect(screen.queryByRole("button", { name: /Make standing|Include below|Make exact|Reassign/ })).toBeNull();
    });
  });
});
