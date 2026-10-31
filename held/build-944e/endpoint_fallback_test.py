#!/usr/bin/env python3
"""hestia #944, endpoint half: a gate with no projected endpoint sends nothing, to any port.

On 2026-10-06 (#1246) a CI harness ran gates whose registration carried no HESTIA_HOME. The
decision path refused, but the side paths fell back to http://127.0.0.1:7711/mcp, reached the live
daemon, and opened four real escalations under codex's and kimi-code's names.

Loads the mechanism named by HESTIA_MECH_UNDER_TEST (default: the repo's), so the same rows run
against main (expected to FAIL rows 1-3) and the held result (expected to pass all).
Run: HESTIA_MECH_UNDER_TEST=<out>/mech_rev.py python3 held/build-944e/endpoint_fallback_test.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
import urllib.request

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
SRC = os.environ.get("HESTIA_MECH_UNDER_TEST") or str(ROOT / "plugins" / "_shared" / "hestia_gate_mechanism.py")
spec = importlib.util.spec_from_file_location("hestia_gate_mechanism", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["hestia_gate_mechanism"] = m
spec.loader.exec_module(m)

SENT = []


class _Refuse(Exception):
    pass


def _record(req, timeout=None):
    SENT.append(req.full_url)
    raise _Refuse(req.full_url)


urllib.request.urlopen = _record


def _env(endpoint=None, endpoint_file=None):
    home = tempfile.mkdtemp(prefix="hestia944-")
    if endpoint_file is not None:
        pathlib.Path(home, "endpoint").write_text(endpoint_file)
    os.environ["HESTIA_HOME"] = home
    os.environ.pop("HESTIA_ENDPOINT", None)
    if endpoint is not None:
        os.environ["HESTIA_ENDPOINT"] = endpoint
    SENT.clear()


def _calls():
    out = {}
    try:
        out["gate_self_call"] = m.gate_self_call("hestia_request_witness", {}, plugin_id="codex",
                                                 role="role:constellation:member", client_name="t")
    except _Refuse:
        out["gate_self_call"] = "raised"
    try:
        out["scope_call"] = m.scope_call("hestia_scope_claim", {}, plugin_id="codex",
                                         role="role:constellation:member", client_name="t")
    except _Refuse:
        out["scope_call"] = "raised"
    try:
        out["emit_attestation"] = m.emit_attestation([], [], plugin_id="codex",
                                                     role_lct="role:constellation:member")
    except _Refuse:
        out["emit_attestation"] = "raised"
    return out


ROWS = []


def row(fn):
    ROWS.append(fn)
    return fn


@row
def no_endpoint_sends_nothing():
    _env()
    got = _calls()
    assert SENT == [], f"sent to {SENT}"
    assert got == {"gate_self_call": None, "scope_call": None, "emit_attestation": None}, got


@row
def no_endpoint_never_reaches_the_default_port():
    _env()
    _calls()
    assert not any(":7711" in u for u in SENT), SENT


@row
def the_endpoint_file_is_honoured_like_the_decision_path():
    _env(endpoint_file="http://127.0.0.1:65001/mcp\n")
    _calls()
    assert SENT and all(u == "http://127.0.0.1:65001/mcp" for u in SENT), SENT


@row
def an_explicit_endpoint_is_used():
    _env(endpoint="http://127.0.0.1:65002/mcp")
    _calls()
    assert SENT and all(u == "http://127.0.0.1:65002/mcp" for u in SENT), SENT


@row
def the_literal_is_gone_from_the_source():
    text = pathlib.Path(SRC).read_text(encoding="utf-8")
    assert "127.0.0.1:7711" not in text, "a :7711 literal remains in the mechanism"


fails = 0
for fn in ROWS:
    try:
        fn()
        print(f"  ok    {fn.__name__}")
    except AssertionError as e:
        fails += 1
        print(f"  FAIL  {fn.__name__}: {e}")
print(f"{len(ROWS) - fails} passed, {fails} failed  ({SRC})")
sys.exit(1 if fails else 0)
