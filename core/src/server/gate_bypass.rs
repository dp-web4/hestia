//! Bypass / restore a member's gate — a fail-OPEN recovery switch, witnessed.
//!
//! dp, 2026-09-28: *"in discover, for every registered harness add a 'bypass' button (that turns
//! into 'restore'). the effect would be to replace that harness's pretooluse hook with a fail-[open]
//! bypass. it should come with appropriate warnings."* — then: *"this is useful for instances when
//! an update locks out a member that we need to be active to fix the issues. happens frequently
//! still"*.
//!
//! So this is the operator's way to let a member ACT again when its own gate has broken under it:
//! the gate's path in the member's harness registration is swapped for a stub that allows every
//! call, and swapped back on restore. Everything else in the registration — env prefixes, the
//! interpreter, the other hooks, comments, formatting — is left byte-for-byte alone, because only
//! the one path token moves.
//!
//! WHAT THIS MODULE DOES NOT DO, on purpose: it does not tell any other surface that the member is
//! bypassed. dp: *"if everything is working correctly, the bypassed harness should automatically
//! be flagged as 'miswired'. don't add any new code for that, this would be a good test to see if
//! miswired indication works."* The stub is written by the daemon from a string that names the
//! member and the moment, so its bytes match no file hestia ships, sit at no path any plugin
//! declares, and appear in no deploy record — none of agent-inventory's provenance rules (#1144)
//! can mistake it for hestia's gate. What the inventory then says about the member is its own
//! finding, and the test.
//!
//! Where the gate is: the inventory's own `hook_targets` for the member — `is_gate` and
//! `owned_by_hestia`, with the `config` file that registers it — the same discovered truth the
//! Gates pane and `discovered_gate_paths` use. No per-harness config reader is written here.
//!
//! Durable: the record of what was swapped lives in `$HESTIA_HOME/bypass/<member>.json`, so a
//! restore after a daemon restart is exact. Refusals: a second bypass while one is active; a
//! restore whose config no longer carries the stub (it names what changed instead of guessing).

use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

/// One gate's edit: in `config`, the command string(s) registered on `event` that named `original`
/// now name `replacement` -- the shell-quoted path of a stub UNIQUE to this original (its filename
/// carries a hash of the original path), so the reverse swap is unambiguous per entry even when one
/// config registers several gates (GPT, #1158 review).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Swap {
    pub config: String,
    #[serde(default)]
    pub event: String,
    pub original: String,
    /// The COMPLETE shell word that was replaced, with its own quoting as it appeared in the config
    /// (`/g/x.py`, `'/g/x.py'`, or `\"/g/x.py\"` inside a JSON/TOML basic string). Restore puts
    /// back exactly this; empty in a record written before 2026-09-28's quoting fix.
    #[serde(default)]
    pub original_word: String,
    pub replacement: String,
    #[serde(default)]
    pub stub_file: String,
    pub occurrences: usize,
}

/// A gate the inventory found: which config registers it, on which event, at which path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateTarget {
    pub config: String,
    pub event: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BypassRecord {
    pub member: String,
    pub reason: String,
    pub bypassed_at: String,
    pub stub: String,
    pub swaps: Vec<Swap>,
}

/// A member id as a filename component. Member ids are `[A-Za-z0-9_.-]`; anything else is
/// refused rather than sanitised, so two ids can never share a record.
pub fn checked_member(member: &str) -> Result<&str> {
    let m = member.trim();
    if m.is_empty()
        || m.len() > 64
        || m.starts_with('.')
        || !m.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
    {
        bail!("'{member}' is not a member id");
    }
    Ok(m)
}

pub fn bypass_dir(home: &Path) -> PathBuf {
    home.join("bypass")
}

pub fn record_path(home: &Path, member: &str) -> PathBuf {
    bypass_dir(home).join(format!("{member}.json"))
}

/// One stub per ORIGINAL gate path: `gate_bypass-<sha256(original)[..12]>.py`.
pub fn stub_path(home: &Path, member: &str, original: &str) -> PathBuf {
    use sha2::{Digest, Sha256};
    let h = hex::encode(Sha256::digest(original.as_bytes()));
    bypass_dir(home).join(member).join(format!("gate_bypass-{}.py", &h[..12]))
}

/// The stub's path as it must appear inside a registered command: bare when it is one shell
/// word, else single-quoted. Refused when it cannot be carried safely through BOTH layers -- the
/// shell word, and the config string that holds the command (a JSON or TOML basic string, where a
/// double quote or backslash would need escaping, and a TOML literal string, where a single quote
/// cannot appear at all).
pub fn command_word(path: &str, delim: char) -> Result<String> {
    if path.chars().all(|c| c.is_ascii_alphanumeric() || "/._-+:@%,=".contains(c)) {
        return Ok(path.to_string());
    }
    if path.chars().any(|c| c.is_control() || matches!(c, '\'' | '"' | '\\')) {
        bail!("the bypass stub path {path:?} cannot be quoted safely into a hook command; \
               move HESTIA_HOME to a path without quotes or backslashes");
    }
    if delim == '\'' {
        bail!("the gate's command is a TOML literal string ('...'), which cannot hold the quotes the \
               stub path {path:?} needs; nothing was changed");
    }
    Ok(format!("'{path}'"))
}

