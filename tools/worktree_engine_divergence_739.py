#!/usr/bin/env python3
"""Codex's loader is path-relative, and the paths on this disk hold three different engines.

#739's differential reports `SEAT DISAGREEMENTS: none` by calling each seat's
`_closure_classify` with identical arguments. All three driveable seats resolve that name to
the same imported symbol, so the comparison can only fail if two seats' imports landed on
different bytes. At the instant the differential runs they do not -- one sha256.

But claude-code and kimi resolve `$HESTIA_HOME/shared` (one installed copy, fleet-wide) while
codex resolves `plugins/_shared` by SEARCH, not by pin. Its invoked hook
(`/home/dp/.codex/hooks/pre_tool_use.py`, byte-identical to the repo copy at `75698b0e...`)
inserts two candidates: `~/.codex/_shared` first, then `$HESTIA_WORKSPACE/hestia/plugins/_shared`.
The first directory EXISTS but holds only `hestia_gate_mechanism.py`, so `isdir` passes, the
path is inserted, and the closure import falls through to candidate two -- the LIVE SHARED
WORKING TREE, whose contents are whatever branch that tree currently has checked out.

So codex's gate engine is a function of the shared tree's HEAD. This probe asks what byte-sets
that HEAD can actually produce, and whether the difference is behavioural or cosmetic.

It does not classify from a diff. It loads each on-disk engine and asks it to classify the
two commands whose comments live in the engine itself (#463, #496) -- so a stale engine is
convicted by the citation its own successor carries.

Read-only: imports modules, writes nothing.
"""
import hashlib
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The two regression cases #463 and #496 closed, quoted from the engine's own comments.
# Both are the SAME write; only the separator in front of it changes.
CASES = [
    ("positive control", "cp /tmp/evil {closure}/x.py"),
    ("#463 newline-as-separator", "printf hi\ncp /tmp/evil {closure}/x.py"),
    ("#496 fused blank line", "printf hi\n\ncp /tmp/evil {closure}/x.py"),
]

# A path the closure layer is meant to protect, spelled the way the seat hooks spell it.
CLOSURE_DIR = os.path.join(REPO, "plugins", "_shared")


def load(path):
    # Distinct module name per engine so the three versions coexist in one interpreter.
    # It MUST be registered in sys.modules before exec: the engine defines a frozen
    # dataclass, and dataclasses resolves annotations via sys.modules[cls.__module__].
    name = "engine_" + hashlib.sha256(path.encode()).hexdigest()[:8]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def classify(mod, cmd):
    """Drive the engine exactly as `plugins/codex/hooks/pre_tool_use.py:879` drives it:
    `classify("Bash", {"command": ...}, cwd=...)` -- the symbol the seat imports as
    `_closure_classify`. Also report the tokenizer's raw view, which is where #463/#496 live."""
    fn = getattr(mod, "classify", None)
    if fn is None:
        return "NO-CLASSIFIER", "-"
    try:
        verdict = fn("Bash", {"command": cmd}, cwd=REPO)
        kind = getattr(verdict, "classification", verdict)
    except Exception as exc:  # noqa: BLE001
        kind = "ERR:%s" % type(exc).__name__
    seen = getattr(mod, "_bash_write_targets", None)
    try:
        targets = seen(cmd) if seen else "-"
    except Exception as exc:  # noqa: BLE001
        targets = "ERR:%s" % type(exc).__name__
    return kind, targets


def report(label, path):
    print("%s\n    path   = %s\n    sha256 = %s" % (label, path, sha(path)))
    mod = load(path)
    for case, tmpl in CASES:
        cmd = tmpl.format(closure=CLOSURE_DIR)
        kind, targets = classify(mod, cmd)
        n = len(targets) if isinstance(targets, list) else targets
        print("      %-28s -> %-8s (write targets seen: %s)" % (case, kind, n))
    print()


def main():
    report("INSTALLED (claude-code, kimi)",
           os.path.expanduser("~/.hestia/shared/hestia_governance_closure.py"))
    report("WORKING TREE (codex, this tree)",
           os.path.join(REPO, "plugins", "_shared", "hestia_governance_closure.py"))
    # The two branch states below are NOT reachable via a worktree -- codex is pinned to
    # HESTIA_WORKSPACE=/mnt/c/exe/projects/ai-agents, so `.wt/*` is never on its path. They are
    # reachable the way every other state of the shared tree is: `git checkout` in that tree.
    # `codex/2584-chain-window-cutover` is an UNMERGED live branch.
    report("SHARED TREE @ codex/2584-chain-window-cutover (unmerged)",
           os.path.join(REPO, ".wt", "codex-2584", "plugins", "_shared",
                        "hestia_governance_closure.py"))
    report("SHARED TREE @ 528-turnover (165e009)",
           os.path.join(REPO, ".wt", "528-turnover", "plugins", "_shared",
                        "hestia_governance_closure.py"))
    print("VERDICT")
    print("  claude-code and kimi read one installed file; codex reads the shared tree.")
    print("  Today those agree, and #739's differential therefore reports 'no disagreement'.")
    print("  One `git checkout codex/2584-chain-window-cutover` in that tree splits them:")
    print("  codex would classify the #463 and #496 writes as READ (0 targets seen) while the")
    print("  other two seats correctly deny. The differential samples one instant and cannot")
    print("  see this; it is a property of the LOADER, which the differential does not drive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
