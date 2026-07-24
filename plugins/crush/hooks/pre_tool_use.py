#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Charm Crush) - reference adapter.

Crush is CLAUDE-CODE LINEAGE in gate semantics (a single `PreToolUse` event, `exit 2` blocks, the
engine FAILS OPEN) but a Go TUI with its OWN lowercase tool vocabulary and - the load-bearing catch -
a DIFFERENT stdin field for the event name. Source-verified from charmbracelet/crush@main:

  - internal/hooks/input.go: stdin JSON = {`event`, `session_id`, `cwd`, `tool_name`, `tool_input`}.
    The event field is **`event`**, NOT `hook_event_name`. A gate that checks `hook_event_name` would
    see None, treat it as "not my event", exit 0, and SILENTLY DISARM on every call. We check `event`
    (with hook_event_name as a harmless fallback).
  - internal/hooks/runner.go exit handling: `exit 2` -> DecisionDeny, reason = stderr; `exit 49`
    (HaltExitCode) -> deny + halt the turn; **any OTHER non-zero exit -> "non-blocking error" ->
    DecisionNone (the tool RUNS)**; timeout -> DecisionNone (runs); `exit 0` -> parse stdout JSON
    {decision: allow|deny|none}. Default hook timeout 30s.
  => FAIL-CLOSED BY CONSTRUCTION: only ever exit 0 (explicit confirmed allow) or 2 (deny, with stderr
     text). Never rely on a crash to deny - an uncaught Python exception exits 1, which is a
     non-blocking error = ALLOW here (the gemini live-repro that ran `rm -rf /`). main() wraps the gate
     in a top-level deny-on-exception so a crash fails CLOSED.

