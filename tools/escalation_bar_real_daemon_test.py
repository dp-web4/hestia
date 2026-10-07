#!/usr/bin/env python3
"""The RECORDED bar of a real escalation, opened by every seat's real gate on a real daemon.

Why this exists. The seat-boundary suite asserts that a write to a member's gate entry is
REFUSED, against a stub daemon whose escalation reply is canned, so it cannot see the price the
daemon records. An escalation that opens at one approver where two factors were owed is refused
just the same, and is weaker. This file runs each seat's real gate against an ISOLATED daemon,
lets the daemon open the escalation for real, then reads the escalation back
(`hestia://escalation/<id>`) and asserts the bar it recorded.

It covers the spellings whose summary cannot carry the entry's location: a write relative to the
event cwd, a `cd` then a bare name, and a long command whose summary cuts the path off. The
daemon must price all of them from the location the gate resolved and sent, never from the
summary. A same-named file outside every declared location is the negative control: it must
record one approver.

Runs only against an isolated daemon, never the live one:
    HESTIA_ESCALATION_BAR_ENDPOINT=http://127.0.0.1:7799/mcp python3 tools/escalation_bar_real_daemon_test.py
CI's isolated-daemon job sets it. An endpoint on :7711 (the live daemon's port) is refused.
Unset, the file says it ran nothing and exits 0.
"""
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
sys.path.insert(0, str(SHARED))
import seat_gate_boundary_test as sb  # noqa: E402  (its fixture, shim runner and event shapes)

LIVE_PORT = 7711
ENDPOINT = os.environ.get("HESTIA_ESCALATION_BAR_ENDPOINT", "").strip()
FAILS: list = []


def check(name, ok, detail=""):
    if not ok:
        FAILS.append(f"{name}: {str(detail)[:600]}")


def _post(url, body, session=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        **({"mcp-session-id": session} if session else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        sid = r.headers.get("mcp-session-id")
        raw = r.read().decode()
    if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
        raw = "\n".join(ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:"))
    return sid, (json.loads(raw) if raw.strip() else None)


def read_escalation(url, esc_id):
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "escalation-bar-test", "version": "0"}}})
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, out = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                         "params": {"uri": f"hestia://escalation/{esc_id}"}}, sid)
    contents = ((out or {}).get("result") or {}).get("contents") or []
    return json.loads(contents[0]["text"]) if contents else {"_raw": out}


ESC_ID = re.compile(r"Escalation ([0-9a-f]{8,}) is open")


def open_and_read(seat, home, event, label, shim_path=None):
    # A cold daemon (a debug build's first claims) can miss the gate's claim deadline: the gate
    # then says OUTCOME UNKNOWN and that re-issuing the identical act is safe (it returns the
    # same escalation). Re-issue, bounded; the refusal itself never depends on it.
    for _attempt in range(3):
        v, text, _ = sb.run(seat, home, event, shim_path=shim_path)
        if "OUTCOME UNKNOWN" not in text:
            break
    check(f"{seat}-{label}-refused", v == "deny" and "gate.self_access" in text, text)
    m = ESC_ID.search(text)
    check(f"{seat}-{label}-escalation-opened", m, text)
    return read_escalation(ENDPOINT, m.group(1)) if m else {}


def test_every_seat_records_two_factors_for_its_own_entry_whatever_the_spelling():
    for seat in sb.SEATS:
        fx = sb.Fixture()
        try:
            home = fx.home(seat, ENDPOINT)
            target = sb._install_surfaces(seat, home)["entry"]
            dest, base = os.path.dirname(target), os.path.basename(target)
            os.makedirs(dest, exist_ok=True)
            want = os.path.realpath(target)
            long_src = "/tmp/" + "s" * 230 + "/staged/x.py"
            forms = [
                ("relative-write", "Write", {"file_path": base, "content": "x"}, dest),
                ("cd-then-touch", "Bash", {"command": f"cd {dest} && touch {base}"}, None),
                ("summary-cut", "Bash", {"command": f"cp {long_src} {dest}/{base}"}, None),
            ]
            for n, (label, tool, ti, cwd) in enumerate(forms, start=60):
                ev = sb.native(seat, tool, ti, n=n)
                if cwd:
                    ev["cwd"] = cwd
                rec = open_and_read(seat, home, ev, label)
                check(f"{seat}-{label}-bar", rec.get("bar") == "sovereign_plus_peer", rec)
                check(f"{seat}-{label}-resolved-target", want in (rec.get("resolved_targets") or []),
                      (want, rec.get("resolved_targets")))
        finally:
            fx.close()


