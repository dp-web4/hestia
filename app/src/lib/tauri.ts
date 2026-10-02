import { invoke } from "@tauri-apps/api/core";
import type {
  AgentInventory,
  DashboardSnapshot,
  DecideOutcome,
  ReachOutcome,
  StandingActOutcome,
  ScopeGrantRow,
  GateReport,
  DaemonStatus,
  AppConfig,
  RemoteEntry,
  DerivationReceipt,
  OperatorStatus,
  SeatConfigList,
  SeatConfigInspect,
  SeatConfigPutResult,
} from "./types";

/**
 * Decide one governance-surface escalation as the signed-in operator.
 *
 * Reaches `POST /api/operator/gate-escalation` — the channel behind a proved
 * operator LCT — and never the CLI path, which is authenticated only by
 * filesystem access to HESTIA_HOME. Returns the daemon's own answer: whether an
 * approval actually permits the write depends on the bar, and this must not
 * claim more than the daemon said.
 */
export async function decideGateEscalation(
  id: string,
  approve: boolean,
  reason: string | null,
): Promise<DecideOutcome> {
  return invoke("decide_gate_escalation", { id, approve, reason });
}

/**
 * Grant or refuse one scope request as the signed-in operator, via
 * `POST /api/scope/decide`. A grant needs a reason; a refusal does not; a
 * standing refusal is not a thing; exact unless the operator chooses recursion.
 * A request already ruled elsewhere comes back as `already_decided`.
 */
export async function ruleScopeRequest(
  requestId: string,
  granted: boolean,
  reason: string | null,
  opts: { standing?: boolean; recursive?: boolean } = {},
): Promise<DecideOutcome> {
  return invoke("rule_scope_request", {
    requestId,
    granted,
    reason,
    standing: opts.standing ?? false,
    recursive: opts.recursive ?? false,
  });
}

/** Gate verdicts plus the evidence to ratify against. */
export async function gatesVerify(): Promise<GateReport> {
  return invoke("gates_verify");
}

/**
 * Ratify named gates' CURRENT bytes (`paths`), merging into the other gates' expectations;
 * or, with no `paths`, every discovered gate — which the daemon accepts only when every gate
 * is the bytes the deploy installed.
 */
export async function gatesRatify(
  reason: string,
  expected: Record<string, string | null>,
  paths?: string[],
): Promise<unknown> {
  // `expected` binds the ratification to the bytes the operator reviewed: the daemon
  // refuses (409) when the installed gates no longer match it.
  return invoke("gates_ratify", { reason, expected, paths: paths ?? null });
}

/** Remove the expectations for gates this machine no longer wires, per path. */
export async function gatesForget(reason: string, paths: string[]): Promise<unknown> {
  return invoke("gates_forget", { reason, paths });
}

/** Who is on this box and whether it is governed. Read-only. */
export async function agentsInventory(): Promise<AgentInventory> {
  return invoke("agents_inventory");
}

/**
 * Grant a member STANDING reach on a path. A reason is required. `seen` is the standing row the
 * form showed for this (member, path), or null: last edit wins in the engine, so the command
 * re-reads and returns `moved` — sending nothing — if the row is no longer what was shown.
 */
export async function grantReach(
  member: string,
  path: string,
  reason: string,
  opts: { recursive?: boolean; expiresInSecs?: number | null; seen: ScopeGrantRow | null },
): Promise<ReachOutcome> {
  return invoke("grant_reach", {
    member,
    path,
    reason,
    recursive: opts.recursive ?? false,
    expiresInSecs: opts.expiresInSecs ?? null,
    seen: opts.seen,
  });
}

/** Revoke one grant: a live one by request id, a standing one by (member, path). No reason required. */
export async function revokeReach(row: ScopeGrantRow, reason: string | null): Promise<ReachOutcome> {
  return invoke("revoke_reach", {
    lifetime: row.lifetime,
    requestId: row.request_id ?? null,
    member: row.plugin_id,
    path: row.path,
    reason,
  });
}

/**
 * Bypass a member's gate: its PreToolUse gate is swapped for a stub that ALLOWS every call, so a
 * member its own gate has locked out can act to fix it. It is UNGOVERNED until restored.
 */
export async function agentGateBypass(member: string, reason: string): Promise<unknown> {
  return invoke("agent_gate_bypass", { member, reason });
}

/** Put a bypassed member's gate back exactly as it was registered. */
export async function agentGateRestore(member: string): Promise<unknown> {
  return invoke("agent_gate_restore", { member });
}

/**
 * Make a LIVE grant standing. `seen` is the standing row the page showed on that path (null =
 * none): promotion replaces it, so the daemon refuses (`moved`) if it changed since.
 */
