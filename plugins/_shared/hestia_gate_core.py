#!/usr/bin/env python3
"""hestia_gate_core — ONE policy gate. Harnesses get adapter shims, not their own gates.

dp, 2026-08-02:

    "that's why we need one policy hook with adapter shims for harness semantics, not
     separate hook for each one..."

This is the consolidation half of dp's 2026-07-29 P0 ruling ("gate is a hestia policy entity
function. there can be only one") applied to the HOOKS. The rules were consolidated then; the
five implementations of them were not.

WHAT THE MEASUREMENT ACTUALLY SHOWED (claude-code, 2026-08-02)
--------------------------------------------------------------
Five plugin gates: claude-code 2357 lines, codex 1136, kimi 540, gemini 528, cursor 390.
24 function names appear in two or more of them.

My first pass hashed function TEXT and reported "12 drifted, including 100% of the scope
functions." That was a count, not a judgement — it scored trailing comments and a `s2`->`s`
rename as drift. Diffing code bodies only:

    command_in_scope   kimi 49 lines / codex 49 lines   -> zero semantic difference
    load_in_scope, _all_repos                            -> byte-identical
    launch_cwd_repo                                      -> env var name only (legitimate)
    deny                                                 -> 5 lines. THE REAL ONE.

So the honest finding is not that the copies drifted. It is that **five hand-maintained
copies have stayed in lockstep by unpaid effort, and the single place they have already
diverged is `deny`** — codex witnesses a blocked reach via `witness_decision(...)`, kimi via
`_daemon_witness(...)` inside a swallowed `try/except`. The one function that records
refusals is the one that disagrees, so the trust chain's denominator already varies by
vendor.

That is the argument for this module, and it does not rest on drift having happened. It
rests on five copies being one refactor away from disagreeing about who may touch what,
with the governance-critical function already disagreeing.

THE REMEDY INVENTORY IS THE POINT
---------------------------------
The duplication that actually hurt anyone was never in the shared functions. It was in the
SENTENCES, authored fresh at every `deny(...)` call site across five files. Four instances in
two days of a refusal naming a door the recipient could not open:

  1. kimi's scope deny said "request it (request_scope)". No such tool existed — 29 MCP
     tools, none scope-related. kimi filed an appeal instead, which by design cannot deliver
     a file, and sat blocked through a correct-but-useless arbitration.
  2. The same deny never named `hestia_appeal`, so when dp suggested appealing, kimi did not
     know how and built its own mechanism.
  3. `pre-push-guard` told refused members to "submit through .git-inbox/" — a path only
     codex has in its MRH.
  4. codex's gate names no remedy at all.

Every one was written by the author of a control, who was not subject to the constraint that
blocks the recipient. `claude-code` is not path-scoped at all, so every door it names is open
to it and it cannot discover the problem by following its own instructions.

**A remedy is a claim about someone else's reachability.** So remedies live HERE, in one
table, and `remedy_tools()` enumerates every tool any remedy names — which
`test_remedies_name_only_globally_registered_doors` checks against the daemon's live tool list.

**That test is weaker than the claim, and the gap is the interesting part.** (codex NOT-SAME
review of #169, finding 3.) It queries the daemon's *global* `tools/list`, so it proves
REGISTRATION, not RECIPIENT REACHABILITY. It can be green while the refused member cannot
reach the tool at all — the harness may have no hestia MCP registration, or not expose that
tool. That is not hypothetical: it is the measured `hestia_appeal` class, where the tool was
globally registered the whole time kimi had no way to call it.

So the honest scope: this excludes **globally absent** tools — the `request_scope` case, where
the door existed nowhere. It does NOT yet make fake remedies unwriteable in general. The
stronger invariant needs a per-harness capability manifest, or a probe through each shim's own
tool-discovery surface, and is deliberately not claimed until one exists.

The first version of this file claimed the strong property. Naming the weaker one is not a
retreat — an instrument that overstates its own coverage is the defect this whole thread keeps
finding, and it would be a poor joke to ship it inside the fix for it.

THE SHIM BOUNDARY
-----------------
A shim may set ONLY what `HarnessProfile` carries, and may implement only:

    parse_event(raw_stdin) -> NormalizedEvent      # harness event schema
    render(verdict)        -> (exit_code, stderr)  # harness exit-code contract

A shim contains NO scope logic, NO forbidden list, NO remedy text, and NO decision. If a
shim needs to make a policy choice, the profile is missing a field — add the field, do not
branch in the shim.

`test_shims_contain_no_policy` checks this over every file matching `shim_*.py` here. **No
shim exists yet, so today it reports that it checked nothing** rather than passing silently
— a green that means "nothing was inspected" is the null-state twin of a green that means
"inspected and clean". The first version of this docstring said the test "enforces this by
construction"; the test did not exist (codex NOT-SAME review of #169, finding 4). A doc that
credits an absent check is worse than no doc: it retires the reviewer's attention.

FAIL-CLOSED IS THE SHIM'S JOB, AND IT IS NOT NEGOTIABLE
-------------------------------------------------------
Every Claude-Code-lineage hook engine (kimi, codex, cursor, ...) fails OPEN on timeout,
spawn failure, non-2 exit and exception. So the gate must be the fail-closed party: a shim's
default path is deny, and `exit 0` is reached only on an explicit confirmed allow. This
module never calls `sys.exit` — it returns a Verdict — precisely so a shim cannot mistake
"the core returned nothing" for "the core allowed it".

NOT WIRED. Nothing imports this yet. Migrating each harness is an edit to that harness's
governance surface and needs its own escalation; this lands first so the migration is
reviewable before anything switches over.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Innate invariants ────────────────────────────────────────────────────────────────────
#
# Denied even inside a granted repo, and NEVER relaxed by trust or by warn-mode: a leaked
# read is irreversible egress, so there is no "surface it and allow" that means anything.
FORBIDDEN_DEFAULT = (
    "/.ssh", ".env", "credentials", "id_rsa", "id_ed25519", "/.git/config", "secrets",
)

# Tools that only read. Read-class is fully covered by the local gates, so it never needs the
# daemon's destructive/secret verdict — which is what keeps a down daemon from bricking reads.
READ_CLASS = frozenset({"Read", "Glob", "Grep", "TodoWrite", "TodoList", "GetGoal"})

# A bare member plugin-id is an ADDRESS (a mesh notify target, a tool arg), not a filesystem
# reach — even when a same-named directory exists at the workspace root. Live false-deny:
# kimi's mesh ack `send claude-code ack <ptr>` denied on the claude-code DIR, 2026-07-24.
# With a slash it is a path again and votes normally.
MEMBER_ADDRESSES = frozenset({"claude-code", "kimi-code", "codex-cli", "gemini-cli", "cursor"})


# ── The remedy inventory ─────────────────────────────────────────────────────────────────
#
# One table. Every sentence a member reads after a refusal comes from here, and every tool
# any sentence names is enumerable by `remedy_tools()` so a test can check it exists.
#
# Each entry is (text, tools_named). `tools_named` is not decoration — it is the field the
# test reads. An entry that names a tool in prose but omits it here defeats the check, so
# `test_remedy_text_declares_every_tool_it_names` also scans the text for `hestia_*` tokens.
@dataclass(frozen=True)
class Remedy:
    text: str
    tools: tuple = ()


REMEDIES: dict[str, Remedy] = {
    # ── scope ────────────────────────────────────────────────────────────────────────────
    "mrh.path": Remedy(
        "Adjust to work within scope. If the path is genuinely needed, ask for it with "
        "hestia_request_scope (one path, with a reason) — a human decides, the grant is "
        "memory-only and expires. Do NOT appeal this: hestia_appeal asks whether the deny was "
        "WRONG and returns a verdict on conduct; it cannot and must not hand you a file. If "
        "you believe the deny itself was wrong, that is the appeal, and it is a separate act.",
        ("hestia_request_scope", "hestia_appeal"),
    ),
    "mrh.command": Remedy(
        "Scope the command to a granted repo. If the path is genuinely needed, ask for it with "
        "hestia_request_scope (one path, with a reason). An appeal cannot deliver a path — "
        "hestia_appeal disputes whether the deny was right, which is a different question.",
        ("hestia_request_scope", "hestia_appeal"),
    ),
    # ── egress ───────────────────────────────────────────────────────────────────────────
    #
    # Deliberately names NO door. This is the one refusal with no remedy, and saying so is the
    # honest answer: a leaked secret has no undo, so there is no request that makes it fine.
    # Offering a channel here would be worse than offering none — it would imply the act is
    # available at a price.
    "egress.secret": Remedy(
        "There is no in-scope way to do this; it is not yours to touch. This one is innate: it "
        "is not relaxed by warn-mode, by trust, or by any grant, because a leaked read is "
        "irreversible and no approval can un-leak it.",
        (),
    ),
    # ── governance surface ───────────────────────────────────────────────────────────────
    "gate.self_access": Remedy(
        "An agent that can edit the thing that governs it is not governed. Reading the gate is "
        "allowed and witnessed; changing it is not. If a gate change is genuinely needed, open "
        "hestia_gate_escalation_open with the deny's chain hash and say what you need changed "
        "and why, then re-issue the write to claim the approval with "
        "hestia_gate_escalation_claim. Do not reach the same file by another route — that is "
        "the behaviour this rule exists to make visible, and it scores BELOW plain compliance.",
        ("hestia_gate_escalation_open", "hestia_gate_escalation_claim"),
    ),
    # ── society safety ───────────────────────────────────────────────────────────────────
    "society.safety": Remedy(
        "This is society law, not a local rule — it binds every member equally. If it blocks "
        "legitimate work, dispute it with hestia_appeal (this deny's chain hash plus your "
        "reason) rather than rephrasing around it. A rephrase that reaches the same resource "
        "scores 0.35, BELOW plain compliance, and teaches the society nothing. An appeal is "
        "recorded conduct that can change the law.",
        ("hestia_appeal",),
    ),
    "society.unreachable": Remedy(
        "The governor could not be reached, so this failed closed. That is the correct "
        "posture, not a bug: law-in-the-loop means the loop does not proceed when law cannot "
        "be consulted. Retry once the daemon is up; if it stays down, that is an operator "
        "matter and not something to work around.",
        (),
    ),
}


def remedy_tools() -> set:
    """Every tool named by any remedy. The test reads this against the daemon's live list."""
    out = set()
    for r in REMEDIES.values():
        out.update(r.tools)
    return out


