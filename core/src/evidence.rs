//! Typed evidence primitives for witnessed V3 inputs.
//!
//! These types describe evidence; they do not compute or mutate T3. Raw events
//! remain append-only, and later derivations can interpret them by schema
//! version without rewriting history.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fmt;
use std::str::FromStr;

pub const CLOSURE_CLAIMS_SCHEMA_V1: &str = "hestia.closure-claims/v1";
pub const MAX_CLOSURE_CLAIMS: usize = 32;
const MAX_CLAIM_ID_LEN: usize = 128;
const MAX_STATEMENT_LEN: usize = 4096;
const MAX_SCOPE_LEN: usize = 2048;
const MAX_EVIDENCE_REFS: usize = 32;
const MAX_EVIDENCE_REF_LEN: usize = 1024;
const MAX_LIMITATIONS: usize = 32;
const MAX_LIMITATION_LEN: usize = 2048;

/// An explicit claim made by the actor when closing an action.
///
/// Claims are optional, but every submitted claim must be scoped, calibrated,
/// and evidence-linked. The daemon never manufactures implied claims from an
/// outcome or tool result.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClosureClaim {
    pub claim_id: String,
    pub statement: String,
    pub scope: String,
    pub confidence: f64,
    pub evidence: Vec<String>,
    #[serde(default)]
    pub known_limitations: Vec<String>,
}

impl ClosureClaim {
    fn validate(&self) -> Result<(), String> {
        validate_nonempty_bounded("claim_id", &self.claim_id, MAX_CLAIM_ID_LEN)?;
        if !self
            .claim_id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-' | ':'))
        {
            return Err(format!(
                "claim_id '{}' may contain only ASCII letters, digits, '.', '_', '-', or ':'",
                self.claim_id
            ));
        }
        validate_nonempty_bounded("statement", &self.statement, MAX_STATEMENT_LEN)?;
        validate_nonempty_bounded("scope", &self.scope, MAX_SCOPE_LEN)?;
        if !self.confidence.is_finite() || !(0.0..=1.0).contains(&self.confidence) {
            return Err("confidence must be a finite number in [0,1]".into());
        }
        if self.evidence.is_empty() {
            return Err("evidence must contain at least one explicit pointer".into());
        }
        if self.evidence.len() > MAX_EVIDENCE_REFS {
            return Err(format!(
                "evidence has {} pointers; maximum is {}",
                self.evidence.len(),
                MAX_EVIDENCE_REFS
            ));
        }
        for reference in &self.evidence {
            validate_nonempty_bounded("evidence pointer", reference, MAX_EVIDENCE_REF_LEN)?;
        }
        if self.known_limitations.len() > MAX_LIMITATIONS {
            return Err(format!(
                "known_limitations has {} entries; maximum is {}",
                self.known_limitations.len(),
                MAX_LIMITATIONS
            ));
        }
        for limitation in &self.known_limitations {
            validate_nonempty_bounded("known limitation", limitation, MAX_LIMITATION_LEN)?;
        }
        Ok(())
    }
}

/// Parse and validate an optional closure-claims array from an MCP argument.
///
/// Missing claims are represented as an empty vector. This preserves honest
/// missingness: an execution result is not silently converted into a claim.
/// Aggregate cap on the serialized claims payload per outcome. The per-field
/// bounds alone admit a ~3.3 MB worst case (MAX_CLOSURE_CLAIMS × max field
/// sizes) — an outlier against the chain's hash-not-payload norm. 64 KB is
/// generous for structured claims; anything larger belongs behind an evidence
/// POINTER, not inline (review 2026-07-24).
pub const MAX_CLOSURE_CLAIMS_TOTAL_BYTES: usize = 64 * 1024;

pub fn parse_closure_claims(
    value: Option<&serde_json::Value>,
) -> Result<Vec<ClosureClaim>, String> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let serialized_len = value.to_string().len();
    if serialized_len > MAX_CLOSURE_CLAIMS_TOTAL_BYTES {
        return Err(format!(
            "closure_claims serializes to {serialized_len} bytes; maximum is \
             {MAX_CLOSURE_CLAIMS_TOTAL_BYTES} — put large evidence behind a pointer, not inline"
        ));
    }
    let claims: Vec<ClosureClaim> = serde_json::from_value(value.clone()).map_err(|error| {
        format!("closure_claims must match {CLOSURE_CLAIMS_SCHEMA_V1}: {error}")
    })?;
    if claims.len() > MAX_CLOSURE_CLAIMS {
        return Err(format!(
            "closure_claims has {} entries; maximum is {}",
            claims.len(),
            MAX_CLOSURE_CLAIMS
        ));
    }
    let mut ids = HashSet::with_capacity(claims.len());
    for claim in &claims {
        claim.validate()?;
        if !ids.insert(claim.claim_id.as_str()) {
            return Err(format!("duplicate claim_id '{}'", claim.claim_id));
        }
    }
    Ok(claims)
}

