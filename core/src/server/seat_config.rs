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
//!   * No seat or hook loads the rendered artifact at startup. It is written and checked and
//!     then read by nobody, so a correct render and a quarantined one have the same effect on a
//!     running seat: none.
//!   * Readiness does not consume the verdicts, so an INDETERMINATE seat still reports as it
//!     did before.
//!
//! Until those two are wired, this module makes drift VISIBLE and makes an unbacked artifact
//! UNUSABLE. It does not yet make the vault the thing a seat actually starts from. Saying so is
//! the point: an unconsumed producer that reads as a completed mechanism is the defect this
//! codebase keeps re-finding, and it is not improved by being introduced with confidence.
//!
//! CLOSED SINCE: the enumeration limit named here was the third item, and `members_to_check`
//! replaced it with the union of vault-declared, connected and on-disk. Struck rather than left
//! standing, because a limits section that outlives its limits is how a reader concludes a fixed
//! thing is still broken, and how an author concludes it is still on the list.

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

/// THE SHARED SET (dp, 2026-09-05: "we need a SHARED set, and only genuinely per-harness vars
/// belong in individual configs. that's the whole part about a common gate").
///
/// One reserved document in the same namespace, written and read through the same operator
/// API. Every seat's projection is `shared ∪ own`, and SHARED WINS: the society's facts — where
/// home is, which workspace is governed, where the common runtime and the endpoint are — are
/// not a seat's to restate. A seat document that repeats a shared key is refused at the write
/// door (`keys_owned_by_shared`), and a collision that already exists is reported as
/// `shadowed` rather than silently resolved either way. Per-seat law was the defect the common
/// gate ended; per-seat config of common facts is the same defect one layer down.
///
/// `_shared` is never a member: it renders no artifact of its own, is excluded from the check
/// domain, and cannot be a seat's plugin_id.
pub const SHARED_MEMBER: &str = "_shared";

pub fn is_shared(member: &str) -> bool {
    member == SHARED_MEMBER
}

/// The shared document as the vault holds it. `None` when no shared set has been written yet
/// (every seat renders its own document alone); `Some(Err)` when the vault declares one that
/// cannot be used — which makes EVERY seat's projection unbacked, because a projection built on
/// an unusable authority is not a projection.
pub fn load_shared(vault: &crate::vault::Vault) -> Option<Result<SeatConfig, String>> {
    vault.get_document(SEAT_CONFIG_NS, SHARED_MEMBER).map(|bytes| {
        serde_json::from_slice::<SeatConfig>(bytes)
            .map_err(|e| format!("shared config does not decode as seat config: {e}"))
            .and_then(|c| c.validate().map(|_| c))
    })
}

/// ATTRIBUTION (dp, 2026-09-05: "make sure the right vars are attributed to the right
/// entity"). A seat's identity is a fact of WHICH document this is, not a value an operator
/// types: `HESTIA_PLUGIN_ID` is rendered from the document's name, and a document that
/// states a different one is refused at the door (`validate_attribution`). Without this, a
/// typo or a break-glass edit could put another seat's id into a document and every
/// outcome, notice and mailbox of that seat would be attributed to the other -- attribution
/// laundered through config. The shared set carries no identity-shaped key for the same
/// reason: identity is the one thing that is never shared.
pub const ATTRIBUTION_KEY: &str = "HESTIA_PLUGIN_ID";
/// Keys that name WHO a seat is. Refused in `_shared`; the first is derived per seat.
pub const IDENTITY_KEYS: [&str; 4] = [
    "HESTIA_PLUGIN_ID", "HESTIA_MESH_PLUGIN", "HESTIA_MESH_HOST_AGENT", "HESTIA_HOST_AGENT",
];

/// Refuse a document that mis-attributes. `member` is the document's name.
pub fn validate_attribution(member: &str, cfg: &SeatConfig) -> Result<(), String> {
    if is_shared(member) {
        let carried: Vec<&str> = IDENTITY_KEYS.iter().copied().filter(|k| cfg.env.contains_key(*k)).collect();
        if !carried.is_empty() {
            return Err(format!(
                "the shared set may not carry identity keys {carried:?}: identity is per seat and \
                 is never shared"
            ));
        }
        return Ok(());
    }
    if let Some(stated) = cfg.env.get(ATTRIBUTION_KEY) {
        if stated != member {
            return Err(format!(
                "{ATTRIBUTION_KEY}={stated:?} in the document for {member:?}: a seat's id is derived \
                 from its document's name and cannot be restated as another seat"
            ));
        }
    }
    Ok(())
}

