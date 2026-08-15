#!/usr/bin/env python3
"""Differential: what does the O(n) `host_session_id` reuse scan actually cost?

#423 names #320's scan half as its leading root cause of multi-second stalls,
and #423 itself asks for the control before any fix is written: *"instrument or
sample `s.sessions.len()` against connect latency over an uptime window."*
This is that control, run as a paired differential instead of a correlation —
because the scan sits behind `if let Some(hsid) = host_session_id.as_deref()`,
which gives us a within-daemon A/B nobody has to wait for uptime to obtain:

  arm SCAN  : connect WITH a unique `host_session_id` → enters the scan, matches
              nothing, so it walks the entire resident map under the state lock.
  arm SKIP  : connect WITHOUT one → the `if let` is not taken, no walk.
  arm REUSE : a SECOND connect on the same transport carrying the same
              `host_session_id` → enters the scan and HITS. Not part of the
              scan differential; it separates "cost per connect call" from
              "cost per new transport session", which is what tells a reader
              whether a non-null floor lives in the map or somewhere else.

Both arms are otherwise byte-identical connects issued by the same client at the
same map size, alternating so any drift in daemon state hits both arms equally.
`median(SCAN) - median(SKIP)` is the scan's cost at the current `sessions.len()`,
measured rather than reasoned about.

Caveats stated up front, since a null here is the interesting outcome:
- Each connect mints a resident session (#320 — no remover), so this instrument
  grows the population it measures by 2N. It reports the before/after size.
- A null result bounds the SCAN ARM ONLY. It does not exonerate the state lock:
  another holder (witness write, reputation fold) stalling the request path is a
  different hypothesis this cannot see.
- Arm SCAN's ids are unique, i.e. worst case — a full walk every time. A real
  reusing seat can short-circuit early, so this is an upper bound on the cost.

Usage: python3 tools/session_scan_cost_differential.py [N] [--json]
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_handshake_latency_probe import Client, endpoint, unwrap  # noqa: E402
from session_residency_census import read_siblings, sessions_of  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
PLUGIN = "contention-probe"


def resident_count(c: Client) -> int:
    doc = read_siblings(c)
    sessions, _ = sessions_of(doc)
    return len(sessions)


def fresh_client() -> Client:
    c = Client(endpoint(), timeout=30.0)
    init = c._post("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "scan-cost-differential", "version": "0"},
    })
    if "result" not in init:
        raise SystemExit(f"initialize failed: {json.dumps(init)[:400]}")
    c._post("notifications/initialized", {}, notify=True)
    return c


def one_connect(c: Client, host_session_id):
    args = {
        "plugin_id": PLUGIN,
        "plugin_version": "probe",
        # the probe's own name, never "claude-code": a leaked seat must render
        # as the probe it is on hestia://session/siblings (#316 re-review).
        "host_agent": "scan-cost-differential",
        "host_agent_version": "probe",
        "requested_role": "citizen",
        "protocol_version": PROTOCOL_VERSION,
        "role": "role:constellation:member",
        "synthetic": True,
    }
    if host_session_id is not None:
        args["host_session_id"] = host_session_id
    t = time.monotonic()
    resp = c.call_tool("hestia_connect", args)
    dt = (time.monotonic() - t) * 1000
    ok = isinstance(unwrap(resp), dict)
    return dt, ok


def main() -> int:
    as_json = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 12

    meter = fresh_client()
    before = resident_count(meter)

    scan, skip, reuse, errors = [], [], [], 0
    for i in range(n):
        # alternate arm order per iteration so neither arm owns the warm slot
        hsid = f"scan-cost-diff-{i}-{time.monotonic_ns()}"
        order = [("scan", hsid), ("skip", None)]
        if i % 2:
            order.reverse()
        for arm, key in order:
            c = fresh_client()
            dt, ok = one_connect(c, key)
            if not ok:
                errors += 1
                continue
            (scan if arm == "scan" else skip).append(dt)
            if arm == "scan":
                # same transport, same key: the scan now HITS on the session the
                # line above just minted. Mints nothing further.
                dt2, ok2 = one_connect(c, key)
                if ok2:
                    reuse.append(dt2)
                else:
                    errors += 1

    after = resident_count(meter)

    def stats(xs):
        if not xs:
            return None
        return {
            "n": len(xs),
            "median_ms": round(statistics.median(xs), 3),
            "mean_ms": round(statistics.fmean(xs), 3),
            "min_ms": round(min(xs), 3),
            "max_ms": round(max(xs), 3),
        }

    out = {
        "resident_sessions_before": before,
        "resident_sessions_after": after,
        "minted_by_this_run": after - before,
        "arm_scan_with_host_session_id": stats(scan),
        "arm_skip_no_host_session_id": stats(skip),
        "arm_reuse_second_connect_same_transport": stats(reuse),
        "errors": errors,
    }
    if scan and skip:
        delta = statistics.median(scan) - statistics.median(skip)
        out["scan_cost_ms_at_n"] = round(delta, 3)
        out["n_for_scan_cost"] = after
        # linear extrapolation: how large would the map have to be for the scan
        # alone to cost one second, if cost is linear in n (it is a walk)?
        if delta > 0:
            out["sessions_for_1s_scan_linear"] = int(after * (1000.0 / delta))
        else:
            out["sessions_for_1s_scan_linear"] = None
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    for k, v in out.items():
        print(f"{k:34}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
