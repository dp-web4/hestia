#!/usr/bin/env python3
"""Non-executing classifier checks for PR #1232 / notices 20966 and 20978.

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
    # Conservative request accepted at 20978: the observed no-splitting behavior
    # need not become an allowance promised by the classifier.
    ("ifs-array-conservative-request", "IFS[0]=:; S=/tmp:/etc; cat $S/hostname", False),
    ("ifs-loop-binding", "S=/tmp:/etc; for IFS in :; do cat $S/hostname; done", False),
    ("ifs-array-quoted-control", 'IFS[0]=:; S=/tmp:/etc; cat "$S/hostname"', True),
    ("ifs-loop-quoted-control", 'S=/tmp:/etc; for IFS in :; do cat "$S/hostname"; done', True),
    ("ordinary-ifs-assignment-control", "IFS=:; S=/tmp:/etc; cat $S/hostname", False),
    ("default-ifs-control", "S=/tmp:/etc; cat $S/hostname", True),
    ("ifs-for-positional", "S=/tmp:/etc; for IFS; do cat $S/hostname; done", False),
    ("ifs-select", "S=/tmp:/etc; select IFS in :; do cat $S/hostname; break; done", False),
    ("ifs-exec-fd", "S=/tmp1/etc; exec {IFS}>/dev/null; cat $S/hostname", False),
    ("ifs-coproc", "S=/tmp1/etc; coproc IFS { :; }; cat $S/hostname", False),
    ("ifs-wait-p", "S=/tmp1/etc; sleep 0 & wait -n -p IFS; cat $S/hostname", False),
    ("ifs-case", "S=/tmp:/etc; case : in *) IFS=: ;; esac; cat $S/hostname", False),
    ("ifs-continuation-assignment", "S=/tmp:/etc; I\\\nFS=:; cat $S/hostname", False),
    ("ifs-continuation-loop", "S=/tmp:/etc; for I\\\nFS in :; do cat $S/hostname; done", False),
    ("ifs-continuation-fd", "S=/tmp1/etc; exec {I\\\nFS}>/dev/null; cat $S/hostname", False),
    ("ifs-two-continuations", "S=/tmp:/etc; for I\\\nF\\\nS in :; do cat $S/hostname; done", False),
    ("ifs-comment-conservative-request", "S=/tmp/x; # IFS\ncat $S/hostname", False),
    ("ifs-comment-quoted-control", 'S=/tmp/x; # IFS\ncat "$S/hostname"', True),
    ("ifs-substring-conservative-request", "S=/tmp/IFS-review; cat $S/hostname", False),
    ("ifs-substring-quoted-control", 'S=/tmp/IFS-review; cat "$S/hostname"', True),
]

if __name__ == "__main__":
    if sys.argv[1:] == ["--argv-proof"]:
        import json
        import subprocess

        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        prefix = "cat() { printf '%s\\0' \"$@\"; }; "
        for name, command, _ in regressions.CASES:
            # Only these deterministic, side-effect-free forms are argv proofs.
            # fd/coprocess/wait/select cases remain classifier inputs only.
            if name not in {"ifs-array-conservative-request", "ifs-loop-binding",
                            "ifs-array-quoted-control", "ifs-loop-quoted-control",
                            "ordinary-ifs-assignment-control", "default-ifs-control",
                            "ifs-continuation-assignment", "ifs-continuation-loop",
                            "ifs-two-continuations"}:
                continue
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c",
                                     prefix + command], env=env, capture_output=True,
                                    check=True, timeout=5)
            print(json.dumps({"case": name, "command": command,
                              "argv": result.stdout.decode().split("\0")[:-1]}))
        sys.exit(0)
    sys.exit(regressions.main())