/// The projection a seat actually renders: shared first, own on top, shared winning on a
/// collision, and the seat's identity DERIVED from the document name. Returns the composed
/// config and the keys the seat tried to restate.
pub fn effective(shared: Option<&SeatConfig>, own: &SeatConfig) -> (SeatConfig, Vec<String>) {
    let mut env = own.env.clone();
    let mut shadowed = Vec::new();
    if let Some(sh) = shared {
        for (k, v) in &sh.env {
            if own.env.contains_key(k) {
                shadowed.push(k.clone());
            }
            env.insert(k.clone(), v.clone());
        }
    }
    (SeatConfig { env, note: own.note.clone() }, shadowed)
}

/// `effective` with the identity line rendered from the member name -- the composition
/// every projection uses. Kept apart from `effective` so the shadowed report stays about the
/// operator's own keys.
pub fn effective_for(member: &str, shared: Option<&SeatConfig>, own: &SeatConfig) -> (SeatConfig, Vec<String>) {
    let (mut eff, shadowed) = effective(shared, own);
    if !is_shared(member) {
        eff.env.insert(ATTRIBUTION_KEY.to_string(), member.to_string());
    }
    (eff, shadowed)
}

/// Keys a seat document may not carry because the shared set owns them. Checked at the write
/// door so a new collision cannot be created; `effective()` reports the ones that exist.
pub fn keys_owned_by_shared(shared: Option<&SeatConfig>, own: &SeatConfig) -> Vec<String> {
    match shared {
        Some(sh) => own.env.keys().filter(|k| sh.env.contains_key(*k)).cloned().collect(),
        None => Vec::new(),
    }
}

/// The exact bytes a seat's projection renders to, with the shared keys named in the header so
/// a reader of the file can tell which lines the seat owns. Byte-identical to `render()` when
/// there is no shared set, so existing projections do not read as drift the day this lands.
pub fn render_effective(member: &str, shared: Option<&SeatConfig>, own: &SeatConfig) -> (String, Vec<String>) {
    let (eff, shadowed) = effective_for(member, shared, own);
    let mut out = render(member, &eff);
    if let Some(sh) = shared {
        if !sh.env.is_empty() {
            let keys: Vec<&str> = sh.env.keys().map(String::as_str).collect();
            // Inserted after the member line so the header stays: source, warning, member, provenance.
            let marker = format!("# member: {member}\n");
            let line = format!("# shared: {}\n", keys.join(" "));
            out = out.replacen(&marker, &format!("{marker}{line}"), 1);
        }
    }
    (out, shadowed)
}

/// `verify_one` over the composed projection.
pub fn verify_effective(home: &Path, member: &str, shared: Option<&SeatConfig>, own: &SeatConfig) -> ConfigVerdict {
    let (expected_bytes, _) = render_effective(member, shared, own);
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

/// `render_to_disk` over the composed projection. Returns whether the bytes on disk CHANGED.
pub fn render_effective_to_disk(home: &Path, member: &str, shared: Option<&SeatConfig>, own: &SeatConfig) -> std::io::Result<bool> {
    let (eff, _) = effective_for(member, shared, own);
    if let Err(msg) = eff.validate() {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, msg));
    }
    let path = render_path(home, member);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let (bytes, _) = render_effective(member, shared, own);
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

/// Every member this pass must look at, from all three places one can appear.
///
/// GPT review of #898, finding 4. The worker enumerated `gate_capabilities.keys()`, which is a
/// record of who has CONNECTED and reported a capability this daemon run. That set answers a
/// different question than "who has config", and using it meant:
///
///   * a member the vault configures but that has not connected is never rendered, so the
///     workspace-root move is not a one-vault-change operation for it;
///   * a stray artifact belonging to a member in neither list is never quarantined, because
///     nothing enumerates it — the exact case the quarantine was added for;
///   * "every seat is verified" was true only of seats that happened to report a capability.
///
/// The union of the three is the honest domain: what the vault declares, what has connected,
/// and what is already written on disk. Sorted and de-duplicated so a pass is deterministic and
/// two runs produce the same order of chain rows.
pub fn members_to_check(vault: &crate::vault::Vault, home: &Path, connected: &[String]) -> Vec<String> {
    let mut set: std::collections::BTreeSet<String> = connected.iter().cloned().collect();

    // 1. Declared in the vault. The authority, and the reason this function exists.
    for item in vault.document_index() {
        // The shared set is authority every seat inherits, not a seat: no artifact, no verdict.
        if item.namespace == SEAT_CONFIG_NS && !is_shared(&item.name) {
            set.insert(item.name);
        }
    }

    // 2. Already rendered on disk. A file nobody enumerates cannot be quarantined, and an
    //    orphan artifact is precisely what has no other trace.
    if let Ok(entries) = std::fs::read_dir(home.join(RENDER_DIR)) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            // Only live projections. `.env.unbacked` quarantines and `.env.tmp` write-temporaries
            // must not be read back as members, or a quarantine would resurrect its own subject
            // as a new member name on the next pass.
            if let Some(member) = name.strip_suffix(".env") {
                if !member.is_empty() {
                    set.insert(member.to_string());
                }
            }
        }
    }

    set.into_iter().collect()
}

