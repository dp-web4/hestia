"""Does the CODEX-path classifier refuse a read-only `for` loop that names
governance files, where the CLAUDE-path classifier permits it?

No governance literal is spelled here: the test vector's vocabulary token is
obtained FROM the closure itself at runtime. Nothing is opened; only strings
are classified.
"""
import importlib.util
import os
import sys

SHARED = os.getenv("HESTIA_SHARED_DIR") or os.path.expanduser("~/.hestia/shared") + "/"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SHARED + name + ".py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


closure_mod = load("hestia_governance_closure")
shell_mod = load("hestia_shell_classifier")

# --- what does the write-position parser call a `for` loop? ---
print("=== _write_position_targets note (codex path) ===")
for label, cmd in [
    ("plain read",  'grep -c "" alpha.txt'),
    ("for loop",    'for f in alpha.txt beta.txt; do grep -c "" "$f"; done'),
    ("while loop",  'while read f; do grep -c "" "$f"; done'),
    ("if block",    'if grep -q x alpha.txt; then echo hi; fi'),
]:
    try:
        targets, note = closure_mod._write_position_targets("Bash", {"command": cmd})
        print(f"  note={note!r:18} targets={len(targets)}  <- {label}")
    except Exception as exc:
        print(f"  RAISED {type(exc).__name__}  <- {label}")

# --- pull a real vocabulary token from the closure itself ---
cl = closure_mod.default_closure()
vocab = None
for attr in ("files_hooks_only", "files_anywhere", "dir_markers", "exact_paths"):
    v = getattr(cl, attr, None)
    if v:
        vocab = sorted(v)
        print(f"\nclosure.{attr}: {vocab[:6]}")
        break
if vocab is None:
    print("\n(no vocabulary attribute found; listing closure attrs)")
    print(" ", [a for a in dir(cl) if not a.startswith("__")])

token = vocab[0] if vocab else None
if token:
    cmds = {
        "read of one governed file":  f'grep -c "" {token}',
        "for loop over governed file": f'for f in {token}; do grep -c "" "$f"; done',
    }
    print("\n=== same command, both modules (NOT two seats: closure decides on ALL seats) ===")
    print(f"{'closure PRIMARY':>12} {'shellcls FALLBACK':>12}   case")
    print("-" * 60)
    for label, cmd in cmds.items():
        v = closure_mod.classify("Bash", {"command": cmd})
        codex_verdict = f"{v.classification}"
        ro = shell_mod._is_read_only("Bash", {"command": cmd})
        claude_verdict = "read" if ro else "write"
        print(f"{codex_verdict:>15} {claude_verdict:>17}   {label}")
        if v.classification == "write":
            print(f"{'':>26} rule={getattr(v, 'rule', '?')} marker={getattr(v, 'marker', '?')}")
