#!/usr/bin/env python3
"""Retarget the README draft from c535619d / 65d892f2 to #1274's 716ae2d1 / 88c5095c, insert the
tests section from tests.md, append the old README's history. Writes readme_final.md only."""
from pathlib import Path

H = Path(__file__).resolve().parent
s = (H / "readme_head.md").read_text()


def sub1(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new)


s = s.replace("65d892f2a306b6ce11a5c43a04cfd4cd589114c175fbc7038bb0e2b629bb105e",
              "88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb")
s = s.replace("65d892f2", "88c5095c")
sub1("## Current: `88c5095c…`, re-stacked on #1239's applied head `c535619d`",
     "## Current: `88c5095c…`, re-stacked on #1274 (`716ae2d1`, #1239's clean replacement)")
sub1("""**Base: `c535619dccc4de821d3a0e9b3087d70dfc436ff2`**, #1239's head with its Codex-cleared held
patch `ca833c34…` applied (escalation `1617aee101fc9d1d`). #1247 was stacked on #1239's older,
regressed base (`574426d6…`, via `1d82846e`). This branch now merges `c535619d` in (no force).""",
     """**Base: `716ae2d155e2e8625fb5b8e7c208871e659609c9`**, the head of #1274. #1274 replaces #1239,
which is closed. It is `c535619d` merged with main `ecd888f1`. `c535619d` is #1239 with its
Codex-cleared held patch `ca833c34…` applied (escalation `1617aee101fc9d1d`). #1247 was stacked
on #1239's older, regressed base (`574426d6…`, via `1d82846e`). This branch now merges
`716ae2d1` in (no force). Its governed tree is `c535619d`'s plus main's claude-code hooks change
(`disposition_deliver.py`, `hooks.json` and the claude-code manifest). This patch touches none of
the source files that change.""")
sub1("""**This branch's governed tree is `c535619d`'s, byte for byte** (`plugins/` and `hooks-gt/` are
c535619d's tree objects).""", """**This branch's governed tree is `716ae2d1`'s, byte for byte** (`plugins/` and `hooks-gt/` are
716ae2d1's tree objects).""")
sub1("- `build_held.py` emitted the patch against a checkout of `c535619d` (verified)",
     "- `build_held.py` emitted the patch against a checkout of `716ae2d1` (verified)")
sub1("IN MEMORY over `c535619d`'s blobs", "IN MEMORY over `716ae2d1`'s blobs")
sub1("The governed subtrees are `c535619d`'s, which an", "The governed subtrees are `716ae2d1`'s, which an")
sub1("## History (before the re-stack on `c535619d`)", "## History (before the re-stack on `716ae2d1`)")
sub1("because the governed tree is now `c535619d`'s.", "because the governed tree is now `716ae2d1`'s.")
sub1("Theirs is `c535619d`. Two files", "Theirs is `c535619d` (#1274 changes none of these sources). Two files")
sub1("TESTS_PLACEHOLDER", (H / "tests.md").read_text().rstrip("\n"))
old = (H / "readme_old.md").read_text()
marker = "**Correction (Codex review, notice 18786): this branch's tree ALREADY CONTAINS `e2b891c2…`.**"
head_end = s.index(marker)
s = s[:head_end] + old[old.index(marker):]
(H / "readme_final.md").write_text(s)
print("ok", len(s))
