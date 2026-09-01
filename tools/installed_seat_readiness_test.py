#!/usr/bin/env python3
"""installed_seat_readiness.py measures RESIDENT bytes and never omits a declared seat (#771).

CI has no installed seats, so this builds a synthetic installation from the tree: every
discovered gate copied to a fake home, the manifest engine staged as a content-addressed
build behind a `shared` symlink, and a ledger (current-build.json) that claims those bytes.
Then it sabotages the installation one way at a time and asserts the row says so.

  1. faithful install      -> every seat present; claude-code's loader resolves `exact`;
                              no seat's resident/engine row reads MISWIRED
  2. tampered resident     -> that seat MISWIRED (FAIL), the others unchanged
  3. tampered engine       -> every seat names the engine mismatch
  4. missing resident      -> that seat INDETERMINATE, never dropped from the table
  5. per-seat bound        -> a bound on one seat fails THAT seat and moves no other row
  6. no ledger             -> rc 3, INDETERMINATE, not a pass

The verdict column is not asserted as PASS for every seat: on the real tree gemini carries
four divergent scope forks and three seats extract 3/10 path keys, and this test does not
get to pretend otherwise. It asserts the instrument, not the fleet.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "installed_seat_readiness.py"
SHARED = REPO / "plugins" / "_shared"
MANIFEST = [ln.strip() for ln in (SHARED / "RUNTIME_MANIFEST.txt").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
GATES = {"claude-code": "hooks/pre_tool_use.py", "codex": "hooks/pre_tool_use.py",
         "gemini": "hooks/before_tool.py", "kimi": "hooks/pre_tool_use.py"}

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    assert not FAILURES, FAILURES


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def install(root: Path) -> tuple[Path, Path]:
    """A faithful synthetic install: resident hooks + engine build + ledger claiming them."""
    home = root / "home"
    hestia = home / ".hestia"
    build = hestia / "shared.builds" / "synthetic"
    build.mkdir(parents=True)
    for name in MANIFEST:
        shutil.copy(SHARED / name, build / name)
    shutil.copy(SHARED / "RUNTIME_MANIFEST.txt", build / "RUNTIME_MANIFEST.txt")
    os.symlink("shared.builds/synthetic", hestia / "shared")
    members = []
    for seat, rel in GATES.items():
        src = REPO / "plugins" / seat / rel
        if not src.is_file():
            continue
        dest = home / f".{seat}" / "hooks" / Path(rel).name
        dest.parent.mkdir(parents=True)
        shutil.copy(src, dest)
        members.append({"member": seat, "declared_dest": str(dest.parent),
                        "files": [{"file": dest.name, "path": str(dest), "sha256": sha(dest)}]})
    ledger = {
        "build_id": "synthetic", "head_sha": "0" * 40, "installed_at_iso": "2026-01-01T00:00:00Z",
        "members": members,
        "shared_engine": [{"file": n, "path": str(hestia / "shared" / n), "sha256": sha(build / n)}
                          for n in MANIFEST],
    }
    (hestia / "current-build.json").write_text(json.dumps(ledger), encoding="utf-8")
    return home, hestia


def run(hestia: Path, *extra: str) -> tuple[int, dict]:
    env = dict(os.environ, HESTIA_HOME=str(hestia), HOME=str(hestia.parent))
    env.pop("HESTIA_SHARED_DIR", None)
    r = subprocess.run([sys.executable, str(TOOL), "--json", *extra], env=env, text=True,
                       capture_output=True, timeout=300)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        data = {"rows": [], "trend": {}, "stderr": r.stderr[-400:]}
    return r.returncode, data


def by_seat(data: dict) -> dict:
    return {r["seat"]: r for r in data.get("rows", [])}


def test_faithful_install_is_measured_per_seat() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, hestia = install(Path(raw))
        rc, data = run(hestia, "--report-only")
        rows = by_seat(data)
        check(set(rows) == set(GATES), f"[1] every ledger member has a row: {sorted(rows)}")
        check(all(r.get("resident_match") for r in rows.values()), "[1] every resident gate == ledger")
        check(data.get("trend", {}).get("engine_ok") is True, "[1] resident engine == ledger")
        cl = rows.get("claude-code", {})
        check(cl.get("loader_verdict") == "exact",
              f"[1] claude-code resolves every shared module from the installed engine: {cl.get('loader')}")
        check(all(isinstance(r.get("local_pct"), float) for r in rows.values()), "[1] local% measured per seat")
        check(rc == 0, "[1] --report-only exits 0")


def test_tampered_resident_is_miswired_and_isolated() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, hestia = install(Path(raw))
        base_rc, base = run(hestia, "--report-only")
        victim = home / ".kimi" / "hooks" / "pre_tool_use.py"
        victim.write_text(victim.read_text() + "\n# tampered after deploy\n", encoding="utf-8")
        rc, data = run(hestia)
        rows, before = by_seat(data), by_seat(base)
        check(rows["kimi"]["verdict"] == "FAIL" and any("MISWIRED" in s for s in rows["kimi"]["reasons"]),
              f"[2] tampered kimi reads MISWIRED: {rows['kimi']['reasons']}")
        for s in ("claude-code", "codex", "gemini"):
            check(rows[s]["verdict"] == before[s]["verdict"] and rows[s]["reasons"] == before[s]["reasons"],
                  f"[2] {s} row unchanged by kimi's tamper")
        check(rc == 1, "[2] a MISWIRED seat fails the run")


def test_tampered_engine_names_every_seat() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, hestia = install(Path(raw))
        eng = hestia / "shared" / MANIFEST[0]
        eng.write_text(eng.read_text() + "\n# tampered\n", encoding="utf-8")
        rc, data = run(hestia)
        rows = by_seat(data)
        check(data["trend"].get("engine_ok") is False, "[3] engine mismatch detected")
        check(all(any("engine" in s and "MISWIRED" in s for s in r["reasons"]) for r in rows.values()),
              "[3] every seat names the engine mismatch")


def test_missing_resident_is_indeterminate_not_omitted() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, hestia = install(Path(raw))
        os.remove(home / ".codex" / "hooks" / "pre_tool_use.py")
        rc, data = run(hestia)
        rows = by_seat(data)
        check("codex" in rows, "[4] a declared seat with no resident gate is still a row")
        check(rows.get("codex", {}).get("verdict") == "INDETERMINATE",
              f"[4] and it reads INDETERMINATE: {rows.get('codex', {}).get('verdict')}")
        check(rc == 1, "[4] INDETERMINATE is not a pass")


def test_per_seat_bound_names_one_seat() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, hestia = install(Path(raw))
        _, base = run(hestia, "--report-only")
        before = by_seat(base)
        rc, data = run(hestia, "--max-local-pct", "claude-code=0.1")
        rows = by_seat(data)
        check(any("per-seat bound" in s for s in rows["claude-code"]["reasons"]),
              "[5] the bound fails claude-code by name")
        for s in ("codex", "gemini", "kimi"):
            check(rows[s]["local_pct"] == before[s]["local_pct"] and rows[s]["reasons"] == before[s]["reasons"],
                  f"[5] {s} measured value and reasons unchanged by claude-code's bound")


def test_no_ledger_is_indeterminate() -> None:
    with tempfile.TemporaryDirectory() as raw:
        hestia = Path(raw) / "empty"
        hestia.mkdir()
        rc, _ = run(hestia)
        check(rc == 3, f"[6] no deployment truth -> rc 3, not 0 (got {rc})")


if __name__ == "__main__":
    test_faithful_install_is_measured_per_seat()
    test_tampered_resident_is_miswired_and_isolated()
    test_tampered_engine_names_every_seat()
    test_missing_resident_is_indeterminate_not_omitted()
    test_per_seat_bound_names_one_seat()
    test_no_ledger_is_indeterminate()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: installed-seat readiness measures resident bytes per seat and never omits a declared seat")
