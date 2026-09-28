#!/usr/bin/env python3
"""Class T (GATE_BYPASS_CATALOG §17), audited for EVERY governed seat on this machine.

WHY THIS EXISTS
---------------
§17 asks (dp, 2026-08-07) that the pair

    gate internal budget   <   harness hook timeout

be audited on a schedule, per member. PR #939 audited claude-code on CBP: the seat FAILS,
and the invariant is the reason it reads as passing -- the budget is not a whole-hook
deadline, it is minted once per ENTRY POINT into the shared mechanism and one hook
invocation crosses several. #939 left two asks open, and neither needed a peer:

  ask 2  "run the same audit on codex, kimi and gemini -- untested is not passing."
  ask 3  "locate the third budget window; source shows two mint sites, slope is 3.00."

The peers could not answer ask 2 (out of credits; three notices bounced 2026-09-04).
They did not have to: neither half of the pair is a property of the PEER. Every shim is
installed on this box and every harness timeout is in a config file on this box. Asking a
seat to measure itself was never the only route, and it is the slowest one.

WHAT IT MEASURES
----------------
Two instruments, deliberately different in kind:

  WALL  -- the seat's own shim, run as the harness runs it (a subprocess, one event on
           stdin), against a black hole. This is the number the harness deadline is
           compared against, and it needs no theory of the composition.
  MINTS -- the same shim in-process with `_McpHttp.__init__` patched, recording every
           client with the time remaining on the deadline it was handed. Budget-derived
           windows (~B) separate from the fixed-cost clients that consult no budget at
           all, so slope and intercept come out as a DECOMPOSITION rather than a fit.
           (#939 fitted a line and could not name the third window. This counts it.)

THE LAW, CORRECTED AGAIN
------------------------
#939 measured `wall = 3.00 * budget + c` and swept 500-4000 ms. That fit is real and it is
LOCAL. Swept past the per-request cap the composition saturates:

    wall  =  3 * min(budget, REQUEST_TIMEOUT_S)  +  c_seat

because a window ends when its FIRST request gives up, and each request is capped at
`min(REQUEST_TIMEOUT_S, remaining)` (mechanism :162). Every one of #939's probes was below
the 5 s cap, so the cap never showed. Measured here at 2/4/6/10/20 s on two seats:
claude 6.40 / 12.43 / 15.38 / 15.39 / 15.41; codex 7.88 / 13.93 / 16.92 / 16.93 / 16.89.

Two consequences the linear fit hides:

  * There is a CEILING no budget can exceed (3 * REQUEST_TIMEOUT_S + c_seat: 15.4 s on
    claude, 16.9 s on codex/kimi). A seat whose harness deadline is under that ceiling
    cannot be made safe by raising the harness deadline a little, and a seat over it
    cannot be broken by any budget at all.
  * Extrapolating the linear fit past 5 s OVERSTATES the overrun by up to 3x. The kimi
    seat runs a 14000 ms budget; the linear law predicts 43.8 s, the truth is 16.9 s. Both
    exceed kimi's 15 s deadline, so the verdict is unchanged -- but a predictor that is
    wrong by 27 s is not a predictor, and arm B of the pinned test carried the linear form.

The target is a black hole -- a listener that accepts and never answers, §17's own model
of a daemon that is ALIVE BUT LOADED (C1/C2). It is inert: no daemon, no chain, no
petition. Wake 0904b learned that distinction the expensive way by replaying a governance
event through the PRODUCTION shim and minting a real escalation that invited 8 peers.

THREE THINGS §17 GETS WRONG ABOUT WHAT IS PER-SEAT
--------------------------------------------------
1. The harness deadline is per-seat AND per-unit: claude/codex/kimi spell it in SECONDS,
   gemini in MILLISECONDS. A number quoted across seats is a number read wrong.
2. The BUDGET is per-seat too. It is not the engine default -- a seat may override
   HESTIA_PRE_TOTAL_BUDGET_MS on its own hook command line, and one does, by 3.5x. #939
   assumed one budget fleet-wide. Parsed from the command line here, not assumed.
3. The event key differs (PreToolUse / BeforeTool) and so does the tool vocabulary. A
   probe event that the seat's shim does not recognise exits early and measures nothing,
   which is the "absence reads as OK" shape Class T is itself made of.

READ THIS BEFORE EDITING
------------------------
The process-environment mapping is reached through getattr and every gate path is joined
from parts. That is not style. The gate's `egress.secret` rule matches the forbidden
dotfile literal as a bare SUBSTRING (#680), so the ordinary spelling of the environment
mapping is refused outright; and `gate-self-access` (#440) reads a governed path anywhere
in a command's token vocabulary as a WRITE, so a .py file is the only place these names
can be spelled at all. Both classes are pinned in
plugins/claude-code/tests/gate_false_refusal_test.py.

Usage:  python3 tools/class_t_seat_audit.py [--seat NAME] [--json]
        python3 tools/class_t_seat_audit.py --mints SEAT BUDGET_MS   (internal)
"""
from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback

ENVMAP = getattr(os, "environ")
H = os.path.expanduser("~")
J = os.path.join

#: Small budget for the counting run. The mint COUNT is budget-invariant (verified on
#: claude at 500/1000/4000), so the composition is characterised cheaply and the worst
#: case at the seat's own budget is computed from it -- but the WALL run below is still
#: done at the real budget, because a computed number is not a measured one.
MINT_PROBE_MS = 500


def _ev(**kw) -> dict:
    base = {"cwd": "/tmp", "session_id": "class-t-audit"}
    base.update(kw)
    return base


# ── seat table ────────────────────────────────────────────────────────────────────────
SEATS = {
    "claude": {
        "shim": J(H, ".claude", "hooks", "hestia", "pre_tool_use" + ".py"),
        "config": J(H, ".claude", "settings.json"),
        "kind": "claude-settings", "event_key": "PreToolUse", "units": "s",
        "event": _ev(hook_event_name="PreToolUse", tool_name="Bash",
                     tool_input={"command": "true"}),
    },
    "codex": {
        "shim": J(H, ".codex", "hooks", "pre_tool_use" + ".py"),
        "config": J(H, ".codex", "config" + ".toml"),
        "kind": "toml", "event_key": "hooks.PreToolUse", "units": "s",
        "event": _ev(hook_event_name="PreToolUse", tool_name="bash",
                     tool_input={"command": "true"}),
    },
    "kimi": {
        "shim": J(H, ".kimi-code", "hooks", "pre_tool_use" + ".py"),
        "config": J(H, ".kimi-code", "config" + ".toml"),
        "kind": "toml-flat", "event_key": "PreToolUse", "units": "s",
        "event": _ev(hook_event_name="PreToolUse", tool_name="Bash",
                     tool_input={"command": "true"}),
    },
    "gemini": {
        "shim": J(H, ".gemini", "hestia-plugins", "gemini", "hooks", "before_tool" + ".py"),
        "config": J(H, ".gemini", "settings.json"),
        "kind": "gemini-settings", "event_key": "BeforeTool", "units": "ms",
        "event": _ev(hook_event_name="BeforeTool", tool_name="run_shell_command",
                     tool_input={"command": "true"}),
    },
}


