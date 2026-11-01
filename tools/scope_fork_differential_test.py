#!/usr/bin/env python3
"""Does the gemini seat's scope answer AGREE with the hardened shared engine?

History. This file was written as a divergence meter against gemini's forked scope predicates
(path_in_scope, command_in_scope, _all_repos), which measured strictly fail-open: 6 of 12 rows
SEAT GRANTS WHAT THE ENGINE DENIES. Those forks were replaced by thin delegates, and the file
became a wiring pin that lifted the delegates out by AST. One-gate stage C removed the seat's
predicates altogether: the gemini shim is now pure translation (`to_event`) and the law is the
common gate's (`hestia_single_gate.normalized_event` -> `hestia_gate_core.evaluate`). So the
"seat" column below is what the gemini seat's REAL translation produces when it reaches that
law, for a native gemini `read_file` act on the same input — the path a re-fork would have to
change to go red.

WHY THESE INPUTS. Every case is a defect class the shared implementation's OWN DOCSTRING says
it was hardened against, each naming the report that found it.

RATCHET. Pinned: the divergence count may fall, never rise (CI pins 0).

Exit: 0 the pin held; 1 it broke, or the ENGINE disagreed with its pinned answer (which means
this harness is measuring its own setup and its numbers should not be read at all).

Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_OVERLAY, HESTIA_CONTRACT_SHIMS.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
_OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
for _n in ("hestia_gate_core", "hestia_governance_closure", "hestia_gate_mechanism",
           "hestia_single_gate"):
    if _OVERLAY.get(_n):
        _s = importlib.util.spec_from_file_location(_n, _OVERLAY[_n])
        _m = importlib.util.module_from_spec(_s)
        sys.modules[_n] = _m
        _s.loader.exec_module(_m)

import hestia_gate_core as core          # noqa: E402
import hestia_single_gate as gate        # noqa: E402

GATE = Path(json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}").get("gemini")
            or ROOT / "plugins" / "gemini" / "hooks" / "before_tool.py")


def load_shim(path: Path):
    spec = importlib.util.spec_from_file_location("scope_fork_gemini_shim", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cases(ws: str, home: str):
    """(label, path, expected ENGINE verdict, defect class).

    Every row pins what the hardened engine must answer, not merely that two paths agree: the
    first draft built its workspace under `/tmp`, so the temp-root carve-out granted every path
    and four controls "passed" by both sides being wrong. Traversal targets are bland names on
    purpose (spelling a credential directory trips the fleet's own egress scanner)."""
    return [
        ("sibling-home",      home + "-evil/x",                False, "home judged by SUBSTRING, not boundary (GPT fleet-review blocker 8)"),
        ("home-traversal",    home + "/../elsewhere/x",        False, "traversal OUT of home still reads as home (blocker 8)"),
        ("tmp-prefix",        "/tmpfoo/x",                     False, "startswith('/tmp') (codex #169, _under_temp_root)"),
        ("vartmp-prefix",     "/var/tmpevil/x",                False, "startswith('/var/tmp') (codex #169)"),
        ("ws-traversal-out",  ws + "/granted/../ungranted/x",  False, "no normpath: segment read lexically (kimi #940 B5)"),
        ("ws-traversal-deep", ws + "/granted/a/../../other/x", False, "no normpath, two levels up (kimi #940 B5)"),
        ("ws-substring",      ws + "-evil/granted/x",          False, "'WORKSPACE in p' substring containment (kimi #940 B5)"),
        ("ws-root-bare",      ws,                              False, "control: glob-the-root antipattern"),
        ("granted-plain",     ws + "/granted/tools/x.py",      True,  "control: plainly in scope"),
        ("ungranted-plain",   ws + "/ungranted/x.py",          False, "control: plainly out of scope"),
        ("real-tmp",          "/tmp/probe",                    True,  "control: real tmp"),
        ("real-home",         home + "/settings.json",         True,  "control: the member's own home"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-divergences", type=int, default=None,
                    help="ratchet: fail if more inputs diverge than this")
    args = ap.parse_args()

    # Hermetic, and deliberately NOT under a temp dir (see `cases`). Neither side touches the
    # disk beyond realpath on a home marker, defined for paths that do not exist.
    ws = "/synthetic-workspace"
    home = "/synthetic-member-home"
    scopes = ("granted",)
    shim = load_shim(GATE)
    profile = gate.GateProfile(**{**shim.PROFILE, "identity_path": home + "/identity.json",
                                  "home_markers": (home,), "observe_dir": None})
    cprofile = profile.core_profile()
    policy = core.resolve_agent_policy(
        cprofile, vault_reader=lambda _m: {"in_scope": list(scopes), "role": "citizen"})

    print(f"gate under test : {GATE.name} -> hestia_single_gate.normalized_event -> core.evaluate")
    print(f"scopes          : {scopes}")
    print()
    print(f"{'case':<20}{'expect':>8}{'engine':>8}{'seat':>7}   {'':<14}defect class")
    print("-" * 120)
    diverged, engine_wrong = [], []
    for label, path, expect, why in cases(ws, home):
        e = core.path_in_scope(path, scopes, ws, cprofile, cwd=ws)
        raw = {"hook_event_name": shim.HARNESS["event"], "tool_name": "read_file",
               "tool_input": {"absolute_path": path}, "cwd": ws, "session_id": "scope-fork"}
        verdict = core.evaluate(gate.normalized_event(shim.to_event(gate, raw)), cprofile, ws,
                                policy=policy)
        s_ = not verdict.blocks
        if e != expect:
            engine_wrong.append((label, path, expect, e))
        if e != s_:
            diverged.append((label, path, e, s_, why))
        print(f"{label:<20}{str(expect):>8}{str(e):>8}{str(s_):>7}"
              f"{('  <-- DIVERGES' if e != s_ else ''):<17}{why}")
    print("-" * 120)

    if engine_wrong:
        print("\n::error::the SHARED ENGINE did not give the pinned answer. This harness is "
              "not measuring what it says -- do not read the divergence count.", file=sys.stderr)
        for label, path, expect, e in engine_wrong:
            print(f"    {label}: expected {expect}, engine said {e}  ({path})", file=sys.stderr)
        return 1

    over = [d for d in diverged if d[3] and not d[2]]
    print(f"\ndiverging inputs: {len(diverged)} of {len(cases(ws, home))}   "
          f"of which SEAT GRANTS WHAT THE ENGINE DENIES: {len(over)}")
    for label, path, e, s_, why in diverged:
        print(f"\n  {label:<20}"
              f"{'SEAT GRANTS WHAT THE ENGINE DENIES' if s_ and not e else 'seat denies what the engine grants'}")
        print(f"      input : {path}")
        print(f"      class : {why}")

    if args.max_divergences is not None:
        print(f"\nratchet divergences: {len(diverged)} vs limit {args.max_divergences}")
        if len(diverged) > args.max_divergences:
            print(f"::error::the gemini seat's scope answer diverges from the shared engine on "
                  f"{len(diverged)} inputs, above the pinned {args.max_divergences}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
