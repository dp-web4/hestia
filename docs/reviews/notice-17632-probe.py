#!/usr/bin/env python3
"""Read-only producer probe for notice 17632. Usage: python3 this.py PATCH.

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
EXPECTED = "863c5296e1c9d1b34d5e252a6b59b5fe3ffe797d5f654cfc100a10359f81f6fa"
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


def probe(label, command, tool="Bash", tool_input=None):
    ti = tool_input or {"command": command}
    event = gate.GateEvent(tool, ti, cwd="/w")
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
pad = " ".join("/tmp/pad" + str(i) for i in range(25))
control = probe("fixed multi-target shell", f"touch {ordinary} {pad} {strong}")
assert control["wire"] == [ordinary, strong]
assert "hestia_single_gate.py" not in control["summary"]

paths = [ordinary, strong, "/tmp/" + "x" * 150 + ".txt"]
body = "*** Begin Patch\n" + "".join(
    "*** Update File: " + p + "\n@@\n-a\n+b\n" for p in paths
) + "*** End Patch\n"
control = probe("fixed multi-target patch", None, "apply_patch", {"input": body})
assert control["wire"] == [ordinary, strong]

for command in ("touch /w/plugins/_shared/$TARGET",
                'touch /w/plugins/_shared/ordinary.txt; touch "$TARGET"'):
    result = probe("P1 unenumerated marked complete", command)
    assert result["rule"] == closure.RULE_OUT_OF_GRAMMAR
    assert result["complete"] is True
    assert not any(t.startswith(mechanism.UNPRICEABLE_PREFIX) for t in result["wire"])
    assert "hestia_single_gate.py" not in json.dumps(result)

alias = "/w/alias.txt"
realpath = closure.os.path.realpath
with patch.object(closure.os.path, "realpath",
                  side_effect=lambda p: strong if p == alias else realpath(p)):
    result = probe("P1 resolved alias discarded (modeled realpath)", "touch " + alias)
assert result["marker"] == "plugins/_shared"
assert result["wire"] == [alias]
assert result["complete"] is True
assert "hestia_single_gate.py" not in json.dumps(result)
print("Both remaining pricing-evidence gaps reproduced; no live claims or writes performed.")
