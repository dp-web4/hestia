#!/usr/bin/env python3
"""Hestia Phase-1 BeforeTool GATE for a foreign member (Google Gemini CLI) - reference adapter.

Adapted from the Codex/Kimi reference gates. Gemini's hook engine is INDEPENDENT lineage (its own
Before*/After* event vocabulary), but its wire protocol is concept-parallel to the Claude lineage
and, per Google's official hooks reference, near-identical in the fields this gate needs:

  - Base stdin JSON carries `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`.
  - `BeforeTool` adds `tool_name` (string) and `tool_input` (object, the raw model arguments).
  - Exit-code contract (SOURCE-VERIFIED from packages/core/src/hooks/hookRunner.ts@main,
    convertPlainTextToHookOutput L537-560 + close-handler L434-506; NOT just the docs):
      * exit 0  -> {decision:'allow'}                         (allow)
      * exit 1  (EXIT_CODE_NON_BLOCKING_ERROR) -> {decision:'allow', systemMessage:'Warning: '+text}
                (a NON-blocking warning: the tool STILL RUNS - exit 1 is NOT a block)
      * exit 2 or any other non-zero -> {decision:'deny', reason:text}   (BLOCK)
      * timeout (default 60000ms, L36) or spawn error -> success:false, NO output -> FAIL OPEN
    So the ONLY fail-open surface is a TIMEOUT or spawn error (hence CBP's ext4-not-/mnt/c note: a 9p
    cold-load that exceeds the hook timeout fails open). A running gate that exits 2+ blocks.
  - CRITICAL: a block requires EMITTED TEXT. The runner parses `stdout.trim() || stderr.trim()`
    (L455); on exit 2 with EMPTY output, `output` is undefined and the call is NOT denied. So this
    gate ALWAYS writes a reason to stderr before `exit 2` (see deny() and every exit-2 path). A stdout
    JSON `{"decision":"deny","reason":...}` at exit 0 would also block (L459-467), but exit-2+stderr
    is simpler and used here.

This gate is therefore FAIL-CLOSED BY CONSTRUCTION: it only ever exits 0 (explicit confirmed allow) or
2 (deny, with text). It never exits 1, so it never emits an allow-with-warning by accident. That last
claim is only true because main() wraps the whole gate in a deny-on-exception - an uncaught Python
exception exits 1, which the engine reads as ALLOW. See main().

FIDELITY NOTE (2026-07-22): the exit-code/deny/fail-open contract above is SOURCE-verified (file+lines
cited) AND now LIVE-VERIFIED by CBP against an installed gemini-cli 0.52.0 with real model
round-trips (forum/cbp-to-nomad-gemini-hook-contract-LIVE-VERIFIED-2026-07-22.md). Live additions:
  - hook deny beats `--approval-mode yolo` - the hook layer sits before the policy engine;
  - MCP calls fire BeforeTool as `mcp_<server>_<tool>` AND carry an `mcp_context` object
    ({server_name, tool_name, command, args}) - use those fields, not string-parsing (see
    to_claude_lineage);
  - `hooksConfig.enabled` defaults true but is a one-line kill-switch: install docs must pin it.
The per-tool `tool_input` arg names are source-read from `tools/definitions/base-declarations.ts`
(notably read_many_files = `include`/`exclude`, NOT `paths`) plus a defensive superset - because the
gate is fail-closed, an unrecognized shape over-blocks (safe).
ADAPTER-TIER LIVE PASS (CBP, 2026-07-22, forum/cbp-to-nomad-gemini-adapter-review-LIVE-VERIFIED-*):
this gate was wired in as gemini-cli 0.52.0's real BeforeTool hook and fired with model round-trips.
In-scope read allowed; out-of-scope read, ../ traversal, symlink escape, absolute oos, oos shell
command, governor deny, and malformed JSON all denied exit 2 with the reason surfaced to the model.
Confirmed live: read_file -> `file_path` (absolute), run_shell_command -> `command`. The pass also
found the two holes closed here (ungated web_fetch egress; mcp_context unread by Gate-1). RE-FIRE
(CBP, 2026-07-22, ...-LIVE-VERIFIED-re-fire-*): both verified live against 7e2d8f4; follow-on note
folded in here - an HTTP/SSE MCP server's `url`/`cwd` (no command/args) is the same egress class,
now swept by mcp_egress()/mcp_strings() and lifted into the governor handoff.
Also live: gemini-cli natively confines FILE tools to the launch dir (+ --include-directories) and
refuses .env - so for file paths this gate is layer 2. Shell, MCP and web egress have NO native
layer, i.e. this gate is the ONLY thing between the model and them. That is the hardening priority.
Gemini also has a NATIVE policy engine (docs/reference/policy-engine.md) + BeforeToolSelection/
BeforeModel events; those are complementary (this gate is the BeforeTool scope+safety layer we own),
not reinvented here.

Config (all env-overridable; defaults suit a generic install):
  HESTIA_WORKSPACE         root that contains the granted repos       (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE      path to the society-safety gate caller      (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_GEMINI_IDENTITY   the member's live identity.json             (default: ~/.gemini/hestia-instance/identity.json)
  HESTIA_GEMINI_GATE_MODE  warn | enforce   (default: enforce - deny-tight, relax as trust accrues)
  HESTIA_GEMINI_LAUNCH_CWD launch dir granted for the session          (default: os.getcwd())
  HESTIA_FORBIDDEN_EXTRA   comma-separated extra forbidden path tokens (e.g. your private repo names)
"""
import json
import os
import re
import sys
import subprocess

