#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (AWS Kiro CLI) - reference adapter.

Kiro is CLAUDE-CODE LINEAGE in its gate semantics (events PreToolUse/PostToolUse/UserPromptSubmit/
Stop, `exit 2` blocks with stderr-as-reason, a `matcher` regex scopes a hook, engine FAILS OPEN) but
carries AMAZON Q DEVELOPER CLI heritage in its tool vocabulary - the builtin tools are `fs_read`,
`fs_write`, `execute_bash`, `use_aws`, NOT Claude's Read/Write/Bash. So this gate is closer to the
codex/kimi PreToolUse gate than to gemini's, with ONE gemini-borrowed necessity: a tool-name
translator, because the society-safety governor (plugins/claude-code) dispatches on Claude names.

Contract (agent-atlas talk-to/kiro_cli, DOCUMENTED tier - Kiro is a closed AWS product, not yet fired
live by this registry; sources: kiro.dev/docs/hooks, /docs/cli/hooks, custom-agents config-reference):
  - stdin JSON carries the Claude-lineage fields: `hook_event_name`, `tool_name`, `tool_input`, `cwd`,
    `session_id` (exact per-tool `tool_input` key names are Amazon-Q-documented, defensively widened).
  - Block: **exit 2**, STDERR returned to the agent as the reason. `matcher` regex scopes the hook.
  - FAILS OPEN: any exit code other than 0 or 2 shows a warning and lets the tool RUN; PostToolUse /
    PostTask* run after the fact and cannot block. Default hook timeout 30s.
  => FAIL-CLOSED BY CONSTRUCTION: only ever exit 0 (explicit confirmed allow) or 2 (deny, with text).
     Never exit on an odd code and never rely on a crash to deny - an uncaught Python exception exits 1,
     which is ALLOW here (the exact gemini live-repro that ran `rm -rf /`). main() wraps the gate in a
     top-level deny-on-exception so a crash fails CLOSED. This is the load-bearing lesson from the
     gemini adapter-tier pass, carried in from the start rather than found in review.

FIDELITY: documented-tier, NOT live-verified. The verified pass belongs on CBP's onboarding rig (an
installed `kiro` CLI). Because the gate is fail-closed, any wrong field-name/tool-name guess
over-blocks (safe), never silently allows. Kiro also supports MCP; the MCP transport arg shape is not
documented in the reviewed sources, so MCP args are swept as free-text string-leaves (Gate-1a) and the
call is treated as consequential (Gate-2) - covered conservatively, flagged for live confirmation.