fn validate_nonempty_bounded(name: &str, value: &str, maximum: usize) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{name} must not be empty"));
    }
    if value.len() > maximum {
        return Err(format!(
            "{name} is {} bytes; maximum is {maximum}",
            value.len()
        ));
    }
    Ok(())
}

/// Why a previously recorded result or decision was reversed.
///
/// This is deliberately orthogonal to operational reversal `kind`
/// (`override`, `rollback`, `incident`). Only `InvalidResult` is evidence that
/// the subject's result was invalid. Other causes are witnessed history but
/// must not silently become negative validity evidence.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ReversalCause {
    InvalidResult,
    ChangedRequirements,
    NewEvidence,
    CorrectedAdjudication,
    SelfCorrection,
    Obsolescence,
}

impl ReversalCause {
    pub const ALL: [&'static str; 6] = [
        "invalid-result",
        "changed-requirements",
        "new-evidence",
        "corrected-adjudication",
        "self-correction",
        "obsolescence",
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidResult => "invalid-result",
            Self::ChangedRequirements => "changed-requirements",
            Self::NewEvidence => "new-evidence",
            Self::CorrectedAdjudication => "corrected-adjudication",
            Self::SelfCorrection => "self-correction",
            Self::Obsolescence => "obsolescence",
        }
    }

    /// Whether this cause supports a `validity:refuted` observation.
    pub const fn refutes_validity(self) -> bool {
        matches!(self, Self::InvalidResult)
    }
}

impl fmt::Display for ReversalCause {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ReversalCause {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "invalid-result" => Ok(Self::InvalidResult),
            "changed-requirements" => Ok(Self::ChangedRequirements),
            "new-evidence" => Ok(Self::NewEvidence),
            "corrected-adjudication" => Ok(Self::CorrectedAdjudication),
            "self-correction" => Ok(Self::SelfCorrection),
            "obsolescence" => Ok(Self::Obsolescence),
            _ => Err(format!("cause '{value}' not in {:?}", ReversalCause::ALL)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn closure_claims_are_explicit_scoped_and_calibrated() {
        let claims = parse_closure_claims(Some(&json!([{
            "claim_id": "tests-pass",
            "statement": "The focused test suite passes.",
            "scope": "core package at commit abc123",
            "confidence": 0.98,
            "evidence": ["chain:012345", "commit:abc123"],
            "known_limitations": ["Full workspace tests were not run."]
        }])))
        .unwrap();
        assert_eq!(claims.len(), 1);
        assert_eq!(claims[0].claim_id, "tests-pass");
        assert_eq!(claims[0].confidence, 0.98);
    }

    #[test]
    fn missing_claims_stay_missing() {
        assert!(parse_closure_claims(None).unwrap().is_empty());
    }

    #[test]
    fn invalid_or_ambiguous_claims_are_rejected() {
        let no_evidence = json!([{
            "claim_id": "works",
            "statement": "It works.",
            "scope": "everything",
            "confidence": 1.0,
            "evidence": []
        }]);
        assert!(
            parse_closure_claims(Some(&no_evidence))
                .unwrap_err()
                .contains("at least one")
        );

        let uncalibrated = json!([{
            "claim_id": "works",
            "statement": "It works.",
            "scope": "everything",
            "confidence": 1.1,
            "evidence": ["test:1"]
        }]);
        assert!(
            parse_closure_claims(Some(&uncalibrated))
                .unwrap_err()
                .contains("[0,1]")
        );

        let duplicate = json!([
            {
                "claim_id": "same",
                "statement": "One.",
                "scope": "a",
                "confidence": 0.5,
                "evidence": ["test:1"]
            },
            {
                "claim_id": "same",
                "statement": "Two.",
                "scope": "b",
                "confidence": 0.5,
                "evidence": ["test:2"]
            }
        ]);
        assert!(
            parse_closure_claims(Some(&duplicate))
                .unwrap_err()
                .contains("duplicate claim_id")
        );
    }

    #[test]
    fn only_invalid_result_refutes_validity() {
        for cause in ReversalCause::ALL {
            let parsed: ReversalCause = cause.parse().unwrap();
            assert_eq!(parsed.refutes_validity(), cause == "invalid-result");
            assert_eq!(parsed.to_string(), cause);
        }
    }
}