# Shared realpath-containment lib (hestia/plugins/lib/path_scope.py) - the one implementation of
# Gate-1b, so every adapter's scope check is identical and hardened against ../ / symlink / absolute
# escapes that string-prefix logic cannot see. This gemini gate is its first adopter; if it is absent
# (partial checkout), we fall back to the inline string check, which still denies the bare-root case.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
try:
    from path_scope import check_paths as _shared_check_paths  # type: ignore
except Exception:
    _shared_check_paths = None

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_GEMINI_IDENTITY", "~/.gemini/hestia-instance/identity.json"))
CLAUDE_PRE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

# Innate egress/secret invariants - denied even inside a granted repo. Trust never relaxes these (S1).
FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# Gemini builtin LOCAL read-class tools (no write, no exec, no network) - they may skip Gate-2.
READ_CLASS = {"read_file", "read_many_files", "glob", "search_file_content", "list_directory"}

# Egress tools. These READ, but they read the *network* - and egress is the irreversible direction
# (a prompt-injected `web_fetch` is exfiltration). They were in READ_CLASS, which skipped Gate-2, so
# on gemini - which has no sandbox behind the gate - egress never met the governor at all.
# They are NOT writes to the filesystem, so Gate-1b must not treat them as such (see for_write below).
EGRESS_CLASS = {"google_web_search", "web_fetch"}

# The agent's own home is always in scope (state, identity, config).
GEMINI_HOME = os.path.expanduser("~/.gemini")


def load_in_scope():
    """Gemini's granted MRH (repos it may touch), read from its identity - per-entity, role-sourced."""
    try:
        mrh = json.load(open(IDENTITY, encoding="utf-8")).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]  # "repo:web4" -> "web4"
    except Exception:
        pass
    return ["web4"]


def launch_cwd_repo():
    """The repo Gemini is launched in is always in scope - a per-launch dynamic grant on top of the
    static allowlist, so a task-specific launch dir is reachable for that session without widening
    the standing grant."""
    cwd = (os.environ.get("HESTIA_GEMINI_LAUNCH_CWD") or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def path_targets(tool_input):
    out = []
    if isinstance(tool_input, dict):
        # superset of Gemini builtin file-arg names (read_file/write_file/replace/glob/...)
        for k in ("path", "file_path", "absolute_path", "notebook_path", "pattern", "dir_path"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
        # read_many_files takes `include`/`exclude` GLOBS, not `paths` (SOURCE-VERIFIED:
        # tools/definitions/base-declarations.ts). Scanning only paths/file_paths skipped Gate-1b
        # for this tool entirely - an out-of-scope `include:["../private-context/**"]` was ALLOWED.
        # `paths`/`file_paths` stay as a defensive superset (other/future tools, harmless if absent).
        for k in ("paths", "file_paths", "include", "exclude"):
            v = tool_input.get(k)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str))
    return out


