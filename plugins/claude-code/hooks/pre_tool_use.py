#!/usr/bin/env python3
"""Hestia PreToolUse hook for Claude Code — synchronous policy gate.

Wired from .claude-plugin/plugin.json as the PreToolUse hook. Reads the
hook event JSON from stdin, asks the local Hestia daemon for a policy
decision, and exits with the appropriate code to allow / warn / deny
the tool call.

DESIGN
- **Synchronous on Claude Code's critical path.** Unlike the
  PostToolUse witness hook (fire-and-forget), this one MUST block until
  the daemon answers, because Claude Code uses the exit code to decide
  whether to run the tool.
- **Short budget.** Total deadline is `TOTAL_BUDGET_MS` (default 800 ms).
  If the daemon hasn't returned a `decided` verdict by then, we fall
  back to the local heuristic engine (the legacy `web4-governance`
  plugin's pre_tool_use.py).
- **Wait protocol (spec §3.4.1).** If the daemon returns
  `status: "evaluating"` with `nextPollMs: N`, we sleep N ms and
  re-query — up to `MAX_POLLS` times. Useful when (future) LLM-backed
  policy entities need a moment.
- **Action cache.** On a decision we store the action_id under
  /tmp/hestia-actions/<tool_use_id>.json so the PostToolUse hook can
  pair the outcome to the begin_action.
- **Exit semantics for Claude Code:**
    - `exit 0` (silent)               — allow, no message
    - `exit 0` with stderr message    — warn, surfaced to the agent
    - `exit 2` with stderr message    — DENY, Claude Code blocks the tool

ENV
  HESTIA_HOOK_DEBUG=1            log to ~/.hestia-claude/hook.log
  HESTIA_PRE_FAIL_CLOSED=1       fail-CLOSED profile for governed roles:
                                  any path that cannot get a daemon verdict
                                  (daemon unreachable, budget exhausted,
                                  unexpected error) DENIES the tool instead
                                  of allowing. The legacy fallback is skipped
                                  entirely — the daemon is the law.
  HESTIA_PRE_NO_FALLBACK=1       disable the legacy-engine fallback
                                  (deny-on-daemon-unreachable instead)
  HESTIA_PRE_TOTAL_BUDGET_MS     override TOTAL_BUDGET_MS
  HESTIA_ENDPOINT                override endpoint discovery
  HESTIA_LEGACY_FALLBACK         path to the legacy web4-governance gate. Set this
                                  when the hooks are deployed off-repo (local-fs
                                  deployment), or the relocated gate keeps calling
                                  a fallback that may not be where it was left.
                                  A path that does not exist ALLOWS — see
                                  invoke_legacy_fallback.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple

# ---- Config -----------------------------------------------------------

PLUGIN_ID = "claude-code"
HOST_AGENT = "claude-code"
PROTOCOL_VERSION = 1
HOOK_VERSION = "0.0.2"

STATE_DIR = Path.home() / ".hestia-claude"
ACTIONS_DIR = Path("/tmp/hestia-actions")
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"
DEFAULT_ENDPOINT = "http://127.0.0.1:7711/mcp"

# Total time budget across all daemon round-trips + re-polls.
TOTAL_BUDGET_MS = int(os.environ.get("HESTIA_PRE_TOTAL_BUDGET_MS", "800"))
# Why the last daemon call failed — "timeout" (alive but starved), "refused"
# (nothing listening) or "unknown". Read by `deny_no_verdict` so the refusal can
# state what is known instead of asserting a cause it cannot observe. Module-level
# because the failure happens deep in the request path and the message is composed
# at the top; a hook process handles one call, so there is no cross-request bleed.
_LAST_FAILURE = "unknown"


def _set_last_failure(kind: str) -> None:
    global _LAST_FAILURE
    _LAST_FAILURE = kind


# Per-request HTTP timeout.
REQUEST_TIMEOUT_S = 0.5
# Cap on re-poll iterations during the "evaluating" wait protocol.
MAX_POLLS = 5
# Floor on poll sleep to avoid busy loops if daemon misbehaves.
MIN_POLL_SLEEP_MS = 50

# Path to the legacy fallback hook. Sourced from the same code we ported,
# but kept in-place under claude-code/plugins/ for fallback robustness.
#
# Overridable since 2026-07-26: this was a hardcoded absolute path naming one machine's
# workspace, sitting on the fail-OPEN profile's critical path. A machine that deploys its
# hooks to local fs (the 9p-migration pattern) could relocate the outer gate and silently
# leave the fallback behind — and if the path is simply wrong, `invoke_legacy_fallback`
# returns 0, so a missing fallback ALLOWS. Wrong-path and no-policy are indistinguishable
# at the exit code. The default preserves the previous behaviour exactly.
LEGACY_FALLBACK = os.environ.get(
    "HESTIA_LEGACY_FALLBACK",
    "/mnt/c/exe/projects/ai-agents/claude-code/plugins/web4-governance/hooks/pre_tool_use.py",
)


def debug_log(msg: str) -> None:
    if os.environ.get("HESTIA_HOOK_DEBUG") != "1":
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "hook.log").open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} pre  {msg}\n")
    except OSError:
        pass


def discover_endpoint() -> Optional[str]:
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    try:
        v = (home / "endpoint").read_text().strip()
        return v or None
    except OSError:
        return None



# ---------------------------------------------------------------------------
# THE GATE IS NOT THE AGENT'S TO EDIT — OR TO READ
# ---------------------------------------------------------------------------
#
# dp, 2026-07-28: "an agent that wants to do something it doesn't want governed
# can use this to turn off the gate, do whatever, then turn it back on like
# nothing happened. that wouldn't be an accident :)"
#
# Correct, and it is the hole that makes every other control optional. Gate
# integrity (#52) HASHES this file and reports drift on an operator endpoint —
# tamper-EVIDENT, and only to a human who looks. Nothing in the decision path
# consults it, so disable -> act -> restore leaves a clean record and a matching
# hash. The whole governance model rests on a file the governed party can write.
#
# THE PRINCIPLE, which we already use elsewhere: you do not get to modify the
# thing that governs you, for the same reason you do not get to rule on your own
# appeal. Gate custody belongs to a not-self party.
#
# WHY READ IS DENIED TOO, and not only write: reading this file is how you find
# its blind spots. Every false-positive class we hit this week was discoverable
# by reading the matcher. Denying read forces evasion to be blind probing, which
# is noisy, slow and leaves denials on the chain. It converts a silent read into
# an audible attempt.
#
# WHY THIS RUNS BEFORE THE DAEMON CALL AND NEVER CONSULTS IT: if this check
# required a verdict, then "kill the daemon, then edit the gate" would be the
# same evasion one layer over. Self-protection has to hold when everything else
# is down, so it is local, unconditional, and fails CLOSED.
#
# ON THE DELIBERATE JUDGE-BY-MENTION: for Bash this scans the WHOLE command for
# any mention of a self path, which is exactly the matching style that produced
# ten false positives this week and that policy::shell was written to fix. That
# is intentional and the stakes invert here. A false positive costs a rephrase;
# a false negative costs the entire governance model. `sed -i`, `cp`, `>`,
# `python -c`, `tee` and a heredoc all reach this file by different syntax, and
# an executable-position parse would have to be right about all of them.
#
# ONE SCOPED EXCEPTION (2026-08-07, kimi-code, claiming claude-code notice 1529):
# the daemon's destructive preset tells the member, in its reason string, that "a
# quoted heredoc body under cat/tee does not trip it" (presets.rs, backed by
# policy::shell) — but this hook runs FIRST and matched raw, so a report ABOUT the
# gate written by heredoc was refused by code the quoted law does not describe
# (FP8 through the Bash door; the Write door was carved out below when `content`
# left the haystack). `_blank_inert_heredoc_bodies` is that carve-out, here. It is
# deliberately NARROWER than policy::shell: only heredoc bodies are blanked, never
# quoted argument spans, because this gate matches PATHS and a path can sit at
# argument position — `tee "hooks/pre_tool_use.py"` must keep matching, while
# `rm "-rf"` shapes are the destructive preset's problem, not this one's. A
# heredoc body is stdin content: it can never name the destination, so blanking
# it cannot hide a write to the gate — the destination always sits in executable
# position (`> PATH`, `tee PATH`), where matching stays raw. Everything the parser
# cannot read confidently returns None and None means "match the raw command" —
# the fail-closed edge, unchanged.
#
# WHAT THIS IS NOT: containment. A determined agent can still reach the file by
# a path this misses, or kill the hook process. This is A1 — cooperative. What it
# removes is the CHEAP, SILENT version, and it removes "I didn't know" as an
# account, because the refusal names the rule.
_SELF = os.path.realpath(__file__)
_SELF_DIR = os.path.dirname(_SELF)
_SELF_MARKERS = (
    _SELF,
    _SELF_DIR,
    "plugins/claude-code/hooks",
    "hestia/hooks",
    # THE INSTALLERS ARE WRITE POSITIONS ON THIS GATE (claude-code disclosure 3a,
    # forum "the rung nobody built", 2026-08-07 — handed to kimi-code). Both sit
    # off every marker above by construction: `plugins/claude-code/install.sh`
    # one directory up, `deploy/install-members.sh` (#272) in a directory
    # no hook marker names. (#273, which carried install.sh, was CLOSED
    # unmerged in favour of #272 — the file lives only on that branch; the
    # marker pre-positions for its return, it names nothing on main today.)
    # Verified there by invocation: the gate ALLOWED
    # `bash <installer>` and only the script's own role check refused. Running
    # the installer overwrites the enforcing copy — it IS writing the gate, one
    # `cp` removed, and it belongs in the self-access class (witnessed,
    # escalatable) rather than in ordinary policy. Editing either script is the
    # same act one hop earlier, so the path-key match refusing it is intended.
    # Disclosed limit, same as every path marker: an invocation that never
    # spells the path (cd in, `bash install.sh`) matches nothing — A1 removes
    # the cheap silent version, it is not containment.
    "plugins/claude-code/install.sh",
    "deploy/install-members.sh",
)

# THE GOVERNANCE SURFACE, not just this file. Protecting only `pre_tool_use.py`
# was the first cut, and testing it found the gaps immediately: the SOCIETY gate
# (`society_pre_tool_use.py` — the one that actually parked a member today) and
# `witness.py` (the outcome recorder) were both reachable. Disarming the recorder
# is the worse attack of the two: it does not produce denials, it produces
# SILENCE, and silence is indistinguishable from "attempted nothing".
#
# Matched by filename anywhere, deliberately, so this holds for a peer's copy as
# well as mine. An agent editing ANOTHER member's gate is not a lesser act — it
# is disarming an entity that did not consent, and the record would name the
# victim rather than the author.
#
# `hestia_gate_core.py` added 2026-08-03, on the same reasoning one step ahead of it.
# PR #169 landed the shared policy core — the file that is to BECOME the single gate for
# all five harnesses, with the per-harness hooks reduced to adapter shims. It matched
# nothing here and nothing in `_SELF_MARKERS`, so the whole PR was written unrefused. That
# was verified by writing it, and disclosed in the PR rather than used.
#
# The failure mode consolidation creates: today, disarming the gate means editing five
# files and tripping this rule five times. After the shims land it means editing ONE file
# — and if that file is outside the rule, consolidation will have moved the entire policy
# surface somewhere unguarded while every per-harness protection still reads as intact.
# The rule would be green about five shims that no longer decide anything.
#
# Filename-anywhere is the right mechanism and not merely the convenient one: shims will
# import the core from several locations, so a directory marker would miss it — and the
# rationale directly above ("so this holds for a peer's copy as well as mine") is exactly
# the property needed when one file governs five members.
_GOVERNANCE_FILES = (
    "pre_tool_use.py",
    "society_pre_tool_use.py",
    "post_tool_use.py",
    "witness.py",
    "law_inject.py",
    "hestia_gate_core.py",
    # The EXEMPTION LEDGER is a policy artifact too (codex NOT-SAME review of #175).
    # `gate_self_protection_test.py` holds `EXEMPT`, the list of shared files allowed to
    # escape the guard. Outside this tuple, the bypass was one unescalated write: add a new
    # decider to `plugins/_shared/`, add its name to EXEMPT, and every check passes. Its own
    # comment claimed adding an exemption was "as hard as adding a rule" while the code made
    # it free — an aspirational claim a reader would have trusted.
    "gate_self_protection_test.py",
)


# Commands whose arguments and stdin are DATA, never shell code — the same
# allowlist policy::shell uses, kept in sync with it deliberately. An allowlist,
# never a denylist: an unrecognised head is treated as interpreting, so
# `sh -c`, `eval`, `sed`, `awk`, `python3 -` and everything nobody has vetted keep
# their heredoc bodies fully scanned. Adding a name widens the gate; it belongs in
# a reviewed diff with the reason stated.
#
# `git` STAYS ABSENT and that is still correct — see `_git_stdin_is_data`, the
# other half of condition 2 rather than an entry here. A name in this list is a
# promise about every invocation of it, and `git` cannot make that promise.
# (Mirror of policy::shell's INERT_CONTENT_HEADS note; the shadow test below
# keeps adding `git` here a loud act, because the `git` arm decides first and a
# list entry would be unreachable — claude-code's sabotage finding, 2026-08-07.)
_INERT_CONTENT_HEADS = frozenset({
    # byte movers
    "cat", "tee", "head", "tail", "rev", "nl",
    # pattern search — none of these can execute a match
    "grep", "egrep", "fgrep", "rg",
    # output
    "echo", "printf",
    # text filters
    "wc", "sort", "uniq", "cut", "tr", "comm", "diff", "column", "fold", "paste",
    "join",
    # structured filters
    "jq",
    # path arithmetic
    "basename", "dirname",
})


# --- `git`: the one head that is not a decision by itself ---------------------
#
# Mirror of policy::shell's `git_stdin_is_data` (claude-code, branch
# claude/git-stdin-is-argv-position), which lands adjudication a96b79c4's remedy
# (kimi-code, cross-vendor, UPHELD on deny 9199c25e): the same quoted heredoc
# body was ALLOWED under `cat` and DENIED under `git commit -F -`, because the
# head basename alone decided. The ruling named the remedy — argv-position-aware
# inertness for stdin consumers — and ruled OUT adding `git` to the head
# allowlist: a head-only list cannot tell `git commit -F -` from
# `git -c core.hooksPath=… commit`. This gate's copy exists for the FP8 shape:
# a commit message written by heredoc that names a GOVERNANCE PATH.
#
# The walk vouches for a SHAPE and fails closed at the first thing it does not
# recognise — the head allowlist's discipline, one level finer:
# 1. Every global option before the subcommand must be unable to introduce an
#    interpreter. `-c` is admitted only for _GIT_INERT_CONFIG_KEYS;
#    `--exec-path`, `--config-env` and anything unlisted stop the walk.
# 2. The subcommand must be a builtin whose stdin is content. Git itself refuses
#    to let an alias shadow a builtin, so `commit`/`tag`/`hash-object` cannot be
#    redefined — while clause 1 keeps a NEW alias off the command line (the
#    `git -c alias.x='!sh' x <<'X'` bypass).
# 3. Something must declare stdin to be that content: `-F -`, `--file=-`,
#    `--stdin`. `git commit -m x <<'X'` is not vouched for — unknown means
#    scanned, the same discipline as an unknown head.
#
# WHAT THIS DOES NOT CLAIM: that the repository is safe — a `commit-msg` hook on
# disk can do anything with the message, and a text matcher cannot see the
# filesystem. It says the command TEXT introduces no interpreter for its own
# stdin, the same standard already applied to `cat > f`.

# `git -c KEY=VALUE` keys that cannot change what git will EXECUTE. Deliberately
# two: inline config is the documented way to hand git new code (`core.hooksPath`,
# `core.pager`, `alias.*`, `core.fsmonitor`, `diff.*.textconv`,
# `credential.helper` …), so the default for an unlisted key is "this might
# introduce an interpreter".
_GIT_INERT_CONFIG_KEYS = frozenset({"user.name", "user.email"})

# `git` global options taking no value that cannot re-point it at code.
_GIT_INERT_GLOBAL_FLAGS = frozenset({
    "--no-pager", "--bare", "--literal-pathspecs", "--no-replace-objects",
    "--no-optional-locks",
})

# `git` global options taking a value (`--git-dir=X` or `--git-dir X`) that
# select WHERE git works, never WHAT it runs. `--exec-path` and `--config-env`
# are absent on purpose: both name code or config the command text itself chose.
_GIT_INERT_GLOBAL_VALUE_OPTS = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})


def _git_config_is_inert(kv: str) -> bool:
    """`-c KEY=VALUE` where KEY cannot change what git executes."""
    if "=" not in kv:
        # `-c key` with no `=` sets it true. No listed key is a boolean, so
        # this is always some other key: refuse.
        return False
    return kv.split("=", 1)[0].lower() in _GIT_INERT_CONFIG_KEYS


def _message_comes_from_stdin(rest: list) -> bool:
    """Does this argv say "read the message from stdin"? `-F -`, `-F-`,
    `--file=-`, `--file -`. `-F /path` is a FILE and is deliberately not
    vouched for: the heredoc body is then not what git reads."""
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--file=-":
            return True
        if a in ("-F", "--file"):
            return i + 1 < len(rest) and rest[i + 1] == "-"
        if a == "-F-":
            return True
        i += 1
    return False


def _git_stdin_is_data(args: list) -> bool:
    """Is this `git` invocation one whose stdin is data, so a quoted heredoc
    body fed to it can never be executed? See the block comment above."""
    i = 0
    # ---- 1. global options, up to the subcommand ----
    while True:
        if i >= len(args):
            return False  # `git` with no subcommand at all
        a = args[i]
        if not a.startswith("-"):
            i += 1
            break
        i += 1
        if a == "-c":
            if i >= len(args) or not _git_config_is_inert(args[i]):
                return False
            i += 1
            continue
        if a.startswith("-c"):
            # git's glued form, `-ckey=value`.
            if not _git_config_is_inert(a[2:]):
                return False
            continue
        if a in _GIT_INERT_GLOBAL_FLAGS:
            continue
        name = a.split("=", 1)[0]
        if name in _GIT_INERT_GLOBAL_VALUE_OPTS:
            if "=" not in a:
                # the value is the next word
                if i >= len(args):
                    return False
                i += 1
            continue
        return False  # unrecognised global option: unknown means scanned

    # ---- 2 + 3. subcommand, and the flag that declares stdin to be content ----
    subcommand = a
    rest = args[i:]
    if subcommand in ("commit", "tag"):
        return _message_comes_from_stdin(rest)
    if subcommand == "hash-object":
        return "--stdin" in rest
    return False


def _treats_content_as_data(seg: list) -> bool:
    """Condition 2: does this segment's command treat its arguments and stdin
    as data? `git` is matched BEFORE the list, so a list entry for it would be
    unreachable — the shadow test in test_pre_tool_use_self.py keeps that loud."""
    head = seg[0]
    if head == "git":
        return _git_stdin_is_data(seg[2])
    return head in _INERT_CONTENT_HEADS


def _blank_inert_heredoc_bodies(cmd: str) -> Optional[str]:
    """A copy of `cmd` with QUOTED heredoc bodies blanked to spaces, else None.

    The scoped port of policy::shell's `executable_positions` for this gate —
    scoped because the two gates match different things. The destructive preset
    matches COMMAND TOKENS (`rm -`, `dd `), so it can blank any inert quoted
    span; this gate matches PATHS, and a path can sit at argument position, so
    blanking quoted arguments would open `tee "hooks/pre_tool_use.py"` as a
    one-word evasion. A heredoc BODY is the only span that can never name a
    destination — it is stdin content — so it is the only span blanked here.

    The three safety conditions are the daemon's, unchanged in kind:

    1. The body cannot expand: only a QUOTED delimiter (`<<'X'`, `<<"X"`,
       `<<\\X`) qualifies. `cat <<X` can carry `$(...)` and stays visible.
    2. The command governing the body treats stdin as data: the owning
       segment's head must be in `_INERT_CONTENT_HEADS` — except `git`, the
       one head that is not a decision by itself, which `_git_stdin_is_data`
       answers from the argv (see `_treats_content_as_data`).
    3. Nothing downstream re-interprets it: inertness propagates backwards
       along pipes, so `cat <<'X' | sh` keeps its body visible.

    Returns None on anything the parser cannot resolve — unterminated quote,
    heredoc whose delimiter never arrives, unbalanced `$(`, trailing backslash —
    and None means "match the raw command" (fail closed, today's behaviour).
    Length and newlines are preserved in the projection, so a report against it
    still lines up with the original.
    """
    n = len(cmd)
    # (head, sep, args) per segment; sep is 'pipe', 'break' or 'end'; args is
    # the argv after the head (no assignment prefixes, no redirection targets),
    # collected because condition 2 is not always answerable from the head alone.
    segs: list = [[None, "end", []]]
    inert_spans: list = []  # (seg_idx, start, end) of candidate bodies
    pending: list = []      # heredocs opened on this line: dicts
    seg = 0
    word: list = []
    word_quoted = False
    head_done = False
    expect_redir_target = False
    subst_depth = 0

    def flush_word() -> None:
        nonlocal word_quoted, head_done, expect_redir_target
        if not word:
            word_quoted = False
            return
        w = "".join(word)
        if expect_redir_target:
            expect_redir_target = False
        elif not head_done:
            if not word_quoted and _is_shell_assignment(w):
                pass  # `FOO=bar cmd …` — keep looking for the head
            else:
                segs[seg][0] = w.rsplit("/", 1)[-1]
                head_done = True
        else:
            segs[seg][2].append(w)
        word.clear()
        word_quoted = False

    def find_unescaped(start: int, close: str, honour_backslash: bool) -> Optional[int]:
        j = start
        while j < n:
            if honour_backslash and cmd[j] == "\\":
                j += 2
                continue
            if cmd[j] == close:
                return j
            j += 1
        return None  # unterminated — fail closed

    def read_delimiter(i: int) -> Optional[Tuple[str, bool, int]]:
        delim: list = []
        quoted = False
        while i < n:
            c = cmd[i]
            if c in "'\"":
                quoted = True
                end = find_unescaped(i + 1, c, c == '"')
                if end is None:
                    return None
                delim.extend(cmd[i + 1:end])
                i = end + 1
            elif c == "\\":
                if i + 1 >= n:
                    return None
                quoted = True
                delim.append(cmd[i + 1])
                i += 2
            elif c.isspace() or c in ";&|<>()":
                break
            else:
                delim.append(c)
                i += 1
        if not delim:
            return None
        return "".join(delim), quoted, i

    def consume_body(i: int, hd: dict) -> Optional[Tuple[int, int, int]]:
        body_start = i
        line_start = i
        while i <= n:
            if i == n or cmd[i] == "\n":
                line = cmd[line_start:i]
                if hd["strip_tabs"]:
                    line = line.lstrip("\t")
                if line.rstrip("\r") == hd["delim"]:
                    return body_start, line_start, (i if i == n else i + 1)
                if i == n:
                    return None  # ran out of input before the terminator
                line_start = i + 1
            i += 1
        return None

    i = 0
    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 >= n:
                return None  # trailing backslash: unresolved
            word.extend((c, cmd[i + 1]))
            word_quoted = True
            i += 2
        elif c == "'":
            end = find_unescaped(i + 1, "'", False)
            if end is None:
                return None
            word.extend(cmd[i + 1:end])
            word_quoted = True
            i = end + 1
        elif c == '"':
            end = find_unescaped(i + 1, '"', True)
            if end is None:
                return None
            word.extend(cmd[i + 1:end])
            word_quoted = True
            i = end + 1
        elif c == "$" and i + 1 < n and cmd[i + 1] == "(":
            subst_depth += 1
            word.extend("$(")
            i += 2
        elif c == "`":
            end = find_unescaped(i + 1, "`", True)
            if end is None:
                return None
            word_quoted = True
            i = end + 1
        elif c == "<" and i + 1 < n and cmd[i + 1] == "<":
            flush_word()
            if i + 2 < n and cmd[i + 2] == "<":
                i += 3  # herestring: the following word is ordinary data
            else:
                i += 2
                strip_tabs = i < n and cmd[i] == "-"
                if strip_tabs:
                    i += 1
                while i < n and cmd[i] in " \t":
                    i += 1
                got = read_delimiter(i)
                if got is None:
                    return None
                delim, quoted, i = got
                pending.append({"delim": delim, "quoted": quoted,
                                "strip_tabs": strip_tabs, "seg": seg})
        elif c in "><":
            if word and all(ch.isdigit() for ch in word):
                word.clear()
                word_quoted = False
            flush_word()
            i += 1
            while i < n and cmd[i] in "><&|":
                i += 1
            expect_redir_target = True
        elif c in "|;&({}":
            if c == "(" and subst_depth > 0:
                word.append(c)
                i += 1
                continue
            flush_word()
            is_pipe = c == "|" and not (i + 1 < n and cmd[i + 1] == "|")
            segs[seg][1] = "pipe" if is_pipe else "break"
            segs.append([None, "end", []])
            seg += 1
            head_done = False
            expect_redir_target = False
            i += 1
            if i < n and cmd[i] == c and c in "&|":
                i += 1
        elif c == ")":
            if subst_depth > 0:
                subst_depth -= 1
                word.append(c)
                i += 1
            else:
                flush_word()
                segs[seg][1] = "break"
                segs.append([None, "end", []])
                seg += 1
                head_done = False
                expect_redir_target = False
                i += 1
        elif c == "\n":
            flush_word()
            i += 1
            for hd in pending:
                got = consume_body(i, hd)
                if got is None:
                    return None
                body_start, body_end, i = got
                if hd["quoted"] and subst_depth == 0:
                    inert_spans.append((hd["seg"], body_start, body_end))
            pending.clear()
            segs[seg][1] = "break"
            segs.append([None, "end", []])
            seg += 1
            head_done = False
            expect_redir_target = False
        elif c in " \t\r":
            flush_word()
            i += 1
        else:
            word.append(c)
            i += 1

    if subst_depth != 0:
        return None  # unbalanced `$(`
    if pending:
        return None  # heredoc opened, body never arrived
    flush_word()

    # Conditions 2 + 3 together, walking backwards so a segment is inert only
    # if the segment it pipes into is inert too.
    inert_seg = [False] * len(segs)
    for k in range(len(segs) - 1, -1, -1):
        head_ok = _treats_content_as_data(segs[k])
        if segs[k][1] == "pipe":
            inert_seg[k] = head_ok and (inert_seg[k + 1] if k + 1 < len(segs) else False)
        else:
            inert_seg[k] = head_ok

    out = list(cmd)
    for s, start, end in inert_spans:
        if 0 <= s < len(inert_seg) and inert_seg[s]:
            for slot in range(start, end):
                if out[slot] != "\n":
                    out[slot] = " "
    return "".join(out)


def _is_shell_assignment(word: str) -> bool:
    """`FOO=bar` — a variable assignment prefix, not the segment's head."""
    eq = word.find("=")
    if eq <= 0:
        return False
    name = word[:eq]
    return (name[0].isalpha() or name[0] == "_") and all(
        ch.isalnum() or ch == "_" for ch in name)


def _touches_self(tool_name: str, tool_input: Any) -> Optional[Tuple[str, str, str]]:
    """`(marker, resource, key)` if this call reaches the gate's own code, else None.

    The TRIPLE, not the bare marker (5.2, claude-code notice 1474 §2): the first cut
    returned only the marker and discarded the haystack element that matched, so the
    deny message and the escalation text printed the PATTERN that fired where they
    promised the RESOURCE the call would reach — and because `_SELF_MARKERS` is an
    ordered first-match-wins tuple, the same file spelled two ways produced two
    different "destinations" (1474 §3a). The escalation record is the human's entire
    basis for approving; it must name the act, with the marker as the REASON.

    `resource` is the matched element itself: the path for a PATH-key match (raw or
    realpath'd), the matched text for a TEXT-key match. `key` says which input field
    it came from, so the caller can report a `command`/`new_string`/`content` match
    as PAYLOAD content rather than as a destination — the FP8 case, where the match
    is a document QUOTING the gate. The marker is unchanged and still goes to the
    daemon as `marker`: approvals key on it, and this fix moves the human-facing
    strings, not the keying.
    """
    if not isinstance(tool_input, dict):
        return None
    # PATH keys are resolved against cwd so `../hooks/pre_tool_use.py` is caught.
    # TEXT keys are matched RAW, and that distinction is load-bearing: the first
    # cut resolved every key, and `os.path.realpath()` on a non-path string
    # silently prepends the cwd — `realpath("fn main() {}")` is a real path under
    # wherever the session happens to be standing.
    #
    # Scope it honestly: this is cwd-DEPENDENT, not universal. It fires when the
    # session's cwd sits under a marker directory (the installed hooks dir, or a
    # tree matching `plugins/claude-code/hooks` / `hestia/hooks`), and in the
    # common case — cwd at a project root — it does not fire at all. It was found
    # by the "ordinary work is untouched" case in test_pre_tool_use_self.py, which
    # runs from the hooks directory and so stands exactly where it bites. Latent,
    # never observed in the wild, and cheap to remove.
    #
    # The false positive is not the expensive half. A spurious refusal costs a
    # rephrase; a spurious `gate_self_access` WITNESS costs the alert class its
    # meaning — this event exists to be rare and to be read as evidence about
    # intent, and an event type that fires on ordinary work gets muted by the
    # first operator who sees it, which is exactly the burial the block above
    # gave its own event type to avoid.
    #
    # Nothing is lost by matching `command` text raw: `../hooks/pre_tool_use.py` in a
    # shell command still contains both `hooks/` and a governance filename. What IS
    # given up is a symlinked alias inside a command string — admitted, and no
    # worse than the Bash surface's other known gaps.
    #
    # `content` LEFT the haystack 2026-08-07 (FP8/FP13, kimi-code; claimed from
    # claude-code's notice 1334). For a Write the DESTINATION is already below as
    # `file_path` plus its realpath, and the destination is what decides whether the
    # gate changes — the payload text names no resource this call touches. Scanning it
    # refused every document ABOUT the gate: eight recorded instances of a finding that
    # names the gate being unwriteable anywhere on disk, including drafts of the report
    # itself. Staging gate source at a scratch path and copying it in still refuses —
    # at the `cp`, an unknown head (`cp_onto_gate` in `_SURVIVE`). `new_string` STAYS:
    # Edit is the genuinely hard case (string replacement steers a file whose destination
    # never is the gate), and it keeps the old treatment until that case is earned.
    #
    # `command` got the SAME disease through the Bash door, one day later (claude-code
    # notice 1529 §7): a report about the gate written by heredoc is the FP8 shape
    # with `cat`/`tee` holding the pen. The fix is NOT to drop `command` from the
    # haystack — the destination of a shell write lives IN the command text, so raw
    # matching is the only thing standing over `> PATH` and `tee PATH`. Instead the
    # command is matched against `_blank_inert_heredoc_bodies`: quoted heredoc bodies
    # (the only span that can never name a destination) are blanked before matching;
    # everything else, quoted or not, is matched raw. The entries below are
    # (report_text, match_text, key) so the deny and the escalation still quote what
    # the member actually wrote, not the projection.
    resolved = []
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            resolved.append((v, v, key))
            try:
                rp = os.path.realpath(v)
                resolved.append((rp, rp, key))
            except (OSError, ValueError):
                pass
    for key in ("command", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            match = v
            if key == "command":
                proj = _blank_inert_heredoc_bodies(v)
                if proj is not None:
                    match = proj
            resolved.append((v, match, key))
    if not resolved:
        # No target key and no command we recognised — an unknown tool shape. Scan
        # `content` after all: an absent destination must not read as absent risk.
        v = tool_input.get("content")
        if isinstance(v, str) and v:
            resolved.append((v, v, "content"))
    for report, match, key in resolved:
        for marker in _SELF_MARKERS:
            if marker and marker in match:
                return (marker, report, key)
        # Governance files by name, ANYWHERE by default. `_HOOKS_DIR_ONLY` carves out the
        # names common enough that matching them everywhere would fire on ordinary work.
        #
        # THE DEFAULT WAS INVERTED, AND THE INVERSION WAS THE DEFECT. This required a `hooks/`
        # segment before consulting `_GOVERNANCE_FILES` at all — so `plugins/_shared/
        # hestia_gate_core.py` (the policy core for all five harnesses) and the exemption
        # ledger under `tests/` were named in a protected tuple that COULD NOT FIRE against
        # them. Five behavioural probes proved it: relative write, absolute write, Edit, Bash,
        # and the ledger — every one returned None while the membership test stayed green.
        #
        # So: a newly governed name is protected because someone added it, not because they
        # also remembered where it lives. Weakening is now an explicit, visible second edit
        # into `_HOOKS_DIR_ONLY`, and the subset test keeps that list from drifting away from
        # the list it weakens.
        low = match.replace("\\", "/")
        in_hooks = "hooks/" in low or "/hooks" in low
        for fname in _GOVERNANCE_FILES:
            if fname not in low:
                continue
            if fname in _HOOKS_DIR_ONLY and not in_hooks:
                continue
            return (fname, report, key)
    return None


# ---------------------------------------------------------------------------
# THE GATE'S REGISTRATION IS PART OF THE GATE (2026-07-28, follow-on)
# ---------------------------------------------------------------------------
#
# The block above protects the gate's CODE. It was probed against the evasions
# it claims to remove, and the cheapest one walked straight through:
#
#   Write  ~/.claude/settings.json  content='{}'      -> _touches_self: None
#   Bash   mv ~/.claude/settings.json{,.bak}          -> _touches_self: None
#   Edit   ~/.claude/settings.json  (drop the stanza) -> _touches_self: None
#
# Verified by direct call against this file at 99d122f, not by reading it. The
# hook is invoked because `~/.claude/settings.json` names it; that path carries
# no `hooks/` segment and no governance filename, so every marker missed. One
# write of `{}` disarms the PreToolUse gate AND the PostToolUse witness — and
# unlike editing this file it needs no knowledge of what the matcher looks for.
#
# So the protection as shipped was strictly weaker than its own claim to "remove
# the cheap, silent version": the cheapest version was the one it did not see.
# A control that protects its implementation but not its INSTALLATION protects
# nothing — this is `gate installed != gate enforced` pointed at itself.
#
# DECIDABILITY, per tool, because the honest rule differs by what we can see:
#
#   Write / NotebookEdit  we hold the full proposed content. Parse it, compare
#                         the `hooks` stanza to what is on disk, and refuse only
#                         if it would CHANGE. A permissions-only edit passes.
#                         Content we cannot parse is refused: an unreadable
#                         proposal cannot demonstrate it preserves anything.
#   Edit                  we hold old_string/new_string. Refuse if either names
#                         `hooks` or a governance file — that is the only kind of
#                         edit that can reach the stanza.
#   Bash                  undecidable. `mv`, `>`, `jq`, `python -c` and a heredoc
#                         all rewrite the file by different syntax and none of
#                         them has to say `hooks`. Mention of a settings path is
#                         refused outright, same stakes-inversion as above: the
#                         false positive costs one rephrase into Read/Edit, which
#                         ARE decidable, and the false negative costs the gate.
#
# STILL NOT CONTAINMENT, and the gap is now narrower but sharper: settings can
# also be supplied by CLI flag and by env, neither of which passes through any
# hook — by construction, since the hook is not running yet when they are read.
# That surface belongs to whoever installs the agent, not to the agent's gate,
# and saying so is the point: the boundary is where custody changes, and this
# file cannot be both sides of it.
# Governance filenames that are ONLY governed under a `hooks/` path — the deliberate
# weakening, kept small and visible.
#
# These are common enough that matching them anywhere would fire on ordinary work: a repo can
# legitimately hold an unrelated `witness.py`, and `post_tool_use.py` appears in vendor
# examples and documentation. The distinctive names — `hestia_gate_core.py`, the exemption
# ledger — are NOT here, so they are governed wherever they live.
#
# The direction matters more than the contents. A name added to `_GOVERNANCE_FILES` is
# protected by default; weakening it costs a second, deliberate edit into this tuple, and the
# subset test refuses an entry here that is not governed at all. Before, the default ran the
# other way and a governed name silently protected nothing unless someone also happened to put
# it in a hooks directory.
_HOOKS_DIR_ONLY = (
    "pre_tool_use.py",
    "society_pre_tool_use.py",
    "post_tool_use.py",
    "witness.py",
    "law_inject.py",
)

_SETTINGS_MARKERS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
)

# Tokens that mean an edit is reaching the hook registration rather than some
# unrelated key (permissions, env, model) in the same file.
_REGISTRATION_TOKENS = ("hooks",) + _GOVERNANCE_FILES


def _mentions_settings(s: str) -> bool:
    return any(m in s.replace("\\", "/") for m in _SETTINGS_MARKERS)


def _hooks_stanza(text: str) -> Any:
    """The `hooks` value of a settings blob, or None if it has none / is unreadable."""
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return d.get("hooks") if isinstance(d, dict) else None


def _touches_registration(tool_name: str, tool_input: Any) -> Optional[str]:
    """Return a marker if this call could disarm the gate by DE-REGISTERING it."""
    if not isinstance(tool_input, dict):
        return None

    if tool_name == "Bash":
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and _mentions_settings(cmd):
            return "claude settings file (shell — write intent undecidable)"
        return None

    path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
    )
    if not isinstance(path, str) or not _mentions_settings(path):
        return None

    # Nothing to disarm if the file registers no hooks. Read failures are treated
    # as "has hooks": a settings file we cannot read is not a settings file we can
    # clear.
    try:
        with open(os.path.realpath(path), "r", encoding="utf-8") as fh:
            current = _hooks_stanza(fh.read())
    except OSError:
        current = None
    except Exception:  # noqa: BLE001 — unreadable is not permission
        current = True
    if not current:
        return None

    if "content" in tool_input:
        content = tool_input.get("content")
        if not isinstance(content, str):
            return "claude settings hooks stanza (opaque write)"
        if _hooks_stanza(content) != current:
            return "claude settings hooks stanza"
        return None

    for key in ("old_string", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str) and any(t in v for t in _REGISTRATION_TOKENS):
            return "claude settings hooks stanza"
    return None




