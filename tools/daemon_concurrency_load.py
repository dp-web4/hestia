#!/usr/bin/env python3
"""Daemon concurrency load: gate-shaped traffic at rising concurrency, latency percentiles per level.

WHY. The gate refuses with `gate.degraded` when the daemon does not return a member's policy
snapshot inside the gate deadline (claude-code: 10 s registered - 1.5 s margin = 8.5 s). Measured
2026-10-07 on CBP: round trips normally ~0.1 s, stalls of 4.5 s and 8.3 s during a burst (a
1200-test suite plus several sessions and subagents calling the gate). Every daemon handler
serialises on one global state lock. This tool reproduces the burst against an ISOLATED daemon
and is the before/after instrument for each stage of the per-member serialisation plan.

WHAT ONE WORKER ITERATION IS — the gate's real call shape, one fresh MCP session per call (the
hook is a new process per tool call):
  snapshot: initialize -> notifications/initialized -> hestia_connect (stable host_session_id per
            worker, so the reuse arm, as the hook) -> hestia_operating_law -> hestia_scope_status
  witness:  hestia_begin_action -> hestia_query_policy -> hestia_record_outcome   (--witness)
Optional heavy readers (--readers N) poll the operator surfaces the August incident (#482) was
about: /api/dashboard and /api/governance/ledger. Optional CPU pressure (--cpu-burn K) spins K
processes for the whole run, standing in for the test suite.

After each level the tool diffs the daemon's own lock report (`GET /api/debug/locks`, operator
session from <home>/operator.key) over just that level's window: the top holders by total hold,
with p95 from the diffed histogram, and every slow hold the daemon logged inside the window. An
older daemon without the route still gets the client-side table.

IT REFUSES THE LIVE DAEMON. It writes: sessions (which the daemon never drops, #320), chain
entries (begin/outcome), and a member record per simulated member. Port 7711, and whatever
~/.hestia/endpoint names, are refused with no override flag — an override would be the easy path
around the one rule that matters here.

    hestia --home "$H" init ...; hestia --home "$H" serve --bind 127.0.0.1:7799 &
    python3 tools/daemon_concurrency_load.py --endpoint http://127.0.0.1:7799/mcp \\
        --home "$H" --levels 1,4,16,32 --duration 20 --witness --readers 2 --cpu-burn 6 --io-burn 2 \\
        --json-out before.json
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GATE_DEADLINE_S = 8.5  # claude-code: 10 s registered - 1.5 s margin
PROTOCOL_VERSION = "2025-06-18"


def refuse_live(endpoint: str) -> None:
    u = urllib.parse.urlparse(endpoint)
    live = None
    try:
        live = (Path.home() / ".hestia" / "endpoint").read_text().strip()
    except OSError:
        pass
    if u.port == 7711 or (live and urllib.parse.urlparse(live).netloc == u.netloc):
        sys.exit(f"refusing {endpoint}: that is the live daemon. This tool writes sessions, chain "
                 "entries and member records; run it against an isolated daemon "
                 "(hestia --home <tmp> serve --bind 127.0.0.1:<spare port>).")


def parse_rpc(payload: str):
    payload = payload.strip()
    if not payload:
        return None
    if payload.startswith("{"):
        return json.loads(payload)
    for line in payload.splitlines():
        if line.startswith("data:"):
            body = line[5:].strip()
            if body.startswith("{"):
                return json.loads(body)
    return None


class Mcp:
    def __init__(self, endpoint: str, deadline: float):
        self.endpoint, self.deadline, self.sid, self.n = endpoint, deadline, None, 0

    def _post(self, body: dict, notify: bool = False):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline")
        hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            hdrs["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.endpoint, json.dumps(body).encode(), hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=max(0.01, left)) as r:
            self.sid = self.sid or r.headers.get("mcp-session-id")
            if notify:
                return None
            return parse_rpc(r.read().decode("utf-8", "replace"))

    def initialize(self):
        self.n += 1
        return self._post({"jsonrpc": "2.0", "id": self.n, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "daemon-concurrency-load", "version": "1"}}})

    def initialized(self):
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, True)

    def tool(self, name: str, args: dict) -> dict:
        self.n += 1
        r = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                        "params": {"name": name, "arguments": args}}) or {}
        res = r.get("result") or {}
        sc = res.get("structuredContent")
        if isinstance(sc, dict):
            return sc
        try:
            return json.loads(res["content"][0]["text"])
        except Exception:  # noqa: BLE001
            return {"_raw": r}


class Operator:
    """Operator session for the read-only lock report. Ed25519 challenge sign-in."""

    def __init__(self, base: str, key_path: Path):
        self.base, self.key_path, self.token = base, key_path, None

    def _req(self, method: str, path: str, body=None, timeout=30):
        hdrs = {"Content-Type": "application/json"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data, hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")

    def sign_in(self) -> bool:
        try:
            from nacl.signing import SigningKey
            key = json.loads(self.key_path.read_text())
            sk = SigningKey(bytes.fromhex(key["secret_key_hex"])[:32])
            ch = self._req("POST", "/api/operator/challenge", {})["challenge"]
            sess = self._req("POST", "/api/operator/session", {
                "lct_id": key["lct_id"], "challenge": ch,
                "signature": sk.sign(ch.encode()).signature.hex()})
            self.token = sess["token"]
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  (no operator session: {type(e).__name__}: {e}; lock report skipped)")
            return False

    def get(self, path: str, timeout=30):
        return self._req("GET", path, timeout=timeout)


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * len(xs) + 0.5)) - 1))]


def summarize(xs):
    return {"n": len(xs), "p50": pct(xs, .5), "p95": pct(xs, .95), "p99": pct(xs, .99),
            "max": max(xs) if xs else None, "mean": statistics.fmean(xs) if xs else None}


def burn(stop_at: float):
    x = 0
    while time.time() < stop_at:
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF


def io_burn(stop_at: float, d: str, idx: int):
    """Write-and-fsync 8 MiB at a time: the disk pressure a cargo build/test puts on the box,
    which a CPU spinner does not. Every write the daemon fsyncs (chain WAL, vault, trust files)
    then queues behind it."""
    path = os.path.join(d, f"io-burn-{idx}.bin")
    block = os.urandom(1 << 20)
    try:
        while time.time() < stop_at:
            with open(path, "wb") as f:
                for _ in range(8):
                    f.write(block)
                f.flush()
                os.fsync(f.fileno())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def worker(idx, args, stop, out, lock):
    member = f"load-m{idx % args.members}"
    hsid = f"load-hs-{idx}"
    while not stop.is_set():
        rec = {"steps": {}, "ok": False, "err": None}
        t0 = time.monotonic()
        c = Mcp(args.endpoint, t0 + GATE_DEADLINE_S)
        stage = "initialize"
        try:
            def step(name, fn):
                nonlocal stage
                stage = name
                s = time.monotonic()
                v = fn()
                rec["steps"][name] = time.monotonic() - s
                return v
            step("initialize", c.initialize)
            step("initialized", c.initialized)
            conn = step("connect", lambda: c.tool("hestia_connect", {
                "plugin_id": member, "host_agent": "daemon-concurrency-load",
                "requested_role": "citizen", "protocol_version": PROTOCOL_VERSION,
                "instance_name": "gate-policy-fetch", "host_session_id": hsid,
                "gate_capabilities": ["society-floor:v1"]}))
            sid = conn.get("sessionId")
            if not sid:
                raise RuntimeError(f"connect: no sessionId: {str(conn)[:160]}")
            law = step("operating_law", lambda: c.tool("hestia_operating_law", {"session_id": sid}))
            if "law_hash" not in law:
                raise RuntimeError(f"operating_law: {str(law)[:160]}")
            step("scope_status", lambda: c.tool("hestia_scope_status", {"plugin_id": member}))
            rec["snapshot"] = time.monotonic() - t0
            if args.witness:
                w0 = time.monotonic()
                c.deadline = w0 + GATE_DEADLINE_S
                b = step("begin_action", lambda: c.tool("hestia_begin_action", {
                    "session_id": sid, "tool_name": "Read", "target": f"/tmp/load/{idx}.txt",
                    "parameters": {"file_path": f"/tmp/load/{idx}.txt"}}))
                aid = b.get("actionId")
                if not aid:
                    raise RuntimeError(f"begin_action: {str(b)[:160]}")
                step("query_policy", lambda: c.tool("hestia_query_policy", {"action_id": aid}))
                step("record_outcome", lambda: c.tool("hestia_record_outcome", {
                    "action_id": aid, "success": True, "magnitude": 0.1}))
                rec["witness"] = time.monotonic() - w0
            rec["ok"] = True
        except Exception as e:  # noqa: BLE001
            timeout = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError) \
                or "timed out" in str(e)
            rec["err"] = f"{stage}:{'timeout' if timeout else type(e).__name__}"
            rec["elapsed"] = time.monotonic() - t0
        with lock:
            out.append(rec)
        if args.think_ms:
            time.sleep(args.think_ms / 1000)


def reader(op: Operator, stop, out, lock):
    paths = ["/api/dashboard?range=hour", "/api/governance/ledger?limit=200"]
    i = 0
    while not stop.is_set():
        p = paths[i % len(paths)]
        i += 1
        t = time.monotonic()
        try:
            op.get(p, timeout=60)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        with lock:
            out.append({"path": p.split("?")[0], "t": time.monotonic() - t, "ok": ok})
        time.sleep(0.2)


def diff_locks(before, after, t_start_ms, t_end_ms, top=12):
    if not before or not after:
        return None

    def index(rep):
        return {r["label"]: r for r in rep.get("by_label", [])}

    def index_sites(rep):
        return {(r["label"], r["site"]): r for r in rep.get("by_site", [])}

    def d(a, b, key):
        return a.get(key, 0) - (b.get(key, 0) if b else 0)

    def hdiff(a, b, key):
        ha = a.get(key) or []
        hb = (b.get(key) if b else None) or [0] * len(ha)
        return [x - y for x, y in zip(ha, hb)]

    def q(h, qq):
        n = sum(h)
        if n == 0:
            return 0
        rank, seen = max(1, int(-(-n * qq // 1))), 0
        for i, c in enumerate(h):
            seen += c
            if seen >= rank:
                return 1 << (i + 1)
        return 1 << len(h)

    def rows(ia, ib):
        out = []
        for k, a in ia.items():
            b = ib.get(k)
            cnt = d(a, b, "count")
            if cnt <= 0:
                continue
            hh, wh = hdiff(a, b, "hold_hist"), hdiff(a, b, "wait_hist")
            out.append({"label": a["label"], "site": a.get("site"), "count": cnt,
                        "hold_total_ms": d(a, b, "hold_total_ms"),
                        "wait_total_ms": d(a, b, "wait_total_ms"),
                        "hold_p95_us": q(hh, .95), "wait_p95_us": q(wh, .95),
                        "hold_max_us_cumulative": a.get("hold_max_us")})
        out.sort(key=lambda r: -r["hold_total_ms"])
        return out[:top]

    slow = [s for s in after.get("slow_recent", []) if t_start_ms <= s["at_unix_ms"] <= t_end_ms]
    return {"by_label": rows(index(after), index(before)),
            "by_site": rows(index_sites(after), index_sites(before)),
            "slow_in_window": sorted(slow, key=lambda s: -s["hold_ms"])[:top],
            "slow_total_delta": after.get("slow_total", 0) - before.get("slow_total", 0)}


def fmt(v):
    return "-" if v is None else f"{v * 1000:.0f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", required=True, help="isolated daemon MCP endpoint, e.g. http://127.0.0.1:7799/mcp")
    ap.add_argument("--home", help="the isolated daemon's HESTIA home (for operator.key -> lock report)")
    ap.add_argument("--levels", default="1,4,16,32", help="comma-separated concurrency levels")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds per level")
    ap.add_argument("--members", type=int, default=8, help="distinct simulated member ids")
    ap.add_argument("--witness", action="store_true", help="add begin/query_policy/outcome per iteration")
    ap.add_argument("--readers", type=int, default=0, help="operator-surface reader threads (dashboard, ledger)")
    ap.add_argument("--cpu-burn", type=int, default=0, help="CPU-spinning processes for the whole run")
    ap.add_argument("--io-burn", type=int, default=0, help="write+fsync processes for the whole run (disk pressure)")
    ap.add_argument("--think-ms", type=float, default=0.0, help="pause between a worker's iterations")
    ap.add_argument("--warmup", type=float, default=3.0, help="seconds of 1-worker warmup (connect mints members)")
    ap.add_argument("--json-out", help="write the full result here")
    ap.add_argument("--label", default="", help="free text recorded in the result (e.g. 'stage1 before')")
    args = ap.parse_args()
    refuse_live(args.endpoint)
    base = args.endpoint.rsplit("/mcp", 1)[0]
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    op = None
    if args.home:
        op = Operator(base, Path(args.home) / "operator.key")
        if not op.sign_in():
            op = None

    burners = []
    total = args.warmup + len(levels) * (args.duration + 2) + 5
    stop_at = time.time() + total
    for _ in range(args.cpu_burn):
        p = multiprocessing.Process(target=burn, args=(stop_at,), daemon=True)
        p.start()
        burners.append(p)
    if args.io_burn:
        import tempfile
        io_dir = tempfile.mkdtemp(prefix="daemon-load-io-")
        for i in range(args.io_burn):
            p = multiprocessing.Process(target=io_burn, args=(stop_at, io_dir, i), daemon=True)
            p.start()
            burners.append(p)

    # Warm up: mint every simulated member once, so level 1 is not paying first-connect.
    for m in range(args.members):
        stop = threading.Event()
        out = []
        lk = threading.Lock()
        a = argparse.Namespace(**{**vars(args), "witness": False})
        th = threading.Thread(target=worker, args=(m, a, stop, out, lk), daemon=True)
        th.start()
        time.sleep(max(0.05, args.warmup / max(1, args.members)))
        stop.set()
        th.join(GATE_DEADLINE_S + 1)

    result = {"label": args.label, "endpoint": args.endpoint, "args": vars(args), "levels": []}
    print(f"# daemon_concurrency_load {args.label!r}: members={args.members} witness={args.witness} "
          f"readers={args.readers} cpu_burn={args.cpu_burn} duration={args.duration}s/level")
    print(f"{'conc':>4} {'iters':>6} {'snap p50':>8} {'p95':>6} {'p99':>6} {'max':>6} "
          f"{'>8.5s':>6} {'errs':>5} | {'conn p95':>8} {'law p95':>7} {'scope p95':>9} | "
          f"{'wit p95':>7} {'wit max':>7} | {'rdr p95':>7}   (ms)")
    for conc in levels:
        before = None
        if op:
            try:
                before = op.get("/api/debug/locks")
            except Exception:  # noqa: BLE001
                before = None
        stop = threading.Event()
        out, rout = [], []
        lk = threading.Lock()
        t_start_ms = int(time.time() * 1000)
        ths = [threading.Thread(target=worker, args=(i, args, stop, out, lk), daemon=True) for i in range(conc)]
        if op:
            ths += [threading.Thread(target=reader, args=(op, stop, rout, lk), daemon=True)
                    for _ in range(args.readers)]
        for t in ths:
            t.start()
        time.sleep(args.duration)
        stop.set()
        for t in ths:
            t.join(GATE_DEADLINE_S + 60)
        t_end_ms = int(time.time() * 1000)
        after = None
        if op:
            try:
                after = op.get("/api/debug/locks")
            except Exception:  # noqa: BLE001
                after = None
        ok = [r for r in out if r["ok"]]
        snaps = [r["snapshot"] for r in out if "snapshot" in r]
        steps = {k: [r["steps"][k] for r in out if k in r["steps"]]
                 for k in ("initialize", "connect", "operating_law", "scope_status",
                           "begin_action", "query_policy", "record_outcome")}
        wit = [r["witness"] for r in ok if "witness" in r]
        errs = {}
        for r in out:
            if r["err"]:
                errs[r["err"]] = errs.get(r["err"], 0) + 1
        over = sum(1 for r in out if r.get("err", "") and "timeout" in (r["err"] or "")) + \
            sum(1 for s in snaps if s > GATE_DEADLINE_S)
        rdr = [r["t"] for r in rout]
        lvl = {"concurrency": conc, "iterations": len(out), "ok": len(ok),
               "snapshot": summarize(snaps), "witness": summarize(wit),
               "steps": {k: summarize(v) for k, v in steps.items()},
               "over_gate_deadline": over, "errors": errs,
               "readers": summarize(rdr), "locks": diff_locks(before, after, t_start_ms, t_end_ms),
               "sections": diff_locks((before or {}).get("sections"), (after or {}).get("sections"),
                                      t_start_ms, t_end_ms)}
        result["levels"].append(lvl)
        s, st = lvl["snapshot"], lvl["steps"]
        print(f"{conc:>4} {len(out):>6} {fmt(s['p50']):>8} {fmt(s['p95']):>6} {fmt(s['p99']):>6} "
              f"{fmt(s['max']):>6} {over:>6} {sum(errs.values()):>5} | {fmt(st['connect']['p95']):>8} "
              f"{fmt(st['operating_law']['p95']):>7} {fmt(st['scope_status']['p95']):>9} | "
              f"{fmt(lvl['witness']['p95']):>7} {fmt(lvl['witness']['max']):>7} | "
              f"{fmt(lvl['readers']['p95']):>7}")
        if errs:
            print(f"       errors: {errs}")
        lk_ = lvl["locks"]
        if lk_:
            for r in lk_["by_label"][:6]:
                print(f"       hold {r['hold_total_ms']:>7} ms  n={r['count']:<6} p95={r['hold_p95_us']/1000:.1f}ms "
                      f"wait_tot={r['wait_total_ms']} ms  {r['label']}")
            for sl in lk_["slow_in_window"][:5]:
                print(f"       SLOW hold {sl['hold_ms']} ms (wait {sl['wait_ms']} ms) {sl['label']} @ {sl['site'].rsplit('/src/', 1)[-1]}")
        sec = lvl["sections"]
        if sec:
            for r in sec["by_label"][:5]:
                print(f"       section {r['label']:<22} tot={r['hold_total_ms']:>6} ms n={r['count']:<6} "
                      f"p95={r['hold_p95_us']/1000:.1f}ms")
            for sl in sec["slow_in_window"][:3]:
                print(f"       SLOW section {sl['label']} {sl['hold_ms']} ms")
    for p in burners:
        p.terminate()
    for p in burners:
        p.join(5)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=1))
        print(f"# wrote {args.json_out}")


if __name__ == "__main__":
    main()
