"""Read-only producer probe: python3 docs/reviews/notice-17101-probe.py PATCH.

Run at daemon commit 8fe646e. Applies the producer diff in memory only; claims
use a stub, and no governance source or installed hook is written.
"""
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import types

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[2]
patch = Path(sys.argv[1]).read_text()
assert hashlib.sha256(patch.encode()).hexdigest() == "d39341b1551b404e74ba27674766e9610cbbc370301970ba7eb1c25567c9f2df"
patched = {}
for part in patch.split("diff --git ")[1:]:
    lines = part.splitlines(True)
    name = lines[0].split()[0][2:]
    old = (root / name).read_text().splitlines(True)
    out, at, i = [], 0, 3
    while i < len(lines):
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
        assert m, (name, lines[i])
        start = int(m[1]) - 1
        out.extend(old[at:start])
        at, i = start, i + 1
        while i < len(lines) and not lines[i].startswith("@@"):
            tag, val = lines[i][0], lines[i][1:]
            if tag in " -":
                assert old[at] == val, (name, at)
                at += 1
            if tag in " +":
                out.append(val)
            i += 1
    out.extend(old[at:])
    patched[name] = "".join(out)
print("Exact patch context: PASS", len(patched), "files")
for name, source in patched.items():
    if name.endswith(".py"):
        compile(source, name, "exec")
print("Python syntax: PASS")
for name in ("hestia_gate_mechanism.py", "hestia_single_gate.py"):
    source = patched["plugins/_shared/" + name]
    gt = patched["hooks-gt/_shared/" + name]
    clean = "".join(line for line in gt.splitlines(True)
                    if not line.startswith("# hestia-gt-sha256: "))
    print("GT source equality", name, clean == source)
    if clean != source:
        print("".join(difflib.unified_diff(source.splitlines(True), clean.splitlines(True))))
    manifest = json.loads(patched["hooks-gt/_shared/manifest.json"])
    expected = next(x["sha256"] for x in manifest["files"] if x["path"] == name)
    normalized = re.sub(r"(hestia-gt-sha256: )[0-9a-f]{64}",
                        lambda m: m[1] + "0" * 64, gt)
    assert hashlib.sha256(normalized.encode()).hexdigest() == expected
    print("GT normalized manifest hash: PASS")
sys.path.insert(0, str(root / "plugins/_shared"))
for name in ("hestia_gate_mechanism", "hestia_single_gate"):
    mod = types.ModuleType(name)
    mod.__file__ = str(root / "plugins/_shared" / (name + ".py"))
    sys.modules[name] = mod
    exec(compile(patched["plugins/_shared/" + name + ".py"], mod.__file__, "exec"), mod.__dict__)
mech = sys.modules["hestia_gate_mechanism"]
gate = sys.modules["hestia_single_gate"]
seen = []
mech.gate_self_call = lambda name, args, **kw: seen.append(args) or {"claimed": False, "escalation_id": "fixture"}
for target in ["/w/plugins/kimi/hooks/pre_tool_use.py", None, "   ",
               "/w/credential-fixture/plugins/kimi/hooks/pre_tool_use.py",
               "/" + "d" * 900 + "/pre_tool_use.py"]:
    mech.claim_self_write("plugins/*/hooks", "Bash", "Bash: bounded summary",
                          plugin_id="fixture", role="fixture", client_name="fixture",
                          resolved_target=target)
    print("Target input:", repr(target if not target or len(target) < 120 else "<long>/pre_tool_use.py"),
          "wire:", repr(seen[-1].get("resolved_target")))
cmd = "touch /w/plugins/_shared/ordinary.txt " + " ".join(
    "/tmp/padding-" + str(i) for i in range(25)) + " /w/plugins/_shared/hestia_single_gate.py"
ev = gate.GateEvent("Bash", {"command": cmd}, cwd="/w")
cv = gate._closure_view(ev)
summary = mech.attempted_summary(ev.tool, ev.tool_input, command=cmd)
print("Multi-write shell:", json.dumps({"marker": cv.marker, "resource": cv.resource, "summary": summary}))
paths = ["/w/plugins/_shared/ordinary.txt", "/w/plugins/_shared/hestia_single_gate.py",
         "/tmp/" + "x" * 150 + ".txt"]
body = "*** Begin Patch\n" + "".join("*** Update File: " + x + "\n@@\n-a\n+b\n" for x in paths) + "*** End Patch\n"
ev = gate.GateEvent("apply_patch", {"input": body}, cwd="/w")
cv = gate._closure_view(ev)
summary = mech.attempted_summary(ev.tool, ev.tool_input, targets=gate._patch_targets(ev.tool, ev.tool_input))
print("Multi-write patch:", json.dumps({"marker": cv.marker, "resource": cv.resource, "summary": summary}))
