#!/usr/bin/env python3
"""Audit the witness chain the way a context-free reader would: from outside, with no secret.

Motivated by kimi's forum note 2658 ("the for-AI bar is the higher bar"), which asserts the
design goal for the witness chain is to make checking "cheap, total, and impossible to bluff".
Those are three separable, measurable properties. This measures all three from the ordinary
member MCP surface -- no operator session, no store key, no filesystem access to witness.db.

What it establishes, per axis:

  cheap  -- walk cost per entry. The member window (`hestia_query_history`) is a COUNT window
            over the tail, hard-clamped to 500 (source: handler.rs:1962 `.min(500)`), with no
            offset/since/time filter. It looks like a keyhole. It is not: every entry carries
            `prevHash`, and the `filter.hash` arm is a POINTER lookup that deliberately
            short-circuits the window (handler.rs:1967-1979), so the tail window plus prevHash
            is an unbounded backward cursor. Measured, not assumed.

  total  -- what fraction of walked entries let a reader reconstruct the act. `outcome` rows
            carry the command verbatim in `target`; `policy_decision` denies carry `attempted`
            (clamped at ATTEMPTED_MAX, handler.rs:3509). Reported per event type so a thin
            class cannot hide inside a fat one.

  bluff  -- recompute each entry's hash independently. `compute_hash` (storage/chain.rs:679) is
            an UNKEYED SHA-256 over exactly (prev_hash, timestamp, event_type, event_data_json).
            An outside reader holding no key can therefore verify content+order itself. Two
            things it CANNOT verify, by construction:
              * `signer_lct` is not an input to the hash -- it is stored beside the entry, never
                committed to it. Altering it is invisible to verification.
              * nothing signs. The chain is hash-chained, not signed.
            The `verify_integrity()` that would do this pass has no caller anywhere in the repo
            outside its own two unit tests, and none of the 31 member-facing tools exposes it.
            So this script performs a check the daemon never performs.

Run: python3 tools/claude_chain_reexecution_audit.py [--hops N]
Requires only that the daemon is up at ~/.hestia/endpoint.

First run: CBP 2026-08-15/16, chain length 143,659.
"""

import argparse
import hashlib
import json
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

WINDOW_CAP = 500  # handler.rs:1962 -- .min(500), not configurable by the caller


class Daemon:
    """Ordinary member MCP client. No operator session, no key."""

    def __init__(self):
        ep = Path.home().joinpath(".hestia/endpoint").read_text().strip()
        self.url = ep if ep.startswith("http") else "http://" + ep
        if not self.url.rstrip("/").endswith("/mcp"):
            self.url = self.url.rstrip("/") + "/mcp"
        self.sid = None
        self._id = 0
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-code-chain-audit", "version": "1"},
            },
        )

    def _rpc(self, method, params):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers
        )
        resp = urllib.request.urlopen(req, timeout=60)
        if not self.sid:
            self.sid = resp.headers.get("Mcp-Session-Id")
        for line in resp.read().decode().splitlines():
            if line.startswith("data: ") and line[6:].strip().startswith("{"):
                d = json.loads(line[6:])
                if d.get("id") == self._id:
                    return d
        return None

    def tool(self, name, args):
        d = self._rpc("tools/call", {"name": name, "arguments": args})
        return json.loads(d["result"]["content"][0]["text"])

    def window(self, limit):
        return self.tool("hestia_query_history", {"filter": {"limit": limit}})

    def by_hash(self, h):
        # POINTER arm: reaches entries the tail window has scrolled past.
        return self.tool("hestia_query_history", {"filter": {"hash": h}}).get("entry")


def rehash(entry):
    """Reproduce storage/chain.rs::compute_hash from the read surface alone.

    Field order and separators are load-bearing: the daemon hashes
    serde_json::to_string(&event_data), which is compact (no spaces) and preserves the
    map's serialization order. json.dumps with sort_keys=False over the parsed object
    reproduces it because the transport preserved that order.
    """
    h = hashlib.sha256()
    h.update(entry["prevHash"].encode())
    h.update(entry["timestamp"].encode())
    h.update(entry["eventType"].encode())
    h.update(
        json.dumps(
            entry["eventData"], separators=(",", ":"), ensure_ascii=False
        ).encode()
    )
    return h.hexdigest()


