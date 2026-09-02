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

WIRED (Sprints B–F). Sprint C pointed kimi's scope predicates here; D centralised the
constants and remedies; E unified transport and the deny recorder; F cuts kimi and codex
over to evaluate() — decided from a policy snapshot fetched LIVE from the daemon
(hestia_gate_mechanism.fetch_policy_snapshot), or the ratified degraded mode
(degraded_verdict below) when the daemon is unreachable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Deployed-generation attestation (PRD gate-consolidation §7.2(7), rides #231) ─────────
# The RUNNING core attests what was imported — a bystander hashing a file beside a process
# proves nothing about what that process loaded (kimi's sharpening, notice 1929). Computed
# once at import; carried on every refusal record by the unified recorder.
import hashlib as _hashlib


def core_digest() -> str:
    """sha256 of this module's own source as imported; "unknown" if unreadable —
    and unknown must never read as healthy (#231 posture)."""
    try:
        with open(__file__, "rb") as _fh:
            # FULL sha256 (PR #408 review, converging with Hub #708's invariant): the
            # running thing attests its EXACT bytes; truncation is a second, weaker
            # definition of identity that external consumers would over-trust.
            return _hashlib.sha256(_fh.read()).hexdigest()
    except Exception:
        return "unknown"


_CORE_DIGEST = core_digest()


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


# ── The governance closure — the CANONICAL list, mirrored (not imported) by every gate ──────
#
# Filenames of the files that DECIDE policy, matched anywhere so the rule holds for a peer's
# copy as well as one's own. This is the single source of truth for the self-protection list
# the per-harness gates enforce, so their copies cannot silently drift apart. The self-protection
# test's drift check pins each enforcing gate's literal against this tuple.
#
# WHY MIRRORED, NOT IMPORTED (load-bearing). A gate must carry its protection list as a
# FAIL-SAFE LITERAL, never as `from hestia_gate_core import GOVERNANCE_FILES`. If the list were
# import-only and the import failed, the self-access check would run against an EMPTY list — and
# because every Claude-lineage engine fails OPEN on a hook crash, that silently disarms gate
# self-protection entirely. So the canonical lives here for one-source review + drift detection,
# and each gate keeps its own literal for fail-safety; the drift test makes the two agree. This
# is the one place "one implementation" yields to "one canonical + fail-safe replicas + a drift
# guard," and the reason is that the failure mode of a missing import is a disarmed gate.
GOVERNANCE_FILES = (
    "pre_tool_use.py",
    "society_pre_tool_use.py",
    "post_tool_use.py",
    "witness.py",
    "law_inject.py",
    "hestia_gate_core.py",
    "hestia_gate_mechanism.py",
    "gate_self_protection_test.py",
)


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
    # An MCP connector call names a REPOSITORY, not a path — the codex gate scopes on that
    # name (see mcp_repo_target there). Same door as mrh.path, worded for a repo so the
    # member is not sent asking for "a path" it never named. Added Sprint D (§6.D): before
    # this, that call site authored its own sentence, naming the request_scope phantom.
    "mrh.repo": Remedy(
        "Adjust to work within scope. If the repository is genuinely needed, ask for it with "
        "hestia_request_scope (one repo, with a reason) — a human decides, the grant is "
        "memory-only and expires. An appeal cannot deliver a repo — hestia_appeal disputes "
        "whether the deny was right, which is a different question.",
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
    # ── degraded mode (Sprint F — §7.1 criterion 9; semantics ratified dp 2026-08-11) ────
    "gate.degraded": Remedy(
        "The policy authority could not be consulted (the daemon is unreachable), so the "
        "gate is in the ratified degraded mode: deny-writes-allow-reads. This is fault "
        "isolation, not a judgement of your act — the referee is missing, not ruling "
        "against you. Retry when the daemon returns; if it stays down, that is an operator "
        "matter and not something to work around. A shim may tighten this posture locally; "
        "it may never loosen it.",
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
class AgentPolicy:
    """The PER-AGENT layer: what this member specifically may reach, beyond the common law.

    dp, 2026-08-03: *"there should be one common gate, with syntax adapters per-harness, and any
    exceptions/grants/restrictions per agent"* — and, immediately after: *"the latter should live
    in the vault."*

    Three layers, and keeping them apart is the whole design:

        LAW            one, common, amendable only by due process. `REMEDIES` + `evaluate()`.
        HARNESS        syntax only — event schema, exit codes, where the identity file sits.
                       `HarnessProfile`. **No policy may live here.**
        AGENT          this. Exceptions, grants, restrictions, for one member.

    WHY THIS EXISTS AS A TYPE RATHER THAN AS A FILE READ. Today the per-agent layer is scattered
    across three stores with different lifetimes and different authorities: `in_scope` in a
    hand-edited `identity.json`, `instance_grants` in daemon memory, `scope_requests` in daemon
    memory. And for `claude-code` it lives in a fourth place — **nowhere**. That member has no
    MRH check at all, so its unlimited reach is not a grant anyone made; it is a question nobody
    asks. Measured 2026-08-03: a `dpx` path outside every workspace, invented by the member
    itself with no operator involvement, passed both the Read and Bash surfaces.

    An absent check cannot be audited, cannot expire, and cannot be revoked. dp's P0 ruling
    already forbids it — *"any per-agent or per-role modifications have to be an explicit part of
    the one law"* — and an omission is not an explicit part of anything. So `scope` has **no
    permissive default**: a member with unlimited reach must say so, in `UNSCOPED`, and that
    declaration is a recorded grant rather than a silence.

    THE VAULT IS THE AUTHORITY (dp, 2026-08-03). Not `identity.json`. That file is hand-edited,
    lives beside the member's own config, and is writable by the member it governs — kimi
    declined to edit its own `in_scope` on exactly that reasoning, which was right and should not
    have depended on restraint. The vault is operator-controlled, sealed, and already holds the
    instance overlays.

    But the local gate must still decide when the daemon is down, or "stop the daemon, then act"
    becomes the bypass. So: **vault is authority, the local file is a derived replica.**

    **"STALE IS NARROWER" WAS FALSE, AND IT WAS THE PREMISE THIS DESIGN RESTED ON.** (codex/gpt
    open-PR audit, 2026-08-04.) I argued a replica can only ever be staler, and staler-standing
    is narrower, so honouring it fails safe. That holds for grants ADDED since the copy. It
    fails for grants **REVOKED** since the copy: if the vault revoked `repo:restricted-project`, a
    replica still carrying it is **WIDER** than current policy. Revocation and expiry are
    precisely the operations a policy authority most needs to work, and precisely the ones the
    fallback silently defeated.

    So a replica is not trusted for being old. It is trusted for being **CERTIFIED**, and only
    within limits it carries itself:

      * `generation` — a monotonic counter issued by the authority. A replica with no
        generation makes no claim about which policy it is and is refused outright.
      * `expires_at` — a wall-clock horizon written by the authority. Past it, the replica is
        refused rather than honoured, because the longer the daemon has been unreachable the
        more likely a revocation has happened that this copy cannot know about. Bounded
        staleness is the only kind that is safe.
      * never widens — a replica may never yield `UNSCOPED` (see `evaluate`), so the one value
        a member would write into its own file to escape cannot come from this path.

    What is still NOT solved, stated because the audit was right that the last version claimed
    more than it did: this module cannot verify a signature it has no key for, and a
    member-writable file can forge a generation as easily as a scope. **Certification has to be
    a MAC or signature the authority issues and the gate verifies**, and that needs a key
    distribution this file does not own. Until then `generation`/`expires_at` bound the damage
    and make the gap explicit; they do not close it. The honest summary is that a stale replica
    is now *time-limited and self-describing*, not *authenticated*.

    ISSUANCE LANDED (Sprint F R1, 2026-08-14). The two fields were honor-side only — this
    class demanded them and nothing issued them. The daemon now does: `hestia_scope_status`
    serves its durable standing-scope store's monotonic `generation` and a daemon-issued
    `snapshot_expires_at`, `fetch_policy_snapshot` carries both, and `resolve_agent_policy`'s
    vault branch stamps them onto the returned policy — refusing the snapshot outright past
    its horizon. The forgery gap in the paragraph above stands: issued is not yet *signed*.
    """

    #: Sentinel for "this member is deliberately unscoped." Never inferred from an empty list —
    #: empty means *nothing granted*, and conflating the two is how an absent check becomes a
    #: silent permission.
    UNSCOPED = "*"

    member_id: str
    #: Repo names and `path:` grants. `["*"]` = deliberately unscoped, and must be declared.
    scope: tuple = ()
    #: Where this policy was resolved from, carried so a reader never has to guess which store
    #: won. A policy that cannot say where it came from is not auditable.
    source: str = "unresolved"
    #: True when the daemon could not be consulted and this is the on-disk replica.
    stale: bool = False
    #: Monotonic generation issued by the policy authority. A replica may only be honoured if
    #: it carries one; `None` means the file made no claim about which policy it is.
    generation: Optional[int] = None
    #: Wall-clock second after which this replica must not be honoured at all.
    expires_at: Optional[int] = None

    def is_unscoped(self) -> bool:
        return self.UNSCOPED in self.scope


@dataclass(frozen=True)
class HarnessProfile:
    """Everything a harness may legitimately differ in — SYNTAX ONLY.

    If a shim needs something not here, the answer is a new field, not a branch in the shim.
    And if the thing it needs is a *policy* choice, it does not belong here at all: that is
    `AgentPolicy`, and mixing the two is how five harnesses came to disagree about who may
    touch what."""

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
    #: Repository NAMES an MCP connector call targets (codex §3.4: the call names a repo
    #: in its own argument and carries REPO-RELATIVE paths). Scoped by NAME at Gate 1b;
    #: when present, `paths` are repo-relative and are egress-scanned but NOT re-scoped
    #: (the 2026-07-26 false-deny class). Sprint F: this moved the last shim-side scope
    #: decision (codex's mcp_repo check) into the one law.
    repos: list = field(default_factory=list)
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


# ── The reach domain: which (tool, key) values are filesystem reach (#734's other half) ────
# The predicate was collapsed first; the DOMAIN it runs over stayed per-seat, and the seats
# disagreed with receipts on both sides. codex/kimi excluded `pattern` because pattern-as-path
# false-denied every Glob whose matcher did not look like a granted repo (kimi live,
# 2026-07-23). gemini included it because its `glob` tool's pattern IS the reach — and gemini
# also learned that omitting `include`/`exclude` let an out-of-scope
# `include:["../restricted-project/**"]` through Gate-1b entirely (source-verified against
# tools/definitions/base-declarations.ts). Both were right about their own harness and the
# census called it divergence. So the table is (tool, key)-aware: `pattern` is reach ONLY on
# glob-shaped tools, where the matcher walks the filesystem; on a grep-shaped tool it is a
# regex over contents and treating it as a path manufactures the 07-23 class — gemini was
# doing exactly that to `search_file_content` until this table.
#
# One extraction, declared once. Seats call `path_targets(tool, tool_input)` and may not
# re-decide which keys are paths (GATE_ARCHITECTURE §2: the (tool, key) -> value-kind mapping
# is the gate's data, not the shim's code).
PATH_KEYS = ("path", "file_path", "absolute_path", "notebook_path", "dir_path")
PATH_LIST_KEYS = ("paths", "file_paths")
GLOB_KEYS = ("include", "exclude")            # reach-bearing globs; list or str
PATTERN_REACH_TOOLS = ("glob",)               # tools whose `pattern` walks the filesystem


def path_targets(tool_name, tool_input):
    """Every reach-bearing string in a tool call, by the ratified (tool, key) table above.

    Returns a list of raw strings (paths and globs); scope resolution happens in
    `path_in_scope`, which resolves relative values against the event cwd — so a traversal
    glob like `../elsewhere/**` is judged where it lands, not by its spelling."""
    out = []
    if not isinstance(tool_input, dict):
        return out
    for k in PATH_KEYS:
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v)
    for k in PATH_LIST_KEYS + GLOB_KEYS:
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str) and x.strip())
    if isinstance(tool_name, str) and tool_name.lower() in PATTERN_REACH_TOOLS:
        v = tool_input.get("pattern")
        if isinstance(v, str) and v.strip():
            out.append(v)
    return out