Tool vocabulary (source-verified, internal/agent/tools/*.go Name constants):
  local read: view, ls, glob, grep, diagnostics, crush_info, crush_logs, lsp_* (readers), job_output
  write:      edit, write, multiedit
  exec:       bash
  egress:     fetch, download   (network - fetch pulls a URL, download pulls a URL to a local file)
  mcp:        dynamic `mcp__<server>__<tool>` tools
The governor dispatches on Claude TitleCase names, so LINEAGE_TOOL translates at the boundary.

FIDELITY: documented-tier (contract + tool names source-verified; NOT fired against a live Crush).
The per-tool `tool_input` arg names are Claude-lineage-compatible (file_path/command/pattern/url) and
defensively widened; because the gate is fail-closed, a wrong guess over-blocks (safe). The verified
pass (live Crush install) belongs on CBP's onboarding rig.

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
import re
import sys
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
try:
    from path_scope import check_paths as _shared_check_paths  # type: ignore
except Exception:
    _shared_check_paths = None

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
IDENTITY = os.path.expanduser(os.environ.get(
    "HESTIA_CRUSH_IDENTITY", "~/.local/share/crush/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# Crush LOCAL read-class tools (no write, no exec, no network) - may skip Gate-2.
READ_CLASS = {"view", "ls", "glob", "grep", "diagnostics", "crush_info", "crush_logs", "job_output",
              "read", "read_file"}
# Network egress tools: fetch (URL -> context), download (URL -> local file). They READ the network -
# the irreversible direction - so they must meet the governor (Gate-2) and have their url swept for
# secrets (Gate-1a). `download` also writes a local file_path, which Gate-1b scopes normally.
EGRESS_CLASS = {"fetch", "download"}
# Crush's own home / data dir is always in scope (state, identity, config, crush.db).
CRUSH_HOMES = tuple(os.path.expanduser(p) for p in
                    ("~/.local/share/crush", "~/.config/crush", "~/.crush"))


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


def _strings(v, depth=0):
    if isinstance(v, str):
        return [v]
    if depth > 4:
        return []
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x, depth + 1)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x, depth + 1)]
    return []


def path_targets(tool_input):
    """File-path args. Crush: view/edit/write/multiedit take `file_path`; ls/glob/grep take
    `path`/`pattern`; download writes `file_path`. Defensive superset + list forms."""
    out = []
    if isinstance(tool_input, dict):
        for k in ("file_path", "path", "absolute_path", "notebook_path", "pattern", "dir_path"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
        for k in ("paths", "file_paths", "include", "exclude", "edits"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        out.append(x)
                    elif isinstance(x, dict):  # multiedit: [{file_path,...}] or [{old,new}]
                        fp = x.get("file_path") or x.get("path")
                        if isinstance(fp, str):
                            out.append(fp)
    return out


def command_of(tool_input):
    """bash passes the command string under `command`."""
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(x) for x in c)
    return None


def egress_targets(tool, tool_input):
    """fetch/download network args: `url` + any free-text prompt/query. Swept by Gate-1a (a secret is
    laundered out inside a URL) but NOT by Gate-1b (realpath-containing a URL resolves under cwd and
    would deny every fetch). Only for the network tools."""
    if tool.lower() not in EGRESS_CLASS or not isinstance(tool_input, dict):
        return []
    out = []
    for k in ("url", "urls", "prompt", "query"):
        out.extend(_strings(tool_input.get(k)))
    return out


def mcp_strings(tool, tool_input):
    """A dynamic `mcp__<server>__<tool>` call's tool_input is the server's argument object - Gate-1a
    and command-scope are blind to it unless swept. Only for MCP-named tools."""
    if not tool.lower().startswith("mcp") or not isinstance(tool_input, dict):
        return []
    return _strings(tool_input)


def dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Crush lowercase tool names -> the Claude-lineage TitleCase names the society governor dispatches on.
LINEAGE_TOOL = {"bash": "Shell", "edit": "Edit", "write": "Write", "multiedit": "Edit",
                "view": "Read", "ls": "Read", "glob": "Glob", "grep": "Grep",
                "fetch": "WebFetch", "download": "WebFetch"}


def to_claude_lineage(event, tool, tinput):
    """Re-shape a Crush PreToolUse event into the Claude-lineage shape the governor understands,
    lossless (original fields ride under `source_event`)."""
    out = dict(event)
    if tool.lower().startswith("mcp"):
        out["tool_name"] = tool  # already mcp__server__tool shaped
    else:
        out["tool_name"] = LINEAGE_TOOL.get(tool.lower(), tool)
    if isinstance(tinput, dict):
        ti = dict(tinput)
        # download carries a `url` already; fetch too. Ensure the governor's egress check sees a target.
        if "url" not in ti:
            m = re.search(r"https?://[^\s\"'<>)]+", str(tinput.get("prompt") or tinput.get("query") or ""))
            if m:
                ti["url"] = m.group(0)
        out["tool_input"] = ti
    out["source_event"] = {"lineage": "crush", "tool_name": tool, "tool_input": tinput}
    return out


def _all_repos():
    try:
        return [d for d in os.listdir(WORKSPACE)
                if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith(".")]
    except Exception:
        return []


def path_in_scope(path, scopes):
    p = path.replace("\\", "/")
    low = p.lower()
    if any(h.lower() in low for h in CRUSH_HOMES) or "~/.crush" in low:
        return True
    if p.startswith(("/tmp", "/var/tmp")):
        return True
    if WORKSPACE in p:
        rest = p.split(WORKSPACE, 1)[1].lstrip("/")
    else:
        rest = p.lstrip("./")
    seg = rest.split("/", 1)[0] if rest else ""
    if seg == "":
        return False
    return seg in scopes


def command_in_scope(cmd, scopes):
    oos = [r for r in _all_repos() if r not in scopes]
    for repo in oos:
        if re.search(rf"""(^|[\s/=:"'(]){re.escape(repo)}(/|[\s"')]|$)""", cmd):
            return False
    if WORKSPACE in cmd:
        after = cmd.split(WORKSPACE, 1)[1]
        if not any(after.lstrip("/").startswith(s) for s in scopes):
            return False
    return True


MODE = os.environ.get("HESTIA_CRUSH_GATE_MODE", "enforce").lower()


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

    # SOURCE-VERIFIED: Crush's stdin event field is `event`, not `hook_event_name`. Checking the wrong
    # field would exit 0 on every call and silently disarm. Accept either, require PreToolUse.
    evname = event.get("event") or event.get("hook_event_name")
    if evname != "PreToolUse":
        sys.exit(0)  # not our event

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("HESTIA_CRUSH_LAUNCH_CWD") or os.getcwd()
    scopes = dedupe(load_in_scope() + launch_cwd_repo())
    paths = path_targets(tinput)
    cmd = command_of(tinput)
    egress = egress_targets(tool, tinput)      # fetch/download url/prompt: Gate-1a only
    mcp_args = mcp_strings(tool, tinput)        # dynamic mcp__ args: Gate-1 was blind

    # Gate 1a - egress/secret innate invariant. Sweeps every channel a secret can leave by.
    for blob in paths + egress + mcp_args + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. File paths -> path-scope; shell command + MCP args -> command-scope. Egress
    # URLs are NOT realpath-scoped.
    if paths:
        if _shared_check_paths is not None:
            roots = [os.path.join(WORKSPACE, s) for s in scopes] + list(CRUSH_HOMES) + ["/tmp", "/var/tmp"]
            is_write = tool.lower() not in READ_CLASS and tool.lower() not in EGRESS_CLASS
            res = _shared_check_paths(paths, roots, cwd, for_write=is_write)
            if not res.allowed:
                deny(f"'{tool}': {res.reason}",
                     "Adjust to work within scope, or if legitimately needed, request it (request_scope).")
        else:
            for p in paths:
                if not path_in_scope(p, scopes):
                    deny(f"'{tool}' targets '{p[:60]}' outside your granted scope ({'+'.join(scopes)})",
                         "Adjust to work within scope, or if legitimately needed, request it (request_scope).")
    for c in ([cmd] if cmd is not None else []) + mcp_args:
        if not command_in_scope(c, scopes):
            where = "command" if c == cmd else "mcp argument"
            deny(f"'{tool}' {where} reaches outside your granted scope ({'+'.join(scopes)})",
                 "Scope it to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety. Local-read-class skips it; write/exec AND egress AND mcp need the
    # daemon's verdict; fail closed. The event is translated to the Claude lineage first.
    if tool.lower() not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="crush", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(to_claude_lineage(event, tool, tinput)),
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
