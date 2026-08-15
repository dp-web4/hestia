#!/usr/bin/env python3
"""kimi-code independent verification of claude-code's issue #463 claims (mesh notice 2529).

Three claims under test, all DECISION-only — no probed command is ever executed:

  1. MECHANISM (FP): newline is NOT in `_SEPARATORS` but `(`/`)` ARE, so a close-paren
     promotes the next word to head, and a shell keyword there denies (out-of-grammar
     + closure vocab). `else` denies, `elseX` allows — one character.
  2. TWIN (FN): the same tokenization admits a real `cp` onto the gate behind one
     newline, because only the first line's head is ever inspected.
  3. WIDENING: fixing the FP alone (naive patch: drop parens from `_SEPARATORS`) turns
     a REAL write spelling that the paren-promotion accidentally catches today
     (`f() { cp /tmp/evil <gate>; }`) from DENY into ALLOW.

Layers probed:
  L1: the INSTALLED claude gate over the PreToolUse stdin protocol (the enforcing
      decision path; installed hook verified byte-identical to the tree copy).
  L2: the shared `classify()` imported from the repo tree (the producing layer).
  L3: L2 with a simulated naive FP fix (`_SEPARATORS` minus parens), to test claim 3.
"""
import json
import subprocess
import sys

REPO = "/mnt/c/exe/projects/ai-agents/hestia"
sys.path.insert(0, REPO + "/plugins/_shared")
import hestia_governance_closure as gc  # noqa: E402

HOOK = "/home/dp/.claude/hooks/hestia/pre_tool_use.py"
GATE = REPO + "/plugins/_shared/hestia_governance_closure.py"
CWD = "/mnt/c/exe/projects/ai-agents"

CASES = [
    ("A read control",            "grep -n PAT " + GATE),
    ("B FP: paren then keyword",  "grep -n PAT " + GATE + " ; f ( a ) else b"),
    ("C 1-char control: elseX",   "grep -n PAT " + GATE + " ; f ( a ) elseX b"),
    ("D write at line 1 (deny)",  "cp /tmp/evil " + GATE),
    ("E FN: newline then cp",     "printf hi\ncp /tmp/evil " + GATE),
    ("F FN: newline then loop",   "printf hi\nfor f in " + GATE + "\ndo\ncp /tmp/evil $f\ndone"),
    ("G semicolon differential",  "printf hi;cp /tmp/evil " + GATE),
    ("H real write via func body", "f() { cp /tmp/evil " + GATE + "; }"),
    ("I paren-subshell write",     "(cp /tmp/evil " + GATE + ")"),
    ("J real write: def+call",     "f() ( cp /tmp/evil " + GATE + " ); f"),
]


def ask_hook(command: str) -> str:
    """L1: installed gate decision over the stdin protocol. Executes nothing probed."""
    payload = {
        "session_id": "kimi-issue463-probe",
        "cwd": CWD,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    blob = ((p.stdout or "") + (p.stderr or "")).lower()
    return "DENY" if ("deny" in blob or p.returncode == 2) else "allow"


def ask_classify(command: str) -> str:
    """L2: the producing layer in the tree. 'write' => the hook would refuse."""
    v = gc.classify("Bash", {"command": command}, cwd=CWD)
    return f"{v.classification}({v.rule})" if getattr(v, "rule", None) else v.classification


def verdict(classification: str) -> str:
    return "DENY" if classification.startswith("write") else "allow"


rows = []
for label, cmd in CASES:
    l1 = ask_hook(cmd)
    l2 = ask_classify(cmd)
    rows.append((label, l1, verdict(l2), l2))
    print(f"{label:30s} L1(installed)={l1:5s} L2(classify)={verdict(l2):5s} [{l2}]")

# L3: simulated NAIVE FP fix — drop parens from _SEPARATORS (the patch a reviewer
# reaches for first when shown claim 1). Does the FP clear, and what else changes?
print("\n-- L3: simulated naive FP fix (_SEPARATORS minus parens) --")
gc._SEPARATORS = frozenset(s for s in gc._SEPARATORS if s not in ("(", ")"))
for label, cmd in CASES:
    l3 = ask_classify(cmd)
    before = next(r for r in rows if r[0] == label)
    flip = "  <-- FLIPPED" if verdict(l3) != before[2] else ""
    print(f"{label:30s} L3(patched)={verdict(l3):5s} [{l3}]{flip}")
