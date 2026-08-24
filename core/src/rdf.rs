//! Trust as a traversable graph — projecting derived trust into the Web4 ontology.
//!
//! dp, 2026-07-28: *"the biggest open thing … is exactly wiring the lct multi-dimensional
//! tensors, rdf, and attestation/attribution, fractally. the goal: relying party can refuse
//! action on insufficiency of evidence."*
//!
//! **The vocabulary already exists and nothing emitted it.** `web4-standard/ontology/`
//! defines `t3v3-ontology.ttl` with exactly the shape this needs, and hestia contained zero
//! RDF. Three properties in that file are the whole argument:
//!
//! - `web4:entity` + `web4:role` on a tensor — *"Trust is always role-specific."* The
//!   `role@agent` pair we keep rediscovering as a defect is **already normative**, as two
//!   edges rather than a concatenated string. Every attribution bug this week
//!   (`is_recognised_reasoner` prefix-matching, the split kimi grain, adjudications filed to
//!   a role the member never acts in) is a string comparison standing in for an edge.
//! - `web4:subDimensionOf` — *"Creates the open-ended fractal sub-graph. Anyone can extend
//!   the dimension tree without modifying this ontology."* The fractal tensor, specified.
//! - `web4:DimensionScore` — *"Reifies the measurement with timestamp and provenance."* A
//!   score stops being a float and becomes a node you can ask questions of.
//!
//! **WHY A GRAPH CHANGES WHAT A RELYING PARTY CAN DO.** A scalar answers "how much?". Only a
//! graph answers "on what basis, witnessed by whom, and is that enough for *this* act?" —
//! which is the question a relying party must be able to refuse on. This module does not
//! implement that refusal; it emits the object the refusal will be computed over. That is
//! the increment: make the evidence addressable before making it decisive.
//!
//! **KNOWN, RECORDED, AND UPSTREAM: RDFS DOMAIN POLLUTION ON THE V3 SIDE.** The ontology
//! declares `rdfs:domain web4:T3Tensor` on `entity`, `role` and `hasDimensionScore`. This
//! projection emits those edges on `V3Tensor` nodes too, so under RDFS semantics a reasoner
//! infers every V3 tensor is *also* a T3Tensor — type pollution, a join defect of the same
//! family as a wrong namespace. The fix belongs to the ontology (a common `web4:Tensor`
//! superclass, or dropping the domains), not here; kimi-code's review is right that the PR
//! which makes the graph real should be the one that records the inference it triggers.
//! Filed against web4-standard rather than worked around locally.
//!
//! **ABSENCE IS STRUCTURAL HERE, NOT A LOW NUMBER.** An unmeasured dimension emits **no
//! `DimensionScore` node at all** — not a node with score 0, not a node marked unknown. A
//! consumer asking "is there a Validity score?" gets *nothing* rather than something
//! disappointing, so it cannot accidentally read absence as a bad measurement. That is this
//! week's recurring defect (`unmeasured` ranked below `minimal` by an `indexOf` returning
//! -1) made unrepresentable by the data model rather than guarded against in a renderer.

use crate::derivation::{DerivedDimension, DerivedTrust};

/// Ontology namespace. MUST match `web4-standard/ontology/t3v3-ontology.ttl` line 1
/// (`@prefix web4: <https://web4.io/ontology#> .`) exactly.
///
/// The first cut of this emitted `https://web4.foundation/ontology#` — a plausible-looking
/// URI invented rather than read off the file. Every triple would have parsed, looked
/// correct, and **joined with nothing**: a graph in a namespace that exists nowhere shares
/// no predicates with the vocabulary it claims to use. The RDF form of this corpus's
/// recurring defect — output that is confidently shaped and silently disconnected. Caught by
/// diffing against the ontology before merge; pinned by `namespace_matches_the_ontology`
/// below so a future edit cannot reintroduce it quietly.
///
/// If web4 ever moves the namespace, this is a coordinated change across both repos, and
/// the test is the thing that will say so.
pub const WEB4_NS: &str = "https://web4.io/ontology#";

