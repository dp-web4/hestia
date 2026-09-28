#!/usr/bin/env python3
"""The gate's whole-hook deadline must fit inside the harness's hook deadline.

WHY THIS EXISTS
---------------
`docs/GATE_BYPASS_CATALOG.md` §17 (Class T) names the invariant that keeps a member on a
fail-open engine governed at all:

    gate internal budget   <   harness hook timeout

and asks (dp, 2026-08-07) that the pair be audited on a schedule, per member. It was
audited on CBP on 2026-09-04 and the seat FAILED, because the invariant as written is
wrong: the budget is not a whole-hook deadline. It is minted once per *entry point* into
the shared mechanism, and one hook invocation crosses several.

MEASURED, 2026-09-04, claude-code on CBP (`findings/wake-0904b-...md`). Instrument: a TCP
listener that accepts and never answers — the catalog's own model of a daemon that is
"alive but loaded" (C1/C2). Shim run as a subprocess, one event per run, wall-clocked:

    event                 B=4000ms   2000     1000     500      fit
    Bash   (ordinary)     12.383 s   6.374    3.367    1.867    3.00*B + 0.38 s
    Read   (governance)   13.910 s   7.903    4.877    3.380    3.00*B + 1.91 s
    Write  (governance)    3.142 s   3.119    3.112    3.112    3.11 s, B-independent

Slope 3.00 across all three intervals in both B-dependent rows. Harness hook timeout on
this seat is 5 s (`~/.claude/settings.json`, PreToolUse). Every run returned exit 2 — the
gate refuses correctly and is killed 7.4 s before it can say so, and a fail-open engine
allows. Demonstrated end to end: a live session with the endpoint pointed at the black
hole executed the tool call.

Healthy-daemon control, same instrument, live daemon: 0.310 / 0.223 / 0.115 s. The margin
under health is 15-45x, which is why this survived. Only starvation exposes it.

WHAT THIS FILE PINS
-------------------
Two arms, deliberately different in kind:

  A. BEHAVIOURAL, hermetic, must stay GREEN. One entry point against a black hole obeys
     its own budget. This is the property the mechanism already has and must not lose.

  B. COMPOSED, currently RED. The whole hook, at the budget actually in force, must fit
     the harness deadline. Red until either the deadline is minted once per invocation
     and threaded, or the budget is lowered, or the harness deadline is raised. Which of
     those is the right trade is a society decision, not this file's: lowering the budget
     walks back into the false-denial bug dp fixed on 2026-08-11.

Prose does not fail a build. Class T has been documented since 2026-08-07 and the seat was
still failing it 28 days later, so it is asserted here instead.

REGENERATING THE CONSTANTS
--------------------------
The two constants below are measurements, not choices. If the composition changes, re-run
the sweep rather than editing them to taste: start an accept-and-never-answer listener,
point HESTIA_ENDPOINT at it, run the seat shim as a subprocess over several values of
HESTIA_PRE_TOTAL_BUDGET_MS on a governance-Read event, and fit wall against budget. The
slope is COMPOSED_WINDOWS; the intercept is FIXED_OVERHEAD_S.
"""
from __future__ import annotations

import os
import pathlib
import re
import socket
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
SHARED = REPO / "plugins" / "_shared"
MECHANISM = SHARED / "hestia_gate_mechanism.py"

# MEASURED 2026-09-04 on CBP. Slope and intercept of wall-time against budget on the
# governance-read path, which is the binding one (it pays a witness client the ordinary
# path does not).
COMPOSED_WINDOWS = 3.00
FIXED_OVERHEAD_S = 1.91

