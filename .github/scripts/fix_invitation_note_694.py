from pathlib import Path

p = Path("core/src/server/handler.rs")
s = p.read_text()
old = '''        "invitation_note": match (esc.bar, asker_is_proven, invited.is_empty()) {
            (Bar::SingleApprover, _, _) =>
                "this bar names no peer conjunct — no invitation was issued, and none was due",
            (Bar::SovereignPlusPeer, false, _) =>
                "NOBODY WAS WOKEN, and not because the registry is empty. This ask arrived \\
                 without a session_id, so its asker is a string this daemon never verified, \\
                 and waking peers in that name would be an outward message sent on behalf of \\
                 an identity nobody proved (#128). The peers who WOULD have been asked are \\
                 recorded under `invitation_withheld`. Re-open with your session_id from \\
                 hestia_connect to actually invite them; the sovereign can decide either way",
            (Bar::SovereignPlusPeer, true, true) =>
                "this bar invites a peer and this box knows no admissible one to ask. The \\
                 sovereign may still decide (#226: the two-bar invites, it does not block) — \\
                 the record will say the peer half was never asked, not that it declined",
            (Bar::SovereignPlusPeer, true, false) =>
                "peers were invited and woken. Their participation is EVIDENCE, never a veto: \\
                 a sovereign decision stands whether they concur, dissent, or never look",
        },'''
new = '        "invitation_note": invitation_note(asker_is_proven, invited.is_empty()),'
anchor = '''/// `hestia_request_scope` — a member asks the operator to reach ONE path outside its MRH.\n'''
helper = r'''/// Explain the invitation outcome from the facts that actually control it.
///
/// Both bars invite admissible peers. Attribution determines whether an invitation is withheld;
/// an empty invitation after a proven ask means there was nobody admissible to wake.
fn invitation_note(asker_is_proven: bool, invited_is_empty: bool) -> &'static str {
    match (asker_is_proven, invited_is_empty) {
        (false, _) =>
            "NOBODY WAS WOKEN, and not because the registry is empty. This ask arrived \
             without a proven session_id, so its asker is a string this daemon never verified, \
             and waking peers in that name would be an outward message sent on behalf of an \
             identity nobody proved (#128). The peers who WOULD have been asked are recorded \
             under `invitation_withheld`. Re-open with your session_id from hestia_connect to \
             actually invite them; the sovereign can decide either way",
        (true, true) =>
            "this ask was attributed, but this box knows no admissible peer to invite. The \
             sovereign may still decide (#226: participation is invited, never a blocker) — \
             the record says nobody was asked, not that a peer declined",
        (true, false) =>
            "peers were invited and woken. Their participation is EVIDENCE, never a veto: a \
             sovereign decision stands whether they concur, dissent, or never look",
    }
}

#[cfg(test)]
mod invitation_note_contract_tests {
    use super::invitation_note;

    #[test]
    fn unattributed_ask_names_identity_as_cause_and_remedy() {
        for invited_is_empty in [true, false] {
            let note = invitation_note(false, invited_is_empty);
            assert!(note.contains("NOBODY WAS WOKEN"), "{note}");
            assert!(note.contains("session_id"), "{note}");
            assert!(note.contains("hestia_connect"), "{note}");
            assert!(!note.contains("bar names no peer"), "{note}");
        }
    }

    #[test]
    fn attributed_ask_reports_invitation_reality() {
        let none = invitation_note(true, true);
        assert!(none.contains("no admissible peer"), "{none}");
        assert!(!none.contains("peer declined"), "{none}");
        let sent = invitation_note(true, false);
        assert!(sent.contains("peers were invited and woken"), "{sent}");
        assert!(sent.contains("EVIDENCE, never a veto"), "{sent}");
    }
}

'''

if s.count(old) == 1:
    s = s.replace(old, new)
    if s.count(anchor) != 1:
        raise SystemExit(f"expected request-scope anchor once, found {s.count(anchor)}")
    s = s.replace(anchor, helper + anchor)
    p.write_text(s)
elif s.count(new) == 1 and "fn invitation_note(" in s:
    print("source already patched")
else:
    raise SystemExit("invitation-note source is neither the known old nor patched shape")
