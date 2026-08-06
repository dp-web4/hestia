#!/usr/bin/env python3
"""Where does a hook's stdout actually GO on each engine this fleet runs?

Not a pytest file on purpose (no `*_test.py` / `test_*.py` name): it would be RED
today on 3 of 4 engines, and a red that everyone has to route around teaches
nothing. It is a REPORT. Run it, read the matrix, fix the emitter, run it again.

The fleet deploys ONE script -- `session-mesh-inbox.sh` -- to four different
harnesses and has never once measured a second one. This encodes each engine's
hook-output contract as data, feeds candidate payloads through it, and prints
where the bytes land: at the MODEL, at a HUMAN's terminal, or nowhere.

Every contract below cites where it was read. None of them is a guess, and none
of them is a launch of another member's seat -- three are code reads of the
installed engine, one is this process's own live context.

  claude-code   Claude Code (this seat)   live positive control, 2026-08-06:
                the law block arrives as "SessionStart hook additional context:"
                (envelope) AND three hooks arrive as "SessionStart:startup hook
                success: ..." (plain stdout). BOTH forms reach the model.
  gemini        @google/gemini-cli 0.52.0  bundle/chunk-IQDAUFS5.js
                (HookResult.getAdditionalContext, convertPlainTextToHookOutput)
                + bundle/gemini-6K6USV55.js (SessionStart consumption).
  codex         @openai/codex 0.145.0      embedded draft-07 schemas
                `<event>.command.output` in the native binary; `additionalProperties:
                false` at BOTH levels; error string "hook returned invalid session
                start JSON output"; hooks/src/output_spill.rs.
  kimi-code     kimi-code 0.31.1           kimi-code's own code read + launches,
                notices 1106 + 1107 / forum/kimi-re-1105-... and
                forum/kimi-re-1107-...-2026-08-06.md.

Landing sites:
  MODEL   the bytes enter the model's context -- the only outcome the mesh wants
  HUMAN   printed to stderr/terminal; in a mesh-FIRED session that is a log file
          nobody reads, so the model is dark and nothing says so
  DARK    discarded, or rejected as a parse error; model never sees it
  SPILL   delivered as a disk pointer + preview, not as the bytes you sent
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "session-mesh-inbox.sh"

# Codex spills additionalContext over this many tokens to disk and hands the model
# a preview plus recovery metadata instead ("Approximate token threshold for
# spilling this hook's `additionalContext` to disk. `null` uses 2,500 tokens").
CODEX_SPILL_TOKENS = 2500
TOKENS = lambda s: len(s) / 4  # noqa: E731 - order-of-magnitude only, and said so


def claude_code(event, stdout, rc=0):
    if event != "SessionStart":
        return "?", "not measured on this seat"
    try:
        doc = json.loads(stdout)
        ctx = (doc.get("hookSpecificOutput") or {}).get("additionalContext")
        return ("MODEL", "envelope honored") if ctx else ("DARK", "envelope carried no additionalContext")
    except Exception:
        return "MODEL", "plain stdout honored too (rare: this engine takes both)"


def gemini(event, stdout, rc=0):
    if event != "SessionStart":
        return "?", "port also exists on BeforeAgent/AfterTool; not measured here"
    try:
        doc = json.loads(stdout)
    except Exception:
        # convertPlainTextToHookOutput: rc==0 -> {decision:"allow", systemMessage:text}
        # and the SessionStart caller does writeToStderr(result.systemMessage).
        return "HUMAN", "plain text becomes systemMessage -> stderr, NOT the model"
    ctx = (doc.get("hookSpecificOutput") or {}).get("additionalContext")
    if not ctx:
        if doc.get("systemMessage"):
            return "HUMAN", "systemMessage -> stderr"
        return "DARK", "no additionalContext in hookSpecificOutput"
    mangled = "<" in ctx or ">" in ctx
    return "MODEL", (
        "wrapped <hook_context>; ANGLE BRACKETS HTML-ESCAPED (&lt;/&gt;)" if mangled
        else "wrapped <hook_context>"
    )


# Which codex events may emit additionalContext at all -- read off the embedded
# schemas. The other five ship the warning "ignoring additionalContextLimit for
# <hook>: this event cannot emit additionalContext".
CODEX_CTX_EVENTS = {
    "PreToolUse", "PostToolUse", "SessionStart", "SubagentStart", "UserPromptSubmit",
}


def codex(event, stdout, rc=0):
    if not stdout.strip():
        return "DARK", "no output"
    try:
        doc = json.loads(stdout)
    except Exception:
        return "DARK", f"parse error: 'hook returned invalid {event} JSON output'"
    if event not in CODEX_CTX_EVENTS:
        return "DARK", "this event cannot emit additionalContext"
    allowed = {"continue", "hookSpecificOutput", "stopReason", "suppressOutput",
               "systemMessage", "decision", "reason"}
    extra = set(doc) - allowed
    if extra:
        return "DARK", f"schema is CLOSED (additionalProperties:false); rejected keys {sorted(extra)}"
    hso = doc.get("hookSpecificOutput") or {}
    if hso.get("hookEventName") != event:
        return "DARK", "hookEventName is required and const-matched to the event"
    if set(hso) - {"hookEventName", "additionalContext"}:
        return "DARK", "inner object is CLOSED too"
    ctx = hso.get("additionalContext")
    if not ctx:
        return "DARK", "envelope carried no additionalContext"
    if TOKENS(ctx) > CODEX_SPILL_TOKENS:
        return "SPILL", f"~{TOKENS(ctx):.0f} tok > {CODEX_SPILL_TOKENS}: written to hook_outputs/, model gets a preview"
    return "MODEL?", "schema-valid; consumption NOT launch-verified (seat is out of credits)"


def kimi_code(event, stdout, rc=0):
    if event == "SessionStart":
        return "DARK", "triggerSessionStart discards the result in code (1106)"
    if event == "UserPromptSubmit":
        if not stdout.strip():
            return "DARK", "empty output"
        try:
            doc = json.loads(stdout)
        except Exception:
            return "MODEL", "plain stdout appended as a user message (launch-verified, 1106)"
        if doc.get("message") or (doc.get("hookSpecificOutput") or {}).get("message"):
            return "MODEL", "message field appended (top-level: 1106; hookSpecificOutput.message: 1107)"
        # userPromptHookMessage falls back to result.stdout when no message key
        # parses out, so the RAW JSON text itself is appended, <hook_result>-wrapped.
        return "MODEL", "no message key -> raw stdout fallback: the JSON text itself is delivered (launch-verified, 1107)"
    return "?", "not measured"


ENGINES = [("claude-code", claude_code), ("gemini", gemini),
           ("codex", codex), ("kimi-code", kimi_code)]


def envelope(text, event="SessionStart"):
    return json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                              "additionalContext": text}})


def report(title, event, payload):
    print(f"\n### {title}   [event: {event}]")
    print(f"    {len(payload)} bytes: {payload.splitlines()[0][:78] if payload.strip() else '(empty)'}")
    for name, fn in ENGINES:
        where, why = fn(event, payload)
        print(f"    {name:<12} {where:<7} {why}")


def main():
    print(__doc__.split("\n\n")[0])
    print(f"\nemitter under test: {HOOK}")

    # What the hook ACTUALLY emits today, in its loudest state -- the one it was
    # written to make impossible to miss.
    dark = subprocess.run(["sh", str(HOOK)], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"}).stdout
    if not dark.strip():
        dark = "=== HESTIA MEMBER MESH: INBOX NOT READ — this session is DARK ===\n"
        print("    (ran the hook with HESTIA_MESH_PLUGIN unset; using the literal "
              "banner because this host's peek did not take the rc=2 path)")

    report("AS SHIPPED — plain stdout, the DARK banner", "SessionStart", dark)
    report("PROPOSED — the same text in the shared envelope", "SessionStart", envelope(dark))
    report("PROPOSED — kimi's port, one event over", "UserPromptSubmit", dark)
    report("The SHARED ENVELOPE on kimi's port (raw-stdout fallback, 1107)",
           "UserPromptSubmit", envelope(dark, "UserPromptSubmit"))
    report("A LONG payload in the envelope (e.g. the full operating law)",
           "SessionStart", envelope("x" * 4 * (CODEX_SPILL_TOKENS + 500)))

    print("""
    MODEL   reaches the model      MODEL?  schema-valid, consumption unverified
    HUMAN   stderr only            DARK    discarded or rejected     SPILL   disk pointer

    Read: the fleet's one shared context-injection script reaches the model on
    exactly ONE of four engines, and fails three different ways on the rest.
    The envelope fixes two of them and cannot fix kimi, because on kimi the fix
    is not an encoding -- it is a different EVENT. There is no single (event,
    document) that serves four seats: portability here means a per-engine
    emitter, not a cleverer union document. Codex's schema is CLOSED at both
    levels, so a union document with extra keys for other engines is REJECTED
    outright -- the obvious fix is the one that cannot work.""")


if __name__ == "__main__":
    sys.exit(main())
