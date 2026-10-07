#!/usr/bin/env python3
"""Isolated producer -> Rust pricing probes for #1247 at 18f91db.

No live transport, installed writes, or shell execution of the classified acts.
Uses the real producer, stubs its transport, and compiles the reviewed Rust
pricing functions verbatim (only the Bar serde derives are omitted).
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/_shared"))
import hestia_governance_closure as closure
import hestia_gate_mechanism as mechanism
import hestia_single_gate as gate


def compile_price(directory):
    source = (ROOT / "core/src/server/gate_escalation.rs").read_text()
    bar = source[source.index("pub enum Bar {"):source.index("// The DECLARATION ORDER")]
    functions = source[source.index("pub fn bar_for(marker:"):
                       source.index("/// The longest resolved target recorded")]
    main = '''
fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let (bar, markers) = price(&a[0], Some(&a[1]), &a[2..]);
    println!("{bar:?} {markers:?}");
}
'''
    path = directory / "pricing.rs"
    binary = directory / "pricing"
    path.write_text("#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]\n"
                    + bar + functions + main)
    subprocess.run(["rustc", "--edition=2021", str(path), "-o", str(binary)], check=True)
    return binary


def capture(command, *, cwd="/w", registered=None):
    seen = []
    def transport(name, args, **kw):
        seen.append(args)
        return {"claimed": False, "permits_write": False, "escalation_id": "fixture"}
    event = gate.GateEvent("Bash", {"command": command}, cwd=cwd)
    inv = gate._Invocation(event, gate.GateProfile("gemini", None), "enforce",
                           time.monotonic() + 20, "fixture",
                           attempted=gate.attempted_of(event), registered=registered)
    with patch.object(mechanism, "gate_self_call", transport), \
         patch.object(mechanism, "witness_gate_self", return_value=True):
        decision = gate._governance_closure(inv)
    assert decision is not None and len(seen) == 1, (decision, seen)
    claim = seen[0]
    return claim


def main():
    failures = []
    with tempfile.TemporaryDirectory(prefix="codex-18786-price-") as temp:
        binary = compile_price(Path(temp))
        def check(label, command, expected, **kwargs):
            claim = capture(command, **kwargs)
            result = subprocess.check_output(
                [str(binary), claim["marker"], claim["reason"],
                 *claim.get("resolved_targets", [])], text=True).strip()
            ok = result.split()[0] == expected
            print(json.dumps({"label": label, "pass": ok, "expected": expected,
                              "price": result, "targets": claim.get("resolved_targets", [])}))
            if not ok:
                failures.append(label)

        declared = "/home/review/.gemini/hestia-plugins/gemini/hooks"
        legacy = "/home/review/.hestia/members/gemini"
        entry = legacy + "/before_tool.py"
        registered = gate.RegisteredSurface(entry, (legacy,), (entry,), (entry,))
        strong = "SovereignPlusPeer"
        weak = "SingleApprover"
        check("declared-relative-entry", "touch before_tool.py", strong, cwd=declared)
        for order in ("ordinary.txt before_tool.py", "before_tool.py ordinary.txt"):
            check("multi-target-" + order.split()[0], "touch " + order, strong, cwd=declared)
        check("registered-literal", "touch " + entry, strong, registered=registered)
        check("registered-glob", "touch " + legacy + "/before_*", strong, registered=registered)
        check("registered-glob-negative-control", "touch " + legacy + "/after_*", weak,
              registered=registered)
        check("declared-glob-control", "touch " + declared + "/before_*", strong)
        check("unknown-in-protected-dir", "touch " + declared + "/$TARGET", strong)
        check("unknown-later-target", 'touch ' + declared + '/ordinary.txt; touch "$TARGET"', strong)
        check("relative-without-cwd", "touch plugins/_shared/ordinary.txt", strong, cwd=None)
        alias = "/w/alias.txt"
        canonical = "/w/plugins/_shared/hestia_single_gate.py"
        realpath = closure.os.path.realpath
        with patch.object(closure.os.path, "realpath",
                          side_effect=lambda p: canonical if p == alias else realpath(p)):
            check("canonical-alias-control", "touch " + alias, strong)
        for label, act, targets in (
            ("text-only-bracket-glob", "Bash: rm /w/plugins/_shared/[pq]re_tool_use.py", []),
            ("resolved-bracket-glob-control", "Bash: omitted",
             ["/w/plugins/_shared/[pq]re_tool_use.py"]),
        ):
            result = subprocess.check_output(
                [str(binary), "plugins/_shared", act, *targets], text=True).strip()
            ok = result.split()[0] == strong
            print(json.dumps({"label": label, "pass": ok, "price": result}))
            if not ok:
                failures.append(label)
    print(f"{len(failures)} failed invariants: {', '.join(failures)}")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
