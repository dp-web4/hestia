#!/usr/bin/env python3
"""Withdraw YOUR OWN pending escalation, so a human is not asked to rule on a dead request.

Why this exists
---------------
The gate auto-mints a petition on refusal. Most of them are dead on arrival: the
member reaches the same result a compliant way (unrolling a `for` loop into simple
commands is the common one) and no longer wants the write. What is left behind is a
`pending` row that an operator will eventually be shown.

Lapsing is worse than withdrawing. An expired row records NO decision; a withdrawn
one records `gate_escalation_withdrawn` with the asker's own reason, which is the
disposition a reader can actually weigh.

And the affordance was undiscoverable. `hestia gate` ships `pending`, `poll`,
`approve`, `deny`, `corroborate` — no `withdraw`. There is no
`hestia_gate_escalation_withdraw` MCP tool either. The route is
`hestia_gate_arbitrate_escalation` with `approve: false` against your OWN row:
`independence` comes back `None` for a self-directed ruling, which the handler reads
as `Channel::SelfWithdrawn` (`core/src/server/handler.rs`, "a withdrawal is filed
under its own channel and its own event kind"). Nothing in the tree named that, so
this does.

Preconditions, checked before any write
---------------------------------------
Every one is decided from the FREE `resources/read` body, so a refusal costs nothing
and never touches the record it declines to withdraw:

  * the row's `plugin_id` equals this process's seat (`HESTIA_MESH_PLUGIN`, which
    `hestia-mesh.py` already requires and refuses to default) — NOT argv, because an
    argument is a hard-coded string with extra steps;
  * `status` is `pending` — a decided or expired row has nothing to withdraw, and
    self-directed APPROVAL is refused by the daemon itself;
  * the body came from the LIVE store — the chain-fallback body carries no
    `plugin_id`, so ownership is unverifiable and this refuses rather than assumes.

Stated plainly: these are client-side and therefore advisory. `hestia_connect`
authenticates nobody (#63/#128), so this stops THIS DRIVER from being an affordance
for withdrawing someone else's petition; it does not close the daemon-side hole.
That is the #732 ruling question and no client check substitutes for it.

Leg 1 uses `resources/read`, which does NOT start the claim fuse (#732,
`tools/escalation_read.py`). Withdrawal itself is a decision, not an observation, so
it does not spend a claim window either — there is nothing left to claim.

Usage
-----
    HESTIA_MESH_PLUGIN=<your seat> \\
      python3 -I tools/escalation_withdraw.py <id|pointer> [--reason '...'] [--json]

Run under `python3 -I` if cwd may be /tmp: stray modules there shadow the stdlib and
this imports `urllib.request`.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_REASON = (
    "withdrawn by the asker: the act was completed compliantly, so this grant "
    "would authorize nothing anyone wants"
)


def endpoint() -> str:
    if ENDPOINT_FILE.exists():
        return ENDPOINT_FILE.read_text().strip()
    return "http://127.0.0.1:7711/mcp"


class Client:
    """Minimal MCP client: initialize, resources/read, tools/call."""

    def __init__(self, url: str, timeout: float = 20.0):
        self.url = url
        self.timeout = timeout
        self.session = None
        self._id = 0

    def post(self, method: str, params=None):
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

    def handshake(self, name: str):
        self.post("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": name, "version": "1"},
        })

    def call(self, tool: str, arguments: dict):
        resp = self.post("tools/call", {"name": tool, "arguments": arguments})
        if "result" not in resp:
            raise SystemExit(f"{tool} failed: {json.dumps(resp)[:600]}")
        result = resp["result"]
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        content = result.get("content") or []
        return json.loads(content[0].get("text", "{}")) if content else {}


def seat() -> str:
    """The running member's id, from the one place the mesh already mandates it."""
    s = (os.environ.get("HESTIA_MESH_PLUGIN") or "").strip()
    if not s:
        raise SystemExit(
            "HESTIA_MESH_PLUGIN is unset, so this process cannot say which member it is. "
            "Withdrawal is a ruling on your OWN row; it needs a seat, not an argument."
        )
    return s


def read_free(c: Client, pointer: str) -> dict:
    """Leg 1: the free route. Does not start the claim fuse (#732)."""
    ptr = pointer.strip()
    if not ptr.startswith("hestia://escalation/"):
        ptr = f"hestia://escalation/{ptr}"
    resp = c.post("resources/read", {"uri": ptr})
    if "result" not in resp:
        raise SystemExit(f"resources/read failed: {json.dumps(resp)[:600]}")
    contents = resp["result"].get("contents") or []
    if not contents:
        raise SystemExit("resources/read returned no contents")
    body = json.loads(contents[0].get("text", "{}"))
    if "_hestia_error" in body:
        raise SystemExit(f"not resolvable: {json.dumps(body)[:400]}")
    return body


def preconditions(body, me):
    """Return the refusal text, or None if withdrawal is admissible. Read-only."""
    eid = body.get("escalation_id") or "?"
    if body.get("source") != "live_store":
        return (f"escalation {eid} resolved from '{body.get('source')}', not the live store. "
                "That body carries no plugin_id, so ownership is unverifiable — refusing "
                "rather than assuming.")
    owner = body.get("plugin_id")
    if owner != me:
        return (f"escalation {eid} belongs to '{owner}', and this process is '{me}'. "
                "Withdrawal is the asker's move; ruling on a peer's row is `corroborate` "
                "or `arbitrate`, not this.")
    status = body.get("status")
    if status != "pending":
        return (f"escalation {eid} is '{status}', not pending — there is nothing to "
                "withdraw. A decided row keeps its ruling; an expired one already "
                "recorded no decision.")
    return None


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv[1:]
    reason = DEFAULT_REASON
    if "--reason" in argv[1:]:
        i = argv.index("--reason")
        if i + 1 >= len(argv):
            raise SystemExit("--reason needs a value")
        reason = argv[i + 1]
        args = [a for a in args if a != reason]
    if not args:
        raise SystemExit(__doc__.strip().splitlines()[0]
                         + "\nusage: escalation_withdraw.py <id|pointer> [--reason '...'] [--json]")

    me = seat()
    c = Client(endpoint())
    c.handshake("escalation-withdraw")
    body = read_free(c, args[0])

    refusal = preconditions(body, me)
    if refusal is not None:
        print("== REFUSED ==\n  " + refusal, file=sys.stderr)
        return 3

    conn = c.call("hestia_connect", {
        "plugin_id": me,
        "host_agent": (os.environ.get("HESTIA_MESH_HOST_AGENT") or "").strip() or me,
        "role": "role:constellation:member",
    })
    session_id = conn.get("sessionId") or conn.get("session_id")
    if not session_id:
        raise SystemExit(f"hestia_connect returned no session: {json.dumps(conn)[:400]}")

    out = c.call("hestia_gate_arbitrate_escalation", {
        "session_id": session_id,
        "escalation_id": body["escalation_id"],
        "approve": False,
        "reason": reason,
    })
    if as_json:
        print(json.dumps(out, indent=2))
    else:
        status = out.get("status") or out.get("decided_status") or "?"
        via = out.get("decided_via") or "?"
        print(f"{body['escalation_id']}  status={status}  via={via}")
        if "_hestia_error" in out:
            print(json.dumps(out, indent=2))
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
