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

Four sections are permitted, and they are marked below. A shim that adds a fifth is a
certification finding (C4).

  §1 BOOTSTRAP   the authority loader. The ONLY code that legitimately cannot be shared,
                 because it is what decides which shared tree to trust. Byte-identical
                 across every certified shim — a diff here is a C1 failure, not a variant.
  §2 PROFILE     the seat's identity and paths, as DATA. All seat variation lives here.
                 If a seat needs something the profile cannot express, the profile gains a
                 field; the shim does not gain a function (C3).
  §3 ADAPTERS    exactly two: harness event -> NormalizedEvent, and verdict -> the
                 harness's blocking protocol. These are where harnesses genuinely differ.
  §4 MAIN        the harness's I/O contract: how the event arrives, how a block is emitted.

WHAT A SHIM MUST NOT CONTAIN
----------------------------
Anything that decides. No classification, no scope resolution, no workspace detection, no
record rendering, no mode switch, no wrappers that bind seat constants into engine calls.
Every one of those exists in the shared tree today, and every one of them is currently
duplicated in at least one deployed shim.

Mechanically: the set of function names defined here, minus the names in §1/§3/§4, must not
intersect the names exported by the shared modules. That is C2 and it is greppable.

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
_core = _load_shared_module("hestia_gate_core")

PROFILE = _core.HarnessProfile(
    member_id="<seat>",                       # the plugin_id asserted to the daemon
    identity_path="~/.<seat>/hestia-instance/identity.json",
    home_markers=("~/.<seat>",),              # paths always the member's own
    launch_cwd_env="",                        # env var carrying the launch dir, if any
    mode_env="",                              # SEE C5: either every seat has one or none
    workspace_env="HESTIA_WORKSPACE",
    forbidden_extra_env="HESTIA_FORBIDDEN_EXTRA",
    default_role="role:constellation:member",
)

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
def main():
    try:
        gate = _load_shared_module("hestia_gate_mechanism")
        event = to_event(_read_harness_input())
        verdict = gate.decide(event, profile=PROFILE)
    except BaseException as exc:
        # The missing-module case (C7c) lands here, and it is the one no shim tests today.
        # The shared recorder is unavailable by construction, so this is the one place a
        # shim may format its own refusal — and it must still be a REFUSAL, never a pass.
        return emit(_core.fail_closed(PROFILE, exc))
    return emit(verdict)


def _read_harness_input():
    """Per-seat: how the event arrives (stdin JSON, argv, a file). Part of §4."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
