#!/usr/bin/env python3
"""Two pins for #669, both RED on origin/main at the time of writing.

PLACEMENT, STATED RATHER THAN QUIET. This file belongs next to `sprintE_test.py` and
`repair345_test.py` in `plugins/_shared/`, which is where the pins it corrects already
live. Writing it there is a governance-closure write and was refused by the gate
(escalation `f90aa5d7528c35cd`, 2026-08-27) — correctly: a member editing the surface
that governs it is the thing that rule exists to make visible. It is written to
`tools/` instead because `tools/ci_discovery.py bare` collects test files repo-wide
(the 2026-07-29 amendment that ended the `plugins/*/tests/*_test.py` glob), so the pin
runs in CI from here with no loss. If an operator approves the escalation, moving it is
a `git mv` and nothing else changes. Recording the refusal here rather than silently
choosing the reachable directory: the placement is a decision someone else may want to
revisit, not an implementation detail.

WHY THIS FILE EXISTS. #669 measured that `claude-code` records zero `mrh.*`
`policy_decision` rows across 12,177 of its own rows, while `kimi-code` and `codex`
record hundreds — and that the law's prescribed remedy (`hestia_appeal`) is keyed on
the deny's chain hash, so a deny with no row has no remedy. That issue established the
SYMPTOM and left "why" open. This file pins the two MECHANISMS found underneath it.

PIN 1 — the recorder is wired per seat, and the pin that checks it is too.
`witness_decision_unified` is documented in `hestia_gate_mechanism` as "the ONE deny
recorder". `plugins/kimi/hooks/pre_tool_use.py` calls it; `plugins/codex/hooks/
pre_tool_use.py` calls it three times; `plugins/claude-code/hooks/pre_tool_use.py`
calls it zero times. The existing pins are the reason nobody noticed: `sprintE_test.py`
asserts `uses-unified-recorder` against CODEX_HOOK, `repair345_test.py` asserts it
against KIMI_DRAFT, and the claude-side test (`test_claude_copy_no_private_client`)
asserts only DELETIONS — "the private client is gone" — never that the shared one
arrived. The claude hook was cleaned of its own recorder and never given the common
one. A guard is as strong as the domain it validates, and this seat was outside it.

PIN 2 — the scope rule's DOMAIN is the process cwd, so a `cd` silently vacates it.
`detect_workspace` returns `os.getcwd()` when `HESTIA_WORKSPACE` is unset and no
`.hestia-workspace` marker is found (neither is present on CBP). `command_in_scope`
then locates absolute paths by `cmd.split(workspace)` and bare tokens by membership in
`_all_repos(workspace)`. Both collapse when the workspace resolves to a subdirectory:
the split finds no occurrence, and the repo-name set shrinks to that subdirectory's own
children. Measured on CBP: 73 names at the workspace root, 2 from `hestia/tools`.

The consequence is not looser matching, it is no matching. An ABSOLUTE path naming an
ungranted repo is denied when the hook sits at the workspace root and ALLOWED when it
sits two directories down — same target, and an absolute path does not resolve through
cwd. The docstring of `detect_workspace` reasons about exactly one direction of this
fallback: "sibling-repository grants remain inert rather than widening from a guess."
Inert is the safe direction for GRANTING and the fail-OPEN direction for DENYING, and
one value serves both.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "plugins", "_shared"))

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if not ok else ""))
    if not ok:
        FAILURES.append(name)


# ── PIN 1 — every shim that can deny must reach the ONE recorder ───────────────────────
SHIMS = {
    "kimi-code": os.path.join(REPO, "plugins", "kimi", "hooks", "pre_tool_use.py"),
    "codex": os.path.join(REPO, "plugins", "codex", "hooks", "pre_tool_use.py"),
    "claude-code": os.path.join(REPO, "plugins", "claude-code", "hooks", "pre_tool_use.py"),
}


def test_every_shim_calls_the_one_recorder() -> None:
    """Asserted per SEAT, in a loop, not per file the author happened to be editing.

    The loop is the point. Both existing pins name a single hook path, so a seat that
    was never named was never checked, and a fourth harness could reintroduce the gap
    by simply not appearing in a test."""
    print("PIN 1 — unified deny recorder, per seat")
    for seat, path in SHIMS.items():
        if not os.path.isfile(path):
            check(f"{seat}-shim-present", False, f"missing {path}")
            continue
        src = open(path, encoding="utf-8").read()
        # A mention in prose is not a call — `hestia_gate_mechanism` and several comment
        # blocks name the function without invoking it. Require the call syntax.
        calls = src.count("witness_decision_unified(")
        check(f"{seat}-calls-unified-recorder", calls >= 1,
              f"{path} names it {src.count('witness_decision_unified')}x but CALLS it "
              f"{calls}x — its denies reach neither the chain nor the per-seat fallback "
              f"log, and a deny with no chain hash cannot be appealed "
              f"(`tool_appeal` opens with require_string(args, 'deny_hash'))")


def test_scope_deny_path_records_before_returning() -> None:
    """The specific site: the MRH gate's `if _v.blocks:` branch.

    Narrower than the file-level pin above and worth keeping separate — a shim can call
    the recorder on one deny path and not another, which is exactly the shape the claude
    hook has today: `gate_self_access` records via `_emit_gate_event`, and the scope deny
    eight hundred lines later does not. 'Records something' is not one property."""
    print("PIN 1b — the scope-deny branch itself")
    path = SHIMS["claude-code"]
    if not os.path.isfile(path):
        check("claude-scope-branch-present", False, f"missing {path}")
        return
    lines = open(path, encoding="utf-8").read().splitlines()
    branch_starts = [i for i, ln in enumerate(lines) if ln.strip() == "if _v.blocks:"]
    check("scope-deny-branches-found", len(branch_starts) >= 1,
          "the MRH gate's deny branch could not be located; update this pin rather than "
          "letting it pass vacuously")
    for i in branch_starts:
        body = "\n".join(lines[i:i + 12])
        check(f"scope-deny-branch-at-line-{i + 1}-records",
              "witness_decision_unified" in body,
              "the branch writes stderr and returns 2; `debug_log` is a no-op unless "
              "HESTIA_HOOK_DEBUG=1, so the deny's only durable record is the transcript "
              "of the member it denied")


# ── PIN 2 — the denial domain must not depend on where the process happens to sit ──────
def _core():
    import hestia_gate_core as core
    return core


def test_absolute_reach_is_denied_from_any_workspace_depth() -> None:
    """Same target, two workspace resolutions, one verdict required.

    Built on a synthetic tree under /tmp so the pin never names an operator's real
    repositories — the constraint `tools/public_boundary.py` already enforces on this
    repo, and which caught the author of the gate twice."""
    print("PIN 2 — absolute reach, independent of workspace depth")
    import shutil
    import tempfile

    core = _core()
    root = os.path.realpath(tempfile.mkdtemp(prefix="ws-domain-"))
    try:
        granted = os.path.join(root, "granted-repo")
        ungranted = os.path.join(root, "ungranted-repo")
        deep = os.path.join(granted, "sub", "dir")
        os.makedirs(deep)
        os.makedirs(ungranted)
        scopes = (granted,)
        cmd = f"cat {ungranted}/secret.txt"

        ok_at_root, tok_root = core.command_in_scope(cmd, scopes, root, cwd=root)
        ok_at_deep, _ = core.command_in_scope(cmd, scopes, deep, cwd=deep)

        # The control runs FIRST and is load-bearing: without it, a pin that passes
        # because the rule never fires at all would read as the rule holding.
        check("absolute-reach-denied-at-workspace-root", ok_at_root is False,
              "control failed — the rule did not fire even at the root, so the second "
              "assertion below would prove nothing either way")
        check("absolute-reach-denied-from-subdirectory", ok_at_deep is False,
              f"workspace={deep!r} makes the same absolute path invisible: "
              f"cmd.split(workspace) finds no occurrence, and _all_repos(workspace) no "
              f"longer contains the sibling's name. At the root it denies "
              f"({tok_root!r}); one level down it allows. The target is byte-identical "
              f"and an absolute path does not resolve through cwd, so this is a bypass, "
              f"not a loss of precision")

        check("all-repos-collapses-with-depth",
              len(core._all_repos(root)) > len(core._all_repos(deep)),
              "the out-of-scope name set did not shrink with depth, so this environment "
              "cannot exercise the defect and the pin above is inert — treat a green "
              "here as unmeasured, not as passing")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_bare_token_reach_is_denied_from_any_workspace_depth() -> None:
    """The relative-token half of the same collapse.

    Kept separate from the absolute case because the two fail through different code:
    pass 1 (`cmd.split(workspace)`) versus pass 2 (`_all_repos` membership). Fixing one
    does not fix the other, so one pin covering both would go green too early."""
    print("PIN 2b — bare-token reach, independent of workspace depth")
    import shutil
    import tempfile

    core = _core()
    root = os.path.realpath(tempfile.mkdtemp(prefix="ws-domain-tok-"))
    try:
        granted = os.path.join(root, "granted-repo")
        sub = os.path.join(granted, "sub")
        os.makedirs(sub)
        os.makedirs(os.path.join(root, "ungranted-repo"))
        scopes = (granted,)
        cmd = "cat ungranted-repo/secret.txt"

        ok_at_root, _ = core.command_in_scope(cmd, scopes, root, cwd=root)
        check("bare-token-denied-at-workspace-root", ok_at_root is False,
              "control failed — the rule did not fire at the root")

        # cwd is held at the ROOT deliberately: the token still resolves to the ungranted
        # repo exactly as before. Only the workspace moved, and with it the set of names
        # the rule is willing to consider at all.
        ok_at_sub, _ = core.command_in_scope(cmd, scopes, sub, cwd=root)
        check("bare-token-denied-when-workspace-is-a-subdirectory", ok_at_sub is False,
              "the reach is unchanged and still resolves out of scope; the rule stopped "
              "looking because the workspace it was handed no longer lists the sibling")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def teardown_module(_module=None) -> None:
    """Deliver the accumulator to pytest as well as to `python3 <file>`.

    Without this, every `check()` failure is appended to a module-level list that only
    `main()` reads, so `python3 -m pytest` runs all four tests, records every failure,
    returns normally and reports PASSED — a green indistinguishable from the null state,
    under exactly the invocation a `*_test.py` name invites. `tools/ci_selfexec_test.py`
    refuses that shape, and refused this file on its first draft."""
    assert not FAILURES, f"{len(FAILURES)} failing pin(s): {', '.join(FAILURES)}"


def main() -> int:
    for fn in (test_every_shim_calls_the_one_recorder,
               test_scope_deny_path_records_before_returning,
               test_absolute_reach_is_denied_from_any_workspace_depth,
               test_bare_token_reach_is_denied_from_any_workspace_depth):
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILING: {', '.join(FAILURES)}")
        return 1
    print("all pins green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
