#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Charm Crush) - reference adapter.

Crush is CLAUDE-CODE LINEAGE in gate semantics (a single `PreToolUse` event, `exit 2` blocks, the
engine FAILS OPEN) but a Go TUI with its OWN lowercase tool vocabulary and - the load-bearing catch -
a DIFFERENT stdin field for the event name. Source-verified from charmbracelet/crush@main:

  - internal/hooks/input.go:24: stdin JSON = {`event`, `session_id`, `cwd`, `tool_name`, `tool_input`}.
    The event field is **`event`**, NOT `hook_event_name`. A gate that checks `hook_event_name` would
    see None, treat it as "not my event", exit 0, and SILENTLY DISARM on every call.
  - internal/hooks/runner.go exit handling: `exit 2` -> DecisionDeny, reason = stderr; `exit 49`
    (HaltExitCode) -> deny + halt the turn; **any OTHER non-zero exit -> "non-blocking error" ->
    DecisionNone (the tool RUNS)**; timeout -> DecisionNone (runs); `exit 0` -> parse stdout JSON
    {decision: allow|deny|none}. Default hook timeout 30s.
  => FAIL-CLOSED BY CONSTRUCTION: only ever exit 0 (explicit confirmed allow) or 2 (deny, with stderr
     text). Never rely on a crash to deny - an uncaught Python exception exits 1, which is a
     non-blocking error = ALLOW here (the gemini live-repro that ran `rm -rf /`). main() wraps the gate
     in a top-level deny-on-exception so a crash fails CLOSED.
  - internal/agent/tools/mcp-tools.go:59 builds MCP tool names as `mcp_<server>_<tool>` (SINGLE
    underscore), not the Claude `mcp__<server>__<tool>`. The governor dispatches on the Claude
    convention, so gate_core.normalize_mcp_name() translates at the boundary.

ENFORCEMENT LIVES IN `plugins/lib/gate_core.py`, not here. This file is the *vocabulary* - the part
that genuinely differs per engine - plus the engine's exit-code semantics. Gate-1a, command-scope and
lineage translation are shared with every other adapter so a fix lands once. (CBP review, thread
`harness-lane-split`: kiro and crush had drifted three ways from gemini in a single commit, and two
of the holes found here were holes gemini had already closed.)

UNKNOWN TOOLS ARE MAXIMALLY GATED. A tool absent from every table below gets every string leaf swept
for secrets, every non-URL leaf command-scoped, and the governor's verdict required. Crush is a moving
upstream and this gate is documented-tier against it, so vocabulary drift is the expected case: the
review that prompted this found `web_fetch`, `web_search`, `sourcegraph`, `read_mcp_resource` and
`list_mcp_resources` all registered upstream and all classified by nothing, therefore examined for
nothing. `tools.json` + `tests/test_tool_inventory.py` now fail the moment an upstream name is
unclassified, so the gap surfaces as a red test rather than as a silent exfil channel.

FIDELITY: documented-tier (contract + tool names source-verified; NOT fired against a live Crush).
Because the gate is fail-closed, a wrong guess over-blocks (safe). The verified pass (live Crush
install) belongs on CBP's onboarding rig.

