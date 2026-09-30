//! What a governance write would actually DO — assembled once, read by everyone who decides.
//!
//! `PRD_ADJUDICATOR_LADDER.md` §3.3 states the rule this module exists to make true:
//!
//! > **If a rung sees less than the human would, it is not a rung. It is a filter.**
//!
//! The ladder's rungs (heuristic gate, policy-entity agent, human operator) must read the
//! SAME evidence, or a promotion measured on agreement is measuring two different questions.
//! The cheapest way to guarantee that is to have one function build the object and every
//! surface render it — which is why this is a module and not a dashboard field.
//!
//! WHY IT STARTS WITH THE DIFF. On 2026-09-17 an operator was asked to approve
//! `cp /tmp/codex_hook_next.txt plugins/codex/hooks/pre_tool_use.py`, on a card carrying a
//! tool name, a path fragment, and the sentence the gate writes when it auto-opens: *"the
//! member stated no rationale because it did not choose to escalate."* The write was a
//! fifteen-line comment correction and entirely legitimate. Nothing on the card could have
//! said so. The operator approved it, then asked afterwards whether they should have —
//! which is the question a decision surface exists to answer BEFORE the button.
//!
//! An act that says `cp A B` is not self-describing. An act that says `cp A B, and here are
//! the 15 lines that changes` is.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::SystemTime;

/// Beyond this, a side of the comparison is summarised rather than diffed. The LCS table is
/// O(n·m), so this is a memory bound, not a taste one: 4000² u32 is ~64 MB and that is
/// already more than a governance file can justify. A hook is ~1300 lines.
pub const MAX_DIFF_LINES: usize = 4_000;

/// How much diff the bundle carries. A reviewer scrolling 900 changed lines on a card is not
/// reviewing; the honest move is to show the first hunks and SAY that it truncated, so the
/// reader knows to open the file rather than believing they have seen it.
pub const MAX_RENDERED_DIFF_LINES: usize = 240;

/// The source and destination of a copy-shaped act, when it has them.
///
/// Deliberately narrow: `cp`-shaped acts are 63 of 122 spent approvals (#1056), and a parser
/// that tried to understand every shell construction would be guessing on the ones that
/// matter least. An act this cannot read yields `None`, and a `None` here degrades the bundle
/// rather than blocking anything.
pub fn copy_operands(act: &str) -> Option<(PathBuf, String)> {
    let toks: Vec<&str> = act.split_whitespace().collect();
    let (dest, before) = toks.split_last()?;
    // `..` is refused rather than normalised: the daemon does not share the member's working
    // directory, so a path it cannot resolve unambiguously is one it must not claim to have
    // read. Under-reporting is the safe direction for a field a human reads as fact.
    let src = before
        .iter()
        .find(|t| t.starts_with('/') && !t.contains(".."))
        .map(Path::new)?;
    Some((src.to_path_buf(), dest.trim().to_string()))
}

/// The copy of a governed file that is CURRENTLY IN FORCE, if the daemon can find it.
///
/// This is deliberately not "the destination". The destination in these acts is repo-relative
/// (`plugins/codex/hooks/pre_tool_use.py`) and resolves against a working directory the daemon
/// does not share, so any absolute path it produced would be a guess presented as a fact. What
/// the daemon DOES know unambiguously is its own deploy tree — the copy that actually enforces
/// — and "how would this differ from what is enforcing right now" is the more decision-relevant
/// comparison anyway. The bundle labels it as exactly that.
/// IN A TEST THIS READS THE HOST, NOT THE FIXTURE. `default_hestia_home()` resolves the
/// PROCESS's home, which in production is the daemon's own home and is exactly right — but a
/// test that builds its state in a TempDir still diffs against whatever this machine has
/// installed under `~/.hestia/deploy`. Two consequences, both paid for on 2026-09-18: an
/// assertion about the diff's numbers passes locally for an accidental reason and goes red on
/// CI, and it goes red HERE too the moment another test sets `HOME` for its own purposes
/// (`hub.rs` does). Assert on what the rung READ, never on what the host happens to hold.
pub fn enforcing_copy(dest_token: &str) -> Option<PathBuf> {
    let root = crate::vault::storage::default_hestia_home().ok()?;
    enforcing_copy_under(&root, dest_token)
}

/// The resolution itself, with the root passed in — so it can be tested without mutating a
/// process-wide environment variable, which in a parallel test binary is a race rather than a
/// fixture.
pub fn enforcing_copy_under(home: &Path, dest_token: &str) -> Option<PathBuf> {
    let rel = dest_token.trim().trim_start_matches("./");
    // A destination that is absolute, empty, or path-escaping is not resolved against the
    // deploy root: joining it would either silently ignore the root (absolute) or climb out
    // of it (`..`), and both produce a path this function would then present as "the copy now
    // enforcing" — a false label on a real file, which is the worst of the three outcomes.
    if rel.is_empty() || rel.starts_with('/') || rel.contains("..") {
        return None;
    }
    let p = home.join("deploy").join("hestia").join(rel);
    p.is_file().then_some(p)
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineDiff {
    pub added: usize,
    pub removed: usize,
    /// Unified-ish rendering, already bounded. `truncated` says whether a reader is looking at
    /// all of it — a diff that silently stops is worse than no diff, because it reads as
    /// complete.
    pub rendered: Vec<String>,
    pub truncated: bool,
}

/// Longest-common-subsequence line diff.
///
/// Hand-rolled because the alternative is a dependency, and this runs on the path that decides
/// governance writes: a small exact algorithm whose failure modes are visible beats a large
/// one whose are not. It is O(n·m) and capped at [`MAX_DIFF_LINES`].
pub fn line_diff(before: &str, after: &str) -> LineDiff {
    let a: Vec<&str> = before.lines().collect();
    let b: Vec<&str> = after.lines().collect();
    if a.len() > MAX_DIFF_LINES || b.len() > MAX_DIFF_LINES {
        // No table, no claim. Counting lines is honest and cheap; pretending to have diffed
        // would not be.
        return LineDiff {
            added: b.len(),
            removed: a.len(),
            rendered: vec![format!(
                "(too large to diff: {} lines -> {} lines, cap {})",
                a.len(),
                b.len(),
                MAX_DIFF_LINES
            )],
            truncated: true,
        };
    }
    let (n, m) = (a.len(), b.len());
    let mut lcs = vec![0u32; (n + 1) * (m + 1)];
    let idx = |i: usize, j: usize| i * (m + 1) + j;
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            lcs[idx(i, j)] = if a[i] == b[j] {
                lcs[idx(i + 1, j + 1)] + 1
            } else {
                lcs[idx(i + 1, j)].max(lcs[idx(i, j + 1)])
            };
        }
    }
    let (mut i, mut j) = (0usize, 0usize);
    let (mut added, mut removed) = (0usize, 0usize);
    let mut rendered: Vec<String> = Vec::new();
    let mut truncated = false;
    while i < n && j < m {
        if a[i] == b[j] {
            i += 1;
            j += 1;
        } else if lcs[idx(i + 1, j)] >= lcs[idx(i, j + 1)] {
            removed += 1;
            push_line(&mut rendered, &mut truncated, format!("- {}", a[i]));
            i += 1;
        } else {
            added += 1;
            push_line(&mut rendered, &mut truncated, format!("+ {}", b[j]));
            j += 1;
        }
    }
    while i < n {
        removed += 1;
        push_line(&mut rendered, &mut truncated, format!("- {}", a[i]));
        i += 1;
    }
    while j < m {
        added += 1;
        push_line(&mut rendered, &mut truncated, format!("+ {}", b[j]));
        j += 1;
    }
    LineDiff { added, removed, rendered, truncated }
}

fn push_line(rendered: &mut Vec<String>, truncated: &mut bool, line: String) {
    if rendered.len() < MAX_RENDERED_DIFF_LINES {
        rendered.push(line);
    } else {
        *truncated = true;
    }
}

/// Most entries this holds are for escalations that expire within the hour, so the map is
/// bounded by how many distinct acts are pending — but a bound that depends on good behaviour
/// is not a bound. Cleared wholesale past this size rather than evicted cleverly: this is a
/// render cache, and the expensive thing it protects (the diff) is cheap to recompute once.
const MEMO_MAX_ENTRIES: usize = 64;

/// The identity of the INPUTS, not of the act. Two calls agree only if both files are still
/// the same size with the same mtime — so a source rewritten between two dashboard polls
/// recomputes, which is the entire behaviour this cache must not break.
type MemoKey = (String, Option<(u64, u64)>, Option<(u64, u64)>);

static EFFECT_MEMO: Mutex<Option<HashMap<MemoKey, Value>>> = Mutex::new(None);

fn file_identity(p: &Path) -> Option<(u64, u64)> {
    let m = std::fs::metadata(p).ok()?;
    let secs = m
        .modified()
        .ok()
        .and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or(0);
    Some((m.len(), secs))
}

/// `write_effect`, memoised on the identity of the files it reads.
///
/// THE REASON THIS EXISTS AT ALL: the dashboard renders pending escalations on every poll, and
/// the uncached form re-reads a ~52 KB hook and runs an O(n·m) diff over ~1300 lines each
/// time. That is #1040 exactly — a projection rebuilt per poll on an idle chain, which
/// measured at most of a core with the page open — and re-introducing it one PR after fixing
/// it would be its own kind of finding. A render surface must not be an unbounded recompute.
pub fn write_effect_cached(act: &str) -> Option<Value> {
    if let Some(patch) = crate::server::gate_escalation::EscalationStore::patch_file_of_act(act) {
        let key: MemoKey = (act.to_string(), file_identity(&patch), None);
        if let Ok(g) = EFFECT_MEMO.lock() {
            if let Some(hit) = g.as_ref().and_then(|m| m.get(&key)) {
                return Some(hit.clone());
            }
        }
        let computed = patch_effect(&patch, act);
        if let Ok(mut g) = EFFECT_MEMO.lock() {
            let m = g.get_or_insert_with(HashMap::new);
            if m.len() >= MEMO_MAX_ENTRIES {
                m.clear();
            }
            m.insert(key, computed.clone());
        }
        return Some(computed);
    }
    let operands = copy_operands(act);
    let key: MemoKey = (
        act.to_string(),
        operands.as_ref().and_then(|(s, _)| file_identity(s)),
        operands
            .as_ref()
            .and_then(|(_, d)| enforcing_copy(d))
            .as_deref()
            .and_then(file_identity),
    );
    if let Ok(mut g) = EFFECT_MEMO.lock() {
        if let Some(hit) = g.as_ref().and_then(|m| m.get(&key)) {
            return Some(hit.clone());
        }
    }
    let computed = write_effect(act)?;
    if let Ok(mut g) = EFFECT_MEMO.lock() {
        let m = g.get_or_insert_with(HashMap::new);
        if m.len() >= MEMO_MAX_ENTRIES {
            m.clear();
        }
        m.insert(key, computed.clone());
    }
    Some(computed)
}

