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


print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
