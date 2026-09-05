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
  // Canonical unmeasured-handling: a dimension with zero observations is null
  // (honest unmeasured), never a fabricated 0.5 score.
  t3_talent: number | null;
  t3_training: number | null;
  t3_temperament: number | null;
  t3_average: number | null;
  v3_valuation: number | null;
  v3_veracity: number | null;
  v3_validity: number | null;
  v3_average: number | null;
  t3_observation_counts: [number, number, number];
  v3_observation_counts: [number, number, number];
  action_count: number;
  success_count: number;
  success_rate: number;
  days_since_last: number;

  // ---- T3-from-V3 arc (daemon >= 2026-07-24) ----
  // The legacy scalar level, kept for audit and NEVER for display: the chip
  // that called a well-adjudicated member "low" off this field was the
  // footgun (dp 2026-07-24). `level` above is the derived one.
  legacy_level?: string;
  // Conduct-derived temperament: governance response, not self-report.
  derived_temperament?: number | null;
  derived_temperament_n?: number;
  // The #adjudicated grain — V3 folded ONLY from witnessed not-the-actor
  // adjudications. Null = zero adjudications (honest-unmeasured), never 0.5.
  adjudicated_validity?: number | null;
  adjudicated_veracity?: number | null;
  adjudicated_valuation?: number | null;
  // [valuation, veracity, validity]
  adjudicated_counts?: [number, number, number];
  // How the numbers were produced: "legacy-lockstep-v1" = one self-reported
  // scalar smeared across three dims (must NOT be shown as three independent
  // facts); "v3-derived-v1" = per-dimension from adjudicated evidence.
  derivation?: string;
}

/// One evidence entry behind a derived score, as returned by
/// GET /api/trust/derivation. Position + hash make it checkable against the
/// chain; `contribution` says what it did to the score.
export interface DerivationEvidence {
  chain_position: number;
  event_type: string;
  hash: string;
  timestamp: string;
  contribution: string;
  reference?: string;
}

export interface DerivedDimension {
  score: number | null;
  observations: number;
  formula: string;
  evidence: DerivationEvidence[];
}

export interface DerivationReceipt {
  derivation_version: string;
  generated_at: string;
  level: string;
  plugin_id: string;
  role_lct: string;
  temperament: DerivedDimension;
  validity: DerivedDimension;
  valuation: DerivedDimension;
  veracity: DerivedDimension;
}

export interface OperatorStatus {
  signed_in: boolean;
  lct_id: string | null;
  vault_path: string | null;
  vault_exists: boolean;
  migration_available: boolean;
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
  /** Present since v0.2.0: distinguishes "daemon down" from "signed out". */
  signed_in?: boolean;
  operator_lct?: string | null;
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

// ---- Vault-authored seat config (#944 phase 0) ----

/** What the daemon's projection check found for one seat. `status` is the discriminator. */
export interface SeatConfigVerdict {
  status: "verified" | "miswired" | "missing" | "unreadable" | "unbacked" | "unconfigured" | string;
  member: string;
  sha256?: string;
  expected?: string;
  actual?: string;
  reason?: string;
  error?: string;
  quarantined_to?: string | null;
}

/** One row of GET /api/config/seat. Keys and health — never a value. */
export interface SeatConfigSummary {
  member: string;
  configured: boolean;
  keys: string[];
  note: string;
  artifact: string;
  expected_sha256?: string;
  verdict: SeatConfigVerdict;
  finding_open_since?: number | null;
}

export interface SeatConfigList {
  seats: SeatConfigSummary[];
  render_dir: string;
}

/** GET /api/config/seat/:id — the one place values are shown. */
export interface SeatConfigInspect {
  member: string;
  config: { env: Record<string, string>; note: string };
  summary: SeatConfigSummary;
}

/** PUT /api/config/seat — the daemon renders in the same act and returns that render's verdict. */
export interface SeatConfigPutResult {
  ok: boolean;
  member: string;
  replaced: boolean;
  artifact: string;
  verdict: SeatConfigVerdict[];
  intentEntryHash: string;
}
