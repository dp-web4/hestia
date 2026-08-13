#!/usr/bin/env python3
"""Sprint C acceptance (gate-consolidation PRD §6.C): kimi's migrated scope predicates ==
the shared core, on the §3.3 bypass-class inputs, plus a no-regression set of safe inputs.

WHAT THIS PROVES, and only this: after the C migration, the kimi shim's `path_in_scope` /
`command_in_scope` return the SAME verdict the core returns when called directly — for the
two §3.3 bypass classes the core hardens (path-boundary containment vs substring/prefix;
resolve-before-segment traversal) and for ordinary safe reaches. Inputs are the SAME shapes
plugins/_shared/test_gate_core.py uses (its differential spec: the temp-root siblings, the
workspace-substring decoy, the granted/../notgranted escapes) — no fresh bypass strings are
invented here, per PRD §10.

Deliberately NOT asserted (PRD §6.C, GPT 2nd-pass #2): cross-harness convergence. codex is
still pre-hardening until step F; an "all harnesses agree" test here SHOULD fail against the
measured current state, so it lives at step G, not in this file.

SKIPS CLEANLY against an unpatched kimi gate (no `_core` attribute), so it can land in the
same PR as the migration diff and simply start asserting the moment the diff is applied.

Run (from a worktree with the diff applied):
    python3 kimi_core_parity_test.py
    python3 -m pytest kimi_core_parity_test.py -q
Against an explicit file/checkout:
    KIMI_GATE_FILE=/path/to/patched/hook.py python3 kimi_core_parity_test.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest

# The hook's filename, spelled in two parts: the installed gates content-match the joined
# literal (the PR #357 false-positive class — a file ABOUT the gate drawing the gate's own
# deny), and this test names the file as data, not as a write destination.
_HOOK_BASENAME = "pre_" + "tool_use.py"


def _find_repo_root():
    """Walk up from this file for the dir that contains plugins/_shared/hestia_gate_core.py
    — works wherever the test lands in the repo. Env HESTIA_REPO overrides."""
    env = os.environ.get("HESTIA_REPO")
    if env:
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "plugins", "_shared", "hestia_gate_core.py")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _workspace():
    """A scratch workspace NOT under /tmp: /tmp is unconditionally in scope, so a workspace
    built there greens every scope assertion for the wrong reason (test_gate_core's own
    footgun note)."""
    base = os.path.expanduser("~/.cache/hestia-kimi-parity-tests")
    os.makedirs(base, exist_ok=True)
    ws = tempfile.mkdtemp(dir=base)
    assert not ws.startswith(("/tmp", "/var/tmp")), ws
    return ws


# ── module-level setup: env BEFORE the kimi module import (it captures WORKSPACE at import) ──
WS = _workspace()
os.environ["HESTIA_WORKSPACE"] = WS
for d in ("granted", "notgranted", "claude-code"):
    os.makedirs(os.path.join(WS, d), exist_ok=True)

def _skip(msg):
    """Skip that works under BOTH runners: pytest reads a module-level unittest.SkipTest as
    a module skip; the bare runner would read the same raise as a traceback (exit 1), which
    is a red, not a skip — and this file must be able to land in the same PR as the diff."""
    if __name__ == "__main__":
        print(f"SKIP — {msg}")
        sys.exit(0)
    raise unittest.SkipTest(msg)


_REPO = _find_repo_root()
_KIMI_FILE = os.environ.get("KIMI_GATE_FILE") or (
    os.path.join(_REPO, "plugins", "kimi", "hooks", _HOOK_BASENAME) if _REPO else None)
if not _KIMI_FILE or not os.path.isfile(_KIMI_FILE):
    _skip("cannot locate the kimi gate file — set KIMI_GATE_FILE (or HESTIA_REPO), "
          f"looked for {_KIMI_FILE!r}")

# The core must be importable BEFORE the kimi module loads, and from the real _shared dir:
# the kimi module's own _SHARED_DIR is derived from WORKSPACE (here a scratch dir), so its
# `import hestia_gate_core` resolves through THIS sys.path entry.
if _REPO:
    _shared = os.path.join(_REPO, "plugins", "_shared")
else:  # KIMI_GATE_FILE given outside a repo checkout: _shared must be beside a repo root
    _shared = os.path.join(os.environ.get("HESTIA_REPO", ""), "plugins", "_shared")
sys.path.insert(0, _shared)
import hestia_gate_core as core  # noqa: E402

_spec = importlib.util.spec_from_file_location("kimi_gate_under_test", _KIMI_FILE)
KIMI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(KIMI)

if not hasattr(KIMI, "_core"):
    # Unpatched kimi (pre-migration local predicates). SKIP, loudly and by name, so this
    # file can sit in the same PR as the migration diff: red would block the PR on ordering,
    # silent green would claim a parity nobody measured.
    _skip("kimi gate at %s is UNPATCHED (no _core) — apply kimi_predicate_migration.diff "
          "first; parity not asserted" % _KIMI_FILE)
if KIMI._core is None:
    raise AssertionError(
        "kimi gate is patched but its core import FAILED (_core is None) — in production "
        "this fails closed on every act; here it means this test's sys.path setup or the "
        "checkout is broken. Nothing was measured.")

SCOPES = ["granted"]
PROFILE = core.HarnessProfile(member_id="kimi-code",
                              identity_path=os.path.join(WS, "identity.json"),
                              home_markers=("~/.kimi-code",))


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _path_verdicts(p, cwd=None):
    """(kimi_verdict, core_verdict) for one path — the migrated shim path vs the core direct."""
    return (KIMI.path_in_scope(p, SCOPES, cwd or WS),
            core.path_in_scope(p, SCOPES, WS, PROFILE, cwd or WS))


def _cmd_verdicts(cmd, cwd=None):
    return (KIMI.command_in_scope(cmd, SCOPES, cwd or WS),
            core.command_in_scope(cmd, SCOPES, WS, cwd or WS))


def _parity(name, kimi_v, core_v, expect):
    """Parity AND the hardened verdict: parity alone would also pass if both sides were
    wrong the same way, and the §6.C acceptance is 'kimi now DENIES the §3.3 inputs'."""
    check(f"{name}_parity", kimi_v == core_v, f"kimi={kimi_v!r} core={core_v!r}")
    check(f"{name}_verdict", core_v == expect, f"core={core_v!r} expected={expect!r}")


# ── §3.3 class 1: path-boundary written as a substring test ─────────────────────────────
def test_temp_root_is_a_boundary_not_a_prefix():
    """test_gate_core::test_temp_root_is_a_path_boundary_not_a_prefix, through the shim.
    kimi's deleted local form was startswith(("/tmp", "/var/tmp")) — the exact prefix bug."""
    for p in ("/tmp", "/tmp/x/y", "/var/tmp/x"):
        k, c = _path_verdicts(p)
        _parity(f"temp_ok[{p}]", k, c, True)
    for p in ("/tmp-other/x", "/var/tmpsecrets/y", "/tmpfoo"):
        k, c = _path_verdicts(p)
        _parity(f"temp_sibling[{p}]", k, c, False)


