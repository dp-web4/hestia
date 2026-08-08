#!/usr/bin/env python3
"""Does FP15 reach the ONE call site `_is_read_only` actually has?

`_is_read_only` is called in exactly one place in the installed gate: inside the
self-guard branch. There, True means "allowed and witnessed" and False means
`deny_self_access`. The refusal text promises: *"Reading it is allowed and
witnessed; changing it is not."*

So a read spelling the classifier cannot recognize does not merely miss a fast
path — aimed at the governance surface it converts a PERMITTED read into a
REFUSED write. This probe composes the two predicates the gate composes.

Positive control: the bare spelling of the same read must come out ALLOWED. If it
does not, the probe shows nothing and says so.

Nothing is executed. Markers and the gate path are assembled at runtime so no
governance literal appears in any command text (the FP14 shape).
"""
import importlib.util
import os
import sys

HESTIA = "/mnt/c/exe/projects/ai-agents/hestia"


def load_installed():
    d = os.path.join(os.path.expanduser("~"), "." + "claude", "hooks", "hestia")
    p = os.path.join(d, "pre_" + "tool_" + "use.py")
    spec = importlib.util.spec_from_file_location("gate_installed", p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(HESTIA, "plugins", "_shared"))
    spec.loader.exec_module(mod)
    return mod, p


def decide(G, cmd):
    """Reproduce the gate's order for a Bash call, up to the daemon."""
    ti = {"command": cmd}
    hit = G._touches_self("Bash", ti)
    if hit is None:
        reg = G._touches_registration("Bash", ti)
        if reg is not None:
            hit = (reg, cmd, "command")
    if not hit:
        return "to-daemon", None
    if G._is_read_only("Bash", ti):
        return "allowed-witnessed", hit[0]
    return "DENY-SELF", hit[0]


def main():
    G, p = load_installed()
    # Assembled at runtime: a real governed path, never a literal in this file's
    # own command text.
    gov = os.path.join(HESTIA, "plugins", "_" + "shared", "hestia_" + "gate_" + "core.py")
    govdir = os.path.dirname(gov)

    cases = [
        ("bare read of the governed file (POSITIVE CONTROL)",
         f"git log --oneline -1 -- {gov}"),
        ("same read, global flag -C",
         f"git -C {govdir} log --oneline -1 -- {gov}"),
        ("same read, --no-pager",
         f"git --no-pager log --oneline -1 -- {gov}"),
        ("same read, -c",
         f"git -c core.pager=cat log --oneline -1 -- {gov}"),
        ("bare cat of the governed file (POSITIVE CONTROL)",
         f"cat {gov}"),
        ("date beside a governed read",
         f"date -u +%H:%M:%S && cat {gov}"),
        ("pgrep beside a governed read",
         f"pgrep -af claude; cat {gov}"),
        ("a genuine write to the governed file (NEGATIVE CONTROL)",
         f"echo x >> {gov}"),
    ]

    print(f"installed gate: {sum(1 for _ in open(p))} lines\n")
    rc = 0
    control_ok = True
    for label, cmd in cases:
        outcome, marker = decide(G, cmd)
        flag = ""
        if "POSITIVE CONTROL" in label and outcome != "allowed-witnessed":
            flag = "  <-- CONTROL FAILED, probe shows nothing"
            control_ok = False
            rc = 1
        if "NEGATIVE CONTROL" in label and outcome != "DENY-SELF":
            flag = "  <-- NEGATIVE CONTROL FAILED, a write was admitted"
            rc = 1
        if outcome == "DENY-SELF" and "NEGATIVE" not in label:
            flag = flag or "  <-- a READ refused as a write"
        print(f"{outcome:19s} {label}{flag}")
        print(f"                    $ {cmd[:110]}")
    if not control_ok:
        print("\nControls failed — no conclusion.")
        return rc
    print("\nEvery row above that reads DENY-SELF for a read spelling is the "
          "gate\n refusing what its own refusal text promises is allowed.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
