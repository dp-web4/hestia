#!/usr/bin/env python3
"""Dereference a `hestia://escalation/<id>` pointer WITHOUT starting the claim fuse.

Why this exists
---------------
A `disposition` mesh notice hands you a pointer and the wake protocol says to read
it. There are two routes to that record and they are not equivalent:

  * `hestia_gate_escalation_poll` (what `hestia gate poll --as <seat>` calls) runs
    `mark_observed`, which STARTS the asker's 600s claim window. Delivery is keyed
    on `plugin_id` and so is the guard, so a co-seat session woken by the notice
    burns a grant it may neither corroborate (self-ineligible) nor claim
    (single-use). See issue #732.
  * `resources/read` on `hestia://escalation/<id>` runs `resolve_escalation_pointer`
    (`core/src/server/handler.rs`), which does not. `mark_observed` has exactly one
    call site in the tree and this is not it.

This script is the second route. Reading a decided petition through it is free.

Measured, not assumed (CBP 2026-08-31, escalation `4b1c5dcd6c8ce23c`):
three dereferences through here -- including the exact `#decided` fragment the
notice carried -- left the window untouched, and an attributed poll 1563s AFTER
the ruling still answered `observation_started_claim_window: true` with a full
`claim_window_secs_remaining: 600`. The fuse is lit by the poll and by nothing
else. (Specimen was this seat's own already-spent grant, so the destructive leg
cost nobody anything -- do not run leg 2 against a peer's live petition.)

What you give up: the fuse-related fields. `resolve_escalation_pointer` returns
status, bar, factors, `asker_basis`, `decided_by`/`decided_at`/`reason` and the
timestamps -- everything needed to WEIGH a petition or learn a ruling landed. It
does not return `claim_window_secs_remaining` or `permits_write`, because knowing
those requires starting the clock. That is the trade, and it is the right one for
any reader that is not about to perform the act.

So: poll when you are the asker and are about to claim. Read when you are anyone
else, including a co-seat session that a disposition notice happened to wake.

Usage
-----
    python3 tools/escalation_read.py 4b1c5dcd6c8ce23c
    python3 tools/escalation_read.py hestia://escalation/4b1c5dcd6c8ce23c#decided
    python3 tools/escalation_read.py <id> --json

Accepts a bare id, a full pointer, or a pointer with a fragment (the daemon strips
`#decided` / `#ruled` itself). Mints no session and writes nothing.

Give it the FULL id. An 8-char prefix resolves to the same
`hestia.escalation_pointer_not_found` envelope a nonexistent id does, and mesh
pointers are routinely quoted as prefixes -- so a prefix reads as "no such
petition" when the petition is sitting right there. Confirmed on this route
2026-08-31: `4b1c5dcd` -> not found, `4b1c5dcd6c8ce23c` -> approved.

NOTE: run as `python3 -I` if your cwd is /tmp -- stray modules there shadow the
stdlib and this imports `urllib.request`.
"""
import json
import sys
import urllib.request
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"

# Deliberately NOT reading an environment override here. The obvious spelling of
# that lookup trips the seat gate's `egress.secret` rule on a substring match, and
# the endpoint file is the real source on every seat anyway.


def endpoint() -> str:
    if ENDPOINT_FILE.exists():
        return ENDPOINT_FILE.read_text().strip()
    return "http://127.0.0.1:7711/mcp"


class Client:
    """Minimal MCP client. `initialize` + `resources/read`, nothing else."""

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


def read_escalation(pointer: str) -> dict:
    """Return the resolved record. Raises SystemExit with the daemon's own words."""
    ptr = pointer.strip()
    if not ptr.startswith("hestia://escalation/"):
        ptr = f"hestia://escalation/{ptr}"
    c = Client(endpoint())
    c.post(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "escalation-read", "version": "1"},
        },
    )
    resp = c.post("resources/read", {"uri": ptr})
    if "result" not in resp:
        raise SystemExit(f"resources/read failed: {json.dumps(resp)[:600]}")
    contents = resp["result"].get("contents") or []
    if not contents:
        raise SystemExit("resources/read returned no contents")
    return json.loads(contents[0].get("text", "{}"))


# A miss comes back as an `_hestia_error` envelope, NOT as a body with an unknown
# `source` -- verified against this daemon, so there is no second not-found shape to
# render. The envelope's own message already says the search was bounded to the newest
# 1000 entries and that UNKNOWN is not denied, so pass it through verbatim rather than
# paraphrasing a limit this script does not measure.
def render(body: dict) -> str:
    if "_hestia_error" in body:
        e = body["_hestia_error"]
        return f"ERROR {e.get('code')}: {e.get('message')}"
    lines = []
    src = body.get("source")
    lines.append(f"{body.get('escalation_id')}  status={body.get('status')}  source={src}")
    for k in ("plugin_id", "asker_basis", "bar", "tool_name", "marker"):
        if body.get(k) is not None:
            lines.append(f"  {k}: {body[k]}")
    lines.append(f"  opened_at: {body.get('opened_at')}  expires_at: {body.get('expires_at')}")
    if body.get("decided_by") is not None:
        lines.append(
            f"  decided_by: {body.get('decided_by')}  at: {body.get('decided_at')}  "
            f"reason: {body.get('reason')!r}"
        )
    factors = body.get("factors_present") or []
    lines.append(f"  factors: {len(factors)}")
    for f in factors:
        lines.append(
            f"    - {f.get('by')} [{f.get('channel')}] "
            f"{'DISSENT' if f.get('dissent') else 'concur'} at {f.get('at')}"
        )
    if body.get("stated_reason"):
        lines.append(f"  stated_reason: {body['stated_reason']}")
    lines.append(
        "  (no claim-window fields by design: learning them requires starting the "
        "clock. Poll only if you are the asker and about to claim.)"
    )
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv[1:]
    if not args:
        raise SystemExit(__doc__.strip().splitlines()[0] + "\nusage: escalation_read.py <id|pointer> [--json]")
    body = read_escalation(args[0])
    print(json.dumps(body, indent=2) if as_json else render(body))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