/// What this act would do, as far as the daemon can establish it FIRSTHAND.
///
/// Every field is either measured or absent. There is no field here that means "probably" —
/// a decision surface that mixes measurement with inference teaches its reader to trust the
/// inference, and the reader is about to authorise a write to the thing that governs them.
pub fn write_effect(act: &str) -> Option<Value> {
    // A patch-application act is recognised FIRST: `git -C <dir> apply <patch>` would otherwise
    // read as a copy from `<dir>` and report a directory as an unreadable source.
    if let Some(patch) = crate::server::gate_escalation::EscalationStore::patch_file_of_act(act) {
        return Some(patch_effect(&patch, act));
    }
    let (src, dest_token) = copy_operands(act)?;
    let meta = std::fs::metadata(&src).ok();
    let readable = meta.as_ref().map(|m| m.is_file()).unwrap_or(false);
    if !readable {
        // The act names an absolute source the daemon cannot read. Worth REPORTING rather
        // than omitting: "this act names a file that is not there" is a fact a reviewer wants
        // before approving, and silence would read as "nothing to see".
        return Some(json!({
            "source": src.display().to_string(),
            "source_readable": false,
            "note": "the act names an absolute source the daemon cannot read as a file; \
                     nothing about its contents is asserted here",
        }));
    }
    // BOUNDED (GPT hold on #1064): the size is checked before anything is allocated, and a
    // source over the cap is REPORTED as unread -- never diffed from a prefix, never counted.
    let cap = crate::server::gate_escalation::MAX_MEASURED_PAYLOAD_BYTES;
    let new_bytes = match crate::server::gate_escalation::read_regular_file_bounded(&src, cap) {
        Ok(b) => b,
        Err(e) => {
            let size = std::fs::metadata(&src).map(|m| m.len()).ok();
            let too_large = matches!(e, crate::server::gate_escalation::BoundedRead::TooLarge(_));
            return Some(json!({
                "source": src.display().to_string(),
                "source_readable": too_large,
                "source_read": false,
                "source_bytes": size,
                "payload_sha256": Value::Null,
                "destination_stated": dest_token,
                "diff": Value::Null,
                "note": match e {
                    crate::server::gate_escalation::BoundedRead::TooLarge(_) => format!(
                        "the source is larger than the {cap}-byte measurement cap; it was NOT \
                         read, so nothing about its contents is asserted and the approval does \
                         not bind its bytes"),
                    _ => "the source could not be read; nothing about its contents is asserted"
                        .to_string(),
                },
            }));
        }
    };
    let new_text = String::from_utf8_lossy(&new_bytes).to_string();
    // The sha of THESE bytes -- the ones summarised below -- which is what the approval binds
    // for them (`measured_payload_for_act` hashes the same file through the same bounded
    // reader). Computed from this buffer, not by a second read, so the card cannot show a
    // digest of different bytes than the diff it renders.
    let payload_sha256 = Some(crate::server::gate_escalation::sha256_hex(&new_bytes));

    let mut out = json!({
        "source": src.display().to_string(),
        "source_readable": true,
        "source_read": true,
        "source_bytes": new_bytes.len(),
        "source_lines": new_text.lines().count(),
        // The same value the approval BINDS (#1056), carried here so a reader can see that
        // the thing they are reviewing and the thing the permit will hold are one object.
        "payload_sha256": payload_sha256,
        "destination_stated": dest_token,
    });

    match enforcing_copy(&dest_token) {
        Some(cur) => {
            out["compared_against"] = json!({
                "path": cur.display().to_string(),
                // NAMED PRECISELY. This is not the destination the act will write; it is the
                // copy currently enforcing. Calling it "the destination" would be a small lie
                // that a reviewer would reasonably rely on.
                "what": "the copy currently ENFORCING on this daemon, not the act's destination",
            });
            // Bounded like the source. An enforcing copy that cannot be read is SAID, never
            // diffed as if it were empty: `unwrap_or_default()` here used to render every line
            // of the source as an addition against a file nobody had read.
            let old_text = match crate::server::gate_escalation::read_regular_file_bounded(&cur, cap) {
                Ok(b) => String::from_utf8_lossy(&b).to_string(),
                Err(_) => {
                    out["enforcing_read"] = json!(false);
                    out["diff"] = Value::Null;
                    out["note"] = json!(
                        "the enforcing copy could not be read within the measurement cap, so no \
                         diff is shown"
                    );
                    return Some(out);
                }
            };
            let d = line_diff(&old_text, &new_text);
            out["added_lines"] = json!(d.added);
            out["removed_lines"] = json!(d.removed);
            out["diff"] = json!(d.rendered);
            out["diff_truncated"] = json!(d.truncated);
            out["identical_to_enforcing"] = json!(d.added == 0 && d.removed == 0);
        }
        None => {
            out["compared_against"] = Value::Null;
            out["note"] = json!(
                "no enforcing copy found for this destination, so no diff is shown — the \
                 destination is stated relative to a working directory the daemon does not share"
            );
        }
    }
    Some(out)
}

/// Per-file summary of a patch, read from its own structure, and an explicit list of what it
/// could NOT represent.
///
/// `incomplete` is the load-bearing field. A summary is shown to a decider as the effect of
/// the act; a summary that silently drops part of the patch lets them endorse bytes they were
/// not shown. So every form this parser does not fully read lands in `incomplete` by name, and
/// a surface must render a non-empty `incomplete` as "this summary is NOT the whole patch".
#[derive(Debug, Default)]
pub struct PatchStat {
    pub files: Vec<Value>,
    pub added: u64,
    pub removed: u64,
    pub incomplete: Vec<String>,
}

/// One file section, holding every name as the patch SPELLS it (C-quoting decoded, nothing
/// stripped). Which path that is on disk depends on the act's strip level and `--directory`,
/// which only the act knows -- so stripping happens once, in `finish`, under a `NameRule`.
#[derive(Debug, Default)]
struct PatchRow {
    diff_git_raw: Option<String>,
    /// `---` / `+++` names; `None` for `/dev/null` or when absent.
    minus_name: Option<String>,
    plus_name: Option<String>,
    /// `rename|copy from|to` names (repo-relative: they carry no diff prefix).
    hdr_from: Option<String>,
    hdr_to: Option<String>,
    is_copy: bool,
    added: u64,
    removed: u64,
    created: bool,
    deleted: bool,
    old_mode: Option<String>,
    new_mode: Option<String>,
    binary: bool,
    /// Path spellings that could not be decoded (a malformed or non-UTF-8 C-quoted name).
    undecodable: Vec<String>,
}

/// How an act turns the names in a patch into paths: the strip level (`-pN`), a `--directory`
/// prefix, and anything in the act this does not model.
///
/// WHY (coordinator, after GPT's re-review of 8caa210): every earlier cut assumed `-p1` in
/// silence. `git apply -p0` on a `git diff --no-prefix` patch writes `a/keep.txt` where the
/// summary said `keep.txt`; `git apply -p2` writes `core/x.rs` where it said
/// `hestia/core/x.rs`. The level is read from the act; when it cannot be, or the act carries
/// an option this does not model, the summary is marked incomplete and says why.
#[derive(Debug, Clone)]
pub struct NameRule {
    /// `None` = could not be determined from the act.
    pub p: Option<usize>,
    pub directory: Option<String>,
    /// `"git"` or `"patch"`: GNU patch's handling of git rename/copy headers is not modelled.
    pub tool: &'static str,
    /// Where `p` came from, in words (shown to the decider).
    pub source: String,
    /// Options in the act that could change which files or lines are affected.
    pub unmodelled: Vec<String>,
}

impl NameRule {
    /// `git apply`'s documented default: `-p1`, no `--directory`.
    pub fn git_default() -> Self {
        NameRule { p: Some(1), directory: None, tool: "git",
                   source: "git apply's default -p1".into(), unmodelled: vec![] }
    }
}

/// Options that do not change WHICH files or lines a `git apply` / `git am` touches.
const GIT_APPLY_OPTS_OK: [&str; 13] = [
    "-3", "--3way", "--index", "--cached", "--intent-to-add", "-N", "-v", "--verbose", "-q",
    "--quiet", "--ignore-whitespace", "--ignore-space-change", "--allow-empty",
];
const GIT_AM_OPTS_OK: [&str; 21] = [
    "-s", "--signoff", "-k", "--keep", "--keep-non-patch", "--keep-cr", "--no-keep-cr", "-c",
    "--scissors", "--no-scissors", "-m", "--message-id", "--no-message-id", "-u", "--utf8",
    "--no-utf8", "--committer-date-is-author-date", "--ignore-date", "--no-gpg-sign",
    "--no-verify", "--no-3way",
];
const PATCH_OPTS_OK: [&str; 12] = [
    "-N", "--forward", "-s", "--silent", "--quiet", "--verbose", "-b", "--backup",
    "--no-backup-if-mismatch", "--backup-if-mismatch", "-t", "--batch",
];

/// Read the name rule from the act's own command. Recognises the same forms as
/// `EscalationStore::patch_file_of_act`: `git [global opts] apply|am …` and `patch …`.
///
/// - git: `-pN` / `-p N` (default `-p1`, stated as the default), `--directory=<d>` /
///   `--directory <d>`; `--include`/`--exclude`, `-R`/`--reverse`, `--recount`, `--no-add`,
///   `--reject` and any other option not known to be neutral are UNMODELLED.
/// - patch: `-pN` / `-p N` / `--strip=N` / `--strip N`, `-d <d>` / `--directory=<d>`; with no
///   `-p`, GNU patch's choice depends on the patch and its version, so the level is
///   UNDETERMINED. A positional file operand (patch applies to that file, whatever the names
///   say) and any unknown option are UNMODELLED.
pub fn patch_name_rule(act: &str) -> NameRule {
    let mut toks: Vec<&str> = act.split_whitespace().collect();
    if toks.first().map(|t| t.ends_with(':')).unwrap_or(false) {
        toks.remove(0);
    }
    let mut rule = NameRule { p: None, directory: None, tool: "git", source: String::new(),
                              unmodelled: vec![] };
    let parse_p = |v: Option<&str>, rule: &mut NameRule, spelled: String| {
        match v.and_then(|v| v.parse::<usize>().ok()) {
            Some(n) => {
                rule.p = Some(n);
                rule.source = format!("`{spelled}` in the act");
            }
            None => {
                rule.p = None;
                rule.source = format!("`{spelled}` in the act is not a strip level");
            }
        }
    };
    match toks.first().copied() {
        Some("git") => {
            let mut i = 1;
            while i < toks.len() && toks[i].starts_with('-') {
                i += if matches!(toks[i], "-C" | "-c") { 2 } else { 1 };
            }
            let am = toks.get(i).copied() == Some("am");
            rule.p = Some(1);
            rule.source = format!("git {}'s default -p1 (no -p in the act)",
                                  if am { "am" } else { "apply" });
            let rest: Vec<&str> = toks.get(i + 1..).unwrap_or(&[]).to_vec();
            let mut j = 0;
            while j < rest.len() {
                let t = rest[j];
                if t == "-p" {
                    j += 1;
                    parse_p(rest.get(j).copied(), &mut rule, format!("-p {}", rest.get(j).unwrap_or(&"")));
                } else if let Some(v) = t.strip_prefix("-p") {
                    parse_p(Some(v), &mut rule, t.to_string());
                } else if t == "--directory" {
                    j += 1;
                    rule.directory = rest.get(j).map(|d| d.to_string());
                } else if let Some(d) = t.strip_prefix("--directory=") {
                    rule.directory = Some(d.to_string());
                } else if t.starts_with("--whitespace=")
                    || (t.starts_with("-C") && t.len() > 2 && t[2..].chars().all(|c| c.is_ascii_digit()))
                    || t == "--unidiff-zero"
                    || GIT_APPLY_OPTS_OK.contains(&t)
                    || (am && (GIT_AM_OPTS_OK.contains(&t) || t.starts_with("-S")
                        || t.starts_with("--gpg-sign") || t.starts_with("--quoted-cr=")
                        || t.starts_with("--empty=") || t.starts_with("--patch-format=")))
                {
                } else if t.starts_with('-') {
                    rule.unmodelled.push(format!("`{t}`"));
                    if matches!(t, "--include" | "--exclude") {
                        j += 1;
                    }
                }
                j += 1;
            }
        }
        Some("patch") => {
            rule.tool = "patch";
            rule.source = "patch(1) was given no -p; its strip level then depends on the                            patch and the patch version".into();
            let mut j = 1;
            while j < toks.len() {
                let t = toks[j];
                if t == "-p" || t == "--strip" {
                    j += 1;
                    parse_p(toks.get(j).copied(), &mut rule, format!("{t} {}", toks.get(j).unwrap_or(&"")));
                } else if let Some(v) = t.strip_prefix("--strip=") {
                    parse_p(Some(v), &mut rule, t.to_string());
                } else if let Some(v) = t.strip_prefix("-p") {
                    parse_p(Some(v), &mut rule, t.to_string());
                } else if t == "-d" || t == "--directory" {
                    j += 1;
                    rule.directory = toks.get(j).map(|d| d.to_string());
                } else if let Some(d) = t.strip_prefix("--directory=") {
                    rule.directory = Some(d.to_string());
                } else if let Some(d) = t.strip_prefix("-d") {
                    rule.directory = Some(d.to_string());
                } else if t == "-i" || t == "<" {
                    j += 1; // the patch file itself
                } else if t.starts_with("--input=") || (t.starts_with('<') && t.len() > 1) {
                } else if PATCH_OPTS_OK.contains(&t) || t.starts_with("--fuzz=")
                    || (t.starts_with("-F") && t.len() > 2)
                {
                } else if t.starts_with('-') {
                    rule.unmodelled.push(format!("`{t}`"));
                } else {
                    rule.unmodelled.push(format!(
                        "file operand `{t}` (patch applies to that file whatever the patch names)"
                    ));
                }
                j += 1;
            }
        }
        _ => {
            rule.source = "the act's patch tool was not recognised".into();
        }
    }
    rule
}

