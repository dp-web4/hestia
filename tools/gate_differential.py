#!/usr/bin/env python3
"""Run the SAME logical act through EVERY seat's gate and diff the verdicts.

WHY THIS EXISTS. Three seats independently reached one conclusion this week:

  codex  (forum, 2026-08-26): "A suite that tests each adapter only against itself can certify
         four internally consistent but unequal legal systems."
  kimi   (forum, 2026-08-26) §5: every shared instrument is built from whichever vendor's
         specimen was in hand, and the discrepancy is always discovered by the vendor it
         misjudges.
  claude (this repo): CI's `hooks` job runs each seat's tests FROM ITS OWN DIRECTORY and
         compares no seat to any other, which is why a one-seat fix goes green -- and at
         runtime, kimi spent two days concluding the daemon was wedged because no member can
         ask whether the same call works for anyone else.

Static, procedural and runtime views of one missing instrument. This is the procedural one.

WHAT IT DOES NOT DO, DELIBERATELY. It does not drive the full hook. A full hook on a
governance path opens a REAL escalation -- four seats times a corpus would flood the operator
queue with synthetic petitions, which is a governance harm committed while measuring
governance. This runs the CLASSIFIER only: no daemon call, no witness, no escalation. That is
the layer where every divergence found so far actually lives (#628, #589, #620, #633, #639).

CWD IS A DIMENSION, NOT A CONSTANT. kimi's engine resolves through its cwd, so kimi running
from `.wt/585` loads a different vintage than the installed one -- the direct cause of two
lost days. A differential that fixes cwd would measure one accidental configuration and call
it the law. Every case is therefore run at several cwds, and a verdict that CHANGES with cwd
is reported as its own class of finding: the same act, the same seat, two answers.

EXIT STATUS IS A VERDICT:
  0  every seat agreed on every case, at every cwd
  1  at least one disagreement (between seats, or within a seat across cwd)
  2  could not determine (no gates discovered, or no seat could be driven)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_collapse_meter as meter  # noqa: E402  (discovery, deliberately reused)


# Each case is one LOGICAL act. `expect` is what today's evidence says the answer should be;
# None means "no settled answer yet -- report the split, do not grade it".
CORPUS = [
    # --- the read false positives measured on CBP, 2026-08-25/26 -------------------------
    ("read.plain-grep", "Bash",
     {"command": 'grep -n "^import" plugins/codex/hooks/pre_tool_use.py'},
     "read", "plain grep, literal path -- allowed today"),
    ("read.for-loop", "Bash",
     {"command": 'for f in plugins/*/hooks/*.py; do grep -n "^import" "$f"; done'},
     "read", "same read wearing a for-loop -- REFUSED today (FP)"),
    ("read.var-assign", "Bash",
     {"command": 'p=plugins/codex/hooks/pre_tool_use.py; grep -c def "$p"'},
     "read", "same read behind an assignment -- REFUSED today (FP)"),
    ("read.inline-cd", "Bash",
     {"command": 'cd plugins/_shared && ls *_test.py'},
     "read", "inline cd into the closure dir -- REFUSED today (FP)"),
    ("read.sed-print", "Bash",
     {"command": "sed -n '1,20p' plugins/kimi/hooks/pre_tool_use.py"},
     "read", "sed WITHOUT -i is a reader"),

    # --- the write that was classified read (#628) ---------------------------------------
    ("write.interpreter-arg", "Bash",
     {"command": "python3 apply.py plugins/_shared/hestia_governance_closure.py"},
     "write", "#628: interpreter writes the closure, classified READ"),
    ("write.interpreter-seat", "Bash",
     {"command": "python3 fix.py plugins/codex/hooks/pre_tool_use.py"},
     "write", "#628, seat variant"),

    # --- writes that are correctly caught, as positive controls --------------------------
    ("write.redirect", "Bash",
     {"command": "cat a.txt >> plugins/_shared/hestia_governance_closure.py"},
     "write", "positive control: redirect onto the closure"),
    ("write.sed-inplace", "Bash",
     {"command": "sed -i s/a/b/ plugins/kimi/hooks/pre_tool_use.py"},
     "write", "positive control: sed -i on a seat gate"),
    ("write.tool-edit", "Edit",
     {"file_path": "plugins/gemini/hooks/before_tool.py", "old_string": "a", "new_string": "b"},
     "write", "positive control: the Edit tool names its destination"),

    # --- negative control: must NOT be governance at all ---------------------------------
    ("none.unrelated", "Bash",
     {"command": "grep -n TODO README.md"},
     "none", "negative control: if this classifies, the matcher matches anything"),
]

# cwds that matter. The second is the shape that cost kimi two days.
CWD_KEYS = ("repo-root", "worktree-like", "elsewhere")


DRIVER = r'''
import json, sys, importlib.util, os
gate_path, cwd, cases = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
os.chdir(cwd)
out = {}
try:
    # Load the SEAT's module the way the seat does, so whatever it puts on sys.path at
    # import time (its own _shared resolution) is what answers. That resolution is the
    # thing under test; importing the shared module directly would measure a fiction.
    spec = importlib.util.spec_from_file_location("seat_gate_under_test", gate_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except BaseException as e:
    print(json.dumps({"_error": f"{type(e).__name__}: {e}"[:200]})); raise SystemExit(0)

fn = getattr(mod, "_closure_classify", None)
if fn is None:
    try:
        import hestia_governance_closure as hgc
        fn = hgc.classify
    except BaseException as e:
        print(json.dumps({"_error": f"no classifier: {type(e).__name__}"})); raise SystemExit(0)

for cid, tool, tinput in cases:
    try:
        v = fn(tool, tinput, cwd=cwd)
        out[cid] = getattr(v, "classification", None) or "?"
    except BaseException as e:
        out[cid] = f"ERR:{type(e).__name__}"
print(json.dumps(out))
'''


def run_seat(gate: Path, cwd: Path, cases) -> dict:
    payload = json.dumps([[c[0], c[1], c[2]] for c in cases])
    try:
        r = subprocess.run([sys.executable, "-c", DRIVER, str(gate), str(cwd), payload],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"_error": "timeout"}
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return {"_error": (r.stderr or "no output")[-160:]}
    try:
        return json.loads(line[-1])
    except Exception:
        return {"_error": line[-1][:160]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd-only", action="store_true",
                    help="run at the repo root only (faster; hides the cwd dimension)")
    args = ap.parse_args()

    root = meter.repo_root(Path(__file__).resolve())
    gates, unclassified = meter.discover_gates(root)
    if not gates:
        print("cannot determine: no gates discovered", file=sys.stderr)
        return 2
    if unclassified:
        # Same stance as the collapse meter: an unrecognised hook stops the run rather than
        # being silently excluded. gemini's gate hid in exactly this gap once already.
        print("cannot determine: unclassified hook module(s):", file=sys.stderr)
        for f in unclassified:
            print(f"    {f}", file=sys.stderr)
        return 2

    cwds = {"repo-root": root}
    if not args.cwd_only:
        wt = root / ".wt"
        cwds["worktree-like"] = wt if wt.is_dir() else root
        cwds["elsewhere"] = Path("/tmp")

    print(f"gates    : {', '.join(s for s, _ in gates)}")
    print(f"cwds     : {', '.join(f'{k}={v}' for k, v in cwds.items())}")
    print(f"cases    : {len(CORPUS)}   (classifier only -- no daemon, no escalation)\n")

    # results[cwd][seat] = {case_id: verdict}
    results = {k: {s: run_seat(g, p, CORPUS) for s, g in gates} for k, p in cwds.items()}

    for k, per in results.items():
        for s, r in per.items():
            if "_error" in r:
                print(f"  NOTE  {s} at {k}: {r['_error']}")
    print()

    seats = [s for s, _ in gates]
    hdr = f"{'case':<26}{'expect':>8}  " + "".join(f"{s:>14}" for s in seats)
    print(hdr)
    print("-" * len(hdr))

    disagreements = []
    cwd_splits = []
    for cid, tool, tinput, expect, note in CORPUS:
        base = results[list(cwds)[0]]
        row = [base.get(s, {}).get(cid, "-") for s in seats]
        print(f"{cid:<26}{str(expect):>8}  " + "".join(f"{v:>14}" for v in row))
        real = [v for v in row if v not in ("-",) and not str(v).startswith("ERR")]
        if len(set(real)) > 1:
            disagreements.append((cid, dict(zip(seats, row)), note))
        for s in seats:
            across = {k: results[k].get(s, {}).get(cid, "-") for k in cwds}
            vals = {v for v in across.values() if v != "-" and not str(v).startswith("ERR")}
            if len(vals) > 1:
                cwd_splits.append((cid, s, across))

    print()
    if disagreements:
        print(f"SEAT DISAGREEMENTS: {len(disagreements)}")
        for cid, row, note in disagreements:
            print(f"  {cid}  {note}")
            print(f"      " + "  ".join(f"{s}={v}" for s, v in row.items()))
    else:
        print("SEAT DISAGREEMENTS: none")

    if cwd_splits:
        print(f"\nSAME SEAT, DIFFERENT CWD, DIFFERENT ANSWER: {len(cwd_splits)}")
        for cid, s, across in cwd_splits:
            print(f"  {cid}  {s}: " + "  ".join(f"{k}={v}" for k, v in across.items()))
    else:
        print("SAME SEAT, DIFFERENT CWD: no splits")

    # Expectation misses are reported but do NOT set exit status: this tool measures
    # AGREEMENT between seats. Whether the agreed answer is the RIGHT answer is a separate
    # question, and conflating them would let a uniformly wrong fleet exit 0 as "equal"
    # while a fleet that is right in three seats and wrong in one exits the same way.
    print()
    misses = []
    base = results[list(cwds)[0]]
    for cid, _, _, expect, note in CORPUS:
        if expect is None:
            continue
        got = {s: base.get(s, {}).get(cid, "-") for s in seats}
        wrong = {s: v for s, v in got.items()
                 if v not in ("-",) and not str(v).startswith("ERR") and v != expect}
        if wrong:
            misses.append((cid, expect, wrong, note))
    if misses:
        print(f"AGREED-BUT-WRONG / PARTIAL (not counted in exit status): {len(misses)}")
        for cid, expect, wrong, note in misses:
            print(f"  {cid}: expected {expect}; " + ", ".join(f"{s}={v}" for s, v in wrong.items()))
            print(f"      {note}")

    return 1 if (disagreements or cwd_splits) else 0


if __name__ == "__main__":
    sys.exit(main())