# ── The shim contract ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HarnessProfile:
    """Everything a harness may legitimately differ in. If a shim needs something not here,
    the answer is a new field, not a branch in the shim."""

    member_id: str                     # "kimi-code" — the plugin_id asserted to the daemon
    identity_path: str                 # the member's live identity.json
    home_markers: tuple = ()           # paths that are always the member's own (its config dir)
    launch_cwd_env: str = ""           # env var carrying the launch dir, if the harness sets one
    mode_env: str = ""                 # env var selecting warn|enforce
    workspace_env: str = "HESTIA_WORKSPACE"
    forbidden_extra_env: str = "HESTIA_FORBIDDEN_EXTRA"
    default_role: str = "role:constellation:member"


@dataclass
class NormalizedEvent:
    """What every harness event reduces to. The shim's whole job is producing this."""

    tool: str = "?"
    paths: list = field(default_factory=list)   # filesystem targets
    command: Optional[str] = None               # shell command, if any
    cwd: Optional[str] = None
    raw: dict = field(default_factory=dict)     # kept for witnessing, never for deciding


@dataclass(frozen=True)
class Verdict:
    decision: str          # "allow" | "warn" | "deny"
    rule: str = ""         # stable id; the key into REMEDIES
    reason: str = ""       # what tripped, naming the offending token
    remedy: str = ""       # from REMEDIES — never authored at a call site
    innate: bool = False   # true = not relaxable by warn-mode or by any grant

    @property
    def blocks(self) -> bool:
        return self.decision == "deny"