/// The three chain event types this module writes. Kept beside `chain_event()` so the writer
/// and the reader cannot drift apart: a new event name added there without adding it here would
/// make findings that can be opened but never rehydrated.
pub const FINDING_EVENT_TYPES: [&str; 3] = [
    "config_miswire",
    "config_integrity_finding",
    "config_integrity_resolved",
];

/// How many config events to look back over when rebuilding open findings at startup.
///
/// Bounded, and the bound is honest: a finding older than this many CONFIG events, with nothing
/// newer for the same member, is not rehydrated and its resolution row is lost. The filter is by
/// event type, so this is a walk over config history rather than over the chain — on this box
/// that is a few hundred rows against ~160k entries.
pub const REHYDRATE_SCAN_LIMIT: u64 = 10_000;

/// Rebuild "which members currently have an open config finding" from the chain.
///
/// WHY THIS EXISTS (GPT blocker on #898, after the three-state fix). `config_findings_open` is
/// memory-only, and the pass that OPENS a finding also REPAIRS the artifact. So:
///
///   miswire detected -> opening row on the chain -> artifact repaired -> daemon restarts
///   -> in-memory state gone -> next pass sees a clean artifact -> no resolution row
///
/// and the chain is left asserting a finding that is permanently open, for drift that was fixed
/// before the restart. My own comment claimed losing the map "re-opens the finding, which is the
/// safe direction". That was wrong: because the repair already happened in the opening pass,
/// nothing re-opens. The state loss removes only the ability to CLOSE.
///
/// The map stays derived observation state rather than becoming vault authority — the chain
/// already records both edges, so it is the source, and reconstructing from it is cheaper and
/// more honest than maintaining a second durable copy that could itself drift.
///
/// Newest-first, first row per member wins: a resolution means closed, any finding means open.
pub fn rehydrate_open_findings(
    chain: &crate::storage::chain::SqliteChainStore,
) -> std::collections::HashMap<String, u64> {
    let mut open = std::collections::HashMap::new();
    let mut decided = std::collections::HashSet::new();
    let rows = match chain.read_recent_by_types(None, &FINDING_EVENT_TYPES, REHYDRATE_SCAN_LIMIT) {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!(error = %e,
                "could not rebuild open config findings from the chain; \
                 resolutions for findings opened before this restart will not be recorded");
            return open;
        }
    };
    for entry in rows {
        let Some(member) = entry.event_data.get("member").and_then(|v| v.as_str()) else {
            continue;
        };
        // The newest row for a member decides its state; older ones are history.
        if !decided.insert(member.to_string()) {
            continue;
        }
        if entry.event_type == "config_integrity_resolved" {
            continue;
        }
        let first_observed = entry
            .event_data
            .get("first_observed_at")
            .and_then(|v| v.as_u64())
            // A row written before `first_observed_at` existed still has a timestamp, and an
            // approximate open time beats dropping the finding on the floor.
            .unwrap_or_else(|| entry.timestamp.timestamp().max(0) as u64);
        open.insert(member.to_string(), first_observed);
    }
    open
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
    fn a_seat_is_attributed_by_its_document_name_not_by_a_typed_value() {
        // derived: a document with no id renders one, from its name
        let (eff, _) = effective_for("kimi-code", None, &cfg());
        assert_eq!(eff.env["HESTIA_PLUGIN_ID"], "kimi-code");
        let (rendered, _) = render_effective("kimi-code", None, &cfg());
        assert!(rendered.contains("HESTIA_PLUGIN_ID=kimi-code\n"), "{rendered}");
        // stated the same: fine
        let mut same = cfg();
        same.env.insert("HESTIA_PLUGIN_ID".into(), "kimi-code".into());
        assert!(validate_attribution("kimi-code", &same).is_ok());
        // stated as ANOTHER seat: refused -- this is the laundering the check exists to stop
        let mut other = cfg();
        other.env.insert("HESTIA_PLUGIN_ID".into(), "codex".into());
        let err = validate_attribution("kimi-code", &other).unwrap_err();
        assert!(err.contains("derived from its document's name"), "{err}");
        // and even if such a document existed, the render would still say the truth
        let (eff, _) = effective_for("kimi-code", None, &other);
        assert_eq!(eff.env["HESTIA_PLUGIN_ID"], "kimi-code", "the name wins over the typed value");
        // the shared set may not carry identity
        let mut sh = SeatConfig::default();
        sh.env.insert("HESTIA_MESH_PLUGIN".into(), "claude-code".into());
        let err = validate_attribution(SHARED_MEMBER, &sh).unwrap_err();
        assert!(err.contains("never shared"), "{err}");
        // _shared itself renders no identity line
        let (eff, _) = effective_for(SHARED_MEMBER, None, &sh);
        assert!(!eff.env.contains_key("HESTIA_PLUGIN_ID"));
    }

    #[test]
    fn the_shared_set_is_inherited_and_wins_and_names_itself() {
        let mut sh_env = BTreeMap::new();
        sh_env.insert("HESTIA_HOME".to_string(), "/h".to_string());
        sh_env.insert("HESTIA_WORKSPACE".to_string(), "/w/shared".to_string());
        let shared = SeatConfig { env: sh_env, note: "society".into() };
        // own restates HESTIA_WORKSPACE with a different value: shared wins, and it is reported
        let (eff, shadowed) = effective(Some(&shared), &cfg());
        assert_eq!(eff.env["HESTIA_WORKSPACE"], "/w/shared", "shared wins on a collision");
        assert_eq!(eff.env["HESTIA_HOME"], "/h");
        assert_eq!(eff.env["HESTIA_ROLE"], "role:constellation:member", "own keys survive");
        assert_eq!(shadowed, vec!["HESTIA_WORKSPACE".to_string()]);
        assert_eq!(keys_owned_by_shared(Some(&shared), &cfg()), vec!["HESTIA_WORKSPACE".to_string()]);
        // the projection names the shared keys in its header, and stays byte-identical to the
        // plain render when there is no shared set
        let (with, _) = render_effective("claude-code", Some(&shared), &cfg());
        assert!(with.contains("# shared: HESTIA_HOME HESTIA_WORKSPACE\n"), "{with}");
        // With no shared set the render is the plain render of the seat's own config PLUS the
        // one derived line: identity comes from the document's name, never from the header.
        let (without, _) = render_effective("claude-code", None, &cfg());
        let (eff, _) = effective_for("claude-code", None, &cfg());
        assert_eq!(without, render("claude-code", &eff));
        assert!(without.contains("HESTIA_PLUGIN_ID=claude-code\n"), "{without}");
        assert!(!without.contains("# shared:"), "no shared header without a shared set: {without}");
        // _shared is never a member of the check domain
        assert!(is_shared(SHARED_MEMBER));
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

    /// The domain is the UNION of three sources, and each one contributes something the
    /// others cannot see.
    ///
    /// The orphan case is the point: a rendered artifact belonging to a member that neither the
    /// vault declares nor the daemon has seen connect. Under the old enumeration
    /// (`gate_capabilities.keys()`) nothing looked at it, so the quarantine added for exactly
    /// that file could never fire on it. A fix whose trigger is unreachable is not a fix.
    #[test]
    fn the_check_domain_unions_vault_connected_and_on_disk() {
        let dir = tempfile::tempdir().unwrap();
        let mut vault =
            crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        vault
            .put_document(SEAT_CONFIG_NS, "declared-only", b"{}".to_vec())
            .unwrap();

        // An artifact with no vault document and no connection: the orphan.
        let orphan = render_path(dir.path(), "on-disk-only");
        std::fs::create_dir_all(orphan.parent().unwrap()).unwrap();
        std::fs::write(&orphan, "X=1\n").unwrap();
        // Neighbours that must NOT be read back as members, or a quarantine would resurrect
        // its own subject on the next pass and a write-temporary would become a seat.
        std::fs::write(orphan.with_extension("env.unbacked"), "X=1\n").unwrap();
        std::fs::write(orphan.with_extension("env.tmp"), "X=1\n").unwrap();

        let members = members_to_check(&vault, dir.path(), &["connected-only".to_string()]);

        assert!(members.contains(&"declared-only".to_string()), "{members:?}");
        assert!(members.contains(&"connected-only".to_string()), "{members:?}");
        assert!(
            members.contains(&"on-disk-only".to_string()),
            "an orphan artifact must be enumerated or it can never be quarantined: {members:?}"
        );
        assert!(
            !members.iter().any(|m| m.contains("unbacked") || m.contains("tmp")),
            "quarantines and write-temporaries are not members: {members:?}"
        );
        let mut sorted = members.clone();
        sorted.sort();
        assert_eq!(members, sorted, "deterministic order, so chain rows are reproducible");
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
