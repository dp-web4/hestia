# hestia-gt-sha256: c42f240b5ddc1d2bce3cfa90232593ae0d624a478389fb8a39d5c515e9b3347f  (published ground truth; manifest: hooks-gt)
"""The one Hestia gate orchestrator: `decide(GateEvent, GateProfile) -> GateDecision`.

One-gate stage C (docs/one-gate-convergence-plan.md §4): THE GATE OF EVERY SEAT. Each seat's
hook (claude-code, codex, kimi: `hooks/pre_tool_use.py`; gemini: `hooks/before_tool.py`) is the
certified template (`plugins/_template/shim_template.py`): it translates its harness's event into
a GateEvent, asks `harness_bound()` for the deadline its harness's REAL registered timeout allows,
calls `decide()`, and renders the GateDecision in its harness's blocking protocol. It does not
sequence governance. Everything law-bearing is here, in ONE sequence, in this order:

   0. launch     the seat's launch role against the roles its vault projection permits (#1084);
   1. closure    the governance closure: a read is witnessed; a write needs a human approval
                 claimed with this call's invocation key, else `gate.self_access` (innate);
   2. egress     innate `egress.secret` over the egress surfaces the core's paths/command do
                 not cover (web-tool urls/prompts/queries, the MCP transport context);
   3. snapshot   the policy snapshot; with none, every act is DENIED (gate.degraded), reads
                 included, in EVERY rollout mode — an integrity precondition, not a policy view;
   4. law        `core.evaluate`, plus command scope over the MCP transport context (innate
                 denies always; tunable denies follow the rollout);
   5. society    `mechanism.query_society_safety(..., correlation_key=KEY)` for EVERY act, reads
                 included (dp 2026-10-01: align upward to claude-code's posture) — the ONLY
                 writer of the action cache (C13). A superseded invocation, and a society
                 check that returns NO verdict (`society.unreachable`), are denied in EVERY
                 mode — no verdict, no act; an internal error (`gate.internal_error`) likewise;
   6. finalize   `mechanism.record_decision(...)` for the final verdict, and nothing else
                 records it. A consequential permit whose receipt is not committed becomes
                 `gate.evidence_uncommitted` (C11), in every rollout mode.

THREE INVARIANTS, each tested in tools/one_gate_decide_contract_test.py:

ONE DEADLINE, THE SHIM'S, ALWAYS BELOW THE HARNESS'S. A seat's shim passes `bound=` (from
`harness_bound()`): the deadline is the hook process's start plus the timeout its harness
ACTUALLY enforces, read from the live registration, minus the harness's declared margin — never
a default or a template (dp 2026-10-02, the safety invariant). So whatever the registration
says, `decide()` finishes — and fails CLOSED on a slow or cold daemon — before the harness can
kill the hook and fail OPEN. A registration that cannot be read is `gate.harness_timeout_unknown`,
denied at once and without a daemon round trip: with no known bound, any wait could outlive the
harness. A caller that is not a seat (a test, a probe) may pass `deadline=`/`budget_seconds=`;
with neither, DEFAULT_DEADLINE_SECONDS. The phases (gate-self, snapshot, society) must finish by
`deadline - WITNESS_RESERVE_SECONDS`, so the final record keeps its own slice of the same deadline.

THE DEADLINE IS THREADED, AND STILL BELTED. Since stage C every mechanism helper takes the
deadline itself (`deadline=`), so no request STARTS after it. Each call still runs in a daemon
thread waited on only for what the invocation has left (`_bounded`): a belt, so a helper that
overruns its own bound cannot hold the hook past the harness's timeout.

COLD START. A daemon's first act after start, and a never-seen member's first connect, cost
~4.6-5.1 s (measured). A registration of at least 10 s (every template) absorbs one such leg
inside the margin; `deploy/daemon-warmup.sh` warms every rostered member at daemon start, so
most cold connects are paid there. A shorter registration costs availability (a cold connect
becomes a recorded no-verdict deny), never safety.

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
import shlex
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import hestia_gate_core as core
import hestia_gate_mechanism as mechanism
import hestia_governance_closure as closure

#: decide/2 (stage C): `decide(..., bound=, permitted_roles=)`, `harness_bound()` and `render()`
#: are the shim contract. The template's REQUIRED_GATE_API must equal this.
GATE_API_VERSION = "decide/2"

# ── THE DEADLINE IS THE CALLER'S ────────────────────────────────────────────────────────────
# dp, 2026-10-01: "one gate is law. shims are there to match the interface to peculiarities of
# each harness, timeouts being prime example." How long a harness waits for its hook, and what
# it does when the wait runs out, is a harness fact: each seat's shim declares where its harness
# records the registered timeout (its HARNESS data) and `harness_bound()` reads the real value.
#
# DEFAULT_DEADLINE_SECONDS is a DEFAULT for a caller that passes nothing (a test, a probe), not
# law, and NEVER what a seat runs on: a seat always passes `bound=`. Measured basis (isolated
# daemon, 2026-10-01): warm society-safety p99 39 ms (n=40), p99 156 ms under 2x CPU
# oversubscription (n=30); a never-seen member's first act 4.6-4.8 s (n=8), 5.0 s under load
# (n=5); a cold daemon's first act 5.1 s (n=1). 8 s absorbs one cold connect.
DEFAULT_DEADLINE_SECONDS = 8.0
#: The tail of the deadline kept for the final decision record (warm record ~10 ms), at most a
#: quarter of a short budget. A cold daemon's stall was measured to swallow a 0.5 s reserve.
WITNESS_RESERVE_SECONDS = 1.0
#: The declaration a NON-harness invoker (the deploy preflight, a test) makes of the timeout it
#: enforces on this process. A harness invocation is bounded by its registration; when both are
#: known the smaller wins, so this can only shorten a registered bound.
HOOK_TIMEOUT_ENV = "HESTIA_HOOK_TIMEOUT_S"

#: The rollout knob. ONE name for every seat, projected per seat by the vault as
#: `<SEAT_TOKEN>__HESTIA_GATE_MODE` (the per-seat HESTIA_<SEAT>_GATE_MODE names are retired).
#: Anything other than exactly "warn" is enforce: an unreadable rollout fails tight.
ROLLOUT_ENV = "HESTIA_GATE_MODE"
ROLLOUTS = ("enforce", "warn")


def _remedy(rule: str) -> str:
    """The one remedy table is the core's (stage C moved this module's own entries there)."""
    r = core.REMEDIES.get(rule)
    return r.text if r is not None else core.UNREGISTERED_RULE_REMEDY


@dataclass(frozen=True)
class GateProfile:
    """Harness facts only. No law and no enforcement posture belongs here."""

    member_id: str
    identity_path: Optional[str]
    home_markers: tuple = ()
    launch_cwd_env: str = ""
    workspace_env: str = "HESTIA_WORKSPACE"
    forbidden_extra_env: str = "HESTIA_FORBIDDEN_EXTRA"
    default_role: str = "role:constellation:member"
    host_agent: str = ""
    client_name: str = ""
    gate_path: str = ""
    observe_dir: Optional[str] = ""
    attest_every: int = 200
    #: Harness capability, not law: only a seat that holds the review effector says so (#1050).
    declares_review_door: bool = False

    def core_profile(self) -> core.HarnessProfile:
        return core.HarnessProfile(
            member_id=self.member_id,
            identity_path=self.identity_path or "",
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
    budget_seconds: float = 0.0           # the deadline this verdict was reached inside

    @property
    def blocks(self) -> bool:
        return self.decision == "deny"


# ── the harness bound: the deadline the REAL registered timeout allows ───────────────────────

@dataclass(frozen=True)
class HarnessBound:
    """What a seat's registration lets this invocation spend. `deadline` is None when the
    enforced timeout could not be established; `decide()` then refuses without waiting."""

    deadline: Optional[float]             # absolute time.monotonic(); start + timeout - margin
    timeout_seconds: Optional[float]      # the smallest timeout found for this hook
    margin_seconds: float
    on_timeout: str                       # what the harness does when the timeout expires
    sources: tuple = ()                   # where each timeout came from, for the record
    why: str = ""                         # why the bound is unknown, when it is


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand(text: str, env, cwd: Optional[str]) -> Optional[str]:
    """`${VAR:-default}`, `${VAR}`, `$VAR`, `~` and `{cwd}`. None when a variable with no default
    is unset (that registration source does not exist for this process)."""
    missing = []

    def sub(m):
        name, default, bare = m.group(1), m.group(2), m.group(3)
        value = env.get(name or bare)
        if value:
            return value
        if default is not None:
            return default
        missing.append(name or bare)
        return ""

    if "{cwd}" in text:
        if not cwd:
            return None
        text = text.replace("{cwd}", cwd)
    out = _VAR.sub(sub, text)
    if missing:
        return None
    if out == "~" or out.startswith("~/"):
        home = env.get("HOME")
        if not home:
            return None
        out = home + out[1:]
    return out


def _command_targets(command: str, env) -> list:
    """Every absolute path a hook command names, expanded the way the harness's shell would."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    out = []
    for tok in tokens:
        if "=" in tok and not tok.startswith(("/", "~", "$")):
            continue                       # an environment assignment, not the program
        t = _expand(tok, env, None)
        if t and os.path.isabs(t):
            out.append(t)
    return out