/// The stub: read the event (so the harness never blocks on a full pipe), print nothing, exit 0 —
/// ALLOW, on every harness that runs a PreToolUse/BeforeTool command. Its bytes name the member and
/// the moment, so it is never byte-identical to a file hestia ships.
pub fn stub_source(member: &str, at: &str) -> String {
    format!(
        "#!/usr/bin/env python3\n\
         # GATE BYPASSED by the operator for member {member} at {at}.\n\
         # This stands where the member's gate is registered and ALLOWS every tool call: the member\n\
         # acts UNGOVERNED until the operator restores the gate (Discover -> restore). Written by\n\
         # the hestia daemon; the record of what it replaced is beside this directory.\n\
         import sys\n\
         try:\n    sys.stdin.read()\nexcept Exception:\n    pass\n\
         sys.exit(0)\n"
    )
}

fn is_boundary(c: Option<char>) -> bool {
    match c {
        None => true,
        // A backslash is a boundary for the `\"` of a double-quoted word inside a JSON/TOML basic
        // string; `word_span` then checks the whole word, so a glued word is still refused.
        Some(c) => c.is_whitespace() || matches!(c, '"' | '\'' | '=' | '`' | '\\'),
    }
}

/// Replace every WHOLE-TOKEN occurrence of `from` with `to`: bounded by start/end, whitespace or a
/// quote on both sides, so `/h/pre_tool_use.py` never matches inside `/h/pre_tool_use.py.bak` or
/// `/x/h/pre_tool_use.py`. Returns the new text and the count.
pub fn swap_token(text: &str, from: &str, to: &str) -> (String, usize) {
    if from.is_empty() {
        return (text.to_string(), 0);
    }
    let mut out = String::with_capacity(text.len());
    let mut n = 0;
    let mut i = 0;
    while let Some(off) = text[i..].find(from) {
        let at = i + off;
        let end = at + from.len();
        let before = text[..at].chars().next_back();
        let after = text[end..].chars().next();
        out.push_str(&text[i..at]);
        if is_boundary(before) && is_boundary(after) {
            out.push_str(to);
            n += 1;
        } else {
            out.push_str(from);
        }
        i = end;
    }
    out.push_str(&text[i..]);
    (out, n)
}

/// Write `text` to `path` atomically, keeping the file's mode (a 0600 config stays 0600).
fn write_atomic(path: &Path, text: &str) -> Result<()> {
    let dir = path.parent().ok_or_else(|| anyhow!("{} has no parent", path.display()))?;
    let tmp = dir.join(format!(
        ".{}.hestia-bypass.{}",
        path.file_name().and_then(|n| n.to_str()).unwrap_or("cfg"),
        std::process::id()
    ));
    std::fs::write(&tmp, text).with_context(|| format!("write {}", tmp.display()))?;
    #[cfg(unix)]
    if let Ok(meta) = std::fs::metadata(path) {
        let _ = std::fs::set_permissions(&tmp, meta.permissions());
    }
    std::fs::rename(&tmp, path).with_context(|| format!("replace {}", path.display()))?;
    Ok(())
}

/// The member's registered hestia gate(s): `(config file, gate path)` from the inventory report.
pub fn gate_targets(inv: &serde_json::Value, member: &str) -> Result<Vec<GateTarget>> {
    if inv.get("status").and_then(|v| v.as_str()) == Some("UNKNOWN") {
        bail!(
            "the inventory could not look ({}); refusing to edit a registration it cannot see",
            inv.get("reason").and_then(|v| v.as_str()).unwrap_or("no reason given")
        );
    }
    let recs: Vec<&serde_json::Value> = inv
        .get("detail")
        .and_then(|d| d.as_array())
        .into_iter()
        .flatten()
        .filter(|r| r.get("member").and_then(|v| v.as_str()) == Some(member))
        .collect();
    if recs.is_empty() {
        bail!("no harness on this machine is registered as member '{member}'");
    }
    let mut out: Vec<GateTarget> = Vec::new();
    for r in recs {
        for t in r.get("hook_targets").and_then(|v| v.as_array()).into_iter().flatten() {
            let yes = |k: &str| t.get(k).and_then(|v| v.as_bool()) == Some(true);
            if !(yes("is_gate") && yes("owned_by_hestia")) {
                continue;
            }
            let (Some(path), Some(cfg), Some(event)) = (
                t.get("path").and_then(|v| v.as_str()),
                t.get("config").and_then(|v| v.as_str()),
                t.get("event").and_then(|v| v.as_str()),
            ) else {
                continue;
            };
            let g = GateTarget { config: cfg.into(), event: event.into(), path: path.into() };
            if !out.contains(&g) {
                out.push(g);
            }
        }
    }
    if out.is_empty() {
        bail!(
            "member '{member}' has no registered hestia gate to bypass (the inventory lists none on \
             a gate event); nothing is locking it out at the gate"
        );
    }
    Ok(out)
}