# CORRECTED 2026-09-04 (wake 0904c), and the correction matters: the composition is NOT
# linear in the budget. A window ends when its FIRST request gives up, and every request is
# capped at min(REQUEST_TIMEOUT_S, remaining) (mechanism :162), so
#
#     wall = COMPOSED_WINDOWS * min(budget, REQUEST_TIMEOUT_S) + FIXED_OVERHEAD_S
#
# and there is a CEILING no budget can exceed. Every probe in the sweep that produced the
# 3.00 slope sat below the 5 s cap, so the cap never showed in the data. Measured past it
# (2/4/6/10/20 s): claude 6.40/12.43/15.38/15.39/15.41, codex 7.88/13.93/16.92/16.93/16.89.
#
# Using the linear form above 5 s overstates the overrun by up to 3x -- on the kimi seat,
# which runs a 14000 ms budget, linear predicts 43.8 s against a measured 16.9 s. Both
# exceed kimi's 15 s deadline so its verdict is unchanged, but a predictor wrong by 27 s is
# not a predictor. Read from the engine rather than hard-coded: it is env-overridable, and
# it is the third load-bearing constant §17 does not mention.
_REQUEST_CAP = re.compile(r"REQUEST_TIMEOUT_S\s*=.*?,\s*([0-9.]+)\s*,")

# MEASURED from ~/.claude/settings.json on CBP, 2026-09-04: the PreToolUse hestia entry
# carries "timeout": 5. Hard-coded rather than read, because CI has no seat install and
# because §17 says in as many words: do not source a harness timeout from memory -- this
# number is the measured one, and its provenance is this sentence.
HARNESS_HOOK_TIMEOUT_S = 5.0

_DEADLINE_MINT = re.compile(r"time\.monotonic\(\)\s*\+\s*\(\s*TOTAL_BUDGET_MS\s*/\s*1000")


class _BlackHole:
    """Accepts connections, reads nothing, answers nothing, closes nothing.

    A daemon that is DOWN gives a connection refusal, which every client handles fast.
    The failure that matters is a daemon that is UP and starved, which is what this is.
    """

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(64)
        self.port = self._srv.getsockname()[1]
        self._held: list = []
        self._stop = False
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
                self._held.append(conn)
            except OSError:
                return

    def close(self) -> None:
        self._stop = True
        for c in self._held:
            try:
                c.close()
            except OSError:
                pass
        try:
            self._srv.close()
        except OSError:
            pass


def _request_timeout_s() -> float:
    """The per-request cap in force, from the engine. 5.0 if it cannot be read."""
    try:
        m = _REQUEST_CAP.search(MECHANISM.read_text(encoding="utf-8"))
        return float(m.group(1)) if m else 5.0
    except OSError:
        return 5.0


def composed_worst_case_s(budget_ms: float, fixed_s: float = FIXED_OVERHEAD_S) -> float:
    """The measured composition, saturating. See the block comment above."""
    return COMPOSED_WINDOWS * min(budget_ms / 1000.0, _request_timeout_s()) + fixed_s


def _mint_sites() -> list[int]:
    text = MECHANISM.read_text(encoding="utf-8")
    return [i for i, line in enumerate(text.splitlines(), 1) if _DEADLINE_MINT.search(line)]


def arm_a_single_entry_point_obeys_its_budget() -> list[str]:
    """GREEN. One call into the mechanism must not outrun its own budget by much."""
    failures: list[str] = []
    sys.path.insert(0, str(SHARED))
    import hestia_gate_mechanism as mech  # noqa: E402

    hole = _BlackHole()
    prior_budget = mech.TOTAL_BUDGET_MS
    prior_endpoint = os.environ.get("HESTIA_ENDPOINT")
    try:
        mech.TOTAL_BUDGET_MS = 400
        os.environ["HESTIA_ENDPOINT"] = "http://127.0.0.1:%d/mcp" % hole.port
        started = time.monotonic()
        verdict = mech.query_society_safety(
            {"tool_name": "Bash", "tool_input": {"command": "true"}},
            plugin_id="claude-code",
            host_agent="claude-code",
            plugin_version="test",
            host_agent_version="test",
        )
        wall = time.monotonic() - started
        ceiling = 1.5 * (mech.TOTAL_BUDGET_MS / 1000.0) + 0.4
        # FLOOR, not decoration. Without it this arm passes vacuously the day the client
        # starts bailing before it reaches the socket -- which is the same "absence reads
        # as OK" shape Class T is made of. Measured against the black hole the ratio is
        # 1.02-1.22, so half the budget is a floor no healthy implementation trips.
        floor = 0.5 * (mech.TOTAL_BUDGET_MS / 1000.0)
        if wall < floor:
            failures.append(
                "the call returned in %.3f s against a %d ms budget: it did not wait on "
                "the black hole at all, so this arm proved nothing about deadlines"
                % (wall, mech.TOTAL_BUDGET_MS)
            )
        if verdict.decided:
            failures.append(
                "a starved daemon produced a DECIDED verdict -- the black hole answered "
                "nothing, so any decision here is invented"
            )
        if wall > ceiling:
            failures.append(
                "one entry point took %.3f s against a %d ms budget (ceiling %.3f s): the "
                "per-window deadline is not being honoured either" % (
                    wall, mech.TOTAL_BUDGET_MS, ceiling)
            )
    finally:
        mech.TOTAL_BUDGET_MS = prior_budget
        if prior_endpoint is None:
            os.environ.pop("HESTIA_ENDPOINT", None)
        else:
            os.environ["HESTIA_ENDPOINT"] = prior_endpoint
        hole.close()
    return failures