def _hook_entries(doc: Any, reader: str, layout: str, event: str) -> list:
    """[(command, timeout-or-None)] for every hook registered on `event` in a parsed config."""
    out = []
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if layout == "flat":
        for tbl in hooks if isinstance(hooks, list) else []:
            if isinstance(tbl, dict) and tbl.get("event") == event and isinstance(tbl.get("command"), str):
                out.append((tbl["command"], tbl.get("timeout")))
        return out
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    for group in groups if isinstance(groups, list) else []:
        for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(h, dict) and isinstance(h.get("command"), str):
                out.append((h["command"], h.get("timeout")))
    return out


def _load_config(path: str, reader: str):
    """(parsed document, None) or (None, why). A TOML config without tomllib is (None, "scan")."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if reader == "json-hook-commands":
        return json.loads(raw.decode("utf-8")), None
    try:
        import tomllib  # type: ignore
    except ImportError:
        return None, "scan"
    return tomllib.loads(raw.decode("utf-8")), None


def _scan_timeouts(path: str, base: str) -> Optional[list]:
    """No TOML parser: every `timeout = N` in a file that names this hook at all. Conservative —
    the smallest of them can only shorten the bound. None when the file does not name the hook."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if base not in text:
        return None
    return [float(m.group(1)) for m in re.finditer(r"(?m)^\s*timeout\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$", text)]


