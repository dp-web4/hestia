#!/usr/bin/env python3
"""Deployment readiness, one row per INSTALLED seat, measured on resident bytes (#771).

`gate_collapse_meter.py` reads the SOURCE TREE and prints one fleet number. That is a trend,
not a compliance signal: one shim adding local authority moves the aggregate for everyone,
and three nearly-empty adapters can dilute one badly forked shim. The unit of compliance is
the installed seat, and the bytes that matter are the ones the harness actually runs.

So this reads deployment truth ($HESTIA_HOME/current-build.json) and, for every member it
names, measures the RESIDENT files:

  resident    sha256 of the resident gate == the ledger's claim (else MISWIRED)
  shared      sha256 of every resident engine module == the ledger's claim (else MISWIRED)
  local%      law-bearing sloc in the resident gate / (that + law-bearing sloc in the resident
              engine), same classifier and grain as the source meter
  forks       resident gate functions that re-implement a name the resident engine owns
  extraction  path-key names this resident gate extracts / the union across resident gates
  loader      where the resident gate's shared-module imports ACTUALLY resolved when the
              hook was executed under the installed HESTIA_HOME: installed / worktree / other
              / unresolved. A worktree is FAIL: mutable, un-ratified authority.
  verdict     PASS, FAIL (reasons named), or INDETERMINATE (declared installed, not measurable;
              never silently omitted)

Thresholds are per seat (`--max-local-pct SEAT=PCT`, `--max-forks SEAT=N`); a regression in
one seat names that seat and leaves the others' numbers untouched. The fleet aggregate is
printed last, labeled a trend, and decides nothing.

Source-tree files are never substituted for resident bytes here. If you want the predictive
source ratchet, that is the other instrument, and the two are labeled distinctly on purpose.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_collapse_meter as meter  # noqa: E402
from path_key_vocabulary_probe import (  # noqa: E402
    NOT_REACH, keys_from_get_literals, keys_from_path_targets)

GATE_BASENAMES = set(meter.GATE_BASENAMES)


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def in_worktree(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def classify_origin(resolved: str, installed_shared: Path) -> str:
    rp = Path(os.path.realpath(resolved))
    inst = Path(os.path.realpath(installed_shared))
    if rp.parent == inst or str(rp).startswith(str(inst) + os.sep):
        return "installed"
    if in_worktree(rp):
        return "worktree"
    return "other"


PROBE = r"""
import importlib, importlib.util, json, os, sys
hook, names = sys.argv[1], json.loads(sys.argv[2])
out = {"error": None, "resolved": {}}
try:
    s = importlib.util.spec_from_file_location("resident_gate", hook)
    g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
except BaseException as e:  # a hook that cannot even initialise is a finding, not a crash
    out["error"] = f"{type(e).__name__}: {e}"[:200]
for n in names:
    m = sys.modules.get(n)
    if m is None:
        try:
            loader = getattr(sys.modules.get("resident_gate"), "_load_shared_module", None)
            m = loader(n) if loader else importlib.import_module(n)
        except BaseException as e:
            out["resolved"][n] = {"file": None, "error": f"{type(e).__name__}: {e}"[:160]}
            continue
    out["resolved"][n] = {"file": os.path.realpath(getattr(m, "__file__", "") or ""), "error": None}
