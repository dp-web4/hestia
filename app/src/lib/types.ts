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
  /**
   * Governance-surface escalations awaiting a decision, newest first.
   *
   * The daemon has sent these on every tick since the field was added; this type
   * declared five fields and dropped them, so the owner's most consequential
   * decision arrived in the app and was discarded before render.
   * `pending()` drops expired entries daemon-side, so anything here is decidable
   * right now — a queue offering a button the daemon would refuse teaches the
   * operator that the button lies.
   */
  pending_escalations: PendingEscalation[];
  /**
   * Scope requests awaiting a ruling — a member asking for reach on one path.
   * Like the escalations, sent every tick (#1109) and discarded by this type
   * until Sprint 2. Expired requests are dropped daemon-side.
   */
  pending_scope_requests: PendingScopeRequest[];
  /**
   * Ids the operator retired on this seat. Their rows stay in the data — hiding them would
   * make "show retired" impossible and would hide a retired id that is still acting.
   */
  retired?: string[];
  generated_at: string;
}

/**
 * A member's ask for reach on a path. Field names mirror the daemon payload
 * (`core/src/server/dashboard.rs`) exactly.
 */
export interface PendingScopeRequest {
  request_id: string;
  /** Caller-asserted, not authenticated — the same caveat as an escalation's asker. */
  claimed_by: string;
  role: string;
  /** Exactly one path. Recursion is the operator's choice at decide time, never the asker's. */
  path: string;
  /** The asker's own words. Shown whole: truncation is how a request gets ruled on its summary. */
  reason: string;
  requested_at: number;
  expires_at: number;
  secs_remaining: number;
}

/**
 * One escalation awaiting the operator. Field names mirror the daemon payload
 * (`core/src/server/dashboard.rs`) exactly, so a shape change upstream breaks a
 * typed read here rather than rendering stale.
 */
export interface PendingEscalation {
  id: string;
  /**
   * CALLER-ASSERTED, not authenticated (HST-005). Named `claimed_by` daemon-side
   * so a UI cannot present a claim as an identity — the operator decides partly
   * on this string and it is not proof of who asked.
   */
  claimed_by: string;
  role: string;
  tool_name: string;
  marker: string;
  /** The basis for deciding. Without these the operator approves a governance write knowing only a tool name. */
  stated_reason: string;
  stated_detail: string;
  opened_at: number;
  expires_at: number;
  secs_remaining: number;
  /** The criterion in force when this was OPENED, not today's. */
  bar: string;
  factors: string[];
  /**
   * Whether this operator's approval is sufficient, or merely necessary.
   * Derived daemon-side from the predicate itself. Approving a
   * `sovereign_plus_peer` escalation and watching nothing happen is the
   * strongest possible teacher that the button is decorative; it is not, and
   * this field is the discriminator that says so.
   */
  operator_alone_suffices: boolean;
  /** What else the bar still requires when this operator alone does not suffice. */
  still_needs: string[] | null;
  request_id: string | null;
  /**
   * What the retained act would DO, measured by the daemon (`evidence::write_effect`), never
   * the member's description. Absent when the act is not measurable (then nothing is shown,
   * rather than a guess). Two shapes: a copy (`cp <source> <governed>`) and, with `kind:
   * "patch"`, a patch application (`git apply|am`, `patch -i|<`).
   */
  write_effect?: WriteEffect | null;
}

export interface PatchFileStat {
  path: string;
  added: number;
  removed: number;
  created: boolean;
  deleted: boolean;
  /** Present when the patch changes (or, on creation, sets) the file mode. */
  old_mode?: string;
  new_mode?: string;
  renamed_from?: string;
  copied_from?: string;
  /** Binary content changes: `added`/`removed` do not count them. */
  binary?: boolean;
}

export interface WriteEffect {
  kind?: "patch";
  // copy-shaped
  source?: string;
  source_readable?: boolean;
  source_lines?: number;
  /** false: the source was over the measurement cap (or unreadable) and was NOT read. */
  source_read?: boolean;
  source_bytes?: number | null;
  compared_against?: { path: string; what: string } | null;
  /** false: the enforcing copy could not be read, so no diff is claimed. */
  enforcing_read?: boolean;
  identical_to_enforcing?: boolean;
  // patch-shaped
  patch_path?: string;
  patch_readable?: boolean;
  /** false: the patch was over the measurement cap and was NOT read; counts are null. */
  patch_read?: boolean;
  patch_bytes?: number | null;
  files?: PatchFileStat[] | null;
  file_count?: number | null;
  payload_unbound_reason?: string | null;
  /**
   * false whenever `incomplete` names something the summary does not represent (binary
   * content, an unknown header, a cut hunk, an unsupported diff format...). A surface must
   * say so: an incomplete summary read as the whole patch is an endorsement of unseen bytes.
   */
  summary_complete?: boolean;
  incomplete?: string[];
  // both
  payload_sha256?: string | null;
  added_lines?: number | null;
  removed_lines?: number | null;
  diff?: string[] | null;
  diff_truncated?: boolean;
  note?: string;
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
  /** This seat's OWN keys. */
  keys: string[];
  /** Keys inherited from the shared set (`_shared`); shared wins on a collision. */
  inherited?: string[];
  /** Own keys that restate a shared key — reported, never silently resolved. */
  shadowed?: string[];
  note: string;
  artifact: string;
  expected_sha256?: string;
  verdict: SeatConfigVerdict;
  finding_open_since?: number | null;
}

