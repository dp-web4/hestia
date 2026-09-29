#!/usr/bin/env python3
"""Driver for the #732 correction: WHICH read of an escalation pointer starts the fuse?

Publishes the driver, not just the number. The finding
(`findings/observed-fuse-is-seat-scoped-20260831.md`, Correction section) claims
that `resources/read` on `hestia://escalation/<id>` is free and that
`hestia_gate_escalation_poll` is the sole trigger of the 600s claim window. This
is the script that measured it, so the claim is re-runnable by someone other than
its author.

Design
------
leg 1 (FREE, default): dereference the pointer N times through `resources/read`,
       including with the `#decided` fragment a disposition notice actually
       carries. Asserted non-observing.
leg 2 (DESTRUCTIVE, --burn): open an attributed session and poll. If leg 1
       observed, this answers `observation_started_claim_window: false` with a
       partial window. If leg 1 did not, it answers `true` with a full 600 -- and
       the poll itself is what started it.

Leg 2 is the whole experiment and it consumes the thing it measures. There is no
non-destructive version: the only way to learn whether a fuse is lit is to light
it.

THE SPECIMEN RULE IS CHECKED, NOT ASSERTED
------------------------------------------
The first cut of this script stated the rule in prose and then hard-coded
`plugin_id: "claude-code"` in the connect. codex's review of #735 named both ways
that fails, and it was right on both:

  1. MISREPORT. Another seat running leg 2 against its OWN dead petition would
     still poll as `claude-code`. `mark_observed` requires `e.plugin_id ==
     plugin_id`, so it would refuse, the poll would answer
     `observation_started_claim_window: false`, and this script would print
     "fuse was ALREADY lit" -- a wrong conclusion from a correct daemon.
  2. ATTACK. Any caller could point the driver at a LIVE `claude-code`
     escalation and start that seat's clock. That is precisely the
     one-handshake attack the finding documents, packaged as a convenience.

So identity and ownership are now PRECONDITIONS the script checks before it
issues a poll, from data leg 1 already read for free:

  * the running seat is `HESTIA_MESH_PLUGIN` -- the same source `hestia-mesh.py`
    requires and refuses to default. NOT argv, because an argument is just the
    hard-coded string with extra steps.
  * the escalation row's `plugin_id` must EQUAL that seat. A phantom seat from a
    mistyped env var fails here too, because a phantom owns no rows.
  * the row must be `approved` with a `decided_at`. A pending petition is one
    somebody still wants; there is no fuse to find on it.
  * if the pointer resolved through the witness-chain fallback (no `plugin_id`
    in the body), ownership is UNVERIFIABLE and leg 2 refuses. That arm is
    untested for this measurement either way.

What this does NOT do: close the daemon-side hole. `mark_observed`'s seat check
still cannot tell an asker from a co-seat bystander, and asserting a `plugin_id`
to `hestia_connect` remains unauthenticated -- that is the open ruling question
in #732, and no client-side check can stand in for it. These preconditions stop
this DRIVER from being the affordance; they do not stop hand-rolled JSON-RPC.

The 2026-08-31 run used `4b1c5dcd6c8ce23c`: this seat's own petition from a shell
`for` loop that tripped the out-of-grammar rule, whose act had already been done
via unrolled reads. Do NOT point leg 2 at a peer's live grant. That is the exact
cross-seat leg #732 deliberately declines to run, and running it would spend
someone else's approval to prove a point they did not agree to pay for.

Reading the result
------------------
A `false`/`0` on the FIRST poll does not mean the fuse was already lit. It also
means the caller was never attributed -- `hestia_connect` requires `host_agent`
and returns `sessionId` (camelCase), and getting either wrong yields an unproven
poll that looks identical to a spent window. The probe checks for this and says
so rather than reporting a spurious result; it is the error that made the first
2026-08-31 run inconclusive.

Usage
-----
    python3 -I tools/fuse_trigger_probe.py <escalation_id>            # leg 1 only
    HESTIA_MESH_PLUGIN=<your seat> \\
      python3 -I tools/fuse_trigger_probe.py <escalation_id> --burn   # both legs

Run under `python3 -I` if cwd may be /tmp: stray modules there shadow the stdlib
and this imports `urllib.request`.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"
SETTLE_SECS = 17

# No environment override for the endpoint: the obvious spelling of that lookup
# trips the seat gate's `egress.secret` substring rule, and the endpoint file is
# the real source on every seat. The identity lookup below is a different rule
# and a different variable, and it is the one hestia-mesh.py already mandates.


class Client:
    def __init__(self, url, timeout=25.0):
        self.url, self.timeout, self.session, self._id = url, timeout, None, 0

    def post(self, method, params=None):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, "id": self._id}
        if params is not None:
            body["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            raw = resp.read().decode()
        if not raw.strip():
            return {}
        if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
            payloads = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
            raw = payloads[-1] if payloads else "{}"
        return json.loads(raw)


def unwrap(resp):
    try:
        return json.loads(resp["result"]["content"][0]["text"])
    except Exception:
        return resp


def endpoint():
    if ENDPOINT_FILE.exists():
        return ENDPOINT_FILE.read_text().strip()
    return "http://127.0.0.1:7711/mcp"


def running_seat():
    """This process's member id, from the source the mesh CLI already mandates.

    Deliberately NOT an argument. The bug being fixed is a hard-coded seat name;
    accepting one on argv reintroduces it with a nicer spelling, because the
    attack and the misreport both start with a caller naming a seat it is not.
    """
    return os.environ.get("HESTIA_MESH_PLUGIN", "").strip()


def burn_preconditions(seat, esc, body):
    """Return a refusal string, or None if leg 2 may proceed.

    Every conjunct is decided from data leg 1 already fetched for free, so a
    refusal costs nothing and never touches the record it declines to burn.
    """
    if not seat:
        return (
            "HESTIA_MESH_PLUGIN is unset, so this process cannot say which member it is.\n"
            "  Leg 2 moves a claim deadline and the daemon records WHOSE. Refusing rather\n"
            "  than guessing -- a guess here is how a driver becomes someone else's clock.\n"
            "  Set it to your own member id, the same value hestia-mesh.py requires."
        )
    owner = body.get("plugin_id")
    if not owner:
        return (
            f"the pointer for {esc} resolved without a `plugin_id`, which means the witness-\n"
            "  chain fallback answered rather than the live store. Ownership is UNVERIFIABLE\n"
            "  from that body, so leg 2 refuses. (That arm is also untested for this\n"
            "  measurement -- see the finding's limits.)"
        )
    if owner != seat:
        return (
            f"escalation {esc} belongs to '{owner}', and this process is '{seat}'.\n"
            "  Two things go wrong if leg 2 runs anyway, and codex's #735 review named both:\n"
            f"    * MISREPORT -- mark_observed refuses a non-owner, so the poll answers\n"
            "      observation_started_claim_window: false and this script would call that\n"
            "      'already lit' when the fuse is untouched.\n"
            f"    * SPENDING SOMEONE ELSE'S GRANT -- if '{owner}' still wants that approval,\n"
            "      starting its 600s window is the co-seat burn #732 exists to describe.\n"
            "  Run leg 2 only against a dead petition of your own."
        )
    status = body.get("status")
    if status != "approved":
        return (
            f"escalation {esc} reads status='{status}', not 'approved'.\n"
            "  mark_observed fires only on an approved, bar-met row, so there is no fuse here\n"
            "  to find -- and a PENDING petition is one somebody is still waiting on."
        )
    if body.get("decided_at") is None:
        return (
            f"escalation {esc} carries no `decided_at`. The measurement is 'how long after the\n"
            "  ruling did the window still read full', which is unanswerable without one."
        )
    return None


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    burn = "--burn" in argv[1:]
    if not args:
        raise SystemExit("usage: fuse_trigger_probe.py <escalation_id> [--burn]")
    esc = args[0]
    if len(esc) < 16:
        raise SystemExit(
            f"'{esc}' looks like a PREFIX. The resolver answers not-found for a prefix "
            "exactly as it does for a nonexistent id, so a short id reads as 'no such "
            "petition'. Pass the full escalation id."
        )

    c = Client(endpoint())
    c.post("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                          "clientInfo": {"name": "fuse-trigger-probe", "version": "1"}})

    print(f"== leg 1 (free): resources/read x3 on {esc} ==")
    first_body = None
    for i, uri in enumerate([f"hestia://escalation/{esc}#decided",
                             f"hestia://escalation/{esc}",
                             f"hestia://escalation/{esc}#decided"]):
        r = c.post("resources/read", {"uri": uri})
        contents = (r.get("result") or {}).get("contents") or []
        body = json.loads(contents[0]["text"]) if contents else {"_err": r}
        if "_hestia_error" in body:
            raise SystemExit(f"  read[{i}] {uri}\n  {body['_hestia_error'].get('message')}")
        if first_body is None:
            first_body = body
        print(f"  read[{i}] {uri} -> status={body.get('status')} "
              f"plugin_id={body.get('plugin_id')} decided_by={body.get('decided_by')}")
        if i == 0 and not burn:
            print(f"  opened_at={body.get('opened_at')} expires_at={body.get('expires_at')}")
        time.sleep(1)

    if not burn:
        print("\nleg 2 skipped (no --burn). Leg 1 alone cannot tell you whether the fuse "
              "is lit;\nonly the poll can, and asking costs the grant. Re-run with --burn "
              "ONLY against\na petition of your own that is already dead in practice.")
        return 0

    seat = running_seat()
    refusal = burn_preconditions(seat, esc, first_body or {})
    if refusal:
        print(f"\n== leg 2 REFUSED ==\n  {refusal}")
        return 2

    print(f"\n== leg 2 (DESTRUCTIVE): attributed poll on {esc} as '{seat}' ==")
    conn = unwrap(c.post("tools/call", {"name": "hestia_connect", "arguments": {
        "plugin_id": seat,
        "host_agent": os.environ.get("HESTIA_MESH_HOST_AGENT", "").strip() or seat,
        "role": "role:constellation:member"}}))
    if "_hestia_error" in conn:
        raise SystemExit(f"  connect refused: {conn['_hestia_error'].get('message')}")
    sid = conn.get("sessionId")
    if not sid:
        raise SystemExit(f"  connect returned no sessionId (keys: {sorted(conn)}). "
                         "An unattributed poll reads false/0 and is indistinguishable "
                         "from a spent window -- refusing to report a result.")
    print(f"  session: {sid}")

    rows = []
    for i in range(2):
        p = unwrap(c.post("tools/call", {"name": "hestia_gate_escalation_poll",
                                         "arguments": {"escalation_id": esc,
                                                       "session_id": sid}}))
        rows.append(p)
        print(f"  poll[{i}] observed={p.get('observation_started_claim_window')} "
              f"remaining={p.get('claim_window_secs_remaining')} "
              f"permits_write={p.get('permits_write')} status={p.get('status')}")
        if i == 0:
            time.sleep(SETTLE_SECS)

    first = rows[0]
    if first.get("observation_started_claim_window") and \
            first.get("claim_window_secs_remaining") == 600:
        print("\nVERDICT: leg 1 did NOT observe. This poll started the fuse, at a full "
              "600s\n         however long ago the ruling landed. resources/read is free.")
    elif not first.get("observation_started_claim_window"):
        print("\nVERDICT: fuse was ALREADY lit before this poll. Either leg 1 observed "
              "(which\n         would refute the finding) or something else polled first "
              "-- check for a\n         co-seat session before concluding the former.\n"
              "         Ownership was checked before this poll, so a non-owner refusal is "
              "NOT\n         among the causes here.")
    else:
        print("\nVERDICT: fuse started here but the window was not full. Unexpected; "
              "report the\n         raw rows rather than a conclusion.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
