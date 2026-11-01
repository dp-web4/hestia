import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { DelegationList, DelegationRow } from "../lib/types";

const getDashboard = vi.fn();
const operatorStatus = vi.fn();
const delegationsList = vi.fn();
const delegationGrant = vi.fn();
const delegationRevoke = vi.fn();

vi.mock("../lib/tauri", () => ({
  getDashboard: () => getDashboard(),
  operatorStatus: () => operatorStatus(),
  delegationsList: (...a: unknown[]) => delegationsList(...a),
  delegationGrant: (...a: unknown[]) => delegationGrant(...a),
  delegationRevoke: (...a: unknown[]) => delegationRevoke(...a),
}));

const { Delegations } = await import("./Delegations");

const ROLES = ["sovereign", "law_oracle", "policy_entity", "treasurer", "administrator", "archivist", "citizen", "witness", "auditor"];
const row = (over: Partial<DelegationRow> = {}): DelegationRow => ({
  id: "3f7b70d0-13d9-4049-b048-d87528810de1", delegator_lct_id: "op", agent_lct_id: "k",
  scope: { roles: ["witness"], actions: ["ledger.read"] }, created_at: "2026-09-29T00:00:00Z",
  expires_at: null, revoked: false, active: true, ...over,
});
const list = (over: Partial<DelegationList> = {}): DelegationList => ({
  plugin_id: "kimi-code", agent_key: "k", delegations: [row()], roles: ROLES, retired: false, ...over,
});
const signedIn = { signed_in: true, lct_id: "lct:x" };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function pick(member: string) {
  const select = await screen.findByRole("combobox");
  await waitFor(() => expect([...(select as HTMLSelectElement).options].map((o) => o.value)).toContain(member));
  fireEvent.change(select, { target: { value: member } });
}