#: Remedy used when a refusal names a rule with no registered entry. Should be unreachable —
#: `test_every_literal_deny_rule_is_registered` reads the AST and reds the build first — but
#: "should be unreachable" is not a runtime guarantee, and here being wrong costs a governed act.
UNREGISTERED_RULE_REMEDY = (
    "This refusal has no registered remedy, which is itself a defect in the gate — please "
    "report it. The act is still refused: a gate that cannot say what to do next must not "
    "therefore allow the act."
)


def _deny(rule: str, reason: str, innate: bool = False) -> Verdict:
    """The ONLY constructor of a refusal. Takes a rule id, not a sentence — which is what
    makes 'a remedy naming a door nobody built' unwriteable rather than merely discouraged.

    **RETURNS A DENIAL FOR AN UNKNOWN RULE. IT DOES NOT RAISE.** (codex NOT-SAME review of
    #169, finding 1.) The first version raised `KeyError`, reasoning that a refusal with no
    remedy should be loud. codex named the consequence: *this module's own premise is that
    these hook engines fail OPEN on exception.* So the "loud" path was an escaping exception,
    in a gate, on an engine that reads an exception as allow — the exact failure mode this
    file exists to prevent, introduced by the check meant to enforce it.

    Loudness belongs to the TEST, where being wrong costs a red build. Fail-closed belongs to
    the RUNTIME, where being wrong costs a governed act. The first version used one mechanism
    for both jobs and got the runtime one backwards."""
    r = REMEDIES.get(rule)
    if r is None:
        return Verdict("deny", rule or "gate.internal",
                       f"{reason} [gate defect: no remedy registered for rule '{rule}']",
                       UNREGISTERED_RULE_REMEDY, innate)
    return Verdict("deny", rule, reason, r.text, innate)


