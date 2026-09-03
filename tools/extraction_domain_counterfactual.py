#!/usr/bin/env python3
"""Same tool, same destination, same scope: ALLOW or DENY decided only by extraction.

`plugins/_shared/hestia_gate_core.py` owns `path_in_scope` and has been hardened four times
against real defects (codex #169 `startswith("/tmp")`, kimi #940 B5 the unnormalised absolute
branch, GPT fleet-review blocker 8 substring home matching, #596 scope resolution). None of
that hardening is reached unless the path is IN THE EVENT, and putting it there is not the
engine's job. Each seat builds `NormalizedEvent.paths` itself, from a hard-coded list of
argument key names -- three keys in claude-code, codex and kimi, ten in gemini.

This driver holds everything else fixed and varies only that. It calls the engine twice with
the same tool, the same destination and the same scope: once with `paths=[]`, which is what
the seat actually constructs when the destination arrived under an unenumerated key, and once
with the destination extracted. If the two answers differ, the gate's strength on that call
was decided by a key-name list and not by any policy anyone ratified.

The scope used here is a fixed one-repo tuple supplied by this driver, NOT the live grant of
whatever seat runs it -- otherwise the result would move with the operator's grants and stop
being a statement about the engine. `--workspace` sets the root the paths hang off.

Exit 1 if any counterfactual pair disagrees; that non-zero IS the finding, so this is a
report to read rather than a check to keep green.
"""

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", required=True,
                    help="workspace root the test paths hang off")
    ap.add_argument("--granted", default="hestia", help="the single granted repo")
    ap.add_argument("--ungranted", default="metalinxx",
                    help="a repo NOT in the scope tuple above")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    root = here.parent
    sys.path.insert(0, str(root / "plugins" / "_shared"))
    import hestia_gate_core as core

    ws = args.workspace.rstrip("/")
    prof = core.HarnessProfile(member_id="claude-code",
                               identity_path="/nonexistent/identity.json",
                               home_markers=("~/.claude",))
    pol = core.AgentPolicy(member_id="claude-code", scope=(args.granted,), source="driver")

    def verdict(tool, paths):
        ev = core.NormalizedEvent(tool=tool, paths=paths, command=None, cwd=ws, raw={})
        return core.evaluate(ev, prof, workspace=ws, policy=pol)

    # (tool, the key the destination really arrives under, destination)
    #
    # Every one of these was observed in the local transcripts by
    # `tools/path_key_vocabulary_probe.py`; none of the four keys is enumerated by any gate
    # except gemini, and `pattern` is left out here deliberately because Glob/Grep are
    # READ_CLASS -- the policy declares those free, so they are not a hole.
    CASES = [
        ("mcp__playwright__browser_take_screenshot", "filename",
         f"{ws}/{args.ungranted}/website/_screens/home-full.png"),
        ("SendUserFile", "files",
         f"{ws}/{args.ungranted}/pitch-deck/Metalinxx_Pitch_VersionE.pdf"),
        ("ExitPlanMode", "planFilePath", str(Path.home() / ".claude" / "plans" / "p.md")),
        ("mcp__gitnexus__detect_changes", "repo", f"{ws}/{args.ungranted}/.wt/x"),
    ]

    print(f"workspace {ws}   scope ({args.granted!r},)   ungranted repo {args.ungranted!r}\n")
    print(f"{'tool':44} {'key':14} {'as built':9} {'extracted':9} disagrees")
    print("-" * 92)
    disagreements = 0
    for tool, key, dest in CASES:
        if not core.needs_society_gate(tool) or tool in core.READ_CLASS:
            print(f"{tool[:44]:44} {key:14} (not gated by policy -- skipped)")
            continue
        as_built = verdict(tool, []).decision
        extracted = verdict(tool, [dest]).decision
        differs = as_built != extracted
        disagreements += differs
        print(f"{tool[:44]:44} {key:14} {as_built:9} {extracted:9} "
              f"{'YES' if differs else 'no'}")

    # The control. `Write` puts its destination under `file_path`, which every gate
    # enumerates, so the engine sees it and denies. Nothing about the destination differs --
    # only whether the key was on somebody's list.
    ctrl = f"{ws}/{args.ungranted}/x.png"
    print(f"\ncontrol  Write file_path={ctrl}\n"
          f"         -> {verdict('Write', [ctrl]).decision}  "
          f"(same directory, enumerated key)")

    print()
    if disagreements:
        print(f"{disagreements} case(s) where the verdict was decided by the key name and "
              f"not by the policy.")
        print("The engine is right in every extracted column. The domain it is handed is "
              "what is wrong.")
    else:
        print("No disagreement in this set. That is a measured zero for THESE keys, not for "
              "the tool surface.")
    return 1 if disagreements else 0


if __name__ == "__main__":
    raise SystemExit(main())