# ---------------------------------------------------------------------------
# READ IS ALLOWED AND WITNESSED. WRITE IS REFUSED.
# ---------------------------------------------------------------------------
#
# dp, 2026-07-28, agreeing with kimi's third question: read-denial costs verification,
# not just evasion.
#
# The first cut refused BOTH, arguing that reading the gate is how you find its blind
# spots. kimi's counter is the one I could not answer: denying read also denies the
# byte-identity verification it did for #55 and the source-reading behind three of this
# week's reviews. "A witnessed read is evidence; a refused read is a member who cannot
# check its own governance."
#
# It also contradicted this corpus's own posture. We spent two weeks building PUBLISH THE
# LAW so a member can read what governs it — then I argued a member must not read the
# law's implementation. Those pull opposite ways, and I did not notice while writing it.
#
# So reads pass and are WITNESSED, which keeps the reconnaissance signal (a member reading
# gates repeatedly stays visible) without blinding the member to its own law.
#
# CLASSIFICATION FAILS CLOSED. For structured tools the split is exact. For Bash it is not
# decidable in general — `sed -i`, `cp x gate`, `> gate`, `tee gate` all write and nothing
# in the string reliably says so. Bash is therefore a WRITE unless every segment matches a
# small read-only allowlist AND there is no redirection or pipe. Same reasoning as
# policy::shell's inert-head allowlist: widening requires ADDING a name, a reviewable act;
# forgetting one costs a false refusal, never a hole.
_READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
_READ_ONLY_HEADS = {
    "cat", "less", "more", "head", "tail", "grep", "rg", "egrep", "fgrep",
    "wc", "md5sum", "sha256sum", "shasum", "cksum", "diff", "file", "stat", "ls",
    # Added 2026-08-02 after ELEVEN false refusals in one session, every one of them a
    # read. Widening is "a reviewable act" per the note above, so each name is here on
    # purpose and the risky ones are guarded below rather than admitted bare.
    "echo", "printf", "basename", "dirname", "realpath", "readlink", "pwd",
    "true", "false", "test", "[", "seq", "nl", "cut", "tr", "uniq",
    "comm", "rev", "du", "df", "which", "type", "id", "whoami", "uname",
    "jq", "column", "tree",
    # `cd` added 2026-08-05, and it is the cheapest of the four fixes in this pass because
    # `cd` is a head that CANNOT write — there is no flag, no argument and no spelling of it
    # that modifies a file. Its absence cost a real refusal: `cd h && grep -n foo <gate>`,
    # a read of the gate for symbol names while writing a defect report about the gate, was
    # refused and opened escalation 851e0d0ec5a4bf0c on the operator. `grep -n foo <gate>`
    # alone is permitted, so the only thing the refusal measured was that the member changed
    # directory first.
    #
    # Segment walking is what makes this safe, and the test says so rather than trusting it:
    # separators split `cd /tmp && sed -i s/a/b/ <gate>` into two segments and the second is
    # head-checked on `sed`. Adding `cd` frees the `cd` segment, never the one after it.
    # (`cd_does_not_launder` in tests/gate_false_refusal_test.py.)
    "cd",
    # NOT here: `date` and `hostname` (codex peer review, finding 2). `date -s` sets the
    # system clock; `hostname X` sets the hostname. A read-looking NAME carrying a mutating
    # FLAG is precisely what a head allowlist cannot see, which is why `_GUARDED_HEADS`
    # exists for the cases worth keeping.
    #
    # These two survived the first rebuild because that edit covered the logic region and
    # not this set — the classifier then scored 27/29 with exactly these two failing, while
    # the standalone prototype had passed 30/30. Without running the cases against the REAL
    # file this would have shipped claiming all four of codex's findings fixed with two of
    # them still open, and a test that only ever ran against the prototype would have agreed.
}
# Heads that are read-only ONLY without their writing flags. Kept separate so the guard is
# impossible to lose by someone appending to the set above.
#   find  — `-delete`, `-exec`, `-fprint*` execute or write
#   sort  — `-o FILE` writes
_GUARDED_HEADS = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"),
    "sort": ("-o", "--output"),
}
# Admitted UNDER A GRAMMAR, not bare: `sed` — see `_HEAD_GRAMMARS` below. thor refuted an
# earlier attempt to allow `sed -n` by demonstration, not by argument (`sed -n
# '1r /etc/shadow'` reads a file whose path never appears as an argument, invisible to
# every argument-based check); that case is now enforced by code and pinned by a test row
# instead of adjudicated by this comment.
# NOT added, deliberately, and each for a demonstrated reason:
#   awk    — can write via `print > "file"` INSIDE the program text, where the redirection
#            check below cannot see it. Unlike sed's, awk's command set is a full language;
#            its per-head grammar would be "always refuse", which is no grammar at all.
#   xargs  — runs an arbitrary command.
#   python/node/sh/bash — obviously.
# Ambiguity still means write. The point of this change is to stop calling `2>/dev/null` a
# file write, not to make the classifier clever.


