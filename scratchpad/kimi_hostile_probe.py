#!/usr/bin/env python3
"""Hostile review probe (kimi-code, #1197 review): MY 25-act parity corpus against
claude-code's stage-B decide() — the cross-check that isn't their own test harness.

Baseline: tools/gate_parity_report.json (measured on main's four shims, PR #1195).
Any decide() verdict differing from the baseline cell is a HIT; each hit is then
checked against their DECLARED_DIVERGENCES semantics by hand.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

WT = pathlib.Path("/home/dp/ai-workspace/hestia/scratchpad/wt-onegate-review")
spec = importlib.util.spec_from_file_location("ogc", WT / "tools" / "one_gate_decide_contract_test.py")
ogc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ogc)

m, g, wc = ogc.load_engine()

corpus_src = subprocess.run(
    ["git", "-C", "/home/dp/ai-workspace/hestia", "show",
     "origin/kimi/gate-parity-corpus:tools/gate_parity_corpus.py"],
    capture_output=True, text=True, check=True).stdout
ns: dict = {}
exec(corpus_src, ns)
CORPUS = ns["CORPUS"]

baseline = {r["id"]: r for r in
            json.load(open("/home/dp/ai-workspace/hestia/tools/gate_parity_report.json"))["rows"]}

SEATS = ["claude-code", "kimi", "codex", "gemini"]
home = pathlib.Path(tempfile.mkdtemp(prefix="kimi-hostile-home-"))
(home / "identity.json").write_text(json.dumps({"role": "role:constellation:member"}))
scratch = tempfile.mkdtemp(prefix="kimi-hostile-scratch-")

import os
os.environ.setdefault("HESTIA_KIMI_LAUNCH_CWD", str(WT))
os.environ.setdefault("HESTIA_CODEX_LAUNCH_CWD", str(WT))
os.environ.setdefault("HESTIA_GEMINI_LAUNCH_CWD", str(WT))

# relaxed deadline for a loaded box; the contract suite's own convention
g.GATE_DEADLINE_SECONDS = ogc.RELAXED_DEADLINE_SECONDS

hits = []
rows_print = []
stub = ogc.Stub()
try:
    with ogc._Env(m, stub.url, home):
        for act_id, cls, tool, ti_tmpl, expected, note in CORPUS:
            for seat in SEATS:
                ti = json.loads(json.dumps(ti_tmpl)
                                .replace("{REPO}", str(WT))
                                .replace("{SCRATCH}", scratch)
                                .replace("{HOME}", "/home/gate-parity-probe")
                                .replace("{SELF}", seat))
                try:
                    d, _raw = ogc._decide(g, seat, tool, ti, home)
                    new = d.decision
                    new_rule = d.rule
                except Exception as e:
                    new, new_rule = f"RAISED:{type(e).__name__}", str(e)[:80]
                old = baseline[act_id]["seats"][seat]["verdict"]
                mark = "" if new == old else "  <<< HIT"
                rows_print.append((act_id, seat, old, f"{new}({new_rule})" if new != old else new, mark))
                if new != old:
                    hits.append((act_id, seat, cls, old, new, new_rule, expected, note))
finally:
    stub.close()

print(f"{'act':34s} {'seat':12s} {'old':6s} new")
for r in rows_print:
    print(f"{r[0]:34s} {r[1]:12s} {r[2]:6s} {r[3]}{r[4]}")

print(f"\n{len(rows_print)} cells, {len(hits)} divergences vs the measured-main baseline")
print("\n=== HITS (decide() differs from today's seat gate) ===")
for h in hits:
    print(f"\n{h[0]} / {h[1]}  [{h[2]}]")
    print(f"  old: {h[3]}   new: {h[4]} rule={h[5]}")
    print(f"  corpus expected: {h[6]}   note: {h[7]}")
