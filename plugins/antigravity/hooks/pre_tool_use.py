#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (Google Antigravity CLI / `agy`) - reference adapter.

Antigravity is Google's CLOSED-SOURCE successor to gemini-cli (it herds individuals off gemini-cli's
now-deprecated free OAuth). Its hook engine is gemini-LINEAGE but the wire contract is INVERTED in the
two ways that matter, so this adapter is the gemini gate with its output and failure model flipped:

  1. EVENT RENAMED: gemini's `BeforeTool` -> Antigravity's **`PreToolUse`**.
  2. OUTPUT is a STDOUT DECISION OBJECT, not exit-code+stderr. The hook reads JSON on stdin and writes
     a JSON object on stdout: `{"decision": "allow"|"deny", "reason": ...}`. Allow = emit
     `{"decision":"allow"}` (or `{}`) and exit 0.
  3. IT FAILS **CLOSED** (the inversion of gemini). A hook that errors, times out, or exits non-zero is
     read as **DENY** (verified behavior: manaflow-ai/cmux #4768/#5358 - a hook whose backend was down
     exited non-zero and `agy` blocked EVERY tool call, unusable). Contrast gemini-cli, which fails
     OPEN.

The design consequence of (3) is the OPPOSITE risk from gemini. Gemini's danger was crash -> ALLOW, so
that gate carried a deny-on-exception. Antigravity's danger is crash/slow/over-strict -> BLOCK
EVERYTHING, so this gate's imperatives are: (a) emit a CLEAN explicit verdict (stdout JSON + exit 0) on
BOTH paths so a deny carries a readable reason instead of `agy`'s generic hook-failure block; (b) be
ROBUST and FAST on the happy path so it never spuriously denies legitimate work; (c) STILL fail closed
on genuine inability to vouch (a security gate denies on doubt) - but via an explicit
`{"decision":"deny", reason:...}`, with the engine's implicit non-zero=deny only as a backstop.
This is also the clean deny-UX that gemini's exit-2 path could not give (gemini surfaced a scary
"[WARNING] Hook failed"); here a deny is a first-class decision object.

FIDELITY: documented-tier, NOT live-verified. Antigravity is closed-source, so the contract is from its
docs + the cmux issue threads + the gemini lineage, not source. The exact `tool_input` arg/tool names
are assumed gemini-shaped (read_file/run_shell_command/web_fetch/mcp_context) and defensively widened.
CAUTION specific to a FAIL-CLOSED engine: an over-strict guess here BLOCKS work (it does not merely
over-deny-safely as on gemini), so the live pass must confirm normal `agy` events parse and ALLOW
cleanly, not just that denies deny. Config lives at `~/.gemini/config/hooks.json` (agy reuses the
~/.gemini tree; plugins stage under ~/.gemini/antigravity-cli/).