print(json.dumps(out))
"""


def probe_loader(hook: Path, names: list[str], hestia_home: Path) -> dict:
    env = dict(os.environ)
    env.pop("HESTIA_SHARED_DIR", None)          # the INSTALLED path must win on its own
    env.pop("PYTHONPATH", None)
    env.update({"HESTIA_HOME": str(hestia_home), "HESTIA_ENDPOINT": "http://127.0.0.1:1"})
    try:
        r = subprocess.run([sys.executable, "-I", "-c", PROBE, str(hook), json.dumps(names)],
                           env=env, capture_output=True, text=True, timeout=60, cwd=str(hook.parent))
    except subprocess.TimeoutExpired:
        return {"error": "probe timed out", "resolved": {}}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": f"probe produced no verdict (rc={r.returncode}): {r.stderr[-200:]}", "resolved": {}}


def law_sloc(path: Path) -> tuple[int, list[dict]]:
    fns, _ = meter.module_functions(path)
    return sum(f["sloc"] for f in fns if f["law_bearing"]), fns


def parse_seat_limits(items: list[str], cast) -> dict:
    out = {}
    for it in items or []:
        seat, _, val = it.partition("=")
        if not seat or not val:
            raise SystemExit(f"bad per-seat bound {it!r}; want SEAT=VALUE")
        out[seat] = cast(val)
    return out


def measure(ledger_path: Path, hestia_home: Path, max_local: dict, max_forks: dict) -> tuple[list[dict], dict]:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    installed_shared = hestia_home / "shared"

    # --- the resident engine, once
    engine = []
    engine_ok = True
    for e in ledger.get("shared_engine") or []:
        p = Path(e["path"])
        got = sha256(p)
        engine.append({"file": e["file"], "path": p, "ledger": e["sha256"], "resident": got,
                       "match": got == e["sha256"]})
        engine_ok = engine_ok and got == e["sha256"]
    engine_names = [Path(e["file"]).stem for e in engine]
    shared_law = 0
    shared_names: set[str] = set()
    shared_sources: dict[str, str] = {}
    for e in engine:
        if e["resident"] is None:
            continue
        s, _ = law_sloc(e["path"])
        shared_law += s
        src = e["path"].read_text(encoding="utf-8", errors="replace")
        for node in ast.parse(src).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                shared_names.add(node.name)
                if not isinstance(node, ast.ClassDef):
                    shared_sources.setdefault(node.name, ast.get_source_segment(src, node) or "")

    # --- per seat
    rows = []
    for m in ledger.get("members") or []:
        seat = m["member"]
        gate_entries = [f for f in m.get("files", []) if f["file"] in GATE_BASENAMES]
        row = {"seat": seat, "reasons": [], "verdict": None}
        if not gate_entries:
            row.update(verdict="INDETERMINATE", reasons=["ledger names no gate file for this member"])
            rows.append(row)
            continue
        ge = gate_entries[0]
        hook = Path(ge["path"])
        got = sha256(hook)
        row["resident_path"] = str(hook)
        row["resident_sha"] = got
        row["resident_match"] = got == ge["sha256"]
        if got is None:
            row.update(verdict="INDETERMINATE", reasons=[f"resident gate unreadable: {hook}"])
            rows.append(row)
            continue
        if not row["resident_match"]:
            row["reasons"].append("resident gate bytes != ledger (MISWIRED)")
        if not engine_ok:
            row["reasons"].append("resident engine bytes != ledger (MISWIRED)")

        local, fns = law_sloc(hook)
        row["local_law"] = local
        row["shared_law"] = shared_law
        row["local_pct"] = (100.0 * local / (local + shared_law)) if (local + shared_law) else 0.0

        forks = [f for f in fns if f["top_level"] and f["name"] in shared_names and not f["delegates"]]
        row["forks"] = len(forks)
        row["forks_verbatim"] = sum(1 for f in forks if meter.is_verbatim(f, shared_sources))
        row["fork_names"] = [f["name"] for f in forks]

        pl = probe_loader(hook, engine_names, hestia_home)
        origins = {}
        for n in engine_names:
            r = pl["resolved"].get(n)
            if not r or r.get("file") in (None, ""):
                origins[n] = "unresolved"
            else:
                origins[n] = classify_origin(r["file"], installed_shared)
        row["loader"] = origins
        row["loader_error"] = pl.get("error")
        kinds = set(origins.values())
        if pl.get("error"):
            row["loader_verdict"] = "error"
        elif kinds == {"installed"}:
            row["loader_verdict"] = "exact"
        elif "worktree" in kinds:
            row["loader_verdict"] = "worktree"
        elif "other" in kinds:
            row["loader_verdict"] = "other"
        else:
            row["loader_verdict"] = "partial" if "installed" in kinds else "unresolved"
        rows.append(row)

    # --- extraction domain over RESIDENT gates, anchored like the source probe
    declared = {}
    for row in rows:
        p = row.get("resident_path")
        if not p or row.get("resident_sha") is None:
            continue
        k = keys_from_path_targets(Path(p))
        if k is not None:
            declared[row["seat"]] = k
    anchor = set.intersection(*declared.values()) if declared else set()
    vocab = {}
    for row in rows:
        p = row.get("resident_path")
        if not p or row.get("resident_sha") is None:
            continue
        if row["seat"] in declared:
            keys = declared[row["seat"]]
        else:
            keys, _mixed = keys_from_get_literals(Path(p), anchor)
        vocab[row["seat"]] = {k for k in keys if k not in NOT_REACH}
    union = set.union(*vocab.values()) if vocab else set()
    for row in rows:
        if row["seat"] in vocab:
            row["extraction"] = (len(vocab[row["seat"]]), len(union))
            row["extraction_missing"] = sorted(union - vocab[row["seat"]])

    # --- verdicts
    for row in rows:
        if row["verdict"] == "INDETERMINATE":
            continue
        lv = row["loader_verdict"]
        if lv in ("worktree", "other"):
            row["reasons"].append(f"loader resolved shared law outside the installed engine: {lv}")
        elif lv in ("unresolved", "partial", "error"):
            row["reasons"].append(f"loader resolution not provable: {lv}"
                                  + (f" ({row['loader_error']})" if row.get("loader_error") else ""))
        if row["forks"] > max_forks.get(row["seat"], 0):
            row["reasons"].append(f"{row['forks']} fork(s) of engine-owned names: {', '.join(row['fork_names'])}")
        lim = max_local.get(row["seat"])
        if lim is not None and round(row["local_pct"], 1) > lim:
            row["reasons"].append(f"local law {row['local_pct']:.1f}% > per-seat bound {lim:.1f}%")
        if row.get("extraction") and row["extraction"][0] < row["extraction"][1]:
            row["reasons"].append(f"extracts {row['extraction'][0]}/{row['extraction'][1]} path keys; "
                                  f"omits {', '.join(row['extraction_missing'])}")
        if lv in ("unresolved", "partial", "error") and not row["reasons"][:-1]:
            row["verdict"] = "INDETERMINATE"
        else:
            row["verdict"] = "FAIL" if row["reasons"] else "PASS"

    fleet_local = sum(r.get("local_law", 0) for r in rows)
    trend = {"fleet_local_law": fleet_local, "shared_law": shared_law,
             "fleet_pct": (100.0 * fleet_local / (fleet_local + shared_law)) if (fleet_local + shared_law) else 0.0,
             "build_id": ledger.get("build_id"), "installed_at": ledger.get("installed_at_iso"),
             "engine_ok": engine_ok}
    return rows, trend


def render(rows: list[dict], trend: dict) -> None:
    print(f"INSTALLED-SEAT READINESS   build {trend['build_id']}   installed {trend['installed_at']}")
    print(f"{'seat':<13}{'resident':<10}{'shared':<8}{'local%':>7}{'forks':>6}  {'extraction':<11}{'loader':<11}verdict")
    for r in rows:
        if r.get("resident_sha") is None:
            print(f"{r['seat']:<13}{'MISSING':<10}{'':<8}{'':>7}{'':>6}  {'':<11}{'':<11}{r['verdict']}")
        else:
            ex = r.get("extraction")
            print(f"{r['seat']:<13}{r['resident_sha'][:8] + ('' if r['resident_match'] else '!'):<10}"
                  f"{'ok' if trend['engine_ok'] else 'MISW':<8}{r['local_pct']:>7.1f}{r['forks']:>6}  "
                  f"{(f'{ex[0]}/{ex[1]}' if ex else '?'):<11}{r['loader_verdict']:<11}{r['verdict']}")
        for reason in r["reasons"]:
            print(f"{'':<13}- {reason}")
    print(f"TREND (secondary, not a verdict): fleet {trend['fleet_pct']:.1f}% of law-bearing sloc is per-seat "
          f"({trend['fleet_local_law']} per-seat + {trend['shared_law']} shared)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hestia-home", default=os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia"))
    ap.add_argument("--ledger", default=None, help="deployment truth (default: $HESTIA_HOME/current-build.json)")
    ap.add_argument("--max-local-pct", action="append", default=[], metavar="SEAT=PCT")
    ap.add_argument("--max-forks", action="append", default=[], metavar="SEAT=N")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="exit 0 whatever the verdicts")
    args = ap.parse_args()
    home = Path(args.hestia_home)
    ledger = Path(args.ledger) if args.ledger else home / "current-build.json"
    if not ledger.is_file():
        print(f"INDETERMINATE: no deployment truth at {ledger}; nothing here is measurable", file=sys.stderr)
        return 0 if args.report_only else 3
    rows, trend = measure(ledger, home, parse_seat_limits(args.max_local_pct, float),
                          parse_seat_limits(args.max_forks, int))
    if args.json:
        print(json.dumps({"rows": rows, "trend": trend}, indent=1, default=str))
    else:
        render(rows, trend)
    if args.report_only:
        return 0
    return 0 if all(r["verdict"] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
