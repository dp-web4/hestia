#!/usr/bin/env python3
"""Differential: what does the O(n) `host_session_id` reuse scan actually cost?

#423 names #320's scan half as its leading root cause of multi-second stalls,
and #423 itself asks for the control before any fix is written: *"instrument or
sample `s.sessions.len()` against connect latency over an uptime window."*
This is that control, run as a paired differential instead of a correlation —
because the scan sits behind `if let Some(hsid) = host_session_id.as_deref()`,
which gives us a within-daemon A/B nobody has to wait for uptime to obtain.

FIVE arms. The distinction that matters is not scan/no-scan alone; it is
*which* connects provably traverse the WHOLE map, because only those can bound
a per-resident cost (codex, PR #452 second pass):

  cold_miss : FIRST connect on a fresh transport, UNIQUE `host_session_id`.
              Enters the scan, matches nothing → walks the entire map. Also
              pays whatever a new transport session costs (that turns out to
              dominate everything here, ~115 ms).
  cold_skip : FIRST connect on a fresh transport, NO id → the `if let` is not
              taken, no walk. Pairs with cold_miss.
  warm_miss : a LATER connect on an already-warmed transport, UNIQUE id.
              Guaranteed full traversal of every resident, WITHOUT the
              first-transport floor. *** This is the only arm that bounds the
              scan: part ≤ whole, so the walk cost ≤ this call's total. ***
  warm_skip : a LATER connect on the same warmed transport, NO id. Pairs with
              warm_miss; their difference is the walk, floor removed.
  warm_hit  : a LATER connect carrying an id a live session already has, so
              `values_mut().find(..)` SHORT-CIRCUITS at the matched entry
              (handler.rs:578-582). `HashMap` gives that entry no traversal
              position guarantee, so this arm walks an UNKNOWN PREFIX of the
              map — between 1 and n comparisons. It is reported because it
              separates per-call cost from per-transport cost, and it is
              explicitly NOT a bound on a full walk. (A previous run of this
              instrument used it as one; that was wrong.)

Arms are byte-identical connects apart from the id, issued by the same client
at the same map size, with arm order alternating per iteration so no arm owns
the warm slot or the head of a transport.

Caveats stated up front, since a null here is the interesting outcome:
- Each *successful* connect except warm_hit mints a resident session (#320 —
  no remover), so this instrument grows the population it measures, by 5 per
  iteration. Before/after sizes and a per-sample estimate of `sessions.len()`
  are reported so a reader can see whether latency tracks n within the run.
- A null bounds the SCAN ARM ONLY. It does not exonerate the state lock:
  another holder (witness write, reputation fold) stalling the request path is
  a different hypothesis this cannot see.
- A sample is admitted only if the response has the SUCCESS SHAPE (a
  `sessionId`, no JSON-RPC error, no tool-error envelope). Rejects are counted
  by class and printed — an error's latency is not a connect's latency, and a
  run that cannot show its samples were successful connects proves nothing.

Usage: python3 tools/session_scan_cost_differential.py [N] [--json]
"""
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_handshake_latency_probe import Client, endpoint  # noqa: E402
from session_residency_census import read_siblings, sessions_of  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
PLUGIN = "contention-probe"

# arms whose successful connect adds a resident to the map
MINTING_ARMS = {"cold_miss", "cold_skip", "warm_miss", "warm_skip"}


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


def classify(resp):
    """(ok, reject_class). A sample is admitted ONLY on the success shape.

    `unwrap()` in the shared probe module returns `resp.get("result", resp)` on
    any parse failure, so BOTH a JSON-RPC error object and a Hestia tool-error
    envelope come back as dicts — `isinstance(x, dict)` admits them as
    successful connects. It is not a success test; this is.
    """
    if not isinstance(resp, dict):
        return False, "not_a_dict"
    if "error" in resp:
        return False, "jsonrpc_error"
    result = resp.get("result")
    if not isinstance(result, dict):
        return False, "no_result"
    if result.get("isError") is True:
        return False, "tool_error_flag"
    try:
        payload = json.loads(result["content"][0]["text"])
    except Exception:
        return False, "unparseable_content"
    if not isinstance(payload, dict):
        return False, "content_not_object"
    if payload.get("error") or payload.get("denied") or payload.get("status") == "error":
        return False, "tool_error_envelope"
    sid = payload.get("sessionId")
    if not isinstance(sid, str) or not sid:
        return False, "no_session_id"
    return True, None