# ---------------------------------------------------------------------------
# Per-head argument grammars (kimi-code, 2026-08-06; notices 1218 -> 1226 -> 1241)
# ---------------------------------------------------------------------------
#
# The probe at `tools/kimi_read_only_mutation_probe_1218.py` measured that this classifier
# was head-only: adding `sed` to `_READ_ONLY_HEADS` admits `sed -i 's/a/b/' <gate>` in both
# spellings and laundered through a `cd` segment — an in-place write indistinguishable, by
# head, from the `sed -n` range-print the addition is for. "Add it to the list" is off the
# table; the remedy is to audit the ARGUMENTS of the heads that need it.
#
# Written HERE rather than in `hestia_gate_core.py` for the same reason `attempted_summary`
# was (:802): the core is not wired yet and the cost is being paid now. claude-code
# measured the sharper version (notice 1241): the core has exactly ONE importer, its own
# unit test, while sitting inside `_GOVERNANCE_FILES` — guarded and unused at once, so a
# grammar landed there is committed, tested, guarded and INERT, with every check green
# about it. When the shims land this belongs on `Verdict` and goes with the rest of the
# duplication.
#
# The grammar is the adjudication above made executable. Everything it cannot parse is a
# write; every write-shaped construct the comment named — `-i` in either spelling or
# bundled, `-f`, `w`/`W`, `s///w`, `s///e`, the GNU `e` command, and the hidden-path
# `r`/`R` — is refused by code. It parses a conservative SUBSET of sed: address forms
# (line, `$`, `/re/` with modifiers, GNU `\c re c`, `+N`/`~N`/`FIRST~STEP`), groups, labels,
# text commands, `s` and `y` with their delimiters, and a closed set of single-letter
# commands. A real sed construct outside that subset costs a false refusal, never a hole —
# the same trade the head allowlist makes, one token stream down.
def _sed_scan_delimited(prog: str, i: int) -> int:
    """PROG[i] opens a delimited section (`/re/`, the pattern or replacement of `s`,
    one side of `y`). Return the index just past the CLOSING delimiter, or -1 if there
    is none. Backslash escapes the next char. A delimiter inside a bracket expression
    (`s/[/]/x/`) is NOT modelled: the misparse lands on an unknown token, and unknown
    fails closed."""
    d = prog[i]
    i += 1
    while i < len(prog):
        if prog[i] == "\\":
            i += 2
            continue
        if prog[i] == d:
            return i + 1
        i += 1
    return -1