/// Remove `n` leading path components the way `git apply -p<n>` does (a run of slashes
/// counts as one separator). `None` when the name has fewer than `n` components to remove --
/// `git apply` refuses such a patch rather than guessing, and so does this.
fn strip_components(name: &str, n: usize) -> Option<String> {
    let mut rest = name;
    for _ in 0..n {
        let pos = rest.find('/')?;
        rest = rest[pos..].trim_start_matches('/');
    }
    (!rest.is_empty()).then(|| rest.to_string())
}

fn with_directory(dir: &Option<String>, path: String) -> String {
    match dir.as_deref().map(|d| d.trim_end_matches('/')) {
        Some(d) if !d.is_empty() => format!("{d}/{path}"),
        _ => path,
    }
}

/// Git C-quotes a path that contains a `"`, a backslash, a control character or (under the
/// default `core.quotePath`) any non-ASCII byte: `"a/sp ace\tx"`, `"\303\251t\303\251.txt"`.
/// Decode one such token at the start of `s`; return the path and the text after the closing
/// quote. `None` for an unterminated quote, an escape git does not emit, or bytes that are not
/// UTF-8 -- the caller reports that, it never shows the escaped spelling as if it were a path.
fn unquote_c(s: &str) -> Option<(String, &str)> {
    let b = s.as_bytes();
    if b.first() != Some(&b'"') {
        return None;
    }
    let mut out: Vec<u8> = Vec::new();
    let mut i = 1;
    while i < b.len() {
        match b[i] {
            b'"' => return String::from_utf8(out).ok().map(|p| (p, &s[i + 1..])),
            b'\\' => {
                let c = *b.get(i + 1)?;
                let v = match c {
                    b'a' => 7,
                    b'b' => 8,
                    b't' => 9,
                    b'n' => 10,
                    b'v' => 11,
                    b'f' => 12,
                    b'r' => 13,
                    b'"' => b'"',
                    b'\\' => b'\\',
                    b'0'..=b'3' => {
                        let d = b.get(i + 1..i + 4)?;
                        if !d.iter().all(|x| (b'0'..=b'7').contains(x)) {
                            return None;
                        }
                        i += 2;
                        (d[0] - b'0') * 64 + (d[1] - b'0') * 8 + (d[2] - b'0')
                    }
                    _ => return None,
                };
                out.push(v);
                i += 2;
            }
            x => {
                out.push(x);
                i += 1;
            }
        }
    }
    None
}

/// A name from an EXTENDED header (`rename from/to`, `copy from/to`), decoded if C-quoted.
/// These are repo-relative and carry NO diff prefix: `git apply -pN` strips N-1 components
/// from them, not N. (e0df1c9 stripped `a/`/`b/` from them and reported
/// `rename a/old.txt => b/new.txt` as `old.txt => new.txt`: GPT re-review, 2026-09-30.)
fn header_name(v: &str) -> Option<String> {
    if v.starts_with('"') {
        let (p, rest) = unquote_c(v)?;
        return rest.is_empty().then_some(p);
    }
    Some(v.to_string())
}

/// The name on a `--- ` / `+++ ` line, decoded if C-quoted, with a trailing tab-separated
/// timestamp (plain `diff -u`) dropped. Nothing is stripped here. `None` if undecodable.
fn diff_side_name(t: &str) -> Option<String> {
    if t.starts_with('"') {
        let (p, rest) = unquote_c(t)?;
        return (rest.is_empty() || rest.starts_with('\t')).then_some(p);
    }
    Some(t.split('\t').next().unwrap_or(t).trim().to_string())
}

/// Every way `diff --git <rest>` can be read as two names. A quoted side is unambiguous; two
/// unquoted names may contain spaces, so every split at a space is a candidate and the caller
/// keeps only the one its other evidence (equal paths, or the rename headers) confirms.
fn diff_git_candidates(rest: &str) -> Vec<(String, String)> {
    if rest.starts_with('"') {
        let Some((a, r)) = unquote_c(rest) else { return vec![] };
        let Some(r) = r.strip_prefix(' ') else { return vec![] };
        if r.starts_with('"') {
            return match unquote_c(r) {
                Some((b, tail)) if tail.is_empty() => vec![(a, b)],
                _ => vec![],
            };
        }
        return vec![(a, r.to_string())];
    }
    if rest.ends_with('"') {
        let Some(pos) = rest.find(" \"") else { return vec![] };
        return match unquote_c(&rest[pos + 1..]) {
            Some((b, tail)) if tail.is_empty() => vec![(rest[..pos].to_string(), b)],
            _ => vec![],
        };
    }
    rest.match_indices(' ')
        .map(|(i, _)| (rest[..i].to_string(), rest[i + 1..].to_string()))
        .collect()
}

/// `12a13`, `5,7c5,8`, `3d2` -- a normal-format diff command line (GNU `patch` reads these).
fn is_normal_diff_command(l: &str) -> bool {
    let Some(pos) = l.find(|c: char| matches!(c, 'a' | 'c' | 'd')) else { return false };
    let (a, b) = (&l[..pos], &l[pos + 1..]);
    let num = |s: &str| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit() || c == ',')
        && s.starts_with(|c: char| c.is_ascii_digit());
    num(a) && num(b)
}

/// Consume one hunk whose `@@ -a,b +c,d @@` header is `h`, by its DECLARED counts. Returns
/// false when the header does not parse or the patch ends (or a new file starts) before the
/// declared lines do: a cut-off hunk is reported, not counted as if it were whole.
fn consume_hunk<'a, I: Iterator<Item = &'a str>>(
    h: &str,
    it: &mut std::iter::Peekable<I>,
    add: &mut u64,
    del: &mut u64,
) -> bool {
    fn count(spec: &str) -> Option<u64> {
        // "a,b" -> b ; "a" -> 1
        match spec.split_once(',') {
            Some((_, n)) => n.parse().ok(),
            None => spec.parse::<u64>().ok().map(|_| 1),
        }
    }
    let mut parts = h.split_whitespace().skip(1);
    let (Some(o), Some(n)) = (
        parts.next().and_then(|t| t.strip_prefix('-')).and_then(count),
        parts.next().and_then(|t| t.strip_prefix('+')).and_then(count),
    ) else {
        return false;
    };
    let (mut o, mut n) = (o, n);
    while o > 0 || n > 0 {
        match it.peek() {
            None => return false,
            Some(l) if l.starts_with("diff --git ") => return false,
            Some(_) => {}
        }
        let l = it.next().unwrap_or_default();
        match l.as_bytes().first().copied() {
            Some(b'-') => { *del += 1; o = o.saturating_sub(1); }
            Some(b'+') => { *add += 1; n = n.saturating_sub(1); }
            Some(b'\\') => {} // "\ No newline at end of file"
            _ => { o = o.saturating_sub(1); n = n.saturating_sub(1); }
        }
    }
    // a trailing "\ No newline" marker after the counts ran out
    while it.peek().map(|l| l.starts_with('\\')).unwrap_or(false) {
        it.next();
    }
    true
}