Config (env-overridable):
  HESTIA_WORKSPACE      root holding the granted repos      (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE   society-safety governor              (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_AGY_IDENTITY   the member's live identity.json      (default: ~/.gemini/antigravity-cli/hestia-instance/identity.json)
  HESTIA_AGY_GATE_MODE  warn | enforce  (default: enforce)
  HESTIA_AGY_LAUNCH_CWD launch dir granted for the session   (default: cwd)
  HESTIA_FORBIDDEN_EXTRA comma-separated extra forbidden tokens
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
    "HESTIA_AGY_IDENTITY", "~/.gemini/antigravity-cli/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# gemini-lineage LOCAL read-class tools (no write, no exec, no network) - may skip Gate-2.
READ_CLASS = {"read_file", "read_many_files", "glob", "search_file_content", "list_directory"}
# Network egress tools - read the network (the irreversible direction); must meet Gate-2 + Gate-1a.
EGRESS_CLASS = {"google_web_search", "web_fetch"}
# agy reuses the gemini home tree; its own state lives under ~/.gemini/antigravity-cli.
AGY_HOMES = (os.path.expanduser("~/.gemini"),)


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
    cwd = (os.environ.get("HESTIA_AGY_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
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
    out = []
    if isinstance(tool_input, dict):
        for k in ("path", "file_path", "absolute_path", "notebook_path", "pattern", "dir_path"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
        for k in ("paths", "file_paths", "include", "exclude"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str))
    return out


def command_of(tool_input):
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(x) for x in c)
    return None


def egress_targets(tool_input):
    out = []
    if isinstance(tool_input, dict):
        for k in ("url", "urls", "prompt", "query"):
            out.extend(_strings(tool_input.get(k)))
    return out


def mcp_strings(mcp):
    if not isinstance(mcp, dict):
        return []
    return _strings(mcp.get("command")) + _strings(mcp.get("args")) + _strings(mcp.get("cwd"))


def mcp_egress(mcp):
    if not isinstance(mcp, dict):
        return []
    return _strings(mcp.get("url"))


def dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# gemini-lineage tool names -> the Claude-lineage names the society governor dispatches on.
LINEAGE_TOOL = {"run_shell_command": "Shell", "write_file": "Write", "replace": "Edit",
                "read_file": "Read", "read_many_files": "Read", "glob": "Glob",
                "search_file_content": "Grep", "list_directory": "Read",
                "web_fetch": "WebFetch", "google_web_search": "WebSearch"}
LINEAGE_ARG = {"absolute_path": "file_path", "dir_path": "path"}


def to_claude_lineage(event, tool, tinput, mcp):
    out = dict(event)
    if mcp and isinstance(mcp.get("server_name"), str):
        out["tool_name"] = f"mcp__{mcp['server_name']}__{mcp.get('tool_name') or '?'}"
        out["mcp_server_command"] = " ".join(
            [str(mcp.get("command") or "")] + [str(a) for a in (mcp.get("args") or [])]).strip()
    else:
        out["tool_name"] = LINEAGE_TOOL.get(tool.lower(), tool)
    if isinstance(tinput, dict):
        ti = {LINEAGE_ARG.get(k, k): v for k, v in tinput.items()}
        if "file_path" not in ti and "path" not in ti:
            inc = tinput.get("include")
            if isinstance(inc, list) and inc and isinstance(inc[0], str):
                ti["path"] = inc[0]
        if "url" not in ti:
            m = re.search(r"https?://[^\s\"'<>)]+", str(tinput.get("prompt") or ""))
            if m:
                ti["url"] = m.group(0)
        if "url" not in ti and mcp and isinstance(mcp.get("url"), str) and mcp["url"]:
            ti["url"] = mcp["url"]
        out["tool_input"] = ti
    out["source_event"] = {"lineage": "antigravity", "tool_name": tool, "tool_input": tinput,
                           "mcp_context": mcp}
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
    if any(h.lower() in low for h in AGY_HOMES) or "~/.gemini" in low:
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


MODE = os.environ.get("HESTIA_AGY_GATE_MODE", "enforce").lower()


# --- OUTPUT: the inversion. Antigravity reads a stdout decision object; emit an EXPLICIT verdict on
# both paths (exit 0) so a deny is a clean, reasoned decision, not the engine's generic hook-failure
# block. All three helpers exit the process. ---
def _emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()
    sys.exit(0)


def allow():
    _emit({"decision": "allow"})


def deny(reason, what_to_do, innate=False):
    if innate or MODE == "enforce":
        _emit({"decision": "deny", "reason": (
            f"hestia: deny [scope] - {reason}. This is a boundary, not a failure: don't re-run the "
            f"same call. {what_to_do} Asking is a trust-building act; reaching is witnessed.")})
    # warn-rollout: allow, but carry the would-block note back to the model.
    _emit({"decision": "allow",
           "reason": f"hestia: warn [scope] - {reason} (warn-rollout: allowed; would block under enforce)"})


def deny_safety(msg):
    if MODE == "enforce":
        _emit({"decision": "deny", "reason": msg})
    _emit({"decision": "allow",
           "reason": "hestia: warn [safety] - " + msg.split("- ", 1)[-1] +
                     " (warn-rollout: allowed; would block under enforce)"})


def _gate():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        # Fail closed, but EXPLICITLY (a clean reasoned deny beats the engine's generic block).
        _emit({"decision": "deny",
               "reason": "hestia: deny [gate] - could not parse the tool event; failing closed."})

    if event.get("hook_event_name") != "PreToolUse":
        allow()  # not our event -> no-op allow (do not block non-tool events)

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    mcp = event.get("mcp_context") if isinstance(event.get("mcp_context"), dict) else None
    cwd = event.get("cwd") or os.environ.get("HESTIA_AGY_LAUNCH_CWD") or os.getcwd()
    scopes = dedupe(load_in_scope() + launch_cwd_repo())
    paths = path_targets(tinput)
    cmd = command_of(tinput)
    egress = egress_targets(tinput) + mcp_egress(mcp)
    mcp_args = mcp_strings(mcp)

    # Gate 1a - egress/secret innate invariant (always enforced).
    for blob in paths + egress + mcp_args + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope.
    if paths:
        if _shared_check_paths is not None:
            roots = [os.path.join(WORKSPACE, s) for s in scopes] + list(AGY_HOMES) + ["/tmp", "/var/tmp"]
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
            where = "command" if c == cmd else "mcp_context argument"
            deny(f"'{tool}' {where} reaches outside your granted scope ({'+'.join(scopes)})",
                 "Scope it to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety. Local-read-class skips it; write/exec AND egress need the daemon; fail closed.
    if tool.lower() not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="antigravity-cli", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(to_claude_lineage(event, tool, tinput, mcp)),
                               capture_output=True, text=True, timeout=6, env=env)
            if r.returncode != 0:
                msg = (r.stderr.strip() if r.returncode == 2 and r.stderr.strip()
                       else "hestia: deny [safety] - blocked/inconclusive at the society safety gate.")
                deny_safety(msg)
        except Exception:
            deny_safety("hestia: deny [safety] - could not reach the governor; failing closed on a "
                        "consequential act.")

    allow()  # the ONLY clean-allow path - reached only after every gate explicitly passed


def main():
    """Top-level guard. Antigravity fails CLOSED (non-zero exit / hook error = DENY), so a crash already
    blocks - but blocks with the engine's generic "hook failed" message. Convert any crash into an
    EXPLICIT reasoned deny (stdout decision + exit 0) so the block is legible; the engine's implicit
    non-zero=deny remains the backstop if even this emit fails. SystemExit passes through (it carries a
    helper's real emitted verdict)."""
    try:
        _gate()
    except SystemExit:
        raise
    except BaseException as exc:
        try:
            sys.stdout.write(json.dumps({"decision": "deny", "reason": (
                f"hestia: deny [gate] - the gate crashed ({type(exc).__name__}: {str(exc)[:200]}) and "
                f"cannot vouch for this call; failing closed. This is a boundary, not a failure.")}))
            sys.stdout.flush()
        finally:
            sys.exit(0)


if __name__ == "__main__":
    main()
