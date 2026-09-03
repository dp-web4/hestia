#!/usr/bin/env python3
"""Block until an escalation reaches a TERMINAL state, then exit with what happened.

WHY THIS SHAPE. dp, 2026-08-27: "the escalation instructions should include the suggestion
that the asker set a monitor to wait on disposition. most harnesses have that function."

They do, and the harness guidance is specific about which one. For a SINGLE notification --
"tell me when my escalation is decided" -- the correct primitive is a backgrounded command
that EXITS when the condition is true, not a streaming monitor. A streaming monitor is for
one-event-per-occurrence; an escalation resolves once. So this is written to be dropped into:

    Bash(command="python3 tools/await_escalation.py <id> --session <sid>",
         run_in_background=True)

and it produces exactly one completion notification, carrying the outcome in its exit code.

SILENCE IS NOT SUCCESS, which is the trap this file exists to avoid. The obvious watcher --
poll until `approved` -- stays silent through a denial, an expiry, a reaped id and a dead
daemon, and silence is indistinguishable from "still waiting". Every terminal state gets its
own exit code here, and any state this program cannot classify is an ERROR rather than a
patient wait. Measured on CBP 2026-08-27: five approvals across two seats died unclaimed, and
the only delivery channel that worked was the operator saying "approved" out loud.

WHY NOT `hestia gate poll` IN A LOOP. Because it does not work: measured 2026-08-27, it times
out at its 15s client deadline against a daemon answering the same query in ~500ms over a
fresh connection. Its `reqwest` client pools connections and the reused one carries an SSE
stream that never closes, so the tool call after `initialize` reads to a EOF that never comes.
Filed separately. Until that is fixed there is no working shell primitive for "is my
escalation decided", which is a large part of why no member has ever built this watcher.

EXIT CODES, chosen so a caller can branch without parsing anything:
   0  approved AND still claimable  -- re-issue the act NOW, the window is open
   3  approved but the claim window has already closed -- the grant is dead, re-escalate
   4  denied
   5  expired / unknown id (the daemon reports these identically by design)
   2  could not determine: daemon unreachable, malformed answer, or an unclassifiable state
   1  usage error

FAIL-CLOSED IS NOT A LICENCE TO NARRATE. Exit 5 stays a deny, and it is right that it does:
`status_of` answers `expired` for an id it holds no row for, so a dropped store can never
leave a caller waiting on a permission it will not get. What this program used to do on top
of that was print "no decision landed in the window" -- an assertion about HISTORY, which the
daemon never made and cannot support. `reap()` deletes DECIDED rows on the same clock as
lapsed ones (`expires_at + 3600`, run inside every `open()`), so an hour past TTL an approved,
claimed, fully-spent grant reads exactly like a petition nobody ruled. Measured 2026-09-02 by
kimi-code across mesh notices 9313-9391: seven decided escalations -- five approved-and-
claimed, two approved-and-lapsed -- all rendered here as "no decision landed". Seven of seven.

The payload does carry a discriminator, and it is not the status: `bar` is `null` exactly when
the daemon holds NO ROW (reaped, or never existed) and non-null when a real pending row lapsed
undecided. So the two cases are now told apart and only the second one gets the sentence that
is true of it. This is hestia#544's shape in a third consumer -- that issue carved the poll
out as "deliberate and right", which holds for the VERDICT and not for the prose beside it.
The deciding tools' half of #544 (a chain fallback for arbitrate/corroborate) is still open.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"approved", "denied", "expired", "unknown"}


class Mcp:
    """One connection per request, deliberately.

    `hestia gate poll` pools connections and hangs on the reused one's SSE stream. urllib
    opens a fresh connection per call, which is why this works where that does not. The
    inefficiency is the point: a watcher that polls every 15s does not need keep-alive, and
    correctness beats a saved handshake.
    """

    def __init__(self, endpoint: str):
        self.url = endpoint.rstrip("/")
        if not self.url.endswith("/mcp"):
            self.url += "/mcp"
        self.session = None
        self.n = 0

    def call(self, method, params=None, timeout=20):
        self.n += 1
        body = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not self.session:
                self.session = r.headers.get("Mcp-Session-Id")
            raw = r.read().decode("utf-8", "replace")
        out = None
        for line in raw.splitlines():
            # The stream opens with an EMPTY `data:` line; take the first non-empty frame.
            if line.startswith("data: ") and line[6:].strip().startswith("{"):
                out = json.loads(line[6:])
        if out is None:
            raise RuntimeError("no JSON frame in daemon response")
        if "error" in out:
            raise RuntimeError(f"daemon refused {method}: {out['error']}")
        return out

    def tool(self, name, args):
        r = self.call("tools/call", {"name": name, "arguments": args})
        text = r["result"]["content"][0]["text"]
        d = json.loads(text)
        if "_hestia_error" in d:
            # A refusal shaped like a success. Never let it read as an answer.
            raise RuntimeError(d["_hestia_error"].get("message", "tool error"))
        return d


def classify_terminal(escalation_id: str, d: dict) -> tuple[int, str, bool]:
    """Turn one terminal poll payload into (exit code, message, print-to-stderr).

    PULLED OUT OF `main` SO THE SENTENCES CAN BE TESTED. The defect this file most recently
    carried was not a wrong exit code -- exit 5 was right every time -- it was a wrong
    SENTENCE printed beside a right code, and nothing could reach it without a live daemon and
    a reaped id. A pure function over the payload is testable from a dict; see
    `await_escalation_test.py`.
    """
    status = str(d.get("status", "")).lower()
    left = d.get("claim_window_secs_remaining")

    if status == "approved":
        # BOTH conjuncts, because the daemon owns both and a member that re-derives
        # them gets a different answer than the claim path will.
        if d.get("permits_write") is True and isinstance(left, (int, float)) and left > 0:
            return (0, f"{escalation_id}: APPROVED — claimable for {int(left)}s. "
                       f"Re-issue the act VERBATIM now.", False)
        # `consumed_at` is THE discriminator between the two ways a grant stops being
        # claimable, and the daemon publishes it precisely so a reader does not have to
        # substring-match prose. Spent and lapsed are different facts about the same code.
        spent = d.get("consumed_at")
        why = (f"already CLAIMED at {spent} — it was spent, not lost" if spent
               else "the window LAPSED unspent")
        return (3, f"{escalation_id}: approved but NOT claimable ({why}; "
                   f"permits_write={d.get('permits_write')}, window={left}). "
                   f"The grant is dead; re-escalate rather than retrying.", True)

    if status == "denied":
        return (4, f"{escalation_id}: DENIED. {d.get('reason') or ''}".rstrip(), False)

    # `bar` is the row's own field, so `None` means the daemon holds NO ROW at all — reaped
    # or never-existed, which is not the same fact as "nobody ruled it". Only a row that is
    # still present can honestly be reported as having gone undecided.
    if d.get("bar") is None:
        return (5, f"{escalation_id}: {status} — this daemon holds NO ROW for that id. It was "
                   f"either reaped (decided rows are deleted on the same clock as lapsed ones, "
                   f"~1h past TTL) or never existed. Whether anyone ruled it is NOT knowable "
                   f"from here — read the chain (`gate_escalation_decided` / "
                   f"`gate_escalation_opened` entries naming the id).", True)

    return (5, f"{escalation_id}: {status} — the row is still present and undecided, so no "
               f"decision landed in the window.", True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("escalation_id")
    ap.add_argument("--session", help="your session_id from hestia_connect. Passing it means "
                                      "the first detection COUNTS AS YOUR OBSERVATION and "
                                      "starts the claim window from that moment; without it "
                                      "the window still runs from the ruling.")
    ap.add_argument("--endpoint", default="http://127.0.0.1:7711")
    ap.add_argument("--interval", type=float, default=15.0, help="seconds between polls")
    ap.add_argument("--max-wait", type=float, default=4200.0,
                    help="give up after this long. Defaults past the record TTL + claim "
                         "window, so a run that hits it means something is wrong, not that "
                         "the wait was too short.")
    args = ap.parse_args()

    m = Mcp(args.endpoint)
    deadline = None
    consecutive_errors = 0
    started = None

    while True:
        try:
            m.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "await-escalation", "version": "1"}})
            poll_args = {"escalation_id": args.escalation_id}
            if args.session:
                poll_args["session_id"] = args.session
            d = m.tool("hestia_gate_escalation_poll", poll_args)
            consecutive_errors = 0
        except Exception as e:  # noqa: BLE001
            consecutive_errors += 1
            # A transient failure must not end the watch, but a persistent one must not be
            # mistaken for patience either: a daemon that is down looks exactly like an
            # escalation nobody has ruled.
            if consecutive_errors >= 5:
                print(f"cannot determine: {consecutive_errors} consecutive failures, last: {e}",
                      file=sys.stderr)
                return 2
            time.sleep(min(args.interval, 10.0))
            continue

        if started is None:
            started = time.monotonic()
            deadline = started + args.max_wait

        status = str(d.get("status", "")).lower()
        if d.get("observation_started_claim_window"):
            print(f"{args.escalation_id}: observed — the claim window now runs from this moment")

        if status in TERMINAL:
            code, message, to_stderr = classify_terminal(args.escalation_id, d)
            print(message, file=sys.stderr if to_stderr else sys.stdout)
            return code

        if deadline is not None and time.monotonic() > deadline:
            print(f"{args.escalation_id}: still '{status}' after {args.max_wait:.0f}s — "
                  f"giving up. This is a stuck process, not a slow decision.", file=sys.stderr)
            return 2

        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
