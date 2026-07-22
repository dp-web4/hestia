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
2 (deny, with text). It never exits 1, so it never emits an allow-with-warning by accident.

FIDELITY NOTE (2026-07-22): the exit-code/deny/fail-open contract above is SOURCE-verified (file+lines
cited). The base/BeforeTool field names are from `docs/hooks/reference.md`; the exact per-tool
`tool_input` arg names for Gemini's builtin tools (shell/file) are handled defensively below (a
superset of likely keys) - because the gate is fail-closed, an unrecognized shape over-blocks (safe).
Only LIVE FIRING is unverified; mark `verified` after a run against the real Gemini CLI (CBP's rig).
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

# Gemini builtin read-class tools (no write/exec) - name-matched case-insensitively below.
READ_CLASS = {"read_file", "read_many_files", "glob", "search_file_content", "list_directory",
              "google_web_search", "web_fetch"}

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
        # write_many_files / read_many_files pass a list of paths
        for k in ("paths", "file_paths"):
            v = tool_input.get(k)
            if isinstance(v, list):
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


def main():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.stderr.write("hestia: deny [gate] - could not parse the tool event; failing closed.\n")
        sys.exit(2)

    if event.get("hook_event_name") != "BeforeTool":
        sys.exit(0)  # not our event

    tool = event.get("tool_name") or "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.environ.get("HESTIA_GEMINI_LAUNCH_CWD") or os.getcwd()
    scopes = load_in_scope() + launch_cwd_repo()
    paths = path_targets(tinput)
    cmd = command_of(tinput)

    # Gate 1a - egress/secret innate invariant (denied even inside a granted repo). ALWAYS enforced.
    for blob in paths + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            deny(f"'{tool}' touches a forbidden path (secret/credential or out-of-MRH private repo)",
                 "There is no in-scope way to do this; it is not yours to touch.", innate=True)

    # Gate 1b - MRH scope. File paths use path-scope; shell commands use command-scope.
    if paths:
        if _shared_check_paths is not None:
            # Hardened realpath containment via the shared lib. Roots = granted repos + agent home +
            # tmp, all absolute. It denies ../ / symlink / absolute escapes that the string check can't.
            roots = [os.path.join(WORKSPACE, s) for s in scopes] + [GEMINI_HOME, "/tmp", "/var/tmp"]
            res = _shared_check_paths(paths, roots, cwd, for_write=(tool.lower() not in READ_CLASS))
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

    # Gate 2 - society safety (the governor). Only write/exec-class needs the daemon's verdict; fail closed.
    if tool.lower() not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="gemini-cli", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, CLAUDE_PRE], input=json.dumps(event),
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


if __name__ == "__main__":
    main()