def one_connect(c: Client, host_session_id, synthetic: bool = True):
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
        "synthetic": synthetic,
    }
    if host_session_id is not None:
        args["host_session_id"] = host_session_id
    t = time.monotonic()
    try:
        resp = c.call_tool("hestia_connect", args)
    except Exception as exc:  # timeout, reset, malformed frame
        return (time.monotonic() - t) * 1000, False, f"transport:{type(exc).__name__}"
    dt = (time.monotonic() - t) * 1000
    ok, why = classify(resp)
    return dt, ok, why


def uniq(tag: str, i: int) -> str:
    return f"scan-cost-{tag}-{i}-{time.monotonic_ns()}"


VAULT = Path.home() / ".hestia" / "vault.enc"


def vault_stamp():
    """(mtime_ns, size) of the single-file vault every `save_doc` rewrites."""
    try:
        st = VAULT.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def writecheck() -> int:
    """Two-sided: the synthetic connect must MOVE the vault, the no-vault arm must NOT.

    The no-vault arm's whole claim is that it removes `mark_synthetic` →
    `vault::save_doc` and nothing else. Timing alone is suggestive (0.6 ms vs
    113 ms); this watches the artifact the write produces. Caveat, stated
    because it is the only way this can lie: another member connecting for the
    first time also writes the vault, so a MOVE on the no-vault side is
    inconclusive, while a HOLD is the informative outcome — and the synthetic
    side is the positive control proving the observation window is wide enough
    to see a write at all.
    """
    c = fresh_client()
    rows = []
    for label, syn in (("synthetic=true (expect MOVE)", True),
                       ("synthetic=false, id already excluded (expect HOLD)", False)):
        a = vault_stamp()
        dt, ok, why = one_connect(c, uniq("wc", 0), synthetic=syn)
        b = vault_stamp()
        rows.append((label, ok or f"REJECTED:{why}", round(dt, 3), a != b))
    print(f"{'arm':52} {'ok':6} {'ms':>9}  vault moved")
    for label, ok, ms, moved in rows:
        print(f"{label:52} {str(ok):6} {ms:9.3f}  {moved}")
    good = rows[0][3] and not rows[1][3]
    print(f"\ntwo-sided control satisfied (write on synthetic, none on no-vault): {good}")
    return 0 if good else 1


def bootstrap_ci(xs, reps=4000, lo=2.5, hi=97.5, seed=20260815):
    """Percentile bootstrap CI of the MEDIAN. Fixed seed: a re-run must agree."""
    rng = random.Random(seed)
    k = len(xs)
    meds = sorted(statistics.median(rng.choices(xs, k=k)) for _ in range(reps))

    def pct(p):
        idx = min(len(meds) - 1, max(0, int(round(p / 100.0 * (len(meds) - 1)))))
        return meds[idx]

    return round(pct(lo), 4), round(pct(hi), 4)


def novault_pairs(m: int, before: int, minted_start: int):
    """The TIGHT arm: connects that traverse the whole map with no vault write.

    The 113 ms floor every synthetic arm pays is `mark_synthetic` →
    `vault::save_doc`, called UNCONDITIONALLY on each synthetic connect
    (state.rs:581-602) — it re-writes the doc even when the id is already in
    the set. It swamps the walk by five orders of magnitude, which is why the
    synthetic arms can only bound the scan at ~120 µs/resident.

    Declaring `synthetic: false` under a plugin_id that is ALREADY in the
    exclusion set removes exactly that write and nothing else:
      - `if synthetic { mark_synthetic }` is skipped        (handler.rs:626)
      - `if !synthetic { ensure_member }` runs but returns None at its first
        guard, because `is_syn` comes from the SERVER's set, not the request
        (member_registry.rs:216) — no LCT is minted, no member doc is written.
      - the reuse scan and the session insert are unchanged.
    The exclusion is not assumed: the caller establishes it with a synthetic
    connect first, in this same run, and that connect's success IS the proof
    the doc was persisted (mark_synthetic is fail-closed — it refuses the
    connect if the write fails).

    All calls ride ONE warmed transport, so no sample pays first-transport
    setup and each arm is a later call. Each connect still mints a resident
    (#320); 2 per pair, reported.
    """
    c = fresh_client()
    # precondition: the exclusion is persisted for PLUGIN, proven by a
    # fail-closed synthetic connect that returns success.
    dt, ok, why = one_connect(c, None, synthetic=True)
    if not ok:
        raise SystemExit(f"precondition failed: synthetic connect rejected ({why})")
    minted = minted_start + 1
    miss, skip, paired = [], [], []
    for i in range(m):
        order = [("miss", uniq("nv", i)), ("skip", None)]
        if i % 2:
            order.reverse()
        got = {}
        for arm, key in order:
            dt, ok, why = one_connect(c, key, synthetic=False)
            if not ok:
                return {"error": f"novault sample rejected: {why}"}, minted
            minted += 1
            got[arm] = {"ms": dt, "n": before + minted}
        miss.append(got["miss"])
        skip.append(got["skip"])
        paired.append(got["miss"]["ms"] - got["skip"]["ms"])
    return {"miss": miss, "skip": skip, "paired": paired}, minted


