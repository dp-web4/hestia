#!/usr/bin/env python3
"""Look-alike merge suggestion (agent-lifecycle PRD R6): narrow, and it never acts.

dp's trust list showed `claude-code` (5,415 actions), `Claude-code` (0) and `caude-code` (0) as
three agents, because a member id is caller-asserted text and a typo in a grant form mints a
member (#1067). The dashboard now offers, on a never-acted row, to PREPARE the operator's alias
act against the one id it resembles.

A wrong suggestion is an invitation to join two real members' evidence, so what is pinned here is
mostly what it must NOT do:

  * never suggest an id that has acted as the alias -- two ids that both act are two actors;
  * never suggest when more than one survivor fits -- say nothing rather than guess;
  * never suggest on short ids, where one edit apart means nothing;
  * never POST. The suggestion fills the existing form; the act keeps its own button.

`lookalikeSuggestions` / `withinOneEdit` are pure, so they are lifted out and run under node.

Run: python3 tools/lookalike_merge_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def block() -> str:
    a = UI.index("// ── Look-alike members (agent-lifecycle PRD R6)")
    b = UI.index("  function renderHarnessTrust(trust, orchs) {", a)
    return UI[a:b]


def source_contract() -> None:
    blk = block()
    check("NEVER POSTS: no request of any kind in the look-alike block",
          re.findall(r"\b(apiFetch|fetch|XMLHttpRequest|sendBeacon)\s*\(", blk), [])
    check("prefill targets the operator's existing alias form",
          all(f"'{i}'" in blk for i in ("ali-of", "ali-alias", "ali-ref")))
    check("prefill does not press the act's button", "ali-btn" in blk, False)
    check("the row says nothing is recorded until the operator presses the button",
          "Nothing is recorded until you press its button" in UI)
    check("the trust list asks for suggestions", "const alike = lookalikeSuggestions(allRows);" in UI)


def run(expr: str, arg) -> object:
    blk = block()
    pure = blk[blk.index("const LOOKALIKE_MIN_LEN"):blk.index("  // Fill the operator's alias form")]
    prog = pure + f"\nconst A = JSON.parse(process.argv[1]); process.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run(["node", "-e", prog, json.dumps(arg)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[:300]}")
        return None
    return json.loads(r.stdout)


def row(pid, n):
    return {"plugin_id": pid, "action_count": n}


def behaviour() -> None:
    sug = lambda rows: run("lookalikeSuggestions(A)", rows) or {}

    # The measured case, exactly as dp read it off the screen.
    s = sug([row("claude-code", 5415), row("Claude-code", 0), row("caude-code", 0)])
    check("dp's case: both phantoms point at the one that acts",
          {k: v["of"] for k, v in s.items()}, {"Claude-code": "claude-code", "caude-code": "claude-code"})
    check("dp's case: case-only difference is named as such", s.get("Claude-code", {}).get("how"),
          "differs only in case or punctuation")
    check("dp's case: a dropped letter is named as such", s.get("caude-code", {}).get("how"), "one character apart")
    check("the evidence pointer is pre-written and carries both counts",
          "0 actions vs 5415" in s.get("caude-code", {}).get("ref", ""))
    check("the id that acts is never offered as an alias", "claude-code" in s, False)

    # Two ids that both ACT are two actors. codex / codex-cli is a real alias on this fleet, made
    # by an operator on evidence -- not something a string distance may propose.
    check("two acting ids are never suggested", sug([row("kimi-code", 40), row("kimi-codes", 3)]), {})
    check("far apart is not alike", sug([row("claude-code", 9), row("codex-cli", 0)]), {})

    # Ambiguity: a phantom one edit from TWO survivors is not guessed at.
    check("ambiguous survivor -> nothing", sug([row("agent-aa1", 5), row("agent-ab1", 5), row("agent-a1", 0)]), {})

    # Short ids: `pi` vs `pu` is one edit and means nothing.
    check("short ids are left alone", sug([row("codex", 10), row("codez", 0)]), {})
    # Each side has its own length guard, and each needs its own case: a sabotage that removed
    # the phantom's guard passed while only the pair above existed (the survivor's guard caught
    # it). Here the survivor is just long enough and the phantom is not.
    check("a short PHANTOM beside a long-enough survivor is left alone",
          sug([row("codex1", 10), row("codex", 0)]), {})
    check("a long-enough phantom beside a short SURVIVOR is left alone",
          sug([row("codex", 10), row("codex1", 0)]), {})

    # A phantom with no acting neighbour at all.
    check("nothing to fold into -> nothing", sug([row("Claude-code", 0), row("caude-code", 0)]), {})
    check("garbage in", sug([None, {}, {"plugin_id": ""}, row("claude-code", 1)]), {})

    for a, b, want in [("claudecode", "claudecode", True), ("caudecode", "claudecode", True),
                       ("claudecode", "caudecode", True), ("cluadecode", "claudecode", True),
                       ("claudecodx", "claudecode", True), ("claudecod", "claudecode", True),
                       ("clodecode", "claudecode", False), ("claudecode", "claudecodeXY", False),
                       ("abcdef", "badcfe", False)]:
        check(f"withinOneEdit({a}, {b})", run("withinOneEdit(A[0], A[1])", [a, b]), want)


def test_lookalike_merge_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    # ONE body for both invocations (tools/ci_selfexec_test.py: a `test_*` nothing calls never
    # runs under the bare `python3` CI uses). The assert is pytest's channel; here it is caught
    # so that every failure is printed, not only the fact of one.
    try:
        test_lookalike_merge_contract()
    except AssertionError:
        pass
    if not shutil.which("node"):
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"lookalike merge contract: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
