#!/usr/bin/env python3
"""kimi-code NOT-SAME behaviour matrix for PR #1407 (the #1262 re-cut on main, held 565e424e).

RECONSTRUCTED 2026-10-26: the 10-07 originals (24-row protocol probe; /tmp/p12_probe_1262.py,
14 rows) are gone (tmp cleaned, never committed). Every row here is rebuilt from the expected
BEHAVIOUR documented in the PR #1262 thread (kimi 10-07 acceptance comment; the P1/P2 co-seat
comment; Nova's HOLD items; the B1/HOLD-2 design note) — not from claude-code's decide_test.py,
which is the harness under review. Behavior-level only: all rows drive the gate through its
public `harness_bound()` entry with real config files in a temp HOME; nothing reaches into
gate internals.

argv1: gate file under test (default: the re-cut, sg_rev.py beside this file).
Exit 0 = every row behaved as the protocol documents.
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GATE = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "sg_rev.py"

# hestia_gate_core is main's own (the patch does not touch it); serve it from the base checkout.
sys.path.insert(0, "/home/dp/ai-workspace/hestia/scratchpad/s1262-base/plugins/_shared")

spec = importlib.util.spec_from_file_location("sg_under_test", GATE)
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)

WORK = pathlib.Path(tempfile.mkdtemp(prefix="kimi-1407-probe-"))
HOOK = WORK / "pre_tool_use.py"
HOOK.write_text("# the hook under test\n")
ME = os.path.realpath(HOOK)
BASE = os.path.basename(ME)
START = 1000.0

JSON_REG = {"reader": "json-hook-commands", "layout": "nested", "path": ""}  # path filled per row
TOML_REG = {"reader": "toml-hook-commands", "layout": "flat", "path": ""}


def harness_for(reg_path, reader_layout, **extra):
    reg = dict(reader_layout)
    reg["path"] = str(reg_path)
    h = {"event": "PreToolUse", "registrations": [reg],
         "timeout_unit_seconds": 1, "margin_seconds": 1.5,
         "on_timeout": "fail-open: test", "default_timeout_seconds": 30}
    h.update(extra)
    return h


def bound(harness, env_extra=None):
    env = {"HOME": str(WORK)}
    if env_extra:
        env.update(env_extra)
    return g.harness_bound(harness, ME, START, env=env)


def write_json(name, text):
    p = WORK / name
    p.write_text(text)
    return p


def nested_cfg(command, timeout, hook_extra=""):
    to = f', "timeout": {timeout}' if timeout is not None else ""
    return ('{"hooks": {"PreToolUse": [{"matcher": "", "hooks": ['
            f'{{"type": "command", "command": {json.dumps(command)}{to}{hook_extra}}}'
            ']}]}}')


def flat_cfg(command, timeout_line):
    return f'[[hooks]]\nevent = "PreToolUse"\ncommand = {json.dumps(command)}\n{timeout_line}\n'


ROWS = []


def row(rid, note):
    def deco(fn):
        ROWS.append((rid, note, fn))
        return fn
    return deco


# ── the 24 protocol rows (timeout canonicity) ──────────────────────────────────────────────
@row("P01", "canonical 3s accepted; margin floor 0.5")
def _():
    p = write_json("p01.json", nested_cfg(ME, 3))
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 3.0 and abs(b.margin_seconds - 0.5) < 1e-9 and abs(b.deadline - (START + 2.5)) < 1e-9, b


@row("P02", "canonical 10s accepted; margin 1.5")
def _():
    p = write_json("p02.json", nested_cfg(ME, 10))
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 10.0 and abs(b.margin_seconds - 1.5) < 1e-9, b


@row("P03", "canonical 30s accepted; margin capped 1.5")
def _():
    p = write_json("p03.json", nested_cfg(ME, 30))
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 30.0 and abs(b.margin_seconds - 1.5) < 1e-9, b


@row("P04", "2s rejected MISWIRED naming the envelope")
def _():
    p = write_json("p04.json", nested_cfg(ME, 2))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "envelope" in b.why, b


@row("P05", "31s rejected MISWIRED naming the envelope (never clamped)")
def _():
    p = write_json("p05.json", nested_cfg(ME, 31))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "envelope" in b.why, b


@row("P06", "timeout omitted -> MISWIRED (missing is not a default)")
def _():
    p = write_json("p06.json", nested_cfg(ME, None))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "no timeout declared" in b.why, b


@row("P07", "omitted + vendor default present in harness data -> still MISWIRED")
def _():
    p = write_json("p07.json", nested_cfg(ME, None))
    b = bound(harness_for(p, JSON_REG, default_timeout_seconds=30))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("P08", "TOML `timeout = 5e0` binds and normalizes to 5.0")
def _():
    p = write_json("p08.toml", flat_cfg(ME, "timeout = 5e0"))
    b = bound(harness_for(p, TOML_REG))
    assert b.timeout_seconds == 5.0 and b.deadline is not None, b


@row("P09", "TOML `timeout = +5` binds and normalizes to 5.0")
def _():
    p = write_json("p09.toml", flat_cfg(ME, "timeout = +5"))
    b = bound(harness_for(p, TOML_REG))
    assert b.timeout_seconds == 5.0 and b.deadline is not None, b


@row("P10", "JSON inline entry object binds structurally")
def _():
    p = write_json("p10.json", nested_cfg(ME, 15))
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 15.0 and b.deadline is not None, b


@row("P11", "the same timeout text in an unparseable file naming the hook -> MISWIRED")
def _():
    p = write_json("p11.toml", f'[[hooks]]\nevent = "PreToolUse"\ncommand = "{ME}"\ntimeout = 5e0\n[broken\n')
    b = bound(harness_for(p, TOML_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "cannot be parsed" in b.why, b


@row("P12", "untimed exact target + timed sibling: MISWIRED, sibling's value never borrowed")
def _():
    cmd_other = str(WORK / "other_hook.py")
    text = ('{"hooks": {"PreToolUse": [{"matcher": "", "hooks": ['
            f'{{"type": "command", "command": {json.dumps(ME)}}},'
            f'{{"type": "command", "command": {json.dumps(cmd_other)}, "timeout": 20}}'
            ']}]}}')
    p = write_json("p12.json", text)
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and b.timeout_seconds is None, b


@row("P13", "malformed JSON naming the hook -> MISWIRED")
def _():
    p = write_json("p13.json", '{"hooks": {"PreToolUse": [ {"hooks": [{"command": "' + ME + '", "timeout": 10} ]} ]')
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("P14", "a config naming the hook with no parser available -> MISWIRED")
def _():
    p = write_json("p14.toml", flat_cfg(ME, "timeout = 10"))
    real_tomllib = sys.modules.get("tomllib")
    import builtins
    real_import = builtins.__import__

    def no_tomllib(name, *a, **k):
        if name == "tomllib":
            raise ImportError("simulated absence for P14")
        return real_import(name, *a, **k)
    builtins.__import__ = no_tomllib
    sys.modules.pop("tomllib", None)
    c = getattr(g, "_CONFIG_CACHE", None)
    if c is not None:
        c.clear()
    try:
        b = bound(harness_for(p, TOML_REG))
    finally:
        builtins.__import__ = real_import
        if real_tomllib is not None:
            sys.modules["tomllib"] = real_tomllib
        c = getattr(g, "_CONFIG_CACHE", None)
    if c is not None:
        c.clear()
    assert b.deadline is None and "MISWIRED" in b.why and "no parser" in b.why, b


@row("P15", "a no-parser config NOT naming the hook drops (no MISWIRED, no binding)")
def _():
    p = write_json("p15.toml", flat_cfg(str(WORK / "unrelated.py"), "timeout = 10"))
    import builtins
    real_import = builtins.__import__

    def no_tomllib(name, *a, **k):
        if name == "tomllib":
            raise ImportError("simulated absence for P15")
        return real_import(name, *a, **k)
    builtins.__import__ = no_tomllib
    sys.modules.pop("tomllib", None)
    c = getattr(g, "_CONFIG_CACHE", None)
    if c is not None:
        c.clear()
    try:
        b = bound(harness_for(p, TOML_REG))
    finally:
        builtins.__import__ = real_import
        c = getattr(g, "_CONFIG_CACHE", None)
    if c is not None:
        c.clear()
    assert b.deadline is None and "MISWIRED" not in b.why and "no registration" in b.why, b


@row("P16", "a duplicate key in this hook's own entry, AGREEING -> MISWIRED naming the key")
def _():
    text = ('{"hooks": {"PreToolUse": [{"matcher": "", "hooks": ['
            f'{{"command": {json.dumps(ME)}, "timeout": 10, "timeout": 10}}'
            ']}]}}')
    p = write_json("p16.json", text)
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "timeout" in b.why, b


@row("P17", "two files each binding this hook exactly, same timeout -> MISWIRED duplicate/conflicting")
def _():
    p1 = write_json("p17a.json", nested_cfg(ME, 10))
    p2 = write_json("p17b.json", nested_cfg(ME, 10))
    h = harness_for(p1, JSON_REG)
    reg2 = dict(JSON_REG); reg2["path"] = str(p2)
    h["registrations"] = [dict(JSON_REG, path=str(p1)), reg2]
    b = bound(h)
    assert b.deadline is None and "MISWIRED" in b.why and "duplicate/conflicting" in b.why, b


@row("P18", "HESTIA_HOOK_TIMEOUT_S=5 joins the min against a 15s registration")
def _():
    p = write_json("p18.json", nested_cfg(ME, 15))
    b = bound(harness_for(p, JSON_REG), {"HESTIA_HOOK_TIMEOUT_S": "5"})
    assert b.timeout_seconds == 5.0 and b.deadline is not None, b


@row("P19", "HESTIA_HOOK_TIMEOUT_S=25 never lengthens a 15s registration")
def _():
    p = write_json("p19.json", nested_cfg(ME, 15))
    b = bound(harness_for(p, JSON_REG), {"HESTIA_HOOK_TIMEOUT_S": "25"})
    assert b.timeout_seconds == 15.0, b


@row("P20", "HESTIA_HOOK_TIMEOUT_S=abc is MISWIRED evidence, not a deadline")
def _():
    p = write_json("p20.json", nested_cfg(ME, 15))
    b = bound(harness_for(p, JSON_REG), {"HESTIA_HOOK_TIMEOUT_S": "abc"})
    assert b.deadline is None and "not a number" in b.why, b


@row("P21", "HESTIA_HOOK_TIMEOUT_S alone (no registration) binds the declared value")
def _():
    h = harness_for(WORK / "absent.json", JSON_REG)
    b = bound(h, {"HESTIA_HOOK_TIMEOUT_S": "12"})
    assert b.timeout_seconds == 12.0 and b.deadline is not None, b


@row("P22", "HESTIA_HOOK_TIMEOUT_S=-3 is evidence, never a deadline")
def _():
    p = write_json("p22.json", nested_cfg(ME, 15))
    b = bound(harness_for(p, JSON_REG), {"HESTIA_HOOK_TIMEOUT_S": "-3"})
    assert b.deadline is None and "not positive" in b.why, b


@row("P23", "no registration anywhere -> plain no-registration reason, NOT MISWIRED")
def _():
    b = bound(harness_for(WORK / "absent.json", JSON_REG))
    assert b.deadline is None and "no registration" in b.why and "MISWIRED" not in b.why, b


@row("P24", "a broken config NOT naming the hook is ignored outright")
def _():
    p = write_json("p24.json", '{"hooks": not json at all')
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "no registration" in b.why and "MISWIRED" not in b.why, b


# ── the 14 P1/P2 rows (relevance + duplicate attribution) ─────────────────────────────────
@row("R01", "exact absolute binding -> bound (P1 control)")
def _():
    p = write_json("r01.json", nested_cfg(ME, 10))
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 10.0 and b.deadline is not None, b


@row("R02", "relative `./base` spelling beside a longer exact binding -> MISWIRED, not dropped")
def _():
    p = write_json("r02.json", nested_cfg(f"./{BASE}", 25))
    b = bound(harness_for(p, JSON_REG), env_extra=None)
    # cwd-relative: the gate cannot resolve ./ here, so the relative command names without binding
    assert b.deadline is None and "MISWIRED" in b.why and "without binding" in b.why, b


@row("R03", "a FOREIGN absolute path bearing the basename -> MISWIRED (names, does not bind)")
def _():
    foreign = f"/tmp/elsewhere/{BASE}"
    p = write_json("r03.json", nested_cfg(foreign, 10))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R04", "glued `;` spelling MISWIRES (it really runs the hook under sh)")
def _():
    p = write_json("r04.json", nested_cfg(f"{ME}; echo done", 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R05", "glued `&&` spelling MISWIRES")
def _():
    p = write_json("r05.json", nested_cfg(f"true&&{ME}", 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R06", "glued pipe spelling MISWIRES")
def _():
    p = write_json("r06.json", nested_cfg(f"{ME}|cat", 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R07", "subshell-glued spelling MISWIRES")
def _():
    p = write_json("r07.json", nested_cfg(f"(python3 {ME})", 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R08", "`base.bak` DROPS — a longer name containing the basename is a different file")
def _():
    p = write_json("r08.json", nested_cfg(f"{ME}.bak", 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "no registration" in b.why and "MISWIRED" not in b.why, b


@row("R09", "`xbase` / `base5` DROP — prefix/suffix glued alphanumerics are different files")
def _():
    d = WORK / "sub"; d.mkdir()
    p = write_json("r09.json", nested_cfg(f"{WORK}/x{BASE}", 25))
    b = bound(harness_for(p, JSON_REG))
    assert "MISWIRED" not in b.why and b.deadline is None, b


@row("R10", "quote-split spelling `./pre_tool_'use'.py` MISWIRES (shell removes the quotes)")
def _():
    rel = f"./pre_tool_'use'.py"
    p = write_json("r10.json", nested_cfg(rel, 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R11", "backslash-escaped spelling MISWIRES (shell removes the backslash)")
def _():
    rel = "./pre_tool_\\use.py"
    p = write_json("r11.json", nested_cfg(rel, 25))
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why, b


@row("R12", "a duplicate key in ANOTHER hook's entry leaves this hook's clean binding alone")
def _():
    other = str(WORK / "other.py")
    text = ('{"hooks": {"PreToolUse": [{"matcher": "", "hooks": ['
            f'{{"command": {json.dumps(other)}, "timeout": 20, "timeout": 20}},'
            f'{{"command": {json.dumps(ME)}, "timeout": 12}}'
            ']}]}}')
    p = write_json("r12.json", text)
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 12.0 and b.deadline is not None, b


@row("R13", "an ENCLOSING agreeing duplicate (whole group repeated identically) -> MISWIRED")
def _():
    group = '{"matcher": "", "hooks": [{"command": ' + json.dumps(ME) + ', "timeout": 10}]}'
    text = '{"hooks": {"PreToolUse": [' + group + '], "PreToolUse": [' + group + ']}}'
    p = write_json("r13.json", text)
    b = bound(harness_for(p, JSON_REG))
    assert b.deadline is None and "MISWIRED" in b.why and "identical" in b.why, b


@row("R14", "overwritten duplicate objects' recycled ids hang nothing on a clean registration (B1)")
def _():
    # many duplicate-bearing throwaway objects (freed at parse end), then the clean entry last
    junk = ",".join('{"dupkey": 1, "dupkey": %d, "command": "/tmp/nope%d.py", "timeout": 7}' % (i, i)
                    for i in range(400))
    text = ('{"hooks": {"PreToolUse": [{"matcher": "", "hooks": [' + junk +
            ',{"command": ' + json.dumps(ME) + ', "timeout": 14}]}]}}')
    p = write_json("r14.json", text)
    b = bound(harness_for(p, JSON_REG))
    assert b.timeout_seconds == 14.0 and b.deadline is not None, b


def main():
    fails = []
    print(f"gate under test: {GATE}")
    print(f"hook: {ME}")
    print(f"{'row':5s} {'verdict':7s} note")
    for rid, note, fn in ROWS:
        cache = getattr(g, "_CONFIG_CACHE", None)
        if cache is not None:
            cache.clear()
        try:
            fn()
            print(f"{rid:5s} PASS    {note}")
        except AssertionError as e:
            fails.append(rid)
            print(f"{rid:5s} FAIL    {note}\n        {e.args[0] if e.args else e}")
        except Exception as e:
            fails.append(rid)
            print(f"{rid:5s} ERROR   {note}\n        {type(e).__name__}: {e}")
    n_proto = sum(1 for r, _, _ in ROWS if r.startswith("P"))
    print(f"\n{len(ROWS)} rows ({n_proto} protocol + {len(ROWS)-n_proto} P1/P2), "
          f"{len(ROWS)-len(fails)} green, {len(fails)} red"
          + (f": {', '.join(fails)}" if fails else ""))
    return 1 if fails else 0


sys.exit(main())
