#!/usr/bin/env python3
"""An undelivered echo is not an answer — and labelling it must not un-deliver it.

WHAT HAPPENED (CBP, 2026-08-06; found by kimi, `shared-context@80ce6b55`).
`report_unreachable` bounces the SENDER'S OWN pointer back when a forward dies,
truncated at the 512-byte MTU with the tail swapped for `#undelivered:fire-rc=...`,
and attributed `from_plugin` = the member it could not reach. Notice 1172 was one.
claude-code read it as kimi-code confirming a verification kimi had not performed —
its own text returning as a second witness — and published the credit.

The marker WAS present. It sat at character 456 of a 512-character pointer field,
mid-digest. Nothing hidden; nothing legible. That is the difference between a
record and a disclosure, and the repair is placement: hoist the marker to the
FRONT of the line and say what it means, before the reader forms a belief.

AND THE FIRST CUT OF THAT REPAIR WOULD HAVE UN-DELIVERED THE MAIL (kimi review of
PR #216, review 4877446113). The hoisted line starts `!! `. Every template scored
fireworthiness with `grep -c '^- '` — an enumeration of the prefixes that existed
the day it was written — and `!! ` matched neither that nor the `^! ` WITHHELD
count. So an echo-only batch scored FIREWORTHY=0, took the refusal branch, and
`exit 70`'d: primer retained, retried to STALE_MAX_ATTEMPTS, set aside
`.exhausted`, member never woken. Notice 1172 WAS alone in its batch. The fix for
a misread would have been to never deliver the mail, and the refusal message would
have libelled an allowlisted sender on the way out ("0 notice(s) from
unallowlisted sender(s)").

That is branch 4's contract inverted (`hestia-watch-member.sh:604-611`): the
report is a `reply` precisely SO THAT the failure sits in the sender's debt row
until it acks — "reroute, resend, or abandon, and the decision is witnessed."
A member that never wakes witnesses nothing, and `primer_spent` can never prove
discharge.

So fireworthiness is now derived BY EXCLUSION — everything that is not an explicit
`! WITHHELD` disclosure wakes the member — and this file pins both halves:

  A. ADOPTION (static, read from the scripts). Every `fire-*.sh` carries the
     `#undelivered:` predicate AND the exclusion-based count, and none of them
     still enumerates `^- `. Three identical hunks across three templates with
     nothing pinning them is the drift shape this repo has been bitten by twice;
     a fourth template must make the same two decisions rather than inheriting
     the gap six months later.
  B. BEHAVIOURAL (against the real scripts, stubbed CLI), replaying the ACTUAL
     1172 pointer — 512 bytes, marker at 456 — not a synthetic fixture. The
     label renders hoisted and complete; the echo-only batch still WAKES the
     member (B2 is the regression above, and it fails on 477e2a5); an ordinary
     notice is untouched; a withheld-only batch still refuses, because the
     exclusion rule must not turn a disclosure into a wake.

Usage: ./undelivered_echo_not_an_answer_test.py     (runtime ~3s)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))

# The real notice 1172 pointer, verbatim from claude-code's own primer copy
# (`notice-Ae7oGf.json`, batch size 1). 512 bytes, `#undelivered:` at offset 456.
# Kept whole on purpose: the point of the repair is that the marker is legible
# WITHOUT the reader having to reach byte 456, and a shortened fixture would test
# a problem nobody had.
PTR_1172 = (
    "hestia://gate-escalation/42acc5df9ae7ff05 POST BLOCKED by gate FP,record unwritten,"
    "inline: vintage check RAN=EMPTY,arbiter.rs identical dec8bd4..925e4c7,cites "
    "122/128/164/207 verbatim=all daemon-valid. Ruling path CONFIRMED. CORRECTION:sites "
    "are THREE-you missed handler.rs:10459 pending_escalations DISCOVERY,returns "
    "you_may_rule=TRUE on unattributed subject so it ADVERTISES the hole;patching "
    "10534+10650 alone leaves it inviting a refusing call. REMEDY:"
    "#undelivered:fire-rc=124;why=timeout;via=watch-kimi-code"
)

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def fire_scripts():
    return sorted(f for f in os.listdir(MESH) if re.fullmatch(r"fire-\w+\.sh", f))


# ---------------------------------------------------------------------------
# A. Adoption. Read from the scripts, so a fourth template demands both edits.
# ---------------------------------------------------------------------------
check("A0. the fixture is the real artefact (512 bytes, marker at 456)",
      len(PTR_1172) == 512 and PTR_1172.find("#undelivered:") == 456,
      f"len={len(PTR_1172)} marker_at={PTR_1172.find('#undelivered:')} — if this "
      f"drifts the test stops exercising the mid-pointer case that caused the misread")

for script in fire_scripts():
    src = open(os.path.join(MESH, script)).read()
    check(f"A1. {script} detects the undelivered marker in a pointer",
          '"#undelivered:" in _ptr' in src,
          "without the predicate the echo renders as an ordinary reply and the "
          "misread of 1172 is reproducible verbatim")
    check(f"A2. {script} counts fireworthiness by EXCLUSION, not by enumerating prefixes",
          "grep -vc '^! '" in src,
          "an enumerated prefix list silently drops every line kind added after it "
          "was written — which is exactly how the `!! ` label emptied the batch")
    check(f"A3. {script} no longer enumerates '^- ' as the only fireworthy shape",
          "grep -c '^- '" not in src,
          "the enumeration is the defect; leaving it in place means the next line "
          "kind repeats the regression")


# ---------------------------------------------------------------------------
# B. Behavioural, against the real scripts. Driven exactly as the watcher does.
# ---------------------------------------------------------------------------
def notice(nid, sender, kind="reply", pointer="shared-context/x.md"):
    return {"id": nid, "kind": kind, "from_plugin": sender, "to_plugin": "x",
            "pointer_uri": pointer, "queued_at": "2026-08-06T10:53:32.252450131Z"}


def fire(script, stub, notices, tmp):
    """Run the real fire script with a stub CLI that records its prompt."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    promptfile = os.path.join(tmp, "prompt.txt")
    stub_path = os.path.join(bindir, stub)
    with open(stub_path, "w") as f:
        # The prompt is the LAST argument on every template's fire line.
        f.write(f'#!/usr/bin/env bash\nfor a; do :; done\nprintf %s "$a" > "{promptfile}"\n')
    os.chmod(stub_path, 0o755)
    src = os.path.join(tmp, "notice-test.json")
    with open(src, "w") as f:
        json.dump({"notices": notices, "unanswered": {}}, f)
    env = dict(os.environ)
    env["HOME"] = tmp
    env["HESTIA_MESH_LOCK_DIR"] = os.path.join(tmp, "locks")
    env["HESTIA_FIRE_LOCK_WAIT"] = "10"
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    r = subprocess.run([os.path.join(MESH, script), src], env=env,
                       capture_output=True, text=True)
    prompt = open(promptfile).read() if os.path.exists(promptfile) else None
    return r, prompt