# ── Workspace + scope resolution ─────────────────────────────────────────────────────────
def detect_workspace(profile: HarnessProfile) -> str:
    """Resolve explicit install scope and otherwise fail narrow.

    A public gate cannot infer an operator's repository names or home layout. Installers
    should always set ``HESTIA_WORKSPACE``. A ``.hestia-workspace`` marker is the portable
    fallback; absent either signal, cwd is returned and sibling-repository grants remain
    inert rather than widening from a guess.
    """
    env = os.environ.get(profile.workspace_env)
    if env and os.path.isdir(env):
        return env
    d = os.getcwd()
    for _ in range(8):
        if os.path.isfile(os.path.join(d, ".hestia-workspace")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


#: Prefixes an `in_scope` entry may carry. Recognised DELIBERATELY rather than stripped by a
#: blind `split(":", 1)[-1]` (kimi #188, finding 3): that form silently collapsed `repo:*` and
#: `path:*` to the bare wildcard, so an operator writing what looks like "every repo" would
#: have granted "everything, including outside the workspace" — UNSCOPED by emergent side
#: effect rather than by decision. An unknown prefix is now dropped rather than guessed at.
_SCOPE_PREFIXES = ("repo:", "path:")


def now_secs() -> int:
    """Wall clock, isolated so a test can bound expiry without patching the stdlib."""
    import time
    return int(time.time())


def _parse_scope_entries(entries) -> tuple:
    """`["repo:web4", "path:.git-inbox"]` -> `("web4", "path:.git-inbox")`.

    Repo grants become segment names; path grants retain their type. Collapsing both to
    bare strings made an absolute path grant permanently unmatchable by the segment-keyed
    repo rule (#596): ``/workspace`` can never equal the first segment ``repo``.

    Raises on a non-string element so the caller can fail closed rather than let an
    AttributeError escape the gate. Only a BARE `"*"` yields the unscoped marker; a prefixed
    wildcard is refused outright, because "every repo" and "no boundary at all" are different
    grants and the difference must not turn on parser incidentals."""
    out = []
    for e in entries:
        if not isinstance(e, str):
            raise TypeError(f"scope entry is not a string: {e!r}")
        e = e.strip()
        if e == AgentPolicy.UNSCOPED:
            out.append(AgentPolicy.UNSCOPED)
            continue
        for prefix in _SCOPE_PREFIXES:
            if e.startswith(prefix):
                rest = e[len(prefix):]
                # A prefixed wildcard is NOT unscoped. Dropped, loudly-by-absence: the operator
                # who meant "everything" writes a bare "*", which is auditable as such.
                if rest and rest != AgentPolicy.UNSCOPED and rest.strip("."):
                    out.append(("path:" + rest) if prefix == "path:" else rest)
                break
        else:
            # An UNRECOGNISED prefix is dropped, not kept (kimi #937, finding C, sharpened by
            # probe). The comment above claimed "dropped"; the code kept it, and kept was not
            # inert: `ssh:/etc` cannot match a first path segment, but `ssh:etc` CAN — it
            # grants a workspace child literally named that. That is finding 3's defect one
            # shape over: a parser incidental producing a grant nobody wrote. Fails narrow —
            # a legitimate entry misspelled this way is denied and asks for scope.
            if ":" in e:
                continue
            # Unprefixed and not the wildcard: a bare repo name, the legacy spelling.
            if e:
                out.append(e)
    # A scope entry is a NAME. `.` and `..` are path syntax, cannot name a directory, and each
    # granted wide as a bare entry (kimi #940 B1-B4): scope `.` reached every repo via the
    # `/./` spelling, scope `..` reached past the workspace root. Normalising first (see
    # path_in_scope) already makes them unmatchable — but "unmatchable" is a claim about a
    # matcher, and this thread reversed exactly that claim once already (#937 finding C:
    # `ssh:/etc` was inert, `ssh:etc` granted). Dropped here too, so the guarantee does not
    # depend on the caller of the day. No live policy carries one; all are bare repo names.
    return tuple(s for s in out if s.strip("."))


def _scope_parts(scopes, workspace: str) -> tuple:
    """Return ``(repo_names, resolved_path_roots)`` without conflating their semantics.

    Relative path grants are rooted at the configured workspace. Both grants and candidates
    use ``realpath`` so a symlink below an allowed directory cannot turn a lexical descendant
    into an ungranted read elsewhere. Containment is tested at the separator by the caller.
    """
    repos = []
    roots = []
    ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/")
    for scope in scopes:
        if not isinstance(scope, str):
            continue
        if scope.startswith("path:"):
            raw = os.path.expanduser(scope[len("path:"):]).replace("\\", "/")
            if not raw:
                continue
            if not raw.startswith("/"):
                raw = os.path.join(ws, raw)
            root = os.path.realpath(os.path.normpath(raw)).replace("\\", "/").rstrip("/")
            if root:
                roots.append(root)
        else:
            repos.append(scope)
    return tuple(repos), tuple(roots)


def _within_path_grant(path: str, scopes, workspace: str) -> bool:
    """Whether ``path`` is exactly a granted path root or descends from one."""
    candidate = os.path.realpath(os.path.normpath(path)).replace("\\", "/").rstrip("/")
    _, roots = _scope_parts(scopes, workspace)
    return any(candidate == root or candidate.startswith(root + "/") for root in roots)


def resolve_agent_policy(profile: HarnessProfile,
                         vault_reader=None) -> AgentPolicy:
    """Resolve the per-agent layer, naming the store it came from.

    PRECEDENCE, and the reason for it:

      1. **vault** — the authority (dp, 2026-08-03). Operator-controlled, sealed, and not
         writable by the member it governs.
      2. **local replica** — the derived `identity.json`, used only when the vault cannot be
         reached. Marked `stale=True` so a caller can refuse to honour *grants* from it while
         still enforcing *standing scope*. A replica can only ever be staler than the vault, and
         staler-standing is narrower, so enforcing it is the safe direction.
      3. **nothing** — and nothing means NOTHING GRANTED, not everything permitted.

    `vault_reader` is injected rather than imported so the core stays transport-free and
    testable: the shim supplies a callable that returns this member's policy dict, or None when
    the daemon is unreachable. The core must not know how to open a socket.

    THE DEFAULT IS EMPTY, DELIBERATELY. The previous `load_in_scope` returned `["web4"]` on any
    failure — a narrow guess, but still a guess, and a guess that GRANTS. Here an unresolvable
    policy grants nothing and says so in `source`. A member that should be unscoped declares
    `["*"]`; it is never inferred."""
    # 1. Vault — the authority.
    if vault_reader is not None:
        try:
            got = vault_reader(profile.member_id)
        except Exception:
            got = None
        if isinstance(got, dict):
            scope = got.get("in_scope")
            if isinstance(scope, list):
                # PARSE INSIDE THE GUARD (kimi #188, finding 2). The reader call was wrapped and
                # the parse was not, so a non-string element in `in_scope` propagated an
                # AttributeError out of the gate. On a fail-open harness an exception escaping
                # the gate IS an allow — the exact shape `_deny` was corrected for earlier in
                # this file. Bad data must resolve to "unresolved", never to a traceback.
                try:
                    parsed = _parse_scope_entries(scope)
                except Exception:
                    parsed = None
                if parsed is not None:
                    # CERTIFICATION FIELDS, issued by the authority (Sprint F R1): the
                    # daemon's standing-store generation and its honor horizon ride the
                    # snapshot and are stamped onto the policy, so a caller (or a future
                    # replica-writer) can say WHICH policy it holds and until when.
                    # Tighten-only: a snapshot past its own horizon grants NOTHING — the
                    # authority said how long the copy could be honoured and is taken at
                    # its word — and absent fields leave pre-R1 behaviour untouched.
                    # bool is excluded because isinstance(True, int) holds in Python.
                    gen = got.get("generation")
                    exp = got.get("expires_at")
                    gen = gen if isinstance(gen, int) and not isinstance(gen, bool) else None
                    exp = exp if isinstance(exp, int) and not isinstance(exp, bool) else None
                    if exp is not None and now_secs() >= exp:
                        return AgentPolicy(member_id=profile.member_id, scope=(),
                                           source="vault-expired", stale=True,
                                           generation=gen, expires_at=exp)
                    return AgentPolicy(
                        member_id=profile.member_id, scope=parsed, source="vault",
                        generation=gen, expires_at=exp,
                    )

    # 2. Local replica — fail-closed fallback, marked stale.
    try:
        with open(os.path.expanduser(profile.identity_path), encoding="utf-8") as fh:
            mrh = json.load(fh).get("mrh", {})
        scope = mrh.get("in_scope")
        if isinstance(scope, list):
            # A REPLICA MUST SAY WHICH POLICY IT IS AND HOW LONG IT IS GOOD FOR.
            # Absent either, it is not a certified replica — it is just a file. Refused,
            # because "old" was never the safety property; BOUNDED and DECLARED is.
            cert = mrh.get("replica") if isinstance(mrh.get("replica"), dict) else {}
            gen = cert.get("generation")
            exp = cert.get("expires_at")
            if not isinstance(gen, int) or not isinstance(exp, int):
                return AgentPolicy(member_id=profile.member_id, scope=(),
                                   source="replica-uncertified", stale=True)
            if now_secs() >= exp:
                # The longer the authority has been unreachable, the likelier a revocation
                # this copy cannot know about. Expiry is the bound on that unknowability.
                return AgentPolicy(member_id=profile.member_id, scope=(),
                                   source="replica-expired", stale=True)
            return AgentPolicy(
                member_id=profile.member_id,
                scope=_parse_scope_entries(scope),
                source="local-replica",
                stale=True,
                generation=gen,
                expires_at=exp,
            )
    except Exception:
        pass

    # 3. Nothing resolved. Grant nothing, and be legible about why.
    return AgentPolicy(member_id=profile.member_id, scope=(), source="unresolved", stale=True)


# ── DELETED, not shared (gate-consolidation PRD §6.D, §7.1(4)) ──────────────────────────
#
# `load_in_scope` — the blind `split(":", 1)[-1]` parse plus the permissive `["web4"]`-on-
# ANY-failure fallback (a guess that GRANTS) — and `identity_role` are GONE. Both derived
# authority from a member-writable identity file; the ratified target sources authority from
# `resolve_agent_policy` -> `AgentPolicy`, which grants NOTHING when nothing certifiable
# resolves. `launch_cwd_repo` below is the third of §6.D's authority-bearing trio and remains
# ONLY because `evaluate()` still consumes it; its replacement is an explicit launch-cwd
# grant in the certified policy snapshot.
# SPRINT-F: replace with certified snapshot (delete launch_cwd_repo at the evaluate() cutover).
# SPRINT-F RAN (2026-08-13) AND COULD NOT DELETE THIS: the daemon exposes NO launch-cwd
# grant surface (measured against core/src/server/handler.rs — no such tool exists, and
# §9 forbids inventing one), so the per-launch grant still derives from env/cwd here.
# Declared RED in the Sprint F notes; this bridge dies the day the certified snapshot
# carries an explicit launch-cwd grant.
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
    repo's subdir, not the workspace-root `scripts` dir (2026-07-23 false-deny class).

    NORMALISE FIRST, THEN LET CONTAINMENT DECIDE (kimi #940 B5). Normalisation used to run on
    the RELATIVE branch only, so an absolute path was judged on its lexical first segment:
    with scope `("repo-a",)`, `<ws>/repo-a/../repo-b/secret` took `seg = "repo-a"` and was
    GRANTED while resolving into an ungranted repo. The relative spelling of that same path
    was already denied — which pins the seat: the absolute branch skipping normpath, not the
    segment rule. Every caller-supplied spelling now resolves before anything reads a segment.

    Containment is also a boundary test, not `workspace in p`. That substring form judged any
    path merely CONTAINING the workspace string by whatever followed it. Same defect class as
    `_under_temp_root`'s pre-#169 `startswith(("/tmp",...))` — and the same fix: compare at
    the separator."""
    p = path.replace("\\", "/")
    if p.startswith("~"):
        p = os.path.expanduser(p).replace("\\", "/")
    elif not p.startswith("/"):
        cwd = (cwd or os.getcwd()).replace("\\", "/")
        p = os.path.join(cwd, p)
    p = os.path.normpath(p).replace("\\", "/")
    # HOME IS A BOUNDARY, NOT A SUBSTRING (GPT fleet-review blocker 8) -- the same class
    # _under_temp_root (codex #169) and the workspace branch (kimi #940 B5) were already
    # cured of, fixed the same way. The old form ran BEFORE normalisation and tested
    # `marker in path` / `startswith(expanduser(marker))`, so `~/.kimi-code-evil/x` (a
    # SIBLING anyone can create) and `~/.kimi-code/../.ssh/id` (traversal OUT of home)
    # both read as the member's own home. Now the candidate resolves first (expanduser +
    # cwd-join + normpath, above), each marker resolves via expanduser AND realpath (so a
    # symlinked home dir matches under either spelling), and containment compares at the
    # separator.
    low = p.lower()
    for marker in profile.home_markers:
        ex = os.path.expanduser(marker).replace("\\", "/").rstrip("/")
        for root in {ex, os.path.realpath(ex).replace("\\", "/").rstrip("/")}:
            m = root.lower()
            if m and (low == m or low.startswith(m + "/")):
                return True
    if _under_temp_root(p):
        return True
    if _within_path_grant(p, scopes, workspace):
        return True
    ws = workspace.replace("\\", "/").rstrip("/")
    if ws and (p == ws or p.startswith(ws + "/")):
        seg = p[len(ws):].lstrip("/").split("/", 1)[0]
        if seg == "":
            return False          # bare workspace root — the glob-the-root antipattern
        repo_scopes, _ = _scope_parts(scopes, workspace)
        return seg in repo_scopes
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
    repo_scopes, _ = _scope_parts(scopes, workspace)
    for after in cmd.split(workspace)[1:]:
        # Resolve the whole token before reading a segment off it (kimi #940 B7). Taking the
        # head lexically let `cat <ws>/repo-a/../repo-b/secret` pass on `repo-a` while
        # resolving into an ungranted repo — path_in_scope's B5 one function over. A command's
        # text is member-controlled end to end, so this one needs no harness to cooperate.
        tok = re.split(r"""[\s"'`);&|<>]""", after.lstrip("/"), 1)[0]
        resolved = os.path.normpath(f"{ws}/{tok}").replace("\\", "/")
        if resolved != ws and not resolved.startswith(ws + "/"):
            return False, (tok or "<workspace root>")   # traversed out of the workspace
        seg = resolved[len(ws):].lstrip("/").split("/", 1)[0]
        if seg not in repo_scopes and not _within_path_grant(resolved, scopes, workspace):
            return False, (seg or "<workspace root>")

    # Pass 2 — relative tokens. The event cwd is NOT reliable: the engine may run each command
    # with a per-command workdir the event does not carry (observed live via the Codex gate —
    # event cwd = session launch dir while the command ran inside a granted repo). So a token
    # is judged by its PLAUSIBLE interpretations — the event cwd plus every granted repo root —
    # voting by what EXISTS: an existing in-scope interpretation passes; an existing
    # out-of-scope one with no in-scope alternative denies; a token that exists nowhere is not
    # a reach.
    cwd = (cwd or os.getcwd()).replace("\\", "/")
    bases = [cwd] + [f"{ws}/{s}" for s in repo_scopes]
    oos_names = {r for r in _all_repos(workspace) if r not in repo_scopes}
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
                    if seg in repo_scopes or _within_path_grant(cand, scopes, workspace):
                        in_scope_vote = True
                        break
                    oos_vote = seg
                elif _within_path_grant(cand, scopes, workspace):
                    in_scope_vote = True
                    break
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
    `/outside/workspace/` was outside `HESTIA_WORKSPACE` altogether, and saying it was 'not
    granted' would have implied a grant could fix it).

    Normalises on the same rule as `path_in_scope`, and must: judged lexically, the deny for
    `<ws>/repo-a/../repo-b/secret` read "'repo-a' is not granted" — naming the repo the member
    DOES hold as the offender, for a reach that resolved into `repo-b`. A member handed that
    would go asking for scope it already has. This is the defect in this function's own
    docstring — a deny that hides its trigger — arriving through the segment rule instead of
    through truncation."""
    p = path.replace("\\", "/")
    if not p.startswith("/") and not p.startswith("~"):
        p = os.path.join((cwd or os.getcwd()).replace("\\", "/"), p)
    p = os.path.normpath(p).replace("\\", "/")
    ws = workspace.replace("\\", "/").rstrip("/")
    if ws and (p == ws or p.startswith(ws + "/")):
        seg = p[len(ws):].lstrip("/").split("/", 1)[0]
        return seg or "<workspace root>"
    return None


def forbidden_tokens(profile: HarnessProfile) -> tuple:
    extra = os.environ.get(profile.forbidden_extra_env, "")
    return FORBIDDEN_DEFAULT + tuple(t.strip() for t in extra.split(",") if t.strip())


# ── The decision ─────────────────────────────────────────────────────────────────────────
def evaluate(event: NormalizedEvent, profile: HarnessProfile,
             workspace: Optional[str] = None,
             policy: Optional[AgentPolicy] = None) -> Verdict:
    """The whole local policy, for every harness.

    Order is deliberate and is the O clause of the accountability audit: the innate egress
    check dominates everything, then MRH scope. Society safety (the daemon call) is the
    SHIM's second stage and is not decided here, because it needs a live transport — but a
    shim must treat an unreachable daemon as `society.unreachable`, never as allow.

    Never calls sys.exit. A shim that gets no Verdict must deny; making that impossible to
    confuse with an allow is the reason this returns a value instead of exiting."""
    ws = workspace or detect_workspace(profile)
    # THE PER-AGENT LAYER, resolved once and named. `policy` is passed by the shim when it can
    # reach the vault; otherwise resolved here from the replica. Either way the gate consults
    # ONE object rather than three stores and an absence.
    pol = policy if policy is not None else resolve_agent_policy(profile)
    scopes = list(pol.scope) + launch_cwd_repo(profile, ws)
    forbidden = forbidden_tokens(profile)

    # Gate 1a — innate egress/secret. Denied even inside a granted repo, always enforced.
    # Repo names are scanned too: an MCP call naming a forbidden token is still egress.
    for blob in (list(event.paths) + list(event.repos)
                 + ([event.command] if event.command else [])):
        low = blob.lower()
        for f in forbidden:
            if f in low:
                return _deny(
                    "egress.secret",
                    f"'{event.tool}' touches a forbidden path (secret/credential or "
                    f"out-of-MRH private repo): '{f}'",
                    innate=True,
                )

    # A DELIBERATELY UNSCOPED MEMBER SKIPS 1b — AND ONLY 1b.
    #
    # Placed after gate 1a on purpose: `*` is a scope grant, not a licence, so it never buys a
    # credential. The innate egress invariant above binds every member equally and is the one
    # thing trust does not relax.
    #
    # This is what makes claude-code's unlimited reach a RECORDED GRANT instead of an absent
    # check. Before, that member had no MRH evaluation at all — measured 2026-08-03, a dpx path
    # outside every workspace passed both Read and Bash with no operator involvement. Now the
    # same outcome requires someone to have written `*` into the vault, where it can be audited,
    # revoked, and expired. Same behaviour, opposite accountability.
    # ...AND ONLY FROM A TRUSTED SOURCE. `stale` was written in three places and read in NONE
    # (kimi NOT-SAME review of #188, finding 1). `evaluate()` never inspected it, and no call
    # passes a `vault_reader` today — so every resolution came from `identity.json`, the file
    # this module's own docstring calls member-writable, and was honoured in full INCLUDING the
    # unscoped bypass. **A member could write `"*"` into its own identity file and receive
    # blanket ALLOW.** The audit block I shipped claimed the opposite on two lines
    # (`W: the member cannot write its own authority`, `V: stale replica cannot add grants`),
    # which per CLAUDE.md is itself an A violation: the block described the intent, not the
    # build. Fourth time in this thread I verified the artifact rather than the behaviour — the
    # field existed and the docstring explained it, and nothing read it.
    #
    # WHY `*` IS TREATED DIFFERENTLY FROM A STALE REPO LIST, since both come from the same
    # untrusted file: a repo list widens to specific named directories and stays bounded by the
    # workspace, so a compromised replica buys named, auditable reach. `*` removes the boundary
    # entirely, and is precisely the value a member would write to escape. Different in kind,
    # not degree. Standing scope from a stale replica is still honoured — that is what keeps a
    # down daemon from bricking every member — but it can never widen to everything.
    if pol.is_unscoped():
        if not pol.stale:
            return ALLOW
        # Stale + unscoped: drop the wildcard so it cannot match downstream, and evaluate the
        # remaining standing scope normally. Fails narrow, which is the direction a replica may
        # move in.
        scopes = [s for s in scopes if s != AgentPolicy.UNSCOPED]

    # Gate 1b — MRH scope. A repo-named MCP call is scoped on the NAME it carries (its
    # `paths` are repo-relative and must not be re-scoped — egress above already saw
    # them); file paths use path-scope; shell commands use command-scope.
    if event.repos:
        for rname in event.repos:
            if rname not in scopes:
                return _deny(
                    "mrh.repo",
                    f"'{event.tool}' targets repository '{rname}' outside your granted "
                    f"scope (granted: {'+'.join(scopes)})",
                )
    for p in ([] if event.repos else event.paths):
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


# ── The ratified degraded mode (Sprint F — PRD §7.1 criterion 9) ────────────────────────
# Read-only command verbs for the DEGRADED grammar. Two tiers: bare verbs read-only by
# nature, and git subcommands that only inspect (fetch deliberately absent: it writes
# .git objects/refs; fine normally, but degraded mode has no referee to ask).
_DEGRADED_READ_VERBS = frozenset((
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "stat", "file", "df",
    "du", "date", "uptime", "which", "whoami", "id", "env", "grep", "rg", "find",
    "readlink", "realpath", "basename", "dirname", "sort", "uniq", "cut", "tr", "true",
))
_DEGRADED_GIT_READ_SUBS = frozenset((
    "status", "log", "show", "diff", "branch", "describe", "rev-parse", "rev-list",
    "ls-files", "ls-tree", "ls-remote", "remote", "blame", "shortlog", "tag",
    "merge-base", "cat-file", "count-objects", "config",
))


def _degraded_command_is_read(command: str) -> bool:
    """True iff EVERY simple command is a known read verb and nothing in the line can
    write: any redirect (>, >>), substitution ($(, backtick), or unknown verb -> False.
    Pipes between read verbs are fine (git log | head). Conservative by construction —
    a miss here costs a retry-after-daemon-returns, never a leak."""
    if any(tok in command for tok in (">", "$(", "`", "<<")):
        return False
    for chunk_or in command.split("||"):
        for chunk_and in chunk_or.split("&&"):
            for chunk_semi in chunk_and.split(";"):
                for seg in chunk_semi.split("|"):
                    words = seg.strip().split()
                    if not words:
                        continue
                    head = words[0].rsplit("/", 1)[-1]
                    if head == "git":
                        sub = next((w for w in words[1:] if not w.startswith("-")), "")
                        if sub not in _DEGRADED_GIT_READ_SUBS:
                            return False
                        # `git config` writes unless read-flagged; `git remote` writes
                        # unless bare/-v; `git tag` writes unless bare/-l/--list.
                        if sub == "config" and not any(
                                w in ("--get", "--list", "-l") for w in words[2:]):
                            return False
                        if sub == "remote" and len(words) > 2 and words[2] not in ("-v",):
                            return False
                        if sub == "tag" and len(words) > 2 and not any(
                                w in ("-l", "--list") for w in words[2:]):
                            return False
                        if sub == "branch":
                            # `git branch NAME` CREATES (GPT post-merge review, #424), so any
                            # POSITIONAL after `branch` denies. But a read flag's VALUE is not a
                            # positional: `git branch -a --contains HEAD` lists, and refusing it
                            # is an over-refusal with no workaround — the last gap PR #322's case
                            # set names, and FP rate is a security control (#393). Consume known
                            # read-flag values before looking for positionals.
                            rest2 = list(words[2:])
                            _val_flags = ("--contains", "--no-contains", "--merged",
                                          "--no-merged", "--points-at", "--sort", "--format",
                                          "--color", "--column")
                            pos, skip = [], False
                            for w in rest2:
                                if skip:
                                    skip = False          # a read flag's value, not a branch name
                                    continue
                                if w in _val_flags:
                                    skip = True
                                    continue
                                if not w.startswith("-"):
                                    pos.append(w)
                            if pos:
                                return False              # a real positional -> create/rename
                            # Write flags must match in BOTH spellings. Exact-match alone let the
                            # attached form (`--set-upstream-to=origin/main`) through as a READ —
                            # a write reading as a read, the one direction this grammar must never
                            # fail in. Caught by the standalone check before it reached this file.
                            for w in rest2:
                                if w.split("=", 1)[0] in (
                                        "-d", "-D", "-m", "-M", "-c", "-C", "-f", "--force",
                                        "--set-upstream-to", "--unset-upstream",
                                        "--edit-description", "-u", "--track", "--no-track"):
                                    return False
                    elif head not in _DEGRADED_READ_VERBS:
                        return False
                    elif head == "find" and any(
                            w in ("-delete", "-exec", "-execdir", "-ok", "-okdir",
                                  "-fprint", "-fprintf", "-fls", "-fprint0")
                            for w in words[1:]):
                        return False  # find's mutating/executing actions (GPT, #424)
                    elif head == "sort" and any(
                            w == "-o" or w.startswith("--output") for w in words[1:]):
                        return False  # sort -o FILE writes
                    elif head == "env" and any(
                            not w.startswith("-") and "=" not in w for w in words[1:]):
                        return False  # env with a positional EXECUTES it
    return True


def degraded_verdict(event: NormalizedEvent,
                     profile: Optional[HarnessProfile] = None) -> Verdict:
    """Tier-1 degraded posture, computed by the CORE: deny-writes-allow-reads.

    Semantics + trigger ratified (dp, 2026-08-11): the posture is deny-writes-allow-reads
    and the trigger is the DAEMON/REFEREE BEING UNREACHABLE — a shim calls this when, in
    enforce mode, no policy snapshot could be fetched. This module is transport-free (it
    opens no socket), so it stays available exactly when the daemon is not; the shim-level
    literal backstop (Tier 2) exists only for the rare case this module itself will not
    import.

    Tighten-only, in both directions that matter: the innate egress invariant still binds
    the reads this mode allows (a degraded gate that leaked a credential read would be a
    LOOSENING, and egress is the one rule no mode relaxes), and a shim may deny reads too
    but may never allow a write. Never raises, never exits — same contract as evaluate().

    Recording is the CALLER's duty (criterion 9(c)): every degraded deny must land in the
    per-shim diagnostic log via the unified recorder with verdict_available=False — an
    unrecorded degraded deny is the PR #357 defect this criterion exists to end; degraded
    read-allows are recorded on the gate-availability telemetry instead (they are an infra
    series, not refusals, and the deny log's readers expect denies)."""
    forbidden = forbidden_tokens(profile) if profile is not None else FORBIDDEN_DEFAULT
    for blob in (list(event.paths) + list(event.repos)
                 + ([event.command] if event.command else [])):
        low = blob.lower()
        for f in forbidden:
            if f in low:
                return _deny(
                    "egress.secret",
                    f"'{event.tool}' touches a forbidden path (secret/credential or "
                    f"out-of-MRH private repo): '{f}'",
                    innate=True,
                )
    if event.tool in READ_CLASS:
        return ALLOW
    if event.tool.lower() in ("bash", "shell") and event.command \
            and _degraded_command_is_read(event.command):
        # The ratified posture is deny-writes-allow-READS, and a read-only shell command
        # IS a read. Tool-level classing over-denied every Bash in degraded mode (measured
        # live on the codex seat 2026-08-14: `git rev-parse X && git log Y` and
        # `git rev-list --count` refused while single reads passed). The grammar below is
        # deliberately conservative: every segment's verb must be on the read allowlist,
        # any write-redirect/substitution/unknown verb keeps the deny.
        return ALLOW
    return _deny(
        "gate.degraded",
        f"'{event.tool}' is write/exec-class and the policy daemon is unreachable — the "
        f"ratified degraded mode denies writes and allows reads",
    )


# ── Gate availability telemetry ──────────────────────────────────────────────────────────
#
# A FAIL-CLOSED DENY IS NOT A MEMBER EVENT, AND IT NEVER REACHES THE CHAIN.
#
# dp, 2026-08-04: *"it is probably correct not to log timeout fail-closed, at least not as
# agent's fault because it's infra failure. but we should log it somewhere..."* — and then, on
# where: *"the chain is there to witness member events, not infra telemetry."*
#
# THE DEFECT THIS ANSWERS. When the daemon is unreachable the gate denies — correctly. It then
# tries to witness that deny through the same daemon it could not reach, the call fails, and
# `deny()` swallows it so a recording failure can never become a permission. There is no spool,
# so the event simply does not exist. dp saw one live: kimi hit
# `deny [fail-closed] — no policy verdict (daemon path failed for Edit)` and nothing appeared
# anywhere.
#
# The consequence is worse than a missing row. Every OTHER deny — scope, egress, safety — is
# recorded, because the daemon was up to record it. Only the daemon-down ones vanish. So the
# chain is **biased clean** exactly where infrastructure trouble would show, and the dashboard
# cannot display the problem it is a symptom of. kimi's measured "45% of 301 denies are
# daemon-down" came from WIRE LOGS, not the chain — which is precisely why it was measurable.
#
# WHY IT MUST NOT BE A CHAIN ENTRY, which is the part worth getting right. The absence was
# doing two jobs: protecting the member's record (right) and hiding the fault (wrong). If these
# denies were witnessed as `policy_decision`, they would score against the member — ~135 of 301
# at the measured rate — and the Temperament ladder reads a deny as *a boundary the member met
# and how it responded*. An unreachable daemon is not a boundary; it is a missing referee.
# Scoring it would corrupt conduct in the opposite direction and be very hard to unpick later.
#
# So: a different record, in a different place, with a different consumer. The chain witnesses
# what MEMBERS did. This file records whether the gate could decide at all.
#
# WHAT IT BUYS. Gate availability is currently unmeasurable from the chain — contention was
# inferred from wire logs and external latency probes. This gives a per-member series answering
# "how often can the gate not decide", which is the number that would have surfaced the
# contention weeks ago instead of an operator noticing a blank panel.

#: Appended by every harness, read by the member-mesh watcher. One JSON object per line.
#: Under `$HESTIA_HOME` because that is shared across members on a box and the watcher already
#: knows it — a per-member path would need discovery the watcher does not have.
GATE_TELEMETRY_RELPATH = "telemetry/gate-unavailable.jsonl"
GATE_TELEMETRY_STATE_RELPATH = "telemetry/gate-unavailable.state.json"

#: Refuse to grow without bound. Telemetry that fills a disk becomes an outage of its own, and
#: this file is written on exactly the path where the system is already unwell.
GATE_TELEMETRY_MAX_BYTES = 2 * 1024 * 1024


def record_gate_unavailable(member_id: str, tool: str, cause: str,
                            detail: str = "", home: Optional[str] = None) -> bool:
    """Record that the gate could not obtain a verdict. Returns True if written.

    NEVER RAISES, and never blocks a decision. This runs on the failure path of a system that
    is already degraded; a telemetry writer that can throw would convert an infra hiccup into a
    gate crash, and on a fail-open harness a gate crash is an ALLOW. The refusal has already
    been decided by the time this is called — nothing here can change it.

    `cause` distinguishes the two shapes the caller must respond to differently, and which the
    current deny text conflates:
        "timeout"  — the daemon is alive but starved. Back off and retry.
        "refused"  — nothing is listening. Stop and escalate to the operator.
        "unknown"  — could not tell. Say so rather than guessing; a wrong cause sends the
                     member to the wrong response, which is how a peer sat parked for four
                     minutes on 2026-07-28 while the daemon had been up for eight hours.
    """
    try:
        root = home or os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia")
        path = os.path.join(root, GATE_TELEMETRY_RELPATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Rotate rather than truncate: the oldest events are the ones that establish a trend,
        # and a file that silently restarts at zero is another absence-reads-as-quiet defect.
        try:
            if os.path.getsize(path) > GATE_TELEMETRY_MAX_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        rec = {
            "ts": int(__import__("time").time()),
            "member": member_id,
            "tool": tool,
            "cause": cause if cause in ("timeout", "refused", "unknown") else "unknown",
            "detail": detail[:200],
            # Stated in the record so a reader never has to infer it from the filename.
            "kind": "gate_unavailable",
            "note": "infrastructure availability, NOT a member act — must never score conduct",
        }
        # O_APPEND so concurrent members interleave whole lines rather than corrupting each
        # other. Several harnesses write this file at once, by design.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        # Maintain a bounded outage summary beside the per-act evidence. Consumers can
        # alert once per outage window without turning contention into an escalation storm.
        state_path = os.path.join(root, GATE_TELEMETRY_STATE_RELPATH)
        try:
            now = rec["ts"]
            state = {}
            try:
                with open(state_path, encoding="utf-8") as sf:
                    loaded = json.load(sf)
                    if isinstance(loaded, dict):
                        state = loaded
            except (FileNotFoundError, json.JSONDecodeError):
                state = {}
            same = state.get("cause") == rec["cause"] and now - int(state.get("last_ts", 0)) < 300
            if same:
                state["count"] = int(state.get("count", 0)) + 1
            else:
                state = {"first_ts": now, "count": 1, "cause": rec["cause"]}
            state["last_ts"] = now
            tmp = state_path + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as sf:
                json.dump(state, sf, sort_keys=True)
            os.replace(tmp, state_path)
        except Exception:
            pass
        return True
    except Exception:
        return False


def needs_society_gate(tool: str) -> bool:
    """Read-class is fully covered above, so only write/exec-class needs the daemon's verdict.
    This is what keeps a down daemon from bricking reads while still failing closed on writes."""
    return tool not in READ_CLASS
