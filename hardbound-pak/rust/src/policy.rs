//! Oversight policy — the deny/allow/warn gate that replaces consumer
//! Hestia's default-allow stub.

/// A pending action to be evaluated against policy.
///
/// Mirrors the shape of a Hestia R6 action begin record, but
/// intentionally generic so non-Hestia consumers can use the same
/// trait surface.
#[derive(Debug, Clone)]
pub struct PolicyAction {
    /// Tool the agent intends to invoke (e.g. `"Bash"`, `"WebFetch"`).
    pub tool_name: String,

    /// Optional target the tool will act on (file path, URL, etc.).
    pub target: Option<String>,

    /// Plugin requesting the action.
    pub plugin_id: String,

    /// Action magnitude in `[0..1]` — how consequential is this call?
    pub magnitude: f64,
}

/// Policy verdict for a [`PolicyAction`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PolicyDecision {
    /// Caller should proceed.
    Allow,

    /// Caller should NOT proceed. `reason` is shown to the user /
    /// agent for context.
    Deny {
        /// Human-readable explanation.
        reason: String,
        /// Stable identifier for the rule that fired, useful for
        /// log/audit correlation.
        policy_id: Option<String>,
    },

    /// Caller may proceed but the user should see a warning first.
    /// In CRISIS mode this can be promoted to a hard deny.
    Warn {
        /// Human-readable explanation.
        reason: String,
        /// Stable identifier for the rule that fired.
        policy_id: Option<String>,
    },
}

/// A policy engine. Implementations may be:
///
/// - Rule-based (YAML/Rego rules over the action shape)
/// - Model-based (a local LLM evaluating against a written policy)
/// - Hybrid (rules first, model for ambiguous cases)
///
/// The OSS Hestia default returns [`PolicyDecision::Allow`] for every
/// action. Hardbound replaces it with a real engine.
pub trait OversightPolicy: Send + Sync {
    /// Evaluate `action` and return a verdict.
    fn evaluate(&self, action: &PolicyAction) -> PolicyDecision;
}