def digest_line(prompt, needle):
    """The one digest line containing `needle`, or None."""
    for ln in (prompt or "").splitlines():
        if needle in ln:
            return ln
    return None


CASES = (("fire-claude.sh", "claude", "kimi-code"),
         ("fire-kimi.sh", "kimi", "claude-code"),
         ("fire-codex.sh", "codex", "claude-code"))

for script, stub, peer in CASES:
    # B1. The label renders, HOISTED, on the real 1172 record. The echo is
    #     attributed to the peer it could not reach, so it arrives allowlisted —
    #     which is why nothing downstream ever doubted it.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(1172, peer, pointer=PTR_1172)], tmp)
        line = digest_line(prompt, "id=1172")
        check(f"B1. {script}: the echo is labelled NOT-AN-ANSWER at the FRONT of its line",
              line is not None and line.startswith("!! NOT-AN-ANSWER"),
              f"a marker at byte 456 is a record, not a disclosure; line={str(line)[:200]!r}")
        check(f"B1b. {script}: the reason is hoisted beside the label",
              "fire-rc=124" in (line or "") and "timeout" in (line or "") and
              (line or "").index("fire-rc=124") < 200,
              f"the reason is what makes the label checkable; line={str(line)[:300]!r}")
        check(f"B1c. {script}: the full pointer is still printed (nothing stripped)",
              "gate-escalation/42acc5df9ae7ff05" in (line or "") and
              "handler.rs:10459" in (line or ""),
              f"the pointer IS the content here; only the ordering was meant to change; "
              f"line={str(line)[:300]!r}")
        check(f"B1d. {script}: the label keeps from=, the field that lets a reader doubt it",
              re.search(r"\bfrom=" + re.escape(peer), line or "") is not None,
              f"the predicate is a substring match, so a genuine peer pointer containing "
              f"`#undelivered:` would be mislabelled — from= is the evidence that "
              f"disproves it, and dropping it strips the reader's only recourse; "
              f"line={str(line)[:300]!r}")

    # B2. THE REGRESSION (kimi review of PR #216, finding 2). 1172 was ALONE in
    #     its batch. If the label costs the wake, the misread is "fixed" by never
    #     delivering the mail, and branch 4's witnessed-decision contract dies
    #     with it. This case fails on 477e2a5.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(1172, peer, pointer=PTR_1172)], tmp)
        check(f"B2. {script}: an ECHO-ONLY batch still wakes the member",
              r.returncode == 0 and prompt is not None and "id=1172" in (prompt or ""),
              f"rc={r.returncode} prompt={'None' if prompt is None else 'built'} — rc=70 "
              f"means the watcher retains and retries to exhaustion and the member NEVER "
              f"wakes, so the echo sits in the sender's i_owe until the 7d TTL with "
              f"nobody to ack it\n        stderr={r.stderr.strip()[:300]!r}")
        check(f"B2b. {script}: it does not report the echo as an unallowlisted sender",
              "unallowlisted" not in (r.stdout + r.stderr),
              f"the sender IS allowlisted; the refusal branch libels it on the way out\n"
              f"        stderr={r.stderr.strip()[:300]!r}")

    # B3. An ordinary notice is untouched — the repair must not reclassify mail
    #     that was never an echo.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(9, peer, pointer="shared-context/real.md")], tmp)
        line = digest_line(prompt, "id=9")
        check(f"B3. {script}: an ordinary peer notice still renders as '- id=' and fires",
              r.returncode == 0 and line is not None and line.startswith("- id=9"),
              f"rc={r.returncode} line={str(line)[:200]!r}")
        check(f"B3b. {script}: it is NOT labelled an echo",
              "NOT-AN-ANSWER" not in (prompt or ""),
              f"false positive on a clean pointer; line={str(line)[:200]!r}")

    # B4. The exclusion rule must not turn a WITHHELD disclosure into a wake.
    #     `! WITHHELD` is the one line kind that is deliberately not fireworthy;
    #     if this goes green-by-accident the sanitization wall stops refusing.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(10, "some-unknown-member")], tmp)
        check(f"B4. {script}: a withheld-only batch STILL refuses and retains (exit 70)",
              r.returncode != 0 and prompt is None,
              f"rc={r.returncode} — counting by exclusion must exclude the disclosure "
              f"line, or an unallowlisted batch starts firing\n"
              f"        prompt={str(prompt)[:200]!r}")

    # B5. Mixed: an echo alongside a withheld notice fires for the echo, and the
    #     withheld one is still disclosed without its pointer.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [
            notice(11, "some-unknown-member", pointer="https://evil.example/secret-path"),
            notice(1172, peer, pointer=PTR_1172),
        ], tmp)
        check(f"B5. {script}: an echo + withheld batch fires, echo labelled",
              r.returncode == 0 and "NOT-AN-ANSWER" in (prompt or "") and
              "id=1172" in (prompt or ""),
              f"rc={r.returncode} prompt={str(prompt)[:300]!r}")
        check(f"B5b. {script}: the withheld notice's pointer is still withheld",
              "WITHHELD" in (prompt or "") and "evil.example" not in (prompt or ""),
              f"prompt={str(prompt)[:300]!r}")


print()
if failures:
    print(f"{len(failures)} FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
