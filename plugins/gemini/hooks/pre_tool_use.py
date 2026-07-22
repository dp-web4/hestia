#!/usr/bin/env python3
"""Hestia Phase-1 BeforeTool GATE for a foreign member (Google Gemini CLI) — third foreign adapter.

Named `pre_tool_use.py` to hold the cross-member convention (kimi/codex/cursor/openclaw all use it);
on Gemini the event it services is **`BeforeTool`**, not `PreToolUse`. Gemini is an INDEPENDENT
lineage — its own `Before*/After*` vocabulary — so unlike the Codex adapter, nothing here is inherited
from the Claude-Code contract without being read out of `google-gemini/gemini-cli` first.

SOURCE-VERIFIED CONTRACT (read from gemini-cli @ main, 2026-07-22 — not from the docs or the blog).
Construct-pointers are grep-able names, not line numbers:

  1. `BeforeTool` dispatches CENTRALLY and covers EVERY scheduled tool call. `Scheduler._processToolCall`
     calls `evaluateBeforeToolHook` as step 1, *before* `checkPolicy` — so the gate sees the built-ins
     (`run_shell_command`, `write_file`, `replace`, `read_file`, `read_many_files`, `glob`, `grep_search`,
     `list_directory`, `web_fetch`, …) AND MCP calls (`mcp_<server>_<tool>`), and it runs BEFORE
     Gemini's own policy engine. (packages/core/src/scheduler/scheduler.ts, scheduler/hook-utils.ts)
     This is materially better coverage than Codex, where PreToolUse skips several payload types.

  2. Event JSON on stdin is Claude-shaped in its fields but NOT in its values:
     `{session_id, cwd, hook_event_name: "BeforeTool", tool_name, tool_input}`.
     (packages/core/src/hooks/types.ts — `HookInput`, `BeforeToolInput`)

  3. Deny contract, in precedence order (packages/core/src/hooks/hookRunner.ts):
       a. JSON on **stdout or stderr** parses to a `HookOutput` -> that object IS the decision and the
          **exit code is ignored entirely**. `{"decision":"deny"|"block","reason":...}` denies;
          `isBlockingDecision()` accepts both spellings (types.ts).
       b. Non-JSON text -> `convertPlainTextToHookOutput`: exit 0 -> allow; exit **1 -> allow** (warning);
          **every other non-zero, including 2 -> deny**.
     (b) CORRECTS the atlas descriptor and Google's own docs, which say only exit 2 blocks and other
     non-zero exits are non-fatal warnings that proceed. Source says the opposite: 1 is the only
     non-zero that proceeds. Same class of error as the "Codex PreToolUse is Bash-only" blog claim.

  4. **A SILENT non-zero exit does NOT deny.** `textToParse = stdout.trim() || stderr.trim()`; if both
     are empty, `output` stays undefined, the aggregator finds no decision, and `mergeWithOrDecision`
     defaults it to `allow`. So `sys.exit(2)` with nothing written is a hole. Every deny path here
     writes the decision JSON to stdout AND a reason to stderr AND exits 2 — three independent ways to
     land on deny, so no single mis-read of the contract opens the gate.
     (hookRunner.ts + packages/core/src/hooks/hookAggregator.ts)

  5. It **FAILS OPEN** on engine-level failure: a timeout (default 60000 ms) or a spawn error resolves
     `success:false` with no output, which the aggregator turns into `allow`. So this gate is
     FAIL-CLOSED BY CONSTRUCTION: default deny, reach exit 0 only on an explicit confirmed allow.
     Corollary the other hooks inherit: keep this fast, and keep it on ext4 (see README hardening).

  6. Multi-hook merge is OR-on-deny (`mergeWithOrDecision`): if any hook denies, the merged decision is
     deny. Extension-shipped hooks therefore cannot override our deny — the descriptor's "hooks you did
     not install run alongside yours" concern is real for observation, bounded for enforcement.

Three gates, in order (same shape as the Codex adapter, so the members stay comparable):
  1a. EGRESS/SECRET innate denylist — always blocks, never relaxed by trust or by MODE.
  1b. MRH scope containment — delegated to `plugins/lib/path_scope.py` (realpath containment: closes
      `../` traversal, symlink escape, absolute escape). This adapter is that library's first real
      consumer; kimi/codex still carry the naive string-prefix check and get retrofitted to match.
  2.  SOCIETY SAFETY — delegate to the claude-code gate (HESTIA_SOCIETY_GATE) for write/exec-class
      acts, honoring its deny and failing closed when it is unreachable. Because Gemini is a foreign
      lineage, the event is TRANSLATED to the Claude-lineage shape first (see `to_claude_event`) —
      the society gate keys off `Bash`/`Shell`/`file_path`, which Gemini never emits.

Config (all env-overridable; shared names are fleet-wide, `HESTIA_GEMINI_*` are per-member):
  HESTIA_WORKSPACE          root that contains the granted repos        (default: ~/ai-workspace)
  HESTIA_SOCIETY_GATE       path to the society-safety gate caller      (default: $WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py)
  HESTIA_FORBIDDEN_EXTRA    comma-separated extra forbidden path tokens
  HESTIA_GEMINI_IDENTITY    the member's live identity.json             (default: ~/.gemini/hestia-instance/identity.json)
  HESTIA_GEMINI_GATE_MODE   warn | enforce                              (default: enforce)
  HESTIA_GEMINI_LAUNCH_CWD  launch dir granted for the session          (default: the event's cwd)
  HESTIA_GEMINI_HOME        the CLI's own home                          (default: ~/.gemini)
"""
import json
import os
import re
import sys
import subprocess

