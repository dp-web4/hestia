//! Gate integrity — the expectation lives where the governed party cannot write.
//!
//! dp, 2026-07-27: "since each pre-tool-use hook is a .py file that is freely editable, it
//! provides an obvious surface for a sophisticated agent to alter its permissions. at the
//! very least we should have hashes that are stored in the vault but preferably a better
//! system."
//!
//! THE HOLE, DEMONSTRATED RATHER THAN ARGUED. Every gate on this machine is a Python file
//! owned by the same uid as the agent it governs. On 2026-07-27 CBP overwrote *another
//! member's* gate (`~/.kimi-code/hooks/pre_tool_use.py`) and the policy engine's entire
//! response was a WARN — "File deletion flagged - use with caution". An agent wishing to
//! widen its own permissions does not need to defeat the gate; it edits it, and the next
//! invocation enforces whatever it now says.
//!
//! WHY HASHES IN THE VAULT ACTUALLY HELP, AND WHERE THEY STOP.
//!
//! The agent can write the ARTIFACT. It cannot write the EXPECTATION: the vault is
//! SQLCipher-encrypted and every mutation is behind the operator gate, which requires an
//! Ed25519 challenge signed by a key the agent does not hold. That asymmetry is the whole
//! mechanism — a tampered gate becomes *detectable* because the record of what it should
//! be lives somewhere the tamperer cannot reach.
//!
//! Two properties follow, and both must be stated plainly:
//!
//!   * This is TAMPER-EVIDENT, not tamper-PROOF. Nothing here prevents the edit. It makes
//!     the edit visible, and it makes silence meaningful — a verified gate is evidence,
//!     where previously an unmodified gate and a rewritten one were indistinguishable.
//!   * The DAEMON hashes the file itself. It never accepts a hash the gate reports about
//!     itself, because a gate that has been rewritten to lie about its behaviour would
//!     equally lie about its digest. Self-attested integrity is not integrity; it is the
//!     same declaration-vs-evidence inversion hestia#49 is about, one layer down.
//!
//! WHAT WOULD BE BETTER, since dp asked for better and this is not it. Signed gates whose
//! signature the *daemon* verifies before honouring a verdict — then a rewritten gate is
//! not merely noticed, its verdicts stop counting. Beyond that, the gate not being a file
//! in the agent's own filesystem at all. Both are in hestia#49's hardening path; this is
//! the floor beneath them, not a substitute.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::Path;

/// One ratified expectation about a gate file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GateExpectation {
    /// Hex SHA-256 of the file's bytes as the operator ratified them.
    pub sha256: String,
    /// Which member this gate governs — so a mismatch names who is affected, not just
    /// which path changed.
    pub plugin_id: String,
    pub ratified_at: chrono::DateTime<chrono::Utc>,
    /// Free text: why this build was ratified (a PR, a commit, "initial adoption").
    #[serde(default)]
    pub note: String,
}

/// Path → expectation. Ordered so the serialized vault is diffable.
pub type GateExpectations = BTreeMap<String, GateExpectation>;

/// What a verification found for one gate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "status")]
pub enum GateVerdict {
    /// Hash matches the ratified expectation.
    Verified { plugin_id: String, sha256: String },
    /// File exists and its hash differs. The loud case.
    Modified {
        plugin_id: String,
        expected: String,
        actual: String,
        ratified_at: chrono::DateTime<chrono::Utc>,
    },
    /// Ratified but the file is gone. A missing gate FAILS OPEN on Claude-lineage
    /// engines, so an absent gate is a governance hole, never a clean result.
    Missing { plugin_id: String, expected: String },
    /// A gate is wired but nothing was ever ratified for it. Not "fine" — unexamined.
    Unratified { path: String },
    /// The file could not be read (permissions, I/O). Reported, never assumed clean.
    Unreadable { path: String, error: String },
}

impl GateVerdict {
    /// Does this verdict warrant operator attention?
    pub fn is_finding(&self) -> bool {
        !matches!(self, GateVerdict::Verified { .. })
    }
}

