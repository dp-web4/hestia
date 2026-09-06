#!/usr/bin/env python3
"""Who gets asked to rule, who does not, and where the tool must refuse to guess.

The network half of `escalation_solicit.py` is a shell; the judgement is one pure function, so
this pins the judgement. Arms, in the order they matter:

  1. denied            -> NOBODY, reason names shopping. The arm the tool exists to fail on.
  2. reaped/expired    -> INDETERMINATE, never a fresh petition. #867: a reaped row polls as
                          synthetic `expired` whether it was ruled or not, and whether that
                          ruling was approve or DENY, so "open a fresh petition if the act still
                          stands" re-opens a denied question by another door. Only a resolver
                          that says `undecided` unlocks an ask; `denied` keeps it shut.
  3. absent bar        -> INDETERMINATE, not peers. Absence must never become authority; the
                          first cut fell through to the peer branch on an empty bar.
  4. two-factor bar    -> INDETERMINATE, peers cannot close it, operator is the route
  5. single approver   -> the roster's peers, minus the asker
  6. no roster         -> INDETERMINATE, because a baked list is one seat's view of the fleet
  7. approved / spent  -> NOBODY, and the approved remedy states the binding truthfully (#539:
                          a digest over a bounded summary, not the bytes)
  8. the asker         -> never asked to rule on its own act, whichever seat it is
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escalation_solicit import (ASK, INDETERMINATE, NOBODY,  # noqa: E402
                                resolve_peers, solicitation_verdict)

FAILURES: list[str] = []
PEERS = ["codex", "kimi-code", "gemini-cli"]


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    assert not FAILURES, FAILURES


def row(**kw) -> dict:
    base = {"status": "pending", "bar": "single_approver", "plugin_id": "claude-code",
            "consumed_at": None}
    base.update(kw)
    return base


def with_resolver(value):
    """Set or clear the resolved prior ruling for one call."""
    prev = os.environ.get("_RESOLVED_PRIOR_RULING")
    if value is None:
        os.environ.pop("_RESOLVED_PRIOR_RULING", None)
    else:
        os.environ["_RESOLVED_PRIOR_RULING"] = value
    return prev


def test_a_deny_is_never_re_solicited() -> None:
    state, who, reason = solicitation_verdict(row(status="denied"), PEERS)
    check(state == NOBODY and who == [], f"[1] a denied escalation asks nobody: {state} {who}")
    check("shopping" in reason, f"[1] and the reason names why: {reason}")


def test_a_reaped_row_is_indeterminate_not_a_fresh_petition() -> None:
    with_resolver(None)
    for status in ("expired", "unknown", ""):
        state, who, reason = solicitation_verdict(row(status=status), PEERS)
        check(state == INDETERMINATE and who == [],
              f"[2] status {status!r}: INDETERMINATE, nobody asked ({state})")
        check("#867" in reason and "appeal" in reason,
              f"[2] and it names the eviction and the route: {reason[:110]}")
        check("fresh petition" not in reason.split("Resolve")[0],
              "[2] and never recommends a fresh petition on an unresolved status")
    try:
        with_resolver("denied")
        state, who, reason = solicitation_verdict(row(status="expired"), PEERS)
        check(state == NOBODY and "appeal" in reason,
              f"[2] a resolver saying DENY keeps it shut: {state} {reason[:80]}")
        with_resolver("undecided")
        state, who, _ = solicitation_verdict(row(status="expired"), PEERS)
        check(state == ASK and who == PEERS,
              f"[2] only a resolved UNDECIDED unlocks an ask: {state} {who}")
    finally:
        with_resolver(None)


def test_absent_bar_is_not_peer_authority() -> None:
    for bar in ("", None, "some_future_bar"):
        state, who, reason = solicitation_verdict(row(bar=bar), PEERS)
        check(state == INDETERMINATE and who == [],
              f"[3] bar {bar!r}: INDETERMINATE, not peers ({state} {who})")
    check("absent bar is not evidence" in solicitation_verdict(row(bar=""), PEERS)[2],
          "[3] and says absence is not evidence")


def test_two_factor_bar_is_not_a_peer_matter() -> None:
    state, who, reason = solicitation_verdict(row(bar="sovereign_plus_peer"), PEERS)
    check(state == INDETERMINATE and who == [], f"[4] a two-factor bar asks no peer: {state}")
    check("operator is the route" in reason, f"[4] and points at the route that can: {reason[-60:]}")


def test_single_approver_asks_the_roster() -> None:
    state, who, reason = solicitation_verdict(row(), PEERS)
    check(state == ASK and who == PEERS, f"[5] the roster's peers are asked: {who}")
    check("admits a peer" in reason, f"[5] {reason}")


def test_no_roster_asks_nobody() -> None:
    state, who, reason = solicitation_verdict(row(), [])
    check(state == INDETERMINATE and who == [], f"[6] no roster: nobody asked ({state})")
    prev = os.environ.pop("HESTIA_PEERS", None)
    try:
        peers, note = resolve_peers("claude-code", "/nonexistent-workspace")
        check(peers == [] and "no roster" in note, f"[6] and resolve_peers says so: {note[:60]}")
        os.environ["HESTIA_PEERS"] = "codex, claude-code ,kimi-code"
        peers, note = resolve_peers("claude-code", None)
        check(peers == ["codex", "kimi-code"] and note == "HESTIA_PEERS",
              f"[6] an explicit roster is honoured and excludes me: {peers}")
    finally:
        os.environ.pop("HESTIA_PEERS", None)
        if prev is not None:
            os.environ["HESTIA_PEERS"] = prev


def test_decided_or_spent_asks_nobody() -> None:
    state, _, reason = solicitation_verdict(row(status="approved"), PEERS)
    check(state == NOBODY and "#539" in reason,
          f"[7] approved: nobody, and the remedy states the binding truthfully: {reason[-70:]}")
    check("byte-identical" not in reason, "[7] and does not repeat the whole-command promise")
    state, _, _ = solicitation_verdict(row(consumed_at=1800000000), PEERS)
    check(state == NOBODY, "[7] spent: nobody")


def test_the_asker_is_never_asked() -> None:
    _, who, _ = solicitation_verdict(row(plugin_id="codex"), PEERS, me="codex")
    check("codex" not in who and who == ["kimi-code", "gemini-cli"],
          f"[8] codex is not asked to rule on codex's own act: {who}")
    _, who, _ = solicitation_verdict(row(plugin_id="claude-code"), PEERS + ["claude-code"])
    check("claude-code" not in who, f"[8] nor claude its own, even when the roster lists it: {who}")


if __name__ == "__main__":
    test_a_deny_is_never_re_solicited()
    test_a_reaped_row_is_indeterminate_not_a_fresh_petition()
    test_absent_bar_is_not_peer_authority()
    test_two_factor_bar_is_not_a_peer_matter()
    test_single_approver_asks_the_roster()
    test_no_roster_asks_nobody()
    test_decided_or_spent_asks_nobody()
    test_the_asker_is_never_asked()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: peers are asked only where the law admits them, and absence is never authority")
