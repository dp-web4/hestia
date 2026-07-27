#!/usr/bin/env python3
"""SessionStart: put the law in front of the agent BEFORE its first act.

dp, 2026-07-27: "the law should be injected into context at launch ... transparency.
the lists should live in the vault, but the law should be queriable in-session."

WHY THIS EXISTS. `hestia_operating_law` has been queryable all along, and essentially
nobody queried it — you have to already suspect a rule exists to go asking about it. So in
practice a session learned the law the only other way available: **by being denied by it.**
That is governance by ambush. It also produces exactly the conduct the temperament scale
punishes — an agent that discovers a boundary mid-act rephrases around it, because it is
mid-act and the rephrase is right there, whereas an agent that knew the boundary in advance
never approaches it. The efficiency attractor makes the ambush expensive: the correct path
has to be visible *before* the cheap path is taken, not after.

Ten false-positive denies landed on this member in one session, every one of them a rule
whose text would have told me the shape of the trap (`rm` must stand alone; the matcher
judges by mention, not by executable position). None of that was in context at launch.

FAILING OUT LOUD. If the daemon is unreachable this hook emits a line saying *the law could
not be fetched and the gate is still live*, rather than emitting nothing.

Emitting nothing is the failure mode this whole codebase keeps finding: silence would be
bit-identical to "there is no law here", and an agent reading no-law-shown as no-law-applies
is worse off than one that was never told anything, because it has been given a reason to
believe. A hook that cannot do its job must say so in the same channel it would have used.

FAIL OPEN, FAST, AND SMALL. 3-second budget, and any exception exits 0 with no output — a
SessionStart hook that hangs or crashes degrades every launch, and the law is an aid, not a
gate. The gate is `pre_tool_use.py` and it runs regardless of whether this succeeded.

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp)
     HESTIA_LAW_PLUGIN / HESTIA_LAW_HOST_AGENT (identity to resolve law for)
"""
import json
import os
import sys
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_LAW_PLUGIN", "claude-code")
HOST = os.environ.get("HESTIA_LAW_HOST_AGENT", "claude-code")
BUDGET = 3.0


def _post(payload, hdrs=None):
    req = urllib.request.Request(
        EP,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(hdrs or {}),
        },
    )
    r = urllib.request.urlopen(req, timeout=BUDGET)
    return r.read().decode(), r.headers.get("mcp-session-id")


def _rpc(hdrs, name, args):
    body, _ = _post(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": name, "arguments": args}}, hdrs)
    for line in body.splitlines():
        # The stream opens with an empty `data:` keepalive; skip to the payload.
        if line.startswith("data:") and line[5:].strip().startswith("{"):
            return json.loads(json.loads(line[5:].strip())["result"]["content"][0]["text"])
    return {}


def fetch_law():
    _, sid = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "law-inject", "version": "1"}}})
    hdrs = {"mcp-session-id": sid} if sid else {}
    _post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, hdrs)
    conn = _rpc(hdrs, "hestia_connect", {"plugin_id": PLUGIN, "host_agent": HOST,
                                         "instance_name": "law-inject"})
    session = conn.get("sessionId") or conn.get("session_id")
    if not session:
        raise RuntimeError(f"connect returned no session: {str(conn)[:120]}")
    # `hestia_operating_law` refuses unattributed callers by design — the law you are shown
    # is the law for a specific identity, and handing out someone else's would be worse
    # than handing out none.
    return _rpc(hdrs, "hestia_operating_law", {"session_id": session})


def render(law):
    """The law as a compact, quotable block. Rules verbatim — a paraphrased rule is a
    different rule, and the whole point is that what is shown is what is enforced."""
    ident = law.get("identity") or {}
    lines = [
        "## The law you operate under (hestia, injected at launch)",
        "",
        f"Identity: `{ident.get('plugin_id', '?')}` as `{ident.get('role', '?')}` · "
        f"law_hash `{str(law.get('law_hash', '?'))[:16]}` · "
        f"layers {law.get('layers') or []} · lists bound {law.get('lists_bound') or []}",
        "",
    ]
    rules = law.get("law") or []
    if rules:
        lines.append("| decision | rule |")
        lines.append("|---|---|")
        for r in rules:
            decision = str(r.get("decision", "?"))
            text = " ".join(str(r.get("law", "")).split())
            # Denies get the long budget. They are the rules that STOP you, and they carry
            # the escape hatch — the first cut of this hook truncated the destructive-command
            # deny at 400 chars, landing mid-word in the sentence that tells you a rephrase
            # scores below compliance. Cutting the remedy out of the rule that needs it is
            # how you get an agent that knows it was blocked and not what to do instead.
            # The caps still exist: an overlay is not trusted to be brief.
            cap = 1200 if decision == "deny" else 400
            if len(text) > cap:
                text = text[:cap] + f" …[truncated at {cap} chars — full text: hestia_operating_law]"
            lines.append(f"| **{decision}** | {text} |")
    else:
        # Not the same as a failure, and must not read as one: an empty ruleset is a real
        # and legitimate state (no overlay bound). Say which it is.
        lines.append("_No rules resolve for this identity — an empty law, not a failed "
                     "lookup. Acts are ungoverned by policy at this layer._")
    note = law.get("note")
    if note:
        lines += ["", str(note)]
    lines += ["", "Full text and any later amendment: `hestia_operating_law`. "
                  "Dispute a deny with `hestia_appeal` (its chain hash + your reason) — "
                  "never by rephrasing to reach the same resource."]
    return "\n".join(lines)


def emit(text):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": text,
    }}))


def main():
    try:
        law = fetch_law()
    except Exception as e:  # noqa: BLE001 — fail open, but never fail SILENT
        emit(
            "## hestia law: NOT LOADED\n\n"
            f"The operating law could not be fetched (`{type(e).__name__}: "
            f"{str(e)[:160]}`).\n\n"
            "**This does not mean you are ungoverned.** The PreToolUse gate is a separate "
            "process and enforces regardless of whether this lookup succeeded — so the "
            "rules below-the-line still apply, you just have not been shown them. Treat "
            "destructive, credential-touching and outward-facing acts as governed, and run "
            "`hestia_operating_law` once the daemon is reachable."
        )
        return 0
    try:
        emit(render(law))
    except Exception:
        # Rendering failed on a law we DID fetch — say that, rather than dropping it.
        emit("## hestia law: fetched but could not be rendered\n\n"
             "Run `hestia_operating_law` directly; the daemon is reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