/// A command string value in a hook config: the EVENT it is registered on, and the byte span of
/// its raw contents (between the delimiters), plus the delimiter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandSpan {
    pub event: String,
    pub start: usize,
    pub end: usize,
    pub delim: char,
}

/// Every hook command in `text`, bound STRUCTURALLY to its event -- never by searching the whole
/// file, so a gate script also referenced on PostToolUse or SessionStart is not touched (GPT,
/// #1158 review). JSON (`hooks.<Event>[].hooks[].command`, claude/gemini) is read by a key-path
/// scanner; TOML by table: codex's `[[hooks.<Event>...]]` headers, and kimi's flat `[[hooks]]`
/// tables carrying `event = "X"` in either key order.
pub fn command_spans(config: &Path, text: &str) -> Vec<CommandSpan> {
    if config.extension().and_then(|e| e.to_str()) == Some("json") {
        json_command_spans(text)
    } else {
        toml_command_spans(text)
    }
}

fn json_command_spans(text: &str) -> Vec<CommandSpan> {
    enum Fr { Obj { key: Option<String>, want_key: bool }, Arr }
    let b = text.as_bytes();
    let mut st: Vec<Fr> = Vec::new();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'{' => st.push(Fr::Obj { key: None, want_key: true }),
            b'[' => st.push(Fr::Arr),
            b'}' | b']' => { st.pop(); }
            b',' => if let Some(Fr::Obj { want_key, .. }) = st.last_mut() { *want_key = true; },
            b':' => if let Some(Fr::Obj { want_key, .. }) = st.last_mut() { *want_key = false; },
            b'"' => {
                let start = i + 1;
                let mut j = start;
                while j < b.len() && b[j] != b'"' {
                    j += if b[j] == b'\\' { 2 } else { 1 };
                }
                let j = j.min(b.len());
                if let Some(Fr::Obj { key, want_key: true }) = st.last_mut() {
                    *key = Some(text[start..j].to_string());
                } else {
                    let keys: Vec<&str> = st.iter().filter_map(|f| match f {
                        Fr::Obj { key: Some(k), .. } => Some(k.as_str()),
                        _ => None,
                    }).collect();
                    if keys.len() == 4 && keys[0] == "hooks" && keys[2] == "hooks" && keys[3] == "command" {
                        out.push(CommandSpan { event: keys[1].to_string(), start, end: j, delim: '"' });
                    }
                }
                i = j;
            }
            _ => {}
        }
        i += 1;
    }
    out
}

fn toml_command_spans(text: &str) -> Vec<CommandSpan> {
    let mut out = Vec::new();
    let mut header_event: Option<String> = None;
    let mut flat = false;
    let mut flat_event: Option<String> = None;
    let mut pending: Vec<(usize, usize, char)> = Vec::new();
    let flush = |out: &mut Vec<CommandSpan>, ev: &Option<String>, p: &mut Vec<(usize, usize, char)>| {
        if let Some(e) = ev {
            out.extend(p.iter().map(|&(s, t, d)| CommandSpan { event: e.clone(), start: s, end: t, delim: d }));
        }
        p.clear();
    };
    // `(key, value span, delim)` of a `key = "v"` / `key = 'v'` line, offsets absolute.
    let kv = |line: &str, off: usize| -> Option<(String, usize, usize, char)> {
        let (k, rest) = line.split_once('=')?;
        let k = k.trim().to_string();
        let lead = line.len() - rest.len();
        let r = rest.trim_start();
        let q = r.chars().next().filter(|c| *c == '"' || *c == '\'')?;
        let vs = off + lead + (rest.len() - r.len()) + 1;
        let close = r[1..].rfind(q)?;
        Some((k, vs, vs + close, q))
    };
    let mut off = 0;
    for line in text.split_inclusive('\n') {
        let t = line.trim();
        if t.starts_with('[') {
            flush(&mut out, &flat_event, &mut pending);
            let name = t.trim_start_matches('[').trim_end_matches(']').trim();
            flat = name == "hooks";
            flat_event = None;
            header_event = name.strip_prefix("hooks.").map(|r| r.split('.').next().unwrap_or("").to_string());
        } else if let Some((k, s, e, d)) = kv(line.trim_end_matches(['\n', '\r']), off) {
            if k == "event" && flat {
                flat_event = Some(text[s..e].to_string());
            } else if k == "command" {
                if flat {
                    pending.push((s, e, d));
                } else if let Some(ev) = &header_event {
                    out.push(CommandSpan { event: ev.clone(), start: s, end: e, delim: d });
                }
            }
        }
        off += line.len();
    }
    flush(&mut out, &flat_event, &mut pending);
    out
}

/// Whole-token occurrences of `tok` inside [start, end) of `text`, as absolute offsets.
fn token_positions(text: &str, start: usize, end: usize, tok: &str) -> Vec<usize> {
    let mut out = Vec::new();
    let hay = &text[start..end];
    let mut i = 0;
    while let Some(o) = hay[i..].find(tok) {
        let at = i + o;
        let before = hay[..at].chars().next_back();
        let after = hay[at + tok.len()..].chars().next();
        if is_boundary(before) && is_boundary(after) {
            out.push(start + at);
        }
        i = at + tok.len();
    }
    out
}