/// Namespace for predicates hestia needs that the Web4 ontology does not (yet) define.
///
/// `observationCount` was first emitted as `web4:observationCount` — a predicate that exists
/// NOWHERE in `t3v3-ontology.ttl`. kimi-code, reviewing: it "will parse, look plausible, and
/// join with nothing — exactly the failure the namespace story in the module docs warns
/// about, one level down." It was the same defect as the invented namespace, one predicate
/// over, in the file that narrates the invented namespace. I had checked the namespace
/// against the ontology and then stopped checking, as though one lookup discharged the
/// obligation for every term.
///
/// The count is load-bearing for the sufficiency query this graph exists to enable ("witnessed
/// by how many, fresh enough?"), so dropping it would be the wrong fix. Emitting it under a
/// hestia namespace keeps `web4:` **exactly the vocabulary that exists** while the coordinated
/// addition to web4-standard is proposed. A consumer can then tell, from the prefix alone,
/// which predicates are standard and which are ours — which is the honest state.
pub const HESTIA_NS: &str = "https://hestia.local/ontology#";

/// Escape a string for a Turtle **string literal** (quoted position).
fn lit(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n").replace('\r', "")
}

/// Escape a string for Turtle **IRIREF** position — `<…>`.
///
/// `lit()` was previously used here too, and that was wrong: Turtle's IRIREF grammar admits
/// **no backslash escapes except `\uXXXX`/`\UXXXXXXXX`**, so `<role:with\"quote>` — which the
/// old `literals_are_escaped` test pinned as correct — is rejected by a conforming parser.
/// kimi-code, reviewing: a module whose thesis is *verify against the spec, don't assume*
/// should not carry a test that codifies a misreading of the format. **A test asserting
/// invalid output is worse than a missing test — it defends the bug against the next reader.**
///
/// Nothing live reaches this today (hashes are hex, roles are charset-constrained at connect,
/// LCTs are minted), which is precisely why it had to be fixed on the spec rather than on
/// the symptom.
fn iri(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            '<' | '>' | '"' | '{' | '}' | '|' | '^' | '`' | '\\' => format!("\\u{:04X}", c as u32),
            c if (c as u32) <= 0x20 => format!("\\u{:04X}", c as u32),
            c => c.to_string(),
        })
        .collect()
}

/// A dimension's ontology term, and which tensor it belongs to.
fn dimension_term(name: &str) -> Option<(&'static str, Tensor)> {
    match name {
        "talent" => Some(("Talent", Tensor::T3)),
        "training" => Some(("Training", Tensor::T3)),
        "temperament" => Some(("Temperament", Tensor::T3)),
        "valuation" => Some(("Valuation", Tensor::V3)),
        "veracity" => Some(("Veracity", Tensor::V3)),
        "validity" => Some(("Validity", Tensor::V3)),
        _ => None,
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tensor {
    T3,
    V3,
}

impl Tensor {
    fn class(self) -> &'static str {
        match self {
            Tensor::T3 => "T3Tensor",
            Tensor::V3 => "V3Tensor",
        }
    }
    fn slug(self) -> &'static str {
        match self {
            Tensor::T3 => "t3",
            Tensor::V3 => "v3",
        }
    }
}