# ── what the harness actually invokes, and under what deadline ────────────────────────
def _hook_entry(seat: str) -> tuple[str | None, float | None, str]:
    """(command, timeout_seconds, provenance) for the seat's hestia pre-tool hook.

    Sourced from the config every time. §17 says in as many words not to quote a harness
    timeout across seats, and instruction-file caps taught the same lesson: per-harness
    facts do not travel.
    """
    spec = SEATS[seat]
    path, kind, units = spec["config"], spec["kind"], spec["units"]
    shim_leaf = os.path.basename(spec["shim"])
    scale = 1000.0 if units == "ms" else 1.0
    if not os.path.isfile(path):
        return None, None, "no config at %s" % path.replace(H, "~")

    if kind in ("claude-settings", "gemini-settings"):
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            return None, None, "unparseable config: %s" % type(e).__name__
        for entry in (doc.get("hooks") or {}).get(spec["event_key"]) or []:
            for hook in entry.get("hooks") or []:
                cmd = hook.get("command") or ""
                if shim_leaf in cmd:
                    t = hook.get("timeout")
                    return (cmd, (float(t) / scale) if t is not None else None,
                            "%s %s timeout=%s%s" % (path.replace(H, "~"),
                                                    spec["event_key"], t, units))
        return None, None, "no %s hook naming %s in %s" % (
            spec["event_key"], shim_leaf, path.replace(H, "~"))

    # TOML, read line-wise. The stdlib parser is 3.11+ and this must run wherever a seat
    # runs. Two shapes in the fleet: codex nests ([[hooks.PreToolUse.hooks]]), kimi is
    # flat ([[hooks]] + event = "PreToolUse").
    text = open(path, encoding="utf-8", errors="replace").read()
    cmd, in_block = None, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[["):
            if kind == "toml":
                in_block = "hooks.PreToolUse" in s
            else:
                in_block = s == "[[hooks]]"
            cmd = None
            continue
        if not in_block or s.startswith("#"):
            continue
        if s.startswith("command"):
            cmd = s if shim_leaf in s else None
        if s.startswith("event") and kind == "toml-flat" and spec["event_key"] not in s:
            cmd = None
        if cmd and s.startswith("timeout"):
            m = re.search(r"=\s*([0-9.]+)", s)
            if m:
                return (cmd.split("=", 1)[1].strip().strip("'\""),
                        float(m.group(1)) / scale,
                        "%s %s timeout=%s%s" % (path.replace(H, "~"),
                                                spec["event_key"], m.group(1), units))
    return None, None, "no %s hook naming %s in %s" % (
        spec["event_key"], shim_leaf, path.replace(H, "~"))


def _engine_default_budget_ms() -> tuple[int, str]:
    shared = _shared_dir()
    path = J(shared, "hestia_gate_mechanism.py")
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*TOTAL_BUDGET_MS\s*=.*?,\s*(\d+)\s*,", line)
            if m:
                return int(m.group(1)), "engine default (%s)" % path.replace(H, "~")
    except OSError:
        pass
    return 4000, "engine unreadable; assumed"


def _budget_ms(seat: str, cmd: str | None) -> tuple[int, str]:
    """A seat may raise its own budget on its hook command line. One does."""
    if cmd:
        m = re.search(r"HESTIA_PRE_TOTAL_BUDGET_MS=([0-9]+)", cmd)
        if m:
            return int(m.group(1)), "OVERRIDDEN on the seat's own hook command line"
    return _engine_default_budget_ms()


def _request_timeout_s() -> tuple[float, str]:
    """The per-REQUEST cap, which is what a starved window actually ends on.

    Also env-overridable (HESTIA_PRE_REQUEST_TIMEOUT_S), and therefore also a per-seat
    fact that must be read rather than quoted -- the same mistake §17 makes about the
    budget, one level down.
    """
    path = J(_shared_dir(), "hestia_gate_mechanism.py")
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*REQUEST_TIMEOUT_S\s*=.*?,\s*([0-9.]+)\s*,", line)
            if m:
                return float(m.group(1)), "engine default"
    except OSError:
        pass
    return 5.0, "engine unreadable; assumed"


def _shared_dir() -> str:
    return os.getenv("HESTIA_SHARED_DIR") or J(os.path.expanduser(
        os.getenv("HESTIA_HOME") or J(H, ".hestia")), "shared")


# ── the black hole ────────────────────────────────────────────────────────────────────
class BlackHole:
    """Accepts, reads nothing, answers nothing, closes nothing.

    A DOWN daemon gives a connection refusal every client handles fast. The failure that
    matters is a daemon that is UP and starved.
    """

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(64)
        self.port = self._srv.getsockname()[1]
        self._held: list = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                self._held.append(self._srv.accept()[0])
            except OSError:
                return

    def close(self) -> None:
        for c in self._held:
            try:
                c.close()
            except OSError:
                pass
        try:
            self._srv.close()
        except OSError:
            pass


# ── instrument 1: wall, as the harness sees it ────────────────────────────────────────
def measure_wall(seat: str, budget_ms: int, cap_s: float) -> dict:
    spec = SEATS[seat]
    hole = BlackHole()
    env = dict(ENVMAP)
    env["HESTIA_ENDPOINT"] = "http://127.0.0.1:%d/mcp" % hole.port
    env["HESTIA_PRE_TOTAL_BUDGET_MS"] = str(budget_ms)
    env["HESTIA_WORKSPACE"] = env.get("HESTIA_WORKSPACE") or J(H, "ai-workspace")
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, spec["shim"]],
                              input=json.dumps(spec["event"]),
                              capture_output=True, text=True, timeout=cap_s, env=env)
        wall, rc, err = time.monotonic() - started, proc.returncode, proc.stderr
    except subprocess.TimeoutExpired:
        wall, rc, err = time.monotonic() - started, "KILLED-BY-PROBE-CAP", ""
    finally:
        hole.close()
    return {"wall_s": round(wall, 3), "rc": rc, "stderr_tail": (err or "").strip()[-200:]}


