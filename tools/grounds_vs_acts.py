#!/usr/bin/env python3
"""Diff a member's STATED grounds against their MEASURED conduct on the witness chain.

Why this exists:

Finding 7454 (peer-review-terminal-belief-20260829) caught three kimi-code review records
asserting that a factor cannot be filed on a terminal escalation — while the chain recorded
dozens of post-terminal factors filed by the same seat. The stated model and the measured
conduct diverged for weeks; nothing computed the diff. This tool computes it.

It is deliberately an EVIDENCE tool, not a verdict tool (hestia CLAUDE.md: inspectable
evidence, not prescribed trust). It prints:

  1. CONDUCT REGISTER — the seat's `gate_escalation_corroborated` events, each classified
     against its escalation's terminal event: pre-terminal, post-terminal (+dt), or
     no-terminal-in-window. From the chain, not from anyone's report of the chain.
  2. STATEMENT REGISTER — paragraphs in the seat's authored records (findings/review-*.md
     carrying the seat's byline, forum/<seat>/*.md) that conjoin three cue families:
     a factor-filing term, a terminality/pending-ness term, and an impossibility cue.
     These are CANDIDATES. A paragraph can conjoin all three while asserting the opposite
     (negation, quotation, refutation) — the tool flags for adjudication and prints the
     text so the reader adjudicates. Coverage is bounded by the cue lists, which are
     printed in full in the report header so a miss is auditable.
  3. DIVERGENCE — if the conduct register holds post-terminal factors AND the statement
     register holds candidates asserting terminality blocks filing, both sides are printed
     together. The reader decides what the diff means; the tool's job is that neither side
     stays invisible.

Chain walk: hops backward from head via `filter.hash` pointer lookups. A hop budget is NOT
a date (the left edge drifts as the chain grows) — the walked span is printed so runs can
be compared. The terminating genesis sentinel is the all-zeros prevHash; a walk that ends
on any other error is INCOMPLETE and says so (KINDS.md: assert the sentinel, or an error
at position N silently under-counts by N).

The walk dump is seat-independent: one `--cache-out` serves every seat (`--cache-in`
re-analyzes without re-walking). Read-only against the daemon; never writes to the repo.

Usage:
  grounds_vs_acts.py --seat kimi-code --cache-out /tmp/walk.json      # walk + report
  grounds_vs_acts.py --seat claude-code --cache-in /tmp/walk.json     # report only

Exit 1 if a divergence surface is non-empty (both registers non-empty) — a review signal
summoning adjudication, never a verdict (real false positives are a documented class).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ESC_EVENTS = {
    "gate_escalation_opened",
    "gate_escalation_decided",
    "gate_escalation_expired",
    "gate_escalation_withdrawn",
    "gate_escalation_corroborated",
    "gate_escalation_claimed",
}
TERMINAL_EVENTS = {"gate_escalation_decided", "gate_escalation_expired", "gate_escalation_withdrawn"}
GENESIS_SENTINEL = "0" * 64

# The three cue families. A candidate statement conjoins one term from each.
# Coverage-bounded ON PURPOSE: a claim phrased outside this vocabulary is a miss,
# and the lists are printed in the report so the miss class is auditable.
CUE_FACTOR = re.compile(r"corroborat|factor", re.I)
CUE_TERMINALITY = re.compile(
    r"pending|terminal|already decided|decided row|structurally unavailable|no longer reviewable",
    re.I,
)
CUE_IMPOSSIBILITY = re.compile(
    r"\bonly\b|cannot|can't|could not|couldn't|\bno \w|\bnone\b|\bnothing\b|never|unavailable|refused|"
    r"shut|closed|impossible|not possible|frozen|froze|not reviewable",
    re.I,
)

# Authorship attribution: a findings file belongs to the seat named in its byline.
AUTHOR_PATTERNS = [
    re.compile(r"\*\*Reviewer:\*\*\s*`?([\w-]+)`?"),
    re.compile(r"\bby\s+`([\w-]+)`"),
    re.compile(r"\*\*Seat:\*\*\s*`?([\w-]+)`?"),
]


def ts(entry: dict) -> float:
    return datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()


class Daemon:
    """Minimal MCP-over-HTTP client (stdlib only). One session per Daemon."""

    def __init__(self, endpoint: str, plugin_id: str):
        self.endpoint = endpoint
        self.plugin_id = plugin_id
        self.session_id = None
        self._handshake()

    def _post(self, payload: dict, headers: dict | None = None):
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **(headers or {})},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode(), r.headers.get("mcp-session-id")

    @staticmethod
    def _unwrap(body: str):
        for line in body.splitlines():
            if line.startswith("data: {"):
                obj = json.loads(line[6:])
                if "error" in obj:
                    return {"_rpc_error": obj["error"]}
                res = obj.get("result") or {}
                content = res.get("content")
                if content and content[0].get("text"):
                    try:
                        return json.loads(content[0]["text"])
                    except ValueError:
                        return {"_text": content[0]["text"]}
                return res
        return {"_raw": body[:500]}

    def _handshake(self):
        _, msid = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                         "clientInfo": {"name": self.plugin_id, "version": "1"}}})
        h = {"mcp-session-id": msid} if msid else {}
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
        conn = self._unwrap(self._post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "hestia_connect",
                        "arguments": {"plugin_id": self.plugin_id,
                                      "host_agent": f"{self.plugin_id}-cli"}}}, h)[0])
        self.session_id = conn.get("sessionId") or conn.get("session_id")
        if not self.session_id:
            raise SystemExit(f"hestia_connect failed: {json.dumps(conn)[:300]}")
        self._headers = h

    def history(self, flt: dict) -> dict:
        for attempt in range(6):
            try:
                return self._unwrap(self._post(
                    {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                     "params": {"name": "hestia_query_history",
                                "arguments": {"session_id": self.session_id, "filter": flt}}},
                    self._headers)[0])
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(5 * (attempt + 1))
                self._handshake()
        raise AssertionError("unreachable")


def walk_chain(daemon: Daemon, max_hops: int | None, progress=sys.stderr) -> dict:
    """Walk head -> genesis (or hop budget), collecting escalation events.

    Returns a dump dict. `complete` is True ONLY if the walk terminated on the
    all-zeros genesis sentinel — anything else is a bounded window and says so.
    """
    head = daemon.history({"limit": 2})
    entries = head.get("entries") or []
    if not entries:
        raise SystemExit(f"history head unreadable: {json.dumps(head)[:300]}")
    cur = entries[0]
    found = []
    walked = 0
    complete = False
    t0 = time.time()
    while True:
        if cur.get("eventType") in ESC_EVENTS:
            found.append(cur)
        prev = cur.get("prevHash", "")
        if prev == GENESIS_SENTINEL:
            complete = True
            break
        if max_hops is not None and walked >= max_hops:
            break
        nxt = daemon.history({"hash": prev})
        nxt_entry = nxt.get("entry")
        if not nxt_entry:
            print(f"walk aborted by error (NOT genesis): {json.dumps(nxt)[:200]}",
                  file=progress)
            break
        cur = nxt_entry
        walked += 1
        if walked % 25000 == 0:
            print(f"...{walked} hops, {len(found)} events, "
                  f"{time.time() - t0:.0f}s", file=progress, flush=True)
    return {
        "complete": complete,
        "walked_hops": walked,
        "span": [cur.get("timestamp"), entries[0].get("timestamp")],
        "head_position": entries[0].get("chainPosition"),
        "events": found,
    }


def conduct_register(dump: dict, seat: str) -> dict:
    """Classify the seat's corroboration factors against terminality."""
    terminal: dict[str, dict] = {}
    factors = []
    unattributable = []
    for e in dump["events"]:
        d = e.get("eventData") or {}
        eid = d.get("escalation_id")
        if not eid:
            continue
        if e["eventType"] in TERMINAL_EVENTS:
            # The FINAL terminal state, by timestamp — never by walk order. A dump is
            # newest-first from walk_chain but oldest-first from some caches, and an
            # order-dependent "last write wins" classifies duplicate-terminal records
            # backwards in one of them (codex review of #809, hold item 1).
            if eid not in terminal or ts(e) > ts(terminal[eid]):
                terminal[eid] = e
        elif e["eventType"] == "gate_escalation_corroborated":
            # THE FILER, not the owner (#811): on a corroborated event `plugin_id` names the
            # PETITION OWNER; `corroborated_by` names who filed the factor. The two agree on
            # 0 of 295 events in the full-chain dump, so owner-keying reported "peers'
            # factors on my petitions" as the seat's own conduct. No plugin_id fallback on
            # purpose -- falling back would silently reintroduce the wrong population when
            # the field is absent; an event with no corroborated_by is counted and named.
            if d.get("corroborated_by") == seat:
                factors.append(e)
            elif "corroborated_by" not in d:
                unattributable.append(e)
    pre, post, no_terminal = [], [], []
    for e in factors:
        d = e["eventData"]
        t = terminal.get(d["escalation_id"])
        row = {
            "escalation_id": d["escalation_id"],
            "at": e["timestamp"],
            "stance": d.get("stance"),
        }
        if t is None:
            no_terminal.append(row)
        else:
            dt = ts(e) - ts(t)
            row["terminal_at"] = t["timestamp"]
            row["dt_after_terminal_s"] = round(dt, 1)
            (pre if dt <= 0 else post).append(row)
    return {"seat": seat, "factors": len(factors), "pre": pre,
            "post": post, "no_terminal_in_window": no_terminal,
            "unattributable": len(unattributable)}


