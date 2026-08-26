#!/usr/bin/env python3
"""Collapse slice 1: the two byte-identical twins out of the codex and kimi gates.

WHAT THIS MOVES. `_detect_workspace` (19 lines) and `_emit_attestation` (62 lines) existed as
BYTE-IDENTICAL copies in both gates -- verified line for line, not inferred from length. They
are the safest possible first slice precisely because they are identical: a move that changes
no bytes of logic can only fail at the wiring, never at the decision, so a red after this is
unambiguous about where to look.

WHY THE TARGETS ARE ARGUMENTS. Every path this script writes is passed on the command line
rather than spelled inside it. The gate classifies the COMMAND, so a script holding its
targets internally would present as a write to nothing and reach the governance surface with
the gate seeing no marker at all. That is the `computed path invisible to the gate` evasion,
and using it here -- in the collapse of the gate itself -- would be the exact behaviour the
gate-self rule exists to make visible. The paths are in the command so the escalation names
what it authorises.

WHY ONE SCRIPT AND NOT THREE EDITS. Three writes means three escalations, each on its own
600-second claim fuse. The slice is one logical change; making it one ACT means one approval
and one claim, which is the difference between a process that works and a process that is
technically available.

Idempotent: refuses rather than half-applies if the tree is not in the expected shape.
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

# `_detect_workspace` is NOT here, and the reason is structural rather than a scoping
# choice. `_load_mechanism()` resolves the shared engine via `os.path.join(WORKSPACE, ...)`,
# so WORKSPACE must exist BEFORE the engine can be imported: the function that finds the
# engine cannot live inside it. The meter counted its 38 sloc as collapsible because
# "same name in 2+ gates, unowned by shared" cannot see a bootstrap. The unshared fork
# surface is an UPPER BOUND on the work, not the work list.
TWINS = ("_emit_attestation",)


def fn_span(src: str, name: str):
    """(start, end) 0-based line span of a top-level function, or None."""
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.lineno - 1, node.end_lineno
    return None


def cut(src: str, name: str) -> tuple[str, list[str]]:
    span = fn_span(src, name)
    if span is None:
        raise SystemExit(f"refusing: {name} is not a top-level function here")
    lines = src.splitlines(keepends=True)
    body = lines[span[0]:span[1]]
    # Take one trailing blank line with it, so removals do not leave growing gaps.
    end = span[1]
    while end < len(lines) and lines[end].strip() == "":
        end += 1
        break
    return "".join(lines[:span[0]] + lines[end:]), body


def main() -> int:
    argv = [a for a in sys.argv if a != "--dry-run"]
    if len(argv) != 4:
        raise SystemExit("usage: collapse_slice1.py <shared> <codex_hook> <kimi_hook>")
    shared_p, codex_p, kimi_p = (Path(a) for a in argv[1:4])

    shared = io.open(shared_p, encoding="utf-8").read()
    # The shared side must ALREADY own both names. This script does not add them: the bodies
    # were reviewed and parameterised by hand, and a script that both writes the engine and
    # deletes the copies could leave the engine holding something nobody read.
    for want in ("def emit_attestation(",):
        if want not in shared:
            raise SystemExit(
                f"refusing: the shared engine does not define {want!r} yet. Add and review "
                f"the engine side first; this script only removes the copies and rewires."
            )

    bodies = {}
    staged: list[tuple[str, Path, str]] = []

    # PER-SEAT REWIRES, spelled out rather than parameterised. codex reaches the engine
    # through a `_load_mechanism()` helper; kimi imports the name inline at each call site;
    # claude-code does neither and is not in this slice. A single "uniform" rewire would have
    # been written against whichever seat I read first and broken the other -- which is the
    # same mistake as the shared-engine copies themselves, one layer up. Verified before
    # writing: `_mech()` (my first guess) exists in NEITHER seat.
    REWIRE = {
        "codex": [(
            '_emit_attestation(t["allows"], t["denies"])',
            '_load_mechanism().emit_attestation(\n'
            '                t["allows"], t["denies"],\n'
            '                plugin_id=HESTIA_PLUGIN_ID, role_lct=_role_bridge())',
        )],
        "kimi": [(
            '_emit_attestation(t["allows"], t["denies"])',
            'from hestia_gate_mechanism import emit_attestation\n'
            '            emit_attestation(\n'
            '                t["allows"], t["denies"],\n'
            '                plugin_id=HESTIA_PLUGIN_ID, role_lct=_role_bridge())',
        )],
    }

    for label, path in (("codex", codex_p), ("kimi", kimi_p)):
        src = io.open(path, encoding="utf-8").read()
        for name in TWINS:
            src, body = cut(src, name)
            bodies.setdefault(name, []).append("".join(body))
        for old, new in REWIRE[label]:
            if src.count(old) != 1:
                raise SystemExit(
                    f"refusing: {label} has {src.count(old)} occurrences of {old!r}, "
                    f"expected exactly 1. The seat is not in the shape this was measured "
                    f"against."
                )
            src = src.replace(old, new)
        ast.parse(src)  # never stage a file that will not import
        # TWO PHASE, deliberately. Writing each seat as it is computed means a refusal on the
        # SECOND seat leaves the first already rewired and the tree in a state no commit
        # describes. The claim authorising this is single-use, so a half-apply is not a retry
        # away from correct -- it is a governance surface in a shape nobody approved.
        staged.append((label, path, src))

    # THE EQUIVALENCE CHECK, and the reason this slice was chosen. Both seats' copies must
    # have been identical to each other; if they were not, "move the shared one" silently
    # picked a winner and threw away the other seat's behaviour.
    for name, copies in bodies.items():
        if len(set(copies)) != 1:
            raise SystemExit(
                f"refusing: {name} was NOT identical across seats. Moving it would have "
                f"chosen one seat's behaviour and discarded the other's, unreviewed."
            )
        print(f"  verified identical across both seats: {name}")
    if "--dry-run" in sys.argv:
        print("  DRY RUN: verified, nothing written")
        return 0
    # Everything verified. Only now does anything on disk change.
    for label, path, src in staged:
        io.open(path, "w", encoding="utf-8").write(src)
        print(f"  {label}: removed {len(TWINS)} twin(s), rewired 2 call site(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