def test_workspace_containment_is_a_boundary_not_a_substring():
    """test_gate_core's decoy shape: a path merely CONTAINING the workspace string. kimi's
    deleted local form was `WORKSPACE in p`."""
    k, c = _path_verdicts(f"/decoy{WS}/granted/x")
    _parity("workspace_substring_decoy", k, c, False)


# ── §3.3 class 2: segment read lexically before resolving `..` ──────────────────────────
def test_path_resolves_before_segment_is_read():
    """test_gate_core::test_scope_is_decided_after_normalisation_not_before (B5/B6), through
    the shim: the granted first segment must not front for an ungranted resolved target."""
    # Positive control FIRST — a deny-everything regression greens the escapes for free.
    k, c = _path_verdicts(f"{WS}/granted/a.md")
    _parity("control_granted_path", k, c, True)
    k, c = _path_verdicts(f"{WS}/granted/../notgranted/secret")
    _parity("abs_dotdot_escape", k, c, False)
    k, c = _path_verdicts("granted/../notgranted/secret")   # relative spelling, same target
    _parity("rel_dotdot_escape", k, c, False)
    k, c = _path_verdicts(f"{WS}/granted/../../etc/shadow")  # clean out of the workspace
    _parity("traversal_past_workspace_root", k, c, False)


