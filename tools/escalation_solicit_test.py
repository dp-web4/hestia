#!/usr/bin/env python3
"""Who gets asked to rule, and who does not, decided without a daemon.

The network half of `escalation_solicit.py` is a shell; the judgement is one pure function, so
this pins the judgement. Arms, in the order they matter:

  1. denied           -> NOBODY, and the reason says shopping. This is the arm the tool exists
                         to fail on: asking a second peer after a deny is exactly the move a
                         convenient tool would make easy.
  2. two-factor bar   -> NOBODY, because a peer cannot close `sovereign_plus_peer`; the
                         operator is the route and peers only corroborate
  3. single approver  -> the peers, minus the asker
  4. approved         -> nobody: the answer exists, and the remedy is the byte-identical
                         re-issue, not another ask
  5. spent / expired  -> nobody
  6. the asker is never asked to approve its own act, whichever seat it is
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from escalation_solicit import solicitation_verdict  # noqa: E402

FAILURES: list[str] = []


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


def test_a_deny_is_never_re_solicited() -> None:
    peers, reason = solicitation_verdict(row(status="denied"))
    check(peers == [], f"[1] a denied escalation asks nobody: {peers}")
    check("shopping" in reason, f"[1] and the reason names why: {reason}")


def test_two_factor_bar_is_not_a_peer_matter() -> None:
    peers, reason = solicitation_verdict(row(bar="sovereign_plus_peer"))
    check(peers == [], f"[2] a two-factor bar asks no peer to close it: {peers}")
    check("sovereign" in reason and "operator" in reason,
          f"[2] and points at the route that can: {reason}")


def test_single_approver_asks_the_peers() -> None:
    peers, reason = solicitation_verdict(row())
    check(peers == ["codex", "kimi-code", "gemini-cli"], f"[3] the peers are asked: {peers}")
    check("admits a peer" in reason, f"[3] {reason}")


def test_a_decided_or_spent_row_asks_nobody() -> None:
    for kw, tag in ((dict(status="approved"), "approved"),
                    (dict(status="expired"), "expired"),
                    (dict(consumed_at=1800000000), "spent")):
        peers, reason = solicitation_verdict(row(**kw))
        check(peers == [], f"[4/5] {tag}: nobody asked ({reason[:60]})")
    _, reason = solicitation_verdict(row(status="approved"))
    check("byte-identical" in reason,
          f"[4] and an approved row is told the remedy that actually claims it: {reason}")


def test_the_asker_is_never_asked() -> None:
    peers, _ = solicitation_verdict(row(plugin_id="codex"), me="codex")
    check("codex" not in peers and peers == ["kimi-code", "gemini-cli"],
          f"[6] codex is not asked to approve codex's own act: {peers}")
    peers, _ = solicitation_verdict(row(plugin_id="kimi-code"), me="kimi-code")
    check("kimi-code" not in peers, f"[6] nor kimi its own: {peers}")


if __name__ == "__main__":
    test_a_deny_is_never_re_solicited()
    test_two_factor_bar_is_not_a_peer_matter()
    test_single_approver_asks_the_peers()
    test_a_decided_or_spent_row_asks_nobody()
    test_the_asker_is_never_asked()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: peers are asked where the law admits them, and never after a ruling")