Config (env-overridable):
  HESTIA_WORKSPACE       root holding the granted repos          (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE    society-safety governor to delegate to   (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_KIRO_IDENTITY   the member's live identity.json          (default: ~/.kiro/hestia-instance/identity.json)
  HESTIA_KIRO_GATE_MODE  warn | enforce  (default: enforce)
  HESTIA_KIRO_LAUNCH_CWD launch dir granted for the session       (default: cwd)
  HESTIA_FORBIDDEN_EXTRA comma-separated extra forbidden tokens
"""
import json
import os
import re
import sys
import subprocess

# Shared realpath-containment lib - the one implementation of Gate-1b across every adapter (../,
# symlink, absolute escapes that string-prefix logic cannot see). Falls back to the inline check if
# the lib is absent (partial checkout), which still denies the bare-root case.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
try:
    from path_scope import check_paths as _shared_check_paths  # type: ignore
except Exception:
    _shared_check_paths = None

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_KIRO_IDENTITY", "~/.kiro/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# Kiro/Amazon-Q LOCAL read-class tools (no write, no exec, no network/cloud) - may skip Gate-2.
# `fs_read` is Amazon Q's reader; the Claude-lineage names ride along as a defensive superset since
# Kiro's Claude heritage may surface them under some configs.
READ_CLASS = {"fs_read", "read", "read_file", "glob", "grep", "search_file_content", "list_directory"}

# Egress/cloud tools: `use_aws` makes an AWS API call - a cloud read OR write OR exfil channel, the
# irreversible direction. It is NOT a local filesystem write, so Gate-1b must not realpath it; but it
# MUST meet the governor (Gate-2) and have its arguments swept for secrets (Gate-1a).
EGRESS_CLASS = {"use_aws"}
KIRO_HOME = os.path.expanduser("~/.kiro")


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
    cwd = (os.environ.get("HESTIA_KIRO_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def _strings(v, depth=0):
    """Every string leaf of an arbitrarily-shaped value (bounded depth) - for use_aws.parameters and
    MCP argument objects whose shape is the tool's/server's, not ours."""
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
    """File-path args. Amazon-Q: fs_read/fs_write take `path`; search takes `pattern`. Defensive
    superset covers Claude-lineage names + list forms."""
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
    """execute_bash passes the command string under `command`."""
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(x) for x in c)
    return None


def cloud_targets(tool, tool_input):
    """use_aws arguments: service/operation/region/parameters. Swept by Gate-1a for secrets (an AWS
    call can carry a credential in its parameters, or name a secret resource), NOT by Gate-1b (an AWS
    ARN/service is not a local repo path). Only for the cloud/egress tool."""
    if tool.lower() not in EGRESS_CLASS or not isinstance(tool_input, dict):
        return []
    out = []
    for k in ("service_name", "operation_name", "region", "parameters", "label"):
        out.extend(_strings(tool_input.get(k)))
    return out


def dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Amazon-Q tool names -> the Claude-lineage names the society governor dispatches on. The governor
# extracts its target from file_path/path/url/notebook_path and only reads `command` when tool_name is
# in {"Bash","Shell"} - Kiro emits `execute_bash`, so an UNTRANSLATED handoff gives the governor
# target=None for every command (the same blindness the gemini pass found). Translate at the boundary.
LINEAGE_TOOL = {"fs_read": "Read", "fs_write": "Write", "execute_bash": "Shell",
                "use_aws": "Shell", "read": "Read", "grep": "Grep", "glob": "Glob"}
LINEAGE_ARG = {"absolute_path": "file_path", "dir_path": "path"}


def to_claude_lineage(event, tool, tinput):
    """Re-shape a Kiro PreToolUse event into the Claude-lineage shape the governor understands, lossless
    (original fields ride under `source_event`)."""
    out = dict(event)
    out["tool_name"] = LINEAGE_TOOL.get(tool.lower(), tool)
    if isinstance(tinput, dict):
        ti = {LINEAGE_ARG.get(k, k): v for k, v in tinput.items()}
        # use_aws has no `command`; give the governor a synthetic one so its exec check sees a target
        # instead of None, and preserve the structured call for witnessing.
        if tool.lower() == "use_aws" and "command" not in ti:
            ti["command"] = ("aws " + str(tinput.get("service_name") or "") + " " +
                             str(tinput.get("operation_name") or "")).strip()
        out["tool_input"] = ti
    out["source_event"] = {"lineage": "kiro", "tool_name": tool, "tool_input": tinput}
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
    if KIRO_HOME.lower() in low or "~/.kiro" in low:
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


MODE = os.environ.get("HESTIA_KIRO_GATE_MODE", "enforce").lower()


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

    if event.get("hook_event_name") != "PreToolUse":
        sys.exit(0)  # not our event

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("HESTIA_KIRO_LAUNCH_CWD") or os.getcwd()
    scopes = dedupe(load_in_scope() + launch_cwd_repo())
    paths = path_targets(tinput)
    cmd = command_of(tinput)
    cloud = cloud_targets(tool, tinput)  # use_aws args: Gate-1a only

    # Gate 1a - egress/secret innate invariant. Sweeps every channel a secret can leave by: file paths,
    # the shell command, use_aws arguments, and (conservatively) all string leaves for MCP-shaped calls.
    mcp_like = [] if (paths or cmd or cloud) else _strings(tinput)  # unknown-shape call -> sweep it
    for blob in paths + cloud + mcp_like + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. File paths -> path-scope; shell command -> command-scope. Cloud/egress args
    # are NOT realpath-scoped (an AWS service is not a local path).
    if paths:
        if _shared_check_paths is not None:
            roots = [os.path.join(WORKSPACE, s) for s in scopes] + [KIRO_HOME, "/tmp", "/var/tmp"]
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
    if cmd is not None and not command_in_scope(cmd, scopes):
        deny(f"'{tool}' command reaches outside your granted scope ({'+'.join(scopes)})",
             "Scope the command to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety (the governor). Local-read-class skips it; write/exec AND cloud egress
    # need the daemon's verdict; fail closed. The event is translated to the Claude lineage first.
    if tool.lower() not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="kiro-cli", HESTIA_PRE_FAIL_CLOSED="1")
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
    """Top-level deny-on-exception. Kiro FAILS OPEN and an uncaught Python exception exits 1, which is
    ALLOW (warning) - so a crashing fail-closed gate silently opens. SystemExit passes through (it
    carries the gate's real 0/2 verdict); anything else fails CLOSED. Carried from the gemini live-pass
    lesson (a non-string tool_name -> AttributeError -> exit 1 -> the tool ran)."""
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
