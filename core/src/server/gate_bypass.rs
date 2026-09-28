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

/// One registration file edit: every whole-token occurrence of `original` became `replacement`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Swap {
    pub config: String,
    pub original: String,
    pub replacement: String,
    pub occurrences: usize,
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

pub fn stub_path(home: &Path, member: &str) -> PathBuf {
    bypass_dir(home).join(member).join("gate_bypass.py")
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
        Some(c) => c.is_whitespace() || matches!(c, '"' | '\'' | '=' | '`'),
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
pub fn gate_targets(inv: &serde_json::Value, member: &str) -> Result<Vec<(String, String)>> {
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
    let mut out: Vec<(String, String)> = Vec::new();
    for r in recs {
        for t in r.get("hook_targets").and_then(|v| v.as_array()).into_iter().flatten() {
            let yes = |k: &str| t.get(k).and_then(|v| v.as_bool()) == Some(true);
            if !(yes("is_gate") && yes("owned_by_hestia")) {
                continue;
            }
            let (Some(path), Some(cfg)) = (
                t.get("path").and_then(|v| v.as_str()),
                t.get("config").and_then(|v| v.as_str()),
            ) else {
                continue;
            };
            let pair = (cfg.to_string(), path.to_string());
            if !out.contains(&pair) {
                out.push(pair);
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

/// Apply swaps in order; if one fails, put back the ones already applied and fail.
fn apply_swaps(swaps: &[Swap], reverse: bool) -> Result<()> {
    let mut done: Vec<&Swap> = Vec::new();
    for s in swaps {
        let (from, to) = if reverse { (&s.replacement, &s.original) } else { (&s.original, &s.replacement) };
        let r = (|| -> Result<()> {
            let text = std::fs::read_to_string(&s.config)
                .with_context(|| format!("read {}", s.config))?;
            let (next, n) = swap_token(&text, from, to);
            if n == 0 {
                bail!("{} no longer registers {from}", s.config);
            }
            write_atomic(Path::new(&s.config), &next)
        })();
        if let Err(e) = r {
            for d in done.into_iter().rev() {
                let (f, t) = if reverse { (&d.original, &d.replacement) } else { (&d.replacement, &d.original) };
                if let Ok(text) = std::fs::read_to_string(&d.config) {
                    let (back, _) = swap_token(&text, f, t);
                    let _ = write_atomic(Path::new(&d.config), &back);
                }
            }
            return Err(e);
        }
        done.push(s);
    }
    Ok(())
}

/// Swap the member's gate for the fail-open stub and record it. Refuses while a bypass is active.
pub fn bypass(
    home: &Path,
    member: &str,
    reason: &str,
    targets: &[(String, String)],
    at: &str,
) -> Result<BypassRecord> {
    let member = checked_member(member)?;
    if let Some(r) = active(home, member) {
        bail!(
            "member '{member}' is already bypassed (since {}, reason: {}); restore it first",
            r.bypassed_at, r.reason
        );
    }
    let stub = stub_path(home, member);
    let stub_s = stub.display().to_string();
    // Plan every swap before touching anything, so a config that does not carry its gate verbatim
    // (an escaped path, a relative spelling) refuses the whole act rather than half of it.
    let mut swaps = Vec::new();
    for (cfg, gate) in targets {
        let text = std::fs::read_to_string(cfg).with_context(|| format!("read {cfg}"))?;
        let (_, n) = swap_token(&text, gate, &stub_s);
        if n == 0 {
            bail!("{cfg} does not spell the gate path {gate} as a command token; nothing was changed");
        }
        swaps.push(Swap { config: cfg.clone(), original: gate.clone(), replacement: stub_s.clone(), occurrences: n });
    }
    std::fs::create_dir_all(stub.parent().expect("stub has a parent"))?;
    std::fs::write(&stub, stub_source(member, at))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&stub, std::fs::Permissions::from_mode(0o755))?;
    }
    let rec = BypassRecord {
        member: member.to_string(),
        reason: reason.to_string(),
        bypassed_at: at.to_string(),
        stub: stub_s,
        swaps,
    };
    // The record lands BEFORE the configs change: a crash in between leaves a record of a swap
    // that did not happen (restore then says so) rather than a swap nobody recorded.
    write_atomic_new(&record_path(home, member), &serde_json::to_string_pretty(&rec)?)?;
    if let Err(e) = apply_swaps(&rec.swaps, false) {
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
    apply_swaps(&rec.swaps, true)?;
    let _ = std::fs::remove_file(record_path(home, &rec.member));
    Ok(())
}

/// Put the member's gate back exactly. Refuses (naming the file) when a config no longer carries
/// the stub — someone re-registered or edited it since, and swapping blind would guess.
pub fn restore(home: &Path, member: &str) -> Result<BypassRecord> {
    let member = checked_member(member)?;
    let rec = active(home, member).ok_or_else(|| anyhow!("member '{member}' is not bypassed"))?;
    for s in &rec.swaps {
        let text = std::fs::read_to_string(&s.config).with_context(|| format!("read {}", s.config))?;
        let (_, n) = swap_token(&text, &s.replacement, &s.original);
        if n == 0 {
            bail!(
                "{} no longer registers the bypass stub ({}): it was edited or re-registered since \
                 the bypass. Nothing was restored; put the gate back with the member's installer, \
                 or restore the registration by hand, then retire the record at {}",
                s.config,
                s.replacement,
                record_path(home, member).display()
            );
        }
    }
    apply_swaps(&rec.swaps, true)?;
    let _ = std::fs::remove_file(record_path(home, member));
    Ok(rec)
}

/// Undo a restore that could not be recorded on the chain: the member goes back to bypassed.
pub fn undo_restore(home: &Path, rec: &BypassRecord) -> Result<()> {
    apply_swaps(&rec.swaps, false)?;
    write_atomic_new(&record_path(home, &rec.member), &serde_json::to_string_pretty(rec)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    const CLAUDE: &str = r#"{
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "HESTIA_HOME=/h python3 /g/hooks/pre_tool_use.py", "timeout": 15 } ] }
    ],
    "PostToolUse": [
      { "hooks": [ { "type": "command", "command": "python3 /g/hooks/pre_tool_use.py.bak" } ] }
    ]
  }
}
"#;
    const CODEX: &str = "[[hooks.PreToolUse]]\nmatcher = \".*\"\n\n[[hooks.PreToolUse.hooks]]\ntype = \"command\"\ncommand = \"HESTIA_WORKSPACE=/w python3 /g/hooks/pre_tool_use.py\"\ntimeout = 15\n";
    const KIMI: &str = "# keep me\n[[hooks]]\nevent = \"PreToolUse\"\ncommand = \"HESTIA_ROLE=r python3 /g/hooks/pre_tool_use.py\"\ntimeout = 15\n\n[[hooks]]\nevent = \"PostToolUse\"\ncommand = \"python3 /g/hooks/witness.py\"\n";

    fn setup(body: &str, name: &str) -> (tempfile::TempDir, PathBuf, PathBuf) {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().join("hestia-home");
        let cfg = d.path().join(name);
        std::fs::write(&cfg, body).unwrap();
        (d, home, cfg)
    }

    #[test]
    fn swap_is_whole_token_only() {
        let (s, n) = swap_token(CLAUDE, "/g/hooks/pre_tool_use.py", "/stub.py");
        assert_eq!(n, 1, "the .bak sibling must not match");
        assert!(s.contains("HESTIA_HOME=/h python3 /stub.py\""));
        assert!(s.contains("/g/hooks/pre_tool_use.py.bak"));
        let (_, n) = swap_token("python3 /x/g/hooks/pre_tool_use.py", "/g/hooks/pre_tool_use.py", "/s");
        assert_eq!(n, 0, "a path that merely ENDS with the gate path is someone else's");
    }

    #[test]
    fn bypass_then_restore_is_byte_exact_on_all_three_layouts() {
        for (body, name) in [(CLAUDE, "settings.json"), (CODEX, "config.toml"), (KIMI, "kimi.toml")] {
            let (_d, home, cfg) = setup(body, name);
            let c = cfg.display().to_string();
            let rec = bypass(&home, "m1", "locked out by a broken gate", &[(c.clone(), "/g/hooks/pre_tool_use.py".into())], "T").unwrap();
            let during = std::fs::read_to_string(&cfg).unwrap();
            assert!(during.contains(&rec.stub), "{name}: the stub is registered");
            assert!(!during.contains("python3 /g/hooks/pre_tool_use.py\""), "{name}: the gate is not");
            assert_eq!(during.len() as isize - body.len() as isize,
                       rec.stub.len() as isize - "/g/hooks/pre_tool_use.py".len() as isize,
                       "{name}: only the one token moved");
            assert!(Path::new(&rec.stub).is_file());
            assert!(active(&home, "m1").is_some());
            restore(&home, "m1").unwrap();
            assert_eq!(std::fs::read_to_string(&cfg).unwrap(), body, "{name}: restore is exact");
            assert!(active(&home, "m1").is_none());
        }
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
        let c = cfg.display().to_string();
        let t = vec![(c.clone(), "/g/hooks/pre_tool_use.py".to_string())];
        assert!(bypass(&home, "../x", "r", &t, "T").is_err(), "a non-id is refused");
        assert!(bypass(&home, "m", "r", &[(c.clone(), "/elsewhere.py".into())], "T").is_err(),
                "a gate the config does not spell is refused, and nothing changes");
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), CODEX);
        bypass(&home, "m", "r", &t, "T").unwrap();
        let e = bypass(&home, "m", "r", &t, "T").unwrap_err().to_string();
        assert!(e.contains("already bypassed"), "{e}");
        // Someone re-registers the gate by hand meanwhile: restore must refuse, not guess.
        std::fs::write(&cfg, CODEX).unwrap();
        let e = restore(&home, "m").unwrap_err().to_string();
        assert!(e.contains("no longer registers the bypass stub"), "{e}");
        assert!(restore(&home, "nobody").is_err());
    }

    #[test]
    fn undo_puts_everything_back() {
        let (_d, home, cfg) = setup(KIMI, "kimi.toml");
        let c = cfg.display().to_string();
        let rec = bypass(&home, "m", "r", &[(c, "/g/hooks/pre_tool_use.py".into())], "T").unwrap();
        undo_bypass(&home, &rec).unwrap();
        assert_eq!(std::fs::read_to_string(&cfg).unwrap(), KIMI);
        assert!(active(&home, "m").is_none());
        // and a restore that could not be witnessed goes back to bypassed
        let rec = bypass(&home, "m", "r", &rec.swaps.iter().map(|s| (s.config.clone(), s.original.clone())).collect::<Vec<_>>(), "T").unwrap();
        let restored = restore(&home, "m").unwrap();
        undo_restore(&home, &restored).unwrap();
        assert!(std::fs::read_to_string(&rec.swaps[0].config).unwrap().contains(&rec.stub));
        assert!(active(&home, "m").is_some());
    }

    #[test]
    fn a_config_keeps_its_mode() {
        use std::os::unix::fs::PermissionsExt;
        let (_d, home, cfg) = setup(CODEX, "config.toml");
        std::fs::set_permissions(&cfg, std::fs::Permissions::from_mode(0o600)).unwrap();
        bypass(&home, "m", "r", &[(cfg.display().to_string(), "/g/hooks/pre_tool_use.py".into())], "T").unwrap();
        assert_eq!(std::fs::metadata(&cfg).unwrap().permissions().mode() & 0o777, 0o600);
    }

    #[test]
    fn targets_come_from_the_inventory_gate_rows_only() {
        let inv = serde_json::json!({"status":"GAP","detail":[{"member":"kimi-code","hook_targets":[
            {"path":"/k/pre_tool_use.py","config":"/k/config.toml","is_gate":true,"owned_by_hestia":true},
            {"path":"/k/witness.py","config":"/k/config.toml","is_gate":false,"owned_by_hestia":true},
            {"path":"/snarc/pre.js","config":"/k/config.toml","is_gate":true,"owned_by_hestia":false}]}]});
        assert_eq!(gate_targets(&inv, "kimi-code").unwrap(),
                   vec![("/k/config.toml".to_string(), "/k/pre_tool_use.py".to_string())]);
        assert!(gate_targets(&inv, "codex").is_err());
        assert!(gate_targets(&serde_json::json!({"status":"UNKNOWN","reason":"x"}), "kimi-code").is_err());
    }
}