# plugins/lib is a plain directory (no package marker) — same import shape the library's own tests use.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "lib"))
from path_scope import check_path  # noqa: E402

WORKSPACE = os.environ.get("HESTIA_WORKSPACE", os.path.expanduser("~/ai-workspace"))
GEMINI_HOME = os.path.expanduser(os.environ.get("HESTIA_GEMINI_HOME", "~/.gemini"))
IDENTITY = os.path.expanduser(
    os.environ.get("HESTIA_GEMINI_IDENTITY", "~/.gemini/hestia-instance/identity.json"))
SOCIETY_GATE = os.environ.get(
    "HESTIA_SOCIETY_GATE",
    os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py"))

# Rollout mode: DENY-TIGHT by default — a foreign member starts enforced and RELAXES as role-scoped
# trust accrues. Egress/secret is `innate` and blocks regardless of mode.
MODE = os.environ.get("HESTIA_GEMINI_GATE_MODE", "enforce").lower()

# Innate egress/secret invariants — denied even inside a granted repo. Trust never relaxes these (S1).
FORBIDDEN = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets") + tuple(
    t.strip() for t in os.environ.get("HESTIA_FORBIDDEN_EXTRA", "").split(",") if t.strip())

# Gemini's own tool names (source: packages/core/src/tools/definitions/base-declarations.ts).
# Read-class acts skip Gate 2 only — they still pass 1a and 1b.
READ_CLASS = {
    "read_file", "read_many_files", "glob", "grep_search", "search_file_content", "list_directory",
    "write_todos", "ask_user", "get_internal_docs", "activate_skill", "enter_plan_mode",
    "exit_plan_mode", "list_mcp_resources",
}

# Params that carry a filesystem target. `pattern` is a glob relative to cwd, which resolves correctly
# through path_scope (an in-repo `**/*.ts` lands under cwd; a `../../private/**` resolves out and denies).
PATH_KEYS = ("file_path", "dir_path", "path", "absolute_path", "notebook_path", "pattern")
LIST_PATH_KEYS = ("include", "exclude", "paths")

# Gemini tool -> Claude-lineage tool, so the society gate (which keys off Bash/Shell + file_path) can
# read an event from a foreign lineage. Unmapped names pass through unchanged.
CLAUDE_TOOL_MAP = {
    "run_shell_command": "Shell",
    "write_file": "Write",
    "replace": "Edit",
    "read_file": "Read",
    "read_many_files": "Read",
    "list_directory": "Glob",
    "glob": "Glob",
    "grep_search": "Grep",
    "search_file_content": "Grep",
    "web_fetch": "WebFetch",
    "google_web_search": "WebSearch",
}


