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
_GOVERNANCE_FILES = (
    "pre_tool_use.py",
    "society_pre_tool_use.py",
    "post_tool_use.py",
    "witness.py",
    "law_inject.py",
)


def _touches_self(tool_name: str, tool_input: Any) -> Optional[str]:
    """Return the matched marker if this call reaches the gate's own code."""
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
    # Nothing is lost by matching text raw: `../hooks/pre_tool_use.py` in a shell
    # command still contains both `hooks/` and a governance filename. What IS
    # given up is a symlinked alias inside a command string — admitted, and no
    # worse than the Bash surface's other known gaps.
    resolved = []
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            resolved.append(v)
            try:
                resolved.append(os.path.realpath(v))
            except (OSError, ValueError):
                pass
    for key in ("command", "content", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            resolved.append(v)
    for h in resolved:
        for marker in _SELF_MARKERS:
            if marker and marker in h:
                return marker
        # Governance files by name, but only under a hooks directory — so this
        # catches every member's gate and recorder without blocking an unrelated
        # file that happens to share a common name.
        low = h.replace("\\", "/")
        if "hooks/" in low or "/hooks" in low:
            for fname in _GOVERNANCE_FILES:
                if fname in low:
                    return fname
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
}
_GIT_READ_SUBCOMMANDS = {"show", "diff", "log", "cat-file", "blame"}


def _is_read_only(tool_name: str, tool_input: Any) -> bool:
    """True only when the call is CONFIDENTLY read-only. Ambiguity means write."""
    if tool_name in _READ_ONLY_TOOLS:
        return True
    if tool_name in _WRITE_TOOLS:
        return False
    if tool_name not in {"Bash", "Shell"}:
        return False
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    if ">" in cmd or "|" in cmd or "tee " in cmd:
        return False  # any redirection or pipe: treat as a write
    for segment in re.split(r"&&|;", cmd):
        parts = segment.strip().split()
        if not parts:
            continue
        head = os.path.basename(parts[0])
        if head == "git":
            if len(parts) < 2 or parts[1] not in _GIT_READ_SUBCOMMANDS:
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


def deny_self_access(marker: str, tool_name: str, detail: str = "") -> int:
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
        f"hestia: deny [gate-self-access] — {tool_name} WRITES to the gate's own code "
        f"({marker}). An agent that can edit the thing that governs it is not governed. "
        f"Reading it is allowed and witnessed; changing it is not. This refusal is its own "
        f"event class{'' if witnessed else ' (WITNESS FAILED — the refusal stands regardless)'}"
        f" and is escalatable.\n"
        f"If a gate change is genuinely needed, ESCALATE — the write is offered to a human, and "
        f"once one approves it you RETRY this same write and it proceeds. Say what you need "
        f"changed and why. Do not work around this by another route: doing so is the "
        f"behaviour this rule exists to make visible.\n"
        # The escalation id belongs HERE and not only on the line above it. stderr is read by
        # whoever is watching; this string is read by the caller that was refused, and a refusal
        # is only worth the caller that hears it. Without this, "retry after approval" is advice
        # the one party who has to act on it never receives.
        + (f"{detail}\n" if detail else "")
    )
    debug_log(f"gate-self-access deny: {tool_name} -> {marker} witnessed={witnessed} {detail}")
    return 2


# ---- Stage 2: escalate a governance WRITE to a human ------------------
#
# dp, 2026-07-29: "escalate to human for approval (there are legit times when we are
# actually working on the file), deny on timeout of a couple minutes."
#
# Stage 1 (#97) refuses every write to the governance surface. That is correct and it is
# also too much -- the fleet legitimately edits its gates (#55, #89, #90 in one week). This
# is the channel that un-refuses a legitimate one, with a human across it.

# THE HOOK MUST NEVER OUTLIVE ITS HARNESS TIMEOUT. Not for tidiness -- for direction.
#
# kimi-code caught this reviewing #114: the first version of this file waited 135s for a human
# while `.claude-plugin/plugin.json` gives the hook a `"timeout": 5`. I then measured what the
# harness actually does with a hook that overruns, because the failure DIRECTION is the whole
# question and I was not willing to infer it (Claude Code 2.1.220, two runs differing only in
# whether the hook slept past its timeout):
#
#   fast deny, inside the timeout  -> tool BLOCKED
#   same deny, sleeping past it    -> tool EXECUTED
#
# An overrun is not a refusal. It is an allow with a delay in front of it. So a governance write
# under the old code would have opened an escalation, been killed mid-wait, and gone through --
# leaving a `gate_escalation_opened` entry in the chain that reads like process happening while
# the write sailed underneath it. Worse than stage 1, and worse in the way that is hardest to see.
#
# This is the invariant law_inject.py:39 already states in prose for its own budget. Nothing
# enforced it. test_gate_escalation.py now does, by reading the timeout out of plugin.json.
ESCALATION_TOTAL_BUDGET_S = 2.5
ESCALATION_RPC_TIMEOUT_S = 1.0


