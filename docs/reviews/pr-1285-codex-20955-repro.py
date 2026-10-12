#!/usr/bin/env python3
"""Review #1285: exercise successful and failed post-publication tag recovery.

Run from the reviewed checkout with Python 3. Uses its mocked-gh harness only;
no GitHub calls or actual releases. Exit 1 means the false-draft claim reproduces.
"""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "release_publish_review", ROOT / "tools/release_publish_test.py"
)
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)
original_mock = test.FAKE_GH
marker = 'if method == "PATCH" and endpoint == base:\n'
assert original_mock.count(marker) == 1
scenarios = {
    "successful re-bind": (
        '    if fields.get("draft") is False:\n'
        '        fields.pop("tag_name", None)\n'
    ),
    "re-bind HTTP 500": (
        '    if not rel["draft"] and "tag_name" in fields:\n'
        '        save(); print("HTTP 500: mock rebind failure", file=sys.stderr); sys.exit(1)\n'
        '    if fields.get("draft") is False:\n'
        '        fields.pop("tag_name", None)\n'
    ),
}
failures = 0
with tempfile.TemporaryDirectory() as directory:
    for name, injection in scenarios.items():
        test.FAKE_GH = original_mock.replace(marker, marker + injection)
        rc, release, calls, output = test.run_case(Path(directory), "v0.3.0")
        print(f"{name}: exit={rc}, draft={release['draft']}, tag={release['tag_name']}")
        print(output)
        assert release["draft"] is False
        if name == "successful re-bind":
            assert rc == 0 and release["tag_name"] == "v0.3.0"
        else:
            assert rc != 0 and release["tag_name"].startswith("untagged-")
            if "is left as a DRAFT and was NOT published" in output:
                print("FAIL: the diagnostic denies the publication that already occurred")
                failures += 1
raise SystemExit(bool(failures))