def harness_bound(harness: dict, self_path: str, start: float, *, cwd: Optional[str] = None,
                  env=None) -> HarnessBound:
    """The deadline the harness's REAL registered timeout allows this hook process. NEVER raises.

    `harness` is the shim's HARNESS data: where this harness records its hooks (`registrations`:
    reader, layout, path with `~`/`${VAR:-default}`/`{cwd}`), the hook `event`, the timeout's
    unit, the harness's own default when an entry omits it (None when unknown), `on_timeout`
    and `margin_seconds`. Every registration of THIS file on the event counts (its realpath, or
    failing any such match its basename), from every source that exists, and the SMALLEST
    timeout wins: a smaller bound costs availability, never safety. A non-harness invoker's
    HESTIA_HOOK_TIMEOUT_S joins the same minimum.

    Returns `HarnessBound(deadline=start + timeout - margin, ...)`, or `deadline=None` with the
    reason when no enforced timeout could be established."""
    env = os.environ if env is None else env
    margin = float(harness.get("margin_seconds") or 0.0)
    on_timeout = str(harness.get("on_timeout") or "unknown")
    try:
        unit = float(harness.get("timeout_unit_seconds") or 1.0)
        default = harness.get("default_timeout_seconds")
        event = harness.get("event") or ""
        me = os.path.realpath(self_path)
        base = os.path.basename(me)
        exact, by_name, sources, problems = [], [], [], []
        for reg in harness.get("registrations") or ():
            path = _expand(str(reg.get("path") or ""), env, cwd)
            if not path or not os.path.isfile(path):
                continue
            reader, layout = reg.get("reader") or "", reg.get("layout") or "nested"
            try:
                doc, how = _load_config(path, reader)
            except Exception as exc:  # noqa: BLE001 — an unreadable registration is no bound
                problems.append(f"{path}: unreadable ({type(exc).__name__})")
                continue
            if how == "scan":
                values = _scan_timeouts(path, base)
                if values is None:
                    continue
                if not values and default is None:
                    problems.append(f"{path}: names this hook but no timeout could be read")
                    continue
                vals = [v * unit for v in values] + ([float(default)] if default is not None else [])
                by_name.append((min(vals), f"{path} (line scan, smallest timeout in the file)"))
                continue
            for command, timeout in _hook_entries(doc, reader, layout, event):
                targets = _command_targets(command, env)
                hit_exact = any(os.path.realpath(t) == me for t in targets)
                hit_name = hit_exact or any(os.path.basename(t) == base for t in targets)
                if not hit_name:
                    continue
                if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
                    seconds = float(timeout) * unit
                    where = f"{path}: timeout {timeout}"
                elif default is not None:
                    seconds = float(default)
                    where = f"{path}: no timeout declared, harness default {default}s"
                else:
                    problems.append(f"{path}: registers this hook with no timeout, and this "
                                    f"harness's default is not known")
                    continue
                (exact if hit_exact else by_name).append((seconds, where))
        found = exact or by_name
        declared = env.get(HOOK_TIMEOUT_ENV)
        if declared:
            try:
                d = float(declared)
                if d > 0:
                    found = found + [(d, f"{HOOK_TIMEOUT_ENV}={declared} (the invoker's declaration)")]
            except ValueError:
                problems.append(f"{HOOK_TIMEOUT_ENV}={declared!r} is not a number")
        if problems and not exact:
            # A registration of this hook we could not read may carry the smaller timeout.
            return HarnessBound(None, None, margin, on_timeout, tuple(w for _, w in found),
                                "; ".join(problems))
        if not found:
            return HarnessBound(None, None, margin, on_timeout, (),
                                f"no registration of {base} on {event or 'its event'} was found "
                                f"in this harness's configuration, and no {HOOK_TIMEOUT_ENV} was "
                                f"declared")
        timeout = min(s for s, _ in found)
        sources.extend(w for _, w in found)
        return HarnessBound(start + timeout - margin, timeout, margin, on_timeout, tuple(sources))
    except Exception as exc:  # noqa: BLE001 — a reader that breaks establishes nothing
        return HarnessBound(None, None, margin, on_timeout, (),
                            f"the registration reader failed ({type(exc).__name__}: {exc})")


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

    budget: float = DEFAULT_DEADLINE_SECONDS

    @property
    def phase_deadline(self) -> float:
        return self.deadline - min(WITNESS_RESERVE_SECONDS, 0.25 * self.budget)

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