def command_of(tool_input):
    """Gemini's run_shell_command passes the command string under tool_input.command."""
    if isinstance(tool_input, dict):
        c = tool_input.get("command")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(x) for x in c)
    return None


def _strings(v, depth=0):
    """Every string leaf of an arbitrarily-shaped value (bounded depth). Used to sweep free-text and
    MCP argument objects, whose shape is the *server's*, not ours - we cannot enumerate their keys."""
    if isinstance(v, str):
        return [v]
    if depth > 4:
        return []
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x, depth + 1)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x, depth + 1)]
    return []


def egress_targets(tool_input):
    """The network tools' arguments: `url` (web_fetch), free-text `prompt`, `query`.

    These must be swept by Gate-1a - a secret is laundered out *inside* a URL or a prompt, and the
    GEMINI.md promise ("you cannot launder a secret out through ... a web fetch") is only true if the
    innate denylist actually looks at them. They must NOT be fed to Gate-1b: realpath containment on
    `https://...` resolves under cwd and would deny every fetch, so egress rests on Gate-1a + Gate-2.
    """
    out = []
    if isinstance(tool_input, dict):
        for k in ("url", "urls", "prompt", "query"):
            out.extend(_strings(tool_input.get(k)))
    return out


def mcp_strings(mcp):
    """The MCP transport surface: `mcp_context` = {server_name, tool_name, command, args}.

    An `mcp_<server>_<tool>` call's `tool_input` is the *server's* argument object, so path_targets()
    and command_of() see nothing they recognize - Gate-1a and command-scope were blind to MCP
    arguments entirely (live-confirmed by CBP 2026-07-22: an out-of-scope path inside
    `mcp_context.args` passed Gate-1). Sweep the transport command and every string leaf of args.
    """
    if not isinstance(mcp, dict):
        return []
    # `cwd` is the server's launch dir - a real local path, so it belongs to command/path scope
    # alongside command+args. `url` does NOT: it's a network endpoint (see mcp_egress), scoping it
    # against local repo names only mis-fires. LIVE-VERIFIED shape carries cwd/url on HTTP/SSE servers.
    return _strings(mcp.get("command")) + _strings(mcp.get("args")) + _strings(mcp.get("cwd"))


def mcp_egress(mcp):
    """An HTTP/SSE MCP server is reached by `url` (extractMcpContext: `serverConfig.url ?? httpUrl`),
    carrying NO command/args - a live egress surface with the same shape as web_fetch's url. A member
    pointed at an out-of-scope HTTP MCP endpoint would otherwise sail past Gate-1 entirely (CBP note,
    2026-07-22). Swept by Gate-1a for secrets and handed to the governor; NOT command-scoped, because
    a URL is not a local path and repo-name matching on it only produces false denies."""
    if not isinstance(mcp, dict):
        return []
    return _strings(mcp.get("url"))


def dedupe(seq):
    """Order-preserving unique. `scopes` is identity-grant + launch-cwd-grant, which collide whenever
    the member is launched inside a repo it already holds - live denies printed "scope (web4+web4)"
    and listed the same root twice in the path_scope reason."""
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Gemini's event vocabulary -> the Claude-lineage names the society gate dispatches on. The governor
# (plugins/claude-code/hooks/pre_tool_use.py) extracts its target from `file_path`/`path`/`url`/
# `notebook_path`, and only reads `command` when tool_name is in {"Bash","Shell"}. Gemini emits none
# of those names, so an UNTRANSLATED handoff gave the governor target=None for every shell command -
# it was consulted, but blind. Translate at the boundary; the gate stays the lineage adapter.
LINEAGE_TOOL = {"run_shell_command": "Shell", "write_file": "Write", "replace": "Edit",
                "read_file": "Read", "read_many_files": "Read", "glob": "Glob",
                "search_file_content": "Grep", "list_directory": "Read",
                "web_fetch": "WebFetch", "google_web_search": "WebSearch"}
LINEAGE_ARG = {"absolute_path": "file_path", "dir_path": "path"}