def escalate_self_write(marker: str, tool_name: str) -> Tuple[str, str]:
    """Spend a human approval for a governance-surface write, or refuse and ask for one.

    Returns (verdict, detail). 'approved' ONLY when the daemon hands over an unspent,
    in-window grant for this member and this file. Everything else -- no grant, a pending
    decision, a denial, a stale or already-spent grant, an unreachable daemon, a malformed
    answer, running out of budget -- refuses, because the alternative is a governance write
    that proceeded because nobody managed to say no.

    THE SHAPE, and why it is not a wait:

        1st attempt   ->  no grant  ->  open an escalation, print how to decide, DENY NOW
        (a human decides, out of band, on their own clock)
        retry         ->  grant     ->  spent, and the write proceeds

    The hook cannot hold the session open for a person: overrunning the harness timeout does
    not deny, it ALLOWS (see ESCALATION_TOTAL_BUDGET_S). So the deny is immediate and the
    human's clock lives in the daemon, where nothing kills it. The daemon's TTL is unchanged
    at 120s and the grant is spendable for 5 minutes after a decision, so the retry is not
    racing anything.

    Approval lifts the SELF-PROTECTION only. The call then continues to the ordinary policy
    check, so approving a gate edit is not approving whatever else the command would do.
    """
    budget_ends = time.monotonic() + ESCALATION_TOTAL_BUDGET_S
    plugin_id = _escalation_plugin_id()

    def _rpc(tool: str, payload: dict) -> Any:
        """One call, never past the budget. Raises if there is no time left to make it."""
        left = budget_ends - time.monotonic()
        if left <= 0.1:
            raise TimeoutError("escalation budget exhausted")
        client = McpHttp(discover_endpoint() or DEFAULT_ENDPOINT,
                         deadline=time.monotonic() + min(ESCALATION_RPC_TIMEOUT_S, left))
        return client.call_tool(tool, payload)

    # --- Do we already have a yes? One round trip. ---
    try:
        claimed = _rpc("hestia_gate_escalation_claim",
                       {"plugin_id": plugin_id, "marker": marker, "tool_name": tool_name})
    except Exception as e:  # noqa: BLE001
        # An unreachable daemon is a DENY, never a bypass. If a member could edit the gate by
        # making the daemon unavailable, the mechanism would be decorative.
        return "unreachable", f"could not reach the daemon ({type(e).__name__}) -- refused"

    if _dig(claimed, "granted") is True:
        who = _dig(claimed, "decided_by") or "a human"
        via = _dig(claimed, "decided_via") or "unknown-channel"
        esc = _dig(claimed, "escalation_id") or "?"
        return "approved", f"approved by {who} via {via} (escalation {esc}, grant now spent)"

    why = _dig(claimed, "why") or "no approval on file"

    # --- No. Ask for one, and refuse THIS call. ---
    # Best-effort: the deny below happens whether or not the ask succeeds. A member who cannot
    # open an escalation is still refused; they just have nothing to point the operator at.
    esc_id, how = None, None
    try:
        opened = _rpc("hestia_gate_escalation_open", {
            "plugin_id": plugin_id,
            "role": os.environ.get("HESTIA_ROLE", ""),
            "tool_name": tool_name,
            "marker": marker,
        })
        esc_id = _dig(opened, "escalation_id")
        how = _dig(opened, "how_to_decide")
    except Exception as e:  # noqa: BLE001
        debug_log(f"gate-self-write: could not open an escalation: {type(e).__name__}: {e}")

    if esc_id:
        # The deny IS the notification, and it is addressed to both readers: the operator, who
        # decides, and the member, who has to know that retrying is the protocol rather than
        # the evasion it would look like otherwise.
        sys.stderr.write(
            f"hestia: ESCALATION {esc_id} -- {tool_name} would WRITE to the governance "
            f"surface ({marker}).\n"
            f"  REFUSED for now: a hook cannot wait for a human without failing OPEN.\n"
            f"  To allow:  {how or f'hestia gate approve {esc_id}'}\n"
            f"  Then RETRY the same write; the approval is good for one write, for 5 minutes.\n"
        )
        sys.stderr.flush()
        return "escalated", f"escalation {esc_id} opened and awaiting a human ({why})"

    return "no-grant", f"{why} -- refused, and no escalation could be opened"


def _escalation_plugin_id() -> str:
    """Who to record as asking. Caller-asserted (HST-005) and named as such.

    Falls back to a literal 'unattributed' rather than to any member id: guessing would
    file one member's escalation under another's name, which is the defect #108 closed one
    layer over.
    """
    for var in ("HESTIA_MESH_PLUGIN", "HESTIA_PLUGIN_ID"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    return "unattributed"


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


def deny_no_verdict(why: str, *, cause: str = "unknown") -> int:
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
    _self_marker = _touches_self(tool_name, tool_input) or _touches_registration(
        tool_name, tool_input
    )
    if _self_marker:
        if _is_read_only(tool_name, tool_input):
            # Allowed — and RECORDED. A member may inspect what governs it; repeated
            # reads of the governance surface remain visible as a pattern.
            _witness_self_read(_self_marker, tool_name)
            debug_log(f"gate-self-read (allowed, witnessed): {tool_name} -> {_self_marker}")
        else:
            verdict, detail = escalate_self_write(_self_marker, tool_name)
            if verdict != "approved":
                debug_log(f"gate-self-write escalation {verdict}: {detail}")
                return deny_self_access(_self_marker, tool_name, detail)
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
        return deny_no_verdict(f"daemon path failed for {tool_name}", cause=_LAST_FAILURE)
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
