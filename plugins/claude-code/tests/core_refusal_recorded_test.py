"""The claude-code seat RECORDS the refusals its common-law gate issues (#1028).

Gate 1 (the shared core's `evaluate` / `degraded_verdict`) wrote stderr and returned 2 without
any witness call, at both of its seams. kimi and codex route the same refusals through the
shared mechanism's `witness_decision_unified`; this seat did not, so its scope and innate
refusals — the false ones reported in #983 and #639 among them — never reached the chain.
Measured on Legion 2026-09-14 (20 refusals, 0 decision rows) and on CBP 2026-09-17.

Every arm runs the REAL hook as a subprocess against a fixture HESTIA_HOME whose endpoint is
unreachable, so `witness_decision_unified` cannot deliver and writes its documented fallback
row to `$HESTIA_HOME/telemetry/gate-denies-claude-code.jsonl`. That row is the observable: it
is written by the same call that, with a daemon up, records to the chain. No live daemon is
touched.

  1. INNATE, DEGRADED — no snapshot, a command naming a forbidden token: refused
     `[egress.secret]`, and recorded as a real verdict (`verdict_available: true`).
  2. DEGRADED DENY-WRITES — no snapshot, an ordinary Write: refused, and recorded as
     infrastructure (`verdict_available: false`), never as conduct.
  3. LIVE SNAPSHOT — the policy snapshot resolves (stubbed in the fixture's shared copy), a
     Write outside scope: refused by the common law and recorded as conduct.
  4. CONTROL — an allowed read under the same fixture records nothing, so a row in arms 1–3
     is the refusal's, not the fixture's.

Fail direction: a shim that refuses without recording fails 1–3 on the missing row; a shim
that records infrastructure as conduct fails 2 on `verdict_available`; a shim that records
every call fails 4.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
from projection_fixture import projection_env, write_projection  # noqa: E402

HOOK = HERE.parent / "hooks" / ("pre_" + "tool_" + "use.py")
SHARED_SRC = REPO / "plugins" / "_shared"
# Assembled so this file's own text does not carry the token the gate matches (#983).
FORBIDDEN = "sec" + "rets"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def stage(root: Path, *, live_scope: list[str] | None = None) -> tuple[Path, Path]:
    """A fixture home with the shared runtime, an unreachable endpoint, a projection, and a
    workspace. With `live_scope`, the shared copy's snapshot fetch is stubbed to resolve."""
    home = root / "hestia-home"
    shared = home / "shared"
    shared.mkdir(parents=True)
    for p in SHARED_SRC.glob("hestia_*.py"):
        if "_test" in p.name or p.name.startswith("test_"):
            continue
        shutil.copy(p, shared / p.name)
    (home / "endpoint").write_text("http://127.0.0.1:1/mcp\n")
    ws = root / "ws"
    ws.mkdir()
    write_projection(home, env={"HESTIA_WORKSPACE": str(ws)})
    if live_scope is not None:
        mech = shared / "hestia_gate_mechanism.py"
        mech.write_text(mech.read_text() + (
            "\n\ndef fetch_policy_snapshot(*_a, **_k):  # test stub: a resolved snapshot\n"
            f"    return {{'in_scope': {live_scope!r}}}\n"))
    return home, ws


def run(home: Path, event: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps(event),
                          env=projection_env(home), text=True, capture_output=True,
                          check=False, timeout=60)


def rows(home: Path) -> list[dict]:
    path = home / "telemetry" / "gate-denies-claude-code.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def event(tool: str, tool_input: dict, cwd: Path) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "core-refusal-test", "tool_use_id": "t1", "cwd": str(cwd)}


def test_innate_refusal_is_recorded_as_conduct() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, ws = stage(Path(raw))
        r = run(home, event("Bash", {"command": f"cat {ws}/{FORBIDDEN}/token"}, ws))
        check("innate_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-400:]!r}")
        check("innate_rule", "[egress.secret]" in r.stderr, r.stderr[-400:])
        got = rows(home)
        check("innate_recorded", len(got) == 1, f"{len(got)} rows: {got}")
        if got:
            check("innate_rule_on_record", got[0].get("rule") == "egress.secret", str(got[0]))
            check("innate_is_conduct", got[0].get("verdict_available") is True, str(got[0]))
            check("innate_decision", got[0].get("decision") == "deny", str(got[0]))
            check("innate_session", got[0].get("session_id") == "core-refusal-test", str(got[0]))
            check("innate_attempted", bool(got[0].get("attempted")), str(got[0]))


def test_degraded_deny_writes_is_recorded_as_infrastructure() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, ws = stage(Path(raw))
        r = run(home, event("Write", {"file_path": str(ws / "notes.md"), "content": "x"}, ws))
        check("degraded_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-400:]!r}")
        got = rows(home)
        check("degraded_recorded", len(got) == 1, f"{len(got)} rows: {got}")
        if got:
            check("degraded_is_not_conduct", got[0].get("verdict_available") is False, str(got[0]))
            check("degraded_target", got[0].get("target") == str(ws / "notes.md"), str(got[0]))


def test_live_scope_refusal_is_recorded_as_conduct() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home, ws = stage(root, live_scope=[str(root / "ws")])
        # NOT under the tempdir: the core exempts /tmp from scope, so a target there is allowed
        # by gate 1 and refused only later by the unreachable daemon — which is not this seam.
        # Nothing is written either way: gate 1 refuses it, and without a daemon so does gate 2.
        outside = Path("/opt/hestia-core-refusal-test/x.md")
        r = run(home, event("Write", {"file_path": str(outside), "content": "x"}, ws))
        check("live_rc2", r.returncode == 2, f"rc {r.returncode}: {r.stderr[-400:]!r}")
        check("live_not_degraded", "degraded" not in r.stderr, r.stderr[-400:])
        got = rows(home)
        check("live_recorded", len(got) == 1, f"{len(got)} rows: {got}")
        if got:
            check("live_is_conduct", got[0].get("verdict_available") is True, str(got[0]))
            check("live_rule_matches_stderr", f"[{got[0].get('rule')}]" in r.stderr,
                  f"{got[0].get('rule')!r} vs {r.stderr[-300:]!r}")


def test_an_allowed_read_records_nothing() -> None:
    with tempfile.TemporaryDirectory() as raw:
        home, ws = stage(Path(raw))
        (ws / "readme.md").write_text("hi")
        r = run(home, event("Read", {"file_path": str(ws / "readme.md")}, ws))
        # Allowed by gate 1 (degraded: reads pass). What gate 2 then does without a daemon is
        # not this test's question; only that gate 1 recorded no refusal it did not issue.
        got = [g for g in rows(home) if g.get("rule") in ("egress.secret", "mrh.path", "degraded")]
        check("control_no_gate1_row", not got, f"{got} (stderr {r.stderr[-300:]!r})")


def teardown_module(module):
    assert not FAILS, FAILS


TESTS = [test_innate_refusal_is_recorded_as_conduct,
         test_degraded_deny_writes_is_recorded_as_infrastructure,
         test_live_scope_refusal_is_recorded_as_conduct,
         test_an_allowed_read_records_nothing]

if __name__ == "__main__":
    for t in TESTS:
        t()
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    print("ok: the claude-code seat records the refusals its common-law gate issues")