/// Widen an occurrence of a path at `p` to its COMPLETE shell word inside the command span `c`:
/// if the path is wrapped in shell quotes -- `'…'`, or `"…"` which appears as `\"…\"` inside a JSON
/// or TOML basic string and raw inside a TOML literal string -- the quotes belong to the word. The
/// replacement must take them too, or an already-quoted original with a quoted stub becomes
/// `''/stub path''`, which the shell splits (GPT, #1158 re-review). Returns None when the word is
/// glued to something else (`'/g/x.py'--flag`): a word this cannot read is refused, not guessed.
fn word_span(text: &str, c: &CommandSpan, p: usize, len: usize) -> Option<(usize, usize)> {
    let dq: &str = if c.delim == '"' { "\\\"" } else { "\"" };
    let (mut s, mut e) = (p, p + len);
    for q in ["'", dq] {
        if text[c.start..s].ends_with(q) && text[e..c.end].starts_with(q) {
            s -= q.len();
            e += q.len();
            break;
        }
    }
    let before = text[c.start..s].chars().next_back();
    let after = text[e..c.end].chars().next();
    let ok = |ch: Option<char>| ch.map_or(true, char::is_whitespace);
    (ok(before) && ok(after)).then_some((s, e))
}

pub fn active(home: &Path, member: &str) -> Option<BypassRecord> {
    let raw = std::fs::read(record_path(home, member)).ok()?;
    serde_json::from_slice(&raw).ok()
}

pub fn all_active(home: &Path) -> Vec<BypassRecord> {
    let mut out: Vec<BypassRecord> = std::fs::read_dir(bypass_dir(home))
        .into_iter()
        .flatten()
        .flatten()
        .filter(|e| e.path().extension().and_then(|x| x.to_str()) == Some("json"))
        .filter_map(|e| std::fs::read(e.path()).ok())
        .filter_map(|b| serde_json::from_slice::<BypassRecord>(&b).ok())
        .collect();
    out.sort_by(|a, b| a.member.cmp(&b.member));
    out
}

/// Write several configs as ONE act: each file written once, re-read and verified; on any
/// failure every file already written goes back to the exact bytes it had before this call.
fn commit_configs(next: &[(String, String, String)]) -> Result<()> {
    let mut done: Vec<&(String, String, String)> = Vec::new();
    for item in next {
        let (cfg, before, after) = item;
        let r = write_atomic(Path::new(cfg), after).and_then(|_| {
            if std::fs::read_to_string(cfg)? != *after {
                bail!("{cfg} did not read back as written");
            }
            Ok(())
        });
        if let Err(e) = r {
            for (c, b, _) in done.into_iter().rev() {
                let _ = write_atomic(Path::new(c), b);
            }
            let _ = write_atomic(Path::new(cfg), before);
            return Err(e);
        }
        done.push(item);
    }
    Ok(())
}

/// Reverse (or re-apply) recorded swaps, one write per config. Every replacement is unique to its
/// original, so the direction is unambiguous per entry; a token that is no longer present refuses
/// the whole act, naming the file, before anything is written.
fn swap_back(swaps: &[Swap], to_original: bool) -> Result<()> {
    let mut configs: Vec<String> = Vec::new();
    for s in swaps {
        if !configs.contains(&s.config) {
            configs.push(s.config.clone());
        }
    }
    let mut next = Vec::new();
    for cfg in configs {
        let before = std::fs::read_to_string(&cfg).with_context(|| format!("read {cfg}"))?;
        let mut text = before.clone();
        for s in swaps.iter().filter(|s| s.config == cfg) {
            let orig_word = if s.original_word.is_empty() { &s.original } else { &s.original_word };
            let (from, to) = if to_original { (&s.replacement, orig_word) } else { (&s.original, &s.replacement) };
            let (t, n) = if to_original {
                swap_token(&text, from, to)
            } else {
                // Re-applying binds to the gate's event again, and replaces the whole word, as the
                // bypass did.
                let spans: Vec<CommandSpan> = command_spans(Path::new(&cfg), &text)
                    .into_iter().filter(|c| c.event == s.event).collect();
                let mut words: Vec<(usize, usize)> = Vec::new();
                for c in &spans {
                    for p in token_positions(&text, c.start, c.end, from) {
                        if let Some(w) = word_span(&text, c, p, from.len()) {
                            words.push(w);
                        }
                    }
                }
                words.sort_unstable();
                let mut t = text.clone();
                for (ws, we) in words.iter().rev() {
                    t.replace_range(*ws..*we, to);
                }
                (t, words.len())
            };
            if n == 0 {
                bail!(
                    "{cfg} no longer registers {} ({}): it was edited or re-registered since the \
                     bypass. Nothing was changed",
                    if to_original { "the bypass stub" } else { "the gate" }, from
                );
            }
            text = t;
        }
        next.push((cfg, before, text));
    }
    commit_configs(&next)
}

