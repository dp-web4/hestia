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
//!
//! WHAT THIS SLICE DOES NOT YET ESTABLISH (GPT review of #898, finding 4 — stated here rather
//! than left for a reader to discover). This is the render/verify/witness SUBSTRATE. It is not
//! yet the source of truth for anything, because nothing consumes it:
//!
//!   * No seat or hook loads `<home>/seats/<member>.env` at startup. The rendered artifact is
//!     currently written and checked, and then read by nobody, so a correct render and a
//!     quarantined one have the same effect on a running seat: none.
//!   * The only production caller is the periodic worker, which enumerates
//!     `gate_capabilities.keys()`. A member with vault config but no capability row is never
//!     looked at, so "every seat is verified" is true only of seats that happen to have
//!     reported a capability.
//!   * Readiness does not consume the verdicts, so an INDETERMINATE seat still reports as it
//!     did before.
//!
//! Until those three are wired, this module makes drift VISIBLE and makes an unbacked artifact
//! UNUSABLE. It does not yet make the vault the thing a seat actually starts from. Saying so is
//! the point: an unconsumed producer that reads as a completed mechanism is the defect this
//! codebase keeps re-finding, and it is not improved by being introduced with confidence.

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
    /// An artifact exists on disk that the vault no longer backs, or backs with content this
    /// module refuses to render (see `SeatConfig::validate`).
    ///
    /// GPT review of #898, finding 1: the first version simply `continue`d here, which left the
    /// stale file untouched and fully consumable. That is fallback to the artifact by omission —
    /// precisely what this module's own header says it does not do. An unbacked projection is
    /// quarantined so it cannot be read as current, and the reason is carried here.
    Unbacked { member: String, reason: String, quarantined_to: Option<String> },
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
            | ConfigVerdict::Unreadable { member, .. }
            | ConfigVerdict::Unbacked { member, .. } => member,
        }
    }

    /// The chain event name this verdict is witnessed under.
    ///
    /// GPT review of #898, finding 2: only `Miswired` reached the chain, so a runtime deletion
    /// or an unreadable artifact became a log line and a silent rewrite. `is_finding()` already
    /// said those were findings; the witness disagreed with it. Every finding now names an
    /// event, and the mapping lives beside the enum so a new variant cannot be added without
    /// answering this question.
    pub fn chain_event(&self) -> Option<&'static str> {
        match self {
            ConfigVerdict::Verified { .. } => None,
            ConfigVerdict::Miswired { .. } => Some("config_miswire"),
            ConfigVerdict::Missing { .. }
            | ConfigVerdict::Unreadable { .. }
            | ConfigVerdict::Unbacked { .. } => Some("config_integrity_finding"),
        }
    }

    /// Short status word for the witness payload, so one event type stays queryable.
    pub fn status(&self) -> &'static str {
        match self {
            ConfigVerdict::Verified { .. } => "verified",
            ConfigVerdict::Miswired { .. } => "miswired",
            ConfigVerdict::Missing { .. } => "missing",
            ConfigVerdict::Unreadable { .. } => "unreadable",
            ConfigVerdict::Unbacked { .. } => "unbacked",
        }
    }
}

/// A rendered `KEY=value` line is CONFIG THAT WILL BE SOURCED. Validate before rendering.
///
/// GPT review of #898, finding 5. `render()` wrote arbitrary vault keys and values raw, so a
/// value containing a newline does not produce a wrong assignment — it produces EXTRA
/// assignments, changing how many variables the file sets and what they are. The vault is
/// authoritative, but authoritative malformed data must be refused rather than rendered
/// ambiguously, because the rendered file is executable config and the digest check would
/// happily certify the injected version as correct.
pub fn validate_env_pair(k: &str, v: &str) -> Result<(), String> {
    if k.is_empty() {
        return Err("empty environment key".to_string());
    }
    let mut chars = k.chars();
    let first = chars.next().unwrap();
    if !(first.is_ascii_alphabetic() || first == '_') {
        return Err(format!(
            "environment key '{k}' must start with a letter or underscore"
        ));
    }
    if !k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err(format!(
            "environment key '{k}' may only contain letters, digits and underscores"
        ));
    }
    if v.contains('\n') || v.contains('\r') {
        return Err(format!(
            "value for '{k}' contains a line break, which would render as additional \
             assignments rather than as one value"
        ));
    }
    if v.contains('\0') {
        return Err(format!("value for '{k}' contains a NUL byte"));
    }
    Ok(())
}

