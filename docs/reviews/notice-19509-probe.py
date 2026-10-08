#!/usr/bin/env python3
"""Read-only producer probe for notice 19509. Usage: python3 this.py PATCH.

Run in the repository at the reviewed revision. Applies the supplied patch only
in memory, imports those sources, and stubs all claim transport. The alias case
models realpath's result; it creates no symlink and writes no governed file.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PATCH = Path(sys.argv[1])
EXPECTED = "ca833c340ab5fc61a14d9bade234869ec68c848ef46b081a05a1bf7905402b09"
assert hashlib.sha256(PATCH.read_bytes()).hexdigest() == EXPECTED
sources = {}
for block in PATCH.read_text().split("diff --git ")[1:]:
    lines = block.splitlines(True)
    name = lines[0].split()[1][2:]
    old = (ROOT / name).read_text().splitlines(True)
    out, at = [], 0
    i = next(i for i, line in enumerate(lines) if line.startswith("@@"))
    while i < len(lines):
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[i])
        assert m, (name, lines[i])
        start = int(m[1]) - 1
        out.extend(old[at:start])
        at, i = start, i + 1
        while i < len(lines) and not lines[i].startswith("@@"):
            tag, value = lines[i][0], lines[i][1:]
            if tag in " -":
                assert old[at] == value, (name, at)
                at += 1
            if tag in " +":
                out.append(value)
            i += 1
    out.extend(old[at:])
    sources[name] = "".join(out)
print("Patch digest and exact context: PASS")

# Compare the recovered reviewed patch with the new one by exact diff blocks.
# Only these two test files may differ; all production/manifest blocks must match.
lineage = ROOT / "held/lineage/2e0547b59fdec7fc642884a375caeca80e54a8ff49405889bfba74785ae6d8ed.patch"
assert hashlib.sha256(lineage.read_bytes()).hexdigest() == lineage.stem

def blocks(data):
    return {block.splitlines()[0].split()[1][2:]: block
            for block in data.split("diff --git ")[1:]}

before, after = blocks(lineage.read_text()), blocks(PATCH.read_text())
assert before.keys() == after.keys()
changed = {name for name in before if before[name] != after[name]}
assert changed == {"plugins/_shared/claim_self_write_test.py",
                   "plugins/_shared/seat_gate_boundary_test.py"}, changed
print(f"Recovered lineage: {len(before) - len(changed)}/{len(before)} diff blocks byte-identical; only two test blocks differ")

shared = ROOT / "plugins/_shared"
sys.path.insert(0, str(shared))
for name in ("hestia_governance_closure", "hestia_gate_mechanism", "hestia_single_gate"):
    path = shared / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(sources["plugins/_shared/" + name + ".py"], str(path), "exec"), module.__dict__)

closure = sys.modules["hestia_governance_closure"]
mechanism = sys.modules["hestia_gate_mechanism"]
gate = sys.modules["hestia_single_gate"]
closure.default_closure = lambda: closure.LITERAL_FLOOR
seen = []
mechanism.gate_self_call = lambda name, args, **kw: seen.append(args) or {
    "claimed": False, "escalation_id": "fixture"
}


def probe(label, command, tool="Bash", tool_input=None, cwd="/w"):
    ti = tool_input or {"command": command}
    event = gate.GateEvent(tool, ti, cwd=cwd)
    verdict = gate._closure_view(event)
    targets, complete = gate._closure_write_set(event)
    summary = mechanism.attempted_summary(
        tool, ti, command=command,
        targets=gate._patch_targets(tool, ti) if tool == "apply_patch" else None,
    )
    mechanism.claim_self_write(
        verdict.marker, tool, summary, plugin_id="fixture", role="fixture",
        client_name="fixture", resolved_targets=targets,
        resolved_targets_complete=complete,
    )
    result = dict(label=label, rule=verdict.rule, marker=verdict.marker,
                  summary=summary, complete=complete,
                  wire=seen[-1].get("resolved_targets", []))
    print(json.dumps(result, sort_keys=True))
    return result


strong = "/w/plugins/_shared/hestia_single_gate.py"
ordinary = "/w/plugins/_shared/ordinary.txt"
failures = []
def check(label, condition):
    print(("PASS: " if condition else "FAIL: ") + label)
    if not condition:
        failures.append(label)

pad = " ".join("/tmp/pad" + str(i) for i in range(25))
r = probe("multi-target shell control", f"touch {ordinary} {pad} {strong}")
check("multi-target shell carries later gate", r["wire"] == [ordinary, strong])
paths = [ordinary, strong, "/tmp/" + "x" * 150 + ".txt"]
body = "*** Begin Patch\n" + "".join(
    "*** Update File: " + p + "\n@@\n-a\n+b\n" for p in paths
) + "*** End Patch\n"
r = probe("multi-target patch control", None, "apply_patch", {"input": body})
check("multi-target patch carries later gate", r["wire"] == [ordinary, strong])
for command in ("touch /w/plugins/_shared/$TARGET",
                'touch /w/plugins/_shared/ordinary.txt; touch "$TARGET"'):
    r = probe("unknown destinations", command)
    check(command + " is unenumerated",
          r["complete"] is False and mechanism.UNPRICEABLE_PREFIX + "unenumerated" in r["wire"])
alias = "/w/alias.txt"
realpath = closure.os.path.realpath
with patch.object(closure.os.path, "realpath",
                  side_effect=lambda p: strong if p == alias else realpath(p)):
    r = probe("resolved alias (modeled realpath)", "touch " + alias)
check("alias carries canonical destination", r["wire"] == [alias, strong])
r = probe("glob target control", "rm /w/plugins/_shared/*.py")
check("glob carried to daemon", r["wire"] == ["/w/plugins/_shared/*.py"])
r = probe("relative target without cwd", "touch plugins/_shared/ordinary.txt", cwd=None)
check("relative without cwd is unenumerated",
      r["complete"] is False and mechanism.UNPRICEABLE_PREFIX + "unenumerated" in r["wire"])
r = probe("absolute control", "touch " + ordinary)
check("absolute stays complete", r["complete"] and r["wire"] == [ordinary])
print(f"{8-len(failures)}/8 checks passed; no live claims or governed writes performed.")
sys.exit(bool(failures))