def to_claude_lineage(event, tool, tinput, mcp):
    """Re-shape a Gemini BeforeTool event into the Claude-lineage shape the governor understands.

    Kept lossless: the original gemini fields ride along under `source_event` so the daemon can
    witness what actually happened, and `mcp_context` (LIVE-VERIFIED present on gemini 0.52.0 MCP
    calls, CBP 2026-07-22) is used for MCP naming instead of parsing `mcp_<server>_<tool>` - the
    string form is ambiguous when a server or tool name itself contains an underscore.
    """
    out = dict(event)
    if mcp and isinstance(mcp.get("server_name"), str):
        out["tool_name"] = f"mcp__{mcp['server_name']}__{mcp.get('tool_name') or '?'}"
        # command+args are the server's real egress surface - hand them to the governor explicitly.
        out["mcp_server_command"] = " ".join(
            [str(mcp.get("command") or "")] + [str(a) for a in (mcp.get("args") or [])]).strip()
    else:
        out["tool_name"] = LINEAGE_TOOL.get(tool.lower(), tool)
    if isinstance(tinput, dict):
        ti = {LINEAGE_ARG.get(k, k): v for k, v in tinput.items()}
        # `include` is a glob LIST; the governor wants one string target.
        if "file_path" not in ti and "path" not in ti:
            inc = tinput.get("include")
            if isinstance(inc, list) and inc and isinstance(inc[0], str):
                ti["path"] = inc[0]
        # web_fetch carries its URLs INSIDE the free-text `prompt`; lift the first one to `url` so the
        # governor's egress check sees a real target instead of None. The prompt is preserved as-is.
        if "url" not in ti:
            m = re.search(r"https?://[^\s\"'<>)]+", str(tinput.get("prompt") or ""))
            if m:
                ti["url"] = m.group(0)
        # An HTTP/SSE MCP server has no command/args - its egress target is `mcp_context.url`. Lift it
        # so the governor sees a real url instead of None (same fix as run_shell_command's target).
        if "url" not in ti and mcp and isinstance(mcp.get("url"), str) and mcp["url"]:
            ti["url"] = mcp["url"]
        out["tool_input"] = ti
    out["source_event"] = {"lineage": "gemini", "tool_name": tool, "tool_input": tinput,
                           "mcp_context": mcp}
    return out


def _all_repos():
    try:
        return [d for d in os.listdir(WORKSPACE)
                if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith(".")]
    except Exception:
        return []


def path_in_scope(path, scopes):
    """A file path is in-scope if it's the agent's home, /tmp, or under a granted repo."""
    p = path.replace("\\", "/")
    low = p.lower()
    if GEMINI_HOME.lower() in low or "~/.gemini" in low:
        return True
    if p.startswith(("/tmp", "/var/tmp")):
        return True
    if WORKSPACE in p:
        rest = p.split(WORKSPACE, 1)[1].lstrip("/")
    else:
        rest = p.lstrip("./")
    seg = rest.split("/", 1)[0] if rest else ""
    if seg == "":
        return False           # bare workspace root (the glob-the-root antipattern) -> out of scope
    return seg in scopes


def command_in_scope(cmd, scopes):
    """A shell command is out of scope if it names an out-of-scope repo, or globs the workspace root
    without narrowing to a granted repo. (Relative-recursive traversal from a broad cwd escapes
    string-parsing - launch Gemini in the specific task repo, not the workspace root.)"""
    oos = [r for r in _all_repos() if r not in scopes]
    for repo in oos:
        if re.search(rf"""(^|[\s/=:"'(]){re.escape(repo)}(/|[\s"')]|$)""", cmd):
            return False
    if WORKSPACE in cmd:
        after = cmd.split(WORKSPACE, 1)[1]
        if not any(after.lstrip("/").startswith(s) for s in scopes):
            return False
    return True


# Rollout mode: DENY-TIGHT by default - a foreign agent starts enforced and RELAXES as role-scoped
# trust accrues (defensive trust: start at zero, earn the widening). Egress/secret is `innate` -
# always blocks regardless of mode. Set warn via HESTIA_GEMINI_GATE_MODE=warn only while shaking down.
MODE = os.environ.get("HESTIA_GEMINI_GATE_MODE", "enforce").lower()