/// Swap the member's gate(s) for fail-open stubs and record it. Refuses while a bypass is active.
pub fn bypass(
    home: &Path,
    member: &str,
    reason: &str,
    targets: &[GateTarget],
    at: &str,
) -> Result<BypassRecord> {
    let member = checked_member(member)?;
    if let Some(r) = active(home, member) {
        bail!(
            "member '{member}' is already bypassed (since {}, reason: {}); restore it first",
            r.bypassed_at, r.reason
        );
    }
    // Plan EVERY edit before writing anything: a gate the config does not register on its event,
    // or a stub path that cannot be quoted into it, refuses the whole act.
    let mut configs: Vec<String> = Vec::new();
    for t in targets {
        if !configs.contains(&t.config) {
            configs.push(t.config.clone());
        }
    }
    let mut swaps = Vec::new();
    let mut next = Vec::new();
    for cfg in &configs {
        let before = std::fs::read_to_string(cfg).with_context(|| format!("read {cfg}"))?;
        let spans = command_spans(Path::new(cfg), &before);
        let mut edits: Vec<(usize, usize, String)> = Vec::new();
        for t in targets.iter().filter(|t| &t.config == cfg) {
            let stub = stub_path(home, member, &t.path);
            let stub_s = stub.display().to_string();
            let mut n = 0;
            let mut original_word: Option<String> = None;
            for c in spans.iter().filter(|c| c.event == t.event) {
                let word = command_word(&stub_s, c.delim)?;
                for p in token_positions(&before, c.start, c.end, &t.path) {
                    let Some((ws, we)) = word_span(&before, c, p, t.path.len()) else {
                        bail!("{cfg}: the gate path {} on {} is part of a larger shell word this cannot \
                               read safely; nothing was changed", t.path, t.event);
                    };
                    let w = before[ws..we].to_string();
                    if original_word.as_ref().is_some_and(|o| o != &w) {
                        bail!("{cfg}: {} is registered on {} under two different quotings; restore could \
                               not tell them apart, so nothing was changed", t.path, t.event);
                    }
                    original_word = Some(w);
                    edits.push((ws, we, word.clone()));
                    n += 1;
                }
            }
            if n == 0 {
                bail!(
                    "{cfg} does not register {} as a command token on {}; nothing was changed",
                    t.path, t.event
                );
            }
            swaps.push(Swap {
                config: cfg.clone(),
                event: t.event.clone(),
                original: t.path.clone(),
                original_word: original_word.unwrap_or_else(|| t.path.clone()),
                replacement: command_word(&stub_s, '"').unwrap_or_else(|_| stub_s.clone()),
                stub_file: stub_s,
                occurrences: n,
            });
        }
        edits.sort_by_key(|e| e.0);
        edits.dedup_by_key(|e| e.0);
        let mut text = before.clone();
        for (s, e, w) in edits.iter().rev() {
            text.replace_range(*s..*e, w);
        }
        next.push((cfg.clone(), before, text));
    }
    let dir = bypass_dir(home).join(member);
    std::fs::create_dir_all(&dir)?;
    for s in &swaps {
        std::fs::write(&s.stub_file, stub_source(member, at))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&s.stub_file, std::fs::Permissions::from_mode(0o755))?;
        }
    }
    let rec = BypassRecord {
        member: member.to_string(),
        reason: reason.to_string(),
        bypassed_at: at.to_string(),
        stub: dir.display().to_string(),
        swaps,
    };
    // The record lands BEFORE the configs change: a crash in between leaves a record of a swap
    // that did not happen (restore then says so) rather than a swap nobody recorded.
    write_atomic_new(&record_path(home, member), &serde_json::to_string_pretty(&rec)?)?;
    if let Err(e) = commit_configs(&next) {
        let _ = std::fs::remove_file(record_path(home, member));
        return Err(e);
    }
    Ok(rec)
}

fn write_atomic_new(path: &Path, text: &str) -> Result<()> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    if path.exists() {
        return write_atomic(path, text);
    }
    std::fs::write(path, text)?;
    Ok(())
}

/// Undo a bypass that was applied but could not be recorded on the chain.
pub fn undo_bypass(home: &Path, rec: &BypassRecord) -> Result<()> {
    swap_back(&rec.swaps, true)?;
    let _ = std::fs::remove_file(record_path(home, &rec.member));
    Ok(())
}

/// Put the member's gate back exactly. Refuses (naming the file) when a config no longer carries
/// its stub -- someone re-registered or edited it since, and swapping blind would guess.
pub fn restore(home: &Path, member: &str) -> Result<BypassRecord> {
    let member = checked_member(member)?;
    let rec = active(home, member).ok_or_else(|| anyhow!("member '{member}' is not bypassed"))?;
    swap_back(&rec.swaps, true).map_err(|e| anyhow!(
        "{e}. Put the gate back with the member's installer, or restore the registration by hand, \
         then retire the record at {}", record_path(home, member).display()))?;
    let _ = std::fs::remove_file(record_path(home, member));
    Ok(rec)
}

