import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { DaemonStatus, Handshake } from "../lib/types";

const getDaemonStatus = vi.fn<() => Promise<DaemonStatus>>();
const getDashboard = vi.fn();
const getConfig = vi.fn();

vi.mock("../lib/tauri", () => ({
  getDaemonStatus: () => getDaemonStatus(),
  getDashboard: () => getDashboard(),
  getConfig: () => getConfig(),
  setDaemonUrl: vi.fn(),
}));

const { CompatBanner } = await import("./CompatBanner");
const { Dashboard } = await import("../pages/Dashboard");
const { APP_VERSION, blocksRoutes } = await import("../lib/compat");

function hs(over: Partial<Handshake>): Handshake {
  return {
    state: "compatible",
    app_version: "0.3.0",
    app_api_compat: 1,
    daemon_version: "0.3.0",
    daemon_build_id: "v0.3.0",
    daemon_api_compat: 1,
    message: "hestia 0.3.0 (build v0.3.0)",
    ...over,
  };
}

function status(h: Handshake): DaemonStatus {
  return { online: h.state !== "unreachable", url: "http://127.0.0.1:7799", signed_in: false, handshake: h };
}

const INCOMPATIBLE = hs({
  state: "incompatible",
  daemon_version: "0.4.0",
  daemon_build_id: "v0.4.0",
  daemon_api_compat: 2,
  message: "incompatible daemon: it serves operator API v2 (hestia 0.4.0, build v0.4.0); this app speaks v1 (hestia 0.3.0). Upgrade the app so both are the same release.",
});
const NO_ENDPOINT = hs({
  state: "no_version_endpoint",
  daemon_version: null,
  daemon_build_id: null,
  daemon_api_compat: null,
  message: "incompatible daemon (no version endpoint): GET /api/version answered 404, so the daemon predates hestia 0.3.0.",
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CompatBanner", () => {
  it("names an incompatible daemon and both sides' versions", async () => {
    getDaemonStatus.mockResolvedValue(status(INCOMPATIBLE));
    render(<CompatBanner pollMs={60000} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Incompatible daemon");
    expect(alert.textContent).toContain("hestia 0.4.0 · API v2");
    expect(alert.textContent).toContain("hestia 0.3.0 · API v1");
    expect(alert.getAttribute("data-compat")).toBe("incompatible");
  });

  it("reads a daemon with no /api/version as incompatible, not offline", async () => {
    getDaemonStatus.mockResolvedValue(status(NO_ENDPOINT));
    render(<CompatBanner pollMs={60000} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Incompatible daemon (no version endpoint)");
    expect(alert.textContent).toContain("hestia unknown · API unknown");
  });

  it("shows skew as a status, not an alert", async () => {
    getDaemonStatus.mockResolvedValue(
      status(hs({ state: "skew", daemon_version: "0.3.1", message: "version skew: daemon is hestia 0.3.1" })),
    );
    render(<CompatBanner pollMs={60000} />);
    expect((await screen.findByRole("status")).textContent).toContain("Version skew");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says nothing for a compatible daemon or an unreachable one (the offline screens own that)", async () => {
    for (const h of [hs({}), hs({ state: "unreachable", message: "daemon unreachable: refused" })]) {
      getDaemonStatus.mockResolvedValue(status(h));
      const { container } = render(<CompatBanner pollMs={60000} />);
      await vi.waitFor(() => expect(getDaemonStatus).toHaveBeenCalled());
      expect(container.querySelector(".compat-banner")).toBeNull();
      cleanup();
      getDaemonStatus.mockClear();
    }
  });
});

describe("Dashboard against an incompatible daemon", () => {
  it("shows the incompatible state instead of 'Cannot reach Hestia daemon'", async () => {
    getConfig.mockResolvedValue({ mode: "sovereign", daemon_url: "http://127.0.0.1:7799", remotes: [] });
    getDashboard.mockRejectedValue(INCOMPATIBLE.message);
    getDaemonStatus.mockResolvedValue(status(INCOMPATIBLE));
    render(<Dashboard />);
    expect(await screen.findByText("Incompatible daemon")).toBeTruthy();
    expect(screen.queryByText("Cannot reach Hestia daemon")).toBeNull();
    expect(screen.getByText(/daemon: hestia 0.4.0 · API v2/)).toBeTruthy();
  });

  // hestia#1280 P2: a successful poll used to leave the old blocking verdict in place, so a
  // fixed pairing stayed behind the panel until the page remounted. No navigation here.
  const RECOVERED = {
    society: { sovereign_lct: "lct:web4:test", chain_length: 4242, active_sessions: 1, vault_entries: 0, known_plugins: 1 },
    stats: { total_actions: 0, successful_actions: 0, failed_actions: 0, success_rate: 1, by_tool: [], actions_last_hour: 0 },
    trust: [],
    recent: [],
    pending_escalations: [],
    pending_scope_requests: [],
    retired: [],
    generated_at: "2026-10-12T00:00:00Z",
  };
  const MALFORMED = hs({ state: "malformed", daemon_version: null, daemon_build_id: null, daemon_api_compat: null, message: "daemon compatibility unknown: GET /api/version answered 500" });
  for (const blocked of [INCOMPATIBLE, NO_ENDPOINT, MALFORMED]) {
    it(`recovers from ${blocked.state} in place once the daemon answers`, async () => {
      getConfig.mockResolvedValue({ mode: "sovereign", daemon_url: "http://127.0.0.1:7799", remotes: [] });
      getDashboard.mockRejectedValue(blocked.message);
      getDaemonStatus.mockResolvedValue(status(blocked));
      const { container } = render(<Dashboard />);
      await vi.waitFor(() => expect(container.querySelector(`[data-compat="${blocked.state}"]`)).not.toBeNull());

      getDashboard.mockResolvedValue(RECOVERED);
      getDaemonStatus.mockResolvedValue(status(hs({})));
      window.dispatchEvent(new Event("hestia:daemon-url"));
      await vi.waitFor(() => expect(container.querySelector("[data-compat]")).toBeNull());
      expect(screen.queryByText(compatTitleOf(blocked))).toBeNull();
      expect(await screen.findByText("4242")).toBeTruthy();
    });
  }
});

function compatTitleOf(h: Handshake): string {
  return h.state === "malformed" ? "Daemon compatibility unknown" : h.state === "no_version_endpoint" ? "Incompatible daemon (no version endpoint)" : "Incompatible daemon";
}

describe("compat helpers", () => {
  it("bakes the package version, not a hardcoded string", () => {
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("blocks exactly the states the shell refuses", () => {
    const states: Handshake["state"][] = ["compatible", "skew", "incompatible", "no_version_endpoint", "malformed", "unreachable"];
    expect(states.filter((s) => blocksRoutes(hs({ state: s })))).toEqual(["incompatible", "no_version_endpoint", "malformed"]);
  });
});