def emit_deny(reason, innate=False):
    """The single deny path. innate=True ALWAYS blocks (egress/secret is irreversible); tunable rules
    honor MODE. Writes all three signals the engine understands, because #4 above means a silent
    non-zero exit would ALLOW."""
    steer = (f"hestia: deny [scope] — {reason} This is a boundary, not a failure: don't re-run the "
             f"same call. Asking is a trust-building act; reaching is witnessed.")
    if not (innate or MODE == "enforce"):
        # warn-rollout: no stdout (any stdout JSON would BE the decision); stderr text + exit 0 is
        # read as allow-with-systemMessage, so the act proceeds and the operator still sees the line.
        sys.stderr.write(steer.replace("deny [scope]", "warn [scope]") +
                         " (warn-rollout: allowed; would block under enforce)\n")
        return
    sys.stdout.write(json.dumps({"decision": "deny", "reason": steer}))
    sys.stdout.flush()
    sys.stderr.write(steer + "\n")
    sys.exit(2)


def load_in_scope():
    """Gemini's granted MRH (repos it may touch), read from its identity — per-entity, role-sourced.
    hydrate.sh regenerates this from the repo registry, so it is not hand-maintained."""
    try:
        mrh = json.load(open(IDENTITY, encoding="utf-8")).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]  # "repo:web4" -> "web4"
    except Exception:
        pass
    return ["web4"]