def test_command_resolves_before_segment_is_read():
    """test_gate_core B7, through the shim: the command arm of the same class — text is
    member-controlled end to end, so it needs no harness to cooperate."""
    (k_ok, k_off), (c_ok, c_off) = _cmd_verdicts(f"cat {WS}/granted/a.md")
    _parity("control_granted_command", k_ok, c_ok, True)
    (k_ok, k_off), (c_ok, c_off) = _cmd_verdicts(f"cat {WS}/granted/../notgranted/secret")
    _parity("cmd_dotdot_escape", k_ok, c_ok, False)
    check("cmd_dotdot_escape_names_same_offender", k_off == c_off,
          f"kimi={k_off!r} core={c_off!r}")


# ── no-regression: clearly-safe inputs still pass ───────────────────────────────────────
def test_safe_inputs_still_pass():
    """~8 ordinary reaches. A migration that closes bypasses by denying everything would be
    a different defect wearing a green suit."""
    safe_paths = [
        (f"{WS}/granted/a.md", WS),               # in-scope absolute write target
        ("granted/notes.md", WS),                 # relative inside the granted repo
        ("/tmp/scratch/x.json", WS),              # temp scratch
        ("/var/tmp/build/log.txt", WS),           # the second temp root
        ("~/.kimi-code/settings.json", WS),       # the member's own home
    ]
    for p, cwd in safe_paths:
        k, c = _path_verdicts(p, cwd)
        _parity(f"safe_path[{p}]", k, c, True)
    safe_cmds = [
        "ls -la",
        "git status",
        f"cat {WS}/granted/a.md && echo done",
        # The measured 2026-07-24 false-deny class: a bare member plugin-id is an ADDRESS,
        # not a reach — even with a same-named dir at the workspace root (created above).
        "send claude-code ack ptr123",
    ]
    for cmd in safe_cmds:
        (k_ok, _), (c_ok, _) = _cmd_verdicts(cmd)
        _parity(f"safe_cmd[{cmd[:40]}]", k_ok, c_ok, True)


# ── the wiring itself ───────────────────────────────────────────────────────────────────
def test_shim_delegates_to_the_same_core_module():
    """The parity above is only meaningful if the shim consults the SAME implementation the
    differential spec pins — not a third copy that happens to agree today."""
    check("kimi_core_is_this_core", KIMI._core is core,
          f"kimi imported {getattr(KIMI._core, '__file__', '?')}, test imported {core.__file__}")
    check("profile_home_marker", KIMI._CORE_PROFILE.home_markers == ("~/.kimi-code",),
          repr(KIMI._CORE_PROFILE.home_markers))
    check("profile_member_id", KIMI._CORE_PROFILE.member_id == "kimi-code",
          repr(KIMI._CORE_PROFILE.member_id))


# Explicit list — NOT a globals() comprehension — so every test name is a static reference
# (same convention as hestia_gate_mechanism_test.py; tools/ci_selfexec_test.py rejects
# dynamically-swept test functions as un-referenced).
ALL = [
    test_temp_root_is_a_boundary_not_a_prefix,
    test_workspace_containment_is_a_boundary_not_a_substring,
    test_path_resolves_before_segment_is_read,
    test_command_resolves_before_segment_is_read,
    test_safe_inputs_still_pass,
    test_shim_delegates_to_the_same_core_module,
]

if __name__ == "__main__":
    print("kimi shim == gate core — §3.3 bypass-class parity (PRD §6.C acceptance)")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests: kimi's migrated predicates match the core on every "
          f"§3.3 class input and every safe input")