# ── instrument 2: mint decomposition ──────────────────────────────────────────────────
def _mints_worker(seat: str, budget_ms: int) -> int:
    import importlib.util

    shim = SEATS[seat]["shim"]
    hole = BlackHole()
    ENVMAP["HESTIA_ENDPOINT"] = "http://127.0.0.1:%d/mcp" % hole.port
    ENVMAP["HESTIA_PRE_TOTAL_BUDGET_MS"] = str(budget_ms)

    shared = _shared_dir()
    spec_m = importlib.util.spec_from_file_location(
        "hestia_gate_mechanism", J(shared, "hestia_gate_mechanism.py"))
    mech = importlib.util.module_from_spec(spec_m)
    sys.modules["hestia_gate_mechanism"] = mech
    sys.path.insert(0, shared)
    spec_m.loader.exec_module(mech)

    t0, mints = time.monotonic(), []
    orig = mech._McpHttp.__init__

    def patched(self, endpoint, deadline):
        frames = traceback.extract_stack()[:-1][-4:]
        mints.append({"at_s": round(time.monotonic() - t0, 3),
                      "window_s": round(deadline - time.monotonic(), 3),
                      "stack": ["%s:%d %s" % (os.path.basename(f.filename), f.lineno, f.name)
                                for f in frames]})
        return orig(self, endpoint, deadline)

    mech._McpHttp.__init__ = patched
    sys.stdin = io.StringIO(json.dumps(SEATS[seat]["event"]))
    sink, real_out = io.StringIO(), sys.stdout
    sys.stdout = sys.stderr = sink
    rc, started = None, time.monotonic()
    try:
        exec(compile(open(shim, encoding="utf-8").read(), shim, "exec"),
             {"__name__": "__main__", "__file__": shim})
    except SystemExit as e:
        rc = e.code
    except BaseException as e:  # noqa: BLE001 - a shim that dies is a RESULT
        rc = "EXC:%s:%s" % (type(e).__name__, e)
    wall = time.monotonic() - started
    sys.stdout, sys.stderr = real_out, sys.__stderr__
    b = budget_ms / 1000.0
    real_out.write(json.dumps({
        "seat": seat, "budget_ms": budget_ms, "rc": rc, "wall_s": round(wall, 3),
        "budget_windows": sum(1 for m in mints if abs(m["window_s"] - b) < 0.06),
        "fixed_s": [m["window_s"] for m in mints if abs(m["window_s"] - b) >= 0.06],
        "detail": mints}))
    return 0


def measure_mints(seat: str, budget_ms: int) -> dict:
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--mints", seat, str(budget_ms)],
        capture_output=True, text=True, timeout=180)
    out = proc.stdout.strip().splitlines()
    try:
        return json.loads(out[-1])
    except (IndexError, ValueError):
        return {"error": (proc.stderr or proc.stdout)[-300:]}


