#!/usr/bin/env python3
"""Token-walk diagnostics for issue #463 specimens (kimi-code). Decision-only."""
import sys

REPO = "/mnt/c/exe/projects/ai-agents/hestia"
sys.path.insert(0, REPO + "/plugins/_shared")
import hestia_governance_closure as gc  # noqa: E402

G = REPO + "/plugins/_shared/hestia_governance_closure.py"

for label, cmd in [
    ("B FP pair", "grep -n PAT " + G + " ; f ( a ) else b"),
    ("E newline FN", "printf hi\ncp /tmp/evil " + G),
    ("J def+call", "f() ( cp /tmp/evil " + G + " ); f"),
    ("K spaced def", "f () ( cp /tmp/evil " + G + " )"),
    ("H func body", "f() { cp /tmp/evil " + G + "; }"),
]:
    toks = gc._tokenize(cmd)
    v = gc.classify("Bash", {"command": cmd}, cwd=REPO)
    print(f"{label}: {toks}")
    print(f"   -> {v.classification} [{getattr(v, 'rule', None)}]")

print()
print("'()' in _SEPARATORS:", "()" in gc._SEPARATORS,
      "| ');' in _SEPARATORS:", ");" in gc._SEPARATORS)

# And the naive FP patch against K (spaced def) — the widening flip:
gc._SEPARATORS = frozenset(s for s in gc._SEPARATORS if s not in ("(", ")"))
v = gc.classify("Bash", {"command": "f () ( cp /tmp/evil " + G + " )"}, cwd=REPO)
print("K under naive patch ->", v.classification, f"[{getattr(v, 'rule', None)}]")