def arm_b_composed_hook_fits_the_harness_deadline() -> list[str]:
    """RED until Class T is closed on this seat. See the module docstring."""
    sys.path.insert(0, str(SHARED))
    import hestia_gate_mechanism as mech  # noqa: E402

    worst_case = composed_worst_case_s(mech.TOTAL_BUDGET_MS)
    sites = _mint_sites()
    if worst_case < HARNESS_HOOK_TIMEOUT_S:
        return []
    return [
        "CLASS T IS LIVE ON THIS SEAT.\n"
        "    budget in force            %d ms   (hestia_gate_mechanism.TOTAL_BUDGET_MS)\n"
        "    whole-run deadline minted  %d SITE(S) in the shared mechanism, at line(s) %s\n"
        "                               and %.0f TIMES per invocation: the snapshot leg\n"
        "                               retries, so its site is crossed twice (wake 0904c)\n"
        "    measured composition       %.2f x min(budget, %.1f s) + %.2f s\n"
        "    worst-case hook wall       %.2f s\n"
        "    harness hook deadline      %.2f s\n"
        "  The gate reaches exit 2 and the harness is no longer listening: a fail-open\n"
        "  engine allows the call. HESTIA_PRE_FAIL_CLOSED does not help -- the gate is\n"
        "  already fail-closed here; it is killed before it can say so.\n"
        "  The fix that is not a trade: mint the deadline ONCE per hook invocation and\n"
        "  thread it through every client, including the fixed-cost witness and\n"
        "  escalation clients that consult no budget at all." % (
            mech.TOTAL_BUDGET_MS, len(sites), sites or "none found", COMPOSED_WINDOWS,
            COMPOSED_WINDOWS, _request_timeout_s(), FIXED_OVERHEAD_S, worst_case,
            HARNESS_HOOK_TIMEOUT_S)
    ]



# MEASURED per seat, 2026-09-04 (wake 0904c), `tools/class_t_seat_audit.py` against the
# same black hole. The fixed cost is NOT a fleet constant: codex and kimi run a witness
# client on the ORDINARY path that claude only runs on the governance path, so they pay
# 1.91 s where claude pays 0.38 s. gemini is absent on purpose -- it never enters the
# shared mechanism in-process; it spawns the governor under its own 6 s deadline and fails
# closed on overrun, which is the one-deadline-per-invocation fix already in production.
_SEAT_FIXED_S = {"claude": 0.38, "codex": 1.91, "kimi": 1.91}

#: Where each seat's harness deadline and budget-override actually live. Both are per-seat
#: facts and §17 treats both as fleet-wide, which is why the seat that fails is invisible
#: to the audit §17 asks for. Units differ too: gemini spells its deadline in ms.
_SEAT_CONFIG = {
    "claude": (("~", ".claude", "settings.json"), "json", "PreToolUse", 1.0),
    "codex": (("~", ".codex", "config.toml"), "toml", "hooks.PreToolUse", 1.0),
    "kimi": (("~", ".kimi-code", "config.toml"), "toml-flat", "PreToolUse", 1.0),
}


