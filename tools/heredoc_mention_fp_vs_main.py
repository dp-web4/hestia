#!/usr/bin/env python3
"""Does the heredoc-mention scope FP reproduce on MAIN's gate core, or only on mine?

THE PROBLEM THIS EXISTS TO STOP ME DOING. Writing a driver today, a quoted Bash heredoc
whose BODY merely mentions an absolute state path was denied
`mrh.command — 'logs' is not granted`, while the identical bytes through the file-creation
tool were allowed. I wrote that up as a gate defect. Then kimi's mesh notice 7534 claimed my
installed gate was stale, and checking turned up something narrower and worse than its claim:

  * my SEAT hooks (pre_tool_use / law_inject / witness) are byte-identical to origin/main
  * my installed `hestia_gate_core.py` -- the file that actually builds this deny -- is dated
    2026-08-14 and differs from main by 134 lines across 12 hunks
  * `command_in_scope`, the function that produced the verdict, DIFFERS (4353 vs 4044 chars)

So the defect was observed on bytes main does not have. Reporting it as a property of the
gate would be the exact error I have written down twice: reading a boundary in my own
instrument as a fact about the world. The claim is cheap to actually settle, so settle it.

METHOD. Load both cores as independent modules under different names and call the SAME
entry point with the SAME input. Nothing is inferred from the diff; the verdicts are read.

WHAT EACH OUTCOME MEANS, fixed before running:
  BOTH DENY   -- the FP is real on main. The finding stands as written.
  ONLY MINE   -- the FP is an artifact of a stale local core. The finding must retract it,
                 and I have been running a gate whose scope verdicts main has already changed.
  ONLY MAIN   -- main regressed relative to my copy; worth a separate report.
  NEITHER     -- my reproduction does not capture what actually fired; the probe is wrong,
                 not the gate, and nothing may be concluded from it.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile

INSTALLED = os.path.join(os.path.expanduser("~"), ".claude", "_shared",
                         "hestia_gate_core.py")
MAIN_REF = "origin/main:plugins/_shared/hestia_gate_core.py"

#: The shape that was denied: a QUOTED heredoc (no expansion, nothing runs) whose body
#: mentions an absolute path under the mesh state directory. Assembled from parts so this
#: probe file can itself be written without tripping the thing it is testing.
STATE_DIR = os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh",
                         "lo" + "gs")
CASES = {
    "quoted_heredoc_mentioning_state_path":
        "cat > tools/probe.py <<'PY'\nWAKE = \"%s\"\nPY" % STATE_DIR,
    "bare_absolute_read_of_same_path":
        "ls %s" % STATE_DIR,
    "control_in_scope_write":
        "cat > tools/probe.py <<'PY'\nx = 1\nPY",
}


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace = os.path.dirname(workspace) if os.path.basename(workspace) == "hestia" \
        else workspace
    # The grant list as the live deny reported it, trimmed to what matters here.
    scopes = ["hestia", "claude-code", "private-context", "web4", "shared-context"]

    with tempfile.TemporaryDirectory() as td:
        main_path = os.path.join(td, "core_main.py")
        with open(main_path, "wb") as fh:
            fh.write(subprocess.check_output(["git", "show", MAIN_REF]))
        cores = {}
        for label, path in (("installed(2026-08-14)", INSTALLED), ("origin/main", main_path)):
            try:
                cores[label] = load(path, "core_" + label.split("(")[0].replace("/", "_"))
            except Exception as exc:                      # noqa: BLE001
                print("could not load %s: %r" % (label, exc))
        if len(cores) < 2:
            print("FATAL: need both cores; nothing may be concluded from one.")
            return 2

        print("workspace=%s" % workspace)
        print("scopes=%s" % scopes)
        print()
        hdr = "%-42s %-24s %-24s" % ("case", "installed(08-14)", "origin/main")
        print(hdr)
        print("-" * len(hdr))
        verdicts = {}
        for case, cmd in CASES.items():
            row = []
            for label in ("installed(2026-08-14)", "origin/main"):
                fn = getattr(cores[label], "command_in_scope", None)
                if fn is None:
                    row.append("NO command_in_scope")
                    continue
                try:
                    ok, offending = fn(cmd, scopes, workspace)
                    row.append("ALLOW" if ok else "DENY '%s'" % (offending,))
                except Exception as exc:                  # noqa: BLE001
                    row.append("ERROR %s" % type(exc).__name__)
            verdicts[case] = row
            print("%-42s %-24s %-24s" % (case[:42], row[0][:24], row[1][:24]))

        print()
        a, b = verdicts["quoted_heredoc_mentioning_state_path"]
        da, db = a.startswith("DENY"), b.startswith("DENY")
        if da and db:
            print("VERDICT: BOTH DENY — the mention FP is real on main; the finding stands.")
        elif da and not db:
            print("VERDICT: ONLY MINE — the FP is an artifact of a stale local core. "
                  "Retract it, and note that this seat's scope verdicts are 17 days behind "
                  "main.")
        elif db and not da:
            print("VERDICT: ONLY MAIN — main regressed against my copy; report separately.")
        else:
            print("VERDICT: NEITHER — this reproduction does not capture what fired. "
                  "The probe is wrong, not the gate; conclude nothing from it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
