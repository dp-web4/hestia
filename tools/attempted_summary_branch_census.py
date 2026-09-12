#!/usr/bin/env python3
"""What does the operator actually SEE when a gate refusal opens an escalation?

`_attempted_summary` in the enforcing gate hook is a THREE-WAY switch, and which arm a
command lands in is decided entirely at the sender. The daemon never receives the bytes
the other two arms drop, so no reader anywhere can recover them later:

    FULL       <=220 chars, no credential-shaped substring  -> the whole command
    TRUNCATED   >220 chars, no credential-shaped substring  -> first 220 chars + '...'
    ERASED     any length,  one credential-shaped substring -> '[REDACTED - N chars withheld]'

This matters because two seats reviewing hestia#318 reached opposite conclusions about
whether an operator could see the act they approved -- and each was reporting a different
arm of this switch truthfully. The rate, not the anecdote, is the deciding fact.

WHY THE INSTRUMENT IMPORTS THE INSTALLED FILE. A reimplementation of the predicate would
measure the instrument's idea of the rule, and would keep reading green after the rule
changed. The enforcing copy is located through `~/.hestia/current-build.json` -- the
install ledger, which is what actually binds the hook -- rather than a hardcoded path, so
this follows a redeploy instead of silently measuring a stale file.

Usage:  python3 tools/attempted_summary_branch_census.py [transcript-root]
Default transcript root is ~/.claude/projects.

DELIBERATELY PRINTS NO COMMAND TEXT. The ERASED arm is selected for credential-shaped
content, so a sample of it is precisely the thing that must not land in a record that is
easier to read and harder to expunge than the files it came from.
"""
from __future__ import annotations

import collections
import glob
import importlib.util
import json
import os
import sys

LEDGER = os.path.expanduser("~/.hestia/current-build.json")

# The two halves of the shape list, split by what a hit actually EVIDENCES. A hit on the
# left is a claim that key material is present. A hit on the right is a claim that the
# command is ABOUT secrets -- which an ordinary `grep -rn secret docs/` satisfies.
MATERIAL = {
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".pem", ".p12", ".pfx",
    "begin rsa private key", "begin openssh private key", "begin private key",
    "begin ec private key", "begin certificate",
    "/.ssh", ".ssh/", "/.gnupg", ".netrc", ".pgpass", ".htpasswd",
}

# A PROXY for the gate's marker list, not a copy of it: the sub-population that can mint one
# of these escalations at all. Reported as a proxy on purpose -- the full-population rates
# below do not depend on it, only the sub-population block does.
MARKER_SHAPES = ("plugins/", "/hooks", "hooks/", "pre_tool_use", "hestia_gate", "web4-governance")