def test_a_same_named_file_outside_every_location_records_one_approver():
    # Only meaningful for an entry whose NAME is not sovereign everywhere: the member whose
    # entry is priced by location alone.
    seat = "gemini"
    fx = sb.Fixture()
    try:
        home = fx.home(seat, ENDPOINT)
        base = os.path.basename(sb._install_surfaces(seat, home)["entry"])
        stray = os.path.join(fx.repo, "docs", "hooks", base)
        os.makedirs(os.path.dirname(stray), exist_ok=True)
        rec = open_and_read(seat, home, sb.native(seat, "Write", {"file_path": stray, "content": "x"},
                                                  n=90), "outside-control")
        check("outside-control-bar", rec.get("bar") == "single_approver", rec)
    finally:
        fx.close()


def test_a_gate_registered_outside_every_declaration_records_two_factors():
    """A seat whose harness registration runs hestia's gate from a legacy dir no declaration
    names: a write to that gate is refused and the daemon RECORDS sovereign_plus_peer, under the
    registered-entry marker — priced like a declared entry, from what the seat actually runs."""
    for seat in ("claude-code", "gemini"):
        fx = sb.Fixture()
        try:
            home = fx.home(seat, ENDPOINT)
            _legacy, entry, _wit = sb._legacy_install(seat, home)
            rec = open_and_read(seat, home, sb.native(seat, "Write", {"file_path": entry, "content": "x"},
                                                      n=95), "registered-entry", shim_path=entry)
            check(f"{seat}-registered-entry-bar", rec.get("bar") == "sovereign_plus_peer", rec)
            check(f"{seat}-registered-entry-marker", rec.get("marker") == sb.REGISTERED_ENTRY_MARKER, rec)
        finally:
            fx.close()


def test_a_wildcard_or_unresolved_destination_records_two_factors():
    """Codex review of #1247 at 18f91db (notice 18786), both P1s, through the real shim:
    a wildcard that can expand onto the REGISTERED entry, and a destination the gate cannot
    resolve (`$TARGET`), each record sovereign_plus_peer. A wildcard that cannot reach the entry
    is the control: one approver."""
    seat = "gemini"
    fx = sb.Fixture()
    try:
        home = fx.home(seat, ENDPOINT)
        legacy, entry, _wit = sb._legacy_install(seat, home)
        base = os.path.basename(entry)
        for n, (label, target, want) in enumerate((
            ("registered-glob", os.path.join(legacy, base[:3] + "*"), "sovereign_plus_peer"),
            # Codex re-review (notice 18830, P1): fnmatch missed these two Bash bracket forms.
            ("registered-caret-negation", os.path.join(
                legacy, "[^" + ("y" if base[0] == "z" else "z") + "]" + base[1:]),
             "sovereign_plus_peer"),
            ("registered-posix-class", os.path.join(legacy, "[[:print:]]" + base[1:]),
             "sovereign_plus_peer"),
            ("registered-glob-control", os.path.join(legacy, "zz_*"), "single_approver"),
            ("unresolved-target", os.path.join(legacy, "$TARGET"), "sovereign_plus_peer"),
        ), start=110):
            rec = open_and_read(seat, home, sb.native(seat, "Bash", {"command": "touch " + target},
                                                      n=n), label, shim_path=entry)
            check(f"{label}-bar", rec.get("bar") == want, (want, rec))
    finally:
        fx.close()


ALL = [
    test_a_gate_registered_outside_every_declaration_records_two_factors,
    test_a_wildcard_or_unresolved_destination_records_two_factors,
    test_every_seat_records_two_factors_for_its_own_entry_whatever_the_spelling,
    test_a_same_named_file_outside_every_location_records_one_approver,
]

if __name__ == "__main__":
    if not ENDPOINT:
        print("escalation bar (real daemon): NOT RUN -- set HESTIA_ESCALATION_BAR_ENDPOINT to an "
              "isolated daemon (never :7711). Nothing was checked.")
        sys.exit(0)
    if urllib.parse.urlparse(ENDPOINT).port == LIVE_PORT:
        print(f"refused: {ENDPOINT} is the live daemon's port")
        sys.exit(2)
    print(f"escalation bar -- every seat's real gate against the isolated daemon at {ENDPOINT}")
    for t in ALL:
        before = len(FAILS)
        try:
            t()
        except Exception as e:  # noqa: BLE001
            FAILS.append(f"{t.__name__}: raised {type(e).__name__}: {e}")
        print(("PASS " if len(FAILS) == before else "FAIL ") + t.__name__)
    for f in FAILS:
        print("  -", f)
    sys.exit(1 if FAILS else 0)
