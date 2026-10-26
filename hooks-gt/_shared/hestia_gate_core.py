#!/usr/bin/env python3
# hestia-gt-sha256: c8f6226726c9cc17e0e3a6b32081e6558a22717f95c1797c283c0f1fdcf5aa02  (published ground truth; manifest: hooks-gt)
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

import fnmatch as _fnmatch
import glob as _glob
import json
import os
import re
import shlex
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
    # THE common gate (one-gate stage C): every seat's shim delegates its whole decision to
    # it, so after the cutover it is the single file whose edit changes all four seats.
    "hestia_single_gate.py",
    # A harness whose gate entry is not named pre_tool_use.py. The closure also derives each
    # member's entry name from its install declaration; this is the canonical literal.
    "before_tool.py",
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
        "Adjust to work within scope. If the path is genuinely needed: when this refusal names "
        "a scope request id, the gate already opened it for you — a NOT-SAME peer decides it "
        "(this act once, for the session, or standing; the operator may override; you cannot "
        "decide your own), you can watch it with hestia_scope_status, and "
        "you re-issue this identical act afterwards. When no id is named, ask with "
        "hestia_request_scope (one path, with a reason). Do NOT appeal this: hestia_appeal asks "
        "whether the deny was WRONG and returns a verdict on conduct; it cannot and must not "
        "hand you a file. If you believe the deny itself was wrong, that is the appeal, and it "
        "is a separate act.",
        ("hestia_request_scope", "hestia_scope_status", "hestia_appeal"),
    ),
    # AN UNENUMERABLE REACH (dp's ruling, 2026-10-14, hestia#1313: option (b) of three). The act's
    # reach depends on an expansion the gate does not model, so no path exists for a grant to
    # name. Until this ruling the refusal also opened a once-only peer scope request for the act;
    # measured on claude-code's own 50,091 recorded commands, 9,178 (18%) were such requests and
    # most lapsed or were refused as noise. Now it is its own rule, NOT a scope-escalating one
    # (mechanism.SCOPE_ESCALATING_RULES), so the single gate asks the daemon nothing, and the
    # remedy names the two rewrites that work. The rewrite is the asked-for act, not a recast.
    "mrh.command.unenumerated": Remedy(
        "Rewrite the act so the gate can see what it reaches. That rewrite is what this refusal "
        "asks for; it is not a recast. Either spell every path out literally (if a value comes "
        "from a command, run that command on its own first and use what it printed), or put "
        "the expansion in a script file and run the script by its literal path. No scope "
        "request was opened: no grant can name a path the gate cannot see. If the spelled-out "
        "command then reaches outside your scope, its own refusal opens a request for that "
        "path.",
        ("hestia_request_scope",),
    ),
    # A PHANTOM REACH (hestia#1327, the #1313 pattern). A relative `cd` is composed under every
    # earlier directory base, so `cd /ws && cd a && cd ../b` is also judged at `<cwd>/../b`, and
    # every later relative word under that. When neither the refused path nor its parent exists,
    # it names nothing a grant could be about, so it is NOT a scope-escalating rule: refused as
    # before (the over-approximation is the safe direction), but no peer request is opened.
    "mrh.command.nonexistent": Remedy(
        "The refused path does not exist, and neither does its parent directory: most often a "
        "relative cd composed under a directory the command never runs in. Spell the cd target "
        "absolutely (or use git -C / an absolute path) and re-issue. No scope request was opened: "
        "a grant cannot be about a path that names nothing. If the path is genuinely needed (the "
        "command creates it), ask with hestia_request_scope (one path, with a reason).",
        ("hestia_request_scope",),
    ),
    "mrh.command": Remedy(
        "Scope the command to a granted path. If the path is genuinely needed: when this "
        "refusal names a scope request id, the gate already opened it for you — a NOT-SAME "
        "peer decides it (this act once, for the session, or standing; the operator may "
        "override; you cannot decide your own), you can watch it with "
        "hestia_scope_status, and you re-issue this identical command afterwards. When no id "
        "is named, ask with hestia_request_scope (one path, with a reason). Do not rephrase the "
        "command to reach the same path another way. An appeal cannot deliver a path — "
        "hestia_appeal disputes whether the deny was right, which is a different question.",
        ("hestia_request_scope", "hestia_scope_status", "hestia_appeal"),
    ),
    # An MCP connector call names a REPOSITORY, not a path — the codex gate scopes on that
    # name (see mcp_repo_target there). Same door as mrh.path, worded for a repo so the
    # member is not sent asking for "a path" it never named. Added Sprint D (§6.D): before
    # this, that call site authored its own sentence, naming the request_scope phantom.
    "mrh.repo": Remedy(
        "Adjust to work within scope. Remote access requires a qualified entry "
        "`repo:<owner>/<name>` (the deny names it); a path grant, even recursive, never "
        "reaches a remote repository. Repository grants cannot yet be recorded by the "
        "operator or requested by a member (#1402). If the operator has already authorized "
        "the repository operation through the logged-in shell CLI (for example, gh), use "
        "that channel within its existing authority and gates. This refusal does not "
        "authorize another channel or a retry of a refused act. An appeal cannot deliver "
        "a repo — hestia_appeal disputes "
        "whether the deny was right, which is a different question.",
        ("hestia_appeal",),
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
    # Re-ruled 2026-10-01/02 (dp, one-gate stage B, live since stage C): "align upward; no
    # snapshot -> no read" and "no verdict, no act". Without the member's policy snapshot the
    # common gate denies EVERY act, reads included, in every rollout mode. `degraded_verdict`
    # below still runs first so an innate egress refusal keeps its own rule.
    "gate.degraded": Remedy(
        "The policy authority could not be consulted (the daemon did not answer with this "
        "member's policy snapshot), so no act is permitted, reads included: without the "
        "snapshot the gate cannot certify scope. This is fault isolation, not a judgement of "
        "your act — the referee is missing, not ruling against you. Retry when the daemon "
        "returns; if it stays down, that is an operator matter and not something to work "
        "around.",
        (),
    ),
    # ── the common gate's own refusals (hestia_single_gate.decide; moved here from that
    # module's GATE_REMEDIES in one-gate stage C, so every sentence a member reads after a
    # refusal comes from this one table) ─────────────────────────────────────────────────
    "invocation.superseded": Remedy(
        "This call's approval was re-delivered to another invocation of the same act. Do not "
        "retry this call; the invocation that reclaimed the approval carries it.",
        (),
    ),
    "gate.evidence_uncommitted": Remedy(
        "The gate reached a permit but could not commit its decision record before the "
        "deadline, and a consequential act may not run unwitnessed (C11). This is not a "
        "judgement of the act: retry once the daemon's witness path is answering.",
        (),
    ),
    "gate.internal_error": Remedy(
        "This is an infrastructure fault in the gate, not a judgement of the attempted act. "
        "The gate fails closed until the decision path is healthy; please report it.",
        (),
    ),
    # The shim could not establish how long its harness waits for it, so it cannot keep the
    # safety invariant (the gate's deadline strictly below the timeout the harness enforces).
    "gate.harness_timeout_unknown": Remedy(
        "The gate could not read how long this harness waits for it, so it refuses rather than "
        "risk being killed mid-decision (which this harness would treat as an allow). This is "
        "an installation fault, not a judgement of your act: an operator registers the hook "
        "with an explicit timeout (deploy/register-members.py). A non-harness caller declares "
        "the timeout it enforces in HESTIA_HOOK_TIMEOUT_S.",
        (),
    ),
    # The seat's vault projection does not authorise the role it was launched under
    # (launch_role_verdict, #1084).
    "config.miswired": Remedy(
        "This seat's configuration does not match what the vault authorises for it. That is an "
        "operator repair (Govern -> Runtime config), not a judgement of your act; retrying "
        "will not help.",
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
    #: Roots this member may READ and nothing more: the read-only society floor (dp,
    #: 2026-10-19, "the governed see the law" — every member reads the governance snapshot).
    #: Consulted by evaluate() only for an act that is a read; never widens a write.
    read_scope: tuple = ()
    #: Grants NARROWED to fewer than all four modes (hestia #1345 part B), as
    #: ``((entry, modes), ...)`` with `entry` parsed like `scope` and `modes` a subset of
    #: "rwed". Consulted by evaluate() only for an act whose mode it can name, and only when
    #: every mode that act needs is in the grant's. A full-mode grant stays in `scope`.
    mode_scope: tuple = ()
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
    #: The FULL remote identity (`owner/name`) of each entry in `repos`, index-aligned ("" when the call carried
    #: no owner). #1392: a name alone cannot be bound to a checkout -- `other-owner/hestia` and `dp-web4/hestia`
    #: both reduce to `hestia` -- so the recursive-grant admission binds on this, never on the bare name.
    repo_full: list = field(default_factory=list)
    command: Optional[str] = None               # shell command, if any
    cwd: Optional[str] = None
    raw: dict = field(default_factory=dict)     # kept for witnessing, never for deciding
    #: Text that LEAVES THE MACHINE: a web query, a url, a prompt or context handed to a remote
    #: model (#1201). Gate 1a sweeps it with the same innate `egress.secret` rule as paths, repos
    #: and the command. Gate 1b NEVER reads it: natural language is not a path, and scoping its
    #: words is the false-deny SAGE #335 measured ("'models' is not granted"). The field can
    #: only ADD a deny. Default empty: an event that declares no egress is judged as before.
    egress: list = field(default_factory=list)


def egress_items(value: object) -> Optional[list]:
    """Declared egress as the strings Gate 1a sweeps, or None when it cannot be swept.

    A string is ONE blob. `list("~/.ssh/id_rsa")` is fourteen one-character blobs that match no
    token, which is how a bare string slipped past the first #1201 patch (NOVA HOLD at 7a6e410b).
    A list or tuple contributes its strings, flattened through nested lists/tuples, and None
    entries are skipped. Anything else (a dict, bytes, a number, a set, a generator) is not text
    this gate can read whole, so it returns None and the caller fails closed."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        return None
    out: list = []
    for x in value:
        if x is None:
            continue
        sub = egress_items(x)
        if sub is None:
            return None
        out.extend(sub)
    return out


def egress_unsweepable(event: "NormalizedEvent") -> str:
    """The type name of declared egress that `egress_items` cannot sweep; "" when it can."""
    raw = getattr(event, "egress", None)
    return type(raw).__name__ if egress_items(raw) is None else ""


def egress_unsweepable_deny(event: "NormalizedEvent") -> Optional["Verdict"]:
    """Gate 1a's fail-closed half: egress the gate cannot read whole is denied, never passed
    unread. Both Gate 1a sites call it before the token sweep, so the degraded mode does too."""
    bad = egress_unsweepable(event)
    if not bad:
        return None
    return _deny("egress.secret",
                 f"'{event.tool}' declares egress the gate cannot sweep ({bad}): egress must be "
                 f"a string or a list of strings, so it is denied rather than sent unread",
                 innate=True)


def egress_blobs(event: "NormalizedEvent") -> list:
    """Every string Gate 1a sweeps for the innate forbidden tokens: paths, repos, declared
    egress text, and the command. `getattr`, not attribute access: a caller's own event
    shape (SAGE's test fakes) may predate the `egress` field, and that must read as none.
    Unsweepable egress contributes nothing here; `egress_unsweepable_deny` has refused it."""
    return (list(event.paths) + list(event.repos)
            + (egress_items(getattr(event, "egress", None)) or [])
            + ([event.command] if event.command else []))


@dataclass(frozen=True)
class Verdict:
    decision: str          # "allow" | "warn" | "deny"
    rule: str = ""         # stable id; the key into REMEDIES
    reason: str = ""       # what tripped, naming the offending token
    remedy: str = ""       # from REMEDIES — never authored at a call site
    innate: bool = False   # true = not relaxable by warn-mode or by any grant
    #: The resolved absolute path a SCOPE refusal judged (mrh.path / mrh.command), carried as
    #: data so the escalation path can open a scope request for exactly what was refused
    #: (2026-10-05, dp: "escalation should allow standing grants"). Rebuilding it from the
    #: reason text is the #1003 defect (right repo, wrong depth); the checker knows the path.
    target: str = ""

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


def _deny(rule: str, reason: str, innate: bool = False, target: str = "") -> Verdict:
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
                       UNREGISTERED_RULE_REMEDY, innate, target)
    return Verdict("deny", rule, reason, r.text, innate, target)


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


#: The four grant modes (hestia #1345), in their canonical order.
GRANT_MODES = "rwed"


def _parse_mode_scope(raw) -> tuple:
    """`[{"entry": "path:/x/**", "modes": "r"}, ...]` -> `(("path:/x/**", "r"), ...)`.

    Each entry is parsed exactly as an `in_scope` entry is (one entry, one parse), and its
    modes are reduced to letters of "rwed" in canonical order. Anything malformed is dropped,
    whole: bad data here reads as NO narrowed grant, never as a traceback and never as reach.
    An entry whose modes are empty, or carry a letter outside "rwed", is dropped rather than
    trimmed: a mode set nobody wrote must not be repaired into one that admits something.
    A bare `*` is never honoured here: a narrowed grant names a place."""
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry, modes = item.get("entry"), item.get("modes")
        if not isinstance(entry, str) or not isinstance(modes, str) or not modes:
            continue
        if any(m not in GRANT_MODES for m in modes):
            continue
        try:
            parsed = _parse_scope_entries([entry])
        except Exception:
            continue
        if len(parsed) != 1 or parsed[0] == AgentPolicy.UNSCOPED:
            continue
        out.append((parsed[0], "".join(m for m in GRANT_MODES if m in modes)))
    return tuple(out)


#: A `path:` grant that ends in this reaches its whole subtree; a bare one reaches exactly
#: its path (dp, 2026-09-08: "the exact path is useful, and is preferred as default.
#: recursive should be an option"). Spelled in the entry so an older consumer fails closed.
RECURSIVE_SUFFIX = "/**"


def _scope_roots_with_reach(scopes, workspace: str) -> tuple:
    """``((root, recursive), ...)`` for every `path:` grant, resolved like `_scope_parts`."""
    out = []
    ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/")
    for scope in scopes:
        if not isinstance(scope, str) or not scope.startswith("path:"):
            continue
        if scope.startswith("path:" + UNPRICEABLE_PREFIX):
            continue                              # a once-only trial lift, never a root
        raw = os.path.expanduser(scope[len("path:"):]).replace("\\", "/")
        recursive = raw.endswith(RECURSIVE_SUFFIX)
        if recursive:
            raw = raw[: -len(RECURSIVE_SUFFIX)]
        if not raw:
            continue
        if not raw.startswith("/"):
            raw = os.path.join(ws, raw)
        root = os.path.realpath(os.path.normpath(raw)).replace("\\", "/").rstrip("/")
        if root:
            out.append((root, recursive))
    return tuple(out)


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
        if scope.startswith("path:" + UNPRICEABLE_PREFIX):
            continue                              # a once-only trial lift, never a root
        if scope.startswith("path:"):
            raw = os.path.expanduser(scope[len("path:"):]).replace("\\", "/")
            if raw.endswith(RECURSIVE_SUFFIX):     # reach is `_scope_roots_with_reach`'s job
                raw = raw[: -len(RECURSIVE_SUFFIX)]
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
    """Whether ``path`` is a granted root, or descends from a root granted RECURSIVELY.

    Until 2026-09-08 every `path:` grant was matched as a prefix here while the daemon
    recorded it as exact — so the daemon answered a member's re-ask for a child path with a
    fresh grant while this gate had been admitting that child all along. Two producers of
    one fact. Now both read the same rule: exact by default, subtree only when the entry is
    spelled `path:<root>/**`, which only an operator's explicit act produces."""
    candidate = os.path.realpath(os.path.normpath(path)).replace("\\", "/").rstrip("/")
    return any(candidate == root or (recursive and candidate.startswith(root + "/"))
               for root, recursive in _scope_roots_with_reach(scopes, workspace))


_PLAIN_REPO_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def _qualified_repo(s) -> Optional[tuple]:
    """``(owner, name)`` lower-cased when ``s`` is exactly `owner/name` of plain segments (neither `.` nor `..`),
    else None. A `path:` entry is never a repository."""
    if not isinstance(s, str) or s.startswith("path:") or s.count("/") != 1:
        return None
    owner, name = s.split("/")
    for seg in (owner, name):
        if seg in (".", "..") or not _PLAIN_REPO_SEGMENT.match(seg):
            return None
    return (owner.lower(), name.lower())


def _qualified_repo_granted(full: str, scopes) -> bool:
    """#1392 v3: whether remote repository ``full`` (`owner/name`) is granted by a QUALIFIED repository entry.

    The grant boundary spells a repository grant `repo:<owner>/<name>`; `_parse_scope_entries` strips the `repo:`
    prefix, so the entry reaches here as `owner/name`. It is compared by owner AND name, case-insensitively,
    against the call's own full identity.

    Nothing local stands in for a remote repository. v1 joined the owner-stripped name onto the workspace (it
    admitted `unrelated-owner/hestia`). v2 read the checkout's `origin` from `.git/config` when each call was
    judged; that file is member-writable under the very recursive grant that triggered the binding, so a checkout
    created or re-pointed after the grant minted remote authority (Nova's HOLD on PR #1393, the #1281 class).
    Remote identity now comes only from an operator/peer-governed grant: a recursive `path:` grant reaches local
    files, never a remote repository. The legacy bare-name grant keeps its owner-agnostic meaning at the call
    site (a compatibility exception, flagged for its own review)."""
    want = _qualified_repo(full)
    return bool(want) and any(_qualified_repo(s) == want for s in scopes)


def _exact_grant_hint(path: str, scopes, workspace: str) -> str:
    """The sentence a scope deny owes when the refused path lies BENEATH an exact grant.

    The day exact became the default (2026-09-08) three seats hit the same wall in one
    afternoon: `<ws>` granted exact, `<ws>/<repo>` refused as "'<repo>' is not granted
    (granted: path:<ws>+...)". Every word of that is true and none of it names the cause —
    the grant the member can SEE in the list is the one that does not reach, because it is
    exact. The member is left to infer a rule it was never shown, and the operator to
    re-derive it per seat. A deny that hides its trigger sends the agent debugging blind
    (Codex live, 2026-07-23); this is the same defect one level up: a deny that hides the
    SHAPE of the grant it tested against.

    Returns "" when no exact root contains the path (nothing to explain — the path is
    simply outside every grant), else one sentence naming the deepest such root and the
    spelling that would reach. Naming the operator's act is deliberate: the member cannot
    widen its own grant, and should not go looking for a way to."""
    cand = os.path.realpath(os.path.normpath(path)).replace("\\", "/").rstrip("/")
    exact_roots = sorted((root for root, recursive in _scope_roots_with_reach(scopes, workspace)
                          if not recursive and cand.startswith(root + "/")), key=len, reverse=True)
    if not exact_roots:
        return ""
    root = exact_roots[0]
    return (f"; note: your grant path:{root} is EXACT — it reaches that path itself and nothing "
            f"beneath it. A recursive grant (path:{root}{RECURSIVE_SUFFIX}) would reach this; "
            f"only an operator can make it so")


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
                    # Read-only roots, parsed inside the same guard: bad data here reads
                    # as no read-only roots, never as a traceback and never as reach.
                    read_raw = got.get("in_scope_read")
                    try:
                        read_parsed = (_parse_scope_entries(read_raw)
                                       if isinstance(read_raw, list) else ())
                    except Exception:
                        read_parsed = ()
                    return AgentPolicy(
                        member_id=profile.member_id, scope=parsed, source="vault",
                        generation=gen, expires_at=exp,
                        read_scope=tuple(read_parsed or ()),
                        mode_scope=_parse_mode_scope(got.get("in_scope_modes")),
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


def _default_forbidden() -> tuple:
    """The egress list a caller gets when it passes none: the built-ins PLUS the operator's extras.

    #1191 shipped `None -> FORBIDDEN_DEFAULT` (the short list), while the shims' direct-naming scan includes
    `HESTIA_FORBIDDEN_EXTRA` (gemini's `FORBIDDEN = DEFAULT + extras`). So with `.kaggle` in the extras,
    `cat ~/.kaggle/kaggle.json` was denied by name but a symlink to it passed the adapters (kimi-code's #1191
    review, probed: main DENY, branch ALLOW). The old realpath refusal needed no list at all; its replacement
    must not be the weaker one. Every HarnessProfile reads extras from this same variable."""
    extra = os.environ.get("HESTIA_FORBIDDEN_EXTRA", "")
    return FORBIDDEN_DEFAULT + tuple(t.strip() for t in extra.split(",") if t.strip())


def command_in_scope(cmd: str, scopes, workspace: str, cwd: Optional[str] = None, forbidden=None,
                     home_markers=None):
    """Returns (ok, offending_token) — the two-field contract every seat's shim reads.

    `command_scope_reach` is the same check carrying the third fact the deny text needs:
    the resolved path that was refused. This wrapper exists so the shims (kimi, gemini,
    the parity test) keep their contract while `evaluate` reads the richer one. `forbidden`
    passes through; None means `_default_forbidden()` (built-ins + the operator's extras).
    `home_markers` passes through too; a caller that passes none gets no home allowance for
    shell paths OUTSIDE the workspace (the narrow direction)."""
    ok, offending, _resolved = command_scope_reach(cmd, scopes, workspace, cwd, forbidden=forbidden,
                                                   home_markers=home_markers)
    return ok, offending


def _symlink_target_forbidden(resolved: str, forbidden) -> Optional[str]:
    """The resolved target when a SYMLINK on the way leads to a forbidden path, else None.

    Runs on EVERY absolute workspace token, ahead of the grant check (kimi-code's #1191 review, point 2): a
    link whose target stays INSIDE a grant never reached the refusal branch, so under `path:<ws>/**`
    `cat <ws>/granted/env-link` -> `<ws>/other/.env` passed while naming that file directly is denied by
    gate 1a's text scan. The same order covers NAMED repo grants, whose tokens are judged lexically and
    never reached the realpath logic at all (#953's disclosed residual). Behaviour change vs main, safe
    direction: an in-grant link whose target merely CONTAINS a forbidden substring (`.env.example`,
    `docs/credentials.md`) now denies, the same as naming it directly does."""
    lexical = os.path.normpath(resolved).replace("\\", "/")
    target = os.path.realpath(lexical).replace("\\", "/")
    if target == lexical:
        return None
    low = target.lower()
    return target if any(f in low for f in forbidden) else None


def _symlinked_reach_verdict(resolved: str, seg: str, repo_scopes, scopes, workspace: str) -> Optional[tuple]:
    """A reach a SYMLINK carries out of its grant is judged by its target, as if named directly (#953).

    `_within_path_grant` compares realpaths, so `<ws>/proj/venv/bin/python` under `path:<ws>/**` was
    refused: its realpath is the system interpreter. That is a true positive of the realpath rule with an
    unwanted consequence, three times now (HUB 09-05, CBP 09-17, thor 09-30): the caller could have named
    the target itself and been allowed, and the deny named `proj`, which IS granted, so each seat asked an
    operator for a grant it already held.

    Called only after `_symlink_target_forbidden` has cleared the target (egress is judged first, for every
    token). Returns None when the reach is in scope, else `(offending, refused_path)`:
      - no symlink on the way (realpath == the lexical path): the lexical refusal stands, unchanged;
      - target inside the workspace: judged by the TARGET's repo, and a refusal names that repo
        (the misattribution half of #953);
      - target outside the workspace: allowed — the venv interpreter case this function exists for.
        AMENDED 2026-10-05: the old reason ("a command naming it directly is not MRH-scoped") is
        no longer true; pass 3 now judges a direct naming. The allowance is KEPT anyway, for the
        reach a pre-existing link carries out of a granted tree (venvs, toolchains): refusing it
        would re-open #953 on every seat holding a `path:<ws>/**` grant. What keeps it from being
        the way around pass 3 is that MAKING such a link names its target (`ln -s /outside …`),
        and that naming is judged. Residual, stated: a link made by code pass 3 cannot read
        (an interpreter one-liner) carries reach out. Read shares the lexical half of this.
    Read keeps its own rule (`path_in_scope` refuses outside the workspace either way)."""
    lexical = os.path.normpath(resolved).replace("\\", "/")
    target = os.path.realpath(lexical).replace("\\", "/")
    if target == lexical:
        return (seg or "<workspace root>"), resolved
    wsr = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/")
    if target == wsr or target.startswith(wsr + "/"):
        tseg = target[len(wsr):].lstrip("/").split("/", 1)[0]
        if tseg in repo_scopes or _within_path_grant(target, scopes, workspace):
            return None
        return (tseg or "<workspace root>"), target
    return None


#: POSIX stream and device sinks: always reachable, never a scope question. EXACT paths plus the
#: `/dev/fd/<n>` family — deliberately not `/dev/**`: a raw disk (`/dev/sda`) or bash's
#: `/dev/tcp/<host>/<port>` network pseudo-device is reach, and stays judged. Measured
#: 2026-10-05 over 31,397 shell commands: `/dev/null` alone appears in 5,408 of them, so a
#: shell scope check without this allowance would refuse a quarter of every seat's work for
#: plumbing that touches no file. Law, like TEMP_ROOTS, not operator config: these names are
#: fixed by POSIX and carry no data a grant could be about.
DEVICE_SINKS = frozenset((
    "/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty",
    "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full",
))
DEVICE_FD_ROOT = "/dev/fd"


def _device_sink(path: str) -> bool:
    """Lexical, on purpose: `/dev/stderr` realpaths to `/proc/self/fd/2` -> `/dev/pts/N`, and
    judging the target would refuse the sink this allowance exists for."""
    p = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
    return p in DEVICE_SINKS or p == DEVICE_FD_ROOT or p.startswith(DEVICE_FD_ROOT + "/")


#: Heredoc bodies fed to these heads are CODE and are judged; a body fed to anything else
#: (`cat > f <<EOF`, a commit message, a JSON payload) is DATA and is not a reach. Measured
#: 2026-10-05: ~10% of would-be denials sat only inside heredoc bodies — prose and fixtures.
#: A SHELL body is judged as shell; any other interpreter's body is judged by its quoted
#: absolute-path string literals only (`open('/etc/x')`) — shell-tokenising Python or JS
#: manufactures "paths" out of regexes and comment openers (measured on the same replay).
_HEREDOC_SHELL = re.compile(r"^(?:ba|z|da|k|fi)?sh$")
_HEREDOC_INTERPRETER = re.compile(
    r"^(?:(?:ba|z|da|k|fi)?sh|python[0-9.]*|pypy[0-9.]*|node|deno|bun|ruby|perl|php|lua|Rscript"
    r"|osascript|tclsh|awk|gawk)$")
_CODE_PATH_LITERAL = re.compile(r"""(?<![\w])(['"])((?:/|~/|\$HOME/|\$\{HOME\}/)[^'"\s]*)\1""")


def _code_path_literals(text: str) -> list:
    """Quoted absolute-path literals in interpreter code, minus root-only separators (`'/'`,
    `'//'`). A directory literal with a trailing slash (`'/x/'`) is kept (Codex review 17029f)."""
    return [lit for _q, lit in _CODE_PATH_LITERAL.findall(text) if lit.strip("/")]
#: (A code literal must name something below the root: `'/'` / `'//'` in code are separators —
#: `p.split('/')`. Interpreter CODE is outside the shell grammar this parser models; its quoted
#: path literals are judged, and code that computes a path is a declared residual.)
#: Words that run the NEXT word as the command (`sudo bash <<EOF` feeds bash).
_HEREDOC_WRAPPERS = frozenset(("sudo", "env", "nice", "nohup", "timeout", "exec", "command",
                               "time", "doas", "stdbuf", "ionice", "xargs", "builtin"))
#: groups: 1 `-` (tab-strip), 2 a backslash (`<<\EOF`), 3 a quote, 4 the delimiter word. A quoted
#: or backslashed delimiter makes the body LITERAL; an unquoted one makes it undergo expansion.
_HEREDOC_OP = re.compile(r"""(?<!<)<<(?!<)(-?)\s*(\\?)(['"]?)([A-Za-z_][A-Za-z0-9_.-]*)\3""")


class _Unmodelled(Exception):
    """The parser met shell it does not model (an unbalanced quote or substitution, an unknown
    heredoc form). The caller treats this as UNENUMERATED — a scope request for the act, never a
    skip (Codex re-review of #1232; dp, 2026-10-10)."""


class _Unenumerated(_Unmodelled):
    """An expansion whose VALUE would be judged as a path (dp, 2026-10-10: nothing an expansion
    produces is modelled). Collected, not raised past the scan: the literal candidates of the same
    command are still judged first, so a concrete refusal names its path."""


def _balanced_end(text: str, open_idx: int) -> int:
    """Index of the `)` closing the `(` at `open_idx`; quotes and nested substitutions are
    skipped over. Raises `_Unmodelled` when it never closes."""
    depth, i, n = 0, open_idx, len(text)
    pending_docs = []                      # heredoc delimiters opened on the current line
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n" and pending_docs:
            # A heredoc body inside the substitution is text up to its delimiter line — its
            # quotes and parentheses are not shell syntax (`$(cat <<'EOF' … it's … EOF)`).
            i += 1
            for dash, word in pending_docs:
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:n if j < 0 else j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if dash else line) == word:
                        break
            pending_docs = []
            continue
        if text.startswith("<<", i) and not text.startswith("<<<", i):
            m = _HEREDOC_OP.match(text, i)
            if m:
                pending_docs.append((m.group(1), m.group(4)))
                i = m.end()
                continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise _Unmodelled("unbalanced quote inside a substitution")
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise _Unmodelled("unbalanced quote inside a substitution")
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise _Unmodelled("an unclosed $( substitution")


def _substitution_bodies(text: str, quotes: bool = True) -> list:
    """Every `$( … )` and backtick body in `text`, outermost first, with line boundaries intact
    (a body may span lines); nested ones are found when the body is itself tokenised. With
    `quotes`, text inside single quotes is literal and skipped; in a heredoc body (`quotes=False`)
    a quote is an ordinary character and expansions inside it still run. Raises `_Unmodelled` on
    an unclosed one."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'" and quotes:
            j = text.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if text.startswith("$((", i):
            # Arithmetic is not a command — but a substitution INSIDE it runs (Codex review
            # 17029d: `$(( $(cat /x) ))`). Its own bodies are collected, never dropped.
            k = _balanced_end(text, i + 1)
            out.extend(_substitution_bodies(text[i + 3:k - 1], quotes))
            i = k + 1
            continue
        if text.startswith("$(", i):
            k = _balanced_end(text, i + 1)
            out.append(text[i + 2:k])
            i = k + 1
            continue
        if c == "`":
            j = text.find("`", i + 1)
            if j < 0:
                raise _Unmodelled("an unclosed backtick substitution")
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return [b for b in out if b.strip()]


def _quoted_at(line: str, k: int) -> bool:
    """Whether position `k` of `line` sits inside single or double quotes (backslash-aware)."""
    q, i = None, 0
    while i < k:
        c = line[i]
        if c == "\\" and q != "'":
            i += 2
            continue
        if q is None and c in "'\"":
            q = c
        elif q == c:
            q = None
        i += 1
    return q is not None


def _heredoc_head(before: str) -> str:
    """The command word that consumes a heredoc opened at the end of `before`.

    FAIL CLOSED toward code (kimi's review of #1232, F2 A04/A06): `sudo -u root bash <<EOF` used to
    name `root` and `chroot /x bash <<EOF` named `chroot`, so a shell body was stripped as data.
    An interpreter ANYWHERE among the consumer's words now decides it: the body is that
    interpreter's (over-judging a remote or container shell is the narrow direction)."""
    seg = re.split(r"\|\||&&|[|;&(]|\$\(|`", before)[-1]
    try:
        words = shlex.split(seg, posix=True)
    except ValueError:
        words = seg.split()
    for w in words:
        if _HEREDOC_INTERPRETER.match(os.path.basename(w)):
            return os.path.basename(w)
    for w in words:
        if "=" in w and not w.startswith(("-", "/", ".")) and w.split("=", 1)[0].isidentifier():
            continue                       # an env assignment prefix
        base = os.path.basename(w)
        if base in _HEREDOC_WRAPPERS or w.startswith("-") or w.isdigit():
            continue
        return base
    return ""


def _strip_data_heredocs(cmd: str) -> str:
    """The command with every heredoc body handled by what consumes it: a SHELL body stays in
    place and is judged as shell; another interpreter's body is replaced by its quoted
    absolute-path literals (one per line, quoted again so they stay one word); a DATA body is
    removed. See `_HEREDOC_INTERPRETER`.

    EXPANSION IS NOT DATA (Codex review of #1232, P1-2). With an UNQUOTED delimiter the shell
    expands the body before the consumer sees it: `cat <<EOF\\n$(cat /x)\\nEOF` runs `cat /x`.
    So for an unquoted delimiter every `$( … )` and backtick body (including those nested in
    `${ … }`) is kept as an executed command, whatever the consumer. Only a QUOTED delimiter
    (`<<'EOF'`, `<<"EOF"`, `<<\\EOF`) makes the body literal data."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        # A `<<` inside quotes is text, not an operator — and must not be mistaken for one, or the
        # following lines would be swallowed as a "body" and never judged.
        ops = [m for m in _HEREDOC_OP.finditer(line) if not _quoted_at(line, m.start())]
        # Every other unquoted `<<` that is not a here-string (`<<<`) and not arithmetic
        # (`$(( 1<<2 ))`, `(( … ))`) is a heredoc form we do not parse: UNMODELLED (Codex re-review
        # of #1232: never skip what the parser cannot read).
        for k in [m.start() for m in re.finditer(r"(?<!<)<<(?!<)", line)]:
            if any(m.start() == k for m in ops) or _quoted_at(line, k):
                continue
            before = line[:k]
            if before.count("((") > before.count("))"):
                continue
            raise _Unmodelled("a heredoc form the parser does not model")
        for m in ops:
            dash, word = m.group(1), m.group(4)
            literal = bool(m.group(2) or m.group(3))
            head = _heredoc_head(line[:m.start()])
            shell = bool(_HEREDOC_SHELL.match(head))
            code = not shell and bool(_HEREDOC_INTERPRETER.match(head))
            body_lines = []
            while i < len(lines):
                body = lines[i]
                i += 1
                if (body.lstrip("\t") if dash else body) == word:
                    break
                body_lines.append(body)
            if shell:
                out.extend(body_lines)
                out.append(word)
                continue
            literals = []
            if code:
                for body in body_lines:
                    literals.extend(_code_path_literals(body))
            executed = []
            if not literal:
                # The WHOLE body, line boundaries intact, `\`-newline continuations joined: the
                # shell expands it as one text, so a `$(` opened on one line and closed on a
                # later one is one substitution (Codex re-review of #1232, P1-2).
                whole = re.sub(r"\\\n", "", "\n".join(body_lines))
                executed = _substitution_bodies(whole, quotes=False)
            out.extend(shlex.quote(lit) for lit in literals)
            for e in executed:
                out.append(";")
                out.append(e)
            out.append(word)
    return "\n".join(out)


#: A command that gives HOME a value of its own (assignment, export, read, a loop variable).
_HOME_REASSIGNED = re.compile(
    r"""(?:^|[\s;&|(`])(?:(?:export|declare|local|typeset|readonly)\s+(?:-\w+\s+)*)?HOME\+?="""
    r"""|\b(?:read|unset|export)\b[^\n;&|]*\bHOME\b|\bfor\s+HOME\b""")
#: The shell's own home spellings at a word start: `~`, `~/x`, `$HOME/x`, `${HOME}/x`.
_HOME_WORD = re.compile(r"""(?:^|(?<=[\s=;|&(<>'"`:]))(?:~|\$HOME|\$\{HOME\})(?=/|$|[\s;|&)<>'"`:])""",
                        re.MULTILINE)


def _expand_home_words(cmd: str) -> str:
    """Expand the home spellings the shell would expand, so `~/<ws>/x` meets the workspace
    rule and `~/.x` meets the outside rule. Expanded inside single quotes too, where the shell
    would not: over-judging a quoted mention is the narrow direction."""
    if "~" not in cmd and "HOME" not in cmd:
        return cmd
    # Exactly the shell's own source for `~` and `$HOME`: the HOME variable, else the account's
    # passwd entry (what bash falls back to). No path literal (tools/no_path_literals_test.py).
    home = os.getenv("HOME")
    # Only an UNSET HOME falls back to the passwd entry; a set-but-EMPTY HOME is what the shell
    # expands `~` to (Codex re-review of #1232: `if not home` conflated the two).
    if home is None:
        try:
            import pwd
            home = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            return cmd
    home = home.replace("\\", "/").rstrip("/")
    return _HOME_WORD.sub(lambda _m: home, cmd)


_SHELL_PUNCT = frozenset(";|&()<>")
#: Sentinels in a tokenised word: a `$` / backtick the shell will NOT expand (quoted or escaped),
#: and an UNQUOTED brace expansion (`{a,b}`, `{1..3}`) about to open.
_LIT_DOLLAR, _LIT_TICK, _BRACE = "\x00", "\x02", "\x03"
#: Marks a `$NAME` / `${…}` reference, or a `$(…)` / backtick substitution, written INSIDE double
#: quotes (no field splitting, no globbing at that use) — evidence the literal rule needs before a
#: whitespace value may bind, and that a data position needs before an expansion is one argument.
_DQ_REF = "\x04"
#: `$'…'` (ANSI-C) and `$"…"` (locale) quoting rewrite their content; never modelled. The word
#: carries this unbound parameter reference, so wherever it is judged as a path it is
#: unenumerated (`ANSI-C` is not an identifier: no assignment can ever bind it).
_ANSI_C_MARK = "${ANSI-C}"
#: Every byte the lexer uses as an IN-BAND marker (`_LIT_DOLLAR`, `\x01` in `_path_shaped`,
#: `_LIT_TICK`, `_BRACE`, `_DQ_REF`) plus one spare. A command that already contains one could
#: forge quote / literal evidence (Codex 20554: `cat \x04$S` read as a quoted use), so such a
#: command is UNENUMERATED before any marker is inserted. (`_ANSI_C_MARK` is spelled in shell
#: syntax; forging it only makes a word unenumerated, the strict direction.)
_MARKER_BYTES = re.compile("[\x00-\x05]")
_BRACE_EXPANSION = re.compile(r"""\{[^\s{}'"]*(?:,|\.\.)[^\s{}'"]*\}""")


def _tokenize(text: str) -> list:
    """`(kind, value, unquoted_glob)` per token, kind "word" | "op" | "sep".

    A real (if small) shell lexer, because the scope check is now DEFAULT-JUDGE (Codex re-review
    of #1232): quoting is tracked PER CHARACTER, so `"/"*` keeps an expanding star
    (`unquoted_glob`); a `$`/backtick inside single quotes or escaped is marked literal; `$( … )`
    and backticks stay inside their word (bodies are judged separately); `#` at a word start begins
    a comment (not executed); a newline or `;` / `&&` / `||` / `|` / `&` / `(` / `)` separates
    commands; `\\`-newline continues. Anything unbalanced raises `_Unmodelled`."""
    if _MARKER_BYTES.search(text):
        raise _Unmodelled("a control character the gate's lexer reserves as an internal marker")
    out, buf, in_word, uglob = [], [], False, False
    i, n = 0, len(text)

    def flush():
        nonlocal buf, in_word, uglob
        if in_word:
            out.append(("word", "".join(buf), uglob))
        buf, in_word, uglob = [], False, False

    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                ch = text[i + 1]
                buf.append(_LIT_DOLLAR if ch == "$" else _LIT_TICK if ch == "`" else ch)
            in_word = True
            i += 2
            continue
        if c == "#" and not in_word:
            j = text.find("\n", i)
            i = n if j < 0 else j               # a comment runs to the end of the line
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise _Unmodelled("an unbalanced single quote")
            buf.append(text[i + 1:j].replace("$", _LIT_DOLLAR).replace("`", _LIT_TICK))
            in_word = True
            i = j + 1
            continue
        if c == '"':
            j, seg = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n and text[j + 1] in '"\\$`\n':
                    nx = text[j + 1]
                    if nx != "\n":
                        seg.append(_LIT_DOLLAR if nx == "$" else _LIT_TICK if nx == "`" else nx)
                    j += 2
                    continue
                if text.startswith("$(", j):
                    k = _balanced_end(text, j + 1)
                    seg.append(_DQ_REF + text[j:k + 1])   # a quoted substitution
                    j = k + 1
                    continue
                if text[j] == "`":
                    k = text.find("`", j + 1)
                    if k < 0:
                        raise _Unmodelled("an unclosed backtick")
                    seg.append(_DQ_REF + text[j:k + 1])
                    j = k + 1
                    continue
                if text[j] == "$" and j + 1 < n and (text[j + 1] == "{" or text[j + 1] == "_"
                                                     or text[j + 1].isalpha()):
                    seg.append(_DQ_REF)               # a quoted variable reference
                seg.append(text[j])
                j += 1
            if j >= n:
                raise _Unmodelled("an unbalanced double quote")
            buf.append("".join(seg))
            in_word = True
            i = j + 1
            continue
        if text.startswith("$'", i) or text.startswith('$"', i):
            # ANSI-C / locale quoting (Codex 20536): its content is rewritten by the shell, so the
            # word is unenumerated wherever it is judged as a path (`_ANSI_C_MARK`).
            q = text[i + 1]
            j = i + 2
            while j < n and text[j] != q:
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise _Unmodelled("an unbalanced $-quote")
            buf.append(_ANSI_C_MARK + text[i + 2:j].replace("$", _LIT_DOLLAR).replace("`", _LIT_TICK))
            in_word = True
            i = j + 1
            continue
        if text.startswith("$(", i):
            k = _balanced_end(text, i + 1)
            buf.append(text[i:k + 1])
            in_word = True
            i = k + 1
            continue
        if text.startswith("${", i):
            k = text.find("}", i + 2)
            if k < 0:
                raise _Unmodelled("an unclosed ${")
            buf.append(text[i:k + 1])
            in_word = True
            i = k + 1
            continue
        if c == "`":
            j = text.find("`", i + 1)
            if j < 0:
                raise _Unmodelled("an unclosed backtick")
            buf.append(text[i:j + 1])
            in_word = True
            i = j + 1
            continue
        if c.isspace():
            flush()
            if c == "\n":
                out.append(("sep", ";", False))
            i += 1
            continue
        if c in _SHELL_PUNCT:
            if c in "<>" and in_word and buf and "".join(buf).isdigit():
                buf, in_word = [], False         # `2>`: an fd number, not a word
            flush()
            j = i
            while j < n and text[j] in _SHELL_PUNCT and j - i < 3:
                if text[j] in "()" and j > i:
                    break
                j += 1
            op = text[i:j]
            out.append(("op" if ("<" in op or ">" in op) else "sep", op, False))
            i = j
            continue
        if c in "*?[":
            uglob = True
        if c == "{" and _BRACE_EXPANSION.match(text, i):
            buf.append(_BRACE)                   # brace expansion: never modelled (dp, 2026-10-10)
        buf.append(c)
        in_word = True
        i += 1
    flush()
    return out


def _shell_words(cmd: str, depth: int = 0, origin=None) -> list:
    """Every token of a command, with each `$( … )` / backtick body lifted out (balanced, so
    nesting and multiline bodies hold) and tokenised as a command of its own after a separator —
    quoting a substitution cannot hide its reach."""
    if depth > 6:
        raise _Unmodelled("substitutions nested deeper than the parser follows")
    toks = _tokenize(cmd)
    extra = []
    for i, (kind, w, _g) in enumerate(toks):
        if kind == "word" and ("$(" in w or "`" in w):
            # `quotes=False`: `_tokenize` already resolved quoting (a `$` or backtick that single
            # quotes made literal is a sentinel now), so an apostrophe left in a dequoted word is an
            # ordinary character. Re-reading it as a quote hid `"'$(cat /x)'"` (Codex review 17054,
            # P1-quote-context).
            for body in _substitution_bodies(w.replace(_LIT_TICK, "").replace(_DQ_REF, ""),
                                             quotes=False):
                extra.append(("sep", ";", False))
                # The body runs when the OUTER word holding it is expanded: its position in the
                # outer command (`origin`, the outermost word's token index, carried through
                # nesting) is what a binding must precede (Codex 20536, P1-1).
                extra.append(("mark", i if origin is None else origin, False))
                # A heredoc INSIDE a substitution (`-m "$(cat <<'EOF' … EOF)"`) is handled like
                # any other: the outer pass saw its `<<` inside quotes and left it as text.
                extra.extend(_shell_words(_strip_data_heredocs(body), depth + 1,
                                          i if origin is None else origin))
    return toks + extra


#: DEFAULT-JUDGE (Codex re-review of #1232; dp: "the shell is a grammar, and skip-lists keep
#: leaking"). Every word that could be a path — it contains `/`, starts with `~` or `.`, or
#: carries an UNQUOTED glob character — is judged. A word is skipped ONLY under a precise
#: exception keyed on (command, argument position or the option that consumes it). Quoting is
#: never an exemption by itself (`grep -r x "/"` is judged).
#:
#: Per-command specs: `strings` = every positional is a string (`tr` sets); `strings_noglob` =
#: positionals are strings unless they carry an unquoted glob (`echo /*` expands, `echo /` does
#: not); `pattern_first` = the first positional is a pattern/program unless an option supplied
#: one; option sets name the options whose VALUE is a delimiter / pattern / plain string (skipped)
#: or a value we only need to step over (judged as an ordinary word, but it is not positional).
_GREP_SPEC = {"pattern_first": True, "pattern_opts": {"-e", "--regexp"}, "file_opts": {"-f", "--file"},
              "value_opts": {"-A", "-B", "-C", "-m", "--max-count", "--include", "--exclude",
                             "--exclude-dir", "--context", "--after-context", "--before-context",
                             "-d", "--directories", "-D", "--devices", "--label"}}
#: `git grep` (after the subcommand): grep's grammar. Its `-C` is context, not git's directory.
_GIT_GREP_SPEC = dict(_GREP_SPEC)
#: Heads whose PATTERN operands the in-workspace passes of `command_scope_reach` do not read as
#: reaches (#1241 recut, SAGE #368): the tool matches the text against what it reads and never
#: opens it. Recorded by value in `_Found.patterns`, LITERAL words only (an expansion stays live).
_PATTERN_HEADS = frozenset(("grep", "egrep", "fgrep", "rg", "git-grep"))
_CMD_SPECS = {
    "tr": {"positional": "strings"},
    "echo": {"positional": "strings_noglob"},
    "printf": {"positional": "strings_noglob"},
    "grep": _GREP_SPEC, "egrep": _GREP_SPEC, "fgrep": _GREP_SPEC, "zgrep": _GREP_SPEC,
    "rg": {"pattern_first": True, "pattern_opts": {"-e", "--regexp"}, "file_opts": {"-f", "--file"},
           "value_opts": {"-g", "--glob", "-t", "--type", "-T", "--type-not", "-m", "--max-count",
                          "-A", "-B", "-C", "-j", "--threads", "-M", "--max-columns",
                          "--max-depth", "-E", "--encoding", "--sort", "--sortr"}},
    "sed": {"pattern_first": True, "pattern_opts": {"-e", "--expression"}, "file_opts": {"-f", "--file"},
            "value_opts": {"-l", "--line-length"}},
    "awk": {"pattern_first": True, "file_opts": {"-f", "--file"}, "delim_opts": {"-F", "--field-separator"},
            "string_opts": {"-v", "--assign"}},
    "cut": {"delim_opts": {"-d", "--delimiter", "--output-delimiter"},
            "value_opts": {"-f", "-c", "-b", "--fields", "--characters", "--bytes"}},
    "sort": {"delim_opts": {"-t", "--field-separator"}, "value_opts": {"-k", "--key", "-S", "--buffer-size"}},
    "join": {"delim_opts": {"-t"}, "value_opts": {"-1", "-2", "-j", "-o"}},
    "paste": {"delim_opts": {"-d", "--delimiters"}},
    "column": {"delim_opts": {"-s", "--separator", "-o", "--output-separator"}},
    "read": {"delim_opts": {"-d"}, "string_opts": {"-p"}},
    "find": {"pattern_opts": {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename",
                              "-regex", "-iregex", "-lname", "-ilname"},
             "string_opts": {"-printf"}},
    "git": {"string_opts": {"-m", "--message", "--grep", "--author", "--format", "--pretty", "-S", "-G"}},
}
_CMD_SPECS["gawk"] = _CMD_SPECS["mawk"] = _CMD_SPECS["awk"]
#: Heads whose `-c` value is shell code (they also disqualify the literal rule).
_CODE_OPT_HEADS = frozenset(("su", "runuser", "script", "flock"))
#: Arguments that are SHELL CODE (judged as a command of their own, found writing the narrowed
#: battery): `eval` and `watch` take code as positionals; `su`/`runuser`/`script`/`flock` take it
#: as `-c`. (`sh -c` anywhere in argv — `find -exec sh -c`, `docker exec c bash -c` — is caught by
#: position in `_outside_candidates`.)
_CMD_SPECS["eval"] = {"positional": "code"}
_CMD_SPECS["watch"] = {"positional": "code", "value_opts": {"-n", "--interval", "-d"}}
for _h in ("su", "runuser"):
    _CMD_SPECS[_h] = {"code_opts": {"-c", "--command"},
                      "value_opts": {"-s", "--shell", "-g", "--group", "-G", "--supp-group"}}
_CMD_SPECS["script"] = {"code_opts": {"-c", "--command"}}
_CMD_SPECS["flock"] = {"code_opts": {"-c", "--command"}, "value_opts": {"-w", "--timeout"}}
#: PROSE OPTIONS (#1287): values that are messages, not paths — a reason, a body, a title. A seat's
#: `--reason "$R"` with prose in R (a `*`, quotes) was made a once-only scope request by the literal
#: rule although nothing in it is a path. Keyed by (command, subcommand words) and NEVER generic: an
#: option's arity is the command's, and often the subcommand's (`grep --text`, `readelf --notes`,
#: `git diff --summary` and `gh pr review -c` take no value, so a generic prose `--text` swallowed
#: the file after it — Codex HOLD 21639). Each entry is checked against the tool's own definition:
#: hestia's clap tree (every `--reason` / `--argument` is a String) and `gh <sub> --help`. A
#: subcommand word must precede the option; anything else stays a path. An UNQUOTED glob in the
#: word itself is still judged (the shell expands it first), as for every other string position.
_PROSE_OPTS = {
    ("hestia",): {"--reason", "--argument"},
    ("gh", "pr", "create"): {"--title", "-t", "--body", "-b"},
    ("gh", "pr", "edit"): {"--title", "-t", "--body", "-b"},
    ("gh", "issue", "create"): {"--title", "-t", "--body", "-b"},
    ("gh", "issue", "edit"): {"--title", "-t", "--body", "-b"},
    ("gh", "pr", "comment"): {"--body", "-b"},
    ("gh", "issue", "comment"): {"--body", "-b"},
    ("gh", "pr", "review"): {"--body", "-b"},
    ("gh", "pr", "close"): {"--comment", "-c"},
    ("gh", "issue", "close"): {"--comment", "-c"},
    ("gh", "pr", "merge"): {"--subject", "-t", "--body", "-b"},
    ("gh", "release", "create"): {"--title", "-t", "--notes", "-n"},
    ("gh", "release", "edit"): {"--title", "-t", "--notes", "-n"},
}


def _string_opts(head, spec, subs=()) -> set:
    """The options whose value is a plain string for `head` after the positional words `subs`:
    its spec's, plus the prose options `_PROSE_OPTS` names for that command and subcommand."""
    out = set(spec.get("string_opts", set()))
    for key, opts in _PROSE_OPTS.items():
        if key[0] == head and tuple(subs[:len(key) - 1]) == key[1:]:
            out |= opts
    return out


#: Commands whose argv is built from STDIN: what they reach is another command's output.
_STDIN_ARGV = frozenset(("xargs", "parallel"))
#: Commands that resolve their relative arguments against a directory option (`-C D`).
_DIR_OPT_HEADS = frozenset(("git", "make", "gmake", "tar"))
#: How many composed directory bases relative paths are judged against before the gate stops
#: following directory changes (and the reach is unenumerated).
_MAX_DIR_BASES = 16
#: Assignments whose value is not a path being reached: a field separator, or a search path list
#: that only influences later lookups.
_NONPATH_ASSIGNMENTS = frozenset(("IFS", "PS1", "PS2", "PS4", "PATH", "MANPATH", "INFOPATH",
                                  "PYTHONPATH", "LD_LIBRARY_PATH", "CLASSPATH", "NODE_PATH",
                                  "PKG_CONFIG_PATH", "GOPATH", "CDPATH"))
#: Interpreters whose `-c` / `-e` value is CODE: judged by its quoted absolute-path literals.
_CODE_ARG_HEADS = re.compile(r"^(?:python[0-9.]*|pypy[0-9.]*|node|deno|bun|ruby|perl|php)$")
_SHELL_KEYWORDS = frozenset(("if", "then", "else", "elif", "fi", "do", "done", "while", "until",
                             "for", "case", "esac", "in", "function", "!", "{", "}", "time"))
_SHELL_SEPARATORS = frozenset(("|", "||", "&&", ";", "&", "(", ")", "|&", ";;", ";&", "{", "}"))


#: An attached short option carrying a path: `-I/usr/include`, `-C/elsewhere`, `-o/out`.
_ATTACHED_OPT = re.compile(r"^-[A-Za-z](/.*)$")
_GLOB_CHARS = re.compile(r"[*?\[]")


#: How many DISTINCT path spellings one command may carry into the filesystem-probing passes
#: (each pass separately). Past it the classification is incomplete and the command is REFUSED
#: (`_INCOMPLETE`), not allowed: split the command. Bounds probing inside the engine's hook clamp.
SCOPE_JUDGE_BUDGET = 128
_INCOMPLETE = "<incomplete: more distinct paths than the gate judges in one command — split it>"
_UNMODELLED_PREFIX = "<incomplete: the scope parser does not model "

#: #1274's sentinels (daemon `gate_escalation::UNPRICEABLE_PREFIX`, mechanism
#: `UNPRICEABLE_PREFIX`). A scope refusal whose reach the gate cannot ENUMERATE carries one of these
#: as its `target` instead of a path. The gate then opens a scope request for the ACT, and only a
#: one-time approval of that exact act (its complete-act digest) lifts it: there is no path a
#: session or standing grant could name, and the daemon refuses to make one. In a trial scope (the
#: orchestrator re-judging an act it holds an approval for) `path:<sentinel>` lifts exactly that
#: class for that one evaluation; no snapshot ever carries it.
UNPRICEABLE_PREFIX = "hestia:unpriceable:"
UNENUMERATED_TARGET = UNPRICEABLE_PREFIX + "unenumerated"
OVERFLOW_TARGET = UNPRICEABLE_PREFIX + "overflow"


#: NOTHING AN EXPANSION PRODUCES IS MODELLED (dp's ruling, 2026-10-10: "narrow and land").
#: Patch 01e68a1c modelled substitution OUTPUT with tables keyed on the command NAME ("date
#: prints a number", "head selects lines", "find prints paths under its roots"), and four Codex
#: rounds kept finding the same defect in new members: soundness depends on argv SHAPE, and
#: `date +/x`, `seq -f`, `shuf -e`, `expr`, `wc` / `sha256sum` (operand echo), `grep` / `sort` /
#: `head FILE` and `find -printf` all print a path the model said they could not. Variables were
#: modelled the same way, and a linear scan is not the shell's scoping (`D=/tmp cat $D`,
#: `(D=/x); cat $D`), so they are not modelled either. What remains are expansions whose VALUE
#: cannot contain `/` or be `..`: arithmetic (a number) and the special parameters `$?` `$#` `$$`
#: `$!` (digits) and `$-` (flag letters), replaced by a placeholder of the same class.
_PLACEHOLDER_PARAMS = {"$?": "0", "$#": "0", "$$": "0", "$!": "0", "$-": "x"}

#: The heads of a `${…}` PROVED to be one word inside double quotes: a name with no index or an index
#: holding no `@` (`${A[*]}` joins), a positional number, or `*` `#` `?` `$` `-`, then the closing
#: brace or an operator; `${!}` (the last pid) alone; `${#…}` counts; the joined key and prefix
#: lists `${!A[*]}` / `${!P*}`. This is an ALLOWLIST: `${@…}`, `${A[@]…}` and every other `${!…}`
#: (a name, `${!1}`, `${!#}` — the target decides, and `set -- 'A[@]'` makes `"${!1}"` one argument
#: per element) are unproved. A list of shapes known to split was held three times, each for one
#: more shape (Codex HOLDs 21718, 21790, 21861).
_ONE_WORD_HEAD = re.compile(r"\$\{(?:(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]@]*\])?|[0-9]+|[*#?$-])"
                            r"(?=[}:+=?#%/^,@-])|!\}|#[^}]*\}$|![A-Za-z_][A-Za-z0-9_]*(?:\[\*\]|\*)\}$)")


def _brace_end(value: str, i: int) -> int:
    """Index of the `}` closing the `${` at `i`, counting nested `${` (bash balances them:
    `${R:-${A[@]}}` is ONE expansion, Codex HOLD 21790) and skipping a backslash-escaped char."""
    depth, j, n = 0, i, len(value)
    while j < n:
        if value[j] == "\\":
            j += 2
            continue
        if value.startswith("${", j):
            depth += 1
            j += 2
            continue
        if value[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _per_element(ref: str) -> bool:
    """Whether a QUOTED `${…}` can still expand to more than one argument: any head not in
    `_ONE_WORD_HEAD` (`${A[@]}` and its forms, Codex HOLD 21718; every indirection, whose target
    decides, Codex HOLD 21861), or an unproved form NESTED in an operator word (`"${R:-${A[@]}}"`,
    `"${R+$@}"`, Codex HOLD 21790). Recursive; a nested scalar (`"${R:-$X}"`) or joined array
    (`"${R:-${A[*]}}"`) stays one argument."""
    if not ref.startswith("${"):
        return False
    if not _ONE_WORD_HEAD.match(ref):
        return True
    body = ref[2:-1].replace(_DQ_REF, "")
    try:
        inner = _expansion_spans(body)
    except _Unmodelled:
        return True
    return any(body[a:b] == "$@" or (body[a:b].startswith("${") and _per_element(body[a:b]))
               for a, b in inner)


def _expansion_spans(value: str) -> list:
    """`(start, end)` of every live expansion in a tokenised word: `$(…)`, `$((…))`, backticks,
    `${…}`, `$NAME`, and the special parameters `$?` `$#` `$$` `$!` `$-` `$@` `$*` `$0`…`$9`."""
    spans, i, n = [], 0, len(value)
    while i < n:
        if value.startswith("$((", i):
            k = value.find("))", i + 3)
            if k < 0:
                raise _Unmodelled("an unclosed $(( arithmetic")
            spans.append((i, k + 2))
            i = k + 2
        elif value.startswith("$(", i):
            k = _balanced_end(value, i + 1)
            spans.append((i, k + 1))
            i = k + 1
        elif value.startswith("${", i):
            k = _brace_end(value, i)
            if k < 0:
                raise _Unmodelled("an unclosed ${")
            spans.append((i, k + 1))
            i = k + 1
        elif value[i] == "`":
            k = value.find("`", i + 1)
            if k < 0:
                raise _Unmodelled("an unclosed backtick")
            spans.append((i, k + 1))
            i = k + 1
        elif value[i] == "$" and i + 1 < n:
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*|[?#$!@*0-9-]", value[i + 1:])
            if m:
                spans.append((i, i + 1 + m.end()))
                i += 1 + m.end()
            else:
                i += 1
        else:
            i += 1
    return spans


def _expansion_kind(ref: str) -> str:
    """What the refusal says an unenumerated expansion was."""
    if ref.startswith("$("):
        return "a command substitution"
    if ref.startswith("`"):
        return "a backtick substitution"
    if ref.startswith("${"):
        return f"the parameter expansion {ref[:24]}"
    name = ref[1:]
    if name.isdigit() or name in ("@", "*"):
        return f"the positional parameter {ref}"
    return f"the variable {ref}"


def _word_value(value: str, known=None) -> str:
    """The text a tokenised word is judged as. Raises `_Unenumerated` when an expansion's value
    would decide it (see `_PLACEHOLDER_PARAMS`): never a model, never a guess. `known` holds the
    names `_literal_names` proved to carry ONE literal at this point of the command (dp,
    2026-10-11); only a bare `$N` / `${N}` resolves — any operator (`${N:-x}`) stays unenumerated."""
    if _BRACE in value:
        raise _Unenumerated("brace expansion")
    out, last = [], 0
    for a, b in _expansion_spans(value):
        ref = value[a:b]
        out.append(value[last:a])
        if ref.startswith("$(("):
            out.append("0")                      # arithmetic: a number (its bodies are judged)
        elif ref in _PLACEHOLDER_PARAMS:
            out.append(_PLACEHOLDER_PARAMS[ref])
        elif known and (ref[2:-1] if ref.startswith("${") else ref[1:]) in known \
                and (not known[ref[2:-1] if ref.startswith("${") else ref[1:]][1]
                     or (a > 0 and value[a - 1] == _DQ_REF)):
            # A value that field splitting could break apart binds only at a QUOTED use (Codex
            # 20536, P1-2); `known` maps name -> (value, needs_quote).
            out.append(known[ref[2:-1] if ref.startswith("${") else ref[1:]][0])
        else:
            raise _Unenumerated(_expansion_kind(ref))
        last = b
    out.append(value[last:])
    return ("".join(out).replace(_DQ_REF, "").replace(_LIT_DOLLAR, "$").replace(_LIT_TICK, "`"))


def _path_shaped(value: str, uglob: bool) -> bool:
    """The DEFAULT: could this word be a path? (`/`, a leading `~` or `.`, an unquoted glob.)
    Substitution spans are removed first — their bodies are judged as commands; their OUTPUT is
    only path-shaped if the word around it is."""
    rest = re.sub(r"\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`", "\x01", value)
    # A word whose value is (partly) an expansion — a substitution's output, `$VAR` — COULD be a
    # path: it is judged, which now means UNENUMERATED (`_word_value`). Never skipped. A brace
    # expansion is path-shaped when it can produce a separator or a `..`.
    return ("/" in rest or rest.startswith(("~", ".")) or uglob or "\x01" in rest
            or "$" in rest or (_BRACE in rest and ".." in rest))


class _Found:
    """What one scan found besides its literal candidates (shared by nested scans)."""

    def __init__(self):
        self.unenum = []            # why a value the gate would judge is unenumerated
        self.dirs = []              # literal directories relative paths may resolve under
        self.dirs_unknown = None    # why a directory change cannot be followed
        self.known = {}             # names bound to ONE literal so far (`_literal_names`)
        self.patterns = []          # literal grep-family PATTERN values (`_PATTERN_HEADS`, #1241)


#: THE SINGLE-LITERAL-ASSIGNMENT RULE (dp's ruling, 2026-10-11, measured on #1232 first: ~45% of
#: the once-only requests were `S=/tmp/x; cat $S/y`). A variable assigned exactly ONE literal
#: earlier in the SAME command, and never otherwise bound, resolves to that literal where it is
#: used as a path — and is then judged like the literal. Everything else stays unenumerated:
#: names the shell or the environment owns; a second assignment, `unset`, `export`, `read`,
#: `for`, `declare`/`local`/`typeset`/`readonly` (incl. `-n` namerefs), arrays (`N[i]=`,
#: `N=(…)`), appends (`N+=`), `printf -v`, `mapfile`, `let`, `getopts`; any command that runs a
#: string or a file as shell in this command (`eval`, `source`/`.`, `sh -c`, `watch`, `su -c`, …)
#: or defines a function; a value with `$`, a backtick, a glob character, a brace or a `..`
#: component; an assignment that is not a top-level statement of its own (inside `( )`, `{ }`,
#: a loop, a branch, a function, a substitution body; entered after `&&` / `||` / `|`; ended by
#: anything but `;`, a newline or `&&`; or a prefix to a command, which does not bind for that
#: command's own expansions); and a use BEFORE the assignment.
_SHELL_OWNED_NAMES = frozenset(("HOME", "PWD", "OLDPWD", "IFS", "PATH", "CDPATH", "ENV",
                                "BASH_ENV", "SHELLOPTS", "BASHOPTS", "PS4", "UID", "EUID", "PPID",
                                "RANDOM", "SECONDS", "LINENO", "BASH_ARGV0", "GLOBIGNORE"))
_BINDING_COMMANDS = frozenset(("for", "select"))
#: Any of these ANYWHERE in the command disqualifies EVERY name (Codex 20536, P1-3): their operand
#: spellings (`printf -vS`, `read -aS`, `declare -n R=S`, …) are not worth modelling.
_ANY_BINDER = frozenset(("unset", "export", "read", "declare", "local", "typeset", "readonly",
                         "mapfile", "readarray", "getopts", "let", "eval", "source", ".",
                         "watch", "function", "builtin", "enable", "trap", "alias"))
_CODE_COMMANDS = frozenset(("eval", "source", ".", "watch", "function"))


def _literal_names(toks) -> set:
    """Names that may bind (see the rule above): assigned exactly once anywhere in the token
    stream (substitution bodies included), never bound any other way, not shell- or
    environment-owned, and the command runs no string or file as shell and defines no function."""
    words = [w for k, w, _g in toks if k == "word"]
    # Wholesale disqualifications (Codex 20536, P1-3 and P1-4): any binder; `printf` with ANY
    # option starting `-v`; any arithmetic (`$((`, `((`); an assigning expansion (`${N:=x}`,
    # `${N=x}`); any shell or interpreter invocation, with any option spelling, anywhere.
    for i, w in enumerate(words):
        b = os.path.basename(w)
        if b in _ANY_BINDER or _HEREDOC_INTERPRETER.match(b) or b in _CODE_OPT_HEADS \
                or "$((" in w or "((" in w or re.search(r"\$\{[A-Za-z_]\w*:?=", w):
            return set()
        if b == "printf" and any(x.startswith("-v") for x in words[i + 1:]):
            return set()
    for i, (k, w, _g) in enumerate(toks):
        if k == "sep" and w == "(" and i > 0 and toks[i - 1] == ("sep", "(", False):
            return set()                                   # `(( … ))`
    for i, (k, w, _g) in enumerate(toks):
        if k == "word" and (os.path.basename(w) in _CODE_COMMANDS
                            or (w in ("-c", "--command") and i > 0 and toks[i - 1][0] == "word"
                                and (_HEREDOC_SHELL.match(os.path.basename(toks[i - 1][1]))
                                     or os.path.basename(toks[i - 1][1]) in _CODE_OPT_HEADS))):
            return set()
        if (k == "sep" and w == "(" and i > 0 and toks[i - 1][0] == "word"
                and i + 1 < len(toks) and toks[i + 1] == ("sep", ")", False)):
            return set()                                   # `f() …`: a function definition
    if "printf" in words and "-v" in words:
        return set()
    count, banned = {}, set()
    after_binder = False
    for k, w, _g in toks:
        if k != "word":
            after_binder = False
            continue
        if os.path.basename(w) in _BINDING_COMMANDS:
            after_binder = True
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?(\+)?=", w)
        if m:
            name = m.group(1)
            if m.group(2) or m.group(3) or after_binder:
                banned.add(name)                           # arrays, appends, declared/exported
            if after_binder:
                banned.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", w))   # `-n R=N`: N too
            count[name] = count.get(name, 0) + 1
            continue
        if after_binder:
            name = w.split("=", 1)[0]
            if name.isidentifier():
                banned.add(name)                           # `unset N`, `read N`, `for N`, `-n R=N`
            for ref in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", w):
                banned.add(ref)                            # a nameref's TARGET too (`R=N`)
    return {n for n, c in count.items()
            if c == 1 and n not in banned and n not in _SHELL_OWNED_NAMES and n not in os.environ}


def _is_bindable_literal(val: str, uglob: bool) -> bool:
    """A value that is a literal and nothing else: no `$` (live or quoted), backtick, glob
    character, brace or `..` component. (Whitespace is allowed here; such a value binds only at
    a quoted use — see `_word_value`.)"""
    if uglob or _BRACE in val or any(c in val for c in "$`*?[{}") or _LIT_DOLLAR in val \
            or _LIT_TICK in val or _DQ_REF in val or _ANSI_C_MARK in val:
        return False
    return ".." not in val.split("/")


def _outside_candidates(cmd: str, cwd: str = "", depth: int = 0, found=None) -> list:
    """`(spelling, kind, globbed)` for every literal path-shaped word of `cmd`, kind "abs" | "rel".

    DEFAULT-JUDGE: every path-shaped word is a candidate unless a precise (command, position /
    option) exception in `_CMD_SPECS` says that argument is a pattern, delimiter or string.
    Redirection targets are always candidates. NOTHING AN EXPANSION PRODUCES IS MODELLED: a word
    whose value an expansion decides is recorded on `found.unenum` (the act is then a scope request,
    `UNENUMERATED_TARGET`), as are argv built from stdin, a process substitution, an expansion used
    as the program, and an expansion handed to a command in its environment. Directory changes
    (`cd D`, `pushd D`, `git|make|tar -C D`) are recorded on `found.dirs` so relative paths are
    also judged under them. Raises `_Unmodelled` only for shell the lexer cannot read."""
    out = []
    found = found if found is not None else _Found()
    pwd = cwd or os.getcwd()

    def emit(value, uglob):
        if not _path_shaped(value, uglob):
            return
        try:
            v = _word_value(value, in_force())
        except _Unenumerated as why:
            found.unenum.append(str(why))
            return
        if v != value and not _path_shaped(v, uglob):
            # #1296: the word was path-shaped only because it held a `$` the single-literal
            # rule then resolved. Its VALUE is judged as its literal spelling would be: a header
            # (`-H "id: $S"`) or a bare token is not a path when written out, so it is not one
            # when bound either.
            return
        if v.startswith("~"):
            found.unenum.append("a ~user home the gate does not resolve")
            return
        if v.startswith("//"):
            v = "/" + v.lstrip("/")
        if uglob:
            comps = v.split("/")
            g = next((k for k, c in enumerate(comps) if _GLOB_CHARS.search(c)), None)
            if g is not None and ".." in comps[g + 1:]:
                # `/tmp/*/../../x` is wherever the glob's match leads: not the glob's directory.
                found.unenum.append("a glob followed by `..`")
                return
        if v.startswith("/"):
            out.append((v, "abs", uglob))
        elif v:
            out.append((v, "rel", uglob))

    def code(text):
        # A string the command runs as shell (`eval`, `su -c`, `sh -c` in argv): a command of
        # its own. A `$` single quotes kept literal here is live when the string runs.
        out.extend(_outside_candidates(_strip_data_heredocs(
            text.replace(_DQ_REF, "").replace(_BRACE, "").replace(_LIT_DOLLAR, "$")
            .replace(_LIT_TICK, "`")), pwd, depth + 1, found))

    def pattern(word, judge=True):
        """A grep-family PATTERN operand: data like any other (`data`), and, when it is one LITERAL
        word, its value is recorded so the workspace passes do not judge text the tool only matches
        against (#1241 recut). A word holding any expansion is not recorded: what it expands to is
        not known, and a substitution inside it was already lifted out and is judged."""
        if state["head"] in _PATTERN_HEADS and _LIT_DOLLAR not in word and _LIT_TICK not in word:
            try:
                literal = not _expansion_spans(word)
            except _Unmodelled:
                literal = False
            if literal and "$" not in word and "`" not in word and word:
                found.patterns.append(word)
        if judge:
            data(word)

    def in_force():
        cut = body_origin
        return {n: (v_, q_) for n, (v_, q_, ci) in found.known.items() if cut is None or ci < cut}

    def chdir(value, uglob):
        try:
            v = _word_value(value, in_force())
        except _Unenumerated as why:
            found.dirs_unknown = f"a directory change to {why}"
            return
        if uglob or v.startswith("~") or v == "-" or not v:
            found.dirs_unknown = f"a directory change to '{v[:40]}'"
            return
        found.dirs.append(v)

    toks = _shell_words(cmd)
    state = {}
    # Names assigned a value holding a glob character anywhere in the command (#1287). In a data
    # position such a name is still DATA when quoted; UNQUOTED, the shell expands the glob there —
    # a directory read — so that one use is unenumerated.
    globby = {m.group(1) for k, w_, _g in toks if k == "word"
              for m in [re.match(r"([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)", w_, re.S)]
              if m and any(c in m.group(2) for c in "*?[")}

    def data(word, fields=True):
        """A word in a DATA position (a message, pattern or string operand): no path is judged.
        A QUOTED expansion is one argument and stays data, unless it holds `@` (`"${A[@]}"`,
        `"${A[@]:1}"`, `"${!A[@]}"`, `"${@:1}"`): one argument per element, so where `fields` holds it
        is unenumerated (Codex HOLD 21718). An UNQUOTED one is expanded by the
        shell first. A glob-valued name expands to a directory read, so it is unenumerated in
        every data position. And where the next argument would be a file (`fields`: an option
        value, the grep / sed / awk program, a prose option) a value that field splitting breaks
        apart inserts more arguments: `--title $R` with R="hi --body-file F" hands gh a file
        (Codex HOLD 21675; main had it at `grep $R`, `git commit -m $R`). There an unquoted
        expansion is data only when it is provably ONE field: a name bound to one literal
        with no IFS whitespace (`in_force`), arithmetic, or a digit / flag-letter parameter.
        `$'…'` is quoted. In an `echo` / `printf` / `tr` operand (`fields=False`) another field is
        another string."""
        try:
            spans = _expansion_spans(word)
        except _Unmodelled as why:
            found.unenum.append(str(why))
            return
        one = in_force() if fields else {}
        for a, b in spans:
            ref = word[a:b]
            if a > 0 and word[a - 1] == _DQ_REF:
                # Quoted, but `@` inside `${…}` is one argument PER ELEMENT (Codex HOLD 21718):
                # `"${A[@]}"` with A=(hello OUTSIDE) hands `--notes` hello and gh an asset.
                if fields and _per_element(ref):
                    kind = _expansion_kind(ref.replace(_DQ_REF, ""))
                    found.unenum.append(f"{kind}, quoted, still passes one argument per element "
                                        "where another argument can be a file (use a scalar "
                                        "variable)")
                continue
            name = ref[2:-1] if ref.startswith("${") else ref[1:]
            if name in globby:
                found.unenum.append(f"an unquoted ${name} whose value holds a glob")
            elif fields and not (ref.startswith("$((") or ref in _PLACEHOLDER_PARAMS
                                 or ref == _ANSI_C_MARK or (name in one and not one[name][1])):
                # `$'…'` is a quoted word of its own: its placeholder never splits.
                found.unenum.append(f"{_expansion_kind(ref)} unquoted where field splitting can "
                                    "add arguments (quote it to pass one argument)")
    # The literal rule binds only in the OUTER command's own statements: substitution bodies are
    # appended after them by `_shell_words`, and a body is a subshell.
    main_len = len(_tokenize(cmd)) if depth == 0 else 0
    bindable = _literal_names(toks) if depth == 0 else set()
    # IFS decides field splitting. The default-IFS assumption holds only while the command never
    # NAMES IFS: then every binding resolves at an unquoted use too. Any occurrence of the name, in
    # any position (`IFS=`, `IFS+=`, a prefix, `for IFS in`/`for IFS;`, `select IFS`, `exec {IFS}>`,
    # `coproc IFS`, `wait -p IFS`, a data body, a comment), makes every binding resolve only at a
    # double-quoted use. Not an enumeration of binders: Codex 20554 found `=`, 20972 found `for`,
    # and bash has more. Backslash-newlines are removed first (`I\<newline>FS=:` binds IFS). Code
    # the gate cannot see (`eval`, `source`, `sh -c`, namerefs, `printf -v`) already disqualifies
    # the rule wholesale; an IFS inherited from earlier shell state stays the stated residual.
    # The token test is kept beside the text test so this never allows what 20554's repair refused.
    ifs_touched = ("IFS" in cmd.replace("\\\n", "")
                   or any(k == "word" and re.match(r"IFS\+?=", w) for k, w, _g in toks))
    bind = {"pending": None, "prev_sep": ";", "paren": 0, "kw": 0}

    def new_segment(sep=None):
        # An INTERPRETER whose program is not on its command line — piped in, a here-string, `-`,
        # or a descriptor path — runs code the gate cannot see: unenumerated (Codex 20536).
        h = state.get("head")
        if h and _HEREDOC_INTERPRETER.match(h) and not state.get("code_opt") \
                and not state.get("heredoc") and (
                state.get("stdin_prog") or ((state.get("piped_in") or state.get("herestring"))
                                            and not state.get("script_arg"))):
            found.unenum.append(f"`{h}` reading its program from stdin or a descriptor")
        # `cd` with no argument goes HOME; `pushd` with none swaps the stack (not followed).
        if state.get("head") in ("cd", "pushd") and not state.get("chdir_seen"):
            home = os.getenv("HOME")
            if state["head"] == "cd" and home:
                found.dirs.append(home)
            else:
                found.dirs_unknown = f"`{state['head']}` with no directory"
        state.update(head=None, spec={}, pending=None, redirect=False, positional=0, subs=[],
                     pattern_given=False, opts_done=False, dirpending=False, chdir_seen=False,
                     env_expansion=None, code_opt=False, stdin_prog=False, herestring=False,
                     script_arg=False, heredoc=False, piped_in=sep in ("|", "|&"))

    new_segment()
    loop_state = None
    seg_words, prev = [], None
    body_origin = None
    for idx, (kind, w, uglob) in enumerate(toks):
        p, prev = prev, (kind, w)
        if kind == "mark":
            # Entering a substitution body: from here on only bindings committed BEFORE the
            # outer word that holds it are in force (Codex 20536, P1-1).
            body_origin = w
            continue
        if bind["pending"] is not None:
            name_, val_ = bind["pending"]
            bind["pending"] = None
            if kind == "sep" and w in (";", "&&"):
                # The statement ended: N is bound from token `idx` on. (value, needs_quote,
                # commit index): IFS whitespace in the value binds only at a quoted use.
                found.known[name_] = (val_, ifs_touched or any(c in val_ for c in " \t\n"), idx)
        if kind == "sep" and w == "(":
            bind["paren"] += 1
        elif kind == "sep" and w == ")":
            bind["paren"] = max(0, bind["paren"] - 1)
        elif kind == "word" and state["head"] is None and w in ("if", "while", "until", "for",
                                                                "case", "select", "{"):
            bind["kw"] += 1
        elif kind == "word" and state["head"] is None and w in ("fi", "done", "esac", "}"):
            bind["kw"] = max(0, bind["kw"] - 1)
        # `for V in W…; do` — V is a variable (unenumerated wherever it is used as a path); a
        # globbed W is itself a reach.
        if loop_state == "var" and kind == "word":
            loop_state = "in"
            continue
        if loop_state == "in" and kind == "word":
            loop_state = "items" if w == "in" else None
            continue
        if loop_state == "items":
            if kind == "word":
                if uglob:
                    emit(w, uglob)
                continue
            loop_state = None
        if kind == "word" and state["head"] is None and w == "for":
            loop_state = "var"
            continue
        if kind == "sep" and w == "(" and p is not None and p[0] == "op" and p[1] in ("<", ">"):
            found.unenum.append("a process substitution used as a path")
        if kind == "sep" or (kind == "word" and state["head"] is None and w in _SHELL_KEYWORDS):
            seg_words = []
            new_segment(w if kind == "sep" else None)
            bind["prev_sep"] = w if kind == "sep" else "keyword"
            continue
        if kind == "word":
            seg_words.append(w)
        if kind == "op":
            # `<` `>` `>>` `2>` `&>` `<>`: the next word is a file — always judged. `<<<`: the next
            # word is a here-STRING (data; its substitutions were lifted out and are judged).
            # `<<`: the next word is a heredoc delimiter (bodies are handled before tokenising).
            state["redirect"] = "skip" if w.startswith("<<") else True
            if w.startswith("<<<"):
                state["herestring"] = True
            elif w.startswith("<<"):
                state["heredoc"] = True            # a heredoc program is visible and judged
            continue
        if state["redirect"] == "skip":
            state["redirect"] = False
            continue
        if state["redirect"]:                # a redirection target: always judged
            state["redirect"] = False
            emit(w, uglob)
            continue
        head, spec = state["head"], state["spec"]
        if head is None:
            name, eq, val = w.partition("=")
            if eq and name.isidentifier():                 # an assignment
                # Reaches nothing by itself. A LITERAL path value is judged (a command it prefixes
                # may read it: `CFG=/x tool`). A value an expansion decides makes the name unknown
                # (unenumerated wherever it is used as a path), and is unenumerated at once if a
                # command follows in this simple command and receives it in its environment.
                try:
                    _word_value(val)
                    literal = True
                except _Unenumerated:
                    literal = False
                if name not in _NONPATH_ASSIGNMENTS:
                    if literal:
                        emit(val, uglob)
                    elif state["env_expansion"] is None:
                        state["env_expansion"] = name
                if (literal and name in bindable and idx < main_len and bind["paren"] == 0
                        and bind["kw"] == 0 and bind["prev_sep"] == ";"
                        and _is_bindable_literal(val, uglob)):
                    # Bound only if the NEXT token ends the statement (`;`, newline, `&&`):
                    # a word next makes this a prefix assignment, which binds nothing here.
                    bind["pending"] = (name, _word_value(val))
                continue
            base = os.path.basename(w)
            if base in _STDIN_ARGV:
                found.unenum.append(f"argv built from stdin (`{base}`)")
            if base in _HEREDOC_WRAPPERS or w.isdigit() or re.fullmatch(r"\d+[smhd]?", w) \
                    or (w.startswith("-") and len(w) > 1):
                continue                                   # wrapper, its options and durations
            if _expansion_spans(w):
                found.unenum.append("an expansion used as the program")
            if state["env_expansion"] is not None:
                found.unenum.append(f"an expansion handed to `{base}` in "
                                    f"${state['env_expansion']}")
            state["head"], state["spec"] = base, _CMD_SPECS.get(base, {})
            if "/" in w or w.startswith("."):
                emit(w, uglob)                             # a program run by path is a reach
            if base in ("export", "local", "declare", "typeset", "readonly"):
                state["spec"] = {"assign_args": "export" if base == "export" else "local"}
            if base == "popd":
                found.dirs_unknown = "`popd`"
            continue
        # ---- an argument of `head` ----
        if (len(seg_words) >= 3 and seg_words[-2] == "-c" and not _HEREDOC_SHELL.match(head)
                and _HEREDOC_SHELL.match(os.path.basename(seg_words[-3]))):
            code(w)                         # `find … -exec sh -c '…'`, `docker exec c bash -c '…'`
            continue
        if state["dirpending"]:
            state["dirpending"] = False
            chdir(w, uglob)
            emit(w, uglob)
            continue
        if state["pending"] is not None:
            opt, state["pending"] = state["pending"], None
            if opt in spec.get("code_opts", ()):
                code(w)
                continue
            if (opt in spec.get("delim_opts", ()) or opt in spec.get("pattern_opts", ())
                    or opt in _string_opts(head, spec, state["subs"])) and not uglob:
                if opt in spec.get("pattern_opts", ()):
                    state["pattern_given"] = True
                    pattern(w)
                else:
                    data(w)
                continue
            if opt == "-c" and _HEREDOC_SHELL.match(head):
                code(w)
                continue
            if opt in ("-c", "-e") and _CODE_ARG_HEADS.match(head):
                for lit in _code_path_literals(w.replace(_DQ_REF, "").replace(_LIT_DOLLAR, "$")):
                    emit(lit, False)
                continue
            emit(w, uglob)
            continue
        if w == "--" and not state["opts_done"]:
            state["opts_done"] = True
            continue
        if w.startswith("-") and len(w) > 1 and not state["opts_done"]:
            name, eq, val = w.partition("=")
            if head in _DIR_OPT_HEADS:
                if w in ("-C", "--directory"):
                    state["dirpending"] = True
                    continue
                if name == "--directory" and eq:
                    chdir(val, uglob)
                    emit(val, uglob)
                    continue
                if w.startswith("-C") and len(w) > 2:
                    chdir(w[2:], uglob)
                    emit(w[2:], uglob)
                    continue
            strs = _string_opts(head, spec, state["subs"])
            takes = (spec.get("delim_opts", set()) | spec.get("pattern_opts", set())
                     | strs | spec.get("file_opts", set())
                     | spec.get("value_opts", set()) | spec.get("code_opts", set()))
            if eq:
                if name in spec.get("code_opts", ()):
                    code(val)
                    continue
                if name in spec.get("pattern_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (name in spec.get("delim_opts", ())
                                 or name in spec.get("pattern_opts", ())
                                 or name in strs):
                    emit(val, uglob)
                elif name in spec.get("pattern_opts", ()):
                    pattern(val)
                else:
                    data(val)
                continue
            if (_HEREDOC_SHELL.match(head) or _CODE_ARG_HEADS.match(head)) and not w.startswith("--") \
                    and re.fullmatch(r"-[A-Za-z]*[ce][A-Za-z]*", w) \
                    and ("c" in w[1:] or (_CODE_ARG_HEADS.match(head) and "e" in w[1:])):
                # A clustered code option (`bash -lc`, `sh -ec`, `perl -ne`, Codex 20536 P1-4):
                # the next word is the program, whatever letters ride with it.
                state["pending"] = "-c" if "c" in w[1:] else "-e"
                state["code_opt"] = True
                continue
            if w in takes or (w == "-c" and (_HEREDOC_SHELL.match(head)
                                             or _CODE_ARG_HEADS.match(head))) \
                    or (w == "-e" and _CODE_ARG_HEADS.match(head)):
                state["pending"] = w
                if w in ("-c", "-e"):
                    state["code_opt"] = True
                continue
            if not w.startswith("--") and len(w) > 2 and w[:2] in takes:
                # attached short-option value: `-d/`, `-F:`, `-e/x/`, `-fFILE`
                if w[:2] in spec.get("code_opts", ()):
                    code(w[2:])
                    continue
                if w[:2] in spec.get("pattern_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (w[:2] in spec.get("delim_opts", ())
                                 or w[:2] in spec.get("pattern_opts", ())
                                 or w[:2] in spec.get("string_opts", ())):
                    emit(w[2:], uglob)
                elif w[:2] in spec.get("pattern_opts", ()):
                    pattern(w[2:], judge=False)            # as before, plus its value recorded
                continue
            m = _ATTACHED_OPT.match(w)
            if m:
                emit(m.group(1), uglob)                    # `-I/usr/include`, `-C/elsewhere`
            continue
        state["positional"] += 1
        if head == "git" and state["positional"] == 1 and w == "grep":
            # `git [opts] grep …`: from here the arguments are grep's (#1241 recut).
            state.update(head="git-grep", spec=_GIT_GREP_SPEC, positional=0, opts_done=False)
            continue
        if len(state["subs"]) < 3:
            state["subs"].append(w)
        if state["positional"] == 1 and _HEREDOC_INTERPRETER.match(head) and not state["code_opt"]:
            # The program: a script file (judged as a path below), or stdin / a descriptor.
            if w == "-" or w.startswith(("/dev/fd/", "/dev/stdin", "/proc/self/fd/")):
                state["stdin_prog"] = True
            else:
                state["script_arg"] = True
        if head in ("cd", "pushd") and state["positional"] == 1:
            state["chdir_seen"] = True
            chdir(w, uglob)
            emit(w, uglob)                                 # where it goes is a reach too
            continue
        if head == "read" and w.isidentifier():
            continue                                       # a variable name, not a path
        if spec.get("assign_args"):
            name, eq, val = w.partition("=")
            if eq and name.isidentifier():                 # `export D=/x` — as an assignment
                try:
                    _word_value(val)
                    literal = True
                except _Unenumerated:
                    literal = False
                if name not in _NONPATH_ASSIGNMENTS:
                    if literal:
                        emit(val, uglob)
                    elif spec["assign_args"] == "export":
                        found.unenum.append(f"an expansion exported in ${name}")
                continue
        mode = spec.get("positional")
        if mode == "code":
            code(w)                                        # `eval "…"`, `watch '…'`
            continue
        # An UNQUOTED glob is expanded by the shell BEFORE the command sees its arguments, so no
        # (command, position) exception can make it a string or a pattern: `tr /x/* y` and
        # `grep /x/*` read /x (Codex review 17029c). Exceptions apply to glob-free words only.
        if mode in ("strings", "strings_noglob") and not uglob:
            data(w, fields=False)
            continue
        if spec.get("pattern_first") and state["positional"] == 1 and not state["pattern_given"] \
                and not uglob:
            pattern(w)
            continue
        name, eq, val = w.partition("=")
        if eq and name.isidentifier():                     # `dd if=/x`, `make DESTDIR=/x`
            emit(val, uglob)
            continue
        emit(w, uglob)
    new_segment()
    return out


def _dir_bases(dirs, cwd: str):
    """Every directory a relative path may resolve under after the command's directory changes:
    each literal `cd` / `-C` target, a relative one composed under every base known before it
    (`cd a && cd b` reaches cwd/a/b). Over-approximates the shell's scoping (`(cd x)` leaks here),
    which only adds judgments. None when there are more than `_MAX_DIR_BASES`."""
    bases = []
    for d in dirs:
        if d.startswith("/"):
            new = [os.path.normpath(d)]
        else:
            new = [os.path.normpath(os.path.join(b, d)) for b in [cwd] + bases]
        for n in new:
            if n not in bases:
                bases.append(n)
        if len(bases) > _MAX_DIR_BASES:
            return None
    return bases


def _is_reach(path: str) -> bool:
    """Whether an absolute spelling plausibly names a filesystem object: it exists, or its
    nearest existing ancestor is below `/`. `/` itself is a reach (`find /`). A spelling whose
    only existing ancestor is the root — a sed address `/^#/d`, a regex, prose — is not."""
    if path == "/":
        return True
    p = path
    for _ in range(40):
        if os.path.lexists(p):
            return p != "/" or path == "/"
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent
    return False


def _names_nothing(path: str) -> bool:
    """Whether a refused reach is a PHANTOM (hestia#1327): neither it nor its parent directory
    exists, so it names no object a grant could be about. `_dir_bases` composes a relative `cd`
    under every earlier base, so `cd /ws && cd a && cd ../b` also judges `<cwd>/../b` and every
    later relative word under it; each such spelling opened a peer request for nothing. The
    parent rule keeps a NEW file in an existing directory (`echo x > /out/new.txt`) a real ask.
    A glob probe (`dir/*`) is judged as its directory; a device path is never a phantom."""
    p = path[:-2] if path.endswith("/*") else path
    if p == "/dev" or p.startswith("/dev/"):
        return False
    return not os.path.lexists(p) and not os.path.lexists(os.path.dirname(p) or "/")


def _glob_probe(path: str) -> str:
    """The path a glob is judged as: its literal directory plus a `*` child, so a glob reaches
    only what a RECURSIVE grant (or temp/home) covers — an exact grant on one file under the
    directory does not authorise `dir/*`."""
    comps = path.split("/")
    for i, c in enumerate(comps):
        if _GLOB_CHARS.search(c):
            base = "/".join(comps[:i]) or "/"
            return base.rstrip("/") + "/*"
    return path


def _outside_reach_refused(resolved: str, scopes, workspace: str, cwd: Optional[str], egress,
                           home_markers) -> Optional[tuple]:
    """Judge one absolute candidate exactly like a Read path (`path_in_scope`: temp roots, the
    member's home markers, `path:` grants by realpath, the workspace's segment rule) — and,
    when a symlink is on the way, judge where it LANDS as well. Returns None when the reach is
    in scope, else `(offending, refused_path)`."""
    if _device_sink(resolved):
        return None
    prof = HarnessProfile(member_id="", identity_path="", home_markers=tuple(home_markers or ()))
    lexical = os.path.normpath(resolved).replace("\\", "/")
    target = os.path.realpath(lexical).replace("\\", "/")
    if target != lexical:
        low = target.lower()
        hidden = next((f for f in egress if f in low), None)
        if hidden is not None:
            return target, target
    if not path_in_scope(lexical, scopes, workspace, prof, cwd):
        return _elide(lexical), lexical
    if target != lexical and not _device_sink(target) and not path_in_scope(target, scopes,
                                                                            workspace, prof, cwd):
        return _elide(target), target
    return None


#: A whole command that is ONE `for V in <literals>; do BODY; done` (L-b in the #1205 corpus
#: proposal; #1232 field reports, 2026-10-13). Items are limited to characters that can never
#: expand, quote or glob; anything else falls through to the ordinary judge, where V stays
#: unenumerated. The closing `done` must follow a `;` or newline and end the command: Codex
#: HOLD 23938 showed a `\bdone` suffix strips `done` from `.../granted-done` after an
#: already-closed loop, judging a different path.
_LITERAL_FOR = re.compile(
    r"\A\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in((?:[ \t]+[A-Za-z0-9_./:@+,%=-]+)+)[ \t]*[;\n]\s*"
    r"do[ \t\n](.*)[;\n][ \t\n]*done[ \t\n]*\Z", re.S)
LITERAL_FOR_BUDGET = 32
#: A body word that could close or open a loop. Matched ANYWHERE in the body, quoted or not:
#: `echo done` is refused the rule (judged as before) so that no `done` but the last one can be
#: the loop's end.
_LITERAL_FOR_KEYWORD = re.compile(r"(?<![A-Za-z0-9_./-])(?:done|do|for|while|until|select)(?![A-Za-z0-9_./-])")
#: Body state that persists from one iteration into the next, which an independent per-iteration
#: judgement cannot see (Codex HOLD 23938: `cd sub` repeated walks a symlink out of the grant on
#: the third pass). Matched anywhere in the body as a word: directory changes, every builtin
#: that binds, unbinds or re-shapes expansion, function definitions, assignments (bare, array,
#: `+=`, `${X:=}`), and comments/heredocs that could hide the structure. Source (`.`) is a
#: standalone `.` word followed by an argument, in ANY position: Codex review 24029 showed a
#: separator-anchored match misses `! . f`, `if . f`, `time . f` and `>/dev/null . f`. The
#: cost is that `find . -name x` in a body loses the new allow.
_LITERAL_FOR_STATEFUL = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:cd|pushd|popd|export|unset|set|shopt|alias|unalias|source|eval|exec|"
    r"declare|typeset|local|readonly|read|mapfile|readarray|let|getopts|umask|hash|enable|builtin|"
    r"command|trap|ulimit|function|printf)(?![A-Za-z0-9_./-])"
    r"|(?<![^\s;&|(){}`<>!])\.[ \t]+(?=[^\s;&|)])"
    r"|(?:\A|[\s;&|(){}`])[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?="
    r"|\$\{[^}]*=|\(\s*\)|#|<<")


def _literal_for_iterations(cmd: str):
    """`["V=item; BODY", ...]` when `cmd` is a single loop over literal items, else None.

    THE LITERAL-LIST LOOP RULE extends the single-literal-assignment rule (dp, 2026-10-11) to a
    loop whose list is literal: inside iteration i, V holds item i and nothing else, so the
    iteration reaches exactly what `V=item; BODY` reaches, and that statement is judged by the
    ordinary rule, which still refuses a body that re-binds V, runs a string as shell, and so
    on. The loop is allowed only if EVERY iteration is. What is dropped from the judged text is
    the loop header (a name and literals) and the closing `done`; every executable word of the
    body is still judged. A list with a glob, a quote, a `$`, a `..` component, or more than
    LITERAL_FOR_BUDGET items is not literal, and the loop is judged as before.

    Judging iterations independently is sound only if no iteration changes what the next one
    reaches, so a body with any word `_LITERAL_FOR_STATEFUL` names (a `cd`, an assignment, a
    builtin that binds) is judged as before, as is a body holding a second loop keyword
    (`_LITERAL_FOR_KEYWORD`), which could mean the loop closed earlier. Both are deliberately
    coarse: a body they wrongly exclude loses only the new allow, never a refusal."""
    m = _LITERAL_FOR.match(cmd)
    if not m:
        return None
    var, items, body = m.group(1), m.group(2).split(), m.group(3)
    if not body.strip() or len(items) > LITERAL_FOR_BUDGET or var in _SHELL_OWNED_NAMES:
        return None
    if _LITERAL_FOR_KEYWORD.search(body) or _LITERAL_FOR_STATEFUL.search(body):
        return None
    if any(not _is_bindable_literal(it, False) for it in items):
        return None
    if any(_literal_for_body_uncertain(body, var, it) for it in items):
        return None
    return [f"{var}={it}; {body}" for it in items]


#: Builtin names `_LITERAL_FOR_STATEFUL` refuses as words, plus `.` (source), for the glob check.
_LITERAL_FOR_STATEFUL_NAMES = (
    "cd", "pushd", "popd", "export", "unset", "set", "shopt", "alias", "unalias", "source", "eval",
    "exec", "declare", "typeset", "local", "readonly", "read", "mapfile", "readarray", "let",
    "getopts", "umask", "hash", "enable", "builtin", "command", "trap", "ulimit", "function",
    "printf", ".")


def _literal_for_body_uncertain(body: str, var: str, item: str) -> bool:
    r"""True when iteration `var=item` of `body` could run a stateful word the raw text hides.

    `_LITERAL_FOR_STATEFUL` reads raw text, but bash forms command words AFTER expansion and quote
    removal: `c''d`, `c"d"`, `c\d`, a line continuation inside the word, `pu''shd`, an item that is
    itself `cd` (`$f sub`), `c$f`, `$(echo c)d`, `$'\x63d'`, or a glob such as `c?` beside a file
    named `cd` all run `cd` (Codex HOLD 23996). This check does not decode those forms; it refuses
    the ones it cannot read exactly (Codex: "a conservative refusal of uncertain forms is
    preferable to extending the raw-text spelling list"):
    - V is substituted (`$V`, `${V}`) with the item, which is a bindable literal; then any `$`,
      backtick or brace left means an expansion whose result the text does not show;
    - quote characters and backslashes are deleted (a backslash-newline pair first), which yields
      every word quote removal could produce, over-approximately, and the stateful pattern is
      run again on that text;
    - any word still holding a glob character that could match a stateful name is refused;
    - any word holding a bracket expression, and any extglob opener (`?(`, `*(`, `+(`, `@(`,
      `!(`), is refused outright: Python's fnmatch does not implement POSIX classes
      (`c[[:alpha:]]`) or `[^x]` negation, so it cannot show such a word misses a stateful
      name (Codex review 24029). Only the test words `[` and `[[` are kept.
    A body this refuses loses only the new allow and is judged as before."""
    text = re.sub(r"\$\{" + var + r"\}|\$" + var + r"(?![A-Za-z0-9_])", lambda _m: item, body)
    if re.search(r"[$`{}]", text):
        return True
    decoded = re.sub(r"['\"\\]", "", text.replace("\\\n", ""))
    if _LITERAL_FOR_KEYWORD.search(decoded) or _LITERAL_FOR_STATEFUL.search(decoded):
        return True
    if re.search(r"[?*+@!]\(", decoded):
        return True
    for word in re.split(r"[\s;&|()<>]+", decoded):
        if "[" in word and word not in ("[", "[["):
            return True
        if re.search(r"[*?]", word) and any(
                _fnmatch.fnmatchcase(name, word) for name in _LITERAL_FOR_STATEFUL_NAMES):
            return True
    return False


def _grammar_patterns(cmd: str, cwd: Optional[str]) -> tuple:
    """(patterns, judged) from the shell grammar: the literal grep-family PATTERN values it
    recognised (`_PATTERN_HEADS`), and every word it judges as a path. ((), ()) when it cannot
    read the line, so nothing is skipped (pass 3 then refuses the line as unenumerated)."""
    found = _Found()
    try:
        cands = _outside_candidates(_strip_data_heredocs(cmd), cwd or "", found=found)
    except _Unmodelled:
        return (), ()
    return tuple(found.patterns), tuple(c[0] for c in cands)


def _only_pattern_text(text: str, patterns, judged) -> bool:
    """A mention the in-workspace passes do not judge (#1241 recut): it lies inside a recognised
    grep-family PATTERN and inside no word the grammar judges as a path. `grep '<ws>/x' <ws>/x`
    still judges `<ws>/x`, because the operand names it too."""
    return bool(text) and any(text in p_ for p_ in patterns) and not any(text in j for j in judged)


def command_scope_reach(cmd: str, scopes, workspace: str, cwd: Optional[str] = None,
                        forbidden=None, home_markers=None):
    """Returns (ok, offending_token, resolved_path). See `_command_scope_reach_one`; a command
    that is one literal-list loop is judged per iteration (`_literal_for_iterations`)."""
    its = _literal_for_iterations(cmd)
    if its is not None:
        for it in its:
            res = _command_scope_reach_one(it, scopes, workspace, cwd, forbidden, home_markers)
            if not res[0]:
                return res
        return res
    return _command_scope_reach_one(cmd, scopes, workspace, cwd, forbidden, home_markers)


def _command_scope_reach_one(cmd: str, scopes, workspace: str, cwd: Optional[str] = None,
                             forbidden=None, home_markers=None):
    """Returns (ok, offending_token, resolved_path).

    OUTSIDE THE WORKSPACE (2026-10-05, dp: "yes on gate gap, let's fix it"). Until this pass the
    check judged only tokens UNDER the workspace, so `cat /abs/path/outside` passed on every seat
    while a Read of the same path was refused `mrh.path` — measured live the same day, a session
    listed and read a mail client's profile directory on a Windows mount through the shell. Pass 3
    judges every absolute spelling (and every relative escape) that lands outside the workspace by
    the SAME rule as a Read path — temp roots, the member's home markers, `path:` grants by
    realpath — plus the POSIX device sinks, which are law. `home_markers` comes from the
    caller's HarnessProfile; `evaluate` passes it. Heredoc bodies fed to a non-interpreter are
    data and are not judged (see `_strip_data_heredocs`).

    `forbidden` is the egress list applied to a symlink's RESOLVED target, on every absolute workspace
    token and before any grant check (#953, #1191 review); None means `_default_forbidden()`.

    `resolved_path` is the candidate the check actually judged — absolute, normalised — or
    None when nothing was refused. It is carried rather than reconstructed: the deny text
    used to rebuild `<ws>/<offending segment>` from the display token, which names the
    right repo and the wrong depth, so a deny beneath a DEEPER exact grant (`<ws>/repo/sub`
    granted exact, `<ws>/repo/sub/file` reached) got no explanation while the equivalent
    Read deny did (GPT review of #1003). The checker already knew the path; now it says so.

    A reach is judged by WHERE IT RESOLVES, not by what it lexically mentions. Lexical
    mention-scanning false-denied two whole classes, both found live via the Codex gate on
    2026-07-23: (a) the scan matched the workspace root's own path component, denying every
    absolute path; (b) it matched generic dir names ('scripts', 'logs') that exist both at the
    root and inside granted repos, denying in-repo relative paths.

    Residual, documented and accepted: relative traversal that never names a path (`grep -r .`)
    escapes string parsing entirely — the engine sandbox, not this check, is the fs boundary."""
    # The workspace is NORMALISED before anything compares against it. Spelled with `.` / `..`
    # (a caller's REPO.parent, a configured path), an inside path normalised against it looked
    # like a traversal OUT and was judged by the outside rule — under a temp-root workspace that
    # admitted the workspace's own ungranted repos (found by the staged contract run, 2026-10-10;
    # main refused every traversal, so this is a regression 01e68a1c introduced, not main's).
    workspace = os.path.normpath(workspace.replace("\\", "/")).replace("\\", "/")
    ws = workspace.rstrip("/")
    repo_scopes, _ = _scope_parts(scopes, workspace)
    egress = _default_forbidden() if forbidden is None else forbidden
    # The two once-only lifts (see UNENUMERATED_TARGET): present only in a trial scope the
    # orchestrator builds for an act whose one-time approval it holds.
    scopes = list(scopes)
    lift_unenum = "path:" + UNENUMERATED_TARGET in scopes
    lift_overflow = "path:" + OVERFLOW_TARGET in scopes
    # A home spelling is expanded from the gate's HOME below; a command that REASSIGNS HOME
    # (`HOME=/x; cat ~/y`) makes that expansion a guess, so it is unenumerated instead.
    if not lift_unenum and _HOME_REASSIGNED.search(cmd) and _HOME_WORD.search(cmd):
        return False, f"{_UNMODELLED_PREFIX}a home spelling after HOME is reassigned>", UNENUMERATED_TARGET
    # Pass 0 — the shell's home spellings, expanded before anything reads the text, so a
    # workspace path spelled `~/…` or `$HOME/…` meets pass 1 like its literal spelling does.
    cmd = _expand_home_words(cmd)
    # A grep-family PATTERN INSIDE THE WORKSPACE IS NOT A REACH (#1241 recut, SAGE #368): the tool
    # matches against it and never opens it (a being's own `-e '<ws>[^ ]*ft09'` was refused
    # "'[^' is not granted"). Patterns are recognised by the shell GRAMMAR (`_CMD_SPECS`), never by
    # rewriting the text, so a live substitution inside one is still lifted out and judged, and
    # pass 3 is not touched. A TOOLCHAIN (the being's interpreter, its sandbox's `--ro-bind`) is
    # NOT exempted here: it is reached through an operator's recursive `path:<root>/**` grant,
    # which lives in the member's vault-held scope, is witnessed and revocable, and is matched on
    # the REALPATH. #1377 first shipped an environment variable for it (HESTIA_TOOL_ROOTS); Nova's
    # review asked who can set it, and a symlink under the declared root read an ungranted repo
    # (`cat <root>/lib/link/x`), because the exemption was lexical. A caller-controlled
    # environment must not become authority.
    patterns, judged_words = _grammar_patterns(cmd, cwd)
    for after in cmd.split(workspace)[1:]:
        # Resolve the whole token before reading a segment off it (kimi #940 B7). Taking the
        # head lexically let `cat <ws>/repo-a/../repo-b/secret` pass on `repo-a` while
        # resolving into an ungranted repo — path_in_scope's B5 one function over. A command's
        # text is member-controlled end to end, so this one needs no harness to cooperate.
        tok = re.split(r"""[\s"'`);&|<>]""", after.lstrip("/"), 1)[0]
        if patterns and _only_pattern_text(workspace + after[:len(after) - len(after.lstrip("/"))] + tok,
                                           patterns, judged_words):
            continue
        resolved = os.path.normpath(f"{ws}/{tok}").replace("\\", "/")
        if resolved != ws and not resolved.startswith(ws + "/"):
            # Traversed out of the workspace: judged WHERE IT LANDS, by the outside rule (pass 3),
            # so a grant the operator makes for the landing path is honoured however it is
            # spelled. Before 2026-10-05 this refused unconditionally, which made a granted
            # outside path unreachable through a `<ws>/../…` spelling — a grant that could never
            # be spent, re-escalating forever.
            refused = _outside_reach_refused(resolved, scopes, workspace, cwd, egress, home_markers)
            if refused is None:
                continue
            return False, (tok or "<workspace root>"), refused[1]
        # EGRESS FIRST, for every token: a symlink must not launder a forbidden target past a grant.
        hidden = _symlink_target_forbidden(resolved, egress)
        if hidden is not None:
            return False, hidden, hidden
        seg = resolved[len(ws):].lstrip("/").split("/", 1)[0]
        if seg not in repo_scopes and not _within_path_grant(resolved, scopes, workspace):
            refused = _symlinked_reach_verdict(resolved, seg, repo_scopes, scopes, workspace)
            if refused is None:
                continue
            return (False,) + refused

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
    seen2 = set()
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
            if patterns and _only_pattern_text(tok, patterns, judged_words):
                continue                      # text inside a grep-family pattern (#1241 recut)
            if tok in seen2:
                continue                      # a repeated spelling is judged once
            seen2.add(tok)
            if probes >= SCOPE_JUDGE_BUDGET:
                # FAIL CLOSED (Codex review of #1232, P1-3): an unjudged token is not an
                # allowed one. The old bound `break`-ed and returned allow for everything after.
                # Escalable as the act (OVERFLOW_TARGET): a one-time approval of it lifts this.
                if lift_overflow:
                    break
                return False, _INCOMPLETE, OVERFLOW_TARGET
            probes += 1
            comps = tok.split("/")
            k = 0
            while k < len(comps) and comps[k] == "..":
                k += 1
            probe = "/".join(comps[:k + 1]) if k < len(comps) else "/".join(comps)
            in_scope_vote, oos_vote, oos_path = False, None, None
            for base in bases:
                cand = os.path.normpath(os.path.join(base, probe)).replace("\\", "/")
                if not os.path.exists(cand):
                    continue
                if cand == ws:
                    oos_vote = oos_vote or "<workspace root>"
                    oos_path = oos_path or cand
                    continue
                if cand.startswith(ws + "/"):
                    seg = cand[len(ws) + 1:].split("/", 1)[0]
                    if seg in repo_scopes or _within_path_grant(cand, scopes, workspace):
                        in_scope_vote = True
                        break
                    oos_vote, oos_path = seg, cand
                elif _within_path_grant(cand, scopes, workspace):
                    in_scope_vote = True
                    break
            if not in_scope_vote and oos_vote:
                return False, oos_vote, oos_path

    # Pass 3 — OUTSIDE the workspace (2026-10-05). Every absolute spelling, and every relative
    # escape, that lands outside the workspace is judged like a Read path. Data heredoc bodies
    # are removed first; the bound keeps filesystem probing inside the engine's hook clamp.
    judged = 0
    seen3 = set()
    found = _Found()
    try:
        candidates = _outside_candidates(_strip_data_heredocs(cmd), cwd, found=found)
    except _Unmodelled as why:
        # Shell the lexer cannot read is UNENUMERATED: a scope request for the act, never a skip
        # (Codex re-review of #1232; dp, 2026-10-10). The reason travels in the refusal.
        if lift_unenum:
            return True, None, None
        return False, f"{_UNMODELLED_PREFIX}{why}>", UNENUMERATED_TARGET
    rels = [(s_, g_) for s_, k_, g_ in candidates if k_ == "rel"]
    if found.dirs_unknown and rels:
        found.unenum.append(f"a relative path after {found.dirs_unknown}")
    dir_bases = _dir_bases(found.dirs, cwd) if rels else []
    if dir_bases is None:
        found.unenum.append(f"more than {_MAX_DIR_BASES} directory changes")
        dir_bases = []
    # A relative path after a directory change is ALSO judged where it lands under it, strictly
    # (the Read rule, inside the workspace too): `cd /tmp && cat ../etc/x` reaches /etc/x.
    candidates = list(candidates) + [
        (os.path.normpath(os.path.join(b, s_)).replace("\\", "/"), "dir", g_)
        for b in dir_bases for s_, g_ in rels]
    for spelling, kind, globbed in candidates:
        if (spelling, kind, globbed) in seen3:
            continue                          # a repeated spelling is judged once
        seen3.add((spelling, kind, globbed))
        if judged >= SCOPE_JUDGE_BUDGET:
            # FAIL CLOSED (Codex review of #1232, P1-3): past the budget the classification is
            # INCOMPLETE, and incomplete is a refusal — never an allow of the unjudged rest.
            if lift_overflow:
                break
            return False, _INCOMPLETE, OVERFLOW_TARGET
        if kind == "dir":
            probe = _glob_probe(spelling) if globbed else spelling
            if _device_sink(spelling) or not _is_reach(probe.rstrip("*").rstrip("/") or "/"
                                                       if globbed else probe):
                continue
            judged += 1
            refused = _outside_reach_refused(probe, scopes, workspace, cwd, egress, home_markers)
            if refused is not None:
                return (False,) + refused
            continue
        if kind == "abs":
            cand = os.path.normpath(spelling).replace("\\", "/")
            if cand == ws or cand.startswith(ws + "/"):
                continue                      # inside: passes 1 and 2 own it
            # Only an UNQUOTED glob expands; a quoted `*` is a literal character of the name.
            probe = _glob_probe(cand) if globbed else cand
            if _device_sink(cand) or not _is_reach(probe.rstrip("*").rstrip("/") or "/"
                                                   if globbed else probe):
                continue
            judged += 1
            refused = _outside_reach_refused(probe, scopes, workspace, cwd, egress, home_markers)
            if refused is not None:
                return (False,) + refused
            continue
        # A relative spelling, voted like pass 2 over its plausible bases (the event cwd plus
        # every granted repo root): it is refused only when an interpretation that EXISTS lands
        # outside the workspace un-granted and no existing interpretation is in scope.
        in_scope, refused = False, None
        for base in bases:
            cand = os.path.normpath(os.path.join(base, spelling)).replace("\\", "/")
            probe = _glob_probe(cand) if globbed else cand
            if not _is_reach(probe.rstrip("*").rstrip("/") or "/"):
                continue
            if not os.path.lexists(os.path.dirname(probe.rstrip("*").rstrip("/")) or "/"):
                continue
            if cand == ws or cand.startswith(ws + "/"):
                seg = cand[len(ws):].lstrip("/").split("/", 1)[0]
                if seg and (seg in repo_scopes or _within_path_grant(cand, scopes, workspace)):
                    in_scope = True
                    break
                continue                      # an inside interpretation: pass 2's to refuse
            judged += 1
            r = _outside_reach_refused(probe, scopes, workspace, cwd, egress, home_markers)
            if r is None:
                in_scope = True
                break
            refused = refused or r
        if refused is not None and not in_scope:
            return (False,) + refused
    # Every literal candidate passed. What could not be enumerated is a scope REQUEST for the act
    # (never a silent allow): a blanket refusal, load-bearing, priced in the PR's measurement.
    if found.unenum and not lift_unenum:
        return False, f"{_UNMODELLED_PREFIX}{found.unenum[0]}>", UNENUMERATED_TARGET
    return True, None, None


#: Roots that are always reachable regardless of MRH — scratch space, not governed territory.
#: `/private/tmp` and `/private/var/tmp` are the Darwin destinations of the `/tmp` and
#: `/var/tmp` symlinks. Claude Code's macOS scratchpad is under `/private/tmp/...` after
#: resolution; a lexical-only `/tmp` list misses it (#1074).
TEMP_ROOTS = ("/tmp", "/var/tmp", "/private/tmp", "/private/var/tmp")


def _under_temp_root(path: str) -> bool:
    """Is this path the temp root itself, or a DESCENDANT of it?

    codex NOT-SAME review of #169, finding 2. The inherited check was
    `p.startswith(("/tmp", "/var/tmp"))`, which is a string-prefix test, not a path-boundary
    test — so `/tmp-other/x` and `/var/tmpsecrets/y` read as temporary. Those are SIBLINGS of
    the temp roots, and a directory anyone can create: a member could be handed unconditional
    reach by naming a directory, with no grant, no witness and no operator involved.

    Same defect class as the census's `reviewer ⊄ review`: a boundary rule implemented as a
    substring rule. The fix is the same shape — compare at the separator.

    On macOS, callers often hand an already-resolved path (`/private/tmp/...`). Those must
    still count as temp, while `/private/tmp-other` (a sibling of `/private/tmp`) must not."""
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
#: Tools whose path is only READ. The read-only floor admits these and nothing else. Each is
#: also a reader in the governance closure (`_READ_PATH_TOOLS`), which
#: tools/closure_read_tool_names_test.py pins: a tool the scope layer lets read a root must
#: not be one the closure treats as writing it.
READ_ONLY_PATH_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead",
                                  "read_file", "read_many_files", "glob",
                                  "search_file_content", "list_directory"})


#: Shell verbs that only read: no option and no operand of theirs names a file they write.
#: Deliberately tiny. The degraded mode's read grammar is NOT reused here: it admits verbs that
#: write through an option or an operand (`uniq IN OUT`, `sort -oFILE`, `git diff
#: --output=FILE`; Codex HOLD 28057 on this change, and the closure's copy of the hole is #1348).
#: Excluded on purpose: sed (its `w` command writes), awk, find (-fprint, -delete), sort, uniq,
#: git, tee, xargs, and every interpreter.
READ_ONLY_ROOT_VERBS = frozenset({"cat", "head", "tail", "grep", "wc", "ls", "stat"})


def _read_only_root_command(command: str) -> bool:
    """True iff every simple command in the line is a bare READ_ONLY_ROOT_VERBS verb, joined
    only by pipes or && / || / ;. Any redirect, substitution, heredoc, newline, background `&`,
    environment prefix or path-qualified verb makes it False: a miss refuses, never leaks."""
    if any(tok in command for tok in (">", "<", "$(", "`", "\n", "\r")):
        return False
    if "&" in command.replace("&&", ""):
        return False
    for chunk_or in command.split("||"):
        for chunk_and in chunk_or.split("&&"):
            for chunk_semi in chunk_and.split(";"):
                for seg in chunk_semi.split("|"):
                    words = seg.strip().split()
                    if not words:
                        continue
                    if words[0] not in READ_ONLY_ROOT_VERBS:
                        return False
    return True


def _read_only_admits(event: NormalizedEvent, p: str, read_scopes: list, ws: str,
                      profile: HarnessProfile) -> bool:
    """Does the read-only floor admit this path for this act? Only a reader tool, only
    inside a read-only root. No read-only roots means no."""
    return (bool(read_scopes) and event.tool in READ_ONLY_PATH_TOOLS
            and path_in_scope(p, read_scopes, ws, profile, event.cwd))


#: What the PATH of each tool's act needs, in grant modes (hestia #1345 part B). A narrowed
#: grant admits an act only when every mode listed here is in the grant's modes; a tool NOT
#: listed has no nameable mode and is admitted by full (rwed) grants alone, so an unknown or
#: new tool fails narrow. Deliberately per tool, not per argument:
#:   - every READ_ONLY_PATH_TOOLS reader needs r; so do a being's composed reads, whose `path`
#:     is their read target (the governance closure reads them the same way, _COMPOSED_READ_TOOLS);
#:   - Write / write_file create or replace and need w;
#:   - Edit-family tools read the old text to replace it, and answer with it, so they need rw;
#:   - write_note is a being's append, edit and retire alike (one gate tool for three verbs):
#:     w, since an append must work on a write-only grant; its edit receipt quotes the being's
#:     own old text back, never more of the file;
#:   - a being's git_restore rewrites a file from history (w); git_clean deletes one (d);
#:   - a being's run reads its script (to stage a copy) and executes it: re. Its event carries
#:     the script path only; what the run can reach inside its sandbox is mounted from the
#:     being's grants by their own modes on SAGE's side (SAGE #521), never by this table.
#: Shell commands are NOT classified here: see _command_mode_need.
PATH_TOOL_MODES = {
    **{t: "r" for t in READ_ONLY_PATH_TOOLS},
    "search": "r", "git_read": "r",
    "Write": "w", "write_file": "w",
    "Edit": "rw", "MultiEdit": "rw", "NotebookEdit": "rw", "replace": "rw",
    "write_note": "w",
    "git_restore": "w", "git_clean": "d",
    "run": "re",
}


def act_path_modes(event: NormalizedEvent) -> str:
    """The modes this act needs on each path it names, or "" when none can be named (then
    only a full grant admits it)."""
    return PATH_TOOL_MODES.get(event.tool, "")


def _command_mode_need(command: str) -> str:
    """The modes a shell command needs on every path it reaches: "r" for a command made only
    of READ_ONLY_ROOT_VERBS (the same strict allowlist the read-only floor uses), "" for every
    other command. Write, delete and execute positions inside a shell line are not attributed
    per path yet, so a command that does more than read is admitted by full grants alone: a
    narrowed grant never widens a command it cannot fully classify."""
    return "r" if _read_only_root_command(command) else ""


def _mode_entries(mode_scopes, need: str) -> list:
    """The narrowed grants whose modes include every mode in `need` ([] for an empty need)."""
    if not need:
        return []
    return [entry for entry, modes in mode_scopes if all(m in modes for m in need)]


def _mode_admits(event: NormalizedEvent, p: str, mode_scopes, ws: str,
                 profile: HarnessProfile) -> bool:
    """Does a narrowed grant admit this path for this act's modes?"""
    entries = _mode_entries(mode_scopes, act_path_modes(event))
    return bool(entries) and path_in_scope(p, entries, ws, profile, event.cwd)


def _mode_hint(p: str, need: str, mode_scopes, ws: str, profile: HarnessProfile,
               cwd: Optional[str]) -> str:
    """When a narrowed grant DOES reach the path but lacks a mode the act needs, say which:
    "granted r, this act needs w" (the refusal #1345 asks for). Empty otherwise."""
    held = "".join(sorted({m for entry, modes in mode_scopes
                           if path_in_scope(p, [entry], ws, profile, cwd) for m in modes},
                          key=GRANT_MODES.index))
    if not held:
        return ""
    wants = need or GRANT_MODES
    missing = "".join(m for m in wants if m not in held)
    what = (f"needs {wants}" if need else
            "has no mode the gate can name, so only a grant of all four modes (rwed) admits it")
    return (f" Your grant here is narrowed to {held}; this act {what}"
            + (f" (missing {missing})." if need else "."))


def scope_roots_with_modes(policy: AgentPolicy, workspace: str) -> tuple:
    """``((root, recursive, modes), ...)`` for every `path:` grant the policy holds: full
    grants as "rwed", narrowed ones with their modes (#1345 part B). For a consumer that
    confines an act itself after the gate (a dispatcher, a sandbox), so it honours the same
    modes the gate does.

    A NARROWED grant on a workspace-direct root arrives as a bare repo NAME
    (`_scope_entry_for_grant` maps a recursive grant on `<ws>/<name>` that way), and it is
    listed here as the recursive root `<ws>/<name>` with its modes. Leaving it out made the
    gate admit it while every consumer of this list refused it: cbp-being's `governance/**`
    is exactly that shape (nomad review of #1383, point 2). Every `mode_scope` entry comes
    from the daemon's grant rows, so a name here is always a grant. A FULL repo-name entry in
    `policy.scope` is still not listed: that list also carries declarative repo scope, and a
    consumer resolves granted names itself (SAGE `_repo_name_roots`)."""
    out = [(r, rec, GRANT_MODES) for r, rec in _scope_roots_with_reach(list(policy.scope), workspace)]
    ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/")
    for entry, modes in getattr(policy, "mode_scope", ()) or ():
        if entry.startswith("path:"):
            out += [(r, rec, modes) for r, rec in _scope_roots_with_reach([entry], workspace)]
        elif entry and "/" not in entry and "\\" not in entry and entry not in (".", "..", "*"):
            # Resolved like a `path:` root (realpath), so a repo that is a symlink on some
            # machine confines to the same place the gate's path check resolves.
            root = os.path.realpath(os.path.join(ws, entry)).replace("\\", "/").rstrip("/")
            if root:
                out.append((root, True, modes))
    return tuple(out)


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
    read_scopes = list(getattr(pol, "read_scope", ()) or ())
    mode_scopes = list(getattr(pol, "mode_scope", ()) or ())
    forbidden = forbidden_tokens(profile)

    # Gate 1a — innate egress/secret. Denied even inside a granted repo, always enforced.
    # Repo names are scanned too: an MCP call naming a forbidden token is still egress. So is
    # declared egress text (#1201), which Gate 1b below never scopes; egress it cannot read
    # whole is refused first, never passed unread.
    unswept = egress_unsweepable_deny(event)
    if unswept is not None:
        return unswept
    for blob in egress_blobs(event):
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
        fulls = list(getattr(event, "repo_full", None) or [])
        for i, rname in enumerate(event.repos):
            full = fulls[i] if i < len(fulls) and isinstance(fulls[i], str) else ""
            # #1392 v3: the legacy literal name keeps its (owner-agnostic) meaning; otherwise only a QUALIFIED
            # `repo:<owner>/<name>` grant reaches a remote repository. No local state stands in for it.
            if rname not in scopes and not _qualified_repo_granted(full, scopes):
                need = f"repo:{full}" if _qualified_repo(full) else f"repo:<owner>/{rname}"
                return _deny(
                    "mrh.repo",
                    f"'{event.tool}' targets repository '{full or rname}' outside your granted "
                    f"scope (granted: {'+'.join(scopes)}); a repository is reached only by a qualified "
                    f"grant '{need}' (a path grant, even recursive, does not reach a remote repository)",
                )
    for p in ([] if event.repos else event.paths):
        if (not path_in_scope(p, scopes, ws, profile, event.cwd)
                and not _read_only_admits(event, p, read_scopes, ws, profile)
                and not _mode_admits(event, p, mode_scopes, ws, profile)):
            # NAME THE SEGMENT, not just the path. The inherited hooks wrote `p[:60]`, which
            # on any long path truncates away the very component that tripped the gate — the
            # member is handed a string that does not contain its own reason. That is the
            # "a deny that hides its trigger sends the agent debugging blind" defect
            # (Codex live, 2026-07-23) reappearing inside the fix for it. Caught by
            # `deny_names_the_offending_target` once the test workspace moved off /tmp and
            # the paths got long enough to truncate.
            seg = _offending_segment(p, ws, event.cwd)
            # SAY WHY when the cause is the grant's shape, not its absence (2026-09-08).
            absolute = p if os.path.isabs(p) else os.path.join(event.cwd or ws, p)
            mode_hint = _mode_hint(p, act_path_modes(event), mode_scopes, ws, profile, event.cwd)
            # A narrowed grant that REACHES the path is a grant: the refusal must not open by
            # calling it "not granted" and then say it is narrowed (probe on #1383, point 2).
            where = ("a grant reaches it, but not in the mode this act needs" if mode_hint
                     else f"'{seg}' is not granted" if seg else "it is outside the workspace")
            hint = _exact_grant_hint(absolute, scopes, ws) + mode_hint
            lead = "beyond your grant's modes" if mode_hint else "outside your granted scope"
            return _deny(
                "mrh.path",
                f"'{event.tool}' targets '{_elide(p)}' {lead}: {where} "
                f"(granted: {'+'.join(scopes)}){hint}",
                target=os.path.normpath(os.path.expanduser(absolute)).replace("\\", "/"),
            )
    if event.command is not None:
        ok, offending, refused = command_scope_reach(event.command, scopes, ws, event.cwd,
                                                     forbidden=forbidden,
                                                     home_markers=profile.home_markers)
        # A command that only READS may also reach the read-only roots, by a strict verb
        # allowlist (READ_ONLY_ROOT_VERBS): anything outside it refuses rather than leaks.
        # And the narrowed grants that hold every mode the command needs (#1345 part B): for
        # now that is r for the same strict read-only allowlist, and nothing for any other
        # command. One retry over all of them, so a read crossing the floor and a narrowed
        # grant is judged as one act.
        cmd_need = _command_mode_need(event.command)
        extra = ((read_scopes if cmd_need == "r" else [])
                 + _mode_entries(mode_scopes, cmd_need))
        if not ok and extra:
            ok, offending, refused = command_scope_reach(
                event.command, scopes + extra, ws, event.cwd,
                forbidden=forbidden, home_markers=profile.home_markers)
        if not ok:
            # Name WHAT tripped the gate — a deny that hides its trigger sends the agent
            # debugging blind (Codex live session, 2026-07-23). The exact-grant hint is
            # judged on the path the checker actually refused — carried out of the check,
            # not rebuilt from the display token, which has the right repo and the wrong
            # depth (GPT review of #1003).
            unpriceable = bool(refused) and refused.startswith(UNPRICEABLE_PREFIX)
            hint = (_exact_grant_hint(refused, scopes, ws)
                    + _mode_hint(refused, cmd_need, mode_scopes, ws, profile, event.cwd)
                    if refused and not unpriceable else "")
            wsn = ws.replace("\\", "/").rstrip("/")
            outside = bool(refused) and not unpriceable and not (refused == wsn or
                                                                  refused.startswith(wsn + "/"))
            if offending == _INCOMPLETE:
                what = (f"the command names more than {SCOPE_JUDGE_BUDGET} distinct paths, so it "
                        f"could not be judged completely, and an incompletely judged command is "
                        f"refused — split it, or the act can be approved once as written")
            elif offending and offending.startswith(_UNMODELLED_PREFIX):
                # hestia#1313: its own rule, so nothing escalates (see REMEDIES).
                return _deny(
                    "mrh.command.unenumerated",
                    f"'{event.tool}' command: the gate cannot enumerate what it reaches "
                    f"({offending[len(_UNMODELLED_PREFIX):-1]}). Nothing an expansion produces is "
                    f"modelled, so no grant can cover it as written",
                    target=refused or "",
                )
            elif outside and _names_nothing(refused):
                # hestia#1327: its own rule, so nothing escalates (see REMEDIES).
                return _deny(
                    "mrh.command.nonexistent",
                    f"'{event.tool}' command reaches outside your granted scope: '{offending}' "
                    f"names nothing on disk (neither it nor its parent directory exists), so no "
                    f"grant could be about it (granted: {'+'.join(scopes)}){hint}",
                    target=refused,
                )
            elif outside:
                what = f"'{offending}' is outside the workspace and no grant reaches it"
            else:
                what = f"'{offending}' is not granted"
            return _deny(
                "mrh.command",
                f"'{event.tool}' command reaches outside your granted scope: {what} "
                f"(granted: {'+'.join(scopes)}){hint}",
                target=refused or "",
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
    unswept = egress_unsweepable_deny(event)
    if unswept is not None:
        return unswept
    for blob in egress_blobs(event):
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


def launch_role_verdict(permitted, live_role, source: str) -> tuple:
    """Whether a seat may act under the launch role it was given, against the permitted set its
    vault projection declares. Returns ``(miswire, verified)``: ``miswire`` is ``None`` or
    ``(rule, why)`` for the seat to render; ``verified`` is True only when a role was present AND
    checked against a declared set, so a reader can tell a verified role from an unbounded one.

    LAW, AND THEREFORE HERE (hestia #1084). The first cut put this inside the claude-code hook's
    projection loader and ledgered it as wiring; codex and kimi dissented that the predicate, the
    exemption and the refusal's words are law wherever they are rendered, and dp ruled
    2026-09-22: "only absolutely essential things go into shims. all law goes into shared engine."
    A seat hands this its projection's set and its launch role, and renders what comes back.

    Why a bound at all: the role decides WHICH LAW APPLIES. A launcher could supply any string, an
    unpublished one was silently normalised to `member` by the daemon (the 1140-outcomes split,
    PR #66), and on one machine the value came from a `${HESTIA_ROLE:-...}` default in a host file
    the governed seat can write (#943's pattern). The vault declares which roles a seat MAY launch
    under; the launcher still chooses among them.

    An absent role is deliberately NOT refused. Refusing it would deny every seat whose launcher
    never set one; converting the launchers belongs in its own change. It reads as unverified.
    (The first cut compared an absent role, "", against the set and refused it -- GPT on #1084.)
    No declared set: nothing to check, unverified, today's behaviour unchanged.
    """
    if isinstance(permitted, str):
        permitted = permitted.split(",")
    allowed = [str(r).strip() for r in (permitted or []) if str(r).strip()]
    role = str(live_role or "")
    if allowed and role and role not in allowed:
        return (("config.miswired",
                 f"this seat was launched as HESTIA_ROLE={role!r} but {source} permits only "
                 f"{allowed}; the role decides which law applies, so an unlisted one is refused "
                 f"here rather than normalised downstream"), False)
    return (None, bool(allowed and role))