describe("Delegations", () => {
  it("does not expose the previous member while loading or accept an older response", async () => {
    const a = deferred<DelegationList>();
    const b = deferred<DelegationList>();
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code", "claude-code"] });
    delegationsList.mockImplementation((m: string) => m === "kimi-code" ? a.promise : b.promise);
    render(<Delegations />);
    await pick("kimi-code");
    fireEvent.change(screen.getByLabelText("member"), { target: { value: "claude-code" } });
    expect(screen.queryByRole("button", { name: /Delegate|Revoke/ })).toBeNull();
    await act(async () => b.resolve(list({ plugin_id: "claude-code" })));
    expect(await screen.findByText("Delegate to claude-code")).toBeTruthy();
    await act(async () => a.resolve(list()));
    expect(screen.getByText("Delegate to claude-code")).toBeTruthy();
    expect(screen.queryByText("Delegate to kimi-code")).toBeNull();
  });

  it("switching clears entered authority, and stale errors cannot replace the new view", async () => {
    const stale = deferred<DelegationList>();
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code", "claude-code"] });
    delegationsList.mockImplementation((m: string) => m === "kimi-code" ? Promise.resolve(list()) : stale.promise);
    render(<Delegations />);
    await pick("kimi-code");
    await screen.findByText("Delegate to kimi-code");
    fireEvent.click(screen.getByLabelText("witness"));
    fireEvent.change(screen.getByPlaceholderText("why this member needs this authority"), { target: { value: "old reason" } });
    fireEvent.change(screen.getByLabelText("member"), { target: { value: "claude-code" } });
    expect(screen.queryByText("Delegate to kimi-code")).toBeNull();
    fireEvent.change(screen.getByLabelText("member"), { target: { value: "kimi-code" } });
    await screen.findByText("Delegate to kimi-code");
    expect((screen.getByLabelText("witness") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByPlaceholderText("why this member needs this authority") as HTMLInputElement).value).toBe("");
    await act(async () => stale.reject(new Error("stale read")));
    expect(screen.queryByText(/stale read/)).toBeNull();
  });

  it("a mismatched response never enables a different member's controls", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["claude-code"] });
    delegationsList.mockResolvedValue(list());
    render(<Delegations />);
    await pick("claude-code");
    expect(await screen.findByText(/response member does not match selection/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Delegate|Revoke/ })).toBeNull();
  });

  it("a completed old-member grant is attributed correctly and cannot refresh the new member", async () => {
    const pending = deferred<{ delegation_id: string; unvalidated_actions: string[] }>();
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code", "claude-code"] });
    delegationsList.mockImplementation((m: string) => Promise.resolve(list({ plugin_id: m, delegations: [] })));
    delegationGrant.mockReturnValue(pending.promise);
    render(<Delegations />);
    await pick("kimi-code");
    await screen.findByText("Delegate to kimi-code");
    fireEvent.click(screen.getByLabelText("witness"));
    fireEvent.change(screen.getByPlaceholderText("why this member needs this authority"), { target: { value: "audit" } });
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    expect(delegationGrant).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("member"), { target: { value: "claude-code" } });
    await screen.findByText("Delegate to claude-code");
    await act(async () => pending.resolve({ delegation_id: "x", unvalidated_actions: [] }));
    expect(screen.getByText("Delegate to claude-code")).toBeTruthy();
    expect(screen.getByText("Action completed for kimi-code (previous selection): Delegated to kimi-code.")).toBeTruthy();
    expect(delegationsList.mock.calls.filter(([m]) => m === "kimi-code")).toHaveLength(1);
  });

  it("a failed old-member action is reported after switching", async () => {
    const pending = deferred<{ delegation_id: string; unvalidated_actions: string[] }>();
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code", "claude-code"] });
    delegationsList.mockImplementation((m: string) => Promise.resolve(list({ plugin_id: m, delegations: [] })));
    delegationGrant.mockReturnValue(pending.promise);
    render(<Delegations />);
    await pick("kimi-code");
    await screen.findByText("Delegate to kimi-code");
    fireEvent.click(screen.getByLabelText("witness"));
    fireEvent.change(screen.getByPlaceholderText("why this member needs this authority"), { target: { value: "audit" } });
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    fireEvent.change(screen.getByLabelText("member"), { target: { value: "claude-code" } });
    await screen.findByText("Delegate to claude-code");
    await act(async () => pending.reject(new Error("connection lost")));
    expect(screen.getByText(/Action outcome for kimi-code could not be confirmed: Error: connection lost/)).toBeTruthy();
    expect(screen.getByText("Delegate to claude-code")).toBeTruthy();
  });

  it("the member is chosen from the registry, and its delegations listed with status", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code", "claude-code"] });
    delegationsList.mockResolvedValue(list({ delegations: [row(), row({ id: "aaaaaaaa-13d9-4049-b048-d87528810de1", revoked: true, active: false })] }));
    render(<Delegations />);
    await pick("kimi-code");
    expect(delegationsList).toHaveBeenCalledWith("kimi-code");
    expect(await screen.findByText("active")).toBeTruthy();
    expect(screen.getByText("revoked")).toBeTruthy();
    expect(screen.getAllByText("Revoke…")).toHaveLength(1); // only the active one
  });

  it("a grant names what it delegates and why; nothing named is refused before the daemon", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code"] });
    delegationsList.mockResolvedValue(list({ delegations: [] }));
    delegationGrant.mockResolvedValue({ delegation_id: "x", unvalidated_actions: ["frobnicate"] });
    render(<Delegations />);
    await pick("kimi-code");
    await screen.findByText("Delegate to kimi-code");
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    expect(await screen.findByText(/it would be full authority/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("witness"));
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    expect(await screen.findByText(/requires a reason/)).toBeTruthy();
    expect(delegationGrant).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: /actions/ }), { target: { value: "frobnicate\n\n" } });
    fireEvent.change(screen.getByPlaceholderText("why this member needs this authority"), { target: { value: "audit" } });
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    await waitFor(() => expect(delegationGrant).toHaveBeenCalledWith("kimi-code", ["witness"], ["frobnicate"], null, "audit"));
    expect(await screen.findByText(/NOT validated: frobnicate is not a verb this daemon interprets/)).toBeTruthy();
  });

  it("a retired member's history is readable and nothing may be granted to it", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["caude-code"] });
    delegationsList.mockResolvedValue(list({ plugin_id: "caude-code", retired: true, delegations: [row({ revoked: true, active: false })] }));
    render(<Delegations />);
    await pick("caude-code");
    expect(await screen.findByText(/is retired on this seat/)).toBeTruthy();
    expect(screen.getByText("revoked")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delegate" })).toBeNull();
  });

  it("revoke asks for the daemon's reason and an already-revoked answer is an outcome", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    getDashboard.mockResolvedValue({ members: ["kimi-code"] });
    delegationsList.mockResolvedValue(list());
    delegationRevoke.mockResolvedValue({ outcome: "already_revoked" });
    render(<Delegations />);
    await pick("kimi-code");
    fireEvent.click(await screen.findByText("Revoke…"));
    const card = document.querySelector(`[data-delegation="${row().id}"]`) as HTMLElement;
    fireEvent.change(card.querySelector("input[type=text]") as HTMLInputElement, { target: { value: "done" } });
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(delegationRevoke).toHaveBeenCalledWith("kimi-code", row().id, "done"));
    expect(await screen.findByText(/already revoked elsewhere/)).toBeTruthy();
  });

  it("signed out: nothing is read and no control exists", async () => {
    operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
    getDashboard.mockResolvedValue({ members: ["kimi-code"] });
    render(<Delegations />);
    await pick("kimi-code");
    expect(await screen.findByText(/not the same as nothing being delegated/)).toBeTruthy();
    expect(delegationsList).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Delegate|Revoke/ })).toBeNull();
  });
});
