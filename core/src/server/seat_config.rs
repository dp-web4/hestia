//! Seat config is RENDERED from the vault, and a rendered file that drifts is a miswire.
//!
//! dp, 2026-09-03: *"we should not have machine-specific paths in editable configs. all that
//! needs to live in the vault and set env variables, which should be periodically checked vs
//! vault for integrity, just like the hook plaintext... the target: ALL config lives in vault,
//! readable files and vars written from vault on startup, checked at runtime, immediately
//! flagged as miswire (and logged in ledger) when detected as not matching."*
//!
//! WHY THIS AND NOT MORE HAND-EDITING. Five instances were measured on one box in one day, and
//! all of them are the same defect: config authored by hand in a file the governed party is
//! forbidden to fix. kimi's `HESTIA_SOCIETY_GATE` pointed at a hook that does not exist. The
//! claude seat carried no `HESTIA_WORKSPACE`, so its MRH root came from the session cwd, one
//! level above every grant, and produced nine read-only refusals in an hour (#839). codex and
//! gemini carry absolute roots inline, correct today and machine-specific forever. Moving the
//! workspace root costs 24 hook-config lines and 10 systemd units by hand. And because these
//! files are governance markers, a member cannot repair its own miswire: every correction
//! spends an operator approval.
//!
//! THE ASYMMETRY THIS INHERITS. `vault::gate_integrity` already holds the expectation where the
//! governed party cannot write, and has the daemon hash the artifact itself rather than believe
//! what the gate reports about its own file. This is that mechanism carried from hook CODE to
//! hook CONFIG, and it keeps the same honest limit: **tamper-evident, not tamper-proof**.
//! Nothing here prevents an edit. It makes the edit visible, and it makes silence mean
//! something.
//!
//! WHAT IS DELIBERATELY NOT HERE. No fallback to the file that was found. A renderer that reads
//! the artifact when the vault is unavailable is a second authority with extra steps, and the
//! PRD's acceptance arm 5 exists to forbid exactly that: an unreadable vault renders nothing and
//! the caller is told INDETERMINATE rather than handed a stale value that looks current.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Vault namespace for a member's rendered configuration.
pub const SEAT_CONFIG_NS: &str = "seat-config";
/// Directory under `$HESTIA_HOME` that rendered artifacts live in.
pub const RENDER_DIR: &str = "seats";

/// One member's configuration, as the vault holds it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeatConfig {
    /// Environment the seat's hooks should run with. Ordered, so a render is byte-stable:
    /// a map that reordered between runs would report drift that nobody caused.
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    #[serde(default)]
    pub note: String,
}

/// What a check found. `Miswired` is the one that becomes a chain event.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "status")]
pub enum ConfigVerdict {
    /// Rendered artifact matches what the vault says it should be.
    Verified { member: String, sha256: String },
    /// The artifact exists and differs. Somebody or something edited it.
    Miswired { member: String, expected: String, actual: String },
    /// The vault declares config for this member and no artifact is on disk.
    Missing { member: String, expected: String },
    /// The artifact cannot be read. NOT reported as verified, and not as miswired either:
    /// an unreadable file is an unknown, and absence of evidence gets its own name.
    Unreadable { member: String, error: String },
}

impl ConfigVerdict {
    pub fn is_finding(&self) -> bool {
        !matches!(self, ConfigVerdict::Verified { .. })
    }
    pub fn member(&self) -> &str {
        match self {
            ConfigVerdict::Verified { member, .. }
            | ConfigVerdict::Miswired { member, .. }
            | ConfigVerdict::Missing { member, .. }
            | ConfigVerdict::Unreadable { member, .. } => member,
        }
    }
}

/// The rendered path for a member under a given hestia home.
pub fn render_path(home: &Path, member: &str) -> PathBuf {
    home.join(RENDER_DIR).join(format!("{member}.env"))
}

/// The exact bytes a member's config renders to.
///
/// Deterministic by construction: `BTreeMap` fixes the order, one `KEY=value` per line, a
/// trailing newline, and a header naming the source. Byte-stability is not cosmetic here, it is
/// what makes a digest comparison mean "someone changed this" rather than "the map iterated
/// differently this time".
pub fn render(member: &str, cfg: &SeatConfig) -> String {
    let mut out = String::new();
    out.push_str("# rendered from the vault by hestia. Do not edit: this file is a projection,\n");
    out.push_str("# and an edit here is reported as a miswire rather than applied.\n");
    out.push_str(&format!("# member: {member}\n"));
    if !cfg.note.trim().is_empty() {
        out.push_str(&format!("# note: {}\n", cfg.note.trim().replace('\n', " ")));
    }
    for (k, v) in &cfg.env {
        out.push_str(&format!("{k}={v}\n"));
    }
    out
}

