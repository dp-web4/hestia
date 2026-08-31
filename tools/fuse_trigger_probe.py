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
it. So the probe refuses to run leg 2 without `--burn` AND an explicit id.

CHOOSE THE SPECIMEN HONESTLY. Run leg 2 only against a petition that is:
  * yours (the `plugin_id` on the row is your seat), AND
  * already dead in practice -- the act was abandoned, or completed by a
    compliant alternate route, so the grant authorises nothing anyone wants.
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
    python3 -I tools/fuse_trigger_probe.py <escalation_id> --burn     # both legs

Run under `python3 -I` if cwd may be /tmp: stray modules there shadow the stdlib
and this imports `urllib.request`.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"
SETTLE_SECS = 17

# No environment override for the endpoint: the obvious spelling of that lookup
# trips the seat gate's `egress.secret` substring rule, and the endpoint file is
# the real source on every seat.


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
    for i, uri in enumerate([f"hestia://escalation/{esc}#decided",
                             f"hestia://escalation/{esc}",
                             f"hestia://escalation/{esc}#decided"]):
        r = c.post("resources/read", {"uri": uri})
        contents = (r.get("result") or {}).get("contents") or []
        body = json.loads(contents[0]["text"]) if contents else {"_err": r}
        if "_hestia_error" in body:
            raise SystemExit(f"  read[{i}] {uri}\n  {body['_hestia_error'].get('message')}")
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

    print(f"\n== leg 2 (DESTRUCTIVE): attributed poll on {esc} ==")
    conn = unwrap(c.post("tools/call", {"name": "hestia_connect", "arguments": {
        "plugin_id": "claude-code", "host_agent": "claude-code",
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
              "-- check for a\n         co-seat session before concluding the former.")
    else:
        print("\nVERDICT: fuse started here but the window was not full. Unexpected; "
              "report the\n         raw rows rather than a conclusion.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