export interface SeatConfigList {
  /** The shared set: society facts every seat inherits. Keys only. */
  shared?: { configured: boolean; keys: string[]; note?: string; error?: string };
  seats: SeatConfigSummary[];
  render_dir: string;
}

/** GET /api/config/seat/:id — the one place values are shown. */
export interface SeatConfigInspect {
  member: string;
  config: { env: Record<string, string>; note: string };
  /** shared ∪ own, as the seat renders it. */
  effective?: Record<string, string>;
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

/**
 * What came of a decide call.
 *
 * `already_decided` is NOT an error. The daemon on this machine also serves its
 * own web dashboard, and the CLI drives the same state; all of them are views
 * onto one engine, and a decision is single-shot. Losing that race means the
 * operator's intent was settled elsewhere — by their own other window or by a
 * peer — and the honest response is to say so and show the current queue, not
 * to report that their click failed.
 */
export type DecideOutcome =
  | { outcome: "decided"; result: unknown }
  | { outcome: "already_decided"; detail: string };

/**
 * One gate's verdict, as `GET /api/gates/verify` serializes it (tagged on `status`).
 * Mirrors `vault::gate_integrity::GateVerdict`.
 */
export type GateVerdict = (
  | { status: "verified"; path: string; plugin_id: string; sha256: string }
  | { status: "modified"; path: string; plugin_id: string; expected: string; actual: string; ratified_at: string }
  | { status: "missing"; path: string; plugin_id: string; expected: string }
  | { status: "unratified"; path: string }
  | { status: "unreadable"; path: string; error: string }
) & {
  /** false = an expectation for a path no gate is wired at any more (offered for forget). */
  discovered?: boolean;
  /** Current bytes vs the deploy record. */
  deployment?: GateDeployment;
  /** The daemon's judgement (#1156): may this expectation be forgotten, and if not, why. */
  forgettable?: boolean;
  forget_blocked_reason?: string | null;
  /** A ratified gate whose member still declares a gate but has none registered: possible bypass. */
  not_registered?: boolean;
};

export type GateDeployment = "match" | "differs" | "not-deployed" | "no-deploy-record" | "unreadable";

/** What the deployment authority (`current-build.json`) recorded installing. */
export interface DeployedDigests {
  build_id: string | null;
  head_sha: string | null;
  installed_at_iso: string | null;
  files: Record<string, string>;
}

/**
 * `GET /api/gates/verify`. `UNKNOWN` carries a reason and no gates — it means the daemon
 * could not establish the set, and must never be rendered as "all fine".
 */
export interface GateReport {
  status: "VERIFIED" | "FINDINGS" | "MODIFIED" | "UNKNOWN";
  reason?: string;
  findings?: number;
  discovered?: number;
  gates?: GateVerdict[];
  /**
   * The evidence to ratify against: bytes installed now per discovered gate (null when
   * unreadable), and the deploy's own record. Evidence, not a verdict — nothing is
   * refused on it.
   */
  evidence?: {
    current: Record<string, string | null>;
    deployed: DeployedDigests | null;
  };
  /**
   * Whether ratify-all would be accepted: only when every discovered gate is the bytes the
   * deploy installed. Absent on a daemon that predates per-gate ratification.
   */
  bulk_ratify?: {
    allowed: boolean;
    blocked_by: { path: string; plugin_id: string; deployment: GateDeployment }[];
  };
}

/** A being's launcher, as the inventory found it (hestia #1076). */
export interface BeingLauncher {
  unit: string;
  member: string | null;
  members_in_unit: string[];
  sets_hestia_env: boolean;
  enabled_on_disk: boolean;
}

/** One agent row of `GET /api/agents`. Only the fields this app reads are typed. */
export interface AgentRow {
  agent: string;
  /** "being" for SAGE-style beings; absent means a harness. */
  kind?: string;
  /** The governance id — for a being, taken from its launcher's `--member`. */
  plugin: string;
  plugin_available: boolean;
  installed: boolean;
  governed: boolean;
  wired: boolean;
  partial: boolean;
  miswired: boolean;
  unprovisioned?: boolean;
  /** The inventory's own sentences. Shown in full: they say what is missing and where. */
  findings: string[];
  launchers?: BeingLauncher[];
  /** The MEMBER id (agent-inventory `member`); `plugin` is the older fallback. */
  member?: string;
  /** Each registered hook target, qualified: a hestia gate is `is_gate && owned_by_hestia`. */
  hook_targets?: HookTarget[];
}

export interface HookTarget {
  path: string;
  event?: string;
  exists?: boolean;
  is_gate?: boolean;
  owned_by_hestia?: boolean;
  config?: string;
}

/** An operator's active gate bypass, keyed by member id in `AgentInventory.bypassed`. */
export interface GateBypass {
  bypassed_at: string;
  reason: string;
  stub?: string;
  configs?: string[];
}

/** `GET /api/agents`. UNKNOWN carries a reason and must never render as an empty, clean list. */
export interface AgentInventory {
  status: "GOVERNED" | "UNGOVERNED_PRESENT" | "UNKNOWN" | string;
  reason?: string;
  machine?: string;
  installed?: string[];
  governed?: string[];
  plugins_available?: string[];
  registry_known?: number;
  gaps?: Record<string, string[]>;
  detail?: AgentRow[];
  /** Active gate bypasses, BESIDE the inventory's verdicts (the daemon does not tell the inventory). */
  bypassed?: Record<string, GateBypass>;
}
