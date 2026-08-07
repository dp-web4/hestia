#!/usr/bin/env python3
"""Tests for the gate's self-protection matcher.

The claim under test is not "the matcher matches things" — it is the sentence the
feature was written to make true:

    an agent cannot cheaply and silently stop the gate from governing it.

That sentence has TWO surfaces and the first cut only covered one. `_touches_self`
protects the gate's CODE. `_touches_registration` protects the gate's
INSTALLATION — the `hooks` stanza in `~/.claude/settings.json` that is the reason
this file runs at all. A gate that guards its implementation and not its
registration is `gate installed != gate enforced` aimed at itself, and the
registration path is the CHEAPER of the two: it needs no knowledge of what the
matcher looks for.

The registration cases below were confirmed FAILING against 99d122f — the commit
that shipped the code-protection — before `_touches_registration` existed. A test
that has never failed cannot tell a repair from a dead gauge.

Run: python3 test_pre_tool_use_self.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pre_tool_use as G  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILS.append(name)


def denied(tool, inp):
    return bool(G._touches_self(tool, inp) or G._touches_registration(tool, inp))


# --- a settings file that actually registers the gate, so the fixture is not a straw man
TMP = tempfile.mkdtemp(prefix="gate-self-test-")
os.makedirs(os.path.join(TMP, ".claude"), exist_ok=True)
SETTINGS = os.path.join(TMP, ".claude", "settings.json")
LIVE = {
    "model": "opus",
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "python3 /h/pre_tool_use.py"}]}
        ],
        "PostToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "python3 /h/witness.py"}]}
        ],
    },
}
with open(SETTINGS, "w", encoding="utf-8") as fh:
    json.dump(LIVE, fh)

print("code surface — the gate's own implementation")

check(
    "editing the gate itself is refused",
    denied("Edit", {"file_path": G._SELF, "new_string": "return 0"}),
)
check(
    "reading the gate is refused too (blind-probing is the point)",
    denied("Read", {"file_path": G._SELF}),
)
check(
    "a shell rewrite of the gate is refused wherever the path appears",
    denied("Bash", {"command": "sed -i 's/return 2/return 0/' plugins/claude-code/hooks/pre_tool_use.py"}),
)
check(
    "the WITNESS is governance surface too — disarming it produces silence, not denials",
    denied("Edit", {"file_path": "/home/x/.claude/hooks/hestia/witness.py", "new_string": "pass"}),
)
check(
    "a peer's gate is not a lesser target",
    denied("Write", {"file_path": "/home/other/.claude/hooks/hestia/society_pre_tool_use.py", "content": "x"}),
)

print("registration surface — the reason the gate runs at all")

check(
    "clearing settings.json wholesale is refused (RED before _touches_registration)",
    denied("Write", {"file_path": SETTINGS, "content": "{}"}),
)
check(
    "dropping only the hooks stanza is refused (RED before)",
    denied("Write", {"file_path": SETTINGS, "content": json.dumps({k: v for k, v in LIVE.items() if k != "hooks"})}),
)
check(
    "rewriting the stanza to a harmless-looking hook is refused (RED before)",
    denied("Write", {"file_path": SETTINGS, "content": json.dumps({**LIVE, "hooks": {"PreToolUse": []}})}),
)
check(
    "an Edit that names the stanza is refused (RED before)",
    denied("Edit", {"file_path": SETTINGS, "old_string": '"hooks": {', "new_string": '"_hooks": {'}),
)
check(
    "an Edit that names a governance file is refused (RED before)",
    denied("Edit", {"file_path": SETTINGS, "old_string": "python3 /h/witness.py", "new_string": "true"}),
)
check(
    "moving the settings file aside is refused — no `hooks` token anywhere in it (RED before)",
    denied("Bash", {"command": "mv ~/.claude/settings.json ~/.claude/settings.json.bak"}),
)
check(
    "an out-of-band rewrite is refused — heredoc/python -c never says `hooks` in the path (RED before)",
    denied("Bash", {"command": "python3 -c \"import json;p='/home/x/.claude/settings.json';d=json.load(open(p));d.pop('hooks');json.dump(d,open(p,'w'))\""}),
)
check(
    "content the gate cannot parse is refused — it cannot demonstrate preservation",
    denied("Write", {"file_path": SETTINGS, "content": "{not json"}),
)

print("the refusal must stay narrow enough to be livable")

check(
    "a permissions-only edit of the same file is ALLOWED",
    not denied(
        "Write",
        {"file_path": SETTINGS, "content": json.dumps({**LIVE, "permissions": {"allow": ["Bash(ls:*)", "Bash(git:*)"]}})},
    ),
)
check(
    "an Edit elsewhere in settings that never names the stanza is ALLOWED",
    not denied("Edit", {"file_path": SETTINGS, "old_string": '"model": "opus"', "new_string": '"model": "sonnet"'}),
)
check(
    "a settings file with NO hooks has nothing to disarm — ALLOWED",
    not denied("Write", {"file_path": os.path.join(TMP, ".claude", "settings.local.json"), "content": "{}"}),
)
check(
    "ordinary work is untouched",
    not denied("Edit", {"file_path": "/tmp/somewhere/main.rs", "new_string": "fn main() {}"}),
)
check(
    "a file merely NAMED like a hook, outside any hooks dir, is untouched",
    not denied("Edit", {"file_path": "/tmp/docs/witness.py", "new_string": "x"}),
)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)

# --- read allowed + witnessed, write refused (dp/kimi, 2026-07-28) ---
GATE_PATH = "/home/dp/.claude/hooks/hestia/pre_tool_use.py"

for label, tool, ti in [
    ("Read tool", "Read", {"file_path": GATE_PATH}),
    ("cat", "Bash", {"command": f"cat {GATE_PATH}"}),
    ("sha256sum verifies byte-identity", "Bash", {"command": f"sha256sum {GATE_PATH}"}),
    ("git show reads history", "Bash", {"command": f"git show HEAD:{GATE_PATH}"}),
    ("chained read-only heads", "Bash", {"command": f"grep def {GATE_PATH} && wc -l {GATE_PATH}"}),
    # claude-code §5.1 (notice 1471, escalation 10fb8aa5c095c085): hash-object is a
    # read-by-default subcommand the closed _GIT_READ_SUBCOMMANDS set did not name.
    ("git hash-object verifies a blob hash", "Bash", {"command": f"git hash-object {GATE_PATH}"}),
    ("git hash-object --stdin", "Bash", {"command": "git hash-object --stdin"}),
]:
    check(f"READ allowed: {label}", G._is_read_only(tool, ti) is True)

for label, tool, ti in [
    ("Edit tool", "Edit", {"file_path": GATE_PATH}),
    ("sed -i", "Bash", {"command": f"sed -i s/a/b/ {GATE_PATH}"}),
    ("cp over the gate", "Bash", {"command": f"cp /tmp/x {GATE_PATH}"}),
    ("redirect", "Bash", {"command": f"echo x > {GATE_PATH}"}),
    ("append", "Bash", {"command": f"echo x >> {GATE_PATH}"}),
    ("tee", "Bash", {"command": f"echo x | tee {GATE_PATH}"}),
    # a read HEAD with a redirect is a write — the case that makes head-matching alone unsafe
    ("cat piped INTO the gate", "Bash", {"command": f"cat /tmp/x > {GATE_PATH}"}),
    ("git checkout -- overwrites", "Bash", {"command": f"git checkout -- {GATE_PATH}"}),
    # the mutating FLAG on a read-looking subcommand — the case the guard exists for
    ("git hash-object -w writes a blob", "Bash", {"command": f"git hash-object -w {GATE_PATH}"}),
    ("unrecognised head fails closed", "Bash", {"command": f"vim {GATE_PATH}"}),
]:
    check(f"WRITE refused: {label}", G._is_read_only(tool, ti) is False)

print("the heredoc carve-out — the law text a member READS is the code that REFUSES")
# kimi-code, 2026-08-07, claiming claude-code notice 1529 §7. The daemon's destructive
# preset tells the member "a quoted heredoc body under cat/tee does not trip it"
# (presets.rs, backed by policy::shell) — but this hook runs FIRST and matched raw, so a
# report ABOUT the gate written by heredoc was refused by code the quoted law does not
# describe (the FP8 shape through the Bash door). `_blank_inert_heredoc_bodies` blanks
# quoted heredoc bodies — stdin content, the one span that can never name a destination —
# under inert heads only, failing closed on anything it cannot parse. Every case below
# was confirmed against the intent in the daemon's own shell.rs test suite.
GATE = "plugins/claude-code/hooks/pre_tool_use.py"

for label, cmd in [
    ("a heredoc REPORT naming the gate is allowed",
     f"cat > /tmp/report.md <<'EOF'\nthe gate lives at {GATE}\nEOF"),
    ("tee holding the pen is the same shape",
     f"tee /tmp/r.md <<'EOF'\nsee witness.py and hestia_gate_core.py\nEOF"),
    ("a heredoc body piped to an inert consumer is allowed",
     f"cat <<'EOF' | grep hooks\n{GATE}\nEOF"),
    ("an assignment prefix does not confuse head detection",
     f"LC_ALL=C cat > /tmp/r.md <<'EOF'\n{GATE} mention\nEOF"),
    ("the tab-stripping <<- form is honoured",
     f"cat > /tmp/r.md <<-'EOF'\n\t{GATE}\n\tEOF"),
]:
    check(f"ALLOWED: {label}", not denied("Bash", {"command": cmd}))

for label, cmd in [
    # the destination always sits OUTSIDE the body, in executable position
    ("a heredoc INTO the gate is refused (redirect target)",
     f"cat > {GATE} <<'EOF'\nx\nEOF"),
    ("tee onto the gate is refused (argument position)",
     f"tee {GATE} <<'EOF'\nx\nEOF"),
    # quoted argument spans are NOT blanked here — this gate matches paths, and a path
    # can sit at argument position; blanking it would be a one-word evasion
    ("a QUOTED destination stays refused (no quoted-span blanking)",
     f"cat > \"{GATE}\" <<'EOF'\nx\nEOF"),
    # nothing downstream may re-interpret the body
    ("a body piped INTO a shell keeps its teeth",
     f"cat <<'EOF' | sh\ntouch {GATE}\nEOF"),
    # an interpreter head is not on the inert list
    ("python3's heredoc is code, not data",
     f"python3 <<'EOF'\nopen('{GATE}','w')\nEOF"),
    ("sh -c wrapping the heredoc stays refused",
     f"sh -c \"cat <<'EOF'\n{GATE}\nEOF\""),
    # an UNQUOTED delimiter can expand $(...) — not literal, stays visible
    ("an unquoted heredoc delimiter can expand, so stays refused",
     f"cat <<EOF\n{GATE}\nEOF"),
    # fail closed: what the parser cannot read confidently is matched in full
    ("an unterminated heredoc fails closed",
     f"cat <<'EOF'\n{GATE}"),
    ("an unterminated quote fails closed",
     f"cat > /tmp/r.md <<'EOF\n{GATE}\nEOF"),
]:
    check(f"REFUSED: {label}", denied("Bash", {"command": cmd}))

check("the projection preserves length and newlines",
      (lambda c: (lambda p: p is not None and len(p) == len(c)
                  and p.count("\n") == c.count("\n"))(G._blank_inert_heredoc_bodies(c)))(
          f"cat <<'X'\n{GATE}\nX"))
check("an unbalanced $( in executable position fails closed",
      G._blank_inert_heredoc_bodies("echo $(ls /tmp") is None)
check("a trailing backslash fails closed",
      G._blank_inert_heredoc_bodies("echo x\\") is None)

print("git: the one head that is not a decision by itself (mirror of policy::shell's git arm)")
# kimi-code, 2026-08-07 — the python mirror of claude-code's
# claude/git-stdin-is-argv-position (policy::shell `git_stdin_is_data`), landing
# adjudication a96b79c4's remedy on THIS gate's surface: a commit message written
# by heredoc that names a governance path is the FP8 shape through the argv walk.
# Rows ported from the rust suite; here the body names GATE because this gate
# matches paths, not destructive tokens.
check("adding git to the head allowlist would be dead code, so say so",
      "git" not in G._INERT_CONTENT_HEADS)

for label, cmd in [
    ("the commit shape that started this, -c identity flags intact",
     f'git -c user.name="Dennis Palatov" -c user.email="dp@dpcars.net" commit -q -F - <<\'MSG\'\nthe gate lives at {GATE}\nMSG'),
    ("plain commit -F -",
     f"git commit -F - <<'MSG'\n{GATE}\nMSG"),
    ("tag -F -",
     f"git tag -a v1 -F - <<'MSG'\n{GATE}\nMSG"),
    ("--file=-",
     f"git commit --file=- <<'MSG'\n{GATE}\nMSG"),
    # kimi's own cross-seat repro of the mechanism, kept as a row
    ("hash-object --stdin",
     f"git hash-object --stdin <<'MSG'\n{GATE}\nMSG"),
]:
    check(f"ALLOWED: {label}", not denied("Bash", {"command": cmd}))

for label, cmd in [
    # the ruling's caveat as tests: globals that re-point git at code stay visible
    ("-c with an unvetted key keeps the body visible",
     f"git -c core.hooksPath=/tmp/evil commit -F - <<'MSG'\n{GATE}\nMSG"),
    ("--exec-path keeps the body visible",
     f"git --exec-path=/tmp/evil commit -F - <<'MSG'\n{GATE}\nMSG"),
    ("--config-env keeps the body visible",
     f"git --config-env=core.pager=EV commit -F - <<'MSG'\n{GATE}\nMSG"),
    # an alias defined on the command line makes the subcommand arbitrary code
    ("a command-line alias keeps the body visible",
     f"git -c alias.msg='!sh -s' msg <<'MSG'\n{GATE}\nMSG"),
    # nothing declares the body to be message bytes — unknown shape means scanned
    ("commit -m with a heredoc is not vouched for",
     f"git commit -m x <<'MSG'\n{GATE}\nMSG"),
    ("-F naming a FILE is not stdin",
     f"git commit -F /tmp/msg <<'MSG'\n{GATE}\nMSG"),
    ("a subcommand outside the vouched set stays visible",
     f"git bisect run <<'MSG'\n{GATE}\nMSG"),
    # condition 3 holds for the new head exactly as for cat
    ("a vouched git piped INTO a shell keeps its teeth",
     f"git commit -F - <<'MSG' | sh\n{GATE}\nMSG"),
]:
    check(f"REFUSED: {label}", denied("Bash", {"command": cmd}))

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("all gate self-protection checks passed")