impl PatchRow {
    fn finish(self, st: &mut PatchStat, rule: &NameRule) {
        let raw = self.diff_git_raw.clone().unwrap_or_default();
        let short = |s: &str| s.chars().take(80).collect::<String>();
        for u in &self.undecodable {
            st.incomplete.push(format!(
                "a path spelled `{}` could not be decoded (malformed or non-UTF-8 quoting); it \
                 is not shown as a path",
                short(u)
            ));
        }
        // An undetermined level has already been reported by the caller; names are then
        // computed at -p1 and that report says so.
        let p = rule.p.unwrap_or(1);
        let hp = p.saturating_sub(1);
        let mut too_short: Vec<String> = Vec::new();
        let mut strip = |name: &str, n: usize| -> Option<String> {
            let r = strip_components(name, n);
            if r.is_none() {
                too_short.push(name.to_string());
            }
            r
        };
        let is_git = self.diff_git_raw.is_some();
        let (mut path, mut from): (Option<String>, Option<String>) = (None, None);
        // The diff --git pair this row's other evidence confirms, prefixes intact.
        let mut pair: Option<(String, String)> = None;
        if let (Some(f), Some(t)) = (self.hdr_from.as_deref(), self.hdr_to.as_deref()) {
            // RENAME/COPY: headers are stripped by p-1 (git's apply.c does the same).
            let (sf, stt) = (strip(f, hp), strip(t, hp));
            if is_git {
                pair = diff_git_candidates(&raw).into_iter().find(|(a, b)| {
                    strip_components(a, p).as_deref() == sf.as_deref()
                        && strip_components(b, p).as_deref() == stt.as_deref()
                        && sf.is_some()
                });
                if pair.is_none() && sf.is_some() && stt.is_some() {
                    st.incomplete.push(format!(
                        "`diff --git {}` does not name the same files as its rename/copy \
                         headers ({f} -> {t}) under -p{p}",
                        short(&raw)
                    ));
                }
            }
            if rule.tool == "patch" {
                st.incomplete.push(format!(
                    "{t}: patch(1)'s handling of git rename/copy headers is not modelled; use \
                     git apply to have this summarised"
                ));
            }
            path = stt;
            from = sf;
        } else {
            let side = if self.deleted { self.minus_name.as_deref() } else { self.plus_name.as_deref() };
            if let Some(n) = side {
                path = strip(n, p);
            }
            if is_git {
                pair = diff_git_candidates(&raw).into_iter().find(|(a, b)| {
                    let (sa, sb) = (strip_components(a, p), strip_components(b, p));
                    sa.is_some() && sa == sb && (path.is_none() || sb == path)
                });
                if path.is_none() {
                    path = pair.as_ref().and_then(|(_, b)| strip_components(b, p));
                }
            }
        }
        for n in &too_short {
            st.incomplete.push(format!(
                "`{}` has fewer than {} leading component(s) to strip (-p{p}); git apply refuses \
                 such a name, so which file it means is not established",
                short(n), if self.hdr_to.is_some() { hp } else { p }
            ));
        }
        // A patch whose names do not carry the prefixes the strip level removes (a
        // `git diff --no-prefix` patch under -p1), or that carry git's a/ b/ prefixes under
        // -p0, is summarised at the wrong paths. Both sides of `diff --git` show which it is.
        if let Some((a, b)) = pair.as_ref() {
            let first = |s: &str| s.split('/').next().unwrap_or("").to_string();
            let (ca, cb) = (first(a), first(b));
            if p >= 1 && a.contains('/') && b.contains('/') && ca == cb {
                st.incomplete.push(format!(
                    "`diff --git {}`: both names start `{ca}/`, as a `git diff --no-prefix` patch \
                     does -- but -p{p} ({}) strips that component, so the paths shown may not be \
                     the files written",
                    short(&raw), rule.source
                ));
            } else if p == 0 && ca == "a" && cb == "b" {
                st.incomplete.push(format!(
                    "`diff --git {}`: the names carry git's a/ b/ prefixes, but -p0 keeps them, so \
                     the files written are under a/ and b/",
                    short(&raw)
                ));
            }
        }
        let path = match path {
            Some(pth) => with_directory(&rule.directory, pth),
            None => {
                if too_short.is_empty() {
                    st.incomplete.push(format!(
                        "could not determine which file `diff --git {}` changes",
                        short(&raw)
                    ));
                }
                // Never the raw (possibly escaped) spelling presented as a path.
                "<undetermined path>".to_string()
            }
        };
        let from = from.map(|f| with_directory(&rule.directory, f));
        if self.binary {
            st.incomplete.push(format!(
                "{path}: binary content is changed; it is neither counted nor shown here"
            ));
        }
        st.added += self.added;
        st.removed += self.removed;
        let mut row = json!({"path": path, "added": self.added, "removed": self.removed,
                             "created": self.created, "deleted": self.deleted});
        let (renamed_from, copied_from) = if self.is_copy { (None, from) } else { (from, None) };
        for (k, v) in [("old_mode", self.old_mode), ("new_mode", self.new_mode),
                       ("renamed_from", renamed_from), ("copied_from", copied_from)] {
            if let Some(v) = v {
                row[k] = json!(v);
            }
        }
        if self.binary {
            row["binary"] = json!(true);
        }
        st.files.push(row);
    }
}

/// Per-file summary of a patch (`git diff` / `git format-patch` output, or a plain unified
/// diff), read from its own structure.
///
/// - A `diff --git` line opens a file row ON ITS OWN. Its extended headers (`old/new mode`,
///   `new/deleted file mode`, `rename from/to`, `copy from/to`, `similarity index`, `index`)
///   are read into that row, so a mode-only change, a pure rename and a binary patch -- none
///   of which has a `---`/`+++` pair -- are each a file, not nothing. (a32919c keyed rows on
///   that pair and reported all three as ZERO files: GPT hold, 2026-09-29.)
/// - `--- `/`+++ ` are read only OUTSIDE a hunk, and a hunk is consumed by the exact line
///   counts its `@@ -a,b +c,d @@` header declares -- so a removed line that starts `--- ` is
///   never mistaken for a new file. `--- /dev/null` marks a creation, `+++ /dev/null` a
///   deletion (whose target is the `---` path).
/// - Anything this does not fully read is NAMED in `incomplete`: binary content, an unknown
///   git header line, a cut-off or unparseable hunk, a context- or normal-format diff, a hunk
///   with no file header, a path it cannot determine, or a non-empty patch with no file at
///   all. Text between file sections that is not a header (a commit message, a signature) is
///   skipped, exactly as `git apply` skips it.
///
/// One pass over `text.lines()` with one line of lookahead: no per-line allocation, so the
/// work is linear in a buffer the caller has already bounded.
pub fn patch_stat(text: &str) -> PatchStat {
    patch_stat_with(text, &NameRule::git_default())
}

/// `patch_stat` under the name rule the ACT specifies (`patch_name_rule`). The rule's own
/// gaps -- an undetermined strip level, an unmodelled option -- are reported first.
pub fn patch_stat_with(text: &str, rule: &NameRule) -> PatchStat {
    let mut st = PatchStat::default();
    if rule.p.is_none() {
        st.incomplete.push(format!(
            "the strip level could not be determined: {}; the paths shown assume -p1 and may \
             not be the files written",
            rule.source
        ));
    }
    for o in &rule.unmodelled {
        st.incomplete.push(format!(
            "the act passes {o}, which this summary does not model; it may change which files \
             or lines are affected"
        ));
    }
    let mut it = text.lines().peekable();
    let mut cur: Option<PatchRow> = None;
    // true between a `diff --git` line and its first hunk / binary body: the header zone.
    let mut in_git_headers = false;
    let (mut saw_context, mut saw_normal, mut saw_orphan_hunk) = (false, false, false);
    while let Some(l) = it.next() {
        if let Some(rest) = l.strip_prefix("diff --git ") {
            if let Some(r) = cur.take() {
                r.finish(&mut st, rule);
            }
            cur = Some(PatchRow {
                diff_git_raw: Some(rest.to_string()),
                ..Default::default()
            });
            in_git_headers = true;
            continue;
        }
        if let Some(minus) = l.strip_prefix("--- ") {
            if let Some(plus) = it.peek().and_then(|n| n.strip_prefix("+++ ")) {
                let plus = plus.to_string();
                it.next();
                let mut r = if in_git_headers {
                    cur.take().unwrap_or_default()
                } else {
                    if let Some(r) = cur.take() {
                        r.finish(&mut st, rule);
                    }
                    PatchRow::default()
                };
                in_git_headers = false;
                if minus.trim().starts_with("/dev/null") {
                    r.created = true;
                }
                if plus.trim().starts_with("/dev/null") {
                    r.deleted = true;
                }
                for (spelled, slot) in [(minus, &mut r.minus_name), (plus.as_str(), &mut r.plus_name)] {
                    if spelled.trim().starts_with("/dev/null") {
                        continue;
                    }
                    match diff_side_name(spelled) {
                        Some(n) => *slot = Some(n),
                        None => r.undecodable.push(spelled.to_string()),
                    }
                }
                while it.peek().map(|n| n.starts_with("@@")).unwrap_or(false) {
                    let h = it.next().unwrap_or_default();
                    if !consume_hunk(h, &mut it, &mut r.added, &mut r.removed) {
                        let p = r.plus_name.clone().or_else(|| r.minus_name.clone()).unwrap_or_default();
                        st.incomplete.push(format!(
                            "{p}: a hunk is cut off or malformed (`{}`); its counts are partial",
                            h.chars().take(60).collect::<String>()
                        ));
                    }
                }
                cur = Some(r);
                continue;
            }
        }
        if in_git_headers {
            let r = cur.get_or_insert_with(PatchRow::default);
            if let Some(m) = l.strip_prefix("old mode ") {
                r.old_mode = Some(m.trim().to_string());
            } else if let Some(m) = l.strip_prefix("new mode ") {
                r.new_mode = Some(m.trim().to_string());
            } else if let Some(m) = l.strip_prefix("new file mode ") {
                r.created = true;
                r.new_mode = Some(m.trim().to_string());
            } else if let Some(m) = l.strip_prefix("deleted file mode ") {
                r.deleted = true;
                r.old_mode = Some(m.trim().to_string());
            } else if let Some((v, is_from, is_copy)) = l
                .strip_prefix("rename from ").map(|v| (v, true, false))
                .or_else(|| l.strip_prefix("rename to ").map(|v| (v, false, false)))
                .or_else(|| l.strip_prefix("copy from ").map(|v| (v, true, true)))
                .or_else(|| l.strip_prefix("copy to ").map(|v| (v, false, true)))
            {
                r.is_copy |= is_copy;
                match header_name(v) {
                    Some(n) if is_from => r.hdr_from = Some(n),
                    Some(n) => r.hdr_to = Some(n),
                    None => r.undecodable.push(v.to_string()),
                }
            } else if l.starts_with("similarity index ")
                || l.starts_with("dissimilarity index ")
                || l.starts_with("index ")
            {
            } else if l.starts_with("Binary files ") && l.ends_with(" differ") {
                r.binary = true;
                in_git_headers = false;
            } else if l == "GIT binary patch" {
                r.binary = true;
                in_git_headers = false;
                // the base85 body runs to the next file section; none of it is a header
                while it.peek().map(|n| !n.starts_with("diff --git ")).unwrap_or(false) {
                    it.next();
                }
            } else {
                let p = r.diff_git_raw.clone().unwrap_or_default();
                st.incomplete.push(format!(
                    "`diff --git {p}`: unrecognised line in a git file header: `{}`",
                    l.chars().take(60).collect::<String>()
                ));
                in_git_headers = false;
            }
            continue;
        }
        if (l.starts_with("*** ") && it.peek().map(|n| n.starts_with("--- ")).unwrap_or(false))
            || l == "***************"
        {
            saw_context = true;
        } else if is_normal_diff_command(l) {
            saw_normal = true;
        } else if l.starts_with("@@ ") {
            saw_orphan_hunk = true;
        }
    }
    if let Some(r) = cur.take() {
        r.finish(&mut st, rule);
    }
    if saw_context {
        st.incomplete.push("a context-format diff (`*** `/`--- `) is present; it is not \
                            summarised here".into());
    }
    if saw_normal {
        st.incomplete.push("a normal-format diff (`12c12`-style commands) is present; it is \
                            not summarised here".into());
    }
    if saw_orphan_hunk {
        st.incomplete.push("a hunk with no file header is present; its target and counts are \
                            not summarised here".into());
    }
    if st.files.is_empty() && !text.trim().is_empty() {
        st.incomplete.push("no file section was recognised in a non-empty patch".into());
    }
    st
}

