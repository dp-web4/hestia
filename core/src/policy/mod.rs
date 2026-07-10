//! Hestia policy engine.
//!
//! Ports the heuristic + permissiveness-preset functionality from the
//! legacy `claude-code/plugins/web4-governance/governance/` Python
//! reference into the daemon. Four built-in presets:
//!
//! - `permissive` — no rules, all allowed (pure observation)
//! - `safety` — deny destructive bash, deny secret-file reads,
//!   warn on network, warn on memory writes, warn on git-push-without-PAT
//! - `strict` — deny everything except `Read`, `Glob`, `Grep`, `TodoWrite`
//! - `audit-only` — safety rules with `enforce=false` (dry run)
//!
//! The active preset (and any per-rule overrides + custom rules) is
//! stored in the encrypted vault — same crypto, same sealing surface
//! as the credential vault. See `vault::VaultPolicyState`.

pub mod engine;
pub mod extract;
mod law_gate;
pub mod matchers;
pub mod presets;
pub mod rate_limit;
pub mod types;

pub use engine::PolicyEngine;
pub use law_gate::{LawGate, LAW_FILE};
pub use extract::{classify, extract_full_command, extract_target};
pub use presets::{get_preset, is_preset_name, list_presets, PRESET_NAMES};
pub use rate_limit::{RateLimitResult, RateLimiter};
pub use types::{
    fold_strictest, PolicyAction, PolicyConfig, PolicyDecision, PolicyEvaluation, PolicyMatch,
    PolicyRule, PresetDefinition, RateLimitSpec, TimeWindow,
};
