#!/usr/bin/env python3
"""Hestia Phase-1 PreToolUse GATE for a foreign member (AWS Kiro CLI) - reference adapter.

Kiro is CLAUDE-CODE LINEAGE in its gate semantics (events PreToolUse/PostToolUse/UserPromptSubmit/
Stop, `exit 2` blocks with stderr-as-reason, a `matcher` regex scopes a hook, engine FAILS OPEN) but
carries AMAZON Q DEVELOPER CLI heritage in its tool vocabulary - the builtin tools are `fs_read`,
`fs_write`, `execute_bash`, `use_aws`, NOT Claude's Read/Write/Bash. So the gate needs a tool-name
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
     top-level deny-on-exception so a crash fails CLOSED.

THE EVENT-FIELD NAME IS A GUESS, AND A WRONG GUESS DISARMS THE GATE ON EVERY CALL. Kiro's stdin
contract is documented-tier and unverified, and Crush is the existence proof that this field name
varies between engines (Crush uses `event`, not `hook_event_name`). The old code checked
`hook_event_name` only and exited 0 when it did not match - so on an engine that names the field
anything else, every tool call sailed through unexamined. gc.should_gate() now accepts either key,
and - stronger - gates an envelope carrying a `tool_name` even when no recognized event key is
present at all. Exiting 0 on an unrecognized envelope is the same class of fail-open as exiting 0 on
an unrecognized tool. (CBP KIRO-3, thread `harness-lane-split`.)

ENFORCEMENT LIVES IN `plugins/lib/gate_core.py`, not here. This file is the *vocabulary* plus Kiro's
engine semantics. Gate-1a, command-scope and lineage translation are shared with every other adapter
so a fix lands once - the review that prompted this found KIRO-1 and KIRO-2 to be holes the gemini
adapter had ALREADY closed, re-introduced by copying the logic instead of importing it.

UNKNOWN TOOLS ARE MAXIMALLY GATED. Anything absent from the tables below gets every string leaf swept
for secrets, every non-URL leaf command-scoped, and the governor's verdict required. Kiro is a closed
AWS product on a moving release train; drift is the expected case, and its failure mode is now
over-block rather than a silent channel.

FIDELITY: documented-tier, NOT live-verified. The verified pass belongs on CBP's onboarding rig (an
installed `kiro` CLI). Because the gate is fail-closed, a wrong field-name/tool-name guess over-blocks
(safe), never silently allows.

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
import sys
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
# A missing lib must fail CLOSED. An ImportError at module scope raises BEFORE main()'s
# deny-on-exception wrapper can catch it, and an uncaught exception exits 1 - which Kiro treats as a
# non-fatal warning and RUNS THE TOOL. So the import is guarded here, at the only place it can be.
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
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_KIRO_IDENTITY", "~/.kiro/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

FORBIDDEN = gc.FORBIDDEN_DEFAULT + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

KIRO_HOME = os.path.expanduser("~/.kiro")
# `/tmp` and `/var/tmp` are blanket in-scope roots. DELIBERATE, not inherited: they are the scratch
# space and the cross-member hand-off channel. Flagged in review; keeping it as a decision.
TMP_ROOTS = ["/tmp", "/var/tmp"]

# ---------------------------------------------------------------------------
# VOCABULARY - the only per-engine part. Amazon Q Developer CLI builtin tools.
# Anything NOT listed here classifies as UNKNOWN and is gated hardest.
# ---------------------------------------------------------------------------
VOCAB = gc.Vocabulary(
    # LOCAL read-class (no write, no exec, no network/cloud) - the ONLY class that may skip Gate-2.
    # `fs_read` is Amazon Q's reader; the Claude-lineage names ride along as a defensive superset
    # since Kiro's Claude heritage may surface them under some configs.
    read=("fs_read", "read", "read_file", "glob", "grep", "search_file_content", "list_directory"),
    write=("fs_write", "write", "edit"),
    exec_=("execute_bash", "execute_cmd"),
    # `use_aws` makes an AWS API call - a cloud read OR write OR exfil channel, the irreversible
    # direction. NOT a local filesystem write (Gate-1b must not realpath an ARN), but it MUST meet
    # the governor and have EVERY argument leaf swept. The old key whitelist
    # (service_name/operation_name/region/parameters/label) missed `profile_name`, a real use_aws
    # parameter, so a secret there went unswept. Sweeping leaves rather than guessed keys removes
    # the schema-guess dependency permanently. (CBP KIRO-4)
    egress=("use_aws",),
    mcp_prefixes=("mcp",),
    mcp_tools=("read_mcp_resource", "list_mcp_resources"),
    path_keys=("path", "file_path", "absolute_path", "notebook_path", "pattern", "dir_path"),
    list_path_keys=("paths", "file_paths", "include", "exclude"),
    uri_keys=("uri", "resource_uri"),
    cmd_keys=("command",),
    # Amazon-Q names -> the Claude-lineage names the governor dispatches on. The governor extracts
    # its target from file_path/path/url/notebook_path and only reads `command` when tool_name is in
    # {"Bash","Shell"} - Kiro emits `execute_bash`, so an UNTRANSLATED handoff gives the governor
    # target=None for every command (the same blindness the gemini pass found).
    lineage_tool={"fs_read": "Read", "fs_write": "Write", "execute_bash": "Shell",
                  "execute_cmd": "Shell", "use_aws": "Shell", "read": "Read",
                  "grep": "Grep", "glob": "Glob"},
    lineage_arg={"absolute_path": "file_path", "dir_path": "path"},
)

MODE = os.environ.get("HESTIA_KIRO_GATE_MODE", "enforce").lower()


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


def deny(reason, what_to_do, innate=False):
    if innate or MODE == "enforce":
        sys.stderr.write(
            f"hestia: deny [scope] - {reason}. This is a boundary, not a failure: don't re-run the "
            f"same call. {what_to_do} Asking is a trust-building act; reaching is witnessed.\n")
        sys.exit(2)
    sys.stderr.write(f"hestia: warn [scope] - {reason} (warn-rollout: allowed; would block under enforce)\n")


def to_lineage(event, tool, tinput):
    """Kiro-specific addendum to the shared translation: `use_aws` has no `command`, so synthesise
    one from the structured call - otherwise the governor's exec check sees target=None."""
    out = gc.to_claude_lineage(event, tool, tinput, VOCAB, lineage_name="kiro")
    if tool.lower() == "use_aws" and isinstance(out.get("tool_input"), dict) \
            and "command" not in out["tool_input"]:
        ti = tinput if isinstance(tinput, dict) else {}
        out["tool_input"]["command"] = ("aws " + str(ti.get("service_name") or "") + " " +
                                        str(ti.get("operation_name") or "")).strip()
    return out