def _sed_scan_to(prog: str, i: int, d: str) -> int:
    """Scan from PROG[i] to the next unescaped delimiter D (already known); return
    just past it, or -1 if there is none. The `s`/`y` sections after the first share
    the opening delimiter with the section before, so only the first can be found by
    `_sed_scan_delimited`."""
    while i < len(prog):
        if prog[i] == "\\":
            i += 2
            continue
        if prog[i] == d:
            return i + 1
        i += 1
    return -1


def _sed_skip_address(prog: str, i: int) -> int:
    """Skip ONE address at PROG[i]. Return the new index, I unchanged when no address
    starts here (not an error — the command is next), or -1 on a malformed one."""
    n = len(prog)
    if i >= n:
        return i
    ch = prog[i]
    if ch.isdigit():
        while i < n and prog[i].isdigit():
            i += 1
    elif ch == "$":
        i += 1
    elif ch in "+~":
        # GNU range tail standing alone: `addr1,+N` / `addr1,~N`.
        i += 1
        if i >= n or not prog[i].isdigit():
            return -1
        while i < n and prog[i].isdigit():
            i += 1
        return i
    elif ch == "/":
        i = _sed_scan_delimited(prog, i)
        if i < 0:
            return -1
        while i < n and prog[i] in "IM":  # GNU regex modifiers
            i += 1
    elif ch == "\\":
        # GNU `\cREc`: backslash, then any delimiter char.
        if i + 1 >= n:
            return -1
        i = _sed_scan_delimited(prog, i + 1)
        if i < 0:
            return -1
    else:
        return i
    # GNU `FIRST~STEP` suffix on a numeric or `$` address.
    if i < n and prog[i] in "+~":
        i += 1
        if i >= n or not prog[i].isdigit():
            return -1
        while i < n and prog[i].isdigit():
            i += 1
    return i


# Single-letter commands that can neither write a file, read a hidden one, nor execute.
_SED_SAFE_COMMANDS = set("pdDnPhHgGxlqQzv=")


def _sed_program_is_read_only(prog: str) -> bool:
    """True only when a sed program text cannot write, execute, or read a hidden path.

    Refused constructs, each named in the adjudication this parser replaces:
      `w`/`W file`   — write pattern/hold space to a file the redirect check never sees
      `s///w file`   — the same write as a substitute flag
      `s///e`        — execute the replacement as a shell command
      `e [cmd]`      — GNU: execute a shell command outright
      `r`/`R file`   — read a file whose path lives INSIDE the program, so it is
                       invisible to every argument-based check (thor's refutation case)
    """
    i, n, depth = 0, len(prog), 0
    while i < n:
        ch = prog[i]
        if ch in " \t\n;":
            i += 1
            continue
        if ch == "#":  # comment runs to end of line
            j = prog.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch == "}":
            if depth == 0:
                return False
            depth -= 1
            i += 1
            continue
        j = _sed_skip_address(prog, i)
        if j < 0:
            return False
        i = j
        if i < n and prog[i] == ",":
            j = _sed_skip_address(prog, i + 1)
            if j < 0 or j == i + 1:  # a comma with no second address is malformed
                return False
            i = j
        while i < n and prog[i] in " \t":
            i += 1
        if i < n and prog[i] == "!":
            i += 1
            while i < n and prog[i] in " \t":
                i += 1
        if i >= n:
            return False  # an address with no command is malformed
        c = prog[i]
        i += 1
        if c in _SED_SAFE_COMMANDS:
            continue
        if c == "{":
            depth += 1
            continue
        if c in "btT:":
            # Branch/label: the name runs to `;` or end of line and is data, not code.
            while i < n and prog[i] not in ";\n":
                i += 1
            continue
        if c in "aic":
            # GNU one-line form: the text is the REST OF THE LINE, semicolons included —
            # so a `w` appearing there is appended text in real sed too, and skipping it
            # misses nothing.
            j = prog.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "y":
            if i >= n:
                return False
            d = prog[i]
            i = _sed_scan_delimited(prog, i)   # first string, delimiters included
            if i < 0:
                return False
            i = _sed_scan_to(prog, i, d)       # second string, to the closing delimiter
            if i < 0:
                return False
            continue
        if c == "s":
            if i >= n:
                return False
            d = prog[i]
            i = _sed_scan_delimited(prog, i)   # pattern, delimiters included
            if i < 0:
                return False
            i = _sed_scan_to(prog, i, d)       # replacement, to the closing delimiter
            if i < 0:
                return False
            while i < n and prog[i] not in ";\n}":
                f = prog[i]
                if f in " \t":
                    i += 1
                    continue
                if f in "wWe":
                    return False  # s///w writes; s///e executes
                if f.isdigit() or f in "gpiImM":
                    i += 1
                    continue
                return False  # an unknown flag is a write
            continue
        return False  # w W r R e, and every command this parser does not model
    return depth == 0


def _sed_args_are_read_only(args: list[str]) -> bool:
    """True only when a sed ARGV (post-head tokens, quotes still on) is confidently
    read-only. Flags are checked one by one — `-ni` is `-i` — and every program text,
    whether positional or `-e`-supplied, goes through `_sed_program_is_read_only`.
    Input files are read, never written, by everything admitted here."""
    scripts: list[str] = []
    positional: list[str] = []
    from_expr = False
    i, n = 0, len(args)
    while i < n:
        a = args[i].strip("'\"")
        if a == "--":
            positional.extend(x.strip("'\"") for x in args[i + 1:])
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in ("in-place", "file"):
                return False
            if name == "expression":
                from_expr = True
                if eq:
                    scripts.append(val)
                else:
                    i += 1
                    if i >= n:
                        return False
                    scripts.append(args[i].strip("'\""))
            elif name in ("silent", "quiet", "null-data", "posix", "debug",
                          "regexp-extended", "extended-regexp", "separate",
                          "follow-symlinks", "sandbox", "unbuffered",
                          "help", "version"):
                pass
            elif name == "line-length":
                if not eq:
                    i += 1
                    if i >= n or not args[i].strip("'\"").isdigit():
                        return False
            else:
                return False
        elif a.startswith("-") and a != "-":
            cluster = a[1:]
            k = 0
            while k < len(cluster):
                f = cluster[k]
                if f in "nErsuz":
                    k += 1
                elif f == "l":
                    if k + 1 < len(cluster):
                        if not cluster[k + 1:].isdigit():
                            return False
                    else:  # the value is the next token
                        i += 1
                        if i >= n or not args[i].strip("'\"").isdigit():
                            return False
                    k = len(cluster)
                elif f == "e":
                    from_expr = True
                    if k + 1 < len(cluster):
                        scripts.append(cluster[k + 1:])
                    else:
                        i += 1
                        if i >= n:
                            return False
                        scripts.append(args[i].strip("'\""))
                    k = len(cluster)
                else:  # `i` and `f` land here, with everything unknown
                    return False
        else:
            positional.append(a)
        i += 1
    if not from_expr:
        if not positional:
            return False  # no program text at all
        scripts.append(positional[0])
        positional = positional[1:]
    return all(_sed_program_is_read_only(s) for s in scripts)


# Heads admitted only through their argument grammar. Checked BEFORE `_READ_ONLY_HEADS`
# in the segment walk, so the audit cannot be lost by someone appending the head to the
# bare set — the `_GUARDED_HEADS` principle, one column over.
_HEAD_GRAMMARS = {
    "sed": _sed_args_are_read_only,
}

# Separators that START A NEW COMMAND, and redirect operators. Enumerated rather than
# regex-matched, because the token stream below yields them as discrete tokens.
#
# `&` IS HERE (codex peer-review finding 4, 2026-08-02). It was not, so
# `ls & <mutating command>` was classified read-only from `ls` alone — a protection hole in
# the deployed gate, not classifier noise. codex withheld the peer factor over it.
#
# `"\n"` was DEAD TEXT from the day it was written until 2026-08-10. shlex counts a newline
# as whitespace and never emits one as a token, so this entry matched nothing and no newline
# ever started a new command — every line after the first arrived as ARGUMENTS to the first
# line's head, and `echo checking\ncp evil.py <gate>` was classified from `echo`. It is live
# now because `_command_lines` splits the TEXT first and the caller inserts one `"\n"` token
# per honoured newline. A membership test that cannot fire looks exactly like one that
# passes; this entry is why the fix below is a tokenizer change and not a set edit.
_SEPARATORS = {";", "&", "&&", "|", "||", "\n"}
_REDIRECTS = {">", ">>", "<", "<<", "<<<", ">&", "&>", ">|", "<&"}
# INPUT redirects create and modify nothing. Split out 2026-08-05, and the split is the
# narrow, provable half of a larger argument kimi-code and I have been having about the FP6
# remedy — "the redirect branch should return the write target". It cannot, for `<`: there
# is no write target, and `tee <gate> < evil.py` traced to THIS branch (not the head branch,
# as my forum table claimed) would hand a resolver `evil.py` as the thing being written.
#
# What that argument settles here, ahead of the resolver: treating `<` as a write is not
# conservative, it is just wrong, and it costs refusals. `grep foo < <gate>` was refused
# while `cat <gate>` was permitted — the same act, decided by spelling.
#
# `<<` and `<<<` take a DELIMITER or a literal, not a filename, so there is nothing to
# resolve there either. `<&` duplicates a descriptor for reading.
#
# The hole this could open, and why it does not: an input redirect that feeds an
# INTERPRETER (`sh < evil.sh`, `python3 < evil.py`) is still refused — by the head
# allowlist, which is where that danger actually lives, since `sh evil.sh` with no redirect
# at all is the same attack and was never caught by the redirect branch. The test asserts
# the migration rather than the verdict: `shell_reads_a_script` pairs `sh < evil.sh`
# (refused) with `cat < evil.sh` (permitted), and only a live head check makes that pair
# possible. Output redirects (`>`, `>>`, `>|`, `>&`, `&>`) are untouched.
_INPUT_REDIRECTS = {"<", "<<", "<<<", "<&"}
# `branch` and `remote` are NOT here (codex finding 1): `git branch -d` deletes a ref and
# `git remote add` rewrites repository config. A read-looking SUBCOMMAND with a mutating
# FLAG is exactly what a name allowlist cannot see.
_GIT_READ_SUBCOMMANDS = {"show", "diff", "log", "cat-file", "blame", "status", "rev-parse",
                         "describe", "ls-files", "ls-tree", "rev-list", "show-ref",
                         # Added 2026-08-10 (Sprint 5, the `_STILL_OPEN` git-read rows,
                         # kimi-code notice 1745 §3). Both are plumbing READS with no
                         # mutating spelling in any form — `merge-base` computes ancestry
                         # (`--is-ancestor` is the exit-status probe two members ran every
                         # wake and had refused beside a `rev-list` that read fine), and
                         # `for-each-ref` enumerates refs. A bare-set add is correct BECAUSE
                         # neither has a writing mode a flag could hide, unlike `branch`
                         # (creates from a positional) and `hash-object -w` (writes a blob),
                         # which is why those two stay OUT of this set and need a grammar.
                         "merge-base", "for-each-ref"}