/// Undo a restore that could not be recorded on the chain: the member goes back to bypassed.
pub fn undo_restore(home: &Path, rec: &BypassRecord) -> Result<()> {
    swap_back(&rec.swaps, false)?;
    write_atomic_new(&record_path(home, &rec.member), &serde_json::to_string_pretty(rec)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    const G: &str = "/g/hooks/pre_tool_use.py";
    const G2: &str = "/g/hooks/second_gate.py";

    // The gate script ALSO referenced on PostToolUse, and a sibling path that merely ends with it:
    // neither may be touched (GPT #1158, finding 2).
    const CLAUDE: &str = r#"{
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "HESTIA_HOME=/h python3 /g/hooks/pre_tool_use.py", "timeout": 15 } ] }
    ],
    "PostToolUse": [
      { "hooks": [ { "type": "command", "command": "python3 /g/hooks/pre_tool_use.py --post" },
                   { "type": "command", "command": "python3 /g/hooks/pre_tool_use.py.bak" } ] }
    ]
  }
}
"#;
    const CODEX: &str = "[[hooks.PreToolUse]]\nmatcher = \".*\"\n\n[[hooks.PreToolUse.hooks]]\ntype = \"command\"\ncommand = \"HESTIA_WORKSPACE=/w python3 /g/hooks/pre_tool_use.py\"\ntimeout = 15\n\n[[hooks.PostToolUse]]\n\n[[hooks.PostToolUse.hooks]]\ntype = \"command\"\ncommand = \"python3 /g/hooks/pre_tool_use.py --post\"\n";
    // kimi's flat layout, with `event` AFTER `command` in one table.
    const KIMI: &str = "# keep me\n[[hooks]]\ncommand = \"HESTIA_ROLE=r python3 /g/hooks/pre_tool_use.py\"\nevent = \"PreToolUse\"\ntimeout = 15\n\n[[hooks]]\nevent = \"PostToolUse\"\ncommand = \"python3 /g/hooks/pre_tool_use.py --post\"\n";

    fn setup(body: &str, name: &str) -> (tempfile::TempDir, PathBuf, PathBuf) {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().join("hestia-home");
        let cfg = d.path().join(name);
        std::fs::write(&cfg, body).unwrap();
        (d, home, cfg)
    }

    fn gt(cfg: &Path, event: &str, path: &str) -> GateTarget {
        GateTarget { config: cfg.display().to_string(), event: event.into(), path: path.into() }
    }

    #[test]
    fn swap_is_whole_token_only() {
        let (s, n) = swap_token("python3 /g/hooks/pre_tool_use.py.bak x", G, "/stub.py");
        assert_eq!(n, 0, "the .bak sibling must not match");
        assert!(s.contains(".bak"));
        let (_, n) = swap_token("python3 /x/g/hooks/pre_tool_use.py", G, "/s");
        assert_eq!(n, 0, "a path that merely ENDS with the gate path is someone else's");
    }

    #[test]
    fn commands_are_bound_to_their_event_on_all_three_layouts() {
        for (body, name) in [(CLAUDE, "settings.json"), (CODEX, "config.toml"), (KIMI, "kimi.toml")] {
            let spans = command_spans(Path::new(name), body);
            let pre: Vec<&str> = spans.iter().filter(|c| c.event == "PreToolUse").map(|c| &body[c.start..c.end]).collect();
            assert_eq!(pre.len(), 1, "{name}: {spans:?}");
            assert!(pre[0].ends_with(G), "{name}: {pre:?}");
            assert!(spans.iter().any(|c| c.event == "PostToolUse"), "{name}: PostToolUse is seen, as its own event");
        }
    }

    #[test]
    fn only_the_gate_event_changes_and_restore_is_byte_exact() {
        for (body, name) in [(CLAUDE, "settings.json"), (CODEX, "config.toml"), (KIMI, "kimi.toml")] {
            let (_d, home, cfg) = setup(body, name);
            let rec = bypass(&home, "m1", "locked out", &[gt(&cfg, "PreToolUse", G)], "T").unwrap();
            let during = std::fs::read_to_string(&cfg).unwrap();
            assert_eq!(rec.swaps[0].occurrences, 1, "{name}");
            assert!(during.contains(&rec.swaps[0].replacement), "{name}: the stub is registered");
            assert!(during.contains("python3 /g/hooks/pre_tool_use.py --post"),
                    "{name}: the PostToolUse reference to the same script is untouched");
            assert!(Path::new(&rec.swaps[0].stub_file).is_file());
            restore(&home, "m1").unwrap();
            assert_eq!(std::fs::read_to_string(&cfg).unwrap(), body, "{name}: restore is exact");
            assert!(active(&home, "m1").is_none());
        }
    }

    const TWO: &str = r#"{
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "python3 /g/hooks/pre_tool_use.py" },
                   { "type": "command", "command": "python3 /g/hooks/second_gate.py" } ] }
    ]
  }
}
"#;

    #[test]
    fn two_gates_in_one_config_get_distinct_stubs_and_restore_exactly() {
        let (_d, home, cfg) = setup(TWO, "settings.json");
        let t = [gt(&cfg, "PreToolUse", G), gt(&cfg, "PreToolUse", G2)];
        let rec = bypass(&home, "m", "r", &t, "T").unwrap();
        assert_eq!(rec.swaps.len(), 2);
        assert_ne!(rec.swaps[0].replacement, rec.swaps[1].replacement, "one stub per original");
        let during = std::fs::read_to_string(&cfg).unwrap();
        assert!(!during.contains(G) && !during.contains(G2));
        restore(&home, "m").unwrap();
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), TWO, "each original back in its own place");
        // and the chain-append-failure path: undo is the same exact, per-entry reversal
        let rec = bypass(&home, "m", "r", &t, "T").unwrap();
        undo_bypass(&home, &rec).unwrap();
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), TWO);
        assert!(active(&home, "m").is_none());
        // and a restore that could not be witnessed goes back to bypassed, per entry
        bypass(&home, "m", "r", &t, "T").unwrap();
        let restored = restore(&home, "m").unwrap();
        undo_restore(&home, &restored).unwrap();
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), during, "both gates re-bypassed, each by its own stub");
        assert!(active(&home, "m").is_some());
    }

    #[test]
    fn a_spaced_home_is_quoted_for_the_shell_and_restores_exactly() {
        for (body, name) in [(CLAUDE, "settings.json"), (CODEX, "config.toml"), (KIMI, "kimi.toml")] {
            let d = tempfile::tempdir().unwrap();
            let home = d.path().join("hestia home");
            let cfg = d.path().join(name);
            std::fs::write(&cfg, body).unwrap();
            let rec = bypass(&home, "m", "r", &[gt(&cfg, "PreToolUse", G)], "T").unwrap();
            let w = &rec.swaps[0].replacement;
            assert!(w.starts_with('\'') && w.ends_with('\'') && w.contains("hestia home"), "{name}: {w}");
            let during = std::fs::read_to_string(&cfg).unwrap();
            if name.ends_with(".json") {
                let v: serde_json::Value = serde_json::from_str(&during).unwrap();
                let cmd = v["hooks"]["PreToolUse"][0]["hooks"][0]["command"].as_str().unwrap();
                assert!(cmd.ends_with(&format!("python3 {w}")), "{cmd}");
            }
            restore(&home, "m").unwrap();
            assert_eq!(std::fs::read_to_string(&cfg).unwrap(), body, "{name}");
        }
        // A TOML literal string cannot carry the quotes: refused before anything is written.
        let lit = "[[hooks.PreToolUse.hooks]]\ncommand = 'python3 /g/hooks/pre_tool_use.py'\n";
        let d = tempfile::tempdir().unwrap();
        let cfg = d.path().join("config.toml");
        std::fs::write(&cfg, lit).unwrap();
        let e = bypass(&d.path().join("sp ace"), "m", "r", &[gt(&cfg, "PreToolUse", G)], "T").unwrap_err();
        assert!(e.to_string().contains("literal string"), "{e}");
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), lit);
        assert!(command_word("/a'b", '"').is_err());
    }

    /// The command the harness would run for the PreToolUse gate, decoded from its config string.
    fn pre_command(cfg: &Path) -> String {
        let text = std::fs::read_to_string(cfg).unwrap();
        let c = command_spans(cfg, &text).into_iter().find(|c| c.event == "PreToolUse").unwrap();
        let raw = &text[c.start..c.end];
        if cfg.extension().and_then(|e| e.to_str()) == Some("json") || c.delim == '"' {
            serde_json::from_str::<String>(&format!("\"{raw}\"")).unwrap()
        } else {
            raw.to_string()
        }
    }

    /// argv as the real shell splits it, and whether the command actually runs to exit 0.
    fn shell_argv(cmd: &str) -> Vec<String> {
        let out = std::process::Command::new("sh")
            .arg("-c").arg(format!("set -- {cmd}; printf '%s\\n' \"$@\""))
            .output().unwrap();
        String::from_utf8(out.stdout).unwrap().lines().map(str::to_string).collect()
    }

    /// GPT, #1158 re-review: an ALREADY-QUOTED original plus a spaced destination became
    /// `''/stub path''` -- split by the shell, so the stub never ran. Read-back of bytes cannot see
    /// that; the shell can. Each case is executed.
    #[test]
    fn a_quoted_original_with_a_spaced_stub_is_one_argv_word_and_runs() {
        let cases = [
            ("settings.json", "{\n  \"hooks\": {\n    \"PreToolUse\": [\n      { \"hooks\": [ { \"type\": \"command\", \"command\": \"python3 '/g/hooks/pre_tool_use.py'\" } ] }\n    ]\n  }\n}\n"),
            ("settings.json", "{\n  \"hooks\": {\n    \"PreToolUse\": [\n      { \"hooks\": [ { \"type\": \"command\", \"command\": \"python3 \\\"/g/hooks/pre_tool_use.py\\\"\" } ] }\n    ]\n  }\n}\n"),
            ("config.toml", "[[hooks.PreToolUse.hooks]]\ncommand = \"python3 \\\"/g/hooks/pre_tool_use.py\\\"\"\n"),
            ("config.toml", "[[hooks.PreToolUse.hooks]]\ncommand = \"HESTIA_ROLE=r python3 '/g/hooks/pre_tool_use.py'\"\n"),
            ("kimi.toml", "[[hooks]]\nevent = \"PreToolUse\"\ncommand = \"python3 '/g/hooks/pre_tool_use.py'\"\n"),
            ("config.toml", "[[hooks.PreToolUse.hooks]]\ncommand = \"python3 /g/hooks/pre_tool_use.py\"\n"),
        ];
        for (name, body) in cases {
            let d = tempfile::tempdir().unwrap();
            let home = d.path().join("hestia home");
            let cfg = d.path().join(name);
            std::fs::write(&cfg, body).unwrap();
            // before: the shell sees the ORIGINAL gate as one word
            assert!(shell_argv(&pre_command(&cfg)).contains(&G.to_string()), "{name}: fixture");
            let rec = bypass(&home, "m", "r", &[gt(&cfg, "PreToolUse", G)], "T").unwrap();
            let cmd = pre_command(&cfg);
            let argv = shell_argv(&cmd);
            let at = argv.iter().position(|a| a == "python3").unwrap();
            assert_eq!(argv[at + 1], rec.swaps[0].stub_file, "{name}: argv after python3 is the stub, as ONE word: {argv:?} from {cmd}");
            assert_eq!(argv.len(), at + 2, "{name}: no stray words: {argv:?}");
            let run = std::process::Command::new("sh").arg("-c").arg(&cmd)
                .stdin(std::process::Stdio::null()).status().unwrap();
            assert!(run.success(), "{name}: the generated command runs the stub and allows: {cmd}");
            restore(&home, "m").unwrap();
            assert_eq!(std::fs::read_to_string(&cfg).unwrap(), body, "{name}: restore is exact, quotes included");
        }
        // A word this cannot read safely is refused, not guessed.
        let d = tempfile::tempdir().unwrap();
        let cfg = d.path().join("config.toml");
        let glued = "[[hooks.PreToolUse.hooks]]\ncommand = \"python3 '/g/hooks/pre_tool_use.py'--x\"\n";
        std::fs::write(&cfg, glued).unwrap();
        assert!(bypass(&d.path().join("h"), "m", "r", &[gt(&cfg, "PreToolUse", G)], "T").is_err());
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), glued);
    }

    #[test]
    fn the_stub_allows_and_is_unique_bytes() {
        let a = stub_source("kimi-code", "2026-09-28T20:00:00Z");
        let b = stub_source("codex", "2026-09-28T20:00:00Z");
        assert_ne!(a, b, "never byte-identical across members (so never a shipped file's bytes)");
        assert!(a.contains("sys.exit(0)") && !a.contains("sys.exit(2)"));
    }

    #[test]
    fn refusals() {
        let (_d, home, cfg) = setup(CODEX, "config.toml");
        let t = vec![gt(&cfg, "PreToolUse", G)];
        assert!(bypass(&home, "../x", "r", &t, "T").is_err(), "a non-id is refused");
        assert!(bypass(&home, "m", "r", &[gt(&cfg, "PreToolUse", "/elsewhere.py")], "T").is_err());
        assert!(bypass(&home, "m", "r", &[gt(&cfg, "SessionStart", G)], "T").is_err(),
                "a gate not registered on the named event is refused");
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), CODEX, "and nothing changed");
        bypass(&home, "m", "r", &t, "T").unwrap();
        let e = bypass(&home, "m", "r", &t, "T").unwrap_err().to_string();
        assert!(e.contains("already bypassed"), "{e}");
        std::fs::write(&cfg, CODEX).unwrap(); // re-registered by hand meanwhile
        let e = restore(&home, "m").unwrap_err().to_string();
        assert!(e.contains("no longer registers the bypass stub"), "{e}");
        assert!(restore(&home, "nobody").is_err());
    }

    #[test]
    fn a_config_keeps_its_mode() {
        use std::os::unix::fs::PermissionsExt;
        let (_d, home, cfg) = setup(CODEX, "config.toml");
        std::fs::set_permissions(&cfg, std::fs::Permissions::from_mode(0o600)).unwrap();
        bypass(&home, "m", "r", &[gt(&cfg, "PreToolUse", G)], "T").unwrap();
        assert_eq!(std::fs::metadata(&cfg).unwrap().permissions().mode() & 0o777, 0o600);
    }

    #[test]
    fn targets_come_from_the_inventory_gate_rows_only() {
        let inv = serde_json::json!({"status":"GAP","detail":[{"member":"kimi-code","hook_targets":[
            {"path":"/k/pre_tool_use.py","config":"/k/config.toml","event":"PreToolUse","is_gate":true,"owned_by_hestia":true},
            {"path":"/k/witness.py","config":"/k/config.toml","event":"PostToolUse","is_gate":false,"owned_by_hestia":true},
            {"path":"/snarc/pre.js","config":"/k/config.toml","event":"PreToolUse","is_gate":true,"owned_by_hestia":false}]}]});
        assert_eq!(gate_targets(&inv, "kimi-code").unwrap(), vec![GateTarget {
            config: "/k/config.toml".into(), event: "PreToolUse".into(), path: "/k/pre_tool_use.py".into() }]);
        assert!(gate_targets(&inv, "codex").is_err());
        assert!(gate_targets(&serde_json::json!({"status":"UNKNOWN","reason":"x"}), "kimi-code").is_err());
    }
}
