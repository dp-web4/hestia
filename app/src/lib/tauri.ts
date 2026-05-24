import { invoke } from "@tauri-apps/api/core";
import type { DashboardSnapshot, DaemonStatus, AppConfig, RemoteEntry } from "./types";

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