def selftest() -> int:
    """Fire the admission gate on both polarities, and show what the OLD one did.

    A guard that never fires against a live negative is a claim. The old
    predicate was `isinstance(unwrap(resp), dict)`; every row below where OLD
    says ADMIT and NEW says reject is a failed call the published run would
    have timed as a successful connect.
    """
    from gate_handshake_latency_probe import unwrap  # the old predicate's half

    c = fresh_client()
    cases = []

    # live positive: a real connect must still be ADMITTED (polarity check —
    # a gate that rejects everything also "rejects errors")
    resp = c.call_tool("hestia_connect", {
        "plugin_id": PLUGIN, "plugin_version": "probe",
        "host_agent": "scan-cost-differential", "host_agent_version": "probe",
        "requested_role": "citizen", "protocol_version": PROTOCOL_VERSION,
        "role": "role:constellation:member", "synthetic": True,
    })
    cases.append(("live: real connect", resp))

    # live negative 1: a tool that does not exist
    cases.append(("live: unknown tool", c.call_tool("hestia_no_such_tool", {})))
    # live negative 2: connect with a required field missing
    cases.append(("live: connect missing plugin_id", c.call_tool("hestia_connect", {"synthetic": True})))
    # constructed negatives, in the two shapes the old predicate swallowed
    cases.append(("shape: jsonrpc error", {"jsonrpc": "2.0", "id": 1,
                                           "error": {"code": -32602, "message": "bad params"}}))
    cases.append(("shape: tool-error envelope", {"jsonrpc": "2.0", "id": 1, "result": {
        "isError": True,
        "content": [{"type": "text", "text": json.dumps({"error": "denied by policy"})}]}}))

    print(f"{'case':34} {'OLD isinstance(unwrap,dict)':30} NEW")
    disagreements = 0
    for name, resp in cases:
        old = "ADMIT" if isinstance(unwrap(resp), dict) else "reject"
        ok, why = classify(resp)
        new = "ADMIT" if ok else f"reject:{why}"
        if (old == "ADMIT") != ok:
            disagreements += 1
        print(f"{name:34} {old:30} {new}")
    print(f"\ndisagreements (old admitted, new rejects): {disagreements}")
    live_pos_ok, _ = classify(cases[0][1])
    print(f"live positive still admitted: {live_pos_ok}")
    return 0 if (disagreements and live_pos_ok) else 1


