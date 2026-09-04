#!/usr/bin/env python3
"""THE REFERENCE SHIM — the minimal adapter between a harness and the common gate.

This file is the template every certified shim is diffed against
(`docs/PRD_SHIM_CERTIFICATION.md`). It is not installed and never runs in production; it
is the artifact that makes "differs only where necessary" a checkable claim rather than an
opinion.

WHAT A SHIM IS
--------------
An adapter. It converts a harness event into the shared normalized form, calls ONE shared
decision path, and converts the result back into the harness's blocking protocol. It holds
no governance logic of its own.

THE ALLOW-LIST IS THE CRITERION
-------------------------------
`PERMITTED_FUNCTIONS` at the foot of this file is the mechanical statement of C4. It names
EXACTLY the eight functions a certified shim may define. The section headings below are
prose for humans; the tuple is what a checker reads. An earlier draft described "four
sections", "three adapter functions" and a different set of names in the prose, and the
three descriptions disagreed with each other and with the code — which is precisely the
ambiguity certification cannot afford (GPT, review of PR #932).

  §1 BOOTSTRAP   `_shared_runtime_dir`, `_load_shared_module`, `_emergency_refuse`.
                 BYTE-IDENTICAL across every certified shim; a diff here is a C1 failure,
                 not a variant. This is the only code that legitimately cannot be shared,
                 because it is what selects and verifies the shared tree — and, for
                 `_emergency_refuse`, what must still work when that tree is gone.
  §2 PROFILE     the seat's identity and paths, as DATA. All seat variation lives here.
                 If a seat needs something the profile cannot express, the profile gains a
                 field; the shim does not gain a function (C3).
  §3 ADAPTERS    `to_event`, `emit`, `_emergency_block`. Per-seat, because harnesses
                 genuinely differ in event shape and in how a call is blocked.
                 `_emergency_block` is separate from `emit` because `emit` renders a shared
                 verdict object, which does not exist when the core is unavailable.
  §4 MAIN        `main`, `_read_harness_input`. The harness's I/O and entry contract.

WHAT A SHIM MUST NOT CONTAIN
----------------------------
Anything that decides. No classification, no scope resolution, no workspace detection, no
record rendering, no mode switch, no wrappers that bind seat constants into engine calls.
Every one of those exists in the shared tree today, and every one of them is currently
duplicated in at least one deployed shim.

Mechanically (C2): the set of function names defined in a shim MUST equal
`PERMITTED_FUNCTIONS` exactly — no extras, no omissions — and must not otherwise intersect
the names exported by the shared modules. Both halves are greppable.

SIZE IS THE POINT
-----------------
Deployed shims today: claude-code 1756 lines, codex 894, kimi 761, gemini 577. This
template is the shape they should converge toward. If a migrated shim is still many
hundreds of lines, the migration did not happen — something that decides is still living
in it.

THE BLOCKER, STATED HONESTLY: `decide()` DOES NOT EXIST YET
-----------------------------------------------------------
§4 below calls `gate.decide(event, profile=PROFILE)` and `_core.fail_closed(...)`. Neither
function exists. They are the deliverable, not a description of today.

What the shared tree offers today is ~48 PRIMITIVES and no orchestrator:

    hestia_gate_core        evaluate, degraded_verdict, command_in_scope, path_in_scope,
                            needs_society_gate, detect_workspace, forbidden_tokens,
                            resolve_agent_policy, record_gate_unavailable, ...
    hestia_gate_mechanism   query_society_safety, gate_self_call, witness_gate_self,
                            claim_self_write, witness_decision_unified, role_bridge,
                            fetch_policy_snapshot, tally_scope, _extract_target, ...

Every shim must therefore compose those primitives into a decision sequence ITSELF: which
to call, in what order, what to do with each result, when to escalate, when to record,
what to do when one of them fails. That composition IS the governance logic — and because
no shared function performs it, it is necessarily written four times.

This reframes the whole problem. The four shims did not drift because anyone was careless;
they drifted because the architecture requires each of them to re-implement the
orchestration, and orchestration is where every divergence found on 2026-09-04 lives:
the mode switch, the record renderer, the fail-closed handler, the read/write
determination, the workspace lookup. None of those are adapter concerns. All of them are
sequencing decisions that four authors made four times.

So item 1 of this work is not "move six duplicated functions into the common gate." It is
"the common gate is missing its top half." Until `decide(event, profile) -> verdict`
exists and owns the sequence, a minimal shim is not achievable — a shim can only be as
thin as the shared API lets it be, and today the shared API hands back parts.
"""