def load_enforcing_hook():
    """Import the gate hook the install ledger says is in force. Returns the module.

    Raises rather than falling back to a guess: an instrument that silently measures a file
    nobody enforces is worse than one that stops.
    """
    with open(LEDGER, encoding="utf-8") as fh:
        ledger = json.load(fh)
    path = None
    for member in ledger.get("members", []):
        for f in member.get("files", []):
            if os.path.basename(f.get("path", "")) == "pre_tool_use.py":
                path = f["path"]
                break
        if path:
            break
    if not path or not os.path.exists(path):
        raise SystemExit(f"install ledger {LEDGER} names no readable enforcing gate hook")
    spec = importlib.util.spec_from_file_location("enforcing_gate_hook", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["enforcing_gate_hook"] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass  # the hook is also a script; importing it must not take us with it
    return mod, path


def collect_commands(root: str) -> tuple[list[str], int]:
    """Every Bash command issued by a Claude agent on this host, whitespace-normalised.

    Normalised the same way `_attempted_summary` normalises before measuring, so the census
    and the rule agree on what "the command" is.
    """
    files = glob.glob(os.path.join(root, "*", "*.jsonl"))
    out: list[str] = []
    for p in files:
        try:
            with open(p, errors="replace", encoding="utf-8") as fh:
                for line in fh:
                    if '"Bash"' not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    content = (ev.get("message") or {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "tool_use" and c.get("name") == "Bash":
                            v = (c.get("input") or {}).get("command")
                            if isinstance(v, str) and v:
                                out.append(" ".join(v.split()))
        except Exception:
            continue
    return out, len(files)


def split(cmds, cred):
    full = trunc = erased = 0
    for c in cmds:
        if cred(c):
            erased += 1
        elif len(c) > 220:
            trunc += 1
        else:
            full += 1
    return full, trunc, erased


def block(label, cmds, cred):
    n = max(len(cmds), 1)
    full, trunc, erased = split(cmds, cred)
    print(f"--- {label}  (n={len(cmds)})")
    print(f"  FULL act visible : {full:6d}  ({100 * full / n:5.1f}%)")
    print(f"  TRUNCATED at 220 : {trunc:6d}  ({100 * trunc / n:5.1f}%)   tail lost")
    print(f"  WHOLLY ERASED    : {erased:6d}  ({100 * erased / n:5.1f}%)   operator sees no act")
    print(f"  => unreconstructable from the operator surface: {100 * (trunc + erased) / n:.1f}%")
    print()


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.claude/projects")
    mod, path = load_enforcing_hook()
    cred = mod._credential_shaped
    shapes = mod._CREDENTIAL_SHAPES
    print(f"enforcing gate hook (per install ledger): {path}")
    print(f"credential shapes in force: {len(shapes)}")
    print()

    # CONTROLS, BOTH POLARITIES, BEFORE ANY RATE IS PRINTED. A predicate that fired on
    # everything and a predicate that fired on nothing would each produce a clean-looking
    # census, so the census does not get to run until the discriminating cases are checked.
    # POSITIVE CONTROL DERIVED FROM THE PREDICATE'S OWN VOCABULARY, not one hand-picked
    # sample. A single example pins ONE shape and silently stops covering the rest the moment
    # the list grows -- which is the failure mode this census exists to catch elsewhere. Built
    # from `shapes`, the control tracks the predicate instead of going stale beside it.
    #
    # DISCLOSED: it also leaves this file with no key-material literal in it, which is what
    # the public-boundary check flagged (a baked local home path) and what the running gate
    # refuses outright. That is a consequence of the redesign, not its justification -- the
    # justification is coverage, and the redesign is strictly stronger than what it replaces.
    misses = [s for s in shapes if not cred("cat /home/user/x" + s)]
    neg = cred("grep -n foo core/src/handler.rs")
    # OVER-BREADTH, REPORTED NOT ASSERTED. Shapes that are ordinary words fire on prose, and
    # that false-positive supply is the thing this census is measuring the cost of.
    prose = [s for s in shapes if s.replace("_", "").isalpha() and len(s) > 3]
    print(f"controls: shapes={len(shapes)}  all fire={not misses}  "
          f"plain-read fires={neg}  bare-word shapes={len(prose)}")
    if misses or neg:
        raise SystemExit(
            f"CONTROL FAILED - the predicate does not discriminate "
            f"(unmatched shapes={misses}, plain-read fires={neg}); census aborted")
    print()

    cmds, nfiles = collect_commands(root)
    if not cmds:
        raise SystemExit(f"no Bash commands found under {root}; nothing to measure")
    print(f"population: {len(cmds)} Bash commands from {nfiles} transcripts under {root}")
    print()

    block("all Bash commands", cmds, cred)
    block("escalation-eligible (governance-marker-SHAPED text; proxy, not the gate's list)",
          [c for c in cmds if any(m in c for m in MARKER_SHAPES)], cred)

    # WHAT THE ERASURE ACTUALLY EVIDENCED. The redaction's own comment argues the asymmetry
    # is deliberate: a false positive costs one vague escalation, a false negative costs a
    # secret in the permanent record. Sound for the RECORD. The question this block asks is
    # what it costs the DECISION, which is the same string today.
    erased = [c for c in cmds if cred(c)]
    topic_shapes = set(shapes) - MATERIAL
    mat_only = word_only = both = 0
    which: dict[str, int] = collections.Counter()
    for c in erased:
        low = c.lower()
        m = any(s in low for s in MATERIAL)
        t = any(s in low for s in topic_shapes)
        if m and t:
            both += 1
        elif m:
            mat_only += 1
        else:
            word_only += 1
        for s in shapes:
            if s in low:
                which[s] += 1
    e = max(len(erased), 1)
    print(f"--- of the {len(erased)} wholly-erased commands, what triggered it")
    print(f"  a TOPIC word only (secret/password/credential/.env/...) : {word_only:6d}"
          f"  ({100 * word_only / e:.1f}%)")
    print(f"  key MATERIAL only (id_rsa/.pem/.ssh/.netrc/...)         : {mat_only:6d}")
    print(f"  both                                                    : {both:6d}")
    print()
    print("  substrings that erased an act (one command may hit several):")
    for k, v in which.most_common(12):
        print(f"    {v:6d}  {k!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
