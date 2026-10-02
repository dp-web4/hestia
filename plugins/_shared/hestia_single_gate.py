"""The one Hestia gate orchestrator: `decide(GateEvent, GateProfile) -> GateDecision`.

One-gate stage B (docs/one-gate-convergence-plan.md §3). ADDITIVE AND UNWIRED: no seat calls
this module yet, and it is not in RUNTIME_MANIFEST.txt, so the installer does not deploy it.
Stage C replaces each seat's gate with the certified template, whose `main` calls `decide()`.

A harness shim translates syntax into a GateEvent, calls `decide()`, and renders the
GateDecision in its harness's blocking protocol. It does not sequence governance. Everything
law-bearing is here, in ONE sequence, in this order:

   1. closure    the governance closure: a read is witnessed; a write needs a human approval
                 claimed with this call's invocation key, else `gate.self_access` (innate);
   2. egress     innate `egress.secret` over the egress surfaces the core's paths/command do
                 not cover (web-tool urls/prompts/queries, the MCP transport context);
   3. snapshot   the policy snapshot; when it cannot be fetched, the ratified degraded mode;
   4. law        `core.evaluate` (innate denies always; tunable denies follow the rollout);
   5. read class allow without the daemon (the ratified read posture);
   6. society    `mechanism.query_society_safety(..., correlation_key=KEY)` — the ONLY writer
                 of the action cache (C13). A superseded invocation is denied in EVERY mode;
   7. finalize   `mechanism.record_decision(...)` for the final verdict, and nothing else
                 records it. A consequential permit whose receipt is not committed becomes
                 `gate.evidence_uncommitted` (C11), in every rollout mode.

THREE INVARIANTS, each tested in tools/one_gate_decide_contract_test.py:

ONE DEADLINE. `decide()` takes one absolute deadline, GATE_DEADLINE_SECONDS (3 s) after it
starts, under the shortest measured harness clamp (4 s). The phases (gate-self, snapshot,
society) must finish by `deadline - WITNESS_RESERVE_SECONDS`, so the final record keeps its own
slice of the same deadline; `record_decision` takes the deadline itself (stage A). A phase that
does not answer in time is a no-verdict, which fails closed.

STAGE B'S DEADLINE IS COARSE, ON PURPOSE. B does not touch the deployed mechanism (dp,
2026-10-01: B must stay approvable without the sovereign bar), so `query_society_safety`,
`fetch_policy_snapshot` and the gate-self calls still mint their own budgets. `decide()` bounds
them from OUTSIDE: each runs in a daemon thread that is waited on only for the time the
invocation has left (`_bounded`), and a call that has not returned by then is abandoned and
read as a no-verdict. The harness sees the bound; the daemon may still see the abandoned request
arrive late (a begin_action recorded, a snapshot fetched for nobody). Stage C threads an
explicit `deadline=` through those helpers so that no request STARTS after the deadline, and
`_bounded` becomes a belt (plan §4).

MEASURED CAVEAT (stage A): a cold DEBUG daemon took 4.4 s for its first society-safety round
trip, so the first consequential act after a cold daemon start is denied `society.unreachable`
under this deadline; the retry succeeds. That is the deadline doing its job, and the contract
suite pins it.

ONE KEY. `correlation_key(event.raw)` is computed ONCE, from the RAW harness event (C13): a
normalized event loses gemini's `source_event` and kimi's `tool_call_id`. The same key goes to
`claim_self_write` (invocation key, #1169), `query_society_safety` and `record_decision`.
What the daemon is ASKED about is the translated act (`event.tool`/`event.tool_input`): the
daemon's law and target extraction speak lineage tool names, and a raw gemini
`run_shell_command` would reach it with no target (plan §3 step 8 deviation, recorded in the
plan doc).

NO PRIVATE STATE. No action cache, no MCP client, no recorder of its own: the shared outcome
witness owns the cache, the mechanism owns transport, `record_decision` owns the record.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import hestia_gate_core as core
import hestia_gate_mechanism as mechanism
import hestia_governance_closure as closure

GATE_API_VERSION = "decide/1"

#: The one invocation deadline (plan §3 step 1): under the shortest measured harness clamp (4 s).
GATE_DEADLINE_SECONDS = 3.0
#: The tail of that deadline kept for the final decision record. The phases before it are
#: bounded by `deadline - WITNESS_RESERVE_SECONDS`; the record itself by the deadline.
WITNESS_RESERVE_SECONDS = 0.5

#: The rollout knob. ONE name for every seat (the per-seat HESTIA_<SEAT>_GATE_MODE names are
#: stage C's projection work). Anything other than exactly "warn" is enforce: an unreadable
#: rollout fails tight.
ROLLOUT_ENV = "HESTIA_GATE_MODE"
ROLLOUTS = ("enforce", "warn")

#: Rules this module mints that the core's REMEDIES table does not carry. Rendered from here,
#: never at a call site; stage C may move them into the core table.
GATE_REMEDIES = {
    "invocation.superseded": (
        "This call's approval was re-delivered to another invocation of the same act. Do not "
        "retry this call; the invocation that reclaimed the approval carries it."),
    "gate.evidence_uncommitted": (
        "The gate reached a permit but could not commit its decision record before the "
        "deadline, and a consequential act may not run unwitnessed (C11). This is not a "
        "judgement of the act: retry once the daemon's witness path is answering."),
    "gate.internal_error": (
        "This is an infrastructure fault in the gate, not a judgement of the attempted act. "
        "The gate fails closed until the decision path is healthy; please report it."),
}


@dataclass(frozen=True)
class GateProfile:
    """Harness facts only. No law and no enforcement posture belongs here."""

    member_id: str
    identity_path: str
    home_markers: tuple = ()
    launch_cwd_env: str = ""
    workspace_env: str = "HESTIA_WORKSPACE"
    forbidden_extra_env: str = "HESTIA_FORBIDDEN_EXTRA"
    default_role: str = "role:constellation:member"
    host_agent: str = ""
    client_name: str = ""
    gate_path: str = ""
    observe_dir: str = ""
    attest_every: int = 200
    #: Harness capability, not law: only a seat that holds the review effector says so (#1050).
    declares_review_door: bool = False

    def core_profile(self) -> core.HarnessProfile:
        return core.HarnessProfile(
            member_id=self.member_id,
            identity_path=self.identity_path,
            home_markers=tuple(m for m in self.home_markers if m),
            launch_cwd_env=self.launch_cwd_env,
            mode_env="",   # the rollout is read here, once, never per seat
            workspace_env=self.workspace_env,
            forbidden_extra_env=self.forbidden_extra_env,
            default_role=self.default_role,
        )


@dataclass
class GateEvent:
    """One harness event, translated. `raw` is the harness's event exactly as received."""

    tool: str
    tool_input: dict = field(default_factory=dict)
    cwd: Optional[str] = None
    session_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GateDecision:
    """The final verdict. `blocks` is the only field a shim acts on; the rest it renders."""

    decision: str                         # allow | warn | deny
    rule: str = ""
    reason: str = ""
    remedy: str = ""
    verdict_available: bool = True        # False: infrastructure, never member conduct
    innate: bool = False                  # not relaxable by rollout or grant
    anomaly: bool = False                 # the gate could not do its job (render as anomaly)
    action_id: Optional[str] = None
    correlation_key: Optional[str] = None
    escalation_id: Optional[str] = None
    rollout: str = "enforce"
    warnings: tuple = ()                  # (rule, reason) pairs a warn-rollout let through
    notices: tuple = ()                   # informational lines (an approved closure write)
    evidence_committed: bool = False
    receipt_status: str = ""              # the record_decision status of THIS verdict
    supersedes_uncommitted: Optional[str] = None  # the permit gate.evidence_uncommitted replaced

    @property
    def blocks(self) -> bool:
        return self.decision == "deny"


