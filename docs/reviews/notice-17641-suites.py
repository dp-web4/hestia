#!/usr/bin/env python3
"""Run the patched producer suites without installing the producer patch.

Usage: python3 this.py PATCH SUITE [FIXTURE_BASE]
SUITE is claim_self_write_test, hestia_governance_closure_test or
seat_gate_boundary_test. For seat tests supply a writable non-/tmp fixture base.
Temporary overlay files are removed on exit; suite traffic goes to stub daemons.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
probe = Path(__file__).with_name("notice-17641-probe.py")
ns = {"__file__": str(probe)}
# Reuse the digest-checked exact-context patch reader, before it imports or stubs.
exec(probe.read_text().split("shared = ROOT")[0], ns)
root, sources = ns["ROOT"], ns["sources"]
for name, source in sources.items():
    if name.endswith(".py"):
        compile(source, name, "exec")
manifest = json.loads(sources["hooks-gt/_shared/manifest.json"])
for entry in manifest["files"]:
    source_name = entry["source"]
    if source_name not in sources:
        continue
    source = sources[source_name]
    published = sources["hooks-gt/_shared/" + entry["path"]]
    assert re.sub(r"^# hestia-gt-sha256:.*\n", "", published, flags=re.M) == source
    normalized = re.sub(r"(hestia-gt-sha256: )[0-9a-f]{64}",
                        lambda m: m[1] + "0" * 64, published)
    assert hashlib.sha256(normalized.encode()).hexdigest() == entry["sha256"]
print("Changed Python compilation and published engine hashes: PASS", flush=True)

suite = sys.argv[2]
assert suite in ("claim_self_write_test", "hestia_governance_closure_test",
                 "seat_gate_boundary_test")
shared = root / "plugins/_shared"
sys.path.insert(0, str(shared))
with tempfile.TemporaryDirectory(prefix="codex-17641-overlay-") as temp:
    overlay = {}
    for name in ("hestia_governance_closure", "hestia_gate_mechanism", "hestia_single_gate"):
        path = Path(temp) / (name + ".py")
        path.write_text(sources["plugins/_shared/" + name + ".py"])
        overlay[name] = str(path)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    os.environ["HESTIA_CONTRACT_REPO"] = str(root)
    os.environ["HESTIA_CONTRACT_OVERLAY"] = json.dumps(overlay)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    source = sources["plugins/_shared/" + suite + ".py"]
    if suite == "seat_gate_boundary_test":
        base = Path(sys.argv[3]).resolve()
        assert base.is_absolute() and not str(base).startswith("/tmp/")
        source = source.replace('os.path.expanduser("~/.cache/hestia-seat-boundary-tests")',
                                repr(str(base)))
    filename = str(shared / (suite + ".py"))
    exec(compile(source, filename, "exec"), {"__file__": filename, "__name__": "__main__"})
