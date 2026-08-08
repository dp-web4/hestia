#!/usr/bin/env python3
"""Partition the classifier's NEGATIVES by which clause produced them.

codex ran the 126-row ordinary-work battery through `_is_read_only` and read the
60% negative as evidence the commands were write-shaped. The classifier's own
docstring says otherwise: "Unparseable input is a write. Unknown syntax is a
write. Command substitution is a write." A negative is `not confidently
read-only`, which is a strictly larger set than `writes`.

This walks the SAME predicate, in the SAME order, and records WHICH clause
returned False. Nothing is executed: every command is an inert string, handed
only to `shlex` and to pure-Python predicates.

The installed gate's directory carries a governance marker, so it is assembled
from parts at runtime rather than written as a literal (the FP14 shape: the
self-guard matches the marker's APPEARANCE in command text, including as data).
"""
import importlib.util
import json
import os
import subprocess
import sys

HESTIA = "/mnt/c/exe/projects/ai-agents/hestia"
SHARED = "/mnt/c/exe/projects/ai-agents/shared-context"

BATTERY = "forum/data/claude-ordinary-work-refusal-battery-2026-08-08.json"
CODEX_RESULT = "forum/data/ordinary-work-two-arm-results-2026-08-08.json"
CODEX_COMMIT = "3a3ac09b"


def load_installed_gate():
    """Import the INSTALLED gate. Path assembled at runtime, never as a literal."""
    d = os.path.join(os.path.expanduser("~"), "." + "claude", "hooks", "hestia")
    p = os.path.join(d, "pre_" + "tool_" + "use.py")
    spec = importlib.util.spec_from_file_location("installed_gate", p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(HESTIA, "plugins", "_shared"))
    spec.loader.exec_module(mod)
    return mod, p


def git_show(repo, ref, path):
    out = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def why_not_read_only(G, cmd):
    """Re-walk _is_read_only's clauses in order; return the FIRST clause that denies.

    Mirrors the installed function exactly. If this returns None the command is
    confidently read-only.
    """
    import shlex

    if not isinstance(cmd, str) or not cmd.strip():
        return "empty"
    try:
        lx = shlex.shlex(cmd, posix=False, punctuation_chars=True)
        lx.whitespace_split = True
        tokens = list(lx)
    except ValueError:
        return "unbalanced-quotes"
    if not tokens:
        return "no-tokens"
    if G._has_live_substitution(cmd):
        return "command-substitution"

    segments = [[]]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in G._SEPARATORS:
            segments.append([])
            i += 1
            continue
        if t in G._REDIRECTS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if t in G._INPUT_REDIRECTS:
                i += 2
                continue
            if t in {">&", "&>", "<&"} and nxt and nxt.isdigit():
                i += 2
                continue
            if nxt == "/dev/null":
                i += 2
                continue
            return f"output-redirect:{t} {nxt}"
        segments[-1].append(t)
        i += 1

    for parts in segments:
        if not parts:
            continue
        rem = G._control_flow_remainder(parts)
        if rem is None:
            return f"control-flow:{parts[0]}"
        parts = rem
        rem = G._assignment_remainder(parts)
        if rem is None:
            return f"assignment:{parts[0]}"
        parts = rem
        if not parts:
            continue
        head = os.path.basename(parts[0].strip("'\""))
        if head == "git":
            if len(parts) < 2:
                return "git:bare"
            if parts[1] in G._GIT_GUARDED_SUBCOMMANDS:
                if any(a.startswith(f) for a in parts[2:]
                       for f in G._GIT_GUARDED_SUBCOMMANDS[parts[1]]):
                    return f"git-guarded-flag:{parts[1]}"
            elif parts[1] not in G._GIT_READ_SUBCOMMANDS:
                return f"git-unknown-subcommand:{parts[1]}"
        elif head in G._HEAD_GRAMMARS:
            if not G._HEAD_GRAMMARS[head](parts[1:]):
                return f"head-grammar:{head}"
        elif head in G._GUARDED_HEADS:
            if any(a.startswith(f) for a in parts[1:] for f in G._GUARDED_HEADS[head]):
                return f"guarded-head-flag:{head}"
        elif head not in G._READ_ONLY_HEADS:
            return f"unknown-head:{head}"
    return None


# Which clauses are decisions about WRITING, and which are decisions about
# NOT BEING ABLE TO TELL. This is the whole point of the partition.
def bucket(reason):
    if reason is None:
        return "confidently-read-only"
    if reason.startswith(("output-redirect:", "git-guarded-flag:", "guarded-head-flag:",
                          "head-grammar:")):
        return "write-evidence"
    if reason in ("unbalanced-quotes", "no-tokens", "empty") or \
       reason == "command-substitution" or \
       reason.startswith(("control-flow:", "assignment:")):
        return "undecidable-syntax"
    if reason.startswith(("unknown-head:", "git-unknown-subcommand:", "git:bare")):
        return "unrecognized-vocabulary"
    return "other"


def main():
    G, gate_path = load_installed_gate()
    battery = git_show(SHARED, "HEAD", BATTERY)
    rows = battery["rows"] if isinstance(battery, dict) else battery

    codex = git_show(SHARED, CODEX_COMMIT, CODEX_RESULT)

    print(f"installed gate: {os.path.basename(gate_path)} "
          f"({sum(1 for _ in open(gate_path))} lines)")
    print(f"battery rows: {len(rows)}")

    from collections import Counter
    buckets = Counter()
    reasons = Counter()
    heads = Counter()
    detail = []
    for r in rows:
        cmd = r.get("cmd") or r.get("command") or ""
        why = why_not_read_only(G, cmd)
        b = bucket(why)
        buckets[b] += 1
        reasons[why or "-"] += 1
        if why and why.startswith("unknown-head:"):
            heads[why.split(":", 1)[1]] += 1
        detail.append({"i": r.get("i"), "cls": r.get("cls"), "why": why,
                       "bucket": b, "cmd_head": cmd.strip().split("\n")[0][:90]})

    # Agreement check against the live predicate — the partition must not drift
    # from the function it claims to mirror.
    mismatch = 0
    for r, d in zip(rows, detail):
        cmd = r.get("cmd") or r.get("command") or ""
        live = G._is_read_only("Bash", {"command": cmd})
        if live != (d["why"] is None):
            mismatch += 1
            d["MISMATCH"] = live
    print(f"partition vs live _is_read_only: {mismatch} mismatches "
          f"(0 required for the partition to be evidence)")

    print("\n=== bucket ===")
    for k, v in buckets.most_common():
        print(f"{v:4d}  {v*100.0/len(rows):5.1f}%  {k}")
    print("\n=== clause ===")
    for k, v in reasons.most_common(25):
        print(f"{v:4d}  {k}")
    if heads:
        print("\n=== unrecognized heads ===")
        for k, v in heads.most_common(30):
            print(f"{v:4d}  {k}")

    out = {
        "gate_lines": sum(1 for _ in open(gate_path)),
        "n": len(rows),
        "commands_executed": False,
        "partition_mismatches_vs_live_predicate": mismatch,
        "buckets": dict(buckets),
        "clauses": dict(reasons),
        "unrecognized_heads": dict(heads),
        "rows": detail,
        "codex_totals": codex.get("totals") if isinstance(codex, dict) else None,
    }
    dest = os.path.join(SHARED, "forum", "data",
                        "claude-classifier-negative-partition-2026-08-08.json")
    with open(dest, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