/// What a PATCH-APPLICATION act would do: the patch the daemon read, the hash of exactly those
/// bytes (the value the approval binds for them), and per file what it touches.
///
/// WHY (#648, 2026-09-28). codex dissented on an escalation whose record showed a `git apply`
/// command truncated at `…/witness-` with four sibling patches sharing that prefix: *"I cannot
/// bind an endorsement to one of them. Please provide the exact patch filename, digest, and
/// intended behavior."* A patch is the most self-describing act there is once it is READ; the
/// decider was shown its path and nothing else. Every field is measured from the file: targets
/// and counts come from the patch's own headers and hunk lines, never from the member's words.
///
/// BOUNDED, AND HONEST ABOUT IT (GPT hold on a32919c, 2026-09-29). The file is read ONCE,
/// through `read_regular_file_bounded` with the same cap the approval binding uses: a patch
/// over the cap is never allocated, parsed or rendered -- the result says it was not read,
/// carries `file_count: null` rather than a zero, and binds nothing. Within the cap,
/// `summary_complete` is false whenever `incomplete` names something the summary does not
/// represent, and the sha is computed from the same buffer the summary was parsed from.
pub fn patch_effect(patch: &Path, act: &str) -> Value {
    // The act locates the file AND says how its names become paths (`-pN`, `--directory`).
    let rule = patch_name_rule(act);
    use crate::server::gate_escalation::{read_regular_file_bounded, sha256_hex, BoundedRead};
    let cap = crate::server::gate_escalation::MAX_MEASURED_PAYLOAD_BYTES;
    let bytes = match read_regular_file_bounded(patch, cap) {
        Ok(b) => b,
        Err(BoundedRead::TooLarge(n)) => {
            let why = format!(
                "the patch is {n} bytes, above the {cap}-byte measurement cap; it was NOT read, \
                 so nothing about what it changes is asserted"
            );
            return json!({
                "kind": "patch",
                "patch_path": patch.display().to_string(),
                "patch_readable": true,
                "patch_read": false,
                "patch_bytes": n,
                "payload_sha256": Value::Null,
                "payload_unbound_reason": "patch larger than the measurement cap; the approval does not bind its bytes",
                "files": Value::Null,
                "file_count": Value::Null,
                "added_lines": Value::Null,
                "removed_lines": Value::Null,
                "diff": [],
                "diff_truncated": false,
                "summary_complete": false,
                "incomplete": [why],
            });
        }
        Err(_) => {
            return json!({
                "kind": "patch",
                "patch_path": patch.display().to_string(),
                "patch_readable": false,
                "patch_read": false,
                "summary_complete": false,
                "note": "the act names a patch file the daemon cannot read; nothing about what it \
                         would change is asserted here",
            });
        }
    };
    let text = String::from_utf8_lossy(&bytes);
    let mut stat = patch_stat_with(&text, &rule);
    if matches!(text, std::borrow::Cow::Owned(_)) {
        stat.incomplete.push("the patch is not valid UTF-8; the text shown replaces the invalid \
                              bytes, and the sha is of the original bytes".into());
    }
    let mut rendered: Vec<String> = Vec::new();
    let mut truncated = false;
    for line in text.lines().take(MAX_RENDERED_DIFF_LINES + 1) {
        push_line(&mut rendered, &mut truncated, line.to_string());
    }
    json!({
        "kind": "patch",
        "patch_path": patch.display().to_string(),
        "patch_readable": true,
        "patch_read": true,
        "patch_bytes": bytes.len(),
        // The sha of THESE bytes -- the ones summarised and rendered here -- which is what
        // `measured_payload_for_act` binds for them (same file, same bounded reader). Computed
        // from this buffer rather than by a second read, so the card can never show the digest
        // of different bytes than the summary it sits beside.
        "payload_sha256": sha256_hex(&bytes),
        "payload_unbound_reason": Value::Null,
        "strip_level": rule.p,
        "strip_level_source": rule.source,
        "directory": rule.directory,
        "files": stat.files,
        "file_count": stat.files.len(),
        "added_lines": stat.added,
        "removed_lines": stat.removed,
        "diff": rendered,
        "diff_truncated": truncated,
        "summary_complete": stat.incomplete.is_empty(),
        "incomplete": stat.incomplete,
    })
}

/// How much of a marker's escalation history the bundle carries.
///
/// Not a performance knob. A decider reading "this member has asked for this marker 40 times"
/// needs the SHAPE of that history, not all of it — and a bundle large enough to skim past is
/// a bundle that gets skimmed past, which is the failure this whole module exists to fix.
pub const PRIOR_DECISIONS_CAP: u64 = 20;

/// How many of the member's refusals to carry. Same reasoning, and §3.3 asks for the rules
/// that fired rather than a transcript.
pub const MEMBER_DENIES_CAP: u64 = 20;

/// The evidence bundle for one pending escalation — `PRD_ADJUDICATOR_LADDER` §3.3.
///
/// > **If a rung sees less than the human would, it is not a rung. It is a filter.**
///
/// This is the on-demand half. The dashboard card carries the cheap part (the write effect,
/// memoised); everything here needs chain reads, and putting a chain read on a render tick is
/// #1040 — a projection rebuilt per poll, measured at most of a core with the page open. So
/// the rule for this module is: the card gets what is free, the TOOL gets what costs, and
/// both read the same builder.
///
/// Returns `None` for an unknown id rather than an empty bundle, because "no such escalation"
/// and "an escalation about which nothing is known" are different answers and a rung that
/// cannot tell them apart will reason from the wrong one.
/// Where the bundle's `act_text` came from, in words a decider can check. The `UNAVAILABLE`
/// prefix is a contract: `adjudicator::BaselineRung` keys on it to decline for insufficient
/// evidence rather than abstain.
fn act_text_source(esc: &crate::server::gate_escalation::Escalation) -> &'static str {
    use crate::server::gate_escalation::OpenedVia;
    match (esc.act_text.is_some(), esc.opened_via) {
        (false, _) => "UNAVAILABLE: this escalation predates act-text retention (#1066); only \
                       act_digest survives, and a hash is not readable evidence",
        (true, OpenedVia::Open) => "retained at open — the member door's `act` argument, the \
                                    exact text act_digest binds (its `reason` is a rationale \
                                    and is never read as the act)",
        (true, OpenedVia::Claim) => "retained at open — the claim door's act (its `act` \
                                     argument, or `reason` taken as the act when none was \
                                     sent), the exact text act_digest binds",
        (true, OpenedVia::Unknown) => "retained at open — the exact text act_digest binds; the \
                                       door that opened it was not recorded",
    }
}

/// Tools whose act the gate hook composes from the destination alone (#1091, #600): their
/// payload (`new_string`, `content`, ...) never reaches the act text or its digest.
const PATH_KEYED_TOOLS: [&str; 4] = ["Edit", "Write", "MultiEdit", "NotebookEdit"];

fn act_text_covers(esc: &crate::server::gate_escalation::Escalation) -> &'static str {
    if esc.act_text.is_none() {
        "nothing — no act text is retained"
    } else if PATH_KEYED_TOOLS.contains(&esc.tool_name.as_str()) {
        "destination only — for Edit/Write the act and its digest name the target file, not \
         the content to be written; the approval does not bind the content (#1091)"
    } else {
        "the command as stated"
    }
}