/// Hash a file's bytes. The daemon does this itself — see the module docs on why a
/// gate-reported digest is worthless.
pub fn hash_file(path: &Path) -> std::io::Result<String> {
    let bytes = std::fs::read(path)?;
    let mut h = Sha256::new();
    h.update(&bytes);
    Ok(format!("{:x}", h.finalize()))
}

/// Verify every ratified expectation, plus report any wired gate that was never ratified.
///
/// `wired` is the set of gate paths the inventory found actually configured, so a gate
/// that exists and is running but has no expectation is surfaced as `Unratified` rather
/// than passing unmentioned. An unexamined gate reading the same as a verified one is the
/// defect this whole subsystem exists to remove.
pub fn verify(expectations: &GateExpectations, wired: &[String]) -> Vec<GateVerdict> {
    let mut out = Vec::new();
    for (path, exp) in expectations {
        let p = Path::new(path);
        if !p.is_file() {
            out.push(GateVerdict::Missing {
                plugin_id: exp.plugin_id.clone(),
                expected: exp.sha256.clone(),
            });
            continue;
        }
        match hash_file(p) {
            Ok(actual) if actual == exp.sha256 => out.push(GateVerdict::Verified {
                plugin_id: exp.plugin_id.clone(),
                sha256: actual,
            }),
            Ok(actual) => out.push(GateVerdict::Modified {
                plugin_id: exp.plugin_id.clone(),
                expected: exp.sha256.clone(),
                actual,
                ratified_at: exp.ratified_at,
            }),
            Err(e) => out.push(GateVerdict::Unreadable {
                path: path.clone(),
                error: e.to_string(),
            }),
        }
    }
    for w in wired {
        if !expectations.contains_key(w) {
            out.push(GateVerdict::Unratified { path: w.clone() });
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn tmp(content: &str) -> (tempfile::TempDir, String) {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("gate.py");
        let mut f = std::fs::File::create(&p).unwrap();
        f.write_all(content.as_bytes()).unwrap();
        (d, p.to_string_lossy().into_owned())
    }

    fn exp(path_hash: &str) -> GateExpectation {
        GateExpectation {
            sha256: path_hash.into(),
            plugin_id: "codex".into(),
            ratified_at: chrono::Utc::now(),
            note: "test".into(),
        }
    }

    #[test]
    fn an_unmodified_gate_verifies() {
        let (_d, p) = tmp("print('gate')");
        let h = hash_file(Path::new(&p)).unwrap();
        let mut e = GateExpectations::new();
        e.insert(p, exp(&h));
        let v = verify(&e, &[]);
        assert!(matches!(v[0], GateVerdict::Verified { .. }));
        assert!(!v[0].is_finding());
    }

    /// The attack dp named: an agent widens its own permissions by editing the gate.
    #[test]
    fn editing_the_gate_is_detected() {
        let (_d, p) = tmp("print('gate')");
        let h = hash_file(Path::new(&p)).unwrap();
        let mut e = GateExpectations::new();
        e.insert(p.clone(), exp(&h));
        std::fs::write(&p, "import sys; sys.exit(0)  # allow everything").unwrap();
        let v = verify(&e, &[]);
        assert!(matches!(v[0], GateVerdict::Modified { .. }), "a rewritten gate must be Modified");
        assert!(v[0].is_finding());
    }

    /// A deleted gate fails OPEN on this lineage, so absence must never read as clean.
    #[test]
    fn a_deleted_gate_is_a_finding_not_a_pass() {
        let (_d, p) = tmp("print('gate')");
        let h = hash_file(Path::new(&p)).unwrap();
        let mut e = GateExpectations::new();
        e.insert(p.clone(), exp(&h));
        std::fs::remove_file(&p).unwrap();
        let v = verify(&e, &[]);
        assert!(matches!(v[0], GateVerdict::Missing { .. }));
        assert!(v[0].is_finding());
    }

    /// A wired-but-never-ratified gate is UNEXAMINED, not fine.
    #[test]
    fn a_wired_gate_with_no_expectation_is_surfaced() {
        let v = verify(&GateExpectations::new(), &["/some/live/gate.py".to_string()]);
        assert!(matches!(v[0], GateVerdict::Unratified { .. }));
        assert!(v[0].is_finding(), "unexamined must not read the same as verified");
    }
}