def main() -> int:
    as_json = "--json" in sys.argv
    if "--selftest" in sys.argv:
        return selftest()
    if "--writecheck" in sys.argv:
        return writecheck()
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(argv[0]) if argv else 20
    pairs = int(argv[1]) if len(argv) > 1 else 60

    meter = fresh_client()
    before = resident_count(meter)

    samples = {k: [] for k in ("cold_miss", "cold_skip", "warm_miss", "warm_skip", "warm_hit")}
    rejects = Counter()
    minted = 0

    def record(arm, dt, ok, why, at_n):
        nonlocal minted
        if not ok:
            rejects[f"{arm}:{why}"] += 1
            return
        samples[arm].append({"ms": round(dt, 3), "n": at_n})
        if arm in MINTING_ARMS:
            minted += 1

    for i in range(n):
        # --- transport A: the id-carrying transport -------------------------
        # cold_miss (first call, full walk + transport floor), then a warmed
        # pair on the SAME transport: warm_hit (short-circuits on the session
        # cold_miss just minted) and warm_miss (a NEW id → full walk, warm).
        ca = fresh_client()
        key = uniq("A", i)
        dt, ok, why = one_connect(ca, key)
        record("cold_miss", dt, ok, why, before + minted)

        warm_a = [("warm_hit", key), ("warm_miss", uniq("Amiss", i))]
        if i % 2:
            warm_a.reverse()
        for arm, k in warm_a:
            dt, ok, why = one_connect(ca, k)
            record(arm, dt, ok, why, before + minted)

        # --- transport B: the id-free transport -----------------------------
        cb = fresh_client()
        dt, ok, why = one_connect(cb, None)
        record("cold_skip", dt, ok, why, before + minted)
        dt, ok, why = one_connect(cb, None)
        record("warm_skip", dt, ok, why, before + minted)

    nv, minted = novault_pairs(pairs, before, minted) if pairs else (None, minted)

    after = resident_count(meter)

    def stats(rows):
        if not rows:
            return None
        xs = [r["ms"] for r in rows]
        lo = min(rows, key=lambda r: r["ms"])
        return {
            "n_samples": len(xs),
            "median_ms": round(statistics.median(xs), 3),
            "mean_ms": round(statistics.fmean(xs), 3),
            "min_ms": round(lo["ms"], 3),
            "max_ms": round(max(xs), 3),
            "residents_at_min": lo["n"],
        }

    out = {
        "resident_sessions_before": before,
        "resident_sessions_after": after,
        "minted_by_this_run": after - before,
        "arms": {k: stats(v) for k, v in samples.items()},
        "rejected_samples": dict(rejects) or None,
        "rejected_total": sum(rejects.values()),
    }

    wm, ws = samples["warm_miss"], samples["warm_skip"]
    if wm:
        lo = min(wm, key=lambda r: r["ms"])
        # part ≤ whole: this ENTIRE call provably contained a complete
        # traversal of `lo["n"]` residents, so the traversal cost no more.
        out["scan_upper_bound"] = {
            "basis": "fastest warm full-miss connect; the whole call bounds the walk it contains",
            "whole_call_ms": round(lo["ms"], 3),
            "residents_traversed": lo["n"],
            "ns_per_resident_at_most": round(lo["ms"] * 1e6 / lo["n"], 1),
            "residents_for_1s_walk_at_most": int(lo["n"] * 1000.0 / lo["ms"]),
        }
    if wm and ws:
        d = statistics.median([r["ms"] for r in wm]) - statistics.median([r["ms"] for r in ws])
        out["warm_walk_differential_ms"] = round(d, 3)
        out["warm_walk_differential_note"] = (
            "median(warm_miss) - median(warm_skip): the walk with the transport floor "
            "removed. A point estimate at this sample size, not a bound — the bound is "
            "scan_upper_bound above, which needs no differential."
        )

    if nv and "error" not in nv:
        lo = min(nv["miss"], key=lambda r: r["ms"])
        p = nv["paired"]
        out["novault"] = {
            "what": "connects with the unconditional mark_synthetic vault write removed; "
                    "the full-miss arm still traverses every resident",
            "pairs": len(p),
            "miss": stats(nv["miss"]),
            "skip": stats(nv["skip"]),
            "paired_diff_median_ms": round(statistics.median(p), 4),
            "paired_diff_ci95_ms": bootstrap_ci(p),
            "scan_upper_bound": {
                "basis": "fastest no-vault full-miss connect; part ≤ whole",
                "whole_call_ms": round(lo["ms"], 4),
                "residents_traversed": lo["n"],
                "ns_per_resident_at_most": round(lo["ms"] * 1e6 / lo["n"], 1),
                "residents_for_1s_walk_at_most": int(lo["n"] * 1000.0 / lo["ms"]),
            },
        }
    elif nv:
        out["novault"] = nv

    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    for k, v in out.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"  {kk:34}: {vv}")
        else:
            print(f"{k:36}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