# Read-BY-DEFAULT subcommands carrying a mutating flag get the _GUARDED_HEADS treatment one
# column over, rather than a bare-set append (claude-code §5.1, notice 1471, escalation
# 10fb8aa5c095c085): `git hash-object` only hashes, but `git hash-object -w` writes the blob
# into the object database. The flag, not the name, decides. Prefix match, same as there, so
# `-w` bundled or separated is caught alike.
_GIT_GUARDED_SUBCOMMANDS = {"hash-object": ("-w",)}

# Control-flow keywords, modelled 2026-08-07 (FP12, kimi-code; found by claude-code's
# isolating pair: `for f in a b; do grep -c def <gate>; done` REFUSED while
# `git show <rev>:<gate> | grep -c ""` ALLOWED — same governance path, same read, the
# only difference the loop). The mechanism: `for`/`do`/`done` are in no head list, so
# the segment walk returned False on the keyword and never reached the body head.
#
# The `cd` precedent does NOT transfer, and this is the load-bearing part. `cd` frees
# its own segment only, because the next segment is head-checked on its own head. `do`
# SHARES its segment with the body: admit `do` as a no-op head and
# `for x in a; do rm -rf /; done` is `[do, rm, -rf, /]`, head `do`, ALLOWED — the `rm`
# is never seen. The safe shape is a STRIP, not an admission: remove leading keywords,
# then head-check what remains. The red arm (`do rm`, `then tee`, `done > f`) is in
# `_SURVIVE`; a green on the false-refusal rows alone would certify the hole.
_CONTROL_FLOW_BODY = {"do", "then", "else"}        # the remainder is the body command
_CONTROL_FLOW_COND = {"if", "elif", "while", "until"}  # the remainder EXECUTES (the condition)
_CONTROL_FLOW_CLOSE = {"done", "fi", "esac"}       # a segment of closers runs nothing
_FOR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _has_live_substitution(text: str) -> bool:
    """True when `text` carries a command substitution bash would EXECUTE.

    FP14 (claude-code, escalation c80e4a2557df241b, 2026-08-08): the guard this
    replaces was a substring test on posix=False tokens — `"$(" in t` — so a grep
    PATTERN that names substitution (`grep -n "=\\$(\\|…" <gate>`, where `\\$` is a
    literal dollar to bash) refused exactly like a live one. posix=False had already
    preserved the quoting that separates the two; the check just never read it. It
    is also the one FP its own search cannot find: grepping the gate for `$(` trips
    the check being searched for.

    Quoting is a STATE, not a substring, so walk it. Inert by bash's rules: anything
    inside single quotes, and a backslash-escaped character (any character unquoted;
    inside double quotes only before $ ` " \\ or newline). Live everywhere else,
    INCLUDING inside double quotes — `"$(id)"` runs. The walk runs on raw text, not
    on tokens: punctuation splitting puts the `$(` of `a$(id)b` across two tokens,
    where no per-token test can see it whole, and a leading quote hid a backtick
    from the old startswith test. Both were live bypasses; the walk closes them.

    Unterminated quoting cannot reach here — the caller's tokenizer has already
    failed closed on it — but the walk answers True for it anyway: an unresolved
    quote means the quoting was never decided, and undecided means write.
    """
    state = ""  # "", "'" or '"' — the quoting the walk is inside
    i = 0
    while i < len(text):
        c = text[i]
        if state == "'":
            if c == "'":
                state = ""
        elif state == '"':
            if c == '"':
                state = ""
            elif c == "\\" and text[i + 1:i + 2] in ('$', '`', '"', "\\", "\n"):
                i += 1
            elif c == "`" or text[i:i + 2] == "$(":
                return True
        else:
            if c == "'" or c == '"':
                state = c
            elif c == "\\":
                i += 1
            elif c == "`" or text[i:i + 2] == "$(":
                return True
        i += 1
    return state != ""


def _control_flow_remainder(parts):
    """Strip leading shell control-flow keywords from one segment.

    Returns the remaining command tokens to head-check; [] for a segment that carries
    NO command (a bare closer, or a `for VAR [in WORDS]` / `case WORD in` header —
    the words are data, globbed at most, never executed); or None for a keyword shape
    this grammar does not model, which the caller must treat as a WRITE, because
    unparseable input is a write.

    `if`/`while`/`until`/`elif` strip to their CONDITION, not past it: the condition
    really runs, so `if rm -rf /; then ...; fi` refuses on `rm`. `case` arms
    (`pattern) body ;;`) stay unmodelled and refuse on their own segments — fail
    closed, not a hole: the header skip runs nothing by itself.
    """
    p = list(parts)
    while p:
        w = p[0]
        if w in _CONTROL_FLOW_BODY or w in _CONTROL_FLOW_COND:
            p.pop(0)
            continue
        if w in _CONTROL_FLOW_CLOSE:
            return [] if len(p) == 1 else None
        if w == "for":
            if (len(p) >= 2 and _FOR_NAME.match(p[1])
                    and p[1] not in _CONTROL_FLOW_BODY
                    and p[1] not in _CONTROL_FLOW_COND
                    and p[1] not in _CONTROL_FLOW_CLOSE and p[1] != "in"
                    and (len(p) == 2 or p[2] == "in")):
                return []
            return None
        if w == "case":
            return [] if len(p) == 3 and p[2] == "in" else None
        return p
    return []


def _assignment_remainder(parts):
    """Consume leading NAME=VALUE assignment prefixes from one segment.

    FP13 (claude-code, notice 1474 §1): the head check read `G=<path>` as a COMMAND —
    basename(`G=<gate>`) is the gate's own filename, which sits in no head list, so a
    member spelling a read of its own law through a variable was refused as a WRITE
    and minted an escalation (the matched pair: `grep … <gate>` permitted,
    `G=<gate>; grep … "$G"` refused). In shell grammar a leading NAME=VALUE token is a
    PREFIX, not the command — it runs nothing by itself. So consume leading
    assignments and head-check what follows; the empty case (`G=x` alone) runs
    nothing and is read-only.

    A prefix is only free when it is INERT. A command substitution inside the value
    EXECUTES — `G=`rm -rf …`` runs the rm — so a value carrying a LIVE one fails
    closed here rather than being consumed. Liveness is `_has_live_substitution`'s
    call, not a substring test: an escaped or quoted substitution SPELLING in the
    value is data (FP14), and `G=\`id\`` must not refuse the read that follows it.
    (The single-quoted `$(` twin never reaches this check: shlex's punctuation_chars
    mode raises "No closing quotation" on a mid-token quote and the classifier fails
    closed in the tokenizer — safe, and one layer below this one.)

    A consume, NOT a merge into `_control_flow_remainder` (1474 §1): `for` and
    `NAME=` have different arities, and one shared strip is how `do rm -rf /` gets
    freed. The red arm is `assignment_does_not_launder` in `_SURVIVE`; the control
    proves the sed grammar still decides what follows the prefix.
    """
    p = list(parts)
    while p and _ASSIGNMENT.match(p[0]):
        if _has_live_substitution(p[0]):
            return None  # a substitution in the VALUE runs; fail closed
        p.pop(0)
    return p


# Characters after which an unquoted `#` OPENS A COMMENT, plus the start of a line. Bash
# begins a comment only at the start of a WORD: `echo a#b; echo two` prints both lines
# (measured against bash 2026-08-10), because `a#b` is one literal word and the `;` after it
# is a real separator.
#
# DELIBERATELY NARROWER THAN BASH, which also breaks a word at a redirection operator. The
# asymmetry is the safe direction and it is worth stating why: a `#` this set fails to
# recognise is text that is KEPT, tokenised and head-checked, so a miss can only ADD a
# refusal — never drop a command from the walk. A `#` recognised too eagerly discards the
# rest of the line unclassified, which is the bypass shape. `>` is the concrete case left
# out: `echo hi >#f` redirects into a file literally named `#f`, so calling that `#` a
# comment would drop a real write target on the floor.
_COMMENT_OPENS_AFTER = frozenset(" \t\r\f\v;&|")


def _command_lines(text: str) -> list[str]:
    """Split raw command TEXT into the logical lines bash would run, in order.

    THE HOLE THIS CLOSES (found by claude-code 2026-08-08, escalation 4a3e6f6838acabad;
    fixed by LEGION 2026-08-10 claiming CBP's 0015 offer). `_SEPARATORS` has listed `"\\n"`
    since it was written, but the caller's `shlex` treats a newline as whitespace and never
    emits it as a token, so the entry matched nothing. No newline ever split a segment:
    every line after the first arrived as ARGUMENTS to line one's head. So

        echo checking
        cp evil.py <the gate>

    was classified from `echo` alone — read-only, permitted, and the `cp` overwrote the
    enforcing gate with no `gate_self_access` event, no witness and no approval. A silent
    write to the thing that governs writes is the one class worse than a false refusal.

    WHY THE SPLIT IS ON TEXT AND NOT ON TOKENS. Three constructs make the newline
    unrecoverable once shlex has run, and each is a red arm in
    `gate_false_refusal_test.py`:

      - a QUOTED newline is data (`grep -c 'a\\nb' <gate>`), so a blind `text.split("\\n")`
        cuts a pattern in half and leaves an unbalanced quote — a legitimate read refused
        for being multi-line;
      - a `\\`-newline is ONE logical line, so splitting there leaves the gate's PATH
        standing alone as a segment, and `basename` of it is a head no list carries. That
        is FP13's exact shape (`assignment_prefix_is_not_a_head`), reintroduced by the fix
        meant to close a hole;
      - a COMMENT is consumed by shlex THROUGH the end of the line, separator included, so
        by the time there is a token stream the newline after `# note` is already gone.

    AND THE COMMENT RULE HAD TO COME WITH IT, not after it. shlex's `commenters` eats from
    `#` to end of LINE — and a `;` sits on the line, so the comment never needed a newline
    to swallow a separator: `echo a#b; cp evil.py <gate>` was permitted with the `cp`
    entirely unseen, while bash ran it. Splitting on newlines does not touch that; line one
    is the whole command. So the caller sets `commenters = ""` and the rule moves here,
    where the word-start test that separates bash's comment from bash's literal can actually
    be applied. The two directions are pinned as a PAIR —
    `mid_word_hash_is_not_a_comment` must refuse, `word_start_comment_still_comments` must
    stay permitted — because a fix that just refuses anything containing `#` passes the
    first and fails the second, and only the pair says which one happened.

    The quoting walk here follows `_has_live_substitution`'s rules character for character
    (single quotes inert; inside double quotes a backslash escapes only `$` `` ` `` `"` `\\`
    and newline; unquoted backslash escapes anything). That is deliberate duplication of
    SHAPE, not of code: it cannot call that function, which answers one bool about the whole
    string, but two quote walkers in one classifier that disagreed about where a quote ends
    would be a bypass generator. Change one, read the other.

    Unterminated quoting is NOT resolved here — the walk simply ends inside the quote and
    the offending line goes back to the caller with the quote still open, where the
    tokenizer raises and fails closed. One place decides that, and it is the same place as
    before this function existed.
    """
    lines: list[str] = []
    buf: list[str] = []
    state = ""            # "", "'" or '"' — the quoting the walk is inside
    at_word_start = True  # a `#` here opens a comment; mid-word it is a literal
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if state == "'":
            buf.append(c)
            if c == "'":
                state = ""
            at_word_start = False
        elif state == '"':
            if c == "\\" and text[i + 1:i + 2] in ('$', '`', '"', "\\", "\n"):
                buf.append(text[i:i + 2])
                at_word_start = False
                i += 2
                continue
            buf.append(c)
            if c == '"':
                state = ""
            at_word_start = False
        elif c == "\\":
            nxt = text[i + 1:i + 2]
            if nxt == "\n":
                # Line continuation. Bash removes BOTH characters and the lines become one,
                # so emit nothing and do NOT touch `at_word_start` — `ec\<nl>ho` is `echo`,
                # one word across the join.
                i += 2
                continue
            if nxt:
                buf.append(text[i:i + 2])
                at_word_start = False
                i += 2
                continue
            buf.append(c)  # a lone trailing backslash; hand it on unchanged
            at_word_start = False
        elif c == "\n":
            lines.append("".join(buf))
            buf = []
            at_word_start = True
        elif c == "#" and at_word_start:
            # Discard through the end of the line, the newline EXCLUDED so the line still
            # separates. That exclusion is the whole `comment_does_not_eat_the_separator`
            # row: shlex's version consumed the newline with the comment.
            while i < n and text[i] != "\n":
                i += 1
            continue
        else:
            buf.append(c)
            if c == "'" or c == '"':
                state = c
                at_word_start = False
            else:
                at_word_start = c in _COMMENT_OPENS_AFTER
        i += 1
    lines.append("".join(buf))
    return lines


