export interface SocietyView {
  sovereign_lct: string;
  chain_length: number;
  active_sessions: number;
  vault_entries: number;
  known_plugins: number;
}

export interface ActivityStats {
  total_actions: number;
  successful_actions: number;
  failed_actions: number;
  success_rate: number;
  by_tool: [string, number][];
  actions_last_hour: number;
}

export interface TrustView {
  plugin_id: string;
  entity_id: string;
  level: string;
  t3_talent: number;
  t3_training: number;
  t3_temperament: number;
  t3_average: number;
  v3_valuation: number;
  v3_veracity: number;
  v3_validity: number;
  v3_average: number;
  action_count: number;
  success_count: number;
  success_rate: number;
  days_since_last: number;
}

export interface RecentEntry {
  chain_position: number;
  event_type: string;
  timestamp: string;
  hash: string;
  prev_hash: string;
  tool_name?: string;
  target?: string;
  success?: boolean;
  magnitude?: number;
  plugin_id?: string;
  error?: string;
  decision?: string;
  enforced?: boolean;
  rule_name?: string;
  reason?: string;
}

export interface DashboardSnapshot {
  society: SocietyView;
  stats: ActivityStats;
  trust: TrustView[];
  recent: RecentEntry[];
  generated_at: string;
}

export interface DaemonStatus {
  online: boolean;
  url: string;
}

export interface RemoteEntry {
  name: string;
  url: string;
}

export interface AppConfig {
  mode: string;
  daemon_url: string;
  remotes: RemoteEntry[];
}
