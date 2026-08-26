#!/usr/bin/env python3
"""One correct reader for the hestia witness chain, so nobody hand-rolls it a fifth time.

WHY THIS EXISTS. `hestia_query_history` has four independent traps, and between
2026-07-31 and 2026-08-05 members fell into them on four separate occasions, each time
publishing a number before noticing. Every trap fails the same way: it returns a
plausible, well-formed, WRONG answer rather than an error.

  1. `filter` accepts EXACTLY three keys — `limit`, `tool_name`, `hash`. There is no
     `event_type` and no `plugin_id` filter. The tool schema is `additionalProperties:
     true` with zero declared properties, so an unknown key nested inside `filter` is
     accepted and SILENTLY IGNORED: `{"filter":{"event_type":"appeal"}}` returns
     undifferentiated `outcome` rows, which reads exactly like "no appeal events exist."
     (The asymmetry that allowed this — a `limit` at the TOP level refused loudly, an
     unknown key INSIDE `filter` dropped in silence — is closed as of #648: the daemon
     now answers `hestia.query_filter_unknown_key`. That is a SERVER fix, and a server
     fix binds only once the daemon is rebuilt AND restarted, so the client-side refusal
     in `window()` below stays: it is what protects a member talking to a daemon that
     has not been cycled yet, which on this fleet is the common case.)
  2. The window path answers under `entries` (plural). The `filter.hash` cursor answers
     under **`entry` (SINGULAR)**. A walker keyed on `entries` gets an empty list out of
     a SUCCESSFUL lookup and concludes the cursor is dead. That mistake was published to
     KINDS.md, a PR body, a forum post and a mesh notice inside 20 minutes on 2026-08-03.
  3. The per-entry payload key is **`eventData` (camelCase)** — not `data`, not
     `event_data`. A reader keyed on the snake_case spellings gets `None` for every
     field and reads it as "the chain does not record plugin_id."
     AND: `gate_self_read` / `gate_self_access` rows nest their fields under `data`
     INSIDE `eventData`, behind a `requested_by` envelope, while every other event type
     is flat. So the two event types specifically about the gate are exactly the ones a
     flat reader silently drops. `payload()` below normalises both shapes.
  4. Running off the genesis end terminates with an `_hestia_error` ENVELOPE, not an
     empty result. A walker that does not test for it stops early and silently
     under-counts. Note `_hestia_error` rides the SUCCESS path — `isError` is false.

The 500 cap is NOT a wall: `filter.hash` is a pointer lookup that deliberately
short-circuits the window, and every entry carries `prevHash`. Chain them and you walk
the whole chain — measured on CBP at ~1.0 ms/hop, 89,974 entries in 96 s.

Usage:
    from chain_walk import ChainWalker
    w = ChainWalker()
    for e in w.walk(max_entries=5000):        # newest -> oldest, across the 500 cap
        if e["eventType"] == "gate_escalation_opened":
            print(payload(e).get("plugin_id"))

    w.window(limit=500)                        # single window, correctly nested
    w.census(("gate_escalation_opened",), key="plugin_id", max_entries=20000)

CLI:
    python3 chain_walk.py --census plugin_id --types gate_escalation_opened --max 20000
"""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from typing import Any, Dict, Iterator, Optional, Sequence

DEFAULT_ENDPOINT = "http://127.0.0.1:7711/mcp"
MAX_WINDOW = 500  # handler clamps with .min(500)

# The only keys `filter` understands. Anything else is silently ignored, so we refuse
# it here rather than let the daemon serve a confidently wrong answer (trap 1).
_ALLOWED_FILTER_KEYS = frozenset({"limit", "tool_name", "hash"})