def launch_repo(cwd):
    """The repo Gemini is launched in is always in scope — a per-launch dynamic grant on top of the
    static allowlist, so a task-specific launch dir (even a private repo) is reachable for that session
    without widening the standing grant."""
    cwd = (os.environ.get("HESTIA_GEMINI_LAUNCH_CWD") or cwd or os.getcwd()).replace("\\", "/")
    if WORKSPACE in cwd:
        rest = cwd.split(WORKSPACE, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def allowed_roots(scopes):
    """The granted roots as absolute directories — what path_scope actually contains against."""
    roots = [os.path.join(WORKSPACE, s) for s in scopes if s]
    roots += [GEMINI_HOME, "/tmp", "/var/tmp"]
    return roots


def path_targets(tool_input):
    out = []
    if isinstance(tool_input, dict):
        for k in PATH_KEYS:
            v = tool_input.get(k)
            if isinstance(v, str) and v:
                out.append(v)
        for k in LIST_PATH_KEYS:
            v = tool_input.get(k)
            if isinstance(v, list):
                out += [x for x in v if isinstance(x, str) and x]
    return out


def command_of(tool_input):
    """run_shell_command passes the command under tool_input.command."""
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


def command_names_out_of_scope_repo(cmd, scopes):
    """Catches the bare-name reach — `grep -r foo private-context/` — which carries no `/`-anchored
    token for the path check below to see. String-parse, and honestly weak: it catches explicit
    reaches, not a relative-recursive traversal from a broad cwd."""
    for repo in [r for r in _all_repos() if r not in scopes]:
        if re.search(rf"""(^|[\s/=:"'(]){re.escape(repo)}(/|[\s"')]|$)""", cmd):
            return repo
    if WORKSPACE in cmd:
        after = cmd.split(WORKSPACE, 1)[1]
        if not any(after.lstrip("/").startswith(s) for s in scopes):
            return "the workspace root"
    return None


# Tokens that unambiguously name a path: absolute, `./`, `../`, or `~`-rooted. Anything else (a bare
# word, a `s/a/b/` sed script, a flag) is left to the repo-name scan above.
_PATHY = re.compile(r"""(?:^|[\s=:"'(\[<>|])((?:~|\.{1,2}/|/)[^\s"';|&)\]<>]*)""")

# Read-only system trees a shell command legitimately names: interpreters, coreutils, the null sink.
# These are executables and plumbing, not repo reaches — scope-checking them would deny `/usr/bin/env`
# and `> /dev/null` for no governance gain. Secrets living under them are still caught by Gate 1a,
# which runs first and is innate.
SYSTEM_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/lib/", "/lib64/", "/opt/", "/dev/", "/proc/", "/etc/ssl/")


def command_path_escape(cmd, roots, cwd):
    """Run every `/`-anchored path token of a shell command through path_scope, skipping only the
    system trees above. This closes the `cat ../../private-context/x` traversal and the
    `cat /home/<user>/other-repo/x` absolute reach that the Codex/Kimi string-prefix check both miss —
    the reason CBP asked that this library get a real consumer rather than another copied prefix."""
    for tok in _PATHY.findall(cmd):
        if "://" in tok:
            continue
        expanded = os.path.expanduser(tok)
        landing = os.path.normpath(os.path.join(cwd, expanded))
        if landing.startswith(SYSTEM_PREFIXES):
            continue
        r = check_path(expanded, roots, cwd)
        if not r.allowed:
            return tok, r.reason
    return None


def to_claude_event(event):
    """Translate a Gemini BeforeTool event into the Claude-lineage shape the society gate reads.
    Without this the gate sees tool_name `run_shell_command` and extracts no target at all, so Gate 2
    would be witnessing a blank. Codex needed no translation (same lineage); Gemini does."""
    tool = event.get("tool_name") or "?"
    tinput = dict(event.get("tool_input") or {})
    if "dir_path" in tinput and "path" not in tinput:
        tinput["path"] = tinput["dir_path"]
    name = CLAUDE_TOOL_MAP.get(tool)
    if name is None and tool.startswith("mcp_"):
        parts = tool.split("_", 2)  # gemini `mcp_<server>_<tool>` -> claude `mcp__<server>__<tool>`
        name = f"mcp__{parts[1]}__{parts[2]}" if len(parts) == 3 else tool
    return dict(event, hook_event_name="PreToolUse", tool_name=name or tool,
                tool_input=tinput, source_tool_name=tool)


def main():
    # Fail-closed skeleton: any unexpected error -> deny (never fall through to allow).
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        emit_deny("could not parse the tool event; failing closed.", innate=True)
        return

    if event.get("hook_event_name") != "BeforeTool":
        sys.exit(0)  # not our event

    tool = event.get("tool_name") or "?"
    tinput = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    scopes = load_in_scope() + launch_repo(cwd)
    roots = allowed_roots(scopes)
    paths = path_targets(tinput)
    cmd = command_of(tinput)

    # Gate 1a — egress/secret innate invariant (denied even inside a granted repo). ALWAYS enforced.
    for blob in paths + ([cmd] if cmd else []):
        if any(f in blob.lower() for f in FORBIDDEN):
            emit_deny(f"'{tool}' touches a forbidden path (secret/credential or out-of-MRH private "
                      f"repo). There is no in-scope way to do this; it is not yours to touch.",
                      innate=True)

    # Gate 1b — MRH scope containment, via the shared realpath predicate.
    for p in paths:
        r = check_path(p, roots, cwd)
        if not r.allowed:
            emit_deny(f"'{tool}' targets '{p[:60]}' outside your granted scope "
                      f"({'+'.join(scopes)}): {r.reason} Adjust to work within scope, or if "
                      f"legitimately needed, request it (request_scope).")
    if cmd is not None:
        repo = command_names_out_of_scope_repo(cmd, scopes)
        if repo:
            emit_deny(f"'{tool}' command names '{repo}', outside your granted scope "
                      f"({'+'.join(scopes)}). Scope the command to a granted repo, or if legitimately "
                      f"needed, request it (request_scope).")
        escape = command_path_escape(cmd, roots, cwd)
        if escape:
            tok, reason = escape
            emit_deny(f"'{tool}' command reaches '{tok[:60]}': {reason}")

    # Gate 2 — society safety (the governor). Only write/exec-class needs the daemon's verdict; the
    # 6s budget sits far inside Gemini's 60s hook timeout, because a timeout here would ALLOW.
    if tool not in READ_CLASS:
        try:
            env = dict(os.environ, HESTIA_PLUGIN_ID="gemini-cli", HESTIA_PRE_FAIL_CLOSED="1")
            r = subprocess.run([sys.executable, SOCIETY_GATE],
                               input=json.dumps(to_claude_event(event)),
                               capture_output=True, text=True, timeout=6, env=env)
            if r.returncode != 0:  # daemon denied, or inconclusive -> fail-closed for a write/exec act
                msg = (r.stderr.strip() if r.returncode == 2 and r.stderr.strip()
                       else "blocked or inconclusive at the society safety gate.")
                emit_deny(msg.split("— ", 1)[-1])
        except Exception:
            emit_deny("could not reach the governor; failing closed on a consequential act.")

    sys.exit(0)  # the ONLY allow path — reached only after every gate explicitly passed


if __name__ == "__main__":
    main()