def deny(reason, what_to_do, innate=False):
    """innate=True -> ALWAYS blocks (egress/secret is irreversible). Tunable rules honor MODE."""
    if innate or MODE == "enforce":
        sys.stderr.write(
            f"hestia: deny [scope] - {reason}. This is a boundary, not a failure: don't re-run the "
            f"same call. {what_to_do} Asking is a trust-building act; reaching is witnessed.\n")
        sys.exit(2)
    sys.stderr.write(f"hestia: warn [scope] - {reason} (warn-rollout: allowed; would block under enforce)\n")


def _gate():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] - could not parse the tool event; failing closed.\n")
        sys.exit(2)

    if event.get("hook_event_name") != "BeforeTool":
        sys.exit(0)  # not our event

    raw_tool = event.get("tool_name")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "?"
    tinput = event.get("tool_input") or {}
    mcp = event.get("mcp_context") if isinstance(event.get("mcp_context"), dict) else None
    cwd = event.get("cwd") or os.environ.get("HESTIA_GEMINI_LAUNCH_CWD") or os.getcwd()
    scopes = dedupe(load_in_scope() + launch_cwd_repo())
    paths = path_targets(tinput)
    cmd = command_of(tinput)
    egress = egress_targets(tinput) + mcp_egress(mcp)  # url/prompt/query + HTTP-MCP url: Gate-1a only
    mcp_args = mcp_strings(mcp)          # the MCP transport surface Gate-1 could not see (command+args+cwd)

    # Gate 1a - egress/secret innate invariant (denied even inside a granted repo). ALWAYS enforced.
    # The sweep covers every channel a secret can leave by: file paths, the shell command, the
    # network tools' url/prompt/query, and MCP arguments. Anything added here must be added there.
    for blob in paths + egress + mcp_args + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' names a forbidden target (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. File paths use path-scope; shell commands use command-scope.
    if paths:
        if _shared_check_paths is not None:
            # Hardened realpath containment via the shared lib. Roots = granted repos + agent home +
            # tmp, all absolute. It denies ../ / symlink / absolute escapes that the string check can't.
            roots = [os.path.join(WORKSPACE, s) for s in scopes] + [GEMINI_HOME, "/tmp", "/var/tmp"]
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
    # Command-scope covers the shell command AND the MCP transport (its command + args are a real
    # exec surface: an oos root handed to a filesystem server is an oos read the file gates never see).
    for c in ([cmd] if cmd is not None else []) + mcp_args:
        if not command_in_scope(c, scopes):
            where = "command" if c == cmd else "mcp_context argument"
            deny(f"'{tool}' {where} reaches outside your granted scope ({'+'.join(scopes)})",
                 "Scope it to a granted repo, or if legitimately needed, request it (request_scope).")

    # Gate 2 - society safety (the governor). Local-read-class skips it; write/exec AND EGRESS need
    # the daemon's verdict; fail closed.
    if tool.lower() not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="gemini-cli", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(to_claude_lineage(event, tool, tinput, mcp)),
                               capture_output=True, text=True, timeout=6, env=env)
            if r.returncode != 0:  # daemon denied, or inconclusive -> fail-closed for a write/exec act
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
    """Top-level deny-on-exception.

    LIVE-VERIFIED (CBP, gemini-cli 0.52.0, 2026-07-22): exit 1 is ALLOW+warning, and an uncaught
    Python exception exits 1. So without this wrapper a crashing fail-closed gate silently OPENS -
    confirmed here by repro (`tool_name` non-string -> AttributeError -> exit 1 -> tool ran).
    SystemExit must pass through untouched: it carries the gate's real 0/2 verdict.
    """
    try:
        _gate()
    except SystemExit:
        raise                      # the gate's own verdict - never reinterpret it
    except BaseException as exc:   # incl. KeyboardInterrupt/MemoryError: still a consequential act
        sys.stderr.write(
            f"hestia: deny [gate] - the gate crashed ({type(exc).__name__}: {str(exc)[:200]}) and "
            f"cannot vouch for this call; failing closed. This is a boundary, not a failure.\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
