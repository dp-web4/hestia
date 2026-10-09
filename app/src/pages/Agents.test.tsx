import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AgentInventory, AgentRow } from "../lib/types";

const agentsInventory = vi.fn();
const getDashboard = vi.fn();
const operatorStatus = vi.fn();
const retireAgent = vi.fn();
const reinstateAgent = vi.fn();
const agentGateBypass = vi.fn();
const agentGateRestore = vi.fn();

vi.mock("../lib/tauri", () => ({
  agentsInventory: () => agentsInventory(),
  getDashboard: () => getDashboard(),
  operatorStatus: () => operatorStatus(),
  retireAgent: (...a: unknown[]) => retireAgent(...a),
  reinstateAgent: (...a: unknown[]) => reinstateAgent(...a),
  agentGateBypass: (m: string, r: string) => agentGateBypass(m, r),
  agentGateRestore: (m: string) => agentGateRestore(m),
}));

const { Agents, unaccountedMembers } = await import("./Agents");

const claude: AgentRow = {
  agent: "claude", plugin: "claude-code", plugin_available: true, installed: true,
  governed: true, wired: true, partial: false, miswired: false, findings: [],
};
const codex: AgentRow = {
  agent: "codex", plugin: "codex", plugin_available: true, installed: true,
  governed: false, wired: false, partial: false, miswired: false,
  findings: ["ROLE ABSENT: no live hestia hook on gate event(s) PreToolUse — enforcement is not present on this machine"],
};
const being: AgentRow = {
  agent: "sage", kind: "being", plugin: "hub-being", plugin_available: false, installed: true,
  governed: true, wired: true, partial: false, miswired: false, unprovisioned: false, findings: [],
  launchers: [{
    unit: "/home/dp/.config/systemd/user/sage-heartbeat.service", member: "hub-being",
    members_in_unit: ["hub-being"], sets_hestia_env: true, enabled_on_disk: true,
  }],
};

function inventory(detail: AgentRow[], over: Partial<AgentInventory> = {}): AgentInventory {
  return {
    status: "UNGOVERNED_PRESENT", machine: "HUB",
    installed: detail.map((d) => d.agent),
    governed: detail.filter((d) => d.governed).map((d) => d.agent),
    gaps: { ungoverned: detail.filter((d) => !d.governed).map((d) => d.agent), dormant_plugin: ["gemini"] },
    detail, ...over,
  };
}

