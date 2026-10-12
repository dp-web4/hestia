#!/usr/bin/env python3
"""No-install regression probes for #1279; run from any working directory.

Uses the submitted helper's extracted installer functions and temporary stubs.
Exits nonzero while the source-build/prerelease downgrade hold remains open.
"""
from pathlib import Path
import sys

helper = Path(__file__).resolve().parents[2] / "deploy/fleet/install_version_test.py"
ns = {"__file__": str(helper)}
exec(compile(helper.read_text().split("LATEST =", 1)[0], str(helper), "exec"), ns)
run = ns["run"]

cases = [
    ("source build to pinned release", dict(installed="0.0.4", pin="v0.0.4"), False),
    ("source build to latest release", dict(installed="0.0.4", api_json='\n  "tag_name": "v0.0.4"\n'), False),
    ("source build to fallback release", dict(installed="0.0.4"), False),
    ("stable release to prerelease", dict(raw_version="hestia 0.0.4 (v0.0.4)", pin="v0.0.4-rc.1"), False),
    ("unrecognized target suffix", dict(raw_version="hestia 0.0.4 (v0.0.4)", pin="v0.0.4-not-a-release"), False),
    ("genuine same-release reinstall", dict(raw_version="hestia 0.0.4 (v0.0.4)", pin="v0.0.4"), True),
    ("older stable release upgrade", dict(raw_version="hestia 0.0.3 (v0.0.3)", pin="v0.0.4"), True),
    ("explicit source-build downgrade override", dict(installed="0.0.4", pin="v0.0.4", allow="1"), True),
]

failures = 0
for name, kwargs, should_proceed in cases:
    rc, output = run(**kwargs)
    ok = (rc == 0) == should_proceed
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: rc={rc}, output={output.strip()!r}")
print(f"{len(cases) - failures}/{len(cases)} passed; {failures} failed")
sys.exit(bool(failures))
