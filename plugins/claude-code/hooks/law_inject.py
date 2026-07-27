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

FAIL OPEN, FAST, AND SMALL. One WHOLE-RUN deadline, and any exception exits 0 with no output
— a SessionStart hook that hangs or crashes degrades every launch, and the law is an aid, not
a gate. The gate is `pre_tool_use.py` and it runs regardless of whether this succeeded.

THE BUDGET IS A TOTAL, NOT A PER-CALL ALLOWANCE (kimi review of #59, item 3). It used to be
a per-`urlopen` timeout, and this hook makes four sequential calls — so the real worst case
was ~4x the number printed, above the harness's own `timeout` on the hook. A slow-but-alive
daemon (this box has measured 9p-mount tail stalls) would get the hook KILLED mid-render:
no output at all, which is precisely the silent-absence state the docstring above argues is
worse than saying nothing was ever promised. The fail-loud guarantee has to hold under load,
not only under refusal, so the deadline is computed once and every call gets what is left.
`TOTAL_BUDGET` must stay BELOW the `timeout` on this hook's settings.json entry — if that
entry is tightened below it, the harness wins and the guarantee is void again.

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp)
     HESTIA_LAW_PLUGIN / HESTIA_LAW_HOST_AGENT (identity to resolve law for)
"""
import json
import os
import sys
import time
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_LAW_PLUGIN", "claude-code")
HOST = os.environ.get("HESTIA_LAW_HOST_AGENT", "claude-code")
# Whole-run wall clock across all four RPCs. Below the settings.json `timeout: 5` so the
# hook, not the harness, decides what a timeout looks like — a hook killed by the harness
# emits nothing, and emitting nothing is the one outcome this file exists to prevent.
TOTAL_BUDGET = 4.0
# Never hand urlopen a non-positive timeout — it would mean "block forever", which turns
# an exhausted budget into the hang the budget exists to bound.
_MIN_SLICE = 0.2
_DEADLINE = None


def _remaining():
    """Seconds left in the whole-run budget. Raises once it is spent, so an exhausted
    deadline surfaces as the NOT LOADED branch rather than as a silent partial render."""
    if _DEADLINE is None:
        return TOTAL_BUDGET
    left = _DEADLINE - time.monotonic()
    if left <= 0:
        raise TimeoutError(
            f"whole-run law budget of {TOTAL_BUDGET}s exhausted before the law was read")
    return max(left, _MIN_SLICE)


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
    r = urllib.request.urlopen(req, timeout=_remaining())
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


def _must_be_a_law(law):
    """A FAILED LOOKUP MUST NEVER REACH `render` (kimi review of #59, item 1).

    This hook's central claim is that an empty ruleset renders as an explicit *empty law*,
    DISTINCT from a failed lookup. Two paths defeated that claim by handing `render` a dict
    that is not a law at all, whereupon it took the no-rules branch and printed

        "an empty law, not a failed lookup. Acts are ungoverned by policy at this layer."

    — an affirmative statement that the member is ungoverned, produced by a lookup that
    failed. Not silence: a false assurance, which the docstring above argues is the worse
    of the two. The PR that exists to stop a reassuring state from being bit-identical to
    the null state contained that exact shape.

      1. `hestia_operating_law` reports IN-BAND failure as `{"_hestia_error": {...}}`.
         `fetch_law` only raised on transport errors, so an in-band refusal sailed through.
         Narrow to reach — connect succeeds and the session is unresolvable one call later
         (daemon restart or session eviction between the two RPCs) — but not unreachable,
         and every future server-side error class lands here too.
      2. `_rpc` returns `{}` when no `data:` payload line is found. A protocol change, a
         keepalive-only response, or a truncated stream all produce it, and `{}` renders
         identically to a real empty law.

    So the test is positive: a law response ALWAYS carries `identity` and `law` (handler.rs
    builds both unconditionally; `law` is `[]` when no rules resolve, which is the genuine
    empty case this must keep letting through). Anything else is a failure, and failures
    belong in the NOT LOADED branch that says the gate is still live.
    """
    if isinstance(law, dict) and "_hestia_error" in law:
        err = law.get("_hestia_error")
        code = err.get("code") if isinstance(err, dict) else None
        raise RuntimeError(f"daemon refused the law lookup in-band: {code or str(err)[:120]}")
    if not isinstance(law, dict) or "identity" not in law or "law" not in law:
        raise RuntimeError(
            f"response is not an operating-law body (keys: "
            f"{sorted(law)[:8] if isinstance(law, dict) else type(law).__name__})")
    return law


def fetch_law():
    global _DEADLINE
    _DEADLINE = time.monotonic() + TOTAL_BUDGET
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
    return _must_be_a_law(_rpc(hdrs, "hestia_operating_law", {"session_id": session}))


def _cell(text):
    """Make law text safe to sit inside a markdown table cell (kimi review of #59, item 2).

    This was live in the FIRST ROW: the allow rule's own text names the shell metacharacters
    it forbids — "no `&&`, `;`, `|`, newline, backticks" — and that literal pipe is a cell
    separator, so the rule an agent most needs to read rendered with a phantom column and
    its own text split across it. Law that describes shell syntax will keep containing pipes;
    this is structural, not a one-off.

    Only `|` needs escaping. Newlines are already collapsed by the caller's `" ".join(split())`
    (they would break the row outright), and backticks/asterisks inside a cell are harmless
    markdown that renders as the emphasis the law author intended.
    """
    return text.replace("|", "\\|")


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
        # Header says LAW TEXT because that is what the column holds. The rule's *name*
        # (`deny-destructive-commands`) is a different field and is not shown; calling the
        # text "rule" invited reading the quoted sentence as an identifier.
        lines.append("| decision | law text |")
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
            # ESCAPE LAST, and cap the LAW text, not the escaped text: the cap is a promise
            # about how much law you are shown, and `\|` would spend two characters of it on
            # one character of rule. Escaping after also removes the possibility of cutting
            # a backslash away from the pipe it escapes.
            lines.append(f"| **{_cell(decision)}** | {_cell(text)} |")
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
