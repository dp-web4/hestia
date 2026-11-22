//! Governance Twin shadow evaluation, ratified activation, and learning evidence.
//!
//! Candidates never block an act and never mutate active policy. Only an exact,
//! ratified projection can be returned for activation by the caller.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};

use super::engine::PolicyEngine;
use super::law_gate::LawGate;
use super::lawbook::{LocalLawbook, LocalProjection, ResolutionPath, SocietyLawbook};
use super::types::{PolicyAction, PolicyConfig, PolicyEvaluation};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstitutionalSourceKind {
    Document,
    Interview,
    Observation,
    ApprovalMatrix,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstitutionalSourceRef {
    pub source_id: String,
    pub kind: InstitutionalSourceKind,
    pub reference: String,
    pub provenance: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RatificationRef {
    pub authority: String,
    pub reference: String,
    pub effective_from: Option<String>,
    pub effective_to: Option<String>,
    pub signed_projection_sha256: String,
}

#[derive(Debug, Clone)]
pub struct CandidateProjection {
    pub lawbook: LocalLawbook,
    pub institutional_sources: Vec<InstitutionalSourceRef>,
    pub ratification: Option<RatificationRef>,
}

#[derive(Debug, Clone)]
pub struct SocietyCandidateProjection {
    pub lawbook: SocietyLawbook,
    pub institutional_sources: Vec<InstitutionalSourceRef>,
    pub ratification: Option<RatificationRef>,
}

#[derive(Debug, Clone)]
pub struct ShadowContext<'a> {
    pub actor_role: &'a str,
    pub origin_mrh: &'a str,
    pub society_context: &'a str,
    pub seat_context: &'a str,
    pub category: &'a str,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShadowDecision {
    pub candidate: PolicyEvaluation,
    pub active: PolicyEvaluation,
    pub divergence: bool,
    pub institutional_sources: Vec<InstitutionalSourceRef>,
    pub ratification: Option<RatificationRef>,
    pub resolution: Option<ResolutionPath>,
    pub lawbook_id: String,
    pub lawbook_version: String,
    pub source_projection_hash: String,
    pub actor_role: String,
    pub origin_mrh: String,
    pub society_context: String,
    pub seat_context: String,
    pub category: String,
}

fn resolution_for(lawbook: &LocalLawbook, evaluation: &PolicyEvaluation) -> Option<ResolutionPath> {
    evaluation.rule_id.as_ref().and_then(|id| {
        lawbook.rules.iter().find(|rule| &rule.rule_id == id).and_then(|rule| rule.resolution.clone())
    }).or_else(|| lawbook.provenance.resolution.clone())
}

pub fn shadow_local(
    candidate: &CandidateProjection,
    active_config: &PolicyConfig,
    context: ShadowContext<'_>,
    action: &PolicyAction<'_>,
    actual: Option<PolicyEvaluation>,
) -> Result<ShadowDecision> {
    let projection = candidate.lawbook.compile()?;
    let candidate_eval = PolicyEngine::new(projection.config).evaluate(action);
    let active_eval = match actual {
        Some(actual) => actual,
        None => PolicyEngine::new(active_config.clone()).evaluate(action),
    };
    let divergence = candidate_eval.decision != active_eval.decision
        || candidate_eval.rule_id != active_eval.rule_id
        || candidate_eval.enforced != active_eval.enforced;
    Ok(ShadowDecision {
        resolution: resolution_for(&candidate.lawbook, &candidate_eval),
        candidate: candidate_eval,
        active: active_eval,
        divergence,
        institutional_sources: candidate.institutional_sources.clone(),
        ratification: candidate.ratification.clone(),
        lawbook_id: candidate.lawbook.provenance.lawbook_id.clone(),
        lawbook_version: candidate.lawbook.provenance.lawbook_version.clone(),
        source_projection_hash: projection.source_projection_hash,
        actor_role: context.actor_role.into(),
        origin_mrh: context.origin_mrh.into(),
        society_context: context.society_context.into(),
        seat_context: context.seat_context.into(),
        category: context.category.into(),
    })
}

pub fn shadow_society(
    candidate: &SocietyCandidateProjection,
    active_config: &PolicyConfig,
    context: ShadowContext<'_>,
    action: &PolicyAction<'_>,
    role: &str,
    actual: Option<PolicyEvaluation>,
) -> Result<ShadowDecision> {
    let gate = candidate.lawbook.compile()?;
    let candidate_eval = gate.evaluate(action, role);
    let active_eval = match actual {
        Some(actual) => actual,
        None => PolicyEngine::new(active_config.clone()).evaluate(action),
    };
    let divergence = candidate_eval.decision != active_eval.decision
        || candidate_eval.rule_id != active_eval.rule_id
        || candidate_eval.enforced != active_eval.enforced;
    Ok(ShadowDecision {
        resolution: candidate.lawbook.provenance.resolution.clone(),
        candidate: candidate_eval,
        active: active_eval,
        divergence,
        institutional_sources: candidate.institutional_sources.clone(),
        ratification: candidate.ratification.clone(),
        lawbook_id: candidate.lawbook.provenance.lawbook_id.clone(),
        lawbook_version: candidate.lawbook.provenance.lawbook_version.clone(),
        source_projection_hash: candidate.lawbook.projection_hash()?,
        actor_role: context.actor_role.into(),
        origin_mrh: context.origin_mrh.into(),
        society_context: context.society_context.into(),
        seat_context: context.seat_context.into(),
        category: context.category.into(),
    })
}

fn validate_ratification(
    ratification: Option<&RatificationRef>,
    expected_hash: &str,
    valid_at: &str,
) -> Result<()> {
    let ratification = ratification.ok_or_else(|| anyhow::anyhow!("a ratification reference is required"))?;
    ensure!(!ratification.authority.trim().is_empty(), "ratification authority is required");
    ensure!(!ratification.reference.trim().is_empty(), "ratification reference is required");
    ensure!(ratification.signed_projection_sha256 == expected_hash, "signed projection hash does not match the Lawbook projection");
    if let Some(from) = &ratification.effective_from {
        ensure!(valid_at >= from.as_str(), "the ratified projection is not yet effective");
    }
    if let Some(to) = &ratification.effective_to {
        ensure!(valid_at <= to.as_str(), "the ratified projection is expired or superseded");
    }
    Ok(())
}

pub fn activate_local(candidate: &CandidateProjection, valid_at: &str) -> Result<LocalProjection> {
    let projection = candidate.lawbook.compile()?;
    validate_ratification(
        candidate.ratification.as_ref(),
        &projection.source_projection_hash,
        valid_at,
    )?;
    Ok(projection)
}

pub fn activate_society(candidate: &SocietyCandidateProjection, valid_at: &str) -> Result<LawGate> {
    let hash = candidate.lawbook.projection_hash()?;
    validate_ratification(candidate.ratification.as_ref(), &hash, valid_at)?;
    candidate.lawbook.compile()
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ShadowStats {
    pub total: usize,
    pub divergent: usize,
    pub by_candidate_rule: BTreeMap<String, usize>,
    pub by_category: BTreeMap<String, usize>,
}

impl ShadowStats {
    pub fn from_decisions(decisions: &[ShadowDecision]) -> Self {
        let mut stats = Self::default();
        for decision in decisions {
            stats.total += 1;
            *stats.by_candidate_rule.entry(decision.candidate.rule_id.clone().unwrap_or_else(|| "default".into())).or_default() += 1;
            *stats.by_category.entry(decision.category.clone()).or_default() += 1;
            if decision.divergence {
                stats.divergent += 1;
            }
        }
        stats
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ElicitedClaim {
    pub id: String,
    pub text: String,
    pub source: InstitutionalSourceRef,
    pub authoritative: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClarificationQuestion {
    pub id: String,
    pub prompt: String,
    pub route_to: String,
    pub origin_mrh: String,
    pub role_context: String,
    pub answered: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapStatus {
    Open,
    Answered,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KnowledgeGap {
    pub id: String,
    pub question_id: String,
    pub topic: String,
    pub status: GapStatus,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RuntimeWitnessExport {
    pub observations: usize,
    pub divergent: usize,
    pub repeated_exceptions: BTreeMap<String, usize>,
    pub category_coverage: BTreeMap<String, usize>,
    pub resolver_usage: BTreeMap<String, usize>,
    pub role_usage: BTreeMap<String, usize>,
    pub rule_firings: BTreeMap<String, usize>,
    pub open_gaps: Vec<KnowledgeGap>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SituateState {
    pub observations: Vec<ShadowDecision>,
    pub claims: Vec<ElicitedClaim>,
    pub questions: Vec<ClarificationQuestion>,
    pub answers: Vec<ElicitedClaim>,
    pub contradictions: Vec<String>,
    pub knowledge_gaps: Vec<KnowledgeGap>,
}

pub struct SituateStore {
    path: PathBuf,
    pub state: SituateState,
}

impl SituateStore {
    pub fn load(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        let state = match std::fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes)?,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => SituateState::default(),
            Err(error) => return Err(error.into()),
        };
        Ok(Self { path, state })
    }

    fn save_json<T: Serialize>(path: &Path, value: &T) -> Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, serde_json::to_vec_pretty(value)?)?;
        std::fs::rename(temporary, path)?;
        Ok(())
    }

    pub fn save(&self) -> Result<()> {
        Self::save_json(&self.path, &self.state)
    }

    pub fn observe(&mut self, observation: ShadowDecision) -> Result<Option<ClarificationQuestion>> {
        let mut question = None;
        if observation.divergence {
            self.state.contradictions.push(format!(
                "{}: candidate={:?}/active={:?}",
                observation.category, observation.candidate.decision, observation.active.decision
            ));
            let topic = observation.candidate.rule_id.clone().unwrap_or_else(|| "default".into());
            let question_id = format!("question-{}", self.state.questions.len() + 1);
            if !self.state.knowledge_gaps.iter().any(|gap| gap.topic == topic && gap.status == GapStatus::Open) {
                self.state.knowledge_gaps.push(KnowledgeGap {
                    id: format!("gap-{}", self.state.knowledge_gaps.len() + 1),
                    question_id: question_id.clone(),
                    topic: topic.clone(),
                    status: GapStatus::Open,
                });
            }
            let route_to = observation.resolution.as_ref().map(|path| path.target.clone())
                .unwrap_or_else(|| observation.ratification.as_ref().map(|rat| rat.authority.clone())
                    .unwrap_or_else(|| "operator".into()));
            let prompt = format!(
                "{} performs {} in {}: candidate governance says {:?}, active governance says {:?}. Is this an approved exception, a missing delegation, or a policy mismatch?",
                observation.actor_role, observation.category, observation.origin_mrh,
                observation.candidate.decision, observation.active.decision
            );
            if !self.state.questions.iter().any(|q| q.prompt == prompt && !q.answered) {
                let next = ClarificationQuestion {
                    id: question_id,
                    prompt,
                    route_to,
                    origin_mrh: observation.origin_mrh.clone(),
                    role_context: observation.actor_role.clone(),
                    answered: false,
                };
                self.state.questions.push(next.clone());
                question = Some(next);
            }
        }
        self.state.observations.push(observation);
        self.save()?;
        Ok(question)
    }

    pub fn answer(&mut self, question_id: &str, claim: ElicitedClaim) -> Result<()> {
        ensure!(!claim.text.trim().is_empty(), "an elicited answer cannot be empty");
        let question = self.state.questions.iter_mut().find(|question| question.id == question_id)
            .ok_or_else(|| anyhow::anyhow!("unknown clarification question {question_id}"))?;
        ensure!(!question.answered, "question {question_id} is already answered");
        question.answered = true;
        for gap in &mut self.state.knowledge_gaps {
            if gap.question_id == question_id {
                gap.status = GapStatus::Answered;
            }
        }
        let mut claim = claim;
        claim.authoritative = false;
        self.state.answers.push(claim.clone());
        self.state.claims.push(claim);
        self.save()
    }

    pub fn export(&self) -> RuntimeWitnessExport {
        let mut export = RuntimeWitnessExport {
            observations: self.state.observations.len(),
            divergent: self.state.observations.iter().filter(|observation| observation.divergence).count(),
            open_gaps: self.state.knowledge_gaps.iter().filter(|gap| gap.status == GapStatus::Open).cloned().collect(),
            ..Default::default()
        };
        for observation in &self.state.observations {
            *export.category_coverage.entry(observation.category.clone()).or_default() += 1;
            if observation.divergence {
                *export.repeated_exceptions.entry(observation.category.clone()).or_default() += 1;
            }
            *export.role_usage.entry(observation.actor_role.clone()).or_default() += 1;
            *export.rule_firings.entry(observation.candidate.rule_id.clone().unwrap_or_else(|| "default".into())).or_default() += 1;
            if let Some(path) = &observation.resolution {
                *export.resolver_usage.entry(path.target.clone()).or_default() += 1;
            }
        }
        export
    }

    pub fn export_to(&self, path: &Path) -> Result<()> {
        Self::save_json(path, &self.export())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::lawbook::{
        AuthorityDomain, LawbookProvenance, LocalRule, ResolutionKind, SocietyLawbook,
    };
    use crate::policy::types::{MatchScope, PolicyDecision, PolicyMatch};
    use web4_policy::{Decision, EscalationTrigger, Law, NoExtension, Norm, Operator};

    fn provenance() -> LawbookProvenance {
        LawbookProvenance {
            lawbook_id: "governance-twin-pilot".into(),
            lawbook_version: "1.0.0".into(),
            authority_domain: AuthorityDomain::LocalOperator,
            authority_ref: "operator".into(),
            effective_from: Some("2026-10-01T00:00:00Z".into()),
            effective_to: Some("2026-12-31T23:59:59Z".into()),
            resolution: Some(ResolutionPath {
                kind: ResolutionKind::Escalation,
                target: "release-manager".into(),
                timeout_secs: Some(3600),
            }),
        }
    }

    fn candidate_book() -> LocalLawbook {
        LocalLawbook {
            provenance: provenance(),
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![LocalRule {
                rule_id: "deploy-requires-approval".into(),
                rule_version: "1.0.0".into(),
                name: "Production deploy requires release approval".into(),
                priority: 1,
                decision: PolicyDecision::Deny,
                reason: Some("release manager approval required".into()),
                r#match: PolicyMatch {
                    tools: Some(vec!["Bash".into()]),
                    categories: Some(vec!["production_deploy".into()]),
                    target_patterns_scope: MatchScope::ExecutablePositions,
                    ..Default::default()
                },
                resolution: Some(ResolutionPath {
                    kind: ResolutionKind::Escalation,
                    target: "release-manager".into(),
                    timeout_secs: Some(3600),
                }),
            }],
        }
    }

    fn sources() -> Vec<InstitutionalSourceRef> {
        vec![InstitutionalSourceRef {
            source_id: "interview-release-process".into(),
            kind: InstitutionalSourceKind::Interview,
            reference: "interviews/2026-09-12-release-manager".into(),
            provenance: Some("release manager interview".into()),
        }]
    }

    fn candidate() -> CandidateProjection {
        let lawbook = candidate_book();
        let signed_projection_sha256 = lawbook.compile().unwrap().source_projection_hash;
        CandidateProjection {
            lawbook,
            institutional_sources: sources(),
            ratification: Some(RatificationRef {
                authority: "release-manager".into(),
                reference: "ratifications/2026-10-03-deploy".into(),
                effective_from: Some("2026-10-01T00:00:00Z".into()),
                effective_to: Some("2026-12-31T23:59:59Z".into()),
                signed_projection_sha256,
            }),
        }
    }

    fn context() -> ShadowContext<'static> {
        ShadowContext {
            actor_role: "role:constellation:interactive-dev",
            origin_mrh: "service:pilot",
            society_context: "society:example",
            seat_context: "seat:pilot",
            category: "production_deploy",
        }
    }

    fn deploy_action<'a>() -> PolicyAction<'a> {
        PolicyAction {
            tool_name: "Bash",
            category: "production_deploy",
            target: Some("./deploy.sh"),
            full_command: Some("./deploy.sh"),
        }
    }

    fn observation(candidate: &CandidateProjection) -> ShadowDecision {
        shadow_local(candidate, &PolicyConfig {
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![],
        }, context(), &deploy_action(), None).unwrap()
    }

    #[test]
    fn shadow_records_divergence_without_blocking_or_changing_law() {
        let candidate = candidate();
        let active = PolicyConfig {
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![],
        };
        let decision = observation(&candidate);
        assert_eq!(decision.candidate.decision, PolicyDecision::Deny);
        assert_eq!(decision.active.decision, PolicyDecision::Allow);
        assert!(decision.divergence);
        assert_eq!(decision.institutional_sources, sources());
        assert_eq!(decision.resolution.as_ref().unwrap().target, "release-manager");
        assert_eq!(active.default_policy, PolicyDecision::Allow);
        assert_eq!(active.rules.len(), 0);
        let stats = ShadowStats::from_decisions(&[decision]);
        assert_eq!((stats.total, stats.divergent), (1, 1));
        assert_eq!(stats.by_category["production_deploy"], 1);
    }

    #[test]
    fn activation_requires_exact_ratified_projection() {
        let candidate = candidate();
        let expected = candidate.lawbook.compile().unwrap().config;
        let activated = activate_local(&candidate, "2026-11-01T00:00:00Z").unwrap();
        assert_eq!(activated.config, expected);
        let ordinary = PolicyAction {
            tool_name: "Read",
            category: "file_read",
            target: Some("README.md"),
            full_command: None,
        };
        assert_eq!(PolicyEngine::new(activated.config).evaluate(&ordinary).decision, PolicyDecision::Allow);
        assert!(activate_local(&candidate, "2027-01-01T00:00:00Z").is_err());
        let mut missing = candidate.clone();
        missing.ratification = None;
        assert!(activate_local(&missing, "2026-11-01T00:00:00Z").is_err());
        let mut wrong_hash = candidate.clone();
        wrong_hash.ratification.as_mut().unwrap().signed_projection_sha256 = "0".repeat(64);
        assert!(activate_local(&wrong_hash, "2026-11-01T00:00:00Z").is_err());
    }

    #[test]
    fn situate_persists_learning_without_turning_it_into_law() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("situate.json");
        let candidate = candidate();
        let mut store = SituateStore::load(&path).unwrap();
        assert!(store.observe(observation(&candidate)).unwrap().is_some());
        assert!(store.observe(observation(&candidate)).unwrap().is_none());
        store.save().unwrap();
        let mut reloaded = SituateStore::load(&path).unwrap();
        assert_eq!(reloaded.state.observations.len(), 2);
        assert_eq!(reloaded.state.questions.len(), 1);
        assert_eq!(reloaded.state.contradictions.len(), 2);
        let export = reloaded.export();
        assert_eq!(export.repeated_exceptions["production_deploy"], 2);
        assert_eq!(export.category_coverage["production_deploy"], 2);
        assert_eq!(export.role_usage["role:constellation:interactive-dev"], 2);
        assert_eq!(export.rule_firings["deploy-requires-approval"], 2);
        assert_eq!(export.resolver_usage["release-manager"], 2);
        let question = reloaded.state.questions[0].id.clone();
        reloaded.answer(&question, ElicitedClaim {
            id: "answer-after-hours".into(),
            text: "After-hours emergency deploys use a different delegated approval.".into(),
            source: sources()[0].clone(),
            authoritative: false,
        }).unwrap();
        let export_path = dir.path().join("witness-export.json");
        reloaded.export_to(&export_path).unwrap();
        let final_store = SituateStore::load(&path).unwrap();
        assert!(final_store.state.questions[0].answered);
        assert_eq!(final_store.state.knowledge_gaps.len(), 1);
        assert_eq!(final_store.state.knowledge_gaps[0].status, GapStatus::Answered);
        assert!(final_store.state.answers.iter().all(|answer| !answer.authoritative));
        assert!(export_path.exists());
    }

    #[test]
    fn society_shadow_and_activation_use_the_existing_lawgate() {
        let law = Law {
            version: "1.0.0".into(),
            norms: vec![Norm {
                id: "society-deploy-approval".into(),
                selector: "r6.request.payload.category".into(),
                operator: Operator::Eq,
                value: "production_deploy".into(),
                decision: Decision::Escalate,
                priority: 1,
                description: Some("society release control".into()),
            }],
            responses: Vec::new(),
            procedures: Vec::new(),
            escalation: vec![EscalationTrigger {
                condition: "r6.request.payload.category == 'production_deploy'".into(),
                escalate_to: "sovereign".into(),
                description: Some("sovereign review".into()),
            }],
            custom_predicates: Vec::new(),
            ext: NoExtension {},
        };
        let mut society_provenance = provenance();
        society_provenance.authority_domain = AuthorityDomain::SocietyHub;
        let society = SocietyLawbook::new(society_provenance, law).unwrap();
        let signed_projection_sha256 = society.projection_hash().unwrap();
        let candidate = SocietyCandidateProjection {
            lawbook: society,
            institutional_sources: sources(),
            ratification: Some(RatificationRef {
                authority: "release-manager".into(),
                reference: "ratifications/2026-10-03-society".into(),
                effective_from: Some("2026-10-01T00:00:00Z".into()),
                effective_to: Some("2026-12-31T23:59:59Z".into()),
                signed_projection_sha256,
            }),
        };
        let decision = shadow_society(&candidate, &PolicyConfig {
            default_policy: PolicyDecision::Allow,
            enforce: true,
            rules: vec![],
        }, context(), &deploy_action(), "role:constellation:member", None).unwrap();
        assert_eq!(decision.candidate.decision, PolicyDecision::Deny);
        assert!(decision.candidate.constraints.contains(&"escalate_to:sovereign".into()));
        assert!(decision.divergence);
        assert!(activate_society(&candidate, "2026-11-01T00:00:00Z").is_ok());
    }
}
