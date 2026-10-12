#!/usr/bin/env python3
"""Non-executing classifier checks for PR #1232 / notice 20966.

Same in-memory candidate reconstruction and disposable policy stub as the
original runner. Classifier mode never executes the command strings below.
--argv-proof instead uses Bash with cat replaced by an argument-printing
function: no represented file is opened.
"""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
path = Path(__file__).with_name("scope-1232-shell-regressions.py")
spec = importlib.util.spec_from_file_location("scope_regressions", path)
regressions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regressions)
regressions.CASES = [
    ("ifs-array-no-splitting-control", "IFS[0]=:; S=/tmp:/etc; cat $S/hostname", True),
    ("ifs-loop-binding", "S=/tmp:/etc; for IFS in :; do cat $S/hostname; done", False),
    ("ifs-array-quoted-control", 'IFS[0]=:; S=/tmp:/etc; cat "$S/hostname"', True),
    ("ifs-loop-quoted-control", 'S=/tmp:/etc; for IFS in :; do cat "$S/hostname"; done', True),
    ("ordinary-ifs-assignment-control", "IFS=:; S=/tmp:/etc; cat $S/hostname", False),
    ("default-ifs-control", "S=/tmp:/etc; cat $S/hostname", True),
]

if __name__ == "__main__":
    if sys.argv[1:] == ["--argv-proof"]:
        import json
        import subprocess

        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        prefix = "cat() { printf '%s\\0' \"$@\"; }; "
        for name, command, _ in regressions.CASES:
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c",
                                     prefix + command], env=env, capture_output=True,
                                    check=True, timeout=5)
            print(json.dumps({"case": name, "command": command,
                              "argv": result.stdout.decode().split("\0")[:-1]}))
        sys.exit(0)
    sys.exit(regressions.main())