export async function promoteGrant(
  live: ScopeGrantRow,
  reason: string | null,
  seen: ScopeGrantRow | null,
): Promise<StandingActOutcome> {
  return invoke("promote_grant", { member: live.plugin_id, path: live.path, reason, seen });
}

/** Widen a grant to its subtree (reason required) or narrow it to exactly its path. */
export async function setReach(
  row: ScopeGrantRow,
  recursive: boolean,
  reason: string | null,
): Promise<StandingActOutcome> {
  return invoke("set_reach", { member: row.plugin_id, path: row.path, recursive, reason });
}

/** Move one standing grant to another recorded member, bound to the row as shown. */
export async function reassignGrant(
  row: ScopeGrantRow,
  to: string,
  reason: string,
): Promise<StandingActOutcome> {
  return invoke("reassign_grant", { member: row.plugin_id, path: row.path, to, reason, seen: row });
}

export async function getDashboard(): Promise<DashboardSnapshot> {
  return invoke("get_dashboard");
}

export async function getFailures(): Promise<unknown> {
  return invoke("get_failures");
}

export async function getDaemonStatus(): Promise<DaemonStatus> {
  return invoke("get_daemon_status");
}

export async function vaultList(): Promise<unknown> {
  return invoke("vault_list");
}

export async function vaultSet(
  name: string,
  value: string,
  scope: string[],
  tags: string[],
  allowedConsumers: string[]
): Promise<unknown> {
  return invoke("vault_set", {
    req: { name, value, scope, tags, allowed_consumers: allowedConsumers },
  });
}

export async function vaultDelete(name: string): Promise<unknown> {
  return invoke("vault_delete", { name });
}

// Vault-authored seat config (#944 phase 0). Same authed transport; no delete by design.
export async function configSeatList(): Promise<SeatConfigList> {
  return invoke("config_seat_list");
}

export async function configSeatGet(pluginId: string): Promise<SeatConfigInspect> {
  return invoke("config_seat_get", { req: { plugin_id: pluginId } });
}

export async function configSeatPut(
  pluginId: string,
  env: Record<string, string>,
  note: string
): Promise<SeatConfigPutResult> {
  return invoke("config_seat_put", { req: { plugin_id: pluginId, env, note } });
}

export async function getPolicy(): Promise<unknown> {
  return invoke("get_policy");
}

export async function setPreset(preset: string): Promise<unknown> {
  return invoke("set_preset", { preset });
}

export async function queryChain(
  limit?: number,
  eventType?: string,
  toolFilter?: string
): Promise<unknown> {
  return invoke("query_chain", {
    limit: limit ?? null,
    event_type: eventType ?? null,
    tool_filter: toolFilter ?? null,
  });
}

export async function chainStats(): Promise<unknown> {
  return invoke("chain_stats");
}

export async function getConfig(): Promise<AppConfig> {
  return invoke("get_config");
}

export async function setMode(mode: string): Promise<unknown> {
  return invoke("set_mode", { mode });
}

export async function setDaemonUrl(url: string): Promise<unknown> {
  return invoke("set_daemon_url", { url });
}

export async function addRemote(name: string, url: string): Promise<unknown> {
  return invoke("add_remote", { remote: { name, url } });
}

export async function removeRemote(name: string): Promise<unknown> {
  return invoke("remove_remote", { name });
}

export async function listRemotes(): Promise<{ remotes: RemoteEntry[] }> {
  return invoke("list_remotes");
}

export async function getRemoteDashboard(url: string): Promise<DashboardSnapshot> {
  return invoke("get_remote_dashboard", { url });
}

// ---- operator session (Sprint 2 prerequisite) ----
// The key and bearer token live in the Rust shell; these calls only move
// intent in and status out. The webview cannot read the credential — the
// reason this app is a better operator surface than the web dashboard,
// which must keep its cred in localStorage.

export async function operatorStatus(): Promise<OperatorStatus> {
  return invoke("operator_status");
}

/** Unlock the app-owned identity vault; first use imports the legacy key. */
export async function operatorSignIn(
  passphrase: string,
  vaultPath?: string,
): Promise<OperatorStatus> {
  return invoke("operator_sign_in", {
    passphrase,
    vaultPath: vaultPath ?? null,
  });
}

export async function operatorSignOut(): Promise<OperatorStatus> {
  return invoke("operator_sign_out");
}

// ---- trust derivation receipts ----

export async function getDerivation(
  pluginId: string,
  role?: string,
): Promise<DerivationReceipt> {
  return invoke("get_derivation", { pluginId, role: role ?? null });
}