def authored_files(repo: Path, seat: str) -> list[Path]:
    """The seat's authored corpus: findings/review-*.md by byline, forum/<seat>/*.md."""
    out = []
    findings = repo / "findings"
    if findings.is_dir():
        for p in sorted(findings.glob("review-*.md")):
            try:
                head_text = p.read_text(errors="replace")[:1500]
            except OSError:
                continue
            if any(m.search(head_text) and m.search(head_text).group(1) == seat
                   for m in AUTHOR_PATTERNS):
                out.append(p)
    forum = repo / "forum" / seat
    if forum.is_dir():
        out.extend(sorted(forum.glob("*.md")))
    return out


def statement_register(files: list[Path]) -> list[dict]:
    """Paragraphs conjoining all three cue families. Candidates, not verdicts."""
    hits = []
    for p in files:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        start = 0
        para: list[str] = []
        for i, line in enumerate(lines + [""]):
            if line.strip():
                if not para:
                    start = i
                para.append(line)
            elif para:
                blob = " ".join(x.strip() for x in para)
                fm = CUE_FACTOR.search(blob)
                tm = CUE_TERMINALITY.search(blob)
                im = CUE_IMPOSSIBILITY.search(blob)
                if fm and tm and im:
                    # Store the FULL paragraph and the matched cue terms: truncating the
                    # text can cut off the cue, negation, or correction the adjudicator
                    # needs (codex review of #809, hold item 2).
                    hits.append({"file": str(p), "line": start + 1, "text": blob,
                                 "cues": {"factor": fm.group(0), "terminality": tm.group(0),
                                          "impossibility": im.group(0)}})
                para = []
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seat", required=True)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--as", dest="as_", default=None,
                    help="connecting plugin_id (default: the seat itself)")
    ap.add_argument("--endpoint", default="http://127.0.0.1:7711/mcp")
    ap.add_argument("--max-hops", type=int, default=None)
    ap.add_argument("--cache-in")
    ap.add_argument("--cache-out")
    args = ap.parse_args()

    if args.cache_in:
        dump = json.loads(Path(args.cache_in).read_text())
    else:
        daemon = Daemon(args.endpoint, args.as_ or args.seat)
        dump = walk_chain(daemon, args.max_hops)
        if args.cache_out:
            Path(args.cache_out).write_text(json.dumps(dump))

    span = dump.get("span") or ["?", "?"]
    print(f"# grounds vs acts — seat: {args.seat}")
    print(f"# corpus root: {Path(args.repo).resolve()}")  # codex review: results must name their corpus, not float ambient
    print(f"# walk: {dump.get('walked_hops')} hops, complete={dump.get('complete')}, "
          f"head_position={dump.get('head_position')}, span {span[0]} .. {span[1]}")
    print("# cue families (coverage bound — a claim outside this vocabulary is a miss):")
    print(f"#   factor:       {CUE_FACTOR.pattern}")
    print(f"#   terminality:  {CUE_TERMINALITY.pattern}")
    print(f"#   impossibility:{CUE_IMPOSSIBILITY.pattern}")

    conduct = conduct_register(dump, args.seat)
    post = conduct["post"]
    if conduct.get("unattributable"):
        print(f"\n## NOTE: {conduct['unattributable']} corroborated event(s) carry no "
              f"corroborated_by and are counted for no seat")
    print(f"\n## conduct register: {conduct['factors']} factors — "
          f"{len(conduct['pre'])} pre-terminal, {len(post)} post-terminal, "
          f"{len(conduct['no_terminal_in_window'])} no-terminal-in-window")
    for row in post[:10]:
        print(f"  POST-TERMINAL esc={row['escalation_id'][:12]} "
              f"at={row['at']} (+{row['dt_after_terminal_s']}s) stance={row['stance']}")
    if len(post) > 10:
        print(f"  ... and {len(post) - 10} more")

    files = authored_files(Path(args.repo), args.seat)
    hits = statement_register(files)
    print(f"\n## statement register: {len(files)} authored records, "
          f"{len(hits)} candidate statements")
    for hit in hits:
        c = hit["cues"]
        print(f"  {hit['file']}:{hit['line']}: [{c['factor']} | {c['terminality']} | "
              f"{c['impossibility']}] {hit['text'][:400]}")

    # A review signal, NOT a verdict: both registers non-empty means the reader must
    # adjudicate, and real false positives (quotation, refutation, the correction
    # itself) prove the inference "candidates imply contradiction" is invalid.
    divergent = bool(post) and bool(hits)
    print(f"\n## divergence surface: {'PRESENT — adjudication required (exit 1 is a review signal, not a verdict)' if divergent else 'none detected within coverage bounds'}")
    return 1 if divergent else 0


if __name__ == "__main__":
    sys.exit(main())
