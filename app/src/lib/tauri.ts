import { invoke } from "@tauri-apps/api/core";
import type { DashboardSnapshot, DaemonStatus, AppConfig, RemoteEntry, DerivationReceipt, OperatorStatus } from "./types";

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