def _is_read_only(tool_name: str, tool_input: Any) -> bool:
    """True only when the call is CONFIDENTLY read-only. Ambiguity means write.

    TOKENISED, NOT SPLIT (codex peer review, 2026-08-02). The previous version split raw
    command TEXT, so a quoted operator was indistinguishable from a real one:
    `grep -E "a|b" f` split inside its own quotes, and `grep ">" f` tripped a substring
    test for `>`. That is the #116 quoted-token class, and an earlier draft of this widening
    made it worse rather than better.

    `shlex` with `posix=False` is the fix as a CLASS rather than as more special cases: it
    preserves quoting, so a quoted `|` or `>` arrives as one data token (`'"a|b"'`) and can
    never be read as syntax. `posix=True` would strip the quotes and silently keep the bug —
    the trap this nearly walked into.

    codex's structural point, which is why this is a rewrite and not another list:

        "shell syntax is exceeding what a string splitter can safely model. If this
         classifier stays lexical, its supported grammar needs to be explicit and everything
         outside that grammar must remain a write. Another growing list of heads and
         separators will keep alternating false denial and bypass."

    So the grammar is explicit and CLOSED: enumerated separators, enumerated redirects,
    enumerated control-flow keywords, enumerated heads. Unparseable input is a write.
    Unknown syntax is a write. Command substitution is a write. The aim is to stop
    calling `2>/dev/null` a file write — not to make the classifier clever.
    """
    if tool_name in _READ_ONLY_TOOLS:
        return True
    if tool_name in _WRITE_TOOLS:
        return False
    if tool_name not in {"Bash", "Shell"}:
        return False
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(cmd, str) or not cmd.strip():
        return False

    # Imported here rather than at module scope: this hook is on the agent's critical path
    # with an 800ms budget, and `shlex` is only needed on the Bash branch.
    import shlex

    # ONE TOKENIZER PER LOGICAL LINE, with an explicit `"\n"` token between them — one per
    # newline `_command_lines` honoured. shlex cannot do this itself: it counts a newline as
    # whitespace, so a single pass over the whole command emits no separator and every line
    # after the first becomes argv to line one's head (the bypass above). Tokenising per line
    # is also what makes `commenters = ""` safe — the comment rule now lives in
    # `_command_lines`, where bash's word-start test can be applied, instead of in a
    # tokenizer that eats to end-of-line and takes any `;` on that line with it.
    tokens: list[str] = []
    try:
        for idx, line in enumerate(_command_lines(cmd)):
            if idx:
                tokens.append("\n")
            lx = shlex.shlex(line, posix=False, punctuation_chars=True)
            lx.whitespace_split = True
            lx.commenters = ""
            tokens.extend(lx)
    except ValueError:
        # Unbalanced quotes: we cannot know what this runs. Fail closed. Still decided in
        # exactly one place, and a quote `_command_lines` left open arrives here to be
        # refused rather than being resolved by a second, divergent walk.
        return False
    if not tokens:
        return False

    # Command substitution runs arbitrary code and its contents are never walked below.
    # Checked on the RAW command, with quoting walked as a state — not as a substring
    # test on tokens (FP14): posix=False preserves the quoting, so `grep -n "=\$(\|…"
    # <gate>` is data bash passes through, and the old test could not tell it from the
    # live case. The raw walk also sees what no per-token test can: `a$(id)b`, split
    # across tokens by punctuation_chars, and a backtick behind a leading quote.
    if _has_live_substitution(cmd):
        return False

    segments: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _SEPARATORS:
            segments.append([])
            i += 1
            continue
        if t in _REDIRECTS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            # An input redirect writes nothing; consume it and its operand. The operand is
            # a source file, a heredoc delimiter or a literal — never a destination — so it
            # must not fall through and be head-checked as if it started a command.
            if t in _INPUT_REDIRECTS:
                i += 2
                continue
            # fd duplication (`2>&1`) and `/dev/null` write no file. Everything else does.
            if t in {">&", "&>", "<&"} and nxt and nxt.isdigit():
                i += 2
                continue
            if nxt == "/dev/null":
                i += 2
                continue
            return False
        segments[-1].append(t)
        i += 1

    for parts in segments:
        if not parts:
            continue
        parts = _control_flow_remainder(parts)
        if parts is None:
            return False
        parts = _assignment_remainder(parts)
        if parts is None:
            return False
        if not parts:
            continue
        head = os.path.basename(parts[0].strip("'\""))
        if head == "git":
            if len(parts) < 2:
                return False
            if parts[1] in _GIT_GUARDED_SUBCOMMANDS:
                if any(a.startswith(f) for a in parts[2:] for f in _GIT_GUARDED_SUBCOMMANDS[parts[1]]):
                    return False
            elif parts[1] not in _GIT_READ_SUBCOMMANDS:
                return False
        elif head in _HEAD_GRAMMARS:
            # Admitted by head, audited by arguments. BEFORE the bare set, so an append
            # there can never bypass the grammar — `sed` in `_READ_ONLY_HEADS` would be
            # dead text, not a hole.
            if not _HEAD_GRAMMARS[head](parts[1:]):
                return False
        elif head in _GUARDED_HEADS:
            # Read-only only without its writing flags. Prefix match so `-exec`,
            # `-execdir` and `--output=x` are all caught.
            if any(a.startswith(f) for a in parts[1:] for f in _GUARDED_HEADS[head]):
                return False
        elif head not in _READ_ONLY_HEADS:
            return False
    return True


def _emit_gate_event(event_type: str, marker: str, tool_name: str, *, severity: str) -> bool:
    """Append a governance-surface event. Best effort, short budget.

    One emitter, two callers, DISTINCT event types — `gate_self_access` for a refused
    write, `gate_self_read` for a permitted read. Collapsing them into one type would make
    an alert on the refusal meaningless, since permitted reads are ordinary conduct and
    refused writes are not.

    Written against `McpHttp` as it actually exists. An earlier draft invented a
    `DaemonClient(budget_s=).connect()/.call()` that appears nowhere — the same
    reach-for-a-plausible-API reflex that produced `web4:observationCount` and an invented
    ontology namespace. Checked, then written.
    """
    endpoint = discover_endpoint()
    if endpoint is None:
        return False
    client = McpHttp(endpoint, time.monotonic() + 1.5)
    try:
        if "result" not in client.initialize():
            return False
        client.initialized()
        conn = client.call_tool(
            "hestia_connect",
            {"plugin_id": PLUGIN_ID, "host_agent": HOST_AGENT, "instance_name": "gate-self"},
        )
        sid = None
        res = conn.get("result") if isinstance(conn, dict) else None
        if isinstance(res, dict):
            content = res.get("content") or []
            if content and isinstance(content[0], dict):
                try:
                    sid = json.loads(content[0].get("text") or "{}").get("sessionId")
                except (json.JSONDecodeError, AttributeError):
                    sid = None
        if not sid:
            return False
        out = client.call_tool(
            "hestia_request_witness",
            {
                "session_id": sid,
                "event_type": event_type,
                "event_data": {
                    "plugin_id": PLUGIN_ID,
                    "tool_name": tool_name,
                    "marker": marker,
                    "gate_path": _SELF,
                    "severity": severity,
                },
            },
        )
        return isinstance(out, dict) and "result" in out
    except Exception:  # noqa: BLE001 — the record must never block the decision
        return False


def _witness_self_read(marker: str, tool_name: str) -> bool:
    """Record a PERMITTED read of the governance surface.

    A member may inspect what governs it — that is the publish-the-law posture, and
    refusing it would make a member unable to check its own law. Recording keeps the
    reconnaissance signal: repeated reads of gates remain visible as a pattern.

    A failed witness never blocks the read. Turning a recording failure into a denial
    would make the daemon's health a precondition for reading one's own law."""
    return _emit_gate_event("gate_self_read", marker, tool_name, severity="record")


def _witness_self_access(marker: str, tool_name: str) -> bool:
    """Record a REFUSED write to the governance surface. Escalatable."""
    return _emit_gate_event("gate_self_access", marker, tool_name, severity="escalate")


_PATH_KEYS = ("file_path", "path", "notebook_path")


def _describe_hit(marker: str, resource: Optional[str], key: Optional[str],
                  dest: Optional[str] = None) -> str:
    """The ACT, for the human who rules on the record — not the rule that fired.

    5.2 (claude-code, notice 1474 §2/§3): every human-facing string on this path used
    to describe the gate's internal state — the marker that matched — where it
    promised the caller's act. The marker stays, as the REASON; the resource is what
    the call would actually reach. A match inside TEXT (`command`/`new_string`/
    `content`) is reported as payload content, not a destination — the FP8 case,
    where the "write to the governance surface" was a forum post quoting it.
    """
    if resource is None:
        return f"the governance surface (matched marker {marker!r})"
    if key in _PATH_KEYS:
        return f"{resource} (matched governance marker {marker!r})"
    short = resource if len(resource) <= 200 else resource[:200] + "…"
    if dest:
        return (f"{dest} — its {key} text matched governance marker {marker!r}; the "
                f"match is payload content, not the destination: {short!r}")
    return (f"a command carrying governance marker {marker!r} in its {key or 'text'} "
            f"text: {short!r}")


def deny_self_access(marker: str, tool_name: str, resource: Optional[str] = None,
                     key: Optional[str] = None, dest: Optional[str] = None) -> int:
    """Refuse, loudly, and try to witness it as its own event class.

    Deliberately NOT an ordinary deny: an ordinary deny is a boundary met in the
    course of work. This is an attempt to reach the mechanism that draws the
    boundaries, which is evidence about intent rather than about scope — so it
    gets its own event type so an operator can alert on it separately, and so it
    cannot be lost in the volume of routine refusals.

    Witnessing is BEST EFFORT and the refusal does not depend on it: if the
    daemon cannot be reached, the act is still refused and stderr still says so.
    An unwitnessed refusal is a worse record, never a permission."""
    witnessed = False
    try:
        witnessed = _witness_self_access(marker, tool_name)
    except Exception:  # noqa: BLE001 — never let the record attempt block the refusal
        witnessed = False
    sys.stderr.write(
        f"hestia: deny [gate-self-access] — {tool_name} would WRITE to "
        f"{_describe_hit(marker, resource, key, dest)}. An agent that can edit the "
        f"thing that governs it is not governed. "
        f"Reading it is allowed and witnessed; changing it is not. This refusal is its own "
        f"event class{'' if witnessed else ' (WITNESS FAILED — the refusal stands regardless)'}"
        f" and is escalatable.\n"
        f"If a gate change is genuinely needed, ESCALATE — the write is offered to a human "
        f"for approval and proceeds only if one approves inside the window. Say what you "
        f"need changed and why. Do not work around this by another route: doing so is the "
        f"behaviour this rule exists to make visible.\n"
    )
    debug_log(f"gate-self-access deny: {tool_name} -> {resource or marker} "
              f"(marker {marker}) witnessed={witnessed}")
    return 2


# ---- Stage 2: escalate a governance WRITE to a human ------------------
#
# dp, 2026-07-29: "escalate to human for approval (there are legit times when we are
# actually working on the file), deny on timeout of a couple minutes."
#
# Stage 1 (#97) refuses every write to the governance surface. That is correct and it is
# also too much -- the fleet legitimately edits its gates (#55, #89, #90 in one week). This
# is the channel that un-refuses a legitimate one, with a human across it.

# The claim call must finish well inside the harness's 5s budget for the WHOLE hook, which
# also has to cover the ordinary policy verdict. Sized for a loopback call to a local daemon,
# not for a human.
# (A 5.0 assignment preceded this one from the constant's introduction in 5e15636 (#114)
# and was shadowed by it for the constant's entire life -- 1.5 has always been the value
# in force. Removed 2026-08-05; zero behaviour change.)
ESCALATION_RPC_TIMEOUT_S = 1.5


def _attempted_summary(tool_name: str, tool_input: Any) -> str:
    """WHAT was attempted, in one bounded line, for the human who has to rule on it.

    dp, 2026-08-03, after approving several in a row: *"the issue remains that they don't
    tell me what i'm approving or why. they just say 'no reason'."* The dashboard renders
    `why: (none stated — decide on the payload alone)` and then shows no payload.

    They said no reason because nothing ever sent one. The daemon has accepted the operator's
    two questions on the claim path since 2026-08-02 and this hook never populated them — the
    call sent `plugin_id`, `role`, `tool_name`, `marker` and stopped. So an operator saw
    `Edit` and a directory name and was asked to decide, which is identical whether the
    command was `sed -n '470,520p'` or `rm -rf`. A live channel with nothing in it.

    **THE WIRE ARGUMENTS ARE `reason` AND `detail`.** Not `stated_reason` / `stated_detail` —
    those are only how the daemon STORES and re-emits them, in the `gate_escalation_opened`
    chain entry and in `hestia_gate_pending_escalations`. An earlier draft of this docstring
    named the stored pair, and codex caught it before it could mislead anyone (NOT-SAME review
    of #175). The consequence would have been silent and permanent: hestia tools are
    `additionalProperties: true`, so sending two keys nobody reads SUCCEEDS, the escalation is
    filed, and the operator surface renders "why: (none stated)" forever — the exact bug this
    function exists to fix, reintroduced by the comment describing the fix.

    kimi's and codex's gates already send an attempted summary — it is why kimi's denials
    render with the full command and this member's do not. **This is the drift the shared
    core exists to end, and it drifted in the direction that costs the operator.** Written
    here rather than only in `hestia_gate_core.py` because the core is not wired yet and
    the cost is being paid now; when the shims land it belongs on `Verdict` and this copy
    should go with the rest of the duplication.

    BOUNDED AND SELF-CENSORING. Truncated hard, because an escalation body is read by a
    human under interruption. Redacted on credential-shaped tokens, because a refusal is not
    a licence to copy a payload into the witness chain: an egress deny is ABOUT a secret
    path, so verbatim echo would reproduce the protected thing inside a record that is
    deliberately easier to read than the file was.
    """
    if not isinstance(tool_input, dict):
        return f"{tool_name} (no inspectable input)"
    raw = tool_input.get("command")
    if not isinstance(raw, str):
        for k in ("file_path", "path", "notebook_path"):
            v = tool_input.get(k)
            if isinstance(v, str):
                # THE PATH FALLBACK IS REDACTED TOO (kimi #185, finding 2). It returned the
                # path bare. Lower risk than a command — paths, not contents — but a path can
                # BE the secret, and an inconsistent rule is one a reader cannot rely on.
                # Confirmed leaking before this existed.
                if _credential_shaped(v):
                    return (f"{tool_name} [REDACTED — the target is a credential-shaped path; "
                            f"{len(v)} chars withheld rather than copied into the record]")
                return f"{tool_name} -> {v[-140:]}"
        return f"{tool_name} (no command or path in input)"
    s = " ".join(raw.split())
    if _credential_shaped(s):
        return (f"{tool_name} [REDACTED — names a credential-shaped token; "
                f"{len(s)} chars withheld rather than copied into the record]")
    return f"{tool_name}: {s[:220]}" + (" …" if len(s) > 220 else "")