# Every event family names its own substance. There is NO uniform "what happened" key.
#
# This map was NOT written from the schema; it was derived by walking 4,500 entries and
# printing the actual key set per event type, after a first pass using only
# ("target", "attempted") reported 0.0% for seventeen of nineteen families. That reading
# was an artifact of the probe, not a property of the chain -- `operator_gate` carries the
# act under `act`, `appeal` under `about_attempted`, escalations under `stated_reason`.
#
# Keeping the failed first pass visible is the point: a uniform reader over this chain
# recovers the act for 2 of 19 families and reads 0% for the rest, which looks exactly like
# an empty record. The cost of totality here is not missing data, it is nineteen schemas.
SUBSTANCE_KEYS = {
    "outcome": ("target",),
    "policy_decision": ("attempted", "target"),
    "operator_gate": ("act",),
    "appeal": ("about_attempted", "reason"),
    "adjudication": ("rationale",),
    "gate_escalation_opened": ("stated_reason", "stated_detail"),
    "gate_escalation_decided": ("reason", "marker", "tool_name"),
    "gate_escalation_corroborated": ("argument",),
    "gate_escalation_refused": ("why",),
    "gate_escalation_claimed": ("stated_attempted_act", "reason"),
    "gate_escalation_withdrawn": ("assurance", "reason"),
    "member_notice": ("pointer_uri",),
    "scope_attestation": ("allows", "denies"),
    "scope_requested": ("requested_because", "path", "reason"),
    "scope_granted": ("requested_because", "path", "decision_reason"),
    "gate_self_read": ("data",),
    "gate_self_access": ("data",),
    "agent_inventory": ("data",),
    "operator_session_opened": ("evidence", "operator"),
    "policy_edit": ("change", "preset"),
}

# What a reader that knows only the common vocabulary would try.
NAIVE_KEYS = ("target", "attempted")


def _nonempty(ed, keys):
    """Numbers count. `scope_attestation.allows` is an INT (191), not a list -- an earlier
    version of this predicate accepted only str/list/dict and scored that family 0/39,
    which is the same instrument error as the naive key list, one type-check deeper."""
    for key in keys:
        v = ed.get(key)
        if isinstance(v, bool):
            return key
        if isinstance(v, (int, float)):
            return key
        if isinstance(v, str) and v.strip():
            return key
        if isinstance(v, (list, dict)) and len(v) > 0:
            return key
    return None