const signedIn = { signed_in: true, lct_id: "lct:x" };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Agents", () => {
  it("UNKNOWN is shown as its reason, never as an empty clean list", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue({
      status: "UNKNOWN",
      reason: "agent-inventory is not installed on this machine",
    });
    getDashboard.mockResolvedValue({ retired: [] });
    render(<Agents />);
    expect(await screen.findByText(/agent-inventory is not installed on this machine/)).toBeTruthy();
    expect(screen.getByText(/could not be looked at/)).toBeTruthy();
    expect(screen.queryByText(/installed ·/)).toBeNull();
  });

  it("shows a being, governed through its launcher's --member", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue(inventory([claude, being]));
    getDashboard.mockResolvedValue({ retired: [] });
    render(<Agents />);
    expect(await screen.findByText(/· being/)).toBeTruthy();
    expect(screen.getByText(/--member hub-being/)).toBeTruthy();
  });

  it("flags an ungoverned agent with the inventory's findings in full", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue(inventory([claude, codex]));
    getDashboard.mockResolvedValue({ retired: [] });
    render(<Agents />);
    expect(await screen.findByText("UNGOVERNED")).toBeTruthy();
    expect(screen.getByText(/ungoverned: codex/)).toBeTruthy();
    expect(screen.getByText(/no live hestia hook on gate event\(s\) PreToolUse/)).toBeTruthy();
  });

  it("calls out a retired id that is still governed", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue(inventory([claude, being]));
    getDashboard.mockResolvedValue({ retired: ["hub-being"] });
    render(<Agents />);
    expect(await screen.findByText(/retired on this seat, but still governed/)).toBeTruthy();
  });

  it("signed out: says it could not look, and does not ask the daemon", async () => {
    operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
    render(<Agents />);
    expect(await screen.findByText(/not the same as nothing being ungoverned/)).toBeTruthy();
    expect(agentsInventory).not.toHaveBeenCalled();
  });

  it("lists adapters for agents that are not installed, apart from the table", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue(inventory([claude]));
    getDashboard.mockResolvedValue({ retired: [] });
    render(<Agents />);
    expect(await screen.findByText(/Adapters available for agents not installed here: gemini/)).toBeTruthy();
  });

  // dp, 2026-09-28: a fail-open recovery switch for a member its own gate has locked out.
  const gated: AgentRow = {
    ...claude, member: "claude-code",
    hook_targets: [{ path: "/h/pre_tool_use.py", event: "PreToolUse", is_gate: true, owned_by_hestia: true }],
  };

  it("offers bypass only where a hestia gate is registered, and requires a reason", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    agentsInventory.mockResolvedValue(inventory([gated, codex]));
    getDashboard.mockResolvedValue({ retired: [] });
    agentGateBypass.mockResolvedValue({ ok: true });
    render(<Agents />);
    const offers = await screen.findAllByText("bypass gate…");
    expect(offers.length).toBe(1); // codex has no hestia gate row: nothing to bypass
    fireEvent.click(offers[0]);
    expect(screen.getByText(/acts UNGOVERNED: no gate, no scope, no\s+safety preset, no escalations/)).toBeTruthy();
    fireEvent.click(screen.getByText("bypass claude-code's gate"));
    expect(await screen.findByText(/requires a reason/)).toBeTruthy();
    expect(agentGateBypass).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "gate update locked it out" } });
    fireEvent.click(screen.getByText("bypass claude-code's gate"));
    await screen.findAllByText("bypass gate…");
    expect(agentGateBypass).toHaveBeenCalledWith("claude-code", "gate update locked it out");
  });

  it("a bypassed member shows BYPASSED and restore, and keeps the inventory's own verdict", async () => {
    operatorStatus.mockResolvedValue(signedIn);
    const bypassedRow: AgentRow = { ...codex, member: "codex" };
    agentsInventory.mockResolvedValue(
      inventory([claude, bypassedRow], { bypassed: { codex: { bypassed_at: "T", reason: "locked out" } } }),
    );
    getDashboard.mockResolvedValue({ retired: [] });
    agentGateRestore.mockRejectedValue("the registration changed since the bypass");
    render(<Agents />);
    expect(await screen.findByText("BYPASSED")).toBeTruthy();
    expect(screen.getByText("UNGOVERNED")).toBeTruthy(); // the inventory's word, not the page's
    fireEvent.click(screen.getByText("restore gate"));
    expect(await screen.findByText(/restore refused: the registration changed/)).toBeTruthy();
    expect(agentGateRestore).toHaveBeenCalledWith("codex");
  });

  describe("Sprint 3b — retire / reinstate a member nothing here accounts for", () => {
    const trust = (plugin_id: string, action_count: number, aliased_to?: string) =>
      ({ plugin_id, action_count, aliased_to }) as never;

    it("finds the registry's ids that no installed agent carries, and only those", () => {
      const inv = inventory([claude, being]);
      const out = unaccountedMembers(inv, {
        members: ["claude-code", "hub-being", "caude-code", "hestia-cli", "agent-inventory", "early-grant"],
        trust: [trust("claude-code", 9000), trust("caude-code", 2), trust("Claude-code", 3, "claude-code")],
        retired: ["early-grant"],
      });
      expect(out).toEqual([
        { id: "caude-code", actions: 2, retired: false },
        { id: "early-grant", actions: 0, retired: true },
      ]);
    });

    it("offers retire on a phantom id, and on no installed agent's row", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      agentsInventory.mockResolvedValue(inventory([claude, codex]));
      getDashboard.mockResolvedValue({ retired: [], members: ["claude-code", "codex", "caude-code"], trust: [] });
      render(<Agents />);
      const row = await screen.findByText("caude-code");
      expect(row).toBeTruthy();
      expect(screen.getAllByRole("button", { name: "Retire" })).toHaveLength(1);
      expect(document.querySelector('[data-member="claude-code"]')).toBeNull();
      expect(screen.queryByRole("button", { name: /connect/i })).toBeNull();
    });

    it("the live-member refusal is a question with its evidence, confirmed only by the operator", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      agentsInventory.mockResolvedValue(inventory([claude]));
      getDashboard.mockResolvedValue({ retired: [], members: ["caude-code"], trust: [] });
      retireAgent.mockResolvedValueOnce({
        outcome: "needs_confirmation",
        detail: "this id has taken 12 act(s) in the last 24h, so it is a LIVE member",
        acts_recently: 12, unmeasurable: false, window_hours: 24,
      });
      retireAgent.mockResolvedValueOnce({ outcome: "retired", result: { ok: true } });
      render(<Agents />);
      await screen.findByText("caude-code");
      const [reason, ref] = screen.getAllByRole("textbox");
      fireEvent.change(reason, { target: { value: "typo of claude-code" } });
      fireEvent.change(ref, { target: { value: "dp 2026-09-28" } });
      fireEvent.click(screen.getByRole("button", { name: "Retire" }));
      expect(await screen.findByText(/12 act\(s\) in the last 24h/)).toBeTruthy();
      expect(retireAgent).toHaveBeenLastCalledWith("caude-code", "typo of claude-code", "dp 2026-09-28", false);
      const btn = screen.getByRole("button", { name: "Retire" }) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      const box = screen.getByRole("checkbox") as HTMLInputElement;
      expect(box.checked).toBe(false);
      fireEvent.click(box);
      fireEvent.click(btn);
      await waitFor(() =>
        expect(retireAgent).toHaveBeenLastCalledWith("caude-code", "typo of claude-code", "dp 2026-09-28", true),
      );
      expect(await screen.findByText(/Retired on this seat/)).toBeTruthy();
    });

    it("an id another view already retired is reported, not overwritten", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      agentsInventory.mockResolvedValue(inventory([claude]));
      getDashboard.mockResolvedValue({ retired: [], members: ["caude-code"], trust: [] });
      retireAgent.mockResolvedValue({
        outcome: "already_retired",
        detail: "'caude-code' was already retired on this seat — another view got there first.",
      });
      render(<Agents />);
      await screen.findByText("caude-code");
      fireEvent.click(screen.getByRole("button", { name: "Retire" }));
      expect(await screen.findByText(/another view got there first/)).toBeTruthy();
    });

    it("reinstate says which authority it did NOT give back", async () => {
      operatorStatus.mockResolvedValue(signedIn);
      agentsInventory.mockResolvedValue(inventory([claude]));
      getDashboard.mockResolvedValue({ retired: ["caude-code"], members: ["caude-code"], trust: [] });
      reinstateAgent.mockResolvedValue({
        outcome: "reinstated", result: { ok: true, grants_not_restored: ["/w/repos"] },
      });
      render(<Agents />);
      await screen.findByText("caude-code");
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "it was real after all" } });
      fireEvent.click(screen.getByRole("button", { name: "Reinstate" }));
      expect(await screen.findByText(/NOT restored .*\/w\/repos/)).toBeTruthy();
      expect(reinstateAgent).toHaveBeenCalledWith("caude-code", "it was real after all");
    });

    it("signed out: no lifecycle control exists", async () => {
      operatorStatus.mockResolvedValue({ signed_in: false, lct_id: null });
      render(<Agents />);
      await screen.findByText(/not the same as nothing being ungoverned/);
      expect(screen.queryByRole("button", { name: /Retire|Reinstate/ })).toBeNull();
    });
  });
});