pub fn sha256_of(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    format!("{:x}", h.finalize())
}

/// Compare what is on disk against what the vault renders. Never writes.
pub fn verify_one(home: &Path, member: &str, cfg: &SeatConfig) -> ConfigVerdict {
    let expected_bytes = render(member, cfg);
    let expected = sha256_of(expected_bytes.as_bytes());
    let path = render_path(home, member);
    match std::fs::read(&path) {
        Ok(found) => {
            let actual = sha256_of(&found);
            if actual == expected {
                ConfigVerdict::Verified { member: member.to_string(), sha256: actual }
            } else {
                ConfigVerdict::Miswired { member: member.to_string(), expected, actual }
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            ConfigVerdict::Missing { member: member.to_string(), expected }
        }
        Err(e) => ConfigVerdict::Unreadable { member: member.to_string(), error: e.to_string() },
    }
}

/// Write the rendered artifact. Returns whether the bytes on disk CHANGED.
///
/// Atomic by rename, so a reader never sees a half-written config: a seat that read a truncated
/// env file would resolve a wrong workspace root and enforce against the wrong tree, which is
/// the failure this whole document exists to end.
pub fn render_to_disk(home: &Path, member: &str, cfg: &SeatConfig) -> std::io::Result<bool> {
    let path = render_path(home, member);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let bytes = render(member, cfg);
    if let Ok(found) = std::fs::read(&path) {
        if found == bytes.as_bytes() {
            return Ok(false);
        }
    }
    let tmp = path.with_extension("env.tmp");
    std::fs::write(&tmp, bytes.as_bytes())?;
    std::fs::rename(&tmp, &path)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> SeatConfig {
        let mut env = BTreeMap::new();
        env.insert("HESTIA_WORKSPACE".to_string(), "/w/ai".to_string());
        env.insert("HESTIA_ROLE".to_string(), "role:constellation:member".to_string());
        SeatConfig { env, note: "test".into() }
    }

    #[test]
    fn a_render_is_byte_stable() {
        let a = render("claude-code", &cfg());
        let b = render("claude-code", &cfg());
        assert_eq!(a, b, "the same config must render the same bytes, or drift is unreadable");
        assert!(a.contains("HESTIA_ROLE=role:constellation:member"));
        assert!(
            a.find("HESTIA_ROLE").unwrap() < a.find("HESTIA_WORKSPACE").unwrap(),
            "ordered, so a reordered map is not reported as an edit"
        );
    }

    #[test]
    fn rendering_is_idempotent_and_verifies() {
        let dir = tempfile::tempdir().unwrap();
        assert!(render_to_disk(dir.path(), "claude-code", &cfg()).unwrap(), "first write changes");
        assert!(!render_to_disk(dir.path(), "claude-code", &cfg()).unwrap(), "second is a no-op");
        assert!(matches!(
            verify_one(dir.path(), "claude-code", &cfg()),
            ConfigVerdict::Verified { .. }
        ));
    }

    #[test]
    fn a_hand_edit_is_a_miswire_and_names_both_digests() {
        let dir = tempfile::tempdir().unwrap();
        render_to_disk(dir.path(), "claude-code", &cfg()).unwrap();
        let p = render_path(dir.path(), "claude-code");
        let mut s = std::fs::read_to_string(&p).unwrap();
        s = s.replace("/w/ai", "/w/somewhere-else");
        std::fs::write(&p, s).unwrap();

        match verify_one(dir.path(), "claude-code", &cfg()) {
            ConfigVerdict::Miswired { member, expected, actual } => {
                assert_eq!(member, "claude-code");
                assert_ne!(expected, actual, "a miswire names what it should be and what it is");
            }
            other => panic!("a hand edit must read as a miswire, got {other:?}"),
        }
    }

    #[test]
    fn a_missing_artifact_is_not_verified_and_not_a_miswire() {
        let dir = tempfile::tempdir().unwrap();
        let v = verify_one(dir.path(), "claude-code", &cfg());
        assert!(matches!(v, ConfigVerdict::Missing { .. }), "got {v:?}");
        assert!(v.is_finding(), "absence is a finding, never a silent pass");
    }
}