#: Shapes that carry secrets in a real shell command — not merely filenames that suggest one.
#:
#: kimi NOT-SAME review of #185, finding 2. The first list held key-material filenames and a
#: few English nouns, and a red test confirmed SEVEN shapes passing through verbatim into the
#: signed, hash-chained record: `Authorization:`/`Bearer` headers, `--password=` flags,
#: `PASSWORD=` assignments, ssh config paths, PEM `BEGIN` blocks, bare `bearer`, and the
#: unredacted path fallback.
#:
#: WHY THIS IS AN EGRESS SURFACE AT ALL, which I did not see when I wrote it: before this
#: function, nothing from a denied command was sent anywhere. It is the change that STARTS
#: copying command text into the witness chain — so it introduces the leak it must then
#: prevent. And a witnessed record is deliberately easier to read, and harder to expunge, than
#: the file the deny was protecting. Redaction here is not hygiene; it is the reason the
#: feature is safe to have.
#:
#: Substring matching on a lowered string, deliberately: a regex over attacker-shaped command
#: text is its own hazard, and the cost of a false positive is one unhelpfully-vague escalation
#: while the cost of a false negative is a secret in the permanent record. Asymmetric, so this
#: errs loud. `test_ordinary_commands_are_not_redacted` bounds the over-matching.
_CREDENTIAL_SHAPES = (
    # key material and its filenames
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".pem", ".p12", ".pfx",
    "begin rsa private key", "begin openssh private key", "begin private key",
    "begin ec private key", "begin certificate",
    # ssh / gpg config trees — a path can be the secret
    "/.ssh", ".ssh/", "/.gnupg", ".netrc", ".pgpass", ".htpasswd",
    # http auth
    "authorization:", "authorization ", "bearer ", "x-api-key", "proxy-authorization",
    # generic secret words, and the flag/env spellings that actually appear
    "password", "passwd", "passphrase", "credential", "secret", "api_key", "apikey",
    "access_key", "access-key", "private_key", "private-key", "client_secret",
    "token=", "_token", "auth_token", "session_token", "refresh_token",
    ".env", "dotenv",
)


def _credential_shaped(text: str) -> bool:
    """Does this text plausibly carry a secret? Substring, lowered, no regex.

    One helper for both the command and the path branch so the two cannot drift — the
    inconsistency kimi flagged was exactly that they already had."""
    low = text.lower()
    return any(shape in low for shape in _CREDENTIAL_SHAPES)


def _connect_session(client: "McpHttp", host_session_id: Optional[str]) -> Optional[str]:
    """A live daemon session id for the escalation claim, or None — never raises.

    WHO is asking, provable. The claim path accepts an optional `session_id`
    (handler.rs `tool_gate_escalation_claim`): a session that resolves turns
    `asker_basis` from "asserted" into "session", and a proven asker is what lets
    the invitation actually WAKE the peers it records — until now every
    claim-path escalation recorded peers and woke nobody (kimi-code census over
    the full 114,819-entry chain: `asker_basis` on 0 of 362, claude-code notice
    1530's remainder).

    The daemon's own note said to thread the session `ask_daemon` "already
    holds" — but self-protection runs BEFORE `ask_daemon` in `main`, by design
    ("before the daemon, and never conditional on it"), so at this point in the
    invocation no session exists. This is therefore a real connect, one extra
    loopback round trip inside the escalation budget — not a thread-through.

    `plugin_id` is `_escalation_plugin_id()`, the same value the claim asserts:
    the daemon refuses a claim whose plugin_id disagrees with the session's
    (asker mismatch is the forgery the binding exists to catch), so the two must
    be one value. `host_session_id` keeps connect idempotent across hook
    invocations — one Claude session, one hestia session — matching ask_daemon.

    None means "proceed unproven": session_id is optional on the claim and an
    asserted escalation is paperwork, while a missing one is silence. Failure
    here must degrade the RECORD, never the channel.
    """
    try:
        args: dict[str, Any] = {
            "plugin_id": _escalation_plugin_id(),
            "plugin_version": HOOK_VERSION,
            "host_agent": HOST_AGENT,
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
        }
        role = os.environ.get("HESTIA_ROLE")
        if role:
            args["role"] = role
        if host_session_id:
            args["host_session_id"] = host_session_id
        conn = unwrap_tool_result(client.call_tool("hestia_connect", args))
        sid = conn.get("sessionId")
        return sid if isinstance(sid, str) and sid else None
    except Exception:  # noqa: BLE001 — see the docstring: degrade the record, not the channel
        return None


def request_self_write(marker: str, tool_name: str, attempted: str = "",
                       resource: Optional[str] = None, key: Optional[str] = None,
                       dest: Optional[str] = None,
                       host_session_id: Optional[str] = None) -> Tuple[str, str]:
    """One round trip. Returns (verdict, detail); only 'approved' permits the write.

    `marker` is what the daemon keys the approval on and is NOT the human-facing
    destination: `resource`/`key`/`dest` describe the attempted ACT for the record
    (5.2, notice 1474 §2) — see `_describe_hit`.

    THIS FUNCTION NEVER WAITS, and that is the whole design. The harness kills this hook at 5
    seconds, and a killed hook yields neither `exit 2` nor a JSON deny -- Claude Code reads
    that as a non-blocking error and runs the tool anyway. An in-hook wait for a human
    therefore fails OPEN: the write executes unapproved, with an escalation entry on the chain
    making it look like the safe path ran. That is strictly worse than refusing outright.

    So: ask once. Either a human has already approved this exact (member, governance file) and
    the approval is spent here, or the write is refused now and a human decides out of band.
    The member then RE-ISSUES the write, and that second attempt claims the approval.

    Every failure -- unreachable, malformed, an old daemon that has never heard of this tool --
    is a refusal. A daemon that cannot answer must not be a way to get a governance write
    through.
    """
    try:
        endpoint = discover_endpoint() or DEFAULT_ENDPOINT
        client = McpHttp(endpoint, deadline=time.monotonic() + ESCALATION_RPC_TIMEOUT_S)
        client.initialize()
        client.initialized()
        claim_args: dict[str, Any] = {
            "plugin_id": _escalation_plugin_id(),
            "role": os.environ.get("HESTIA_ROLE", ""),
            "tool_name": tool_name,
            "marker": marker,
            # WHAT was attempted. The daemon has accepted these two since 2026-08-02 and
            # this call never sent them, which is why every escalation rendered
            # "why: (none stated — decide on the payload alone)" and then displayed no
            # payload. dp, 2026-08-03: "they don't tell me what i'm approving or why."
            #
            # `reason` carries the ATTEMPTED ACT, not a rationale, and the distinction is
            # deliberate: an auto-opened escalation HAS no stated why, because the member
            # did not choose to escalate — the gate opened it on their behalf after a deny.
            # Presenting the act as though it were a rationale would be worse than silence,
            # because it would look like the member had explained itself. A member that
            # wants to state a why calls `hestia_gate_escalation_open` and supplies one.
            "reason": attempted or f"{tool_name} -> {resource or marker}",
            "detail": (
                "Auto-opened by the gate on a refused write; the member stated no rationale "
                "because it did not choose to escalate. Approving authorises this one write."
            ),
        }
        # WHO is asking, provable — see `_connect_session`. Absent on any failure:
        # the claim accepts its absence and records `asker_basis: "asserted"`.
        sid = _connect_session(client, host_session_id)
        if sid:
            claim_args["session_id"] = sid
        r = client.call_tool("hestia_gate_escalation_claim", claim_args)
    except Exception as e:  # noqa: BLE001
        return "unreachable", f"no answer from the daemon ({type(e).__name__}) -- refused"

    # BOTH flags, and the daemon owns both. Two places deciding what "approved" means is how
    # they come to disagree, so the hook re-derives nothing.
    if _dig(r, "claimed") is True and _dig(r, "permits_write") is True:
        who = _dig(r, "decided_by") or "a human"
        via = _dig(r, "decided_via") or "unknown-channel"
        return "approved", f"claimed an approval from {who} via {via} (single use, now spent)"

    esc_id = _dig(r, "escalation_id")
    if not esc_id:
        # An old daemon answers {} to a tool it does not know. It must not be able to permit a
        # write by failing to understand the question -- but it also cannot open an escalation,
        # so say which of the two this is rather than implying paperwork exists.
        why = _dig(r, "error") or "this daemon has no escalation channel (is it upgraded?)"
        return "no-channel", f"refused, and NO escalation was opened -- {why}"

    how = _dig(r, "how_to_decide") or f"hestia gate approve {esc_id}"
    retry_secs = _dig(r, "retry_within_secs")
    sys.stderr.write(
        f"hestia: ESCALATION {esc_id} opened — {tool_name} would WRITE to "
        f"{_describe_hit(marker, resource, key, dest)}.\n"
        f"  THE WRITE IS REFUSED. Nothing is waiting: a human decides out of band.\n"
        f"  To allow:  {how}\n"
        f"  Then RE-ISSUE the same write"
        + (f" within {retry_secs}s" if retry_secs else "")
        + " and it will claim the approval (single use).\n"
    )
    sys.stderr.flush()
    return "escalated", f"escalation {esc_id} opened; write refused pending a human decision"


