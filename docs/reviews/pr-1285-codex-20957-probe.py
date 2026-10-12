#!/usr/bin/env python3
"""Offline follow-up probes for #1285: rejected publish and unavailable state read."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "release_publish_review", ROOT / "tools/release_publish_test.py"
)
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)
original = test.FAKE_GH
patch = 'if method == "PATCH" and endpoint == base:\n'
read = 'if method == "GET" and endpoint == base:'
assert original.count(patch) == original.count(read) == 1

with tempfile.TemporaryDirectory() as directory:
    # Refused before applying: the read must show the release still is a draft.
    test.FAKE_GH = original.replace(patch, patch +
        '    if fields.get("draft") is False:\n'
        '        save(); print("HTTP 500: publish rejected", file=sys.stderr); sys.exit(1)\n')
    rc, rel, calls, out = test.run_case(Path(directory), "v0.3.0")
    assert rc == 1 and rel["draft"] is True, out
    assert "now reads draft=true" in out and "fix by hand" in out, out
    assert "is left as a DRAFT and was NOT published" not in out, out
    print("PASS: rejected publish reports re-read draft=true")

    # Applied publish, lost response, then a failed re-read: never infer its state.
    test.FAKE_GH = original.replace(read,
        'if method == "GET" and endpoint == base and not rel["draft"]:\n'
        '    save(); print("HTTP 503: state unavailable", file=sys.stderr); sys.exit(1)\n'
        + read)
    rc, rel, calls, out = test.run_case(Path(directory), "v0.3.0", extra_env={
        "MOCK_GH_PUBLISH_APPLIED_THEN_FAILS": "1"})
    assert rc == 1 and rel["draft"] is False, out
    assert "state is UNKNOWN" in out and "fix by hand" in out, out
    assert "is left as a DRAFT and was NOT published" not in out, out
    print("PASS: lost publish response plus unavailable re-read reports UNKNOWN")
