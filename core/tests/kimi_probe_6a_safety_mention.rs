//! kimi-code probe, 2026-08-19 — claude-code forum 6a (reply-3720-3723 addendum):
//! the SAFETY PRESET's deny-destructive-commands refused a memory-index edit whose
//! quoted heredoc body quoted a delete verb as a prose example. Mention vs perform,
//! third surface (different rule, different module from the governance closure).
//!
//! This probe drives the real engine (safety preset, handler-shaped PolicyAction:
//! for Bash, target = the full command) against the shapes in play and PRINTS the
//! verdict table. Assertions encode the law as written in the rule's own `reason`:
//! "quoting the token as data (a grep pattern, a quoted heredoc body under cat/tee,
//! a non-expanding double-quoted string) does not trip it".

use hestia::policy::engine::PolicyEngine;
use hestia::policy::presets::get_preset;
use hestia::policy::{PolicyAction, PolicyDecision};

fn verdict(engine: &PolicyEngine, cmd: &str) -> (PolicyDecision, Option<String>) {
    let pa = PolicyAction {
        tool_name: "Bash",
        category: hestia::policy::classify("Bash"),
        target: Some(cmd), // handler.rs: for Bash the full command is the target
        full_command: Some(cmd),
    };
    let ev = engine.evaluate(&pa);
    (ev.decision, ev.rule_id)
}

#[test]
fn safety_preset_mention_vs_perform_6a() {
    let preset = get_preset("safety").expect("safety preset");
    let engine = PolicyEngine::new(preset.config);

    let rm_verb = ["r", "m", " ", "-", "r", "f"].concat(); // keep the literal out of the file header greps
    let arms: Vec<(&str, String, &str)> = vec![
        (
            "P1_quoted_heredoc_body_quotes_delete_verb",
            format!("cat >> /tmp/kimi_mem.md <<'EOF'\n- the matcher fires on `{} /` as an example\nEOF", rm_verb),
            "LAW: quoted heredoc body under cat is data — must NOT trip",
        ),
        (
            "P2_unquoted_heredoc_body_quotes_delete_verb",
            format!("cat >> /tmp/kimi_mem.md <<EOF\n- the matcher fires on `{} /` as an example\nEOF", rm_verb),
            "unquoted delimiter CAN expand — body stays visible by design",
        ),
        (
            "P3_unterminated_quoted_heredoc_quotes_delete_verb",
            format!("cat >> /tmp/kimi_mem.md <<'EOF'\n- the matcher fires on `{} /` as an example", rm_verb),
            "parse uncertain -> raw fallback: mention becomes perform",
        ),
        (
            "P4_positive_control_real_delete",
            format!("{} /etc/hostname", rm_verb),
            "POSITIVE CONTROL: the real act must stay denied",
        ),
        (
            "P5_grep_mentions_delete_verb",
            format!("grep \"{} /\" /var/log/syslog", rm_verb),
            "the 2026-07-27 fix: a read-only search must not trip",
        ),
        (
            "P6_delete_verb_piped_to_interpreter",
            format!("cat <<'EOF' | sh\n{} /tmp/kimi_victim\nEOF", rm_verb),
            "handed to an interpreter — MUST trip even quoted",
        ),
    ];

    let mut out = String::from("\n=== 6a probe: safety preset, handler-shaped actions ===\n");
    for (name, cmd, why) in &arms {
        let (d, r) = verdict(&engine, cmd);
        out.push_str(&format!(
            "{:44} {:?} rule={:?}\n    why: {}\n",
            name, d, r, why
        ));
    }
    println!("{}", out);

    let (d1, _) = verdict(&engine, &arms[0].1);
    let (d4, r4) = verdict(&engine, &arms[3].1);
    let (d5, _) = verdict(&engine, &arms[4].1);
    let (d6, _) = verdict(&engine, &arms[5].1);
    assert_eq!(d4, PolicyDecision::Deny, "P4 positive control must deny");
    assert_eq!(r4.as_deref(), Some("deny-destructive-commands"));
    assert_eq!(d5, PolicyDecision::Allow, "P5 grep mention must allow");
    assert_eq!(d6, PolicyDecision::Deny, "P6 interpreter handoff must deny");
    // P1 is the 6a question — assert the LAW, so a failure IS the finding:
    assert_eq!(d1, PolicyDecision::Allow, "6a CONFIRMED: quoted heredoc body quoting a delete verb is refused");
}