Config (env-overridable):
  HESTIA_WORKSPACE        root holding the granted repos          (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE     society-safety governor                  (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_CRUSH_IDENTITY   the member's live identity.json          (default: ~/.local/share/crush/hestia-instance/identity.json)
  HESTIA_CRUSH_GATE_MODE  warn | enforce  (default: enforce)
  HESTIA_CRUSH_LAUNCH_CWD launch dir granted for the session       (default: cwd)
  HESTIA_FORBIDDEN_EXTRA  comma-separated extra forbidden tokens
"""
import json
import os
import sys
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
# A missing lib must fail CLOSED. An ImportError at module scope raises BEFORE main()'s
# deny-on-exception wrapper can catch it, and an uncaught exception exits 1 - which Crush treats as a
# non-blocking error and RUNS THE TOOL. So the import is guarded here, at the only place it can be.
try:
    import gate_core as gc  # noqa: E402  the shared Gate-1 enforcement core
    from path_scope import check_paths as _shared_check_paths  # type: ignore
except BaseException as _exc:  # pragma: no cover - exercised by tests/test_fail_closed.sh
    sys.stderr.write(
        f"hestia: deny [gate] - the shared gate library is unavailable "
        f"({type(_exc).__name__}: {str(_exc)[:120]}); the gate cannot vouch for this call, "
        f"failing closed.\n")
    sys.exit(2)

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
IDENTITY = os.path.expanduser(os.environ.get(
    "HESTIA_CRUSH_IDENTITY", "~/.local/share/crush/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

FORBIDDEN = gc.FORBIDDEN_DEFAULT + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# Crush's own home / data dir is always in scope (state, identity, config, crush.db).
CRUSH_HOMES = tuple(os.path.expanduser(p) for p in
                    ("~/.local/share/crush", "~/.config/crush", "~/.crush"))
# `/tmp` and `/var/tmp` are blanket in-scope roots. DELIBERATE, not inherited: they are the scratch
# space and the cross-member hand-off channel. Flagged in review; keeping it as a decision.
TMP_ROOTS = ["/tmp", "/var/tmp"]

# ---------------------------------------------------------------------------
# VOCABULARY - the only per-engine part. Names source-verified against
# charmbracelet/crush@main internal/agent/tools/*.go Name constants.
# Anything NOT listed here classifies as UNKNOWN and is gated hardest.
# ---------------------------------------------------------------------------
VOCAB = gc.Vocabulary(
    # LOCAL read-class (no write, no exec, no network) - the ONLY class that may skip Gate-2.
    read=("view", "ls", "glob", "grep", "diagnostics", "crush_info", "crush_logs", "job_output",
          "read", "read_file", "lsp_diagnostics", "lsp_references", "lsp_hover",
          "lsp_document_symbols", "lsp_workspace_symbols", "lsp_definition"),
    write=("edit", "write", "multiedit",
           # NOT readers despite the `lsp_` prefix: these mutate source. Listing them explicitly
           # instead of prefix-matching `lsp_*` is the point - a prefix rule would silently
           # re-admit the next lsp writer upstream adds. (CBP CRUSH-4)
           "lsp_rename", "lsp_replace_symbol"),
    exec_=("bash",),
    # Network egress. Every one of these READS THE NETWORK - the irreversible direction - so all
    # must meet the governor and have every argument leaf swept for secrets. `fetch`/`download`
    # were the only two classified before review; upstream registers five. (CBP CRUSH-1)
    egress=("fetch", "download",
            "web_fetch",    # fetch_types.go:7  WebFetchToolName
            "web_search",   # fetch_types.go:10 WebSearchToolName
            "sourcegraph"),  # sourcegraph.go
    # MCP-family tools whose names do NOT start with `mcp` and so escaped a prefix-only
    # sweep. (CBP CRUSH-2)
    mcp_tools=("read_mcp_resource", "list_mcp_resources"),
    mcp_prefixes=("mcp",),
    path_keys=("file_path", "path", "absolute_path", "notebook_path", "pattern", "dir_path"),
    list_path_keys=("paths", "file_paths", "include", "exclude", "edits"),
    uri_keys=("uri", "resource_uri"),
    cmd_keys=("command",),
    # Crush lowercase names -> the Claude-lineage TitleCase names the governor dispatches on.
    lineage_tool={"bash": "Shell", "edit": "Edit", "write": "Write", "multiedit": "Edit",
                  "view": "Read", "ls": "Read", "glob": "Glob", "grep": "Grep",
                  "fetch": "WebFetch", "download": "WebFetch", "web_fetch": "WebFetch",
                  "web_search": "WebSearch", "sourcegraph": "WebSearch",
                  "lsp_rename": "Edit", "lsp_replace_symbol": "Edit",
                  "read_mcp_resource": "Read", "list_mcp_resources": "Read"},
)

MODE = os.environ.get("HESTIA_CRUSH_GATE_MODE", "enforce").lower()


def load_in_scope():
    try:
        mrh = json.load(open(IDENTITY, encoding="utf-8")).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]
    except Exception:
        pass
    return ["web4"]


def launch_cwd_repo():
    cwd = (os.environ.get("HESTIA_CRUSH_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def deny(reason, what_to_do, innate=False):
    if innate or MODE == "enforce":
        sys.stderr.write(
            f"hestia: deny [scope] - {reason}. This is a boundary, not a failure: don't re-run the "
            f"same call. {what_to_do} Asking is a trust-building act; reaching is witnessed.\n")
        sys.exit(2)
    sys.stderr.write(f"hestia: warn [scope] - {reason} (warn-rollout: allowed; would block under enforce)\n")


def _gate():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] - could not parse the tool event; failing closed.\n")
        sys.exit(2)

    # Accepts `event` (Crush) or `hook_event_name` (Claude lineage), and gates an unrecognized
    # envelope that still carries a tool_name rather than exiting 0 on it.
    if not gc.should_gate(event):
        sys.exit(0)

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("HESTIA_CRUSH_LAUNCH_CWD") or os.getcwd()
    scopes = gc.dedupe(load_in_scope() + launch_cwd_repo())

    p = gc.plan(tool, tinput, VOCAB)

    # Gate 1a - egress/secret innate invariant. Sweeps every channel a secret can leave by.
    for blob in p.gate1a:
        hit = gc.forbidden_hit(blob, FORBIDDEN)
        if hit:
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. Local paths -> realpath containment. Network endpoints are NOT
    # realpath-scoped (containing `https://example.com/docs` resolves it under cwd and would deny
    # every fetch); gc.as_local_path() has already dropped them.
    if p.paths:
        roots = [os.path.join(WORKSPACE, s) for s in scopes] + list(CRUSH_HOMES) + TMP_ROOTS
        res = _shared_check_paths(p.paths, roots, cwd, for_write=p.for_write)
        if not res.allowed:
            deny(f"'{tool}': {res.reason}",
                 "Adjust to work within scope, or if legitimately needed, request it (request_scope).")

    # Command-scope: the shell command AND every non-URL argument leaf of an MCP/unknown/egress
    # call. An MCP server's argument object is the server's shape, not ours.
    for c in p.cmd_scope:
        if not gc.command_in_scope(c, scopes, WORKSPACE):
            where = "command" if c == (tinput.get("command") if isinstance(tinput, dict) else None) \
                else f"{p.klass} argument"
            deny(f"'{tool}' {where} reaches outside your granted scope ({'+'.join(scopes)})",
                 "Scope it to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety. Local-read-class skips it; write/exec AND egress AND mcp AND every
    # UNKNOWN tool need the daemon's verdict; fail closed. Translated to the Claude lineage first.
    if p.needs_gate2:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="crush", HESTIA_PRE_FAIL_CLOSED="1")
            payload = gc.to_claude_lineage(event, tool, tinput, VOCAB, lineage_name="crush")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(payload),
                               capture_output=True, text=True, timeout=6, env=env)
            if r.returncode != 0:
                msg = (r.stderr.strip() if r.returncode == 2 and r.stderr.strip()
                       else "hestia: deny [safety] - blocked/inconclusive at the society safety gate.")
                if MODE == "enforce":
                    sys.stderr.write(msg if msg.endswith("\n") else msg + "\n")
                    sys.exit(2)
                sys.stderr.write("hestia: warn [safety] - " + msg.split("- ", 1)[-1] +
                                 " (warn-rollout: allowed; would block under enforce)\n")
        except Exception:
            if MODE == "enforce":
                sys.stderr.write("hestia: deny [safety] - could not reach the governor; failing "
                                 "closed on a consequential act.\n")
                sys.exit(2)
            sys.stderr.write("hestia: warn [safety] - governor unreachable (warn-rollout: allowed).\n")

    sys.exit(0)  # the ONLY allow path - reached only after every gate explicitly passed


def main():
    """Top-level deny-on-exception. Crush FAILS OPEN and an uncaught Python exception exits 1, which is
    a non-blocking error = ALLOW. SystemExit passes through (the gate's real 0/2 verdict); anything else
    fails CLOSED. Carried from the gemini live-pass lesson."""
    try:
        _gate()
    except SystemExit:
        raise
    except BaseException as exc:
        sys.stderr.write(
            f"hestia: deny [gate] - the gate crashed ({type(exc).__name__}: {str(exc)[:200]}) and "
            f"cannot vouch for this call; failing closed. This is a boundary, not a failure.\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