impl SeatConfig {
    /// Every pair must be renderable, or the whole config is refused. Partial rendering would
    /// write a file that is neither the vault's content nor a recognisable failure.
    pub fn validate(&self) -> Result<(), String> {
        for (k, v) in &self.env {
            validate_env_pair(k, v)?;
        }
        Ok(())
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

/// Move an unbacked projection aside so nothing can read it as current.
///
/// RENAMED, NOT DELETED. The stale file is the only evidence of what the seat was running with
/// before the vault stopped backing it, and a migration that destroys its own predecessor state
/// cannot be diagnosed afterwards. The suffix is fixed rather than timestamped so repeated
/// passes converge instead of littering: quarantining twice overwrites the first quarantine,
/// which is correct — the interesting artifact is the one that was live.
///
/// Returns the quarantine path when something was moved, `None` when there was nothing there.
pub fn quarantine(home: &Path, member: &str) -> std::io::Result<Option<PathBuf>> {
    let path = render_path(home, member);
    match std::fs::metadata(&path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e),
        Ok(_) => {
            let dest = path.with_extension("env.unbacked");
            std::fs::rename(&path, &dest)?;
            Ok(Some(dest))
        }
    }
}

/// Write the rendered artifact. Returns whether the bytes on disk CHANGED.
///
/// Atomic by rename, so a reader never sees a half-written config: a seat that read a truncated
/// env file would resolve a wrong workspace root and enforce against the wrong tree, which is
/// the failure this whole document exists to end.
pub fn render_to_disk(home: &Path, member: &str, cfg: &SeatConfig) -> std::io::Result<bool> {
    // Refuse here as well as at the call site. A writer that trusts its caller to have
    // validated is one refactor away from writing an injected file, and this is the only
    // function in the module that makes bytes durable.
    if let Err(msg) = cfg.validate() {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, msg));
    }
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

    /// A newline in a vault value would render as EXTRA ASSIGNMENTS, not as a wrong value.
    ///
    /// GPT review of #898, finding 5. This is the arm that fails on the original `render()`,
    /// which wrote `format!("{k}={v}\n")` raw. The consequence is worse than a bad value: the
    /// rendered file sets a different NUMBER of variables than the vault declares, and the
    /// digest check then certifies the injected file as correct, because it is exactly what the
    /// renderer produces. Refusing at validation is the only point where the two can still be
    /// told apart.
    #[test]
    fn a_value_carrying_a_line_break_is_refused_rather_than_rendered() {
        let mut env = BTreeMap::new();
        env.insert(
            "HESTIA_WORKSPACE".to_string(),
            "/w/ai\nHESTIA_ROLE=role:constellation:sovereign".to_string(),
        );
        let bad = SeatConfig { env, note: String::new() };

        let err = bad.validate().expect_err("an injected value must not validate");
        assert!(err.contains("line break"), "the refusal names the reason: {err}");

        // And nothing reaches disk, checked separately: a validator nobody calls at the write
        // site is a claim, not a guard.
        let dir = tempfile::tempdir().unwrap();
        let e = render_to_disk(dir.path(), "claude-code", &bad)
            .expect_err("the writer refuses too, not only the caller");
        assert_eq!(e.kind(), std::io::ErrorKind::InvalidData);
        assert!(
            !render_path(dir.path(), "claude-code").exists(),
            "no partial artifact is left behind"
        );
    }

    #[test]
    fn an_unusable_environment_key_is_refused() {
        for bad_key in ["", "9LEADING_DIGIT", "HAS-DASH", "HAS SPACE", "HAS=EQUALS"] {
            let mut env = BTreeMap::new();
            env.insert(bad_key.to_string(), "value".to_string());
            let cfg = SeatConfig { env, note: String::new() };
            assert!(
                cfg.validate().is_err(),
                "key {bad_key:?} must be refused: it does not render as one assignment"
            );
        }
        // The positive control, so the rule is not simply "refuse everything".
        assert!(cfg().validate().is_ok(), "an ordinary config still validates");
    }

    /// Quarantine preserves rather than destroys, and is idempotent.
    #[test]
    fn quarantine_moves_the_artifact_aside_and_converges() {
        let dir = tempfile::tempdir().unwrap();
        let p = render_path(dir.path(), "codex");
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(&p, "HESTIA_WORKSPACE=/authored/by/hand\n").unwrap();

        let moved = quarantine(dir.path(), "codex").unwrap().expect("something moved");
        assert!(!p.exists(), "not readable where a seat would source it");
        assert_eq!(
            std::fs::read_to_string(&moved).unwrap(),
            "HESTIA_WORKSPACE=/authored/by/hand\n",
            "the evidence is preserved verbatim"
        );
        assert!(
            quarantine(dir.path(), "codex").unwrap().is_none(),
            "quarantining nothing reports nothing rather than erroring"
        );
    }
}