# ─────────────────────────────────────────────────────────────────────────────────────
# §1 BOOTSTRAP — byte-identical across all certified shims. Diff here == C1 failure.
#
# This section cannot move into the shared tree: it is the code that selects and verifies
# the shared tree. Everything it does is a guard that a previous incident demanded:
#   * installed authority directory only, never a checkout fallback          (#742)
#   * sys.path canonicalized by realpath+normcase, so a symlink and its target cannot
#     both hold precedence
#   * the loaded module's __file__ verified against the required path ("miswire")
#   * BaseException during module init converted to ImportError, so even SystemExit(0)
#     reaches the caller's fail-closed posture instead of exiting quietly
#
# The deployed kimi shim has none of this — it uses bare __import__ from ambient sys.path.
# That is the single largest divergence found in the 2026-09-04 read.
# ─────────────────────────────────────────────────────────────────────────────────────
import os
import sys


def _shared_runtime_dir():
    return os.environ.get("HESTIA_SHARED_DIR") or os.path.join(
        os.path.expanduser(os.environ.get("HESTIA_HOME", "~/.hestia")), "shared")


def _load_shared_module(name):
    """Load governing code only from the selected installed authority directory.

    Copy this verbatim. It is reproduced in each shim rather than shared because a shim
    that imported it from the shared tree would be trusting the tree before verifying it.
    """
    import importlib.util

    shared = _shared_runtime_dir()
    required = os.path.realpath(os.path.join(shared, name + ".py"))
    if not os.path.isfile(required):
        raise ImportError(
            f"installed Hestia shared module {name!r} is unavailable at {required!r}; "
            "run deploy/install-members.sh")

    selected_dir = os.path.dirname(required)
    selected_key = os.path.normcase(selected_dir)
    retained = []
    for entry in sys.path:
        try:
            entry_key = os.path.normcase(os.path.realpath(os.fspath(entry) or os.getcwd()))
        except (TypeError, ValueError, OSError):
            retained.append(entry)
            continue
        if entry_key != selected_key:
            retained.append(entry)
    sys.path[:] = [selected_dir, *retained]

    cached = sys.modules.get(name)
    if cached is not None:
        cached_file = getattr(cached, "__file__", None)
        if cached_file and os.path.realpath(cached_file) == required:
            return cached
        sys.modules.pop(name, None)

    spec = importlib.util.spec_from_file_location(name, required)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot construct a loader for installed module {required!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:
        sys.modules.pop(name, None)
        raise ImportError(
            f"installed Hestia shared module {name!r} failed to initialize") from exc
    loaded_file = getattr(module, "__file__", None)
    if not loaded_file or os.path.realpath(loaded_file) != required:
        sys.modules.pop(name, None)
        raise ImportError(
            f"shared authority miswire: {name!r} resolved to {loaded_file!r}, "
            f"expected {required!r}")
    return module


# ─────────────────────────────────────────────────────────────────────────────────────
# §2 PROFILE — all seat variation, as data. Nothing below this line branches on seat.
#
# Every field a deployed shim currently binds by hand inside a wrapper function belongs
# here. The five wrappers in codex and kimi (_gate_self_call, _role_bridge, _tally_scope,
# _witness_gate_self, _claim_self_write) exist ONLY to bind these values; once the
# mechanism API takes a profile, the wrappers have nothing left to do.
# ─────────────────────────────────────────────────────────────────────────────────────
# The bootstrap is CAPTURED, never fatal. An earlier draft of this template wrote
#
#     _core = _load_shared_module("hestia_gate_core")     # module level, unguarded
#
# and that is a fail-OPEN, verified 2026-09-04: the ImportError propagates out of module
# initialization, the process exits 1 before main() is entered, no handler runs — and the
# repo states in two places that a Claude-lineage engine fails OPEN on a hook crash
# (hestia_gate_core.py:167-173; plugins/gemini/README.md:268). So the one case C7 exists
# to cover was, in the reference template for C7, the case that disarmed the gate.
#
# Caught by GPT in review of PR #932. It is the best possible argument for certification:
# the defect was invisible to every behavioural test because on a healthy machine the
# import always succeeds.
_core = None
_BOOTSTRAP_ERROR = None
try:
    _core = _load_shared_module("hestia_gate_core")
except BaseException as _exc:          # noqa: BLE001 — must catch SystemExit too
    _BOOTSTRAP_ERROR = _exc

PROFILE_FIELDS = dict(
    member_id="<seat>",                       # the plugin_id asserted to the daemon
    identity_path="~/.<seat>/hestia-instance/identity.json",
    home_markers=("~/.<seat>",),              # paths always the member's own
    launch_cwd_env="",                        # env var carrying the launch dir, if any
    mode_env="",                              # SEE C5: either every seat has one or none
    workspace_env="HESTIA_WORKSPACE",
    forbidden_extra_env="HESTIA_FORBIDDEN_EXTRA",
    default_role="role:constellation:member",
)
# Built only if the core survived. Kept as plain data above so the emergency path can name
# the seat without needing the shared dataclass.
PROFILE = _core.HarnessProfile(**PROFILE_FIELDS) if _core is not None else None

# Fields the profile does not yet carry, which the wrappers bind today and which must be
# ADDED to HarnessProfile rather than re-introduced as shim code:
#   client_name      e.g. "hestia-<seat>-gate-self"
#   observe_dir      where scope tallies are written
#   attest_every     tally attestation cadence
# Until those fields exist, the migration for this seat is incomplete. Say so in the
# certification record rather than working around it here.


# ─────────────────────────────────────────────────────────────────────────────────────
# §3 ADAPTERS — the only place harnesses legitimately differ, and the only functions a
# certified shim may define beyond §1 and §4. Both are small by construction: if an
# adapter grows past a screen, something that decides has leaked into it.
# ─────────────────────────────────────────────────────────────────────────────────────
def to_event(raw):
    """Harness event -> NormalizedEvent.

    JUSTIFIED DIFFERENCE (C4). Each harness delivers a different shape: Claude Code sends
    PreToolUse JSON on stdin with tool_name/tool_input; codex and gemini deliver their own
    schemas. Deployed equivalents today are `command_of`, 6-9 lines across three seats.

    This function EXTRACTS. It must not judge — no path checks, no marker matching, no
    read/write determination. Those belong to the shared classifier, which is exactly the
    boundary claude-code currently crosses by holding its own read/write classifier.
    """
    raise NotImplementedError("per-seat: extract tool name, inputs, cwd, session id")


def emit(verdict):
    """Shared verdict -> the harness's blocking protocol.

    JUSTIFIED DIFFERENCE (C4). Harnesses block differently: exit codes, JSON on stdout,
    a structured refusal object. Deployed equivalents today are `deny`, 14-19 lines.

    This function FORMATS. The decision, the rule id, and the remedy text are already
    fixed by the shared verdict; a shim that rewrites any of them fails C5/C6.
    """
    raise NotImplementedError("per-seat: render the verdict in the harness's protocol")


# ─────────────────────────────────────────────────────────────────────────────────────
# §4 MAIN — the harness I/O contract, and the fail-closed posture.
#
# Note what is NOT here: no mode switch, no per-seat recording path, no internal-error
# handler with seat-specific fields. C7 requires that an internal error, an unreachable
# daemon, and a missing shared module each produce a RECORDED refusal carrying a rule id —
# and all three are produced by the shared decision path, not by the shim.
# ─────────────────────────────────────────────────────────────────────────────────────
def _emergency_refuse(exc):
    """Block with a deterministic local artifact, using NO shared code. Byte-identical
    across every certified shim; a diff here is a C1 failure.

    This is the C7b path: the shared recorder is, by construction, the thing that is
    missing. "Recorded refusal" cannot be demanded of code that is unavailable, so the
    obligation is weakened honestly — block, and leave a deterministic artifact a later
    reconciliation can pick up — rather than pretended.

    Pure stdlib, no imports beyond those already at module top, no dependence on `_core`
    or `PROFILE`. It must not raise: an exception here reproduces the exact fail-open this
    function exists to prevent.
    """
    try:
        import json
        import time
        rec = {
            "ts": time.time(),
            "seat": PROFILE_FIELDS["member_id"],
            "decision": "deny",
            "rule": "gate-bootstrap-unavailable",
            "verdict_available": False,      # infra posture, never member conduct
            "detail": f"{type(exc).__name__}: {exc}"[:400],
        }
        d = os.path.join(os.path.expanduser(os.getenv("HESTIA_HOME", "~/.hestia")),
                         "telemetry")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "gate-bootstrap-unavailable.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except BaseException:
        pass          # recording must never convert a fail-closed into a crash
    return _emergency_block()


def _emergency_block():
    """Per-seat: the smallest possible harness-native BLOCK, using no shared code.

    JUSTIFIED DIFFERENCE (C4) and separate from `emit` on purpose: `emit` renders a shared
    verdict object, which does not exist when the core is gone. Typically one exit code or
    one literal JSON line. Keep it literal — no formatting helpers, no shared constants.
    """
    raise NotImplementedError("per-seat: block with no shared code available")


def main():
    if _BOOTSTRAP_ERROR is not None:                 # C7b — core absent or miswired
        return _emergency_refuse(_BOOTSTRAP_ERROR)
    try:
        gate = _load_shared_module("hestia_gate_mechanism")
        event = to_event(_read_harness_input())
        verdict = gate.decide(event, profile=PROFILE)
    except BaseException as exc:                     # C7a — decision module gone; the
        return emit(_core.fail_closed(PROFILE, exc))  # recorder survived, so record.
    return emit(verdict)


def _read_harness_input():
    """Per-seat: how the event arrives (stdin JSON, argv, a file). Part of §4."""
    raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────────────
# THE EXACT ALLOW-LIST (C4). Mechanically checkable; this tuple IS the criterion.
#
# A certified shim defines these names and no others. "Sections" and "kinds" are prose for
# humans; this is what a checker reads. Eight names, three of them byte-identical bootstrap.
#
# THIS FILE IS THE SINGLE SOURCE. `shim_certification_test.py` parses these two tuples out
# of this file rather than restating them. That is not a style preference — it is the
# repair for a defect this PR shipped and then found by reading (2026-09-04): the checker
# had been written with its OWN transcription of the allow-list, and the two copies
# disagreed on 4 of 8 names within a single PR. A criterion stated twice is a criterion
# that will drift, which is exactly the finding (@codex review #1) that produced this
# tuple in the first place. Restating it in a second file re-committed the error one
# layer along. Do not copy these names anywhere; parse them.
# ─────────────────────────────────────────────────────────────────────────────────────
PERMITTED_FUNCTIONS = (
    "_shared_runtime_dir",   # §1 bootstrap — byte-identical across all certified shims
    "_load_shared_module",   # §1 bootstrap — byte-identical
    "_emergency_refuse",     # §1 bootstrap — byte-identical
    "_emergency_block",      # §3 adapter   — per-seat, no shared code available
    "to_event",              # §3 adapter   — per-seat, harness event shape
    "emit",                  # §3 adapter   — per-seat, harness blocking protocol
    "_read_harness_input",   # §4           — per-seat, harness I/O
    "main",                  # §4           — per-seat, harness entry contract
)

# C1 — the subset whose BYTES must be identical across every certified shim. The
# complement of this set is per-seat BY DESIGN and must NOT be hashed for identity.
#
# Getting this membership wrong is not cosmetic, and the first cut had it exactly
# inverted: it demanded byte-identity of `_emergency_block` (which the template requires
# to differ per seat — one harness-native exit code) while never hashing `_emergency_refuse`
# (which the template declares byte-identical and which is the whole C7b fail-closed path).
# So the one function whose silent divergence reintroduces a fail-OPEN was the one function
# with no identity check, and the one function that must differ was required to match.
BYTE_IDENTICAL = (
    "_shared_runtime_dir",
    "_load_shared_module",
    "_emergency_refuse",
)

if __name__ == "__main__":
    raise SystemExit(main())