ALLOW = Verdict("allow")


# ── Workspace + scope resolution ─────────────────────────────────────────────────────────
def detect_workspace(profile: HarnessProfile) -> str:
    """Survives a wrong or absent env. 2026-07-23, live: a session launched before
    HESTIA_WORKSPACE landed in its hook config ran against the default ~/ai-workspace — every
    real path then read as 'outside the workspace' (deny-everything) and the society-gate
    script resolved to a nonexistent file. **A gate's own config must not be able to poison
    its verdicts.**"""
    env = os.environ.get(profile.workspace_env)
    if env and os.path.isdir(env):
        return env
    markers = ("hestia", "shared-context", "web4", "private-context")
    d = os.getcwd()
    for _ in range(8):
        if sum(os.path.isdir(os.path.join(d, m)) for m in markers) >= 2:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.expanduser("~/ai-workspace")


def load_in_scope(profile: HarnessProfile) -> list:
    """The member's granted MRH, from its identity. `repo:web4` -> `web4`, `path:.git-inbox`
    -> `.git-inbox`.

    Both prefixes matter and the difference is not cosmetic: `.git-inbox` is a SIBLING of the
    repos, so no `repo:` grant ever reaches it. On 2026-08-02 kimi was refused while reading
    the very directory the push guard tells refused members to use, because only codex held
    `path:.git-inbox`."""
    try:
        with open(os.path.expanduser(profile.identity_path), encoding="utf-8") as fh:
            mrh = json.load(fh).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list) and scope:
            return [s.split(":", 1)[-1] for s in scope]
    except Exception:
        pass
    # Deliberately narrow. A default that guessed wide would silently grant reach on any
    # machine where the identity file is missing or malformed.
    return ["web4"]


def identity_role(profile: HarnessProfile) -> str:
    """The member's declared LOCAL role (dp 2026-07-24: roles are always local; occupancy
    attributes carry the 'foreign' dimension)."""
    try:
        with open(os.path.expanduser(profile.identity_path), encoding="utf-8") as fh:
            r = json.load(fh).get("role")
        if isinstance(r, str) and r.startswith("role:"):
            return r
    except Exception:
        pass
    return profile.default_role


