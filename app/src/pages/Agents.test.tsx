import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { AgentInventory, AgentRow } from "../lib/types";

const agentsInventory = vi.fn();
const getDashboard = vi.fn();
const operatorStatus = vi.fn();

vi.mock("../lib/tauri", () => ({
  agentsInventory: () => agentsInventory(),
  getDashboard: () => getDashboard(),
  operatorStatus: () => operatorStatus(),
}));

const { Agents } = await import("./Agents");

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
});