_LATE = object()


def _bounded(end: float, fn, *args, **kwargs):
    """Run one mechanism call and wait for it only until `end` (a `time.monotonic()` bound).

    Returns the call's value, or `_LATE` when there was no time to start it or it had not
    returned by `end`. A call that raises re-raises here. The worker is a daemon thread, so an
    abandoned call never holds the hook process open. Since stage C the mechanism takes the
    deadline itself; this is the belt."""
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


def mcp_transport_reach(event: GateEvent) -> list:
    """The MCP transport's LOCAL reach: its server `command`, every `args` leaf and its `cwd`.
    An out-of-scope root handed to a filesystem server is an out-of-scope read the file gates
    never see (gemini's Gate 1b scoped these since 2026-07-22; C10 makes it every seat's law).
    The server `url` is a network endpoint, egress-checked only, never command-scoped."""
    ti = event.tool_input if isinstance(event.tool_input, dict) else {}
    ctx = ti.get("_hestia_mcp_context")
    if not isinstance(ctx, dict):
        return []
    return [s for key in ("command", "args", "cwd") for s in _leaves(ctx.get(key)) if s.strip()]


def attempted_of(event: GateEvent) -> str:
    """The bounded, self-censoring WHAT behind a verdict, for every seat: the mechanism's one
    summary (`attempted_summary`), fed this module's harness-normalised command text and any
    patch-body targets. Since stage C every seat holds the claude-code seat's #185 rule."""
    ti = event.tool_input
    return mechanism.attempted_summary(
        event.tool, ti, command=_command_text(ti) if isinstance(ti, dict) else None,
        targets=_patch_targets(event.tool, ti))


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
                 role_lct=inv.role or _role(inv),
                 deadline=inv.deadline)
    except Exception:  # noqa: BLE001 — accounting never changes a decision
        pass