def _gate():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] - could not parse the tool event; failing closed.\n")
        sys.exit(2)

    # Accepts `hook_event_name` OR `event`, and gates an unrecognized envelope that still carries a
    # tool_name rather than exiting 0 on it. See the module docstring - this is the one place the
    # gate could silently disarm on every call.
    if not gc.should_gate(event):
        sys.exit(0)

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("HESTIA_KIRO_LAUNCH_CWD") or os.getcwd()
    scopes = gc.dedupe(load_in_scope() + launch_cwd_repo())

    p = gc.plan(tool, tinput, VOCAB)

    # Gate 1a - egress/secret innate invariant. Sweeps every channel a secret can leave by. For an
    # MCP/unknown/egress call that is EVERY string leaf - the old code made this an else-branch
    # (`[] if (paths or cmd or cloud) else _strings(...)`), so one recognized key disarmed the sweep
    # for the whole rest of the object. It is a union, never an else. (CBP KIRO-1)
    for blob in p.gate1a:
        hit = gc.forbidden_hit(blob, FORBIDDEN)
        if hit:
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. Local paths -> realpath containment. Cloud/network endpoints are NOT
    # realpath-scoped (an AWS ARN is not a local path); gc.as_local_path() has already dropped them.
    if p.paths:
        roots = [os.path.join(WORKSPACE, s) for s in scopes] + [KIRO_HOME] + TMP_ROOTS
        res = _shared_check_paths(p.paths, roots, cwd, for_write=p.for_write)
        if not res.allowed:
            deny(f"'{tool}': {res.reason}",
                 "Adjust to work within scope, or if legitimately needed, request it (request_scope).")

    # Command-scope: the shell command AND every non-URL argument leaf of an MCP/unknown/egress
    # call. The old code checked `cmd` only, so an MCP argument naming an out-of-scope repo passed
    # (crush already command-scoped its MCP args; this is the drift). (CBP KIRO-2)
    for c in p.cmd_scope:
        if not gc.command_in_scope(c, scopes, WORKSPACE):
            where = "command" if c == (tinput.get("command") if isinstance(tinput, dict) else None) \
                else f"{p.klass} argument"
            deny(f"'{tool}' {where} reaches outside your granted scope ({'+'.join(scopes)})",
                 "Scope it to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety (the governor). Local-read-class skips it; write/exec AND cloud egress
    # AND mcp AND every UNKNOWN tool need the daemon's verdict; fail closed.
    if p.needs_gate2:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="kiro-cli", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, CLAUDE_PRE],
                               input=json.dumps(to_lineage(event, tool, tinput)),
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
