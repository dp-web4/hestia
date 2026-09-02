#!/usr/bin/env python3
"""grounds_vs_acts must re-find the three known 7454 violations and stay quiet on a clean corpus."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("grounds_vs_acts_under_test",
                                              HERE / "grounds_vs_acts.py")
GVA = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GVA)


def esc_event(kind: str, eid: str, at: str, **data) -> dict:
    return {"eventType": kind, "timestamp": at,
            "eventData": {"escalation_id": eid, **data}}


def test_conduct_register_classifies_against_terminality() -> None:
    dump = {"events": [
        esc_event("gate_escalation_opened", "aaa", "2026-08-20T00:00:00Z"),
        esc_event("gate_escalation_decided", "aaa", "2026-08-20T00:01:00Z", status="approved"),
        esc_event("gate_escalation_corroborated", "aaa", "2026-08-20T00:00:30Z",
                  plugin_id="kimi-code", stance="concur"),
        esc_event("gate_escalation_corroborated", "aaa", "2026-08-20T00:05:00Z",
                  plugin_id="kimi-code", stance="concur"),
        esc_event("gate_escalation_corroborated", "aaa", "2026-08-20T00:04:00Z",
                  plugin_id="codex", stance="dissent"),
        esc_event("gate_escalation_corroborated", "bbb", "2026-08-20T00:02:00Z",
                  plugin_id="kimi-code", stance="concur"),
    ]}
    reg = GVA.conduct_register(dump, "kimi-code")
    assert reg["factors"] == 3, reg                       # codex factor excluded
    assert len(reg["pre"]) == 1, reg["pre"]
    assert len(reg["post"]) == 1, reg["post"]
    assert reg["post"][0]["dt_after_terminal_s"] == 240.0
    assert len(reg["no_terminal_in_window"]) == 1        # bbb has no terminal in window
    codex = GVA.conduct_register(dump, "codex")
    assert codex["factors"] == 1 and len(codex["post"]) == 1


# The three known violations, verbatim from the repo records finding 7454 cites.
KNOWN_POSITIVE_7117 = ("`hestia_gate_escalation_corroborate` adds factors to a *pending* "
                       "escalation, so with none pending there is nothing to do.")
KNOWN_POSITIVE_7152 = ("the petition was already terminal (16:06:54Z), so the corroborate door "
                       "was structurally unavailable to every invited peer")
KNOWN_POSITIVE_7195 = ("Review complete: concur with `self_withdrawn` on `6c2034f7df1bc7a5`;\n"
                       "no factor (already\nterminal).")   # wraps across THREE lines
UNRELATED = "The whitepaper rebuild emits six artifacts; the parity step diffs them."


def test_statement_register_refinds_known_positives() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        post = root / "forum" / "kimi-code"
        post.mkdir(parents=True)
        for i, text in enumerate((KNOWN_POSITIVE_7117, KNOWN_POSITIVE_7152,
                                  KNOWN_POSITIVE_7195, UNRELATED)):
            (post / f"post-{i}.md").write_text(text, encoding="utf-8")
        hits = GVA.statement_register(GVA.authored_files(root, "kimi-code"))
    texts = [h["text"] for h in hits]
    assert len(hits) == 3, texts                        # the three positives, not the control
    assert any("structurally unavailable" in t for t in texts)
    assert any("no factor (already terminal)" in t for t in texts)   # wrap joined


def test_authorship_attribution() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        findings = root / "findings"
        findings.mkdir()
        (findings / "review-1.md").write_text("# Review\n\n**Reviewer:** kimi-code\n",
                                              encoding="utf-8")
        (findings / "review-2.md").write_text("# Review\n\n**Reviewer:** codex\n",
                                              encoding="utf-8")
        mine = GVA.authored_files(root, "kimi-code")
        theirs = GVA.authored_files(root, "codex")
    assert [p.name for p in mine] == ["review-1.md"]
    assert [p.name for p in theirs] == ["review-2.md"]


def main() -> int:
    test_conduct_register_classifies_against_terminality()
    print("ok: conduct register classifies pre/post/no-terminal, per-seat")
    test_statement_register_refinds_known_positives()
    print("ok: statement register re-finds the three 7454 positives, control excluded")
    test_authorship_attribution()
    print("ok: byline attribution is per-seat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