# ── invocation context ───────────────────────────────────────────────────────────────────────

@dataclass
class _Invocation:
    event: GateEvent
    profile: GateProfile
    rollout: str
    deadline: float
    key: Optional[str]
    attempted: str = ""
    role: Optional[str] = None
    notices: list = field(default_factory=list)
    warnings: list = field(default_factory=list)   # [(rule, reason, verdict_available)]

    @property
    def phase_deadline(self) -> float:
        return self.deadline - WITNESS_RESERVE_SECONDS

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


_LATE = object()


def _bounded(end: float, fn, *args, **kwargs):
    """Run one mechanism call and wait for it only until `end` (a `time.monotonic()` bound).

    Returns the call's value, or `_LATE` when there was no time to start it or it had not
    returned by `end`. A call that raises re-raises here. The worker is a daemon thread, so an
    abandoned call never holds the hook process open (see "coarse" in the module docstring)."""
    remaining = end - time.monotonic()
    if remaining <= 0:
        return _LATE
    box: dict = {}

    def _bounded_worker():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — carried to the caller
            box["error"] = exc

    worker = threading.Thread(target=_bounded_worker, name="hestia-decide-bounded", daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        return _LATE
    if "error" in box:
        raise box["error"]
    return box.get("value")


def rollout_of(explicit: Optional[str] = None) -> str:
    """The rollout for this invocation: `explicit`, else HESTIA_GATE_MODE; enforce unless "warn"."""
    value = explicit if explicit is not None else os.getenv(ROLLOUT_ENV, "")
    return "warn" if str(value).strip().lower() == "warn" else "enforce"


# ── act description: translation-independent facts the sequence reads ────────────────────────

def _shell_tool(tool: str) -> bool:
    return isinstance(tool, str) and tool.lower() in ("bash", "shell")


def _command_text(tool_input: Any) -> Optional[str]:
    value = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(value, str):
        return value
    if isinstance(value, list):    # an argv list (codex's shell tool may send one)
        return " ".join(str(x) for x in value)
    return None


def _patch_targets(tool: str, tool_input: Any) -> list:
    """apply_patch's targets live in its diff body: `*** Add|Update|Delete File: <path>`."""
    if not (isinstance(tool, str) and tool.lower() == "apply_patch") or not isinstance(tool_input, dict):
        return []
    blob = next((tool_input[k] for k in ("input", "command", "patch")
                 if isinstance(tool_input.get(k), str)), "")
    return [m.group(1) for m in re.finditer(
        r"^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$", blob, re.MULTILINE)]


def _mcp_repo(tool: str, tool_input: Any) -> Optional[str]:
    if not (isinstance(tool, str) and tool.startswith("mcp__")) or not isinstance(tool_input, dict):
        return None
    for key in ("repository_full_name", "repo_full_name", "repository", "repo"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/").split("/")[-1]
    return None


def normalized_event(event: GateEvent) -> core.NormalizedEvent:
    """The core's view of the act. An apply_patch body is CONTENT: its targets are scoped,
    the body is never scanned as a command (the 2026-07-23 review false-deny class)."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    patch = _patch_targets(event.tool, ti)
    paths = [p for p in core.path_targets(event.tool, ti) + patch if isinstance(p, str) and p]
    repo = _mcp_repo(event.tool, ti)
    return core.NormalizedEvent(
        tool=event.tool,
        paths=list(dict.fromkeys(paths)),
        repos=[repo] if repo else [],
        command=None if patch or (isinstance(event.tool, str) and event.tool.lower() == "apply_patch")
        else _command_text(ti),
        cwd=event.cwd,
        raw=event.raw if isinstance(event.raw, dict) else {},
    )


def _leaves(value: Any, depth: int = 0) -> list:
    if isinstance(value, str):
        return [value]
    if depth > 4:
        return []
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _leaves(v, depth + 1)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _leaves(v, depth + 1)]
    return []


_WEB_TOOLS = ("webfetch", "websearch", "web_fetch", "google_web_search")


def egress_surfaces(event: GateEvent) -> list:
    """Egress strings the core's paths/command do not carry: a web tool's url/prompt/query and
    the MCP transport context a shim lifts into `tool_input["_hestia_mcp_context"]`."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    out: list = []
    if isinstance(event.tool, str) and event.tool.lower() in _WEB_TOOLS:
        for key in ("url", "urls", "prompt", "query"):
            out.extend(_leaves(ti.get(key)))
    ctx = ti.get("_hestia_mcp_context")
    if isinstance(ctx, dict):
        for key in ("command", "args", "url", "cwd"):
            out.extend(_leaves(ctx.get(key)))
    return out


def attempted_of(event: GateEvent, limit: int = 400) -> str:
    """The bounded, credential-masked WHAT behind a verdict (the mechanism's one masker)."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    raw: Any = _command_text(ti) or ti.get("file_path") or ti.get("path") or ""
    if not raw and ti:
        try:
            raw = json.dumps(ti, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            raw = str(ti)
    text = mechanism._mask_credential_values(" ".join(str(raw).split()))
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")


def _target(event: GateEvent) -> Optional[str]:
    try:
        return mechanism._extract_target(event.tool_input, event.tool)
    except Exception:  # noqa: BLE001
        return None


def _role(inv: _Invocation, snapshot_role: Optional[str] = None) -> str:
    try:
        return mechanism.role_bridge(snapshot_role=snapshot_role,
                                     identity_path=inv.profile.identity_path)
    except Exception:  # noqa: BLE001
        return inv.profile.default_role


def _client_name(profile: GateProfile) -> str:
    return profile.client_name or f"hestia-{profile.member_id}-gate"


# ── the record: ONE call, every final verdict ────────────────────────────────────────────────

def _record(inv: _Invocation, d: GateDecision, attempted: Optional[str] = None):
    return mechanism.record_decision(
        None,
        plugin_id=inv.profile.member_id,
        decision=d.decision,
        rule=d.rule,
        tool_name=inv.event.tool or "",
        target=_target(inv.event),
        session_id=inv.event.session_id,
        verdict_available=d.verdict_available,
        attempted_summary=attempted if attempted is not None else inv.attempted,
        action_id=d.action_id,
        correlation_key=inv.key,
        deadline=inv.deadline,
    )


def _tally(inv: _Invocation, allowed: bool) -> None:
    observe = inv.profile.observe_dir
    if not observe:
        return
    try:
        tally_dir = os.path.expanduser(observe)
        # Accounting, bounded by the same deadline: once per window it attests over the wire.
        _bounded(inv.deadline, mechanism.tally_scope, allowed, tally_dir=tally_dir,
                              tally_path=os.path.join(tally_dir, "scope-tally.json"),
                              attest_every=inv.profile.attest_every,
                              plugin_id=inv.profile.member_id,
                              role_lct=inv.role or _role(inv))
    except Exception:  # noqa: BLE001 — accounting never changes a decision
        pass


def _finalize(inv: _Invocation, d: GateDecision, *, consequential: bool) -> GateDecision:
    """Record the final verdict and apply C11. The ONLY place a verdict is recorded."""
    d = replace(d, rollout=inv.rollout, correlation_key=inv.key,
                notices=tuple(inv.notices) + tuple(d.notices))
    receipt = _record(inv, d)
    if consequential and d.decision in ("allow", "warn") and not receipt.committed:
        # STATE MUST NOT OUTRUN ITS EVIDENCE (C11, "no class is exempt"): the permit becomes a
        # denial in EVERY rollout mode, and that denial names the verdict it replaced. It goes
        # through the same recorder; it may itself fail to commit (the deadline is shared), and
        # then it is a denial without evidence, which is the safe direction.
        denied = replace(
            d, decision="deny", rule="gate.evidence_uncommitted",
            reason=(f"the gate reached '{d.decision}' ({d.rule}) but its decision record did not "
                    f"commit before the deadline ({receipt.status}: {receipt.detail})"),
            remedy=GATE_REMEDIES["gate.evidence_uncommitted"],
            verdict_available=False, anomaly=True, innate=True,
            supersedes_uncommitted=d.decision)
        second = _record(inv, denied, attempted=(
            f"[supersedes uncommitted {d.decision}:{d.rule}] {inv.attempted}")[:400])
        _tally(inv, False)
        return replace(denied, evidence_committed=second.committed,
                       receipt_status=second.status)
    _tally(inv, d.decision != "deny")
    if receipt.committed:
        return replace(d, evidence_committed=True, receipt_status=receipt.status)
    # A denial stays a denial without evidence; a read keeps the ratified posture and says so.
    return replace(d, evidence_committed=False, receipt_status=receipt.status,
                   anomaly=d.anomaly or d.decision != "deny")


def _verdict_deny(v: core.Verdict, **kw) -> GateDecision:
    return GateDecision("deny", v.rule, v.reason, v.remedy, innate=bool(v.innate), **kw)


def _permit(inv: _Invocation, rule: str, *, action_id: Optional[str] = None,
            message: str = "", verdict_available: bool = True,
            anomaly: bool = False) -> GateDecision:
    """allow, or warn when the rollout let one or more boundaries through."""
    if not inv.warnings:
        return GateDecision("allow", rule, message, verdict_available=verdict_available,
                            anomaly=anomaly, action_id=action_id)
    first_rule, first_reason, _ = inv.warnings[0]
    available = verdict_available and all(w[2] for w in inv.warnings)
    return GateDecision(
        "warn", first_rule,
        "; ".join(f"[{r}] {why}" for r, why, _ in inv.warnings),
        "warn-rollout: allowed; would block under enforce" if inv.rollout == "warn" else "",
        verdict_available=available, anomaly=anomaly, action_id=action_id,
        warnings=tuple((r, why) for r, why, _ in inv.warnings))


# ── the sequence ─────────────────────────────────────────────────────────────────────────────

def _closure_view(event: GateEvent):
    """The closure classifier's verdict on this act. Tool-shape adaptation only: a lowercase
    shell tool or an argv list is the Bash form; an apply_patch is one Write per target."""
    tool, ti = event.tool, event.tool_input if isinstance(event.tool_input, dict) else {}
    targets = _patch_targets(tool, ti)
    if targets or (isinstance(tool, str) and tool.lower() == "apply_patch"):
        found = None
        for p in targets:
            cv = closure.classify("Write", {"file_path": p}, cwd=event.cwd)
            if cv.classification == "write":
                return cv
            if cv.classification == "read" and found is None:
                found = cv
        return found
    if _shell_tool(tool) and tool not in ("Bash", "Shell"):
        tool = "Bash"
    if _shell_tool(tool) and not isinstance(ti.get("command"), str):
        ti = dict(ti, command=_command_text(ti) or "")
    return closure.classify(tool, ti, cwd=event.cwd)


def _governance_closure(inv: _Invocation) -> Optional[GateDecision]:
    ev, prof = inv.event, inv.profile
    cv = _closure_view(ev)
    if cv is None or cv.classification not in ("read", "write"):
        return None
    marker = cv.marker or cv.rule or "governance"
    if cv.classification == "read":
        # Publish-the-law: a member may read what governs it. Recorded as its own class.
        try:
            _bounded(inv.phase_deadline, mechanism.witness_gate_self,
                     "gate_self_read", marker, ev.tool, cv.rule, plugin_id=prof.member_id,
                     role=_role(inv), gate_path=prof.gate_path or "",
                     client_name=_client_name(prof), host_session_id=ev.session_id)
        except Exception:  # noqa: BLE001
            pass
        return None
    try:
        claimed = _bounded(
            inv.phase_deadline, mechanism.claim_self_write,
            marker, ev.tool, inv.attempted, plugin_id=prof.member_id, role=_role(inv),
            client_name=_client_name(prof), host_session_id=ev.session_id,
            invocation_key=inv.key,
            # THIS module stops a superseded invocation in every rollout mode (step 6), so it
            # may make the declaration that lets the daemon reclaim a lost answer (#1169).
            supersession=mechanism.SUPERSESSION_HARD_STOP)
        if claimed is _LATE:
            # Unknown, not "nothing happened": the daemon may have opened or matched an
            # escalation after the bound (#1166). Re-issuing the identical act is safe.
            claimed = ("unknown", "OUTCOME UNKNOWN — the claim did not answer inside the gate's "
                       "deadline; re-issuing this identical act is safe", None, None)
        verdict, detail, esc_id, how = claimed
    except Exception:  # noqa: BLE001 — every failure is a refusal
        verdict, detail, esc_id, how = "unreachable", "no answer from the daemon — refused", None, None
    if verdict == "approved":
        # Approval lifts the closure bar for THIS call only; ordinary law still runs below.
        inv.notices.append(f"hestia: gate write APPROVED — {detail}")
        return None
    try:
        _bounded(inv.phase_deadline, mechanism.witness_gate_self,
                 "gate_self_access", marker, ev.tool, cv.rule, plugin_id=prof.member_id,
                 role=_role(inv), gate_path=prof.gate_path or "",
                 client_name=_client_name(prof), host_session_id=ev.session_id)
    except Exception:  # noqa: BLE001
        pass
    esc = (f" Escalation {esc_id} is open — a human decides out of band ({how}); re-issue the "
           f"write afterwards to claim the approval." if esc_id else "")
    v = core._deny("gate.self_access",
                   f"'{ev.tool}' would WRITE the governance surface: {cv.resource or marker} "
                   f"(matched marker {marker!r}; rule {cv.rule or 'gate-self'}; {detail}).{esc}",
                   innate=True)
    return _verdict_deny(v, escalation_id=esc_id)


def _egress_precheck(inv: _Invocation, cprofile: core.HarnessProfile) -> Optional[GateDecision]:
    forbidden = core.forbidden_tokens(cprofile)
    for blob in egress_surfaces(inv.event):
        low = blob.lower()
        for token in forbidden:
            if token in low:
                return _verdict_deny(core._deny(
                    "egress.secret",
                    f"'{inv.event.tool}' carries a forbidden secret/credential token through an "
                    f"egress surface: '{token}'", innate=True))
    return None


def _local_law(inv: _Invocation, nev: core.NormalizedEvent,
               cprofile: core.HarnessProfile) -> tuple:
    """(decision-or-None, degraded). Snapshot, then the core's law or its degraded mode."""
    prof = inv.profile
    try:
        snapshot = _bounded(
            inv.phase_deadline, mechanism.fetch_policy_snapshot,
            prof.member_id, host_agent=prof.host_agent or prof.member_id,
            host_session_id=inv.event.session_id,
            declares_review_door=prof.declares_review_door)
    except Exception:  # noqa: BLE001 — an unusable mechanism is an unreachable daemon
        snapshot = None
    if snapshot is _LATE or not isinstance(snapshot, dict):
        snapshot = None
    workspace = core.detect_workspace(cprofile)
    if snapshot is not None:
        role = snapshot.get("role") if isinstance(snapshot, dict) else None
        inv.role = _role(inv, role if isinstance(role, str) else None)
        policy = core.resolve_agent_policy(cprofile, vault_reader=lambda _member: snapshot)
        v = core.evaluate(nev, cprofile, workspace, policy=policy)
        if v.blocks:
            if v.innate or inv.rollout == "enforce":
                return _verdict_deny(v), False
            inv.warnings.append((v.rule, v.reason, True))
        return None, False
    if inv.rollout == "enforce":
        # THE RATIFIED DEGRADED MODE (deny writes, allow reads), computed by the core.
        v = core.degraded_verdict(nev, cprofile)
        if v.blocks:
            return _verdict_deny(v, verdict_available=bool(v.innate),
                                 anomaly=not v.innate), True
        try:
            core.record_gate_unavailable(prof.member_id, inv.event.tool, "unknown",
                                         "degraded: policy snapshot fetch failed (allow-read)")
        except Exception:  # noqa: BLE001
            pass
        return None, True
    # Warn-rollout with no snapshot: a policy that grants NOTHING (never a replica), so every
    # boundary surfaces as a warning and innate ones still deny.
    policy = core.AgentPolicy(member_id=prof.member_id, scope=(),
                              source="daemon-unreachable", stale=True)
    v = core.evaluate(nev, cprofile, workspace, policy=policy)
    if v.blocks:
        if v.innate:
            return _verdict_deny(v), True
        inv.warnings.append((v.rule, v.reason, False))
    return None, True


def _society(inv: _Invocation) -> GateDecision:
    ev, prof = inv.event, inv.profile
    try:
        safety = _bounded(
            inv.phase_deadline, mechanism.query_society_safety,
            # The TRANSLATED act: the daemon's law and target extraction speak lineage names.
            {"tool_name": ev.tool, "tool_input": ev.tool_input if isinstance(ev.tool_input, dict) else {}},
            plugin_id=prof.member_id,
            host_agent=prof.host_agent or prof.member_id,
            host_session_id=ev.session_id,
            correlation_key=inv.key)   # from the RAW event, computed once (C13)
        if safety is _LATE:
            safety = mechanism.SafetyVerdict(
                allow=False, decided=False, cause="timeout",
                message=("hestia: no verdict [fail-closed] — the society-safety check did not "
                         "answer inside the gate's deadline (cause=timeout). The daemon is most "
                         "likely ALIVE BUT LOADED or cold: wait and retry with backoff."))
    except Exception as exc:  # noqa: BLE001 — the mechanism never raises; belt anyway
        safety = mechanism.SafetyVerdict(allow=False, decided=False, cause="unknown",
                                         message=f"society-safety mechanism failed: {type(exc).__name__}")
    if getattr(safety, "superseded", False):
        # An INTEGRITY fence, not a policy verdict (#1169): a stop in EVERY rollout mode, or
        # this call runs beside the invocation that reclaimed its approval.
        return GateDecision("deny", "invocation.superseded", safety.message,
                            GATE_REMEDIES["invocation.superseded"],
                            verdict_available=False, innate=True)
    if not safety.allow:
        if safety.decided:
            if inv.rollout == "enforce":
                return GateDecision("deny", "society.safety",
                                    safety.message or "society law refused the act",
                                    core.REMEDIES["society.safety"].text,
                                    action_id=safety.action_id)
            inv.warnings.append(("society.safety", safety.message or "society law refused the act",
                                 True))
            return _permit(inv, "society.safety", action_id=safety.action_id)
        if inv.rollout == "enforce":
            return GateDecision("deny", "society.unreachable",
                                safety.message or "no usable society-safety verdict",
                                core.REMEDIES["society.unreachable"].text,
                                verdict_available=False, anomaly=True,
                                action_id=safety.action_id)
        inv.warnings.append(("society.unreachable",
                             safety.message or "no usable society-safety verdict", False))
        return _permit(inv, "society.unreachable", verdict_available=False, anomaly=True)
    if safety.kind == "warn":
        inv.warnings.append(("society.safety.warn", safety.message or "", True))
    return _permit(inv, "gate.allow", action_id=safety.action_id, message=safety.message or "")


def _sequence(inv: _Invocation) -> GateDecision:
    cprofile = inv.profile.core_profile()

    d = _governance_closure(inv)
    if d is not None:
        return _finalize(inv, d, consequential=False)

    d = _egress_precheck(inv, cprofile)
    if d is not None:
        return _finalize(inv, d, consequential=False)

    nev = normalized_event(inv.event)
    d, degraded = _local_law(inv, nev, cprofile)
    if d is not None:
        return _finalize(inv, d, consequential=False)

    if nev.tool in core.READ_CLASS:
        if degraded and inv.rollout == "enforce":
            # DIVERGENCE for claude-code (needs dp's ruling): today that seat asks the daemon
            # about reads too, so a degraded Read is a no-verdict deny there. Here it takes the
            # ratified degraded posture, as kimi and codex do.
            return _finalize(inv, GateDecision(
                "allow", "gate.degraded.allow_read",
                "read permitted by the ratified degraded posture (policy snapshot unavailable)",
                verdict_available=False, anomaly=True), consequential=False)
        return _finalize(inv, _permit(inv, "gate.allow"), consequential=False)

    # Write/exec class (a degraded read-only shell command included: every seat asks the
    # governor about it today, and the snapshot failing does not prove the daemon is down).
    return _finalize(inv, _society(inv), consequential=True)


def decide(event: GateEvent, profile: GateProfile, *, rollout: Optional[str] = None) -> GateDecision:
    """The one law-bearing sequence for every harness. NEVER raises."""
    deadline = time.monotonic() + GATE_DEADLINE_SECONDS
    mode = rollout_of(rollout)
    inv: Optional[_Invocation] = None
    try:
        if not isinstance(event, GateEvent):
            raise TypeError("decide requires a GateEvent")
        if not isinstance(profile, GateProfile):
            raise TypeError("decide requires a GateProfile")
        inv = _Invocation(event=event, profile=profile, rollout=mode, deadline=deadline,
                          key=mechanism.correlation_key(event.raw))
        inv.attempted = attempted_of(event)
        return _sequence(inv)
    except BaseException as exc:  # noqa: BLE001 — a gate that cannot decide must not allow
        detail = f"{type(exc).__name__}: {exc}"[:300]
        d = GateDecision(
            "deny" if mode == "enforce" else "warn", "gate.internal_error",
            "the common gate could not complete the decision: " + detail,
            GATE_REMEDIES["gate.internal_error"],
            verdict_available=False, anomaly=True, rollout=mode,
            warnings=(() if mode == "enforce" else (("gate.internal_error", detail),)))
        if inv is None:
            return d
        try:
            # A warn-rollout permit of a write/exec act is still a permit: C11 applies.
            return _finalize(inv, d, consequential=event.tool not in core.READ_CLASS)
        except BaseException:  # noqa: BLE001
            return d
