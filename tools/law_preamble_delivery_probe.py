#!/usr/bin/env python3
"""#461, instance 5: the two-bar ruling is SENT by the daemon and DROPPED by the renderer.

WHAT #461 SAYS AND WHY THIS IS NOT A RE-FILE. Issue #461 (open) measured that the composed
operating law omits dp's 2026-08-06 two-bar ruling, so invited peers re-derive it as a
defect. Its remedy landed: `LAW_PREAMBLE` (core/src/policy/preamble.rs) now carries the
ruling verbatim, pinned by `the_two_bar_ruling_is_published_and_not_merely_enforced`, whose
own message says the preamble "reaches every member".

That test's DOMAIN is a Rust string constant. It cannot see delivery. This probe measures
delivery, and delivery is where the remedy stops: the daemon puts the ruling in the
`preamble` key of the law response, and the SessionStart renderer walks `identity`, `law`
and `note` only. The paragraph written *because* a ruling that is merely queryable does not
reach anyone is itself left merely queryable -- by the hook whose own docstring is the
argument that queryable is not delivered ("`hestia_operating_law` has been queryable all
along, and essentially nobody queried it").

Instance 5 landed 2026-09-02, thirteen days after the remedy merged: kimi-code, answering
notices 4194/4213, wrote that a 3600s TTL against a 43s/275s sovereign-alone decision means
"either the TTL or the decision floor is lying" -- the exact re-derivation, from a seat that
had authored a forum post on the ruling. Instances 1-4 are counted in the pinning test.

PASS means the gap is CLOSED. This probe is written to go green when the renderer delivers
the ruling, so it is a regression pin, not a one-shot measurement.

Usage:  python3 -I law_preamble_delivery_probe.py <path-to-law-inject-hook>
"""
import json
import sys
import urllib.request

EP = "http://127.0.0.1:7711/mcp"
RULING = "an invitation to participate, not a blocker"


def _post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=10)
    return r.read().decode(), r.headers.get("mcp-session-id")


def _rpc(hdrs, name, args):
    body, _ = _post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, hdrs)
    for line in body.splitlines():
        if line.startswith("data:") and line[5:].strip().startswith("{"):
            return json.loads(json.loads(line[5:].strip())["result"]["content"][0]["text"])
    return {}


def fetch_law(plugin):
    _, sid = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "preamble-probe", "version": "1"}}})
    h = {"mcp-session-id": sid} if sid else {}
    _post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
    conn = _rpc(h, "hestia_connect", {"plugin_id": plugin, "host_agent": plugin,
                                      "instance_name": "preamble-probe"})
    sess = conn.get("sessionId") or conn.get("session_id")
    if not sess:
        raise SystemExit(f"connect returned no session: {str(conn)[:160]}")
    return _rpc(h, "hestia_operating_law", {"session_id": sess})


def load_render(hook_path):
    """Import the renderer from the seat hook WITHOUT executing its main().

    Read-and-exec rather than importlib-by-path because the hook lives in a governed
    directory and this probe must never be the thing that writes there.
    """
    with open(hook_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    ns = {"__name__": "law_inject_probe"}
    exec(compile(src, hook_path, "exec"), ns)  # noqa: S102 - reading our own seat's hook
    return ns["render"]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[-1])
    hook = sys.argv[1]

    law = fetch_law("claude-code")
    preamble = law.get("preamble") or ""
    sent = RULING in preamble
    anywhere = RULING in json.dumps(law)

    rendered = load_render(hook)(law)
    delivered = RULING in rendered

    print(f"law response keys      : {sorted(law)}")
    print(f"preamble present       : {'preamble' in law} ({len(preamble)} chars)")
    print(f"ruling SENT by daemon  : {sent}   (anywhere in response: {anywhere})")
    print(f"ruling DELIVERED by hook: {delivered}  (rendered block: {len(rendered)} chars)")

    if not sent:
        print("\nINCONCLUSIVE: the daemon did not send the ruling at all. That is a "
              "different defect from the one this probe measures (#461 at the daemon "
              "layer, not the renderer layer). Re-read preamble.rs before filing.")
        return 2
    if delivered:
        print("\nPASS: the ruling reaches the member's launch context. #461's acceptance "
              "test -- does a peer holding only the notice, the record and the composed "
              "law know a lone-sovereign decision is the design? -- is met on this leg.")
        return 0
    print("\nFAIL (#461 still open, renderer leg): the daemon SENDS the ruling and the "
          "renderer DROPS it. `render()` walks identity/law/note and never reads "
          "`preamble`, so the paragraph added to stop peers re-deriving the ruling is "
          "absent from the surface every session actually reads. Five seats have now "
          "re-derived it; the fifth was 13 days after the remedy merged.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
