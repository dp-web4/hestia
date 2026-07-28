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
print("all gate self-protection checks passed")
