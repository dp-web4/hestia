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
    let new_bytes = std::fs::read(&src).ok()?;
    let new_text = String::from_utf8_lossy(&new_bytes).to_string();
    let payload_sha256 =
        crate::server::gate_escalation::EscalationStore::measured_payload_for_act(act);

    let mut out = json!({
        "source": src.display().to_string(),
        "source_readable": true,
        "source_bytes": new_bytes.len(),
        "source_lines": new_text.lines().count(),
        // The same value the approval BINDS (#1056), carried here so a reader can see that
        // the thing they are reviewing and the thing the permit will hold are one object.
        "payload_sha256": payload_sha256,
        "destination_stated": dest_token,
    });

    match enforcing_copy(&dest_token) {
        Some(cur) => {
            let old_text = std::fs::read(&cur)
                .map(|b| String::from_utf8_lossy(&b).to_string())
                .unwrap_or_default();
            let d = line_diff(&old_text, &new_text);
            out["compared_against"] = json!({
                "path": cur.display().to_string(),
                // NAMED PRECISELY. This is not the destination the act will write; it is the
                // copy currently enforcing. Calling it "the destination" would be a small lie
                // that a reviewer would reasonably rely on.
                "what": "the copy currently ENFORCING on this daemon, not the act's destination",
            });
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
}