def _seat_pair(seat):
    """(budget_ms, harness_timeout_s) for an installed seat, or None if not installed.

    Read, never quoted. Returns the budget the harness ACTUALLY passes -- a seat may raise
    HESTIA_PRE_TOTAL_BUDGET_MS on its own hook command line, and one does, by 3.5x.
    """
    import json as _json

    parts, kind, key, scale = _SEAT_CONFIG[seat]
    path = pathlib.Path(os.path.expanduser(parts[0])).joinpath(*parts[1:])
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    def _budget(cmd):
        m = re.search(r"HESTIA_PRE_TOTAL_BUDGET_MS=([0-9]+)", cmd or "")
        return int(m.group(1)) if m else None

    if kind == "json":
        try:
            doc = _json.loads(text)
        except ValueError:
            return None
        for entry in (doc.get("hooks") or {}).get(key) or []:
            for hook in entry.get("hooks") or []:
                cmd = hook.get("command") or ""
                if "pre_tool_use" in cmd and "hestia" in cmd:
                    t = hook.get("timeout")
                    if t is None:
                        return None
                    return _budget(cmd), float(t) / scale
        return None

    cmd, in_block = None, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[["):
            in_block = ("hooks.PreToolUse" in line) if kind == "toml" else (line == "[[hooks]]")
            cmd = None
            continue
        if not in_block or line.startswith("#"):
            continue
        if line.startswith("event") and kind == "toml-flat" and key not in line:
            cmd = None
        if line.startswith("command"):
            cmd = line if "pre_tool_use" in line else None
        if cmd and line.startswith("timeout"):
            m = re.search(r"=\s*([0-9.]+)", line)
            if m:
                return _budget(cmd), float(m.group(1)) / scale
    return None


def arm_c_every_installed_seat_fits_its_own_harness_deadline() -> list[str]:
    """RED. One seat's pair is not the fleet's -- #939 review ask 2, answered locally.

    #939 asked the peers to audit themselves and the peers were out of credits. They did
    not need to: neither half of the pair is a property of the peer. The shims and the
    configs are all on this machine, so this reads them.

    SKIPS a seat that is not installed here, and says so. A skip is not a pass.
    """
    failures: list[str] = []
    for seat, fixed_s in sorted(_SEAT_FIXED_S.items()):
        pair = _seat_pair(seat)
        if pair is None:
            print("    %-8s SKIP (not installed on this machine -- untested, not passing)"
                  % seat)
            continue
        budget_ms, harness_s = pair
        source = "own hook command line" if budget_ms else "shared engine default"
        if budget_ms is None:
            sys.path.insert(0, str(SHARED))
            import hestia_gate_mechanism as mech  # noqa: E402
            budget_ms = mech.TOTAL_BUDGET_MS
        worst = composed_worst_case_s(budget_ms, fixed_s)
        ceiling = COMPOSED_WINDOWS * _request_timeout_s() + fixed_s
        ok = worst < harness_s
        print("    %-8s budget %5d ms (%s)  worst %5.2f s  harness %5.2f s  %s"
              % (seat, budget_ms, source, worst, harness_s, "ok" if ok else "FAIL"))
        if not ok:
            headroom = harness_s - fixed_s
            safe = "" if headroom <= 0 else (
                " Fits only below %d ms." % int(min(headroom / COMPOSED_WINDOWS,
                                                    _request_timeout_s()) * 1000))
            failures.append(
                "%s overruns its own harness deadline by %.2f s (budget %d ms from the %s, "
                "composed %.2f s, deadline %.2f s, ceiling over ALL budgets %.2f s).%s"
                % (seat, worst - harness_s, budget_ms, source, worst, harness_s, ceiling, safe))
    return failures


def main() -> int:
    if not MECHANISM.is_file():
        print("SKIP: shared mechanism not present at %s" % MECHANISM)
        return 0
    failures: list[str] = []
    for arm in (arm_a_single_entry_point_obeys_its_budget,
                arm_b_composed_hook_fits_the_harness_deadline,
                arm_c_every_installed_seat_fits_its_own_harness_deadline):
        found = arm()
        for f in found:
            failures.append("%s: %s" % (arm.__name__, f))
        print("%-48s %s" % (arm.__name__, "FAIL" if found else "ok"))
    if failures:
        print()
        for f in failures:
            print("FAIL %s" % f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
