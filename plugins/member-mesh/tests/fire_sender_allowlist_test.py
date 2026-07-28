#!/usr/bin/env python3
"""A filtered notice must never be indistinguishable from no notice.

WHAT HAPPENED (CBP, 2026-07-27). `fire-claude.sh` and `fire-kimi.sh` both carried
`codex-cli` in their sender allowlist. That is the id Codex's *gate* witnesses
under. Codex's mesh sends carry `codex` — every Codex notice on every primer on
this machine did. So both templates dropped 100% of Codex's mail, and the drop
produced an empty digest, which `exit 0`'d as "ack-only/unknown-sender batch",
which `hestia-watch-member.sh:153` read as success and deleted the consume-once
primer.

Notice 160 — Codex reporting that its own fire had failed, `fire-rc=1` — was
destroyed that way at 11:23:16Z. The mesh's report that a member could not be
woken was itself unwakeable, and it survives only because `fire-*.sh` copies the
primer to the member's home BEFORE the filter runs.

Nothing could catch this, because the whole failure is that a drop looks like an
absence. So the tests here assert the two properties that make it visible:

  A. MUTUAL REACHABILITY (static). Every member this fleet fires must appear in
     every OTHER member's allowlist. Derived from the scripts themselves — the
     member id each one passes to `with-member-lock.sh` — so adding a fourth
     template makes this test demand the six edits it implies, rather than
     failing silently on the wire six months later.
  B. A DROP IS ANNOUNCED, AND AN EMPTY BATCH IS NOT A SUCCESS (behavioural,
     against the real scripts with a stubbed CLI). Withheld notices are named in
     the prompt without their pointer; a batch left with nothing fireworthy
     exits non-zero so the primer is retained. `ack`-only still exits 0 — an ack
     is terminal and nothing is owed, and conflating THAT with an unknown-sender
     batch under one exit code is precisely the bug.

AND THEN THE SAME CLASS ARRIVED THROUGH THE ONE DOOR THIS TEST COULD NOT SEE (Kimi
review of PR #62, 2026-07-27, the day after the above). Property A is derived from the
fire templates, so it can only ever see senders that HAVE a fire template. The daemon
has none. Its `unreachable` report — "your forward to this peer was retired unsent" —
is enqueued `from_plugin: "hestia"`, which no template allowlisted, so it was withheld
on every rendering path; and because its pointer carries which peer, how many attempts
and why, withholding the pointer withheld the whole report. Alone in a batch it hit the
`exit 70` above and the member was not woken at all. The limit this file already
declared — "a member that sends but has no template here is still invisible to it" —
came true in one day.

The repair is NOT to make the daemon a pseudo-member of property A. That would assert
`"hestia" in ALLOW`, and the bare name is the one thing that must not open the wall:
`plugin_id` is caller-supplied at `hestia_connect` and validated only against `/`
(handler.rs), so `hestia` is a claimable id, and unlike every peer name here it is one
no real member occupies — a squatter on it would be noticed by nobody. What cannot be
forged is the KIND: `unreachable` is deliberately absent from `MEMBER_NOTICE_KINDS`, so
`tool_member_notify` refuses it, and the one other path that mints a notice under a
caller-supplied name (the appeal dispatch) hardcodes `review_request`. So:

  A4/A5. Every template admits the daemon as the PAIR ("hestia", "unreachable"), and
     none allowlists the bare name. Read from the scripts, so a fourth template must
     make the same decision rather than inheriting the gap.
  B4/B5. Behavioural, and deliberately at the layer PR #62's own acceptance test
     stopped short of: that test asserted the report reached `drain_member` — the
     store — which was never the wall. B4 fires a daemon report ALONE and demands the
     member is woken with the pointer intact; B5 sends `reply` under the name `hestia`
     and demands it is still withheld.

Usage: ./fire_sender_allowlist_test.py     (runtime ~2s)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def fire_scripts():
    return sorted(f for f in os.listdir(MESH) if re.fullmatch(r"fire-\w+\.sh", f))


def parse(script):
    """(member_id, allow_set) read out of the script, not out of a fixture.

    The member id is the one it hands `with-member-lock.sh` — the same string the
    daemon knows it by, so the two halves of the invariant are read from the same
    place the runtime reads them.
    """
    src = open(os.path.join(MESH, script)).read()
    me = re.search(r"with-member-lock\.sh\"?\s+([A-Za-z0-9_-]+)", src)
    allow = re.search(r"^ALLOW=\{([^}]*)\}", src, re.M)
    return (me.group(1) if me else None,
            set(re.findall(r'"([^"]+)"', allow.group(1))) if allow else None)


def daemon_pairs(script):
    """The (sender, kind) pairs a template admits for the daemon, read from the script."""
    src = open(os.path.join(MESH, script)).read()
    m = re.search(r"^DAEMON=\{(.*?)\}\s*$", src, re.M | re.S)
    return set(re.findall(r'\("([^"]+)"\s*,\s*"([^"]+)"\)', m.group(1))) if m else set()


# ---------------------------------------------------------------------------
# A. Mutual reachability. The invariant that was false on the wire for a day.
# ---------------------------------------------------------------------------
members = {}
for script in fire_scripts():
    me, allow = parse(script)
    check(f"A0. {script}: declares a member id and an ALLOW set",
          me is not None and allow is not None, f"me={me!r} allow={allow!r}")
    if me and allow is not None:
        members[me] = (script, allow)

check("A1. more than one member is defined (otherwise A2 is vacuous)",
      len(members) > 1, f"members={sorted(members)}")

for me, (script, allow) in sorted(members.items()):
    for peer in sorted(members):
        if peer == me:
            continue
        check(f"A2. {script} accepts notices from '{peer}'",
              peer in allow,
              f"'{peer}' fires as a member on this fleet but {script}'s ALLOW is "
              f"{sorted(allow)} — its mail would be filtered to an empty digest, "
              f"which is what destroyed notice 160")
    check(f"A3. {script} does not allowlist itself (a member cannot notify itself)",
          me not in allow, f"ALLOW={sorted(allow)}")

# ---------------------------------------------------------------------------
# A4/A5. The daemon is NOT a pseudo-member (see the module docstring).
# ---------------------------------------------------------------------------
for script in fire_scripts():
    check(f"A4. {script} admits the daemon's unreachable report as a (sender, kind) pair",
          ("hestia", "unreachable") in daemon_pairs(script),
          f"DAEMON={sorted(daemon_pairs(script))} — the daemon's report that a member's "
          f"packet died is the one notice its recipient cannot learn any other way, and "
          f"its pointer IS its content; without this pair it is WITHHELD, and when it is "
          f"the only notice in the batch the member is not woken at all")
    _, allow = parse(script)
    check(f"A5. {script} does not allowlist the bare name 'hestia'",
          allow is not None and "hestia" not in allow,
          f"ALLOW={sorted(allow or [])} — plugin_id is caller-supplied at hestia_connect "
          f"and validated only against '/', so 'hestia' is a claimable id that no real "
          f"member occupies. Admitting the NAME renders an impostor's pointers; admitting "
          f"the PAIR renders only what no member-reachable surface can mint")


# ---------------------------------------------------------------------------
# B. Behavioural, against the real scripts. No test seam: the fires are driven
#    exactly as hestia-watch-member.sh drives them.
# ---------------------------------------------------------------------------
def notice(nid, sender, kind="reply", pointer="shared-context/x.md"):
    return {"id": nid, "kind": kind, "from_plugin": sender, "to_plugin": "x",
            "pointer_uri": pointer, "queued_at": "2026-07-27T00:00:00Z"}


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


CASES = (("fire-claude.sh", "claude", "kimi-code"),
         ("fire-kimi.sh", "kimi", "claude-code"),
         ("fire-codex.sh", "codex", "claude-code"))

for script, stub, peer in CASES:
    # B1. A batch of ONLY unallowlisted mail must not report success — that is
    #     the exact rc the watcher uses to delete the primer.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(1, "some-unknown-member")], tmp)
        check(f"B1. {script}: an all-unknown-sender batch exits non-zero (primer retained)",
              r.returncode != 0,
              f"rc={r.returncode} — the watcher would delete the only copy of the notice\n"
              f"        stdout={r.stdout.strip()!r} stderr={r.stderr.strip()!r}")
        check(f"B1b. {script}: the refusal names the dropped sender",
              "some-unknown-member" in (r.stdout + r.stderr),
              f"stdout={r.stdout.strip()!r} stderr={r.stderr.strip()!r}")
        check(f"B1c. {script}: it did not fire the CLI on mail it refused to show",
              prompt is None, f"prompt was built anyway: {str(prompt)[:200]!r}")

    # B2. A MIXED batch still fires — refusing it would strand the legitimate
    #     notice — and the withheld one is named without its pointer.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [
            notice(2, "some-unknown-member", pointer="https://evil.example/secret-path"),
            notice(3, peer, pointer="shared-context/real.md"),
        ], tmp)
        check(f"B2. {script}: a mixed batch still fires for the allowlisted notice",
              prompt is not None and "id=3" in (prompt or ""),
              f"rc={r.returncode} prompt={str(prompt)[:300]!r}")
        check(f"B2b. {script}: the withheld notice is DISCLOSED in the prompt",
              "WITHHELD" in (prompt or "") and "id=2" in (prompt or ""),
              f"a silent drop is the bug; prompt={str(prompt)[:300]!r}")
        check(f"B2c. {script}: the withheld notice's POINTER is still withheld",
              "evil.example" not in (prompt or ""),
              f"sanitization regressed; prompt={str(prompt)[:300]!r}")

    # B3. ack-only is genuinely nothing-owed and must stay a clean exit 0. If
    #     this goes red the fix has over-reached into a retry loop.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [notice(4, peer, kind="ack")], tmp)
        check(f"B3. {script}: an ack-only batch still exits 0 without firing",
              r.returncode == 0 and prompt is None,
              f"rc={r.returncode} prompt={str(prompt)[:200]!r}")

    # B4. THE RENDERED PATH, which is where PR #62's acceptance test stopped. That
    #     test asserted delivery to the STORE (`drain_member`), and the store was
    #     never the wall — this is. A daemon report ALONE must wake the member with
    #     its pointer intact: the pointer names the peer, the attempt count and the
    #     reason, so a withheld pointer withholds the entire report.
    with tempfile.TemporaryDirectory() as tmp:
        ptr = "hestia://egress/77#unreachable:thor/claude-code after 5 attempts: hub-notify rc=1"
        r, prompt = fire(script, stub,
                         [notice(5, "hestia", kind="unreachable", pointer=ptr)], tmp)
        check(f"B4. {script}: the daemon's unreachable report alone WAKES the member",
              prompt is not None and "id=5" in (prompt or ""),
              f"rc={r.returncode} — rc=70 means the sender was never told its packet "
              f"died; prompt={str(prompt)[:300]!r}")
        check(f"B4b. {script}: the report's pointer survives (it is the whole content)",
              "thor" in (prompt or "") and "5 attempts" in (prompt or ""),
              f"pointer stripped — which peer/how many/why is exactly what is lost; "
              f"prompt={str(prompt)[:300]!r}")

    # B5. The other half of the pair rule. An impostor CAN hold the name — plugin_id
    #     is caller-supplied — so the name alone must never open the wall.
    with tempfile.TemporaryDirectory() as tmp:
        r, prompt = fire(script, stub, [
            notice(6, "hestia", kind="reply", pointer="https://evil.example/secret-path"),
            notice(7, peer, pointer="shared-context/real.md"),
        ], tmp)
        check(f"B5. {script}: a non-daemon kind from 'hestia' is still WITHHELD",
              "WITHHELD" in (prompt or "") and "id=6" in (prompt or ""),
              f"the name was admitted instead of the pair; prompt={str(prompt)[:300]!r}")
        check(f"B5b. {script}: the impostor's pointer never reaches the prompt",
              "evil.example" not in (prompt or ""),
              f"prompt={str(prompt)[:300]!r}")


print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