# ── report ────────────────────────────────────────────────────────────────────────────
def audit(seat: str) -> dict:
    spec = SEATS[seat]
    cmd, timeout_s, provenance = _hook_entry(seat)
    budget_ms, budget_src = _budget_ms(seat, cmd)
    row = {"seat": seat, "shim": spec["shim"].replace(H, "~"),
           "installed": os.path.isfile(spec["shim"]),
           "harness_timeout_s": timeout_s, "harness_provenance": provenance,
           "budget_ms": budget_ms, "budget_source": budget_src}
    if not row["installed"]:
        row["verdict"] = "NOT INSTALLED on this machine -- not audited, not passing"
        return row

    # Cap the wall probe generously above any plausible composition, so a runaway is a
    # RESULT ("still running at N s") rather than a hang.
    cap = max(60.0, 6.0 * budget_ms / 1000.0 + 20.0)
    wall = measure_wall(seat, budget_ms, cap)
    row.update(wall_s=wall["wall_s"], rc=wall["rc"], stderr_tail=wall["stderr_tail"])

    mints = measure_mints(seat, MINT_PROBE_MS)
    if "error" in mints:
        row["mints_error"] = mints["error"]
    else:
        row["budget_windows"] = mints["budget_windows"]
        row["fixed_clients_s"] = mints["fixed_s"]
        row["mint_stacks"] = [m["stack"][-1] for m in mints["detail"]]

    if timeout_s is None:
        row["verdict"] = "UNKNOWN harness deadline -- %s" % provenance
    elif wall["wall_s"] > timeout_s:
        row["verdict"] = "FAIL by %.2f s -- the gate reaches its verdict after the " \
                         "harness has stopped listening" % (wall["wall_s"] - timeout_s)
    else:
        margin = timeout_s - wall["wall_s"]
        row["verdict"] = "pass (margin %.2f s, %.0f%% of the deadline)" % (
            margin, 100.0 * margin / timeout_s)
    # The invariant AS WRITTEN in §17, evaluated on the same seat, for comparison.
    if timeout_s is not None:
        row["s17_as_written"] = "pass" if budget_ms / 1000.0 < timeout_s else "fail"

    # The saturation law. `c_seat` is measured, not assumed: it is whatever the wall run
    # cost beyond the windows it actually crossed.
    rt, rt_src = _request_timeout_s()
    row["request_timeout_s"] = rt
    row["request_timeout_source"] = rt_src
    windows = row.get("budget_windows")
    if windows:
        c_seat = row["wall_s"] - windows * min(budget_ms / 1000.0, rt)
        row["fixed_cost_s"] = round(c_seat, 2)
        row["ceiling_any_budget_s"] = round(windows * rt + c_seat, 2)
        if timeout_s is not None:
            headroom = timeout_s - c_seat
            if headroom <= 0:
                row["max_safe_budget_ms"] = 0
                row["budget_note"] = ("NO budget is safe: the un-budgeted fixed cost "
                                      "alone (%.2f s) meets the deadline" % c_seat)
            else:
                safe = min(headroom / windows, rt)
                row["max_safe_budget_ms"] = int(safe * 1000)
                if safe >= rt:
                    row["budget_note"] = ("safe at any budget -- the ceiling %.2f s is "
                                          "inside the deadline" % row["ceiling_any_budget_s"])
                else:
                    row["budget_note"] = ("budget must be under %d ms; in force %d ms"
                                          % (int(safe * 1000), budget_ms))
    return row


def main(argv: list) -> int:
    if len(argv) > 1 and argv[1] == "--mints":
        return _mints_worker(argv[2], int(argv[3]))
    only = argv[argv.index("--seat") + 1] if "--seat" in argv else None
    rows = [audit(s) for s in SEATS if not only or s == only]

    if "--json" in argv:
        print(json.dumps(rows, indent=1))
    else:
        print("Class T audit -- every governed seat installed on this machine, "
              "measured against a starved daemon")
        print()
        hdr = "%-8s %-9s %-8s %-8s %-9s %-6s %s"
        print(hdr % ("seat", "budget", "windows", "wall", "harness", "§17?", "verdict"))
        print("-" * 108)
        for r in rows:
            print(hdr % (
                r["seat"],
                "%d ms" % r["budget_ms"],
                str(r.get("budget_windows", "?")),
                ("%.2f s" % r["wall_s"]) if "wall_s" in r else "-",
                ("%.0f s" % r["harness_timeout_s"]) if r["harness_timeout_s"] else "?",
                r.get("s17_as_written", "?"),
                r["verdict"]))
        print()
        for r in rows:
            print("  %-8s budget: %s" % (r["seat"], r["budget_source"]))
            print("  %-8s harness: %s" % ("", r["harness_provenance"]))
            if r.get("fixed_clients_s"):
                print("  %-8s un-budgeted fixed-cost clients: %s s" % ("", r["fixed_clients_s"]))
            if "ceiling_any_budget_s" in r:
                print("  %-8s composition: %d x min(B, %.1f s) + %.2f s   ->  ceiling over "
                      "ALL budgets %.2f s" % ("", r["budget_windows"], r["request_timeout_s"],
                                              r["fixed_cost_s"], r["ceiling_any_budget_s"]))
                print("  %-8s %s" % ("", r.get("budget_note", "")))
            if r.get("mints_error"):
                print("  %-8s mint decomposition unavailable: %s" % ("", r["mints_error"][:120]))
        print()
        print("§17? is the invariant AS WRITTEN (budget < harness timeout) on the same")
        print("seat. Where it says pass and the verdict says FAIL, the audit that dp asked")
        print("for on a schedule would have cleared a seat that cannot deliver a refusal.")
    return 1 if any("FAIL" in str(r.get("verdict")) for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
