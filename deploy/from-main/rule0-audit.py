#!/usr/bin/env python3
"""Rule 0, as a check a script can run: is the ENFORCING gate registered inside a working tree?

Rule 0 landed 2026-08-28 after pub locked itself out. A registration that points into a
checkout makes every pull of that tree a hot deploy of the gate, re-read on the next tool call,
unreviewed and mid-session. The members' installer derives its destination FROM the registration,
so on such a machine the deploy cycle writes into the checkout and re-confirms the exposure every
time — mcnugget's deploy.log has been saying exactly that, every four hours, as a WARN nobody
read for two days. This exists so `hestia-deploy` can say it as a REFUSAL instead.

Prints one line per offending registration, empty output when clean. Never exits nonzero for a
finding: the caller decides what a finding means (refuse vs warn), because that is policy and
this is measurement.

Scope, honestly: this reads the claude-code harness settings, which is where every enforcing
hestia gate measured across the fleet so far is registered, plus HESTIA_LEGACY_FALLBACK from the
environment (the fired session's value, which is what actually runs, not only what the file
says). Other harnesses register elsewhere; adding one is a new path here, not a wider glob.
"""
import json
import os
import re
import subprocess
import sys


def in_a_worktree(path):
    """The git toplevel containing `path`'s directory, or None. `rev-parse --show-toplevel`
    rather than looking for a `.git` entry: a linked worktree has a .git FILE, a submodule has
    one too, and a bare-adjacent checkout has neither where you would look. Ask git."""
    d = os.path.dirname(os.path.expanduser(path))
    if not d or not os.path.isdir(d):
        return None
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def registered_gates():
    """Every path in the harness settings that looks like an enforcing hestia gate.

    A registration is a COMMAND LINE, not a path: it carries env assignments, an interpreter,
    and then the script. So the command is split and every token that ends in the gate's
    filename is considered — which also catches the env-var spelling of the legacy fallback
    without a second parser."""
    seen = []
    for fname in ("settings.json", "settings.local.json"):
        p = os.path.expanduser(os.path.join("~", ".claude", fname))
        try:
            with open(p) as fh:
                s = json.load(fh)
        except Exception:
            continue
        cmds = [h.get("command", "")
                for groups in (s.get("hooks") or {}).values()
                for g in groups
                for h in g.get("hooks", [])]
        cmds += [str(v) for k, v in (s.get("env") or {}).items()
                 if k == "HESTIA_LEGACY_FALLBACK"]
        for c in cmds:
            for tok in re.split(r"[\s=\"']+", c):
                if tok.endswith("pre_tool_use.py"):
                    seen.append((f"{fname}: {tok}", tok))
    # What the fired session actually carries can differ from what the file says — the
    # registration may set it inline. This is the value that will be honoured.
    lf = os.getenv("HESTIA_LEGACY_FALLBACK", "").strip()
    if lf:
        seen.append((f"HESTIA_LEGACY_FALLBACK={lf}", lf))
    return seen


def main():
    findings = []
    for label, path in registered_gates():
        top = in_a_worktree(path)
        if top:
            findings.append(f"{label} in {top}")
    for line in sorted(set(findings)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
