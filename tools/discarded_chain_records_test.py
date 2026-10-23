#!/usr/bin/env python3
"""Consequential acts are recorded or undone: no class-A chain record may be discarded again.

findings/discarded-chain-records-2026-09-27.md (#1131) found 13 handlers that performed a
consequential act and then `let _ = s.append_chain(...)` — so a chain failure left the act in force
with nothing recording it. They were fixed one by one, each in the shape its side effect allows
(record-or-undo for vault state, record-first for the filesystem and genesis, record-or-withhold
for reads and issuance). This is the ratchet that keeps them fixed: for each of the finding's
class-A event names, a call that DISCARDS the append's result fails CI.

Two discard spellings are caught: `let _ = x.append_chain("<event>"` and `let x =
append_chain("<event>", ..).ok()` / `.unwrap_or_default()` on the same statement. NOT caught: a
Result kept in a binding and swallowed in a LATER statement — the shape `policy_instance_grant` had
(`entry.map(..).unwrap_or_default()`), which the `let _` sweep in the finding also missed. That route
is pinned by its own injected-failure test (`an_instance_grant_whose_record_fails_is_undone_...`);
this scan is a ratchet on the common spelling, not a proof that no other spelling exists.

`KNOWN_OPEN` names events still discarded on main with the PR that fixes them. An entry whose event
is no longer discarded FAILS too, so the list cannot go stale and hide a regression behind it.

Classes B–D (refusal records, observations, per-call gate decisions) are deliberately not here:
losing them loses audit, not the record of an act that stood (see the finding).

Run: python3 tools/discarded_chain_records_test.py   (bare; exit 1 on failure)
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "core", "src", "server")

CLASS_A = [
    "credential_issued",
    "policy_edit",
    "policy_instance_grant",
    "policy_instance_grant_revoked",
    "config_seeded",
    "config_seat_written",
    "orchestrator_connect",
    "agent_ungovern",
    "vault_get",
    "operator_bootstrap",
    "gate_ratified",
]

# event -> the PR that fixes it. Remove the entry when that PR lands; a stale entry fails.
KNOWN_OPEN: dict[str, str] = {}


def _sources() -> list[tuple[str, str]]:
    out = []
    for root, _dirs, files in os.walk(SERVER):
        for f in files:
            if f.endswith(".rs"):
                p = os.path.join(root, f)
                with open(p, encoding="utf-8") as fh:
                    out.append((os.path.relpath(p, REPO), fh.read()))
    return out


def _skip_literal(src: str, j: int) -> int:
    """If a string/char literal or comment starts at `j`, return the index just past it."""
    c = src[j]
    if src.startswith("//", j):
        k = src.find("\n", j)
        return len(src) if k == -1 else k
    if src.startswith("/*", j):
        k = src.find("*/", j + 2)
        return len(src) if k == -1 else k + 2
    m = re.match(r'r(#*)"', src[j:j + 12])
    if m and (j == 0 or not (src[j - 1].isalnum() or src[j - 1] == "_")):
        close = '"' + m.group(1)
        k = src.find(close, j + len(m.group(0)))
        return len(src) if k == -1 else k + len(close)
    if c == '"':
        k = j + 1
        while k < len(src) and src[k] != '"':
            k += 2 if src[k] == "\\" else 1
        return k + 1
    if c == "'":
        # a char literal ('{', '\n', '\'') — not a lifetime ('a)
        m = re.match(r"'(\\.|[^\\'])'", src[j:j + 4])
        if m:
            return j + len(m.group(0))
    return j


def _strip_tests(src: str) -> str:
    """Drop `#[cfg(test)] mod ... { ... }` bodies (a test may discard freely). Braces inside
    strings, raw strings, char literals and comments do not count — the first cut counted them
    and swallowed 215k characters of http.rs, hiding a real site from the ratchet."""
    out, i = [], 0
    for m in re.finditer(r"#\[cfg\(test\)\]\s*mod\s+\w+\s*\{", src):
        if m.start() < i:
            continue
        out.append(src[i:m.start()])
        depth, j = 1, m.end()
        while j < len(src) and depth:
            k = _skip_literal(src, j)
            if k != j:
                j = k
                continue
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            j += 1
        i = j
    out.append(src[i:])
    return "".join(out)


def discarded(src: str, event: str) -> list[int]:
    """Line numbers where an append of `event` has its result discarded."""
    hits = []
    code = _strip_tests(src)
    ev = re.escape(event)
    # `let _ = <expr>.append_chain(\n?  "<event>"`
    for m in re.finditer(r"let\s+_\s*=\s*[\w.]*append_chain\(\s*\"" + ev + r"\"", code):
        hits.append(code.count("\n", 0, m.start()) + 1)
    # an append whose Result is swallowed into a default on the same statement
    for m in re.finditer(r"append_chain\(\s*\"" + ev + r"\"", code):
        end = code.find(";", m.end())
        stmt = code[m.start(): end if end != -1 else len(code)]
        depth = 0
        open_at = stmt.index("(")
        for k in range(open_at, len(stmt)):
            ch = stmt[k]
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth == 0:
                tail = stmt[k + 1:]
                if re.match(r"\s*\.(ok\(\)|unwrap_or_default\(\))", tail) and "?" not in tail:
                    # `.ok()` inside a larger expression that is then matched/used is fine;
                    # only `let x = append(..).ok();` style swallowing at statement level counts.
                    pre = code[:m.start()].rsplit("\n", 1)[-1]
                    if re.search(r"let\s+\w+\s*=\s*[\w.]*$", pre):
                        hits.append(code.count("\n", 0, m.start()) + 1)
                break
    return hits


def test_no_class_a_record_is_discarded():
    bad = []
    for path, src in _sources():
        for ev in CLASS_A:
            if ev in KNOWN_OPEN:
                continue
            for line in discarded(src, ev):
                bad.append(f"{path}:{line} discards `{ev}`")
    assert not bad, "a consequential act's record is discarded again:\n  " + "\n  ".join(bad)


def test_known_open_entries_are_still_open():
    for ev, pr in KNOWN_OPEN.items():
        found = any(discarded(src, ev) for _p, src in _sources())
        assert found, (f"`{ev}` is no longer discarded — remove it from KNOWN_OPEN ({pr}) so the "
                       "ratchet covers it")


def test_the_detector_sees_both_spellings():
    assert discarded('fn f(){ let _ = s.append_chain(\n "vault_get", x); }', "vault_get") == [1]
    assert discarded('fn f(){ let e = s.append_chain("vault_get", x).ok(); }', "vault_get") == [1]
    assert discarded('fn f(){ if let Err(e) = s.append_chain("vault_get", x) { return; } }', "vault_get") == []
    assert discarded('fn f(){ let e = match s.append_chain("vault_get", x) { Ok(e) => e, Err(_) => return }; }', "vault_get") == []
    assert discarded('#[cfg(test)]\nmod t { fn g(){ let _ = s.append_chain("vault_get", x); } }', "vault_get") == []


TESTS = [
    test_no_class_a_record_is_discarded,
    test_known_open_entries_are_still_open,
    test_the_detector_sees_both_spellings,
]

if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"TESTS list is stale: defined-not-listed {sorted(defined - listed)}, listed-not-defined {sorted(listed - defined)}")
        sys.exit(1)
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"ok    {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