def _finalize(inv: _Invocation, d: GateDecision, *, consequential: bool) -> GateDecision:
    """Record the final verdict and apply C11. The ONLY place a verdict is recorded."""
    d = replace(d, rollout=inv.rollout, correlation_key=inv.key, budget_seconds=round(inv.budget, 3),
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
            remedy=_remedy("gate.evidence_uncommitted"),
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
    # A denial stays a denial without evidence; a read permit keeps the C11 read posture (allowed,
    # its missing record surfaced as an anomaly).
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

def _launch_role(inv: _Invocation, permitted: str) -> Optional[GateDecision]:
    """Step 0 (#1084, dp 2026-09-22: "all law goes into shared engine"): the role this seat was
    launched under against the roles its vault projection permits. The shim's projection loader
    keeps the permitted set aside, unjudged, and hands it here. No declared set: nothing to check."""
    if not str(permitted or "").strip():
        return None
    miswire, _verified = core.launch_role_verdict(
        permitted, os.environ.get("HESTIA_ROLE", ""),
        f"projection {os.environ.get('HESTIA_PROJECTION_PATH', '')}")
    if miswire is None:
        return None
    rule, why = miswire
    return GateDecision("deny", rule, why, _remedy(rule), verdict_available=False,
                        innate=True, anomaly=True)


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
                     client_name=_client_name(prof), host_session_id=ev.session_id,
                     deadline=inv.phase_deadline)
        except Exception:  # noqa: BLE001
            pass
        return None
    try:
        claimed = _bounded(
            inv.phase_deadline, mechanism.claim_self_write,
            marker, ev.tool, inv.attempted, plugin_id=prof.member_id, role=_role(inv),
            client_name=_client_name(prof), host_session_id=ev.session_id,
            invocation_key=inv.key,
            # THIS module stops a superseded invocation in every rollout mode (step 5), so it
            # may make the declaration that lets the daemon reclaim a lost answer (#1169).
            supersession=mechanism.SUPERSESSION_HARD_STOP,
            deadline=inv.phase_deadline,
            # THE ACT'S RESOLVED TARGET (#810; recut of #812, kimi-code): the write-position
            # argument the closure matched. The daemon prices the bar over the marker, the act
            # and this, highest wins — `inv.attempted` is a bounded summary that can cut the
            # filename out; this cannot. Sent only when it matched a closure element: an
            # opaque/internal verdict's resource ("stdin", "internal:…") names no target.
            # The LOCATION the closure resolved (cwd-joined, symlinks and `..` resolved), not the
            # argument as written: the daemon prices a member's gate entry by where it is, and a
            # relative or `cd`-qualified spelling names no location.
            resolved_target=(cv.resolved or cv.resource) if cv.marker else None)
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
                 client_name=_client_name(prof), host_session_id=ev.session_id,
                 deadline=inv.phase_deadline)
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
            declares_review_door=prof.declares_review_door,
            deadline=inv.phase_deadline)
    except Exception:  # noqa: BLE001 — an unusable mechanism is an unreachable daemon
        snapshot = None
    if snapshot is _LATE or not isinstance(snapshot, dict):
        snapshot = None
    if snapshot is not None:
        role = snapshot.get("role") if isinstance(snapshot, dict) else None
        inv.role = _role(inv, role if isinstance(role, str) else None)
        policy = core.resolve_agent_policy(cprofile, vault_reader=lambda _member: snapshot)
        workspace = core.detect_workspace(cprofile)
        # The act itself, then each piece of the MCP transport's local reach as a command of
        # its own (C10: gemini's MCP command scoping, now every seat's). Same law, same order.
        views = [nev] + [core.NormalizedEvent(tool=nev.tool, command=s, cwd=nev.cwd, raw=nev.raw)
                         for s in mcp_transport_reach(inv.event)]
        for view in views:
            v = core.evaluate(view, cprofile, workspace, policy=policy)
            if v.blocks:
                # The rollout softens a TUNABLE policy disagreement, and only when there IS a policy.
                if v.innate or inv.rollout == "enforce":
                    return _verdict_deny(v), False
                inv.warnings.append((v.rule, v.reason, True))
        return None, False
    # NO SNAPSHOT, NO PERMIT — in EVERY rollout mode, for EVERY act class (dp 2026-10-01, "align
    # upward; no snapshot -> no read"). Without the member's policy snapshot the gate cannot
    # certify scope, so the act is denied, reads included, as claude-code did before stage C.
    # This is an infrastructure INTEGRITY precondition, not a policy opinion, so the rollout does
    # not soften it — the same posture as invocation supersession and C11 (GPT, 57bcd10
    # re-review). The core's degraded verdict still runs first so an innate egress refusal keeps
    # its own rule (and counts as conduct); everything else is the infrastructure denial.
    v = core.degraded_verdict(nev, cprofile)
    if v.blocks and v.innate:
        return _verdict_deny(v), True
    reason = (f"'{inv.event.tool}' cannot be judged: the policy daemon did not answer with this "
              f"member's policy snapshot, and without it no act, read or write, is permitted "
              f"(in every rollout mode)")
    return _verdict_deny(core._deny("gate.degraded", reason, innate=True),
                         verdict_available=False, anomaly=True), True


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
            correlation_key=inv.key,   # from the RAW event, computed once (C13)
            deadline=inv.phase_deadline)
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
                            _remedy("invocation.superseded"),
                            verdict_available=False, innate=True)
    if not safety.allow:
        if safety.decided:
            if inv.rollout == "enforce":
                return GateDecision("deny", "society.safety",
                                    safety.message or "society law refused the act",
                                    _remedy("society.safety"),
                                    action_id=safety.action_id)
            inv.warnings.append(("society.safety", safety.message or "society law refused the act",
                                 True))
            return _permit(inv, "society.safety", action_id=safety.action_id)
        # NO VERDICT, NO ACT — in EVERY rollout mode, reads included (dp 2026-10-02). A society
        # check that did not decide is an infrastructure no-verdict, not a policy opinion the
        # rollout may soften: the same posture as the no-snapshot stop, supersession and C11.
        return GateDecision("deny", "society.unreachable",
                            safety.message or "no usable society-safety verdict",
                            _remedy("society.unreachable"),
                            verdict_available=False, anomaly=True, innate=True,
                            action_id=safety.action_id)
    if safety.kind == "warn":
        inv.warnings.append(("society.safety.warn", safety.message or "", True))
    return _permit(inv, "gate.allow", action_id=safety.action_id, message=safety.message or "")