def launch_cwd_repo(profile: HarnessProfile, workspace: str) -> list:
    """The repo the member is launched in is always in scope (dp 2026-07-21: 'whatever cwd we
    launch it in') — a per-launch dynamic grant on top of the static allowlist, so a
    task-specific launch dir is reachable for that session without widening the standing
    grant. This is the precedent `hestia_request_scope` generalises."""
    env = os.environ.get(profile.launch_cwd_env) if profile.launch_cwd_env else None
    cwd = (env or os.getcwd()).replace("\\", "/")
    if workspace in cwd:
        rest = cwd.split(workspace, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return [seg] if seg else []
    return []


def _all_repos(workspace: str) -> list:
    try:
        return [d for d in os.listdir(workspace)
                if os.path.isdir(os.path.join(workspace, d)) and not d.startswith(".")]
    except Exception:
        # Degrade to root-glob detection only. deny-known-out beats allow-all, and we ship no
        # hardcoded repo list — set the workspace env so the live listing works.
        return []


def path_in_scope(path: str, scopes, workspace: str, profile: HarnessProfile,
                  cwd: Optional[str] = None) -> bool:
    """In-scope if it is the member's own home, /tmp, or under a granted repo.

    Relative paths resolve against the event cwd — `scripts/x` inside a granted repo is that
    repo's subdir, not the workspace-root `scripts` dir (2026-07-23 false-deny class)."""
    p = path.replace("\\", "/")
    low = p.lower()
    for marker in profile.home_markers:
        m = marker.lower()
        if m in low or low.startswith(os.path.expanduser(marker).lower()):
            return True
    if not p.startswith("/") and not p.startswith("~"):
        cwd = (cwd or os.getcwd()).replace("\\", "/")
        p = os.path.normpath(os.path.join(cwd, p)).replace("\\", "/")
    if _under_temp_root(p):
        return True
    if workspace in p:
        rest = p.split(workspace, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        if seg == "":
            return False          # bare workspace root — the glob-the-root antipattern
        return seg in scopes
    return False                  # absolute, outside the workspace, not home/tmp


def command_in_scope(cmd: str, scopes, workspace: str, cwd: Optional[str] = None):
    """Returns (ok, offending_token).

    A reach is judged by WHERE IT RESOLVES, not by what it lexically mentions. Lexical
    mention-scanning false-denied two whole classes, both found live via the Codex gate on
    2026-07-23: (a) the scan matched the workspace root's own path component, denying every
    absolute path; (b) it matched generic dir names ('scripts', 'logs') that exist both at the
    root and inside granted repos, denying in-repo relative paths.

    Residual, documented and accepted: relative traversal that never names a path (`grep -r .`)
    escapes string parsing entirely — the engine sandbox, not this check, is the fs boundary."""
    ws = workspace.rstrip("/")
    for after in cmd.split(workspace)[1:]:
        head = after.lstrip("/")
        head = re.split(r"""[\s"'`);&|<>]""", head, 1)[0]
        head = head.split("/", 1)[0]
        if head not in scopes:
            return False, (head or "<workspace root>")

    # Pass 2 — relative tokens. The event cwd is NOT reliable: the engine may run each command
    # with a per-command workdir the event does not carry (observed live via the Codex gate —
    # event cwd = session launch dir while the command ran inside a granted repo). So a token
    # is judged by its PLAUSIBLE interpretations — the event cwd plus every granted repo root —
    # voting by what EXISTS: an existing in-scope interpretation passes; an existing
    # out-of-scope one with no in-scope alternative denies; a token that exists nowhere is not
    # a reach.
    cwd = (cwd or os.getcwd()).replace("\\", "/")
    bases = [cwd] + [f"{ws}/{s}" for s in scopes]
    oos_names = {r for r in _all_repos(workspace) if r not in scopes}
    probes = 0
    for raw in re.split(r"""[\s;|&<>()'"`]+""", cmd):
        for tok in raw.split("="):
            tok = tok.strip()
            if not tok or tok.startswith(("-", "/")) or ":" in tok or tok.strip(".") == "":
                continue
            first = tok.split("/", 1)[0]
            if "/" not in tok and first not in oos_names:
                continue
            if "/" not in tok and tok in MEMBER_ADDRESSES:
                continue
            if probes >= 40:
                break                 # bound fs probing under the engine's hook clamp
            probes += 1
            comps = tok.split("/")
            k = 0
            while k < len(comps) and comps[k] == "..":
                k += 1
            probe = "/".join(comps[:k + 1]) if k < len(comps) else "/".join(comps)
            in_scope_vote, oos_vote = False, None
            for base in bases:
                cand = os.path.normpath(os.path.join(base, probe)).replace("\\", "/")
                if not os.path.exists(cand):
                    continue
                if cand == ws:
                    oos_vote = oos_vote or "<workspace root>"
                    continue
                if cand.startswith(ws + "/"):
                    seg = cand[len(ws) + 1:].split("/", 1)[0]
                    if seg in scopes:
                        in_scope_vote = True
                        break
                    oos_vote = seg
            if not in_scope_vote and oos_vote:
                return False, oos_vote
    return True, None


#: Roots that are always reachable regardless of MRH — scratch space, not governed territory.
TEMP_ROOTS = ("/tmp", "/var/tmp")


def _under_temp_root(path: str) -> bool:
    """Is this path the temp root itself, or a DESCENDANT of it?

    codex NOT-SAME review of #169, finding 2. The inherited check was
    `p.startswith(("/tmp", "/var/tmp"))`, which is a string-prefix test, not a path-boundary
    test — so `/tmp-other/x` and `/var/tmpsecrets/y` read as temporary. Those are SIBLINGS of
    the temp roots, and a directory anyone can create: a member could be handed unconditional
    reach by naming a directory, with no grant, no witness and no operator involved.

    Same defect class as the census's `reviewer ⊄ review`: a boundary rule implemented as a
    substring rule. The fix is the same shape — compare at the separator."""
    p = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
    return any(p == r or p.startswith(r + "/") for r in TEMP_ROOTS)


def _elide(path: str, keep: int = 72) -> str:
    """Shorten from the FRONT. A path's discriminating part is its tail, so truncating the
    head keeps the reason legible while `path[:60]` throws it away."""
    p = path.replace("\\", "/")
    return p if len(p) <= keep else "..." + p[-(keep - 3):]


def _offending_segment(path: str, workspace: str, cwd: Optional[str] = None) -> Optional[str]:
    """The workspace-relative first segment that was not granted, or None if the path simply
    lies outside the workspace entirely (a different fact, and worth saying differently —
    `/mnt/c/exe/dpx/` was outside `HESTIA_WORKSPACE` altogether, and telling kimi it was 'not
    granted' would have implied a grant could fix it)."""
    p = path.replace("\\", "/")
    if not p.startswith("/") and not p.startswith("~"):
        p = os.path.normpath(os.path.join((cwd or os.getcwd()).replace("\\", "/"), p))
        p = p.replace("\\", "/")
    if workspace in p:
        rest = p.split(workspace, 1)[1].lstrip("/")
        seg = rest.split("/", 1)[0] if rest else ""
        return seg or "<workspace root>"
    return None


def forbidden_tokens(profile: HarnessProfile) -> tuple:
    extra = os.environ.get(profile.forbidden_extra_env, "")
    return FORBIDDEN_DEFAULT + tuple(t.strip() for t in extra.split(",") if t.strip())


# ── The decision ─────────────────────────────────────────────────────────────────────────
def evaluate(event: NormalizedEvent, profile: HarnessProfile,
             workspace: Optional[str] = None) -> Verdict:
    """The whole local policy, for every harness.

    Order is deliberate and is the O clause of the accountability audit: the innate egress
    check dominates everything, then MRH scope. Society safety (the daemon call) is the
    SHIM's second stage and is not decided here, because it needs a live transport — but a
    shim must treat an unreachable daemon as `society.unreachable`, never as allow.

    Never calls sys.exit. A shim that gets no Verdict must deny; making that impossible to
    confuse with an allow is the reason this returns a value instead of exiting."""
    ws = workspace or detect_workspace(profile)
    scopes = load_in_scope(profile) + launch_cwd_repo(profile, ws)
    forbidden = forbidden_tokens(profile)

    # Gate 1a — innate egress/secret. Denied even inside a granted repo, always enforced.
    for blob in list(event.paths) + ([event.command] if event.command else []):
        low = blob.lower()
        for f in forbidden:
            if f in low:
                return _deny(
                    "egress.secret",
                    f"'{event.tool}' touches a forbidden path (secret/credential or "
                    f"out-of-MRH private repo): '{f}'",
                    innate=True,
                )

    # Gate 1b — MRH scope. File paths use path-scope; shell commands use command-scope.
    for p in event.paths:
        if not path_in_scope(p, scopes, ws, profile, event.cwd):
            # NAME THE SEGMENT, not just the path. The inherited hooks wrote `p[:60]`, which
            # on any long path truncates away the very component that tripped the gate — the
            # member is handed a string that does not contain its own reason. That is the
            # "a deny that hides its trigger sends the agent debugging blind" defect
            # (Codex live, 2026-07-23) reappearing inside the fix for it. Caught by
            # `deny_names_the_offending_target` once the test workspace moved off /tmp and
            # the paths got long enough to truncate.
            seg = _offending_segment(p, ws, event.cwd)
            where = f"'{seg}' is not granted" if seg else "it is outside the workspace"
            return _deny(
                "mrh.path",
                f"'{event.tool}' targets '{_elide(p)}' outside your granted scope: {where} "
                f"(granted: {'+'.join(scopes)})",
            )
    if event.command is not None:
        ok, offending = command_in_scope(event.command, scopes, ws, event.cwd)
        if not ok:
            # Name WHAT tripped the gate — a deny that hides its trigger sends the agent
            # debugging blind (Codex live session, 2026-07-23).
            return _deny(
                "mrh.command",
                f"'{event.tool}' command reaches outside your granted scope: '{offending}' "
                f"is not granted (granted: {'+'.join(scopes)})",
            )

    return ALLOW


def needs_society_gate(tool: str) -> bool:
    """Read-class is fully covered above, so only write/exec-class needs the daemon's verdict.
    This is what keeps a down daemon from bricking reads while still failing closed on writes."""
    return tool not in READ_CLASS