class ChainError(RuntimeError):
    """An `_hestia_error` envelope, surfaced as an exception instead of an empty result."""

    def __init__(self, code: str, message: str, data: Any = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The event body, normalised across BOTH shapes on this feed (trap 3).

    Flat:   entry["eventData"] = {...fields...}
    Nested: entry["eventData"] = {"data": {...fields...}, "requested_by": {...}}
            (gate_self_read / gate_self_access only)
    """
    d = entry.get("eventData")
    if not isinstance(d, dict):
        return {}
    inner = d.get("data")
    if isinstance(inner, dict):
        # Keep the envelope's own keys reachable, but let the inner fields win.
        merged = {k: v for k, v in d.items() if k != "data"}
        merged.update(inner)
        return merged
    return d


class ChainWalker:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 30.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self._sid: Optional[str] = None
        self._connect()

    # -- transport -------------------------------------------------------------
    def _post(self, payload_obj: Dict[str, Any], timeout: Optional[float] = None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._sid:
            headers["mcp-session-id"] = self._sid
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload_obj).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return r.read().decode("utf-8", "replace"), r.headers.get("mcp-session-id")

    def _connect(self) -> None:
        """`initialize` FIRST or every subsequent call 422s."""
        _, sid = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "chain-walk", "version": "1"},
                },
            }
        )
        self._sid = sid
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    @staticmethod
    def _parse_sse(raw: str) -> Iterator[Dict[str, Any]]:
        for line in raw.splitlines():
            if line.startswith("data: "):
                try:
                    yield json.loads(line[6:])
                except ValueError:
                    continue
            elif line.strip().startswith("{"):
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def _call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raw, _ = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        for msg in self._parse_sse(raw):
            result = msg.get("result")
            if result is None:
                continue
            try:
                body = json.loads(result["content"][0]["text"])
            except (KeyError, IndexError, ValueError) as exc:
                raise ChainError("chain_walk.unparseable", str(exc), result)
            # Trap 4 — errors ride the SUCCESS path; isError is false.
            if isinstance(body, dict) and "_hestia_error" in body:
                err = body["_hestia_error"]
                raise ChainError(
                    err.get("code", "unknown"), err.get("message", ""), err.get("data")
                )
            return body
        raise ChainError("chain_walk.no_result", "no result frame in response", raw[:500])

    # -- queries ---------------------------------------------------------------
    def window(self, limit: int = MAX_WINDOW, **filter_kwargs) -> Dict[str, Any]:
        """One window, newest-first. Returns the raw body (`entries`, `hasMore`, `limit`).

        NOTE `hasMore` is COMPUTED, not hard-coded — assert on that flag, never on
        len(entries), which equals `limit` both when the chain has more and when it
        happens to end exactly there.
        """
        bad = set(filter_kwargs) - _ALLOWED_FILTER_KEYS
        if bad:
            raise ValueError(
                f"filter keys {sorted(bad)} do not exist and would be SILENTLY IGNORED "
                f"(serving an unfiltered tail that looks like a filtered answer). "
                f"Only {sorted(_ALLOWED_FILTER_KEYS)} are real. Filter client-side instead."
            )
        f: Dict[str, Any] = {"limit": min(limit, MAX_WINDOW)}
        f.update(filter_kwargs)
        return self._call("hestia_query_history", {"filter": f})

    def entry_by_hash(self, hash_: str) -> Optional[Dict[str, Any]]:
        """The cursor. Answers under `entry` (SINGULAR) — trap 2."""
        body = self._call("hestia_query_history", {"filter": {"hash": hash_}})
        entry = body.get("entry")
        if entry is None and "entries" in body:
            # Defensive: if the daemon ever unifies the shapes, don't silently return None.
            ents = body.get("entries") or []
            entry = ents[0] if ents else None
        return entry

    def walk(self, max_entries: int = 10_000, start_hash: Optional[str] = None
             ) -> Iterator[Dict[str, Any]]:
        """Newest -> oldest across the whole chain, past the 500 cap, via prevHash.

        Terminates on: max_entries, a missing/absent prevHash, or the genesis
        `_hestia_error` envelope (trap 4) — never silently early.
        """
        seen = 0
        if start_hash is None:
            body = self.window(limit=MAX_WINDOW)
            for e in body.get("entries", []):
                if seen >= max_entries:
                    return
                yield e
                seen += 1
                cursor = e.get("prevHash")
        else:
            cursor = start_hash

        while seen < max_entries and cursor:
            try:
                e = self.entry_by_hash(cursor)
            except ChainError:
                return  # genesis end, reported as an error envelope
            if e is None:
                return
            yield e
            seen += 1
            cursor = e.get("prevHash")

    def census(self, event_types: Optional[Sequence[str]] = None, key: str = "plugin_id",
               max_entries: int = 10_000) -> Dict[str, Any]:
        """Client-side census — the ONLY correct way, since event_type is not a filter key.

        Reports the span actually covered so a caller cannot quote a rate without its
        denominator.
        """
        want = frozenset(event_types) if event_types else None
        counts: Counter = Counter()
        types: Counter = Counter()
        matched = 0
        scanned = 0
        first = last = None
        for e in self.walk(max_entries=max_entries):
            scanned += 1
            ts = e.get("timestamp")
            if first is None:
                first = ts
            last = ts
            et = e.get("eventType")
            types[et] += 1
            if want is not None and et not in want:
                continue
            matched += 1
            counts[payload(e).get(key, "<none>")] += 1
        return {
            "scanned": scanned,
            "matched": matched,
            "counts": dict(counts),
            "event_types": dict(types),
            "newest_timestamp": first,
            "oldest_timestamp": last,
            "truncated_at_max_entries": scanned >= max_entries,
        }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--census", metavar="FIELD", default="plugin_id")
    p.add_argument("--types", nargs="*", default=None,
                   help="event types to count (client-side; there is no server filter)")
    p.add_argument("--max", type=int, default=5000)
    args = p.parse_args()

    w = ChainWalker(endpoint=args.endpoint)
    out = w.census(args.types, key=args.census, max_entries=args.max)
    print(json.dumps(out, indent=2, sort_keys=True))
    if out["truncated_at_max_entries"]:
        print("\nWARNING: stopped at --max; this is a WINDOW, not the population.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