def act_text(entry, family_aware=True):
    """The reconstructable substance of the entry, if it carries one.

    `family_aware=False` reproduces the naive reader: it knows `target`/`attempted` only.
    """
    ed = entry.get("eventData") or {}
    keys = SUBSTANCE_KEYS.get(entry["eventType"], ()) if family_aware else NAIVE_KEYS
    hit = _nonempty(ed, keys)
    return hit, (ed.get(hit) if hit else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hops", type=int, default=5000, help="entries to walk below the window")
    args = ap.parse_args()

    d = Daemon()

    t0 = time.time()
    win = d.window(5000)  # deliberately over-ask, to measure the clamp
    win_secs = time.time() - t0
    entries = win["entries"]
    entries.sort(key=lambda e: e["chainPosition"])
    newest = entries[-1]["chainPosition"]

    print("== window ==")
    print(f"  requested limit 5000 -> served {len(entries)}  (cap {WINDOW_CAP})")
    print(f"  hasMore={win.get('hasMore')}  newest chainPosition={newest}")
    print(f"  one window call: {win_secs*1000:.0f} ms for {len(entries)} entries")

    # --- walk below the window via prevHash ---
    walked = list(entries)
    cursor = entries[0]["prevHash"]
    t0 = time.time()
    hops = 0
    while cursor and hops < args.hops:
        e = d.by_hash(cursor)
        if not e:
            break
        walked.append(e)
        cursor = e.get("prevHash")
        hops += 1
    walk_secs = time.time() - t0
    per = walk_secs / hops if hops else 0

    print("\n== cheap: is the chain enumerable by an ordinary member? ==")
    print(f"  walked {hops} entries below the window in {walk_secs:.2f}s = {per*1000:.2f} ms/entry")
    remaining = newest - len(entries)
    print(f"  entries below window: {remaining}")
    print(f"  extrapolated full walk: {remaining*per:.0f}s ({remaining*per/60:.1f} min), "
          f"{remaining} sequential calls")
    print("  NOTE: measured single-client at idle. One global lock serves all members, so")
    print("        per-entry latency rises with concurrency -- this is a FLOOR, not a promise.")

    # --- bluff: independent verification ---
    ok = bad = 0
    bad_examples = []
    by_pos = {e["chainPosition"]: e for e in walked}
    for e in walked:
        if rehash(e) == e["hash"]:
            ok += 1
        else:
            bad += 1
            if len(bad_examples) < 3:
                bad_examples.append(e["chainPosition"])
    link_ok = link_bad = 0
    for pos, e in by_pos.items():
        prev = by_pos.get(pos - 1)
        if prev is None:
            continue
        if e["prevHash"] == prev["hash"]:
            link_ok += 1
        else:
            link_bad += 1

    print("\n== bluff: what can an outside reader verify, holding no key? ==")
    print(f"  hash recomputed independently: {ok}/{ok+bad} match" + (f"  BAD at {bad_examples}" if bad else ""))
    print(f"  prevHash linkage over contiguous pairs: {link_ok}/{link_ok+link_bad}")
    signers = Counter(e.get("signerLct", "") for e in walked)
    print(f"  distinct signerLct across {len(walked)} entries: {len(signers)}")
    for s, n in signers.most_common(5):
        print(f"    {n:>6}  {s!r}")
    print("  signer_lct is NOT an input to compute_hash (storage/chain.rs:679-692):")
    print("  content and order are committed; AUTHORSHIP is not. Nothing signs.")

    # --- total: act reconstructability ---
    per_type = defaultdict(lambda: [0, 0, 0])  # [family_aware, naive, total]
    key_used = Counter()
    unmapped = Counter()
    for e in walked:
        et = e["eventType"]
        slot = per_type[et]
        slot[2] += 1
        k, _ = act_text(e, family_aware=True)
        if k:
            slot[0] += 1
            key_used[f"{et}.{k}"] += 1
        elif et not in SUBSTANCE_KEYS:
            unmapped[et] += 1
        if act_text(e, family_aware=False)[0]:
            slot[1] += 1

    print("\n== total: can the act be reconstructed from the entry? ==")
    print("  'naive' = a reader that knows only target/attempted (the common vocabulary).")
    print("  'aware' = a reader that knows all 19 per-family schemas.")
    print(f"  {'event type':<30} {'aware':>7} {'naive':>7} {'total':>7}  {'aware%':>7}")
    for t, (fa, nv, tot) in sorted(per_type.items(), key=lambda kv: -kv[1][2]):
        print(f"  {t:<30} {fa:>7} {nv:>7} {tot:>7}  {100*fa/tot:>6.1f}%")
    tfa = sum(v[0] for v in per_type.values())
    tnv = sum(v[1] for v in per_type.values())
    tt = sum(v[2] for v in per_type.values())
    print(f"  {'ALL':<30} {tfa:>7} {tnv:>7} {tt:>7}  {100*tfa/tt:>6.1f}%")
    print(f"\n  families the naive reader recovers at all: "
          f"{sum(1 for v in per_type.values() if v[1] > 0)}/{len(per_type)}")
    if unmapped:
        print(f"  UNMAPPED event types (this probe has no key for them): {dict(unmapped)}")
    print(f"  top carriers: {dict(key_used.most_common(6))}")


if __name__ == "__main__":
    main()
