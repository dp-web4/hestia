#!/usr/bin/env python3
"""Is the gate's fail-closed timeout class caused by GLOBAL LOCK CONTENTION?

HYPOTHESIS. `tool_query_policy` (handler.rs:1039) takes `state.lock().await` and holds it
across policy evaluation AND `append_chain` (disk write to a 163MB witness.db). If that is
the one mutex every member's verdict passes through, then concurrency -- not intrinsic
slowness -- produces the ~500ms stalls that blow the gate's 800ms budget.

PREDICTION (stated before running): serial handshakes stall rarely; with C concurrent
clients doing the SAME work, the stall rate and the tail both rise sharply, and the tail
grows roughly with C because requests queue behind one lock.

CONTROL, both directions:
  - Arm A (C=1) is the negative control: the same code path with no contention.
  - The rise must be in the LOCKED step (query_policy / begin_action), not in `initialize`,
    which does not touch the state lock. If `initialize` degrades equally, the cause is the
    box (CPU, scheduler), not the lock, and the hypothesis is refuted.

This probe only reads policy for a synthetic Read of a /tmp path. It executes nothing.
"""
import json
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_handshake_latency_probe import Client, endpoint, unwrap  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"


def handshake(url: str, role: str, plugin_id: str) -> dict:
    """One full gate-equivalent handshake; returns per-step ms."""
    c = Client(url)
    steps = {}
    t0 = time.monotonic()

    t = time.monotonic()
    init = c._post("initialize", {
        "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
        "clientInfo": {"name": "lock-contention-probe", "version": "0"},
    })
    steps["initialize"] = (time.monotonic() - t) * 1000
    if "result" not in init:
        raise RuntimeError(f"initialize failed: {init}")
    c._post("notifications/initialized", {}, notify=True)

    t = time.monotonic()
    connect = unwrap(c.call_tool("hestia_connect", {
        "plugin_id": plugin_id, "plugin_version": "probe", "host_agent": "claude-code",
        "host_agent_version": "claude-code", "requested_role": "citizen",
        "protocol_version": PROTOCOL_VERSION, "role": role,
    }))
    steps["connect"] = (time.monotonic() - t) * 1000
    sid = connect.get("sessionId") if isinstance(connect, dict) else None

    t = time.monotonic()
    begin = unwrap(c.call_tool("hestia_begin_action", {
        "tool_name": "Read", "target": "/tmp/gate-lock-probe",
        "parameters": {"file_path": "/tmp/gate-lock-probe"},
        **({"session_id": sid} if sid else {}),
    }))
    steps["begin_action"] = (time.monotonic() - t) * 1000
    aid = begin.get("actionId") if isinstance(begin, dict) else None
    if not aid:
        raise RuntimeError(f"no actionId: {begin}")

    t = time.monotonic()
    unwrap(c.call_tool("hestia_query_policy",
                       {"action_id": aid, **({"session_id": sid} if sid else {})}))
    steps["query_policy"] = (time.monotonic() - t) * 1000
    steps["total"] = (time.monotonic() - t0) * 1000
    return steps


def arm(url: str, role: str, plugin_id: str, concurrency: int, per_worker: int) -> list:
    out, lock = [], threading.Lock()

    def worker():
        local = []
        for _ in range(per_worker):
            try:
                local.append(handshake(url, role, plugin_id))
            except Exception as e:  # noqa: BLE001
                local.append({"error": f"{type(e).__name__}: {e}"})
        with lock:
            out.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = (time.monotonic() - t0) * 1000
    return out, wall


def summarize(rows, budget=800):
    ok = [r for r in rows if "error" not in r]
    errs = len(rows) - len(ok)
    if not ok:
        return {"n": 0, "errors": errs}
    tot = sorted(r["total"] for r in ok)
    n = len(tot)

    def pct(v, p):
        return v[min(len(v) - 1, int(len(v) * p / 100))]

    res = {
        "n": n, "errors": errs,
        "p50": round(pct(tot, 50), 1), "p90": round(pct(tot, 90), 1),
        "p99": round(pct(tot, 99), 1), "max": round(tot[-1], 1),
        "over_budget": sum(1 for x in tot if x > budget),
        "stalls_gt_100ms": sum(1 for x in tot if x > 100),
    }
    for step in ("initialize", "connect", "begin_action", "query_policy"):
        v = sorted(r[step] for r in ok)
        res[f"{step}_p50"] = round(pct(v, 50), 1)
        res[f"{step}_p99"] = round(pct(v, 99), 1)
        res[f"{step}_max"] = round(v[-1], 1)
    return res


def main():
    url = endpoint()
    role = "role:constellation:member"
    plugin_id = "claude-code"
    per_worker = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    arms = [1, 2, 4, 8]
    print(f"endpoint={url}  per_worker={per_worker}  arms(concurrency)={arms}")
    print("prediction: stall rate + tail rise with concurrency, and the rise is in the")
    print("LOCKED steps (begin_action/query_policy), not in initialize.\n")
    results = {}
    for c in arms:
        rows, wall = arm(url, role, plugin_id, c, per_worker)
        s = summarize(rows)
        s["wall_ms"] = round(wall, 1)
        s["concurrency"] = c
        results[c] = s
        print(f"C={c:2d}  n={s['n']:4d}  p50={s['p50']:7.1f}  p90={s['p90']:7.1f}  "
              f"p99={s['p99']:8.1f}  max={s['max']:8.1f}  >800ms={s['over_budget']:3d}  "
              f">100ms={s['stalls_gt_100ms']:3d}  errors={s['errors']}")
        time.sleep(1.0)  # let the daemon settle between arms

    print("\nper-step p99 (ms) — initialize is the unlocked control:")
    print(f"{'C':>3} {'initialize':>11} {'connect':>9} {'begin_action':>13} {'query_policy':>13}")
    for c in arms:
        s = results[c]
        print(f"{c:>3} {s['initialize_p99']:>11.1f} {s['connect_p99']:>9.1f} "
              f"{s['begin_action_p99']:>13.1f} {s['query_policy_p99']:>13.1f}")

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
