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

CLEANUP (#316 review, Note A): each handshake closes its action with
`hestia_record_outcome` -- `s.actions` has no other remover, so a default run
(4 arms x C x 40 = 600 handshakes) used to leave 600 in-flight actions resident in
the map the global lock protects, and every later run measured a more loaded daemon
than the last: a confound inside the instrument. The close is untimed (it lands
after `total` is taken) but runs inside the arm, so concurrent workers now carry one
witness-chain append per handshake -- write-side load a real gate sequence also
generates (witness.py records outcomes). That makes the C-arms slightly harsher
than the pre-cleanup probe: biased AGAINST the improvement #316 claims, which is
the safe direction. Sessions connect `synthetic: true` under a hardcoded probe id
so nothing reaches member reputation or the hub; see the latency probe's docstring
for why that id must never be a real member's.

Known residue (#316 re-review): the SESSIONS this run opens cannot be drained from
here — `s.sessions` has one insert and no remover daemon-side (#320) — so a default
run leaves 600 of them resident until daemon restart. They lengthen the O(n)
host_session_id reuse scan real gate handshakes pay under the global lock (this
probe skips that scan: it sends no host_session_id). Until the daemon drains, the
probe self-identifies via `host_agent` so the leaked seats are attributable.
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
        # Own name, not "claude-code": sessions have no daemon-side remover
        # (#320), so a default run leaves 600 seats on session/siblings — they
        # must render as probe seats. Descriptive-only field; no fidelity cost.
        "plugin_id": plugin_id, "plugin_version": "probe", "host_agent": plugin_id,
        "host_agent_version": "probe", "requested_role": "citizen",
        "protocol_version": PROTOCOL_VERSION, "role": role, "synthetic": True,
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

    # Close the action (untimed, after `total`; see docstring). Best-effort:
    # a failed close must not turn a successful measurement into an error row.
    # A daemon rejection arrives as a parsed error envelope, not an exception,
    # so count closes by the witness entry hash that proves them.
    try:
        res = unwrap(c.call_tool("hestia_record_outcome",
                                 {"action_id": aid, "success": True, "magnitude": 0.0}))
        steps["_closed"] = isinstance(res, dict) and "witnessEntryHash" in res
    except Exception:  # noqa: BLE001
        steps["_closed"] = False

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
        # actions this arm began but could not close -- each one is left
        # resident in the daemon's in-flight map (the Note A leak); 0 or the
        # cleanup is not doing its job
        "unclosed": sum(1 for r in ok if not r.get("_closed", False)),
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
    # Hardcoded: rides with `synthetic: true`, which durably persists a
    # synthetic exclusion for this id -- it must never be a real member's.
    plugin_id = "gate-lock-probe"
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
              f">100ms={s['stalls_gt_100ms']:3d}  errors={s['errors']}  "
              f"unclosed={s['unclosed']}")
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