def _sequence(inv: _Invocation, permitted_roles: str) -> GateDecision:
    cprofile = inv.profile.core_profile()

    d = _launch_role(inv, permitted_roles)
    if d is not None:
        return _finalize(inv, d, consequential=False)

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

    # EVERY act asks the governor, reads included (dp 2026-10-01: align upward). A read-class
    # permit that fails to commit keeps the C11 read posture (allowed, anomaly surfaced); a
    # write/exec permit that fails to commit becomes gate.evidence_uncommitted.
    return _finalize(inv, _society(inv), consequential=nev.tool not in core.READ_CLASS)


def _unbounded(bound: HarnessBound, profile: Any, event: Any, mode: str,
               start: float) -> GateDecision:
    """The harness bound could not be established, or leaves no time: refuse NOW. No daemon round
    trip and no chain record — either could outlive a harness timeout nobody knows. The local
    availability series records it (fast, never raises)."""
    if bound.deadline is None:
        why = bound.why or "the enforced timeout is unknown"
    else:
        why = (f"the registered timeout ({bound.timeout_seconds:g}s) leaves no time inside the "
               f"harness margin ({bound.margin_seconds:g}s)")
    member = getattr(profile, "member_id", "unknown")
    tool = getattr(event, "tool", "unknown")
    try:
        core.record_gate_unavailable(member, str(tool), "unknown",
                                     f"gate.harness_timeout_unknown: {why}"[:200])
    except Exception:  # noqa: BLE001
        pass
    return GateDecision(
        "deny", "gate.harness_timeout_unknown",
        f"'{tool}' was not judged: {why}. Without the timeout its harness enforces, the gate "
        f"cannot finish before the harness kills it ({bound.on_timeout})",
        _remedy("gate.harness_timeout_unknown"),
        verdict_available=False, anomaly=True, innate=True, rollout=mode,
        budget_seconds=round(max(0.0, (bound.deadline or start) - start), 3))