pub fn bundle(s: &crate::server::state::ServerState, escalation_id: &str) -> Option<Value> {
    let esc = s.gate_escalations.get(escalation_id.trim())?;
    let now = crate::server::gate_escalation::now_secs();

    // PRIOR DECISIONS ON THE SAME MARKER — §3.3's "the thing a human cannot hold in their
    // head". Summarised AND listed: the counts are what a decider uses, the rows are what
    // makes the counts checkable rather than asserted.
    let prior_rows = s
        .chain_store
        .escalation_rows_for_marker(&esc.plugin_id, &esc.marker, PRIOR_DECISIONS_CAP)
        .unwrap_or_default();
    let mut opened = 0usize;
    let mut approved = 0usize;
    let mut denied = 0usize;
    let mut prior: Vec<Value> = Vec::new();
    for e in &prior_rows {
        let d = &e.event_data;
        let id = d.get("escalation_id").and_then(Value::as_str).unwrap_or("");
        if id == esc.id {
            continue; // this escalation's own rows are the subject, not its precedent
        }
        match e.event_type.as_str() {
            "gate_escalation_opened" => opened += 1,
            "gate_escalation_decided" => {
                match d.get("status").and_then(Value::as_str) {
                    Some("approved") => approved += 1,
                    Some("denied") => denied += 1,
                    _ => {}
                }
            }
            _ => {}
        }
        prior.push(json!({
            "event": e.event_type,
            "escalation_id": id,
            "at": e.timestamp,
            "status": d.get("status"),
            "decided_by": d.get("decided_by"),
            "reason": d.get("reason"),
        }));
    }

    // THE MEMBER'S REFUSALS, by rule. A decider weighing "has this member been refused for
    // this before" is asking about the RULE, not the prose, so the rules are tallied.
    let deny_rows = s
        .chain_store
        .denies_for_member(&esc.plugin_id, MEMBER_DENIES_CAP)
        .unwrap_or_default();
    let mut rule_counts: HashMap<String, usize> = HashMap::new();
    for e in &deny_rows {
        let rule = e
            .event_data
            .get("rule")
            .and_then(Value::as_str)
            .unwrap_or("<unnamed>")
            .to_string();
        *rule_counts.entry(rule).or_insert(0) += 1;
    }
    let mut rules: Vec<Value> = rule_counts
        .into_iter()
        .map(|(rule, n)| json!({"rule": rule, "count": n}))
        .collect();
    rules.sort_by(|a, b| {
        b["count"].as_u64().cmp(&a["count"].as_u64()).then_with(|| {
            a["rule"].as_str().unwrap_or("").cmp(b["rule"].as_str().unwrap_or(""))
        })
    });

    Some(json!({
        "escalation": {
            "id": esc.id,
            // CALLER-ASSERTED, and labelled so (HST-005). The same string the dashboard
            // renders as `claimed_by` rather than `member`, for the same reason: a decider
            // is deciding partly ON this name and it is not authenticated.
            "claimed_by": esc.plugin_id,
            "role": esc.role,
            "tool_name": esc.tool_name,
            "marker": esc.marker,
            // The member's own account of itself — and for a gate-auto-opened escalation the
            // member wrote neither, which is a fact about the ASK worth seeing as such.
            "stated_reason": esc.stated_reason,
            "stated_detail": esc.stated_detail,
            "opened_at": esc.opened_at,
            "expires_at": esc.expires_at,
            "secs_remaining": esc.expires_at.saturating_sub(now),
            "status": format!("{:?}", esc.status_at(now)),
            // The criterion in force WHEN IT WAS OPENED, never today's: a decider must be
            // judged against the bar the ask was filed under.
            "bar": esc.bar,
            "bar_met": esc.bar_met(),
            "factors": esc.factors,
            // #128: whether the asker was proven against a live session or merely asserted.
            // `arbiter::eligibility` clause 0 reads this, and §3.3 says a rung must too.
            "asker_basis": format!("{:?}", esc.asker_basis),
            "act_digest": esc.act_digest,
            // #1066: which door opened it, which is what says what `stated_reason` means.
            "opened_via": esc.opened_via.as_str(),
            // #1056: the bytes the approval BINDS, when the daemon could measure them.
            "payload_sha256": esc.payload_sha256,
        },
        // THE ACT ITSELF — §3.3's first element. Read ONLY from `act_text`, the exact string
        // `act_digest` was computed from and retained at the mint (#1066), so what the decider
        // reads is provably what the permit binds.
        //
        // NEVER FROM `stated_reason`. That was the first cut: `open()` discarded the act, and
        // the text was recovered from the reason on the grounds that the gate door composes
        // `reason` AS the act. Presence of a reason proves no such door. On the member door the
        // reason is a rationale, and a rationale containing some other valid `cp` was shown as
        // the act, with a measured write effect for a write the approval does not bind (GPT,
        // review of #1064). A row with no retained text predates the field; it is reported
        // unavailable, never reconstructed.
        "act_text": esc.act_text,
        "act_text_source": act_text_source(esc),
        // WHAT THE TEXT COVERS. Retained is not the same as complete: for a path-keyed tool
        // (Edit/Write/...) the gate hook composes the act from the TARGET alone, so the text —
        // and the digest the approval binds — name WHERE the write goes and nothing about
        // what it writes (#1091; same class as #600). A decider must not read a path as the
        // content it approved, so this says which one it is holding.
        "act_text_covers": act_text_covers(esc),
        // What the act would DO — from the same retained text, never from the reason. Same
        // builder the operator's card uses, so the human and the rung look at one object.
        "write_effect": esc.act_text.as_deref().and_then(write_effect_cached),
        "prior_on_this_marker": {
            "opened": opened,
            "approved": approved,
            "denied": denied,
            "cap": PRIOR_DECISIONS_CAP,
            // Says whether the reader is seeing all of it. A truncated history that does not
            // announce itself is the windowed-census defect wearing a different hat.
            "truncated": prior_rows.len() as u64 >= PRIOR_DECISIONS_CAP,
            "rows": prior,
        },
        "member_refusals": {
            "counted": deny_rows.len(),
            "cap": MEMBER_DENIES_CAP,
            "truncated": deny_rows.len() as u64 >= MEMBER_DENIES_CAP,
            "by_rule": rules,
        },
        "law": {
            // The society policy in force, which is cheap and caller-independent.
            "society_policy_hash": s.policy_engine.content_hash(),
            // DELIBERATELY NOT A law_hash COMPUTED HERE. `tool_operating_law` composes the law
            // PER CALLER and hashes that composition, and its own doc records that the reply
            // is an allowlist re-projection of the hashed body — so a hash minted here would
            // be a second, subtly different spelling of the same idea, and §3.3's whole point
            // is that the rung records the hash IT consulted. The rung calls the law tool and
            // pins what it was actually shown.
            "consult": "hestia_operating_law — and record the law_hash IT returns to you",
        },
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("hestia-evidence-{}-{}", tag, std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn a_diff_reports_what_changed_and_how_much() {
        let d = line_diff("alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\ndelta\n");
        assert_eq!(d.removed, 1, "beta left");
        assert_eq!(d.added, 2, "BETA and delta arrived");
        assert!(d.rendered.iter().any(|l| l == "- beta"));
        assert!(d.rendered.iter().any(|l| l == "+ BETA"));
        assert!(d.rendered.iter().any(|l| l == "+ delta"));
        assert!(!d.truncated);

        // The control that matters for a REVIEW surface: an unchanged file must render as
        // unchanged, or every approval looks like a rewrite and the signal is gone.
        let same = line_diff("alpha\nbeta\n", "alpha\nbeta\n");
        assert_eq!((same.added, same.removed), (0, 0));
        assert!(same.rendered.is_empty());
    }

    /// A TRUNCATED DIFF MUST SAY SO. A reviewer who reaches the end of a rendered diff
    /// reasonably concludes they have seen the change; if the tail was dropped silently, the
    /// surface has manufactured false confidence — which is worse than showing nothing, and
    /// is the same failure as a windowed measurement published without its window.
    #[test]
    fn a_truncated_diff_is_flagged_and_an_oversized_one_refuses_to_pretend() {
        let big: String = (0..MAX_RENDERED_DIFF_LINES + 50)
            .map(|i| format!("line {i}\n"))
            .collect();
        let d = line_diff("", &big);
        assert!(d.truncated, "more changed lines than the cap must set the flag");
        assert_eq!(d.rendered.len(), MAX_RENDERED_DIFF_LINES, "and render exactly the cap");
        assert_eq!(d.added, MAX_RENDERED_DIFF_LINES + 50, "while COUNTING all of them");

        let huge: String = (0..MAX_DIFF_LINES + 1).map(|i| format!("l{i}\n")).collect();
        let too_big = line_diff(&huge, &huge);
        assert!(too_big.truncated);
        assert!(
            too_big.rendered[0].contains("too large to diff"),
            "beyond the cap it must say it did not diff, not show a wrong one: {:?}",
            too_big.rendered
        );
    }

    #[test]
    fn an_act_that_is_not_a_copy_yields_no_effect() {
        assert!(write_effect("Edit -> plugins/kimi/hooks/pre_tool_use.py").is_none());
        assert!(copy_operands("Bash: cp relative/a.txt plugins/x.py").is_none(),
                "a relative source is not resolvable by the daemon and must not be guessed");
        assert!(copy_operands("Bash: cp /tmp/../etc/passwd plugins/x.py").is_none(),
                "a path-escaping source is refused rather than normalised");
    }

    /// The specimen, as a test: an unreadable-source act must SAY the source is missing
    /// rather than rendering an empty bundle a reviewer reads as "nothing unusual".
    #[test]
    fn a_missing_source_is_reported_not_omitted() {
        let act = "Bash: cp /nonexistent/hestia-evidence-missing.txt plugins/codex/hooks/x.py";
        let v = write_effect(act).expect("an absolute source is still an effect to report");
        assert_eq!(v["source_readable"], json!(false));
        assert!(v["note"].as_str().unwrap().contains("cannot read"));
    }

    /// THE SPECIMEN, END TO END: the 2026-09-17 approval, with the diff the card should have
    /// carried. Everything here is the real resolution path — only the deploy root is a
    /// fixture, because the alternative is mutating `HESTIA_HOME` inside a parallel test
    /// binary, which is a race dressed as a fixture.
    #[test]
    fn the_enforcing_copy_is_found_and_diffed_against_the_incoming_bytes() {
        let home = tmpdir("home");
        let enforcing = home.join("deploy/hestia/plugins/codex/hooks");
        std::fs::create_dir_all(&enforcing).unwrap();
        std::fs::write(enforcing.join("pre_tool_use.py"), "line one\nline two\n").unwrap();

        let found = enforcing_copy_under(&home, "plugins/codex/hooks/pre_tool_use.py")
            .expect("a repo-relative destination resolves under the deploy root");
        assert!(found.ends_with("plugins/codex/hooks/pre_tool_use.py"));

        let incoming = "line one\nline two changed\nline three\n";
        let d = line_diff(&std::fs::read_to_string(&found).unwrap(), incoming);
        assert_eq!((d.added, d.removed), (2, 1), "the reviewable fact, in two numbers");
        assert!(d.rendered.iter().any(|l| l == "+ line three"));

        // The refusals, each of which would otherwise label a real file as "now enforcing".
        assert!(enforcing_copy_under(&home, "/etc/passwd").is_none(), "absolute");
        assert!(enforcing_copy_under(&home, "../../etc/passwd").is_none(), "escaping");
        assert!(enforcing_copy_under(&home, "plugins/nope.py").is_none(), "absent");
        std::fs::remove_dir_all(&home).ok();
    }

    /// THE CACHE MUST NOT OUTLIVE THE BYTES IT DESCRIBES.
    ///
    /// A render cache on a decision surface has a failure mode a plain cache does not: it can
    /// show an operator a diff for bytes that are no longer there, which is the #1056
    /// substitution arriving through the display instead of through the claim. So the key is
    /// the identity of the FILES, not the act string — and this is the arm that holds it.
    #[test]
    fn the_effect_cache_recomputes_when_the_source_changes() {
        let d = tmpdir("memo");
        let src = d.join("next.txt");
        std::fs::write(&src, "one\n").unwrap();
        let act = format!("Bash: cp {} plugins/codex/hooks/pre_tool_use.py", src.display());

        let first = write_effect_cached(&act).unwrap();
        let hit = write_effect_cached(&act).unwrap();
        assert_eq!(first, hit, "an unchanged source must not recompute to something else");

        // Rewrite with DIFFERENT LENGTH so the identity moves even on a coarse-grained
        // filesystem clock: this test must fail for the right reason, not pass because two
        // writes landed in the same second.
        std::fs::write(&src, "one\ntwo\nthree\n").unwrap();
        let after = write_effect_cached(&act).unwrap();
        assert_ne!(
            after["payload_sha256"], first["payload_sha256"],
            "a rewritten source must recompute — a stale diff on an approval card is the \
             substitution this whole line of work exists to stop, arriving through the display"
        );
        assert_eq!(after["source_lines"], json!(3));
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn a_readable_source_carries_its_size_and_the_bound_hash() {
        let d = tmpdir("src");
        let src = d.join("next.txt");
        std::fs::write(&src, "one\ntwo\n").unwrap();
        let act = format!("Bash: cp {} plugins/codex/hooks/pre_tool_use.py", src.display());
        let v = write_effect(&act).unwrap();
        assert_eq!(v["source_readable"], json!(true));
        assert_eq!(v["source_lines"], json!(2));
        assert_eq!(v["source_bytes"], json!(8));
        // The hash a permit would BIND and the bytes a reviewer is READING must be the same
        // object, or the surface is showing one thing and authorising another.
        assert_eq!(
            v["payload_sha256"].as_str().map(str::to_string),
            crate::server::gate_escalation::EscalationStore::measured_payload_for_act(&act),
        );
        std::fs::remove_dir_all(&d).ok();
    }

    // ---- patch-application acts (#648: the decider must be able to identify the bytes) ----

    use crate::server::gate_escalation::EscalationStore as ES;

    const TWO_FILE_PATCH: &str = "diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1,3 +1,3 @@
 title
---- a removed line that merely LOOKS like a header
+++++ an added line that merely LOOKS like a header
 end
diff --git a/src/new.rs b/src/new.rs
new file mode 100644
--- /dev/null
+++ b/src/new.rs
@@ -0,0 +1,2 @@
+fn a() {}
+fn b() {}
\\ No newline at end of file
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
";

    #[test]
    fn a_patch_act_is_recognised_only_in_its_unambiguous_forms() {
        let p = |a: &str| ES::patch_file_of_act(a).map(|x| x.display().to_string());
        assert_eq!(p("Bash: git -C /wt apply /p/x.patch"), Some("/p/x.patch".into()));
        assert_eq!(p("git apply --3way /p/x.patch"), Some("/p/x.patch".into()));
        assert_eq!(p("git -c core.x=y am /p/m.mbox"), Some("/p/m.mbox".into()));
        assert_eq!(p("patch -p1 -i /p/x.patch"), Some("/p/x.patch".into()));
        assert_eq!(p("patch -p1 --input=/p/x.patch"), Some("/p/x.patch".into()));
        assert_eq!(p("patch -p1 < /p/x.patch"), Some("/p/x.patch".into()));
        // read-only, ambiguous, relative, escaping, compound, or not a patch at all: nothing
        assert_eq!(p("git apply --check /p/x.patch"), None);
        assert_eq!(p("git apply --stat /p/x.patch"), None);
        assert_eq!(p("git apply /p/a.patch /p/b.patch"), None);
        assert_eq!(p("git apply x.patch"), None);
        assert_eq!(p("git apply /p/../etc/x.patch"), None);
        assert_eq!(p("cd /wt && git apply /p/x.patch"), None);
        assert_eq!(p("git apply /p/x.patch; rm /p/x.patch"), None);
        assert_eq!(p("cp /a /b"), None);
        assert_eq!(p("git status"), None);
    }

    #[test]
    fn the_approval_binds_the_patch_bytes_not_the_directory() {
        let d = tmpdir("patchbind");
        let patch = d.join("x.patch");
        std::fs::write(&patch, TWO_FILE_PATCH).unwrap();
        let act = format!("Bash: git -C {} apply {}", d.display(), patch.display());
        let h1 = ES::measured_payload_for_act(&act).expect("a readable patch is measured");
        // Before this change the first absolute token (the -C directory) was read as the copy
        // source, found not to be a file, and the approval bound NOTHING.
        std::fs::write(&patch, format!("{TWO_FILE_PATCH}\n")).unwrap();
        let h2 = ES::measured_payload_for_act(&act).unwrap();
        assert_ne!(h1, h2, "changed patch bytes must change the bound hash");
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn patch_stat_reads_structure_not_lookalike_lines() {
        let st = patch_stat(TWO_FILE_PATCH);
        let (files, add, del) = (&st.files, st.added, st.removed);
        assert_eq!(files.len(), 3, "{files:?}");
        assert_eq!(files[0], json!({"path": "docs/notes.md", "added": 1, "removed": 1,
                                    "created": false, "deleted": false}),
                   "a '--- '/'+++ ' line INSIDE a hunk is content, not a new file");
        assert_eq!(files[1], json!({"path": "src/new.rs", "added": 2, "removed": 0,
                                    "created": true, "deleted": false, "new_mode": "100644"}));
        assert_eq!(files[2], json!({"path": "old.txt", "added": 0, "removed": 1,
                                    "created": false, "deleted": true, "old_mode": "100644"}));
        assert_eq!((add, del), (3, 2));
        assert!(st.incomplete.is_empty(), "{:?}", st.incomplete);
    }

    #[test]
    fn a_patch_act_shows_what_it_would_do_and_the_hash_it_binds() {
        let d = tmpdir("patcheffect");
        let patch = d.join("y.patch");
        std::fs::write(&patch, TWO_FILE_PATCH).unwrap();
        let act = format!("git -C /repo apply {}", patch.display());
        let v = write_effect(&act).expect("a patch act has an effect");
        assert_eq!(v["kind"], json!("patch"));
        assert_eq!(v["patch_readable"], json!(true));
        assert_eq!(v["file_count"], json!(3));
        assert_eq!(v["added_lines"], json!(3));
        assert_eq!(v["removed_lines"], json!(2));
        assert_eq!(v["payload_sha256"].as_str().map(str::to_string),
                   ES::measured_payload_for_act(&act),
                   "the bytes a reviewer reads and the bytes the permit binds are one object");
        assert!(v["diff"].as_array().map(|a| !a.is_empty()).unwrap_or(false));
        // the cached form returns the same object, and recomputes when the patch changes
        assert_eq!(write_effect_cached(&act), Some(v.clone()));
        std::thread::sleep(std::time::Duration::from_millis(1100));
        std::fs::write(&patch, "--- a/z\n+++ b/z\n@@ -1 +1 @@\n-a\n+b\n").unwrap();
        let v2 = write_effect_cached(&act).unwrap();
        assert_eq!(v2["file_count"], json!(1), "a rewritten patch is re-read, not served stale");
        // an unreadable patch is REPORTED, not treated as a copy from the -C directory
        let gone = write_effect(&format!("git -C /repo apply {}/missing.patch", d.display())).unwrap();
        assert_eq!(gone["kind"], json!("patch"));
        assert_eq!(gone["patch_readable"], json!(false));
        std::fs::remove_dir_all(&d).ok();
    }

    // ---- GPT hold on a32919c: incomplete patch summaries and unbounded reads ----
    //
    // Every fixture below is byte-for-byte what `git diff` (git 2.x) wrote in a throwaway repo
    // on 2026-09-29, not a hand-written approximation: `chmod +x gate.py` for the mode change,
    // `git mv` + `git diff -M --cached` for the rename, `git diff --binary` / plain `git diff`
    // for the two binary shapes. Ground truth came from `git diff --summary --numstat` on the
    // same trees: "mode change 100644 => 100755 gate.py", "rename old_name.txt => new_name.txt
    // (100%)", "-\t-\tblob.bin". None of them has a `---`/`+++` pair, and the parser on
    // a32919c keyed a file row on exactly that pair, so each read as ZERO files changed.

    const GIT_MODE_ONLY: &str = "diff --git a/gate.py b/gate.py
old mode 100644
new mode 100755
";

    const GIT_RENAME_ONLY: &str = "diff --git a/old_name.txt b/new_name.txt
similarity index 100%
rename from old_name.txt
rename to new_name.txt
";

    const GIT_BINARY: &str = "diff --git a/blob.bin b/blob.bin
index 677273046bce3115f56c248238f3b83f77cfc239..54424e41e1456e098229110a9867f38b15657dc3 100644
GIT binary patch
literal 7
OcmZSJ<VecQGXekvHUWJA

literal 6
NcmZQzWJ=1+0{{Yf0X+Z!

";

    const GIT_BINARY_NO_DATA: &str = "diff --git a/blob.bin b/blob.bin
index 6772730..54424e4 100644
Binary files a/blob.bin and b/blob.bin differ
";

    /// A mode-only change BESIDE a text change: the case where an unsupported effect could
    /// vanish silently next to a supported one and the summary would still look plausible.
    const GIT_MIXED_MODE_AND_TEXT: &str = "diff --git a/gate.py b/gate.py
old mode 100644
new mode 100755
diff --git a/notes.md b/notes.md
index de98044..7be73ce 100644
--- a/notes.md
+++ b/notes.md
@@ -1,3 +1,3 @@
 a
-b
+B
 c
";

    fn effect_of_patch(tag: &str, body: &[u8]) -> Value {
        let d = tmpdir(tag);
        let patch = d.join("p.patch");
        std::fs::write(&patch, body).unwrap();
        let v = write_effect(&format!("git -C /repo apply {}", patch.display())).unwrap();
        std::fs::remove_dir_all(&d).ok();
        v
    }

    #[test]
    fn a_mode_only_git_patch_is_one_file_with_its_mode_change() {
        let v = effect_of_patch("modeonly", GIT_MODE_ONLY.as_bytes());
        assert_eq!(v["file_count"], json!(1), "a32919c said 0 files: {v}");
        assert_eq!(v["files"][0]["path"], json!("gate.py"));
        assert_eq!(v["files"][0]["old_mode"], json!("100644"));
        assert_eq!(v["files"][0]["new_mode"], json!("100755"));
        assert_eq!(v["summary_complete"], json!(true), "a mode change is represented: {v}");
    }

    #[test]
    fn a_pure_rename_git_patch_is_one_file_naming_both_paths() {
        let v = effect_of_patch("renameonly", GIT_RENAME_ONLY.as_bytes());
        assert_eq!(v["file_count"], json!(1), "{v}");
        assert_eq!(v["files"][0]["path"], json!("new_name.txt"));
        assert_eq!(v["files"][0]["renamed_from"], json!("old_name.txt"));
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn a_binary_git_patch_is_listed_and_the_summary_says_it_is_incomplete() {
        for (tag, body) in [("binlit", GIT_BINARY), ("binnodata", GIT_BINARY_NO_DATA)] {
            let v = effect_of_patch(tag, body.as_bytes());
            assert_eq!(v["file_count"], json!(1), "{tag}: {v}");
            assert_eq!(v["files"][0]["path"], json!("blob.bin"), "{tag}");
            assert_eq!(v["files"][0]["binary"], json!(true), "{tag}");
            // +0/-0 would understate a binary change; the summary must SAY it cannot count it.
            assert_eq!(v["summary_complete"], json!(false), "{tag}: {v}");
            let why = v["incomplete"].to_string();
            assert!(why.contains("blob.bin") && why.contains("binary"), "{tag}: {why}");
        }
    }

    #[test]
    fn a_mode_change_beside_a_text_change_does_not_disappear() {
        let v = effect_of_patch("mixed", GIT_MIXED_MODE_AND_TEXT.as_bytes());
        assert_eq!(v["file_count"], json!(2), "a32919c showed only notes.md: {v}");
        let gate = v["files"].as_array().unwrap().iter()
            .find(|f| f["path"] == json!("gate.py")).cloned().expect("gate.py row");
        assert_eq!(gate["new_mode"], json!("100755"));
        let notes = v["files"].as_array().unwrap().iter()
            .find(|f| f["path"] == json!("notes.md")).cloned().expect("notes.md row");
        assert_eq!((notes["added"].clone(), notes["removed"].clone()), (json!(1), json!(1)));
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn an_unsupported_patch_form_is_marked_incomplete_not_summarised_as_zero() {
        // A context-format diff (GNU `patch` applies it; this parser does not read it).
        let context = "*** a/gate.py\n--- b/gate.py\n***************\n*** 1 ****\n! x\n--- 1 ----\n! y\n";
        let v = effect_of_patch("context", context.as_bytes());
        assert_eq!(v["summary_complete"], json!(false), "{v}");
        // A git segment carrying a header this parser does not know.
        let odd = "diff --git a/x b/x\nsomething new 1\n";
        let v = effect_of_patch("oddheader", odd.as_bytes());
        assert_eq!(v["summary_complete"], json!(false), "{v}");
        assert!(v["incomplete"].to_string().contains("something new"), "{v}");
        // A hunk that declares more lines than the patch contains (a cut-off patch).
        let cut = "--- a/x\n+++ b/x\n@@ -1,5 +1,5 @@\n a\n-b\n";
        let v = effect_of_patch("cuthunk", cut.as_bytes());
        assert_eq!(v["summary_complete"], json!(false), "{v}");
        // And the complete control still reads complete.
        let v = effect_of_patch("complete", TWO_FILE_PATCH.as_bytes());
        assert_eq!(v["summary_complete"], json!(true), "{v}");
        assert_eq!(v["incomplete"], json!([]));
    }

    #[test]
    fn a_patch_above_the_cap_is_not_read_and_says_so() {
        let cap = crate::server::gate_escalation::MAX_MEASURED_PAYLOAD_BYTES as usize;
        // A syntactically valid patch one byte over the cap: if it were read and parsed, it
        // would produce a file row and a rendered diff.
        let head = "--- a/big\n+++ b/big\n@@ -0,0 +1,1 @@\n+";
        let mut body = head.as_bytes().to_vec();
        body.resize(cap + 1, b'x');
        let v = effect_of_patch("bigpatch", &body);
        assert_eq!(v["kind"], json!("patch"));
        assert_eq!(v["patch_read"], json!(false), "{}", v["incomplete"]);
        assert_eq!(v["patch_bytes"], json!(cap + 1), "size comes from metadata, not a read");
        assert_eq!(v["payload_sha256"], Value::Null, "an unread patch binds nothing");
        assert_eq!(v["summary_complete"], json!(false));
        assert_eq!(v["file_count"], Value::Null, "not 0: nothing is asserted about its files");
        assert_eq!(v["diff"], json!([]), "a32919c read and rendered the whole file");
    }

    #[test]
    fn a_copy_source_above_the_cap_is_not_read_and_says_so() {
        let cap = crate::server::gate_escalation::MAX_MEASURED_PAYLOAD_BYTES as usize;
        let d = tmpdir("bigcopy");
        let src = d.join("big.txt");
        std::fs::write(&src, vec![b'y'; cap + 1]).unwrap();
        let v = write_effect(&format!("cp {} plugins/codex/hooks/pre_tool_use.py", src.display()))
            .unwrap();
        assert_eq!(v["source_read"], json!(false), "{v}");
        assert_eq!(v["source_bytes"], json!(cap + 1));
        assert_eq!(v["payload_sha256"], Value::Null);
        assert_eq!(v["diff"], Value::Null, "no diff is claimed for bytes nobody read");
        assert!(v.get("source_lines").map(Value::is_null).unwrap_or(true),
                "a line count is a claim about content that was not read");
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn the_sha_shown_is_the_sha_of_the_bytes_shown() {
        // The card's sha must be computed from the SAME buffer the summary was parsed from --
        // one read, one object -- and it must equal what the approval binds for those bytes.
        let v = effect_of_patch("shaone", GIT_MIXED_MODE_AND_TEXT.as_bytes());
        use sha2::{Digest, Sha256};
        let want = format!("{:x}", Sha256::digest(GIT_MIXED_MODE_AND_TEXT.as_bytes()));
        assert_eq!(v["payload_sha256"], json!(want));
    }
    #[test]
    fn the_bounded_reader_refuses_past_its_cap_without_reading_the_rest() {
        let d = tmpdir("bounded");
        let f = d.join("f");
        std::fs::write(&f, b"0123456789").unwrap();
        use crate::server::gate_escalation::{read_regular_file_bounded as rb, BoundedRead};
        assert_eq!(rb(&f, 10).unwrap(), b"0123456789".to_vec());
        assert!(matches!(rb(&f, 9), Err(BoundedRead::TooLarge(10))));
        assert!(matches!(rb(&d, 100), Err(BoundedRead::NotAFile)));
        assert!(matches!(rb(&d.join("nope"), 100), Err(BoundedRead::NotAFile)));
        std::fs::remove_dir_all(&d).ok();
    }


    // ---- GPT re-review hold on e0df1c9: extended-header paths are NOT prefixed, and git
    // C-quotes some paths. Every fixture below is byte-for-byte `git diff` output from a
    // throwaway repo (2026-09-30); ground truth from `git log --summary -M -C` on the same
    // commits: "rename a/old.txt => b/new.txt (100%)", "create mode 100644 b/copy.txt" (copy of
    // a/src.txt under -C --find-copies-harder), "rename \"sp ace\\tx\" => \"sp ace\\ty\"
    // (100%)", "mode change 100644 => 100755 \"\\303\\251t\\303\\251.txt\"" (= été.txt).

    /// `git mv a/old.txt b/new.txt` -- `a/` and `b/` are REAL directories here.
    const GIT_RENAME_AB_DIRS: &str = "diff --git a/a/old.txt b/b/new.txt
similarity index 100%
rename from a/old.txt
rename to b/new.txt
";

    const GIT_COPY_AB_DIRS: &str = "diff --git a/a/src.txt b/b/copy.txt
similarity index 100%
copy from a/src.txt
copy to b/copy.txt
";

    /// A rename of a file whose name contains a space and a TAB: git C-quotes every spelling.
    const GIT_RENAME_QUOTED: &str = "diff --git \"a/sp ace\\tx\" \"b/sp ace\\ty\"
similarity index 100%
rename from \"sp ace\\tx\"
rename to \"sp ace\\ty\"
";

    /// `été.txt`, chmod +x and one line appended: octal-escaped UTF-8 in every spelling.
    const GIT_QUOTED_UTF8_EDIT: &str = "diff --git \"a/\\303\\251t\\303\\251.txt\" \"b/\\303\\251t\\303\\251.txt\"
old mode 100644
new mode 100755
index 975fbec..77811bc
--- \"a/\\303\\251t\\303\\251.txt\"
+++ \"b/\\303\\251t\\303\\251.txt\"
@@ -1 +1,2 @@
 y
+y2
";

    /// Control: an ordinary edit inside a real directory named `a/` (right on e0df1c9 too).
    const GIT_EDIT_IN_A_DIR: &str = "diff --git a/a/keep.txt b/a/keep.txt
index b68fde2..ad2705a 100644
--- a/a/keep.txt
+++ b/a/keep.txt
@@ -1 +1,2 @@
 k
+k2
";

    #[test]
    fn a_rename_between_real_a_and_b_directories_keeps_them() {
        let v = effect_of_patch("renameabdirs", GIT_RENAME_AB_DIRS.as_bytes());
        assert_eq!(v["files"][0]["path"], json!("b/new.txt"), "e0df1c9 said new.txt: {v}");
        assert_eq!(v["files"][0]["renamed_from"], json!("a/old.txt"), "{v}");
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn a_copy_between_real_a_and_b_directories_keeps_them() {
        let v = effect_of_patch("copyabdirs", GIT_COPY_AB_DIRS.as_bytes());
        assert_eq!(v["files"][0]["path"], json!("b/copy.txt"), "{v}");
        assert_eq!(v["files"][0]["copied_from"], json!("a/src.txt"), "{v}");
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn quoted_paths_are_decoded_never_shown_in_their_escaped_spelling() {
        let v = effect_of_patch("renamequoted", GIT_RENAME_QUOTED.as_bytes());
        assert_eq!(v["files"][0]["path"], json!("sp ace\ty"), "{v}");
        assert_eq!(v["files"][0]["renamed_from"], json!("sp ace\tx"), "{v}");
        assert_eq!(v["summary_complete"], json!(true), "{v}");

        let v = effect_of_patch("quotedutf8", GIT_QUOTED_UTF8_EDIT.as_bytes());
        assert_eq!(v["file_count"], json!(1), "{v}");
        assert_eq!(v["files"][0]["path"], json!("été.txt"), "e0df1c9 showed the escapes: {v}");
        assert_eq!(v["files"][0]["new_mode"], json!("100755"));
        assert_eq!((v["added_lines"].clone(), v["removed_lines"].clone()), (json!(1), json!(0)));
        assert_eq!(v["summary_complete"], json!(true), "{v}");

        let v = effect_of_patch("editadir", GIT_EDIT_IN_A_DIR.as_bytes());
        assert_eq!(v["files"][0]["path"], json!("a/keep.txt"), "control: {v}");
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn a_path_that_cannot_be_decoded_or_that_disagrees_is_incomplete() {
        // An unterminated quote, and an octal escape that is not UTF-8: not guessed at.
        for (tag, body) in [
            ("unterminated", "diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to \"y\n"),
            ("badutf8", "diff --git \"a/\\377.txt\" \"b/\\377.txt\"\nold mode 100644\nnew mode 100755\n"),
            // the diff --git line names a/x -> b/y, the rename headers name something else
            ("disagrees", "diff --git a/x b/y\nsimilarity index 100%\nrename from p\nrename to q\n"),
        ] {
            let v = effect_of_patch(tag, body.as_bytes());
            assert_eq!(v["summary_complete"], json!(false), "{tag}: {v}");
            let shown = v["files"].to_string();
            assert!(!shown.contains("\\\\377") && !shown.contains("\\\"y"),
                    "{tag}: an escaped spelling was shown as a path: {shown}");
        }
    }

    // ---- The strip level comes from the ACT (coordinator, after 8caa210 assumed -p1 in
    // silence). Fixtures are byte-for-byte `git diff` output from a throwaway repo
    // (2026-09-30): `git diff --no-prefix` of edits to a/keep.txt (a REAL directory named a/)
    // and src/lib.rs; and `git diff --cached -M` of a rename hestia/core/old.rs -> new.rs plus
    // an edit to hestia/core/x.rs (ground truth `git diff --summary --numstat`:
    // "rename hestia/core/{old.rs => new.rs} (100%)", "1 0 hestia/core/x.rs").

    const GIT_NO_PREFIX: &str = "diff --git a/keep.txt a/keep.txt
index b68fde2..ad2705a 100644
--- a/keep.txt
+++ a/keep.txt
@@ -1 +1,2 @@
 k
+k2
diff --git src/lib.rs src/lib.rs
index ca05282..83021ca 100644
--- src/lib.rs
+++ src/lib.rs
@@ -1 +1,2 @@
 fn a() {}
+fn b() {}
";

    const GIT_DEEP: &str = "diff --git a/hestia/core/old.rs b/hestia/core/new.rs
similarity index 100%
rename from hestia/core/old.rs
rename to hestia/core/new.rs
diff --git a/hestia/core/x.rs b/hestia/core/x.rs
index 5626abf..814f4a4 100644
--- a/hestia/core/x.rs
+++ b/hestia/core/x.rs
@@ -1 +1,2 @@
 one
+two
";

    fn effect_of_patch_act(tag: &str, body: &str, act_of: impl Fn(&str) -> String) -> Value {
        let d = tmpdir(tag);
        let patch = d.join("p.patch");
        std::fs::write(&patch, body).unwrap();
        let act = act_of(&patch.display().to_string());
        let v = write_effect(&act).unwrap_or_else(|| panic!("{tag}: `{act}` is not a patch act"));
        std::fs::remove_dir_all(&d).ok();
        v
    }

    fn paths(v: &Value) -> Vec<String> {
        v["files"].as_array().map(|a| a.iter().map(|f| f["path"].as_str().unwrap_or("?").to_string()).collect())
            .unwrap_or_default()
    }

    #[test]
    fn a_no_prefix_patch_under_p0_names_its_real_paths() {
        let v = effect_of_patch_act("noprefixp0", GIT_NO_PREFIX, |p| format!("git -C /repo apply -p0 {p}"));
        assert_eq!(paths(&v), vec!["a/keep.txt", "src/lib.rs"], "8caa210 said keep.txt: {v}");
        assert_eq!(v["strip_level"], json!(0));
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn a_no_prefix_patch_under_the_default_p1_is_incomplete() {
        let v = effect_of_patch_act("noprefixp1", GIT_NO_PREFIX, |p| format!("git -C /repo apply {p}"));
        assert_eq!(v["summary_complete"], json!(false), "8caa210 called it complete: {v}");
        assert_eq!(v["strip_level"], json!(1));
        let why = v["incomplete"].to_string();
        assert!(why.contains("--no-prefix") && why.contains("-p1"), "{why}");
    }

    #[test]
    fn a_p2_act_strips_two_components_and_one_from_rename_headers() {
        for act in ["git -C /repo/hestia apply -p2 {p}", "git -C /repo/hestia apply -p 2 {p}"] {
            let v = effect_of_patch_act("deepp2", GIT_DEEP, |p| act.replace("{p}", p));
            assert_eq!(paths(&v), vec!["core/new.rs", "core/x.rs"], "{act}: {v}");
            assert_eq!(v["files"][0]["renamed_from"], json!("core/old.rs"), "{act}");
            assert_eq!(v["strip_level"], json!(2), "{act}");
            assert_eq!(v["summary_complete"], json!(true), "{act}: {v}");
        }
        // --directory prefixes every name after stripping
        let v = effect_of_patch_act("deepdir", GIT_DEEP, |p| format!("git apply --directory=sub {p}"));
        assert_eq!(paths(&v), vec!["sub/hestia/core/new.rs", "sub/hestia/core/x.rs"], "{v}");
        assert_eq!(v["files"][0]["renamed_from"], json!("sub/hestia/core/old.rs"));
        assert_eq!(v["summary_complete"], json!(true), "{v}");
    }

    #[test]
    fn an_undeterminable_strip_level_or_unmodelled_option_is_incomplete() {
        for (act, needle) in [
            ("patch -i {p}", "strip level could not be determined"),
            ("git apply -pX {p}", "strip level could not be determined"),
            ("git apply --include=src/* {p}", "--include"),
            ("git apply -R {p}", "`-R`"),
            ("patch -p1 --dry-run -i {p}", "--dry-run"),
        ] {
            let v = effect_of_patch_act("undet", TWO_FILE_PATCH, |p| act.replace("{p}", p));
            assert_eq!(v["summary_complete"], json!(false), "{act}: 8caa210 called it complete: {v}");
            assert!(v["incomplete"].to_string().contains(needle), "{act}: {}", v["incomplete"]);
        }
        // controls: a determined level and neutral options stay complete
        for act in ["patch -p1 -i {p}", "git apply -p1 --3way {p}", "git am -3 --signoff {p}"] {
            let v = effect_of_patch_act("det", TWO_FILE_PATCH, |p| act.replace("{p}", p));
            assert_eq!(v["summary_complete"], json!(true), "{act}: {v}");
        }
    }
}