def _escalation_plugin_id() -> str:
    """Who to record as asking. Caller-asserted (HST-005) and named as such.

    The env vars stay the override -- a mesh fire sets HESTIA_MESH_PLUGIN so the escalation
    names the member being fired, which may differ from this file's own.

    The fallback is PLUGIN_ID, not a literal 'unattributed' (#244). The 'unattributed'
    fallback was defended by #108's rationale -- guessing one member's id under another's
    name -- but PLUGIN_ID is not a guess: it is the module constant this same file already
    asserts as its identity at hestia_connect. Worse than a provenance gap, the literal
    collapsed claim()'s (plugin_id, marker) join key to a constant: every escalation from
    an interactive session (which exports HESTIA_ROLE but no plugin id) was filed under the
    SAME 'unattributed', so an operator's approval was claimable by any interactive session
    resolving to the same marker -- and, once the claim path threads a session through, the
    proven session ('claude-code') disagrees with the asserted 'unattributed' and every
    such approval is REFUSED as an asker mismatch. One literal, both failure directions.
    """
    for var in ("HESTIA_MESH_PLUGIN", "HESTIA_PLUGIN_ID"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    return PLUGIN_ID


def _dig(result: Any, key: str, _depth: int = 0) -> Any:
    """Find `key` anywhere in an MCP tool result, whatever envelope it arrived in.

    The first version enumerated the shapes it expected -- bare, `result{}`,
    `content[0].text` -- and the real answer is `result.result.content[0].text`, one level
    deeper than any branch covered. Every approval then read as "malformed" and the
    mechanism denied legitimate writes while looking impeccably fail-closed. A refusal that
    happens for the wrong reason is not a working guard; it is a broken reader wearing one.

    So: search, don't enumerate. Depth-bounded because an unbounded walk over
    attacker-shaped JSON is its own problem, and JSON text is parsed wherever it appears
    because that is where the daemon actually puts the payload.
    """
    if _depth > 6:
        return None
    if isinstance(result, dict):
        if key in result:
            return result[key]
        for v in result.values():
            found = _dig(v, key, _depth + 1)
            if found is not None:
                return found
    elif isinstance(result, list):
        for item in result:
            found = _dig(item, key, _depth + 1)
            if found is not None:
                return found
    elif isinstance(result, str):
        # A JSON blob carried as text -- content[0].text is exactly this.
        t = result.strip()
        if t.startswith("{") or t.startswith("["):
            try:
                return _dig(json.loads(t), key, _depth + 1)
            except (ValueError, TypeError):
                return None
    return None


def extract_target(tool_input: Any, tool_name: str) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    if tool_name in {"Bash", "Shell"}:
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            # First token = the executable
            return cmd.split()[0]
    return None


# ---- Tiny MCP-over-HTTP client (same shape as the witness hook) -------

class McpHttp:
    def __init__(self, endpoint: str, deadline: float) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0
        self.deadline = deadline  # monotonic time after which we give up

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _remaining_s(self) -> float:
        return max(0.05, self.deadline - time.monotonic())

    def _request(self, body: dict[str, Any], *, is_notification: bool = False) -> Optional[dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        timeout = min(REQUEST_TIMEOUT_S, self._remaining_s())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not self.session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            if is_notification:
                return None
            payload = resp.read().decode("utf-8", errors="replace")
        return parse_json_or_sse(payload)

    def initialize(self) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": PLUGIN_ID, "version": HOOK_VERSION},
            },
        }) or {}

    def initialized(self) -> None:
        self._request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            is_notification=True,
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def parse_json_or_sse(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if body and body.startswith("{"):
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    continue
    return {}


def unwrap_tool_result(rpc_response: dict[str, Any]) -> dict[str, Any]:
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    return {}


# ---- Daemon path ------------------------------------------------------

def ask_daemon(
    tool_name: str,
    tool_input: Any,
    tool_use_id: str,
    host_session_id: Optional[str] = None,
) -> Optional[Tuple[dict[str, Any], str]]:
    """Returns (decision_dict, action_id) on success, None on any failure
    or timeout. decision_dict has the shape from spec §3.4."""
    endpoint = discover_endpoint()
    if endpoint is None:
        debug_log("no endpoint discovered; daemon path skipped")
        return None

    deadline = time.monotonic() + (TOTAL_BUDGET_MS / 1000.0)
    target = extract_target(tool_input, tool_name)
    full_command: Optional[str] = None
    if tool_name in {"Bash", "Shell"} and isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            full_command = cmd

    client = McpHttp(endpoint, deadline)
    try:
        init = client.initialize()
        if "result" not in init:
            debug_log(f"initialize failed: {init}")
            return None
        client.initialized()

        # connect
        connect_args: dict[str, Any] = {
            "plugin_id": PLUGIN_ID,
            "plugin_version": HOOK_VERSION,
            "host_agent": HOST_AGENT,
            "host_agent_version": "claude-code",
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
        }
        # Optional constellation role. Absent env → omit → daemon defaults to
        # role:constellation:member. (Distinct from the legacy requested_role.)
        role = os.environ.get("HESTIA_ROLE")
        if role:
            connect_args["role"] = role
        # Stable host-session id → connect idempotency: one Claude session = one hestia session,
        # instead of a fresh session minted per tool call. Descriptive reuse key only (Guard B —
        # never an authz discriminator; the daemon reuse is liveness-only, Guard A).
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        connect_resp = client.call_tool("hestia_connect", connect_args)
        connect = unwrap_tool_result(connect_resp)
        if "_hestia_error" in connect:
            debug_log(f"connect rejected: {connect['_hestia_error']}")
            return None
        session_id = connect.get("sessionId")

        # begin_action — daemon stores parameters so query_policy can use full_command
        parameters: dict[str, Any] = {}
        if isinstance(tool_input, dict):
            parameters = dict(tool_input)
        begin_args: dict[str, Any] = {
            "tool_name": tool_name,
            "target": target,
            "parameters": parameters,
            **({"session_id": session_id} if session_id else {}),
        }
        # Thread Claude Code's own session id as the audit grain. The daemon
        # records it on the witnessed outcome/policy_decision events.
        if host_session_id:
            begin_args["host_session_id"] = host_session_id
        begin_resp = client.call_tool("hestia_begin_action", begin_args)
        begin = unwrap_tool_result(begin_resp)
        if "_hestia_error" in begin:
            debug_log(f"begin_action rejected: {begin['_hestia_error']}")
            return None
        action_id = begin.get("actionId")
        if not action_id:
            debug_log(f"begin_action missing actionId: {begin}")
            return None

        # query_policy with wait-protocol re-poll
        decision = poll_policy(client, action_id, session_id, deadline)
        if decision is None:
            debug_log("query_policy never reached 'decided' within budget")
            return None
        return (decision, action_id)
    except urllib.error.URLError as e:
        # Classify, so the fail-closed message can say what is KNOWN rather than
        # guess a cause. A timeout means starved; a refused connection means down.
        # These want opposite member behaviour, so conflating them is not cosmetic.
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(e, socket.timeout):
            _set_last_failure("timeout")
        elif isinstance(reason, ConnectionRefusedError):
            _set_last_failure("refused")
        else:
            _set_last_failure("unknown")
        debug_log(f"network: {e}")
        return None
    except TimeoutError as e:
        _set_last_failure("timeout")
        debug_log(f"timeout: {e}")
        return None
    except Exception as e:  # noqa: BLE001 — fail-open path; legacy fallback will catch
        debug_log(f"unexpected: {type(e).__name__}: {e}")
        return None


def poll_policy(
    client: McpHttp,
    action_id: str,
    session_id: Optional[str],
    deadline: float,
) -> Optional[dict[str, Any]]:
    """Call hestia_query_policy and handle the wait protocol. Returns the
    final `decided` payload, or None if we ran out of polls / budget."""
    for poll in range(MAX_POLLS):
        if time.monotonic() >= deadline:
            return None
        args: dict[str, Any] = {"action_id": action_id}
        if session_id:
            args["session_id"] = session_id
        resp = client.call_tool("hestia_query_policy", args)
        body = unwrap_tool_result(resp)
        if "_hestia_error" in body:
            debug_log(f"query_policy error: {body['_hestia_error']}")
            return None
        status = body.get("status", "decided")
        if status == "decided":
            return body
        if status != "evaluating":
            debug_log(f"unknown status {status!r}; treating as decided")
            return body
        next_poll_ms = body.get("nextPollMs")
        if not isinstance(next_poll_ms, int) or next_poll_ms < 0:
            next_poll_ms = 200
        sleep_ms = max(MIN_POLL_SLEEP_MS, next_poll_ms)
        # Cap sleep at remaining budget.
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        sleep_ms = min(sleep_ms, remaining_ms)
        if sleep_ms <= 0:
            return None
        debug_log(f"evaluating; sleeping {sleep_ms}ms before re-poll {poll + 2}")
        time.sleep(sleep_ms / 1000.0)
    return None


def cache_action(tool_use_id: str, action_id: str, tool_name: str) -> None:
    try:
        ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        (ACTIONS_DIR / f"{tool_use_id}.json").write_text(
            json.dumps({"action_id": action_id, "tool_name": tool_name, "ts": time.time()})
        )
    except OSError as e:
        debug_log(f"action cache failed: {e}")


# ---- Legacy fallback --------------------------------------------------

def fail_closed() -> bool:
    return os.environ.get("HESTIA_PRE_FAIL_CLOSED") == "1"


def _record_plane_e(cause: str, detail: str, tool_name: str = "unknown") -> None:
    """Persist an infrastructure refusal without scoring it as member conduct."""
    try:
        shared = Path(__file__).resolve().parents[2] / "_shared"
        if str(shared) not in sys.path:
            sys.path.insert(0, str(shared))
        from hestia_gate_core import record_gate_unavailable  # type: ignore
        record_gate_unavailable(PLUGIN_ID, tool_name, cause, detail, home=str(DEFAULT_HESTIA_HOME))
    except Exception:
        pass


def deny_no_verdict(why: str, *, cause: str = "unknown", tool_name: str = "unknown") -> int:
    """Fail-closed refusal: no daemon verdict → the tool does not run.

    Composed locally (the daemon is exactly what we couldn't reach), so this
    carries its own static steering: without it, an agent facing a down daemon
    reads every deny as a tool error and retry-loops — the highest-risk case
    for the loop the daemon-side guidance exists to prevent.

    SAY WHAT IS KNOWN, NOT A GUESSED CAUSE (2026-07-28).
    ----------------------------------------------------
    This message used to assert "The policy daemon is unavailable" on every
    fail-closed path. The gate cannot know that. All it knows is that it did not
    get a verdict inside its own budget, and the two causes want OPPOSITE
    responses from the member:

      timeout   the daemon is alive but starved (usually another member is
                saturating the box). Correct response: back off and retry.
      refused   nothing is listening. Correct response: stop and escalate.

    Measured on 2026-07-28: a peer was parked for 4+ minutes, escalating to the
    operator on this message's instruction, while the daemon had been up
    continuously for eight hours (`NRestarts=0`) under a 15-minute load average
    of 7.39 caused by another member's test runs. The member did exactly what it
    was told; the message was wrong. codex's gate has carried a comment
    describing this same confusion — "no policy verdict (daemon path failed)
    while the daemon was up the whole time" — and nothing acted on it.

    A false cause is worse than no cause: it spends a session on the wrong
    remedy and makes the next member trust the next message less."""
    remedy = {
        "timeout": (
            "The daemon did not answer within the gate's budget — it is most likely "
            "ALIVE BUT LOADED, not down. Wait and retry with backoff; if it persists "
            "across several minutes, then report to your operator."
        ),
        "refused": (
            "Nothing is listening on the daemon endpoint, so no action can be "
            "approved. Report this to your operator and wait — retrying will not help."
        ),
    }.get(
        cause,
        "The gate could not obtain a verdict and cannot tell whether the daemon is "
        "down or merely slow. Retry once with backoff; if it repeats, report to your "
        "operator.",
    )
    sys.stderr.write(
        f"hestia: deny [fail-closed] — no policy verdict ({why}; cause={cause}). "
        f"This is a boundary, not a tool failure: do not re-run the same call "
        f"immediately. {remedy}\n"
    )
    _record_plane_e(cause, why, tool_name)
    debug_log(f"fail-closed deny: {why} cause={cause}")
    return 2


def invoke_legacy_fallback(stdin_payload: str) -> int:
    """Spawn the legacy web4-governance pre_tool_use.py with the same
    stdin and return its exit code. Returns 0 if the legacy script
    isn't available (fail-open), unless HESTIA_PRE_NO_FALLBACK=1 asked
    for deny-on-daemon-unreachable."""
    if os.environ.get("HESTIA_PRE_NO_FALLBACK") == "1":
        # Used to fall OPEN here despite the documented deny semantics
        # (GPT security review HST-004 / doc-code mismatch).
        return deny_no_verdict("daemon unreachable, legacy fallback disabled")
    if not os.path.exists(LEGACY_FALLBACK):
        debug_log(f"legacy fallback not found at {LEGACY_FALLBACK}; allowing")
        return 0
    try:
        proc = subprocess.run(
            ["python3", LEGACY_FALLBACK],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        # Forward legacy's stderr so Claude Code surfaces it to the user.
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        debug_log(f"legacy fallback exit={proc.returncode}")
        return proc.returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        debug_log(f"legacy fallback failed: {e}; allowing")
        return 0


# ---- Main flow --------------------------------------------------------

def emit_decision(decision: dict[str, Any]) -> int:
    """Translate a Hestia PolicyResult-shaped dict into a Claude Code
    hook exit code (with side-effect stderr)."""
    verdict = decision.get("decision", "allow")
    enforced = bool(decision.get("enforced", True))
    reason = decision.get("reason", "")
    rule_name = decision.get("ruleName")
    label = f" [{rule_name}]" if rule_name else ""

    if verdict == "deny" and enforced:
        # Prefer the daemon-composed steering text (deny-as-redirect): it is
        # what the blocked agent actually reads, so it must say what to DO
        # next, not just why. Fall back to the bare reason for old daemons.
        guidance = decision.get("guidance")
        sys.stderr.write((guidance or f"hestia: deny{label} — {reason}") + "\n")
        return 2
    if verdict == "warn":
        sys.stderr.write(f"hestia: warn{label} — {reason}\n")
        return 0
    if verdict == "deny" and not enforced:
        # audit-only mode: surface the would-be denial as a warning.
        sys.stderr.write(f"hestia: would-deny (audit-only){label} — {reason}\n")
        return 0
    return 0


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        # Empty stdin = the harness sent no event. Not caller-controllable from
        # inside a session, but under strict fail-closed semantics "no event" is
        # still "no verdict" → no tool (CBP relay-verify micro-seam, 2026-07-07).
        if fail_closed():
            return deny_no_verdict("empty hook event")
        return 0
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        if fail_closed():
            return deny_no_verdict(f"unparseable hook event: {e}")
        debug_log(f"bad json: {e}; allowing")
        return 0

    tool_name = event.get("tool_name") or "?"
    # Claude Code's own stable session id — the real per-session audit grain.
    host_session_id = event.get("session_id")
    tool_use_id = event.get("tool_use_id") or event.get("session_id") or "no-id"
    tool_input = event.get("tool_input") or {}

    # SELF-PROTECTION FIRST — before the daemon, and never conditional on it.
    # If this required a verdict, "stop the daemon, then edit the gate" would be
    # the same evasion one layer down.
    _self_hit = _touches_self(tool_name, tool_input)
    if _self_hit is None:
        _reg = _touches_registration(tool_name, tool_input)
        if _reg is not None:
            # Registration markers are already descriptive strings; the resource is
            # the settings path — or, for Bash, the command (write intent there is
            # undecidable, and the marker already says so).
            _r = tool_input.get("command") if tool_name == "Bash" else (
                tool_input.get("file_path") or tool_input.get("path")
                or tool_input.get("notebook_path"))
            _self_hit = (_reg, _r if isinstance(_r, str) and _r else _reg,
                         "command" if tool_name == "Bash" else "file_path")
    if _self_hit:
        _self_marker, _self_resource, _self_key = _self_hit
        # For a TEXT-key match the call's stated destination (if any) is what the
        # write actually reaches — the report names it and calls the match payload.
        _self_dest = None
        if _self_key not in _PATH_KEYS and isinstance(tool_input, dict):
            for _k in _PATH_KEYS:
                _v = tool_input.get(_k)
                if isinstance(_v, str) and _v:
                    _self_dest = _v
                    break
        if _is_read_only(tool_name, tool_input):
            # Allowed — and RECORDED. A member may inspect what governs it; repeated
            # reads of the governance surface remain visible as a pattern.
            _witness_self_read(_self_marker, tool_name)
            debug_log(f"gate-self-read (allowed, witnessed): {tool_name} -> {_self_marker}")
        else:
            verdict, detail = request_self_write(
                _self_marker, tool_name, _attempted_summary(tool_name, tool_input),
                resource=_self_resource, key=_self_key, dest=_self_dest,
                host_session_id=host_session_id,
            )
            if verdict != "approved":
                debug_log(f"gate-self-write {verdict}: {detail}")
                return deny_self_access(_self_marker, tool_name, resource=_self_resource,
                                        key=_self_key, dest=_self_dest)
            # APPROVED -- the self-protection is lifted for THIS call only, and the call
            # continues to the ordinary policy check below. Approving a gate edit is not
            # approving everything else the same command might do.
            sys.stderr.write(f"hestia: gate write APPROVED -- {detail}\n")
            debug_log(f"gate-self-write approved: {detail}")

    # Try the daemon first.
    result = ask_daemon(tool_name, tool_input, tool_use_id, host_session_id)
    if result is not None:
        decision, action_id = result
        cache_action(tool_use_id, action_id, tool_name)
        debug_log(
            f"daemon decided: {tool_name} → {decision.get('decision')} "
            f"(rule={decision.get('ruleId')})"
        )
        return emit_decision(decision)

    # Daemon unavailable or didn't settle. Under the fail-closed profile the
    # daemon is the law: no verdict → no tool (GPT review HST-004; governed /
    # unattended roles must not degrade to fail-open heuristics silently).
    if fail_closed():
        return deny_no_verdict(
            f"daemon path failed for {tool_name}",
            cause=_LAST_FAILURE,
            tool_name=tool_name,
        )
    debug_log(f"daemon path failed; falling back to legacy for {tool_name}")
    return invoke_legacy_fallback(raw)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        if fail_closed():
            sys.exit(deny_no_verdict(f"hook crashed: {type(e).__name__}: {e}"))
        debug_log(f"top-level: {e}; allowing")
        sys.exit(0)
