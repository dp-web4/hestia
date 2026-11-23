//! Typed Lawbook projections into Hestia's existing policy engines.
//!
//! The local extension reuses `PolicyMatch`, and society law reuses
//! `web4_policy::Law`; neither evaluator is reimplemented here.

use std::collections::HashSet;

use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use web4_policy::{Decision, Law, R6Request};

use super::engine::PolicyEngine;
use super::law_gate::LawGate;
use super::types::{
    PolicyAction, PolicyConfig, PolicyDecision, PolicyEvaluation, PolicyMatch, PolicyRule,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityDomain {
    InnateLocal,
    LocalOperator,
    RoleOverlay,
    SocietyHub,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResolutionKind {
    Appeal,
    Escalation,
    Adjudication,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResolutionPath {
    pub kind: ResolutionKind,
    pub target: String,
    pub timeout_secs: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LawbookProvenance {
    pub lawbook_id: String,
    pub lawbook_version: String,
    pub authority_domain: AuthorityDomain,
    pub authority_ref: String,
    pub effective_from: Option<String>,
    pub effective_to: Option<String>,
    pub resolution: Option<ResolutionPath>,
}

impl LawbookProvenance {
    fn validate(&self) -> Result<()> {
        ensure!(!self.lawbook_id.trim().is_empty(), "lawbook_id is required");
        ensure!(!self.lawbook_version.trim().is_empty(), "lawbook_version is required");
        ensure!(!self.authority_ref.trim().is_empty(), "authority_ref is required");
        if let Some(path) = &self.resolution {
            validate_resolution(path)?;
        }
        Ok(())
    }
}

fn validate_resolution(path: &ResolutionPath) -> Result<()> {
    ensure!(!path.target.trim().is_empty(), "a resolution path must name its resolver");
    if let Some(timeout) = path.timeout_secs {
        ensure!(timeout > 0, "a resolution timeout must be positive");
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalRule {
    pub rule_id: String,
    pub rule_version: String,
    pub name: String,
    pub priority: i32,
    pub decision: PolicyDecision,
    pub reason: Option<String>,
    pub r#match: PolicyMatch,
    pub resolution: Option<ResolutionPath>,
}

impl LocalRule {
    fn policy_rule(&self) -> PolicyRule {
        PolicyRule {
            id: self.rule_id.clone(),
            name: self.name.clone(),
            priority: self.priority,
            decision: self.decision,
            reason: self.reason.clone(),
            r#match: self.r#match.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalLawbook {
    pub provenance: LawbookProvenance,
    pub default_policy: PolicyDecision,
    pub enforce: bool,
    pub rules: Vec<LocalRule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalProjection {
    pub provenance: LawbookProvenance,
    pub source_projection_hash: String,
    pub config: PolicyConfig,
}

impl LocalLawbook {
    pub fn from_policy_config(
        provenance: LawbookProvenance,
        config: &PolicyConfig,
        rule_version: &str,
    ) -> Result<Self> {
        provenance.validate()?;
        ensure!(!rule_version.trim().is_empty(), "rule_version is required");
        Ok(Self {
            provenance,
            default_policy: config.default_policy,
            enforce: config.enforce,
            rules: config.rules.iter().map(|rule| LocalRule {
                rule_id: rule.id.clone(),
                rule_version: rule_version.into(),
                name: rule.name.clone(),
                priority: rule.priority,
                decision: rule.decision,
                reason: rule.reason.clone(),
                r#match: rule.r#match.clone(),
                resolution: None,
            }).collect(),
        })
    }

    pub fn compile(&self) -> Result<LocalProjection> {
        self.provenance.validate()?;
        let mut ids = HashSet::new();
        for rule in &self.rules {
            ensure!(!rule.rule_id.trim().is_empty(), "rule_id is required");
            ensure!(!rule.rule_version.trim().is_empty(), "rule_version is required for {}", rule.rule_id);
            ensure!(ids.insert(rule.rule_id.as_str()), "duplicate rule_id {}", rule.rule_id);
            if let Some(path) = &rule.resolution {
                validate_resolution(path)?;
            }
        }
        let source_projection_hash = hex::encode(Sha256::digest(serde_json::to_vec(self)?));
        Ok(LocalProjection {
            provenance: self.provenance.clone(),
            source_projection_hash,
            config: PolicyConfig {
                default_policy: self.default_policy,
                enforce: self.enforce,
                rules: self.rules.iter().map(LocalRule::policy_rule).collect(),
            },
        })
    }
}

#[derive(Debug, Clone)]
pub struct LocalCase<'a> {
    pub id: &'a str,
    pub action: PolicyAction<'a>,
    pub expected_decision: PolicyDecision,
    pub expected_rule_id: Option<&'a str>,
    pub expected_enforced: bool,
}

pub fn run_local_cases(
    lawbook: &LocalLawbook,
    hand_authored: &PolicyConfig,
    cases: &[LocalCase<'_>],
) -> Result<Vec<PolicyEvaluation>> {
    let projection = lawbook.compile()?;
    ensure!(projection.config == *hand_authored, "the generated PolicyConfig differs from the hand-authored fixture");
    let generated = PolicyEngine::new(projection.config);
    let reference = PolicyEngine::new(hand_authored.clone());
    let mut evaluations = Vec::new();
    for case in cases {
        let actual = generated.evaluate(&case.action);
        let expected = reference.evaluate(&case.action);
        ensure!(actual == expected, "{}: generated and reference engines disagree", case.id);
        ensure!(actual.decision == case.expected_decision, "{}: decision {:?}, expected {:?}", case.id, actual.decision, case.expected_decision);
        ensure!(actual.rule_id.as_deref() == case.expected_rule_id, "{}: rule {:?}, expected {:?}", case.id, actual.rule_id, case.expected_rule_id);
        ensure!(actual.enforced == case.expected_enforced, "{}: enforced={}, expected {}", case.id, actual.enforced, case.expected_enforced);
        evaluations.push(actual);
    }
    Ok(evaluations)
}

#[derive(Debug, Clone)]
pub struct SocietyLawbook {
    pub provenance: LawbookProvenance,
    pub law: Law,
    pub source_law_hash: String,
}

impl SocietyLawbook {
    pub fn new(provenance: LawbookProvenance, law: Law) -> Result<Self> {
        provenance.validate()?;
        ensure!(law.version == provenance.lawbook_version, "law.version and lawbook_version differ");
        law.validate()?;
        let source_law_hash = Law::<web4_policy::NoExtension>::sha256_hex_of(&serde_yaml::to_string(&law)?);
        Ok(Self { provenance, law, source_law_hash })
    }

    pub fn from_yaml(lawbook_id: &str, authority_ref: &str, yaml: &str) -> Result<Self> {
        let law = Law::parse_and_validate(yaml)?;
        let provenance = LawbookProvenance {
            lawbook_id: lawbook_id.into(),
            lawbook_version: law.version.clone(),
            authority_domain: AuthorityDomain::SocietyHub,
            authority_ref: authority_ref.into(),
            effective_from: None,
            effective_to: None,
            resolution: None,
        };
        let source_law_hash = Law::<web4_policy::NoExtension>::sha256_hex_of(yaml);
        let mut book = Self::new(provenance, law)?;
        book.source_law_hash = source_law_hash;
        Ok(book)
    }

    pub fn projection_hash(&self) -> Result<String> {
        Ok(self.source_law_hash.clone())
    }

    pub fn compile(&self) -> Result<LawGate> {
        Ok(LawGate::Active {
            law: self.law.clone(),
            sha256: self.projection_hash()?,
        })
    }
}

#[derive(Debug, Clone)]
pub struct SocietyCase {
    pub id: &'static str,
    pub request: R6Request,
}

#[derive(Debug, Clone)]
pub struct SocietyExpectation {
    pub decision: PolicyDecision,
    pub winning_rule: Option<&'static str>,
    pub escalation_target: Option<&'static str>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SocietyComparison {
    pub decision: PolicyDecision,
    pub winning_rule: Option<String>,
    pub escalation_target: Option<String>,
    pub lawbook_version: String,
    pub law_sha256: String,
    pub explanation_root: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WitnessSeverity {
    Advisory,
    Blocker,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssuranceProfile {
    A1,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntegrityWitness {
    RuleUnreachable,
    RuleNeverFiresOnCorpus,
    CategoryUngoverned,
    RoleOverlayWidensBase,
    AppealPathUnreachable,
    PolicyProjectionStale,
    HubHestiaDecisionMismatch,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IntegrityFinding {
    pub witness: IntegrityWitness,
    pub severity: WitnessSeverity,
    pub assurance: AssuranceProfile,
    pub evidence: String,
}

impl IntegrityFinding {
    fn new(witness: IntegrityWitness, severity: WitnessSeverity, evidence: impl Into<String>) -> Self {
        Self { witness, severity, assurance: AssuranceProfile::A1, evidence: evidence.into() }
    }

    fn advisory(witness: IntegrityWitness, evidence: impl Into<String>) -> Self {
        Self::new(witness, WitnessSeverity::Advisory, evidence)
    }

    fn blocker(witness: IntegrityWitness, evidence: impl Into<String>) -> Self {
        Self::new(witness, WitnessSeverity::Blocker, evidence)
    }
}

fn payload_str<'a>(payload: &'a serde_yaml::Value, key: &str) -> Option<&'a str> {
    payload.as_mapping()?.get(&serde_yaml::Value::String(key.into())).and_then(serde_yaml::Value::as_str)
}

pub fn compare_society_case(
    lawbook: &SocietyLawbook,
    case: &SocietyCase,
    expected: &SocietyExpectation,
) -> Result<SocietyComparison, IntegrityFinding> {
    let gate = match lawbook.compile() {
        Ok(gate) => gate,
        Err(error) => return Err(IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            format!("{}: society projection failed: {error}", case.id),
        )),
    };
    let law_hash = match lawbook.projection_hash() {
        Ok(hash) => hash,
        Err(error) => return Err(IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            format!("{}: society hash failed: {error}", case.id),
        )),
    };
    let hub = lawbook.law.evaluate_outcome(&case.request);
    let payload = &case.request.payload;
    let action = PolicyAction {
        tool_name: &case.request.action,
        category: payload_str(payload, "category").unwrap_or(""),
        target: payload_str(payload, "target"),
        full_command: payload_str(payload, "full_command"),
    };
    let actual = gate.evaluate(&action, &case.request.role);
    let decision = match hub.decision {
        Decision::Allow => PolicyDecision::Allow,
        Decision::Warn => PolicyDecision::Warn,
        Decision::Deny | Decision::Escalate => PolicyDecision::Deny,
    };
    let winning_rule = hub.winning_norm.as_ref().map(|id| format!("law:{id}"));
    let escalation_target = if hub.decision == Decision::Escalate {
        Some(hub.escalate_to.unwrap_or_else(|| "sovereign".into()))
    } else {
        None
    };
    let actual_target = if hub.decision == Decision::Escalate {
        actual.constraints.iter().find_map(|token| token.strip_prefix("escalate_to:").map(str::to_string))
    } else {
        None
    };
    let comparison = SocietyComparison {
        decision: actual.decision,
        winning_rule: actual.rule_id.clone(),
        escalation_target: actual_target.clone(),
        lawbook_version: lawbook.provenance.lawbook_version.clone(),
        law_sha256: law_hash,
        explanation_root: hub.winning_norm.clone().unwrap_or_else(|| "escalation-trigger".into()),
    };
    let mismatch = || IntegrityFinding::blocker(
        IntegrityWitness::HubHestiaDecisionMismatch,
        format!("{}: hub={:?}/{:?}/{:?}; hestia={:?}/{:?}/{:?}", case.id,
                decision, winning_rule, escalation_target, actual.decision, actual.rule_id, actual_target),
    );
    if actual.decision != decision
        || actual.decision != expected.decision
        || actual.rule_id != winning_rule
        || actual.rule_id.as_deref() != expected.winning_rule
        || actual_target != escalation_target
        || actual_target.as_deref() != expected.escalation_target
    {
        return Err(mismatch());
    }
    if gate.law_sha256() != Some(comparison.law_sha256.as_str()) {
        return Err(IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            format!("{}: LawGate and Lawbook hashes differ", case.id),
        ));
    }
    Ok(comparison)
}

pub fn integrity_scan(
    lawbook: &LocalLawbook,
    available_tools: &[&str],
    available_categories: &[&str],
    available_resolvers: &[&str],
) -> Vec<IntegrityFinding> {
    let tools: HashSet<&str> = available_tools.iter().copied().collect();
    let categories: HashSet<&str> = available_categories.iter().copied().collect();
    let resolvers: HashSet<&str> = available_resolvers.iter().copied().collect();
    let mut findings = Vec::new();
    for rule in &lawbook.rules {
        let unavailable_tool = rule.r#match.tools.as_ref().is_some_and(|selectors| {
            selectors.iter().any(|tool| !tools.contains(tool.as_str()))
        });
        let unavailable_category = rule.r#match.categories.as_ref().is_some_and(|selectors| {
            selectors.iter().any(|category| !categories.contains(category.as_str()))
        });
        if unavailable_tool || unavailable_category {
            findings.push(IntegrityFinding::advisory(
                IntegrityWitness::RuleUnreachable,
                format!("{}: no current tool/category can satisfy its selector", rule.rule_id),
            ));
        }
        if rule.decision == PolicyDecision::Deny {
            let prose_promises_appeal = rule.reason.as_deref().unwrap_or("").to_ascii_lowercase().contains("appeal");
            match &rule.resolution {
                Some(path) if path.kind == ResolutionKind::Appeal && !resolvers.contains(path.target.as_str()) => {
                    findings.push(IntegrityFinding::advisory(
                        IntegrityWitness::AppealPathUnreachable,
                        format!("{}: appeal resolver {} is unavailable", rule.rule_id, path.target),
                    ));
                }
                None if prose_promises_appeal => {
                    findings.push(IntegrityFinding::advisory(
                        IntegrityWitness::AppealPathUnreachable,
                        format!("{}: deny guidance names appeal without a structured resolution path", rule.rule_id),
                    ));
                }
                _ => {}
            }
        }
    }
    if lawbook.default_policy == PolicyDecision::Allow {
        let governed: HashSet<String> = lawbook.rules.iter().flat_map(|rule| {
            rule.r#match.categories.clone().unwrap_or_default()
        }).collect();
        for category in &categories {
            if !governed.contains(*category) {
                findings.push(IntegrityFinding::advisory(
                    IntegrityWitness::CategoryUngoverned,
                    format!("{category}: consequential category reaches the permissive default"),
                ));
            }
        }
    }
    findings
}

pub fn corpus_coverage(lawbook: &LocalLawbook, cases: &[LocalCase<'_>]) -> Vec<IntegrityFinding> {
    let projection = match lawbook.compile() {
        Ok(projection) => projection,
        Err(error) => return vec![IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            format!("the local Lawbook cannot be compiled: {error}"),
        )],
    };
    let engine = PolicyEngine::new(projection.config);
    let fired: HashSet<String> = cases.iter().filter_map(|case| engine.evaluate(&case.action).rule_id).collect();
    lawbook.rules.iter().filter(|rule| !fired.contains(&rule.rule_id)).map(|rule| {
        IntegrityFinding::advisory(
            IntegrityWitness::RuleNeverFiresOnCorpus,
            format!("{}: shipped conformance corpus never activates this rule", rule.rule_id),
        )
    }).collect()
}

/// Advisory witness that a role overlay may loosen its base.
///
/// The engine sorts by priority (lower first) and the first match wins, so an
/// overlay can widen a base in more ways than relaxing a rule in place. This
/// check reports:
///
/// 1. an overlay default less strict than the base default;
/// 2. a same-id rule whose decision is less severe;
/// 3. a same-id rule that keeps its decision but changes its matcher or its
///    priority — reported as *not checked*, because whether the new matcher
///    covers less (for a strict rule) or more (for a permissive one) is not
///    decided here;
/// 4. a rule the base does not have that *may outrank* a stricter base rule
///    (it is evaluated at or before that rule's priority; an equal priority is
///    a tie broken by config order), or that is less strict than the base
///    default it would pre-empt.
///
/// (3) and (4) are conservative: matcher overlap is not decided, so they can
/// fire on an overlay that is in fact disjoint from the stricter rule. They
/// never stay silent on the shape, which is the point of a witness.
///
/// NOT checked: a base rule that is absent from the overlay. Whether that is a
/// removal depends on whether the overlay replaces the base or is layered on
/// it, and this module does not define that composition.
pub fn overlay_widening(base: &LocalLawbook, overlay: &LocalLawbook) -> Vec<IntegrityFinding> {
    let mut findings = Vec::new();
    if overlay.default_policy.severity() < base.default_policy.severity() {
        findings.push(IntegrityFinding::advisory(
            IntegrityWitness::RoleOverlayWidensBase,
            "overlay default is less strict than base default",
        ));
    }
    for overlay_rule in &overlay.rules {
        if let Some(base_rule) = base.rules.iter().find(|rule| rule.rule_id == overlay_rule.rule_id) {
            if overlay_rule.decision.severity() < base_rule.decision.severity() {
                findings.push(IntegrityFinding::advisory(
                    IntegrityWitness::RoleOverlayWidensBase,
                    format!("{}: overlay relaxes {:?} to {:?}", overlay_rule.rule_id, base_rule.decision, overlay_rule.decision),
                ));
            } else if overlay_rule.r#match != base_rule.r#match || overlay_rule.priority != base_rule.priority {
                findings.push(IntegrityFinding::advisory(
                    IntegrityWitness::RoleOverlayWidensBase,
                    format!(
                        "{}: overlay changes the matcher or priority of a base rule; whether that widens the base was not checked",
                        overlay_rule.rule_id
                    ),
                ));
            }
            continue;
        }
        let severity = overlay_rule.decision.severity();
        let mut outranked: Vec<String> = base.rules.iter()
            .filter(|rule| rule.priority >= overlay_rule.priority && rule.decision.severity() > severity)
            .map(|rule| format!("{} ({:?}, priority {})", rule.rule_id, rule.decision, rule.priority))
            .collect();
        if base.default_policy.severity() > severity {
            outranked.push(format!("the base default ({:?})", base.default_policy));
        }
        if !outranked.is_empty() {
            findings.push(IntegrityFinding::advisory(
                IntegrityWitness::RoleOverlayWidensBase,
                format!(
                    "{}: new overlay rule ({:?}, priority {}) may outrank stricter base law: {}; matcher overlap was not decided",
                    overlay_rule.rule_id, overlay_rule.decision, overlay_rule.priority, outranked.join(", ")
                ),
            ));
        }
    }
    findings
}

pub fn projection_stale(lawbook: &LocalLawbook, active_projection_hash: &str) -> Vec<IntegrityFinding> {
    let Ok(projection) = lawbook.compile() else {
        return vec![IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            "the local Lawbook cannot be compiled",
        )];
    };
    if projection.source_projection_hash == active_projection_hash {
        Vec::new()
    } else {
        vec![IntegrityFinding::blocker(
            IntegrityWitness::PolicyProjectionStale,
            format!("active projection {active_projection_hash} != Lawbook projection {}", projection.source_projection_hash),
        )]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_policy::{EscalationTrigger, NoExtension, Norm, Operator};

    fn provenance(domain: AuthorityDomain) -> LawbookProvenance {
        LawbookProvenance {
            lawbook_id: "sprint-zero-local".into(),
            lawbook_version: "1.0.0".into(),
            authority_domain: domain,
            authority_ref: "operator".into(),
            effective_from: Some("2026-10-03T00:00:00Z".into()),
            effective_to: None,
            resolution: Some(ResolutionPath {
                kind: ResolutionKind::Appeal,
                target: "operator".into(),
                timeout_secs: Some(3600),
            }),
        }
    }

    fn local_book() -> LocalLawbook {
        LocalLawbook {
            provenance: provenance(AuthorityDomain::LocalOperator),
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![
                LocalRule {
                    rule_id: "deny-destructive-shell".into(),
                    rule_version: "1.0.0".into(),
                    name: "Block destructive shell commands".into(),
                    priority: 10,
                    decision: PolicyDecision::Deny,
                    reason: Some("destructive command; appeal to operator".into()),
                    r#match: PolicyMatch {
                        tools: Some(vec!["Bash".into()]),
                        command_patterns: Some(vec![r"rm\s+-rf".into()]),
                        command_patterns_are_regex: true,
                        target_patterns_scope: super::super::types::MatchScope::ExecutablePositions,
                        ..Default::default()
                    },
                    resolution: Some(ResolutionPath {
                        kind: ResolutionKind::Appeal,
                        target: "operator".into(),
                        timeout_secs: Some(3600),
                    }),
                },
                LocalRule {
                    rule_id: "deny-credential-read".into(),
                    rule_version: "1.0.0".into(),
                    name: "Block credential reads".into(),
                    priority: 20,
                    decision: PolicyDecision::Deny,
                    reason: Some("credential material".into()),
                    r#match: PolicyMatch {
                        categories: Some(vec!["credential_access".into()]),
                        target_patterns: Some(vec!["*/.ssh/*".into()]),
                        ..Default::default()
                    },
                    resolution: None,
                },
                LocalRule {
                    rule_id: "warn-network".into(),
                    rule_version: "1.0.0".into(),
                    name: "Warn on network".into(),
                    priority: 30,
                    decision: PolicyDecision::Warn,
                    reason: Some("network access".into()),
                    r#match: PolicyMatch {
                        categories: Some(vec!["network".into()]),
                        ..Default::default()
                    },
                    resolution: None,
                },
            ],
        }
    }

    fn local_cases() -> Vec<LocalCase<'static>> {
        vec![
            LocalCase {
                id: "destructive-shell",
                action: PolicyAction {
                    tool_name: "Bash",
                    category: "shell",
                    target: Some("rm"),
                    full_command: Some("rm -rf /tmp/data"),
                },
                expected_decision: PolicyDecision::Deny,
                expected_rule_id: Some("deny-destructive-shell"),
                expected_enforced: true,
            },
            LocalCase {
                id: "credential-read",
                action: PolicyAction {
                    tool_name: "Read",
                    category: "credential_access",
                    target: Some("/home/member/.ssh/id_ed25519"),
                    full_command: None,
                },
                expected_decision: PolicyDecision::Deny,
                expected_rule_id: Some("deny-credential-read"),
                expected_enforced: true,
            },
            LocalCase {
                id: "network",
                action: PolicyAction {
                    tool_name: "WebFetch",
                    category: "network",
                    target: Some("https://example.invalid"),
                    full_command: None,
                },
                expected_decision: PolicyDecision::Warn,
                expected_rule_id: Some("warn-network"),
                expected_enforced: true,
            },
            LocalCase {
                id: "ordinary-read",
                action: PolicyAction {
                    tool_name: "Read",
                    category: "file_read",
                    target: Some("README.md"),
                    full_command: None,
                },
                expected_decision: PolicyDecision::Allow,
                expected_rule_id: None,
                expected_enforced: true,
            },
        ]
    }

    fn society_book() -> SocietyLawbook {
        let law = Law {
            version: "1.0.0".into(),
            norms: vec![
                Norm {
                    id: "allow-read".into(),
                    selector: "r6.request.action".into(),
                    operator: Operator::Eq,
                    value: "Read".into(),
                    decision: Decision::Allow,
                    priority: 10,
                    description: Some("ordinary read".into()),
                },
                Norm {
                    id: "deny-secret".into(),
                    selector: "r6.request.payload.category".into(),
                    operator: Operator::Eq,
                    value: "credential_access".into(),
                    decision: Decision::Deny,
                    priority: 20,
                    description: Some("credential access refused".into()),
                },
                Norm {
                    id: "escalate-delete".into(),
                    selector: "r6.request.payload.category".into(),
                    operator: Operator::Eq,
                    value: "filesystem_delete".into(),
                    decision: Decision::Escalate,
                    priority: 30,
                    description: Some("deletion needs sovereign review".into()),
                },
            ],
            responses: Vec::new(),
            procedures: Vec::new(),
            escalation: vec![EscalationTrigger {
                condition: "r6.request.payload.category == 'filesystem_delete'".into(),
                escalate_to: "sovereign".into(),
                description: Some("sovereign reviews deletion".into()),
            }],
            custom_predicates: Vec::new(),
            ext: NoExtension {},
        };
        SocietyLawbook::new(provenance(AuthorityDomain::SocietyHub), law).unwrap()
    }

    fn society_case(id: &'static str, action: &str, category: &str) -> SocietyCase {
        let mut payload = serde_yaml::Mapping::new();
        payload.insert("category".into(), category.into());
        SocietyCase {
            id,
            request: R6Request {
                role: "role:constellation:member".into(),
                action: action.into(),
                payload: serde_yaml::Value::Mapping(payload),
                resource: Default::default(),
            },
        }
    }

    #[test]
    fn current_safety_preset_round_trips_without_semantic_loss() {
        let preset = super::super::presets::get_preset("safety").unwrap();
        let book = LocalLawbook::from_policy_config(
            provenance(AuthorityDomain::LocalOperator),
            &preset.config,
            "1.0.0",
        ).unwrap();
        let hand_authored = book.compile().unwrap().config;
        assert_eq!(hand_authored, preset.config);
        let case = LocalCase {
            id: "preset-destructive-shell",
            action: PolicyAction {
                tool_name: "Bash",
                category: "shell",
                target: Some("rm -rf /var/data"),
                full_command: Some("rm -rf /var/data"),
            },
            expected_decision: PolicyDecision::Deny,
            expected_rule_id: Some("deny-destructive-commands"),
            expected_enforced: true,
        };
        run_local_cases(&book, &hand_authored, &[case]).unwrap();
    }

    #[test]
    fn local_projection_preserves_config_and_all_decisions() {
        let book = local_book();
        let hand_authored = book.compile().unwrap().config;
        let evaluations = run_local_cases(&book, &hand_authored, &local_cases()).unwrap();
        assert_eq!(evaluations.len(), 4);
        let mut audit = hand_authored.clone();
        audit.enforce = false;
        let evaluation = PolicyEngine::new(audit).evaluate(&local_cases()[0].action);
        assert_eq!(evaluation.decision, PolicyDecision::Deny);
        assert!(!evaluation.enforced, "audit-only must remain audit-only");
    }

    #[test]
    fn local_projection_binds_provenance_and_detects_staleness() {
        let book = local_book();
        let projection = book.compile().unwrap();
        assert_eq!(projection.provenance.lawbook_id, "sprint-zero-local");
        assert_eq!(projection.source_projection_hash.len(), 64);
        assert!(projection_stale(&book, &projection.source_projection_hash).is_empty());
        let stale = projection_stale(&book, "deadbeef");
        assert_eq!(stale.len(), 1);
        assert_eq!(stale[0].witness, IntegrityWitness::PolicyProjectionStale);
        assert_eq!(stale[0].severity, WitnessSeverity::Blocker);
    }

    #[test]
    fn society_yaml_projection_preserves_the_source_hash() {
        let yaml = "version: 1.0.0\n";
        let book = SocietyLawbook::from_yaml("sprint-zero-society", "hub", yaml).unwrap();
        let expected = Law::<NoExtension>::sha256_hex_of(yaml);
        assert_eq!(book.projection_hash().unwrap(), expected);
        assert_eq!(book.compile().unwrap().law_sha256(), Some(expected.as_str()));
    }

    #[test]
    fn society_projection_matches_hub_and_lawgate() {
        let book = society_book();
        for (case, expected) in [
            (
                society_case("ordinary-allow", "Read", "file_read"),
                SocietyExpectation { decision: PolicyDecision::Allow, winning_rule: Some("law:allow-read"), escalation_target: None },
            ),
            (
                society_case("explicit-deny", "Read", "credential_access"),
                SocietyExpectation { decision: PolicyDecision::Deny, winning_rule: Some("law:deny-secret"), escalation_target: None },
            ),
            (
                society_case("named-escalation", "Bash", "filesystem_delete"),
                SocietyExpectation { decision: PolicyDecision::Deny, winning_rule: Some("law:escalate-delete"), escalation_target: Some("sovereign") },
            ),
            (
                society_case("no-match", "WebFetch", "network"),
                SocietyExpectation { decision: PolicyDecision::Allow, winning_rule: None, escalation_target: None },
            ),
        ] {
            let comparison = compare_society_case(&book, &case, &expected).unwrap();
            assert_eq!(comparison.lawbook_version, "1.0.0");
            assert_eq!(comparison.law_sha256.len(), 64);
        }
    }

    #[test]
    fn a_seeded_society_mismatch_is_a_witness() {
        let book = society_book();
        let case = society_case("wrong-expectation", "Read", "file_read");
        let expected = SocietyExpectation {
            decision: PolicyDecision::Deny,
            winning_rule: Some("law:allow-read"),
            escalation_target: None,
        };
        let finding = compare_society_case(&book, &case, &expected).unwrap_err();
        assert_eq!(finding.witness, IntegrityWitness::HubHestiaDecisionMismatch);
        assert_eq!(finding.severity, WitnessSeverity::Blocker);
    }

    #[test]
    fn clean_fixture_has_no_unexpected_integrity_findings() {
        let book = local_book();
        assert!(integrity_scan(&book, &["Bash", "Read", "WebFetch"], &["credential_access", "network"], &["operator"]).is_empty());
        assert!(corpus_coverage(&book, &local_cases()).is_empty());
        assert!(overlay_widening(&book, &book).is_empty());
    }

    #[test]
    fn broken_fixtures_compute_all_initial_witnesses() {
        let mut book = local_book();
        book.rules.push(LocalRule {
            rule_id: "unreachable".into(),
            rule_version: "1.0.0".into(),
            name: "Unreachable".into(),
            priority: 99,
            decision: PolicyDecision::Deny,
            reason: Some("never matches".into()),
            r#match: PolicyMatch {
                tools: Some(vec!["NoSuchTool".into()]),
                categories: Some(vec!["unimplemented_action".into()]),
                ..Default::default()
            },
            resolution: Some(ResolutionPath {
                kind: ResolutionKind::Appeal,
                target: "absent-resolver".into(),
                timeout_secs: None,
            }),
        });
        book.rules[0].resolution = None;
        let findings = integrity_scan(
            &book,
            &["Bash", "Read", "WebFetch"],
            &["credential_access", "network", "filesystem_delete"],
            &["operator"],
        );
        assert!(findings.iter().any(|finding| finding.witness == IntegrityWitness::RuleUnreachable));
        assert!(findings.iter().any(|finding| finding.witness == IntegrityWitness::CategoryUngoverned));
        assert!(findings.iter().any(|finding| finding.witness == IntegrityWitness::AppealPathUnreachable));
        assert!(corpus_coverage(&book, &local_cases()).iter().any(|finding| finding.witness == IntegrityWitness::RuleNeverFiresOnCorpus));

        let mut overlay = local_book();
        overlay.rules[2].decision = PolicyDecision::Allow;
        assert!(overlay_widening(&book, &overlay).iter().any(|finding| finding.witness == IntegrityWitness::RoleOverlayWidensBase));
    }

    fn overlay_rule(id: &str, priority: i32, decision: PolicyDecision) -> LocalRule {
        LocalRule {
            rule_id: id.into(),
            rule_version: "1.0.0".into(),
            name: id.into(),
            priority,
            decision,
            reason: None,
            r#match: PolicyMatch {
                tools: Some(vec!["Bash".into()]),
                command_patterns: Some(vec![r"rm\s".into()]),
                command_patterns_are_regex: true,
                ..Default::default()
            },
            resolution: None,
        }
    }

    fn widening(findings: &[IntegrityFinding]) -> Vec<&str> {
        findings.iter()
            .filter(|finding| finding.witness == IntegrityWitness::RoleOverlayWidensBase)
            .map(|finding| finding.evidence.as_str())
            .collect()
    }

    /// mcnugget-claude's hold on #1695: the engine is priority-ordered and
    /// first-match-wins, so the usual way to widen a base is to ADD a rule that
    /// is evaluated before a stricter base rule. The shipped preset does this on
    /// purpose (`allow-rm-whitelisted-scratch` at 0 carves
    /// `deny-destructive-commands` at 1). A new-id rule used to yield no finding.
    #[test]
    fn a_new_overlay_rule_that_may_outrank_a_stricter_base_rule_is_a_widening_witness() {
        let preset = super::super::presets::get_preset("safety").unwrap();
        let base = LocalLawbook::from_policy_config(
            provenance(AuthorityDomain::LocalOperator), &preset.config, "1.0.0",
        ).unwrap();
        let mut overlay = base.clone();
        overlay.provenance.authority_domain = AuthorityDomain::RoleOverlay;
        overlay.rules.push(overlay_rule("allow-rm-anywhere", 0, PolicyDecision::Allow));

        // The widening is real, not hypothetical: the overlay turns a Deny into an Allow.
        let action = PolicyAction {
            tool_name: "Bash",
            category: "shell",
            target: Some("rm -rf /var/data"),
            full_command: Some("rm -rf /var/data"),
        };
        let before = PolicyEngine::new(base.compile().unwrap().config).evaluate(&action);
        assert_eq!(before.decision, PolicyDecision::Deny);
        let mut widened = overlay.compile().unwrap().config;
        // Put the overlay rule first so the equal-priority tie resolves its way.
        widened.rules.rotate_right(1);
        let after = PolicyEngine::new(widened).evaluate(&action);
        assert_eq!(after.decision, PolicyDecision::Allow);
        assert_eq!(after.rule_id.as_deref(), Some("allow-rm-anywhere"));

        let findings = overlay_widening(&base, &overlay);
        let evidence = widening(&findings);
        assert!(
            evidence.iter().any(|text| text.contains("allow-rm-anywhere") && text.contains("deny-destructive-commands")),
            "a new priority-0 Allow over the safety preset must be a widening witness, got {evidence:?}"
        );
        assert!(findings.iter().all(|finding| finding.severity == WitnessSeverity::Advisory));
    }

    /// Negative controls: the new arm must not fire on additions that cannot widen.
    #[test]
    fn overlay_additions_that_cannot_outrank_a_stricter_base_rule_are_not_widening() {
        let base = local_book(); // default Allow; Deny@10, Deny@20, Warn@30

        // A new Deny evaluated first only tightens.
        let mut tighter = base.clone();
        tighter.rules.push(overlay_rule("deny-rm", 0, PolicyDecision::Deny));
        assert!(widening(&overlay_widening(&base, &tighter)).is_empty());

        // A new Allow evaluated after every stricter base rule, under an Allow default.
        let mut late = base.clone();
        late.rules.push(overlay_rule("allow-rm-late", 31, PolicyDecision::Allow));
        assert!(widening(&overlay_widening(&base, &late)).is_empty());

        // A new Warn between the Denies and the Warn outranks nothing stricter.
        let mut warn = base.clone();
        warn.rules.push(overlay_rule("warn-rm", 25, PolicyDecision::Warn));
        assert!(widening(&overlay_widening(&base, &warn)).is_empty());

        // Boundary: equal priority is a tie the engine breaks by config order, so it counts.
        let mut tie = base.clone();
        tie.rules.push(overlay_rule("allow-rm-tie", 30, PolicyDecision::Allow));
        let tie_findings = overlay_widening(&base, &tie);
        let evidence = widening(&tie_findings);
        assert_eq!(evidence.len(), 1, "{evidence:?}");
        assert!(evidence[0].contains("allow-rm-tie") && evidence[0].contains("warn-network"));
        assert!(!evidence[0].contains("deny-credential-read"), "priority 20 is evaluated first: {evidence:?}");
    }

    /// A new rule that outranks no base rule still widens when it is less strict
    /// than the default the action would otherwise have reached.
    #[test]
    fn a_new_overlay_rule_less_strict_than_the_base_default_is_a_widening_witness() {
        let mut base = local_book();
        base.default_policy = PolicyDecision::Deny;
        let mut overlay = base.clone();
        overlay.rules.push(overlay_rule("allow-rm-late", 99, PolicyDecision::Allow));
        let findings = overlay_widening(&base, &overlay);
        let evidence = widening(&findings);
        assert_eq!(evidence.len(), 1, "{evidence:?}");
        assert!(evidence[0].contains("allow-rm-late") && evidence[0].contains("base default"));
    }

    /// A same-id rule that keeps its decision can still widen by moving in the
    /// order or by changing what it matches. Matcher containment is not decided
    /// here, so the report must say "not checked" rather than stay silent.
    #[test]
    fn a_same_id_overlay_rule_with_a_changed_matcher_or_priority_is_reported_as_unchecked() {
        let base = local_book();
        let mut narrowed = base.clone();
        narrowed.rules[0].r#match.command_patterns = Some(vec![r"rm\s+-rf\s+/$".into()]);
        let narrowed_findings = overlay_widening(&base, &narrowed);
        let evidence = widening(&narrowed_findings);
        assert_eq!(evidence.len(), 1, "{evidence:?}");
        assert!(evidence[0].contains("deny-destructive-shell") && evidence[0].contains("not checked"));

        let mut moved = base.clone();
        moved.rules[2].priority = 5;
        let moved_findings = overlay_widening(&base, &moved);
        let evidence = widening(&moved_findings);
        assert_eq!(evidence.len(), 1, "{evidence:?}");
        assert!(evidence[0].contains("warn-network") && evidence[0].contains("not checked"));
    }

    #[test]
    fn invalid_local_books_and_society_yaml_fail_closed() {
        let mut duplicate = local_book();
        duplicate.rules.push(duplicate.rules[0].clone());
        assert!(duplicate.compile().is_err());
        let coverage = corpus_coverage(&duplicate, &local_cases());
        assert_eq!(coverage.len(), 1);
        assert_eq!(coverage[0].witness, IntegrityWitness::PolicyProjectionStale);
        assert_eq!(coverage[0].severity, WitnessSeverity::Blocker);
        assert!(SocietyLawbook::from_yaml("broken", "hub", "version: not-a-version\n").is_err());
    }
}
