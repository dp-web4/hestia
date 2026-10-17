import sys, pathlib, difflib, hashlib, subprocess
WT = pathlib.Path("/home/dp/ai-workspace/hestia/scratchpad/s1314e-base")
S = pathlib.Path("/tmp/s1314e")
sys.path.insert(0, str(WT / "tools"))
SERVE = {str(WT / "plugins/_shared/hestia_gate_core.py"): S / "core_rev.py"}
_orig = pathlib.Path.read_bytes
def rb(self):
    t = SERVE.get(str(self))
    return _orig(t) if t else _orig(self)
pathlib.Path.read_bytes = rb
_orig_rt = pathlib.Path.read_text
def rt(self, *a, **k):
    t = SERVE.get(str(self))
    return _orig_rt(t, *a, **k) if t else _orig_rt(self, *a, **k)
pathlib.Path.read_text = rt
import hooks_gt
out = S / "gt.patch"
n = hooks_gt.emit_patch(WT, out)
parts = [out.read_text()]
for rel, new in (("plugins/_shared/hestia_gate_core.py", "core_rev.py"),
                 ("tools/shell_scope_reach_battery_test.py", "battery_rev.py"),
                 ("tools/one_gate_decide_contract_test.py", "contract_held.py")):
    a = _orig_rt(WT / rel).splitlines(True)
    b = _orig_rt(S / new).splitlines(True)
    d = "".join(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}"))
    parts.append(f"diff --git a/{rel} b/{rel}\n" + d)
data = "".join(parts).encode()
h = hashlib.sha256(data).hexdigest()
(S / f"{h}.patch").write_bytes(data)
print(n, "gt chunks;", h)