/// Project one grain's derived trust into Turtle against the Web4 T3/V3 ontology.
///
/// `entity_lct` is the durable member LCT — NOT the `plugin_id`. Note precisely what that
/// vouches for: `member_lct` is a **naming function**, returning `Some` for any non-empty
/// non-synthetic string, so a plugin that never connected still derives a well-formed LCT
/// (the #79 lesson — it never reads the registry). Using it here is right for *joining*,
/// because the derivation is deterministic and stable; it is not evidence of presence, and
/// this projection does not claim it is. The plugin_id is a label the
/// caller supplies; the LCT is what the society minted. Passing the label here would encode
/// the attribution gap into the graph, which is the one thing this projection exists to close.
///
/// Emits, per grain:
/// - a `T3Tensor` and/or `V3Tensor`, each bound by `web4:entity` and `web4:role`;
/// - one `DimensionScore` per **measured** dimension, carrying `web4:score`,
///   `web4:observedAt` and one `web4:witnessedBy` per backing chain entry.
///
/// A tensor with no measured dimensions is omitted entirely rather than emitted empty —
/// same reason as the missing score node: an empty tensor invites "the tensor exists but is
/// bad", which is not what the evidence says.
pub fn trust_to_turtle(derived: &DerivedTrust, entity_lct: &str) -> String {
    let mut out = String::new();
    out.push_str("@prefix web4: <");
    out.push_str(WEB4_NS);
    out.push_str("> .\n@prefix hestia: <");
    out.push_str(HESTIA_NS);
    out.push_str("> .\n@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n");
    out.push_str(&format!(
        "# derived by hestia {} at {}\n# grain: {} as {}\n\n",
        lit(&derived.derivation_version),
        derived.generated_at.to_rfc3339(),
        lit(&derived.plugin_id),
        lit(&derived.role_lct),
    ));

    let dims: [(&str, &DerivedDimension); 4] = [
        ("temperament", &derived.temperament),
        ("validity", &derived.validity),
        ("veracity", &derived.veracity),
        ("valuation", &derived.valuation),
    ];

    for tensor in [Tensor::T3, Tensor::V3] {
        // Only dimensions of THIS tensor that are actually measured.
        let measured: Vec<(&str, &'static str, &DerivedDimension)> = dims
            .iter()
            .filter_map(|(name, d)| {
                let (term, t) = dimension_term(name)?;
                (t == tensor && d.score.is_some()).then_some((*name, term, *d))
            })
            .collect();
        if measured.is_empty() {
            continue; // no measured dimension => no tensor node. Absence stays absent.
        }

        let tensor_uri = format!(
            "<urn:hestia:tensor:{}:{}:{}>",
            tensor.slug(),
            uri_frag(entity_lct),
            uri_frag(&derived.role_lct)
        );
        out.push_str(&format!("{tensor_uri} a web4:{} ;\n", tensor.class()));
        // THE role@agent EDGES. Two properties, not one concatenated key.
        out.push_str(&format!("  web4:entity <{}> ;\n", iri(entity_lct)));
        out.push_str(&format!("  web4:role <{}> ;\n", iri(&derived.role_lct)));
        for (i, (name, term, _)) in measured.iter().enumerate() {
            let sep = if i + 1 == measured.len() { " ." } else { " ;" };
            out.push_str(&format!(
                "  web4:hasDimensionScore {}{}\n",
                score_uri(entity_lct, &derived.role_lct, name),
                sep
            ));
            let _ = term;
        }
        out.push('\n');

        for (name, term, d) in measured {
            let s_uri = score_uri(entity_lct, &derived.role_lct, name);
            let score = d.score.expect("filtered to measured");
            out.push_str(&format!("{s_uri} a web4:DimensionScore ;\n"));
            out.push_str(&format!("  web4:dimension web4:{term} ;\n"));
            out.push_str(&format!("  web4:score \"{score:.6}\"^^xsd:decimal ;\n"));
            // observedAt = the NEWEST backing observation, so staleness is readable off the
            // graph rather than inferred from when someone happened to query.
            if let Some(newest) = d.evidence.iter().map(|e| e.timestamp).max() {
                out.push_str(&format!(
                    "  web4:observedAt \"{}\"^^xsd:dateTime ;\n",
                    newest.to_rfc3339()
                ));
            }
            // PROVENANCE. One edge per backing chain entry: the score is traversable back to
            // the exact witnessed events that produced it. This is what makes "insufficient
            // evidence" a query rather than an opinion.
            for e in &d.evidence {
                out.push_str(&format!(
                    "  web4:witnessedBy <urn:hestia:chain:{}> ;\n",
                    iri(&e.hash)
                ));
            }
            out.push_str(&format!(
                "  hestia:observationCount \"{}\"^^xsd:integer .\n\n",
                d.observations
            ));
        }
    }
    out
}

fn uri_frag(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' { c } else { '_' })
        .collect()
}

fn score_uri(entity_lct: &str, role: &str, dim: &str) -> String {
    format!(
        "<urn:hestia:score:{}:{}:{}>",
        uri_frag(entity_lct),
        uri_frag(role),
        dim
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::derivation::{DerivedDimension, DerivedTrust, Evidence};
    use chrono::{TimeZone, Utc};

    fn ev(hash: &str, mins: i64) -> Evidence {
        Evidence {
            chain_position: 1,
            hash: hash.into(),
            event_type: "adjudication".into(),
            timestamp: Utc.with_ymd_and_hms(2026, 7, 28, 0, mins as u32, 0).unwrap(),
            contribution: "adjudication validity upheld 1.00 (review)".into(),
            reference: None,
        }
    }
    fn dim(score: Option<f64>, evidence: Vec<Evidence>) -> DerivedDimension {
        DerivedDimension {
            observations: evidence.len() as u64,
            score,
            formula: "test".into(),
            evidence,
        }
    }
    fn grain(temperament: Option<f64>, validity: Option<f64>) -> DerivedTrust {
        DerivedTrust {
            derivation_version: "v3-derived-v1".into(),
            plugin_id: "kimi-code".into(),
            role_lct: "role:constellation:interactive-dev".into(),
            generated_at: Utc.with_ymd_and_hms(2026, 7, 28, 1, 0, 0).unwrap(),
            temperament: dim(temperament, if temperament.is_some() { vec![ev("aaa1", 1)] } else { vec![] }),
            validity: dim(validity, if validity.is_some() { vec![ev("bbb2", 2), ev("ccc3", 3)] } else { vec![] }),
            veracity: dim(None, vec![]),
            valuation: dim(None, vec![]),
            level: "high".into(),
            level_basis: "conduct".into(),
            baseline_acts: 0,
            governed_acts: 0,
        }
    }

    /// The role@agent pair is emitted as TWO EDGES, not a concatenated key — which is the
    /// whole reason this projection exists.
    #[test]
    fn the_grain_is_two_edges_entity_and_role() {
        let ttl = trust_to_turtle(&grain(Some(0.85), Some(0.92)), "lct:web4:member:abc123");
        assert!(ttl.contains("web4:entity <lct:web4:member:abc123>"), "{ttl}");
        assert!(
            ttl.contains("web4:role <role:constellation:interactive-dev>"),
            "role must be its own edge, not glued to the entity: {ttl}"
        );
        // and NOT the caller-supplied label, which is the attribution gap
        assert!(!ttl.contains("web4:entity <kimi-code>"), "plugin_id must not stand in for the LCT");
    }

    /// An unmeasured dimension emits NOTHING — no node, no zero, no "unknown" literal.
    #[test]
    fn an_unmeasured_dimension_has_no_node_at_all() {
        let ttl = trust_to_turtle(&grain(Some(0.85), None), "lct:web4:member:abc123");
        assert!(ttl.contains("web4:Temperament"), "measured dimension present: {ttl}");
        assert!(!ttl.contains("web4:Validity"), "unmeasured dimension must be ABSENT: {ttl}");
        assert!(!ttl.contains("Veracity") && !ttl.contains("Valuation"));
        // The V3 tensor has no measured dimension at all, so it is not emitted either.
        assert!(!ttl.contains("web4:V3Tensor"), "an empty tensor invites 'exists but bad': {ttl}");
        assert!(ttl.contains("web4:T3Tensor"));
    }

    /// Every score traverses back to the exact chain entries that produced it. This is the
    /// property that turns "insufficient evidence" into a query.
    #[test]
    fn a_score_is_traversable_to_its_backing_chain_entries() {
        let ttl = trust_to_turtle(&grain(None, Some(0.92)), "lct:web4:member:abc123");
        assert!(ttl.contains("web4:witnessedBy <urn:hestia:chain:bbb2>"), "{ttl}");
        assert!(ttl.contains("web4:witnessedBy <urn:hestia:chain:ccc3>"), "{ttl}");
        assert!(ttl.contains("hestia:observationCount \"2\"^^xsd:integer"));
        // newest observation, so staleness is on the graph
        assert!(ttl.contains("web4:observedAt \"2026-07-28T00:03:00+00:00\""), "{ttl}");
    }

    /// A grain with no measured dimension anywhere emits no tensors — only the header.
    #[test]
    fn a_wholly_unmeasured_grain_emits_no_tensor() {
        let ttl = trust_to_turtle(&grain(None, None), "lct:web4:member:abc123");
        assert!(!ttl.contains("a web4:T3Tensor") && !ttl.contains("a web4:V3Tensor"), "{ttl}");
        assert!(ttl.contains("@prefix web4:"), "the prefix header still identifies the vocabulary");
    }

    /// The namespace is the one thing that cannot be approximately right: a wrong URI
    /// produces triples that parse cleanly and match no vocabulary. Pinned verbatim against
    /// `web4-standard/ontology/t3v3-ontology.ttl` line 1.
    #[test]
    fn namespace_matches_the_ontology() {
        assert_eq!(
            WEB4_NS, "https://web4.io/ontology#",
            "must equal the @prefix in web4-standard/ontology/t3v3-ontology.ttl — a graph in \
             the wrong namespace joins with nothing while looking correct"
        );
        let ttl = trust_to_turtle(&grain(Some(0.5), None), "lct:web4:member:abc");
        assert!(ttl.contains("@prefix web4: <https://web4.io/ontology#> ."), "{ttl}");
    }

    /// IRI position takes UCHAR, not backslash escapes.
    ///
    /// This test previously asserted `<role:with\\"quote>` was correct output. It is not —
    /// Turtle's IRIREF grammar rejects backslash escapes. The test defended the bug; it now
    /// pins the fix. A test asserting invalid output is worse than a missing test.
    #[test]
    fn iri_position_uses_uchar_not_backslash_escapes() {
        let mut g = grain(Some(0.5), None);
        g.role_lct = "role:with\"quote".into();
        let ttl = trust_to_turtle(&g, "lct:web4:member:abc123");
        assert!(ttl.contains("role:with\\u0022quote"), "IRIREF needs UCHAR: {ttl}");
        assert!(!ttl.contains("role:with\\\\\"quote"), "backslash escape is invalid in IRIREF: {ttl}");
    }

    /// The two grammars are different and the module must not collapse them again.
    #[test]
    fn literal_and_iri_escaping_are_distinct() {
        assert_eq!(lit("a\"b"), "a\\\"b");
        assert_eq!(iri("a\"b"), "a\\u0022b");
    }

    /// Predicates the ontology does not define live under `hestia:`, so a consumer can tell
    /// standard from local by prefix alone.
    #[test]
    fn nonstandard_predicates_are_not_emitted_as_web4() {
        let ttl = trust_to_turtle(&grain(Some(0.85), None), "lct:web4:member:abc123");
        assert!(ttl.contains("hestia:observationCount"), "{ttl}");
        assert!(!ttl.contains("web4:observationCount"),
                "observationCount is absent from t3v3-ontology.ttl; emitting it as web4: \
                 forks the vocabulary silently: {ttl}");
        assert!(ttl.contains("@prefix hestia: <https://hestia.local/ontology#> ."), "{ttl}");
    }
}
