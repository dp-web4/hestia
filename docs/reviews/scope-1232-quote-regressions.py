#!/usr/bin/env python3
"""Non-executing scope checks for PR #1232 / notice 20554.

The EOT character in classifier inputs is written with a Python escape. It is
ordinary shell word data, but collides with the candidate's quote marker.
Uses the same in-memory reconstruction and disposable stub as the prior runner.
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
    ("custom-ifs-splits-literal", "IFS=:; S=/tmp:/etc; cat $S/hostname", False),
    ("raw-quote-marker", 'S="/tmp/x /etc"; cat \x04$S/hostname', False),
    ("single-quoted-marker", 'S="/tmp/x /etc"; cat \'\x04\'$S/hostname', False),
    ("custom-ifs-quoted-control", 'IFS=:; S=/tmp:/etc; cat "$S/hostname"', True),
    ("whitespace-quoted-control", 'S="/tmp/x /etc"; cat "$S/hostname"', True),
    ("whitespace-unquoted-control", 'S="/tmp/x /etc"; cat $S/hostname', False),
    ("mixed-quoted-unquoted-control", 'S="/tmp/x /etc"; cat "$S"$S/hostname', False),
    ("newline-unquoted-control", 'S="/tmp/x\n/etc"; cat $S/hostname', False),
    ("simple-literal-control", 'S=/tmp/x; cat $S/hostname', True),
]

if __name__ == "__main__":
    sys.exit(regressions.main())