def decide(event: GateEvent, profile: GateProfile, *, rollout: Optional[str] = None,
           deadline: Optional[float] = None,
           budget_seconds: Optional[float] = None,
           bound: Optional[HarnessBound] = None,
           permitted_roles: str = "") -> GateDecision:
    """The one law-bearing sequence for every harness. NEVER raises.

    `bound`: a seat's `harness_bound()` — the deadline its harness's real registered timeout
    allows. A seat ALWAYS passes it; an unknown bound is `gate.harness_timeout_unknown`, denied
    at once. `deadline` / `budget_seconds`: an absolute `time.monotonic()` bound / the same
    relative to now, for a caller that is not a seat. With none of the three,
    DEFAULT_DEADLINE_SECONDS. `permitted_roles`: the launch roles the seat's vault projection
    permits (its loader keeps them aside, unjudged). Every leg and the record's reserve run
    inside the deadline; when it runs out the act fails closed."""
    start = time.monotonic()
    mode = rollout_of(rollout)
    if bound is not None:
        if not isinstance(bound, HarnessBound) or bound.deadline is None or bound.deadline <= start:
            if not isinstance(bound, HarnessBound):
                bound = HarnessBound(None, None, 0.0, "unknown", (), "the harness bound is malformed")
            return _unbounded(bound, profile, event, mode, start)
        deadline = bound.deadline
    if deadline is not None:
        budget = max(0.0, float(deadline) - start)
    elif budget_seconds is not None:
        budget = max(0.0, float(budget_seconds))
    else:
        budget = DEFAULT_DEADLINE_SECONDS
    deadline = start + budget
    inv: Optional[_Invocation] = None
    try:
        if not isinstance(event, GateEvent):
            raise TypeError("decide requires a GateEvent")
        if not isinstance(profile, GateProfile):
            raise TypeError("decide requires a GateProfile")
        inv = _Invocation(event=event, profile=profile, rollout=mode, deadline=deadline,
                          key=mechanism.correlation_key(event.raw), budget=budget)
        inv.attempted = attempted_of(event)
        return _sequence(inv, permitted_roles)
    except BaseException as exc:  # noqa: BLE001 — a gate that cannot decide must not allow
        detail = f"{type(exc).__name__}: {exc}"[:300]
        # NO VERDICT, NO ACT — a gate that could not decide denies in EVERY rollout mode, for
        # every act class, reads included (dp 2026-10-02).
        d = GateDecision(
            "deny", "gate.internal_error",
            "the common gate could not complete the decision: " + detail,
            _remedy("gate.internal_error"),
            verdict_available=False, anomaly=True, innate=True, rollout=mode)
        if inv is None:
            return d
        try:
            return _finalize(inv, d, consequential=False)
        except BaseException:  # noqa: BLE001
            return d


# ── the one renderer (C6): every seat shows a verdict in the same words ──────────────────────

def render(decision: Any) -> str:
    """The text a shim shows its harness for a GateDecision, the same on every seat (C6). A
    shim chooses only the CHANNEL (exit code, stderr, a JSON payload); never the words.

    Empty for a silent allow. A daemon-composed message (it starts with `hestia:`) is shown as
    the daemon wrote it — that is its steering text — followed by the remedy when it does not
    already carry it."""
    lines = [str(n) for n in (getattr(decision, "notices", ()) or ()) if n]
    verb = getattr(decision, "decision", "deny")
    rule = getattr(decision, "rule", "") or ""
    reason = (getattr(decision, "reason", "") or "").strip()
    remedy = (getattr(decision, "remedy", "") or "").strip()
    if verb == "allow":
        if reason.startswith("hestia:"):
            lines.append(reason)
        return "\n".join(lines)
    if reason.startswith("hestia:"):
        text = reason
    else:
        text = f"hestia: {verb} [{rule}] — {reason}" if reason else f"hestia: {verb} [{rule}]"
    if remedy and remedy not in text:
        text = f"{text.rstrip('.')}. {remedy}"
    lines.append(text)
    return "\n".join(lines)
