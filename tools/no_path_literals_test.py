#!/usr/bin/env python3
"""Release-blocking: the runtime tree carries NO hardcoded machine paths and NO default-root
fallbacks. The directive is zero; this file holds the line at today's count and moves it
only downward.

THE DIRECTIVE (dp, 2026-09-03, verbatim in docs/PRD_CONFIG_FROM_VAULT.md §0): runtime code
MUST NOT contain hardcoded paths. Paths reference environment variables; the variables are
stored in the vault, rendered from it at startup, and integrity-checked against it (#898
render+check substrate; #921 operator write door; the hook-side consumer is the open step).
A fallback IS a hardcoded path: `os.getenv("HESTIA_HOME", "~/.hestia")` fails exactly as
`"~/.hestia"` does. This file exists because that fallback shipped in #943 and every
reviewer — including the one who had just written the certification criteria — read it as
an improvement. It was held the same day. A rule that only lives in prose is a rule that
gets re-derived and re-violated; this one is now a test.

THE ONE PERMITTED EXCEPTION, STATED SO IT DOES NOT BECOME TWO. HESTIA_HOME is the single
bootstrap locator — causally there must be one, because the vault cannot supply the path
needed to open it. It still has no permitted VALUE in code: a resolver may read it and MUST
fail closed when it is absent. `os.getenv("HESTIA_HOME")` with no default passes; with any
default it fails. Everything downstream derives RELATIVE paths from that authoritative root.

TWO SHAPES THIS FILE DOES NOT REPORT, AND WHY (each is a C10-style declared exception —
named here, justified here, so a reviewer can disagree with the justification rather than
discover the silence):
  * `os.fspath(entry) or os.getcwd()` inside the authority loader's sys.path canonicalization.
    Python spells "current directory" as the EMPTY sys.path entry; resolving '' to a real
    path so it can be compared is not choosing a root, it is naming the one Python already
    chose. Selecting authority happens one line earlier and is scanned.
  * `(cwd or os.getcwd())` in the scope resolvers, where `cwd` is the EVENT's cwd and the
    thing being resolved is the ACT's relative target (`git add foo` means foo under the cwd
    the act runs in). That is data about the act, not a root for the resolver.
  Anything else spelled `or os.getcwd()`, `= os.getcwd()` or `return os.getcwd()` IS a root
  fallback and is reported: `detect_workspace` walking up from cwd and returning cwd when no
  marker is found (the 2026-09-03 cutover failure), `WORKSPACE = <env read> or os.getcwd()`,
  and the launch-cwd dynamic scope grant (`env or os.getcwd()` — a grant derived from where
  the process happens to be is authority from location).

PINNED, NOT EXPECTED-TO-FAIL (house idiom — hestia_governance_closure_test's OPEN-DEFECT
PINS, gate_false_refusal_test's _STILL_OPEN). tools/ci_discovery.py runs every *_test.py
under bare python3, and a file that cannot go green cannot land on main. So:
  * PINNED_BASELINE records today's per-file CODE hit count, measured on origin/main.
  * test_no_new_path_literals goes RED if any file's count RISES (a new literal — that is
    the release-blocking half, and it fires the day it is introduced) and RED if any
    count FALLS without the pin being updated (good news must be recorded, not silently
    absorbed, or the pin drifts into meaninglessness).
  * test_the_directive_is_not_yet_met goes RED the day the total reaches zero, and its
    message says: delete both pins, assert zero, and this file becomes the directive.

DISCRIMINATING POWER, MEASURED BEFORE TRUSTING IT (2026-09-04). The pin is PER FILE AND PER
CLASS, not a per-file total — because #943 was literal-NEUTRAL by count: it replaced one line
matching [tilde-hestia]+[expanduser-tilde] with one line matching [tilde-hestia]+
[getenv-path-default]. A total-count pin passes that substitution; a per-class pin reports
[getenv-path-default] 0 -> 1 on each of the five files. Measured on gpt/single-gate-collapse
at 97f659d (without the hunk) versus the same tree with it: the per-class pin goes RED on all
five files, the per-file total does not move. What no pin catches: replacing one literal with
another of the SAME class. That is still a literal, still counted, still the directive's
problem — but not a regression this file can see.

WHAT IS SCANNED. The runtime set is a declaration, not a glob (#481/#525 ruling): the
modules RUNTIME_MANIFEST.txt installs, plus the four seat shims, plus the template when the
manifest ships the single gate (the collapse lands both together; on a tree without the
single gate there is no template to certify). Tests, docs and tools are not runtime.
Comments and docstrings are scanned and reported separately: a literal in prose is not a
defect, but it is exactly where the next copy is pasted from.

FAIL DIRECTION. An unreadable runtime file, a missing manifest, or an unset pin is a
FAILURE — never clean by absence.

Run:  python3 tools/no_path_literals_test.py
      HESTIA_RUNTIME_ROOT=<dir> python3 tools/no_path_literals_test.py   (an alternate tree)
"""
from __future__ import annotations

import io
import os
import re
import sys
import tokenize

ROOT = os.getenv("HESTIA_RUNTIME_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOOK = "pre_" + "tool_" + "use.py"
_GEM = "before_" + "tool.py"

# (class, regex, why it is a defect)
PATTERNS = [
    ("tilde-hestia",        r"~/\.hestia",
     "the daemon home spelled as a literal; must come from the vault-backed env root"),
    ("abs-home",            r"(?<![\w/])/home/[A-Za-z0-9_]",
     "a machine-specific absolute path"),
    ("abs-mnt",             r"(?<![\w/])/mnt/",
     "a machine-specific mount path"),
    ("expanduser-tilde",    r"expanduser\(\s*[\"']~",
     "expanding a tilde literal is a hardcoded home"),
    ("getenv-path-default", r"(?:getenv|environ\.get)\(\s*[\"'][A-Z0-9_]+[\"']\s*,\s*[\"'][~/]",
     "an env read WITH a path-shaped default: the default is a hardcoded path (the #943 class)"),
    ("cwd-root-fallback",   r"(?:\bor\s+os\.getcwd\(\)|return\s+os\.getcwd\(\)|=\s*os\.getcwd\(\)\s*$)",
     "cwd used as a ROOT: layout inference, not authority"),
    ("checkout-inference",  r"parents\[\d\]|dirname\(\s*dirname\(",
     "resolving a root from __file__: checkout inference, not authority"),
]

# Declared exceptions: (class, substring that identifies the accepted spelling, justification).
# A hit whose line contains the substring is reported as "allowed" with its reason, never
# silently dropped. Add a row here only with a justification a reviewer can reject.
ALLOWED = [
    ("cwd-root-fallback", "os.fspath(entry) or os.getcwd()",
     "canonicalizing the EMPTY sys.path entry, which Python defines as cwd; not selecting authority"),
    ("cwd-root-fallback", "(cwd or os.getcwd())",
     "resolving the ACT's relative target against the event cwd; data about the act, not a root"),
]

# Per-file, per-class CODE hit counts on origin/main, measured 2026-09-04 at cc64864 by running
# this file with HESTIA_RUNTIME_ROOT pointing at a clean origin/main worktree. A file absent
# here is "unpinned" and RED. None until measured — an unset pin is a failure, so this file
# cannot pass by accident before its first measurement.
PINNED_BASELINE: dict | None = {
    "plugins/_shared/hestia_gate_core.py":          {"cwd-root-fallback": 3, "expanduser-tilde": 1, "tilde-hestia": 1},
    "plugins/_shared/hestia_gate_mechanism.py":     {},
    "plugins/_shared/hestia_governance_closure.py": {},
    "plugins/_shared/hestia_shell_classifier.py":   {},
    "plugins/claude-code/hooks/" + _HOOK:           {"expanduser-tilde": 2, "getenv-path-default": 1, "tilde-hestia": 1},
    "plugins/codex/hooks/" + _HOOK:                 {"cwd-root-fallback": 2, "expanduser-tilde": 1, "getenv-path-default": 3, "tilde-hestia": 1},
    "plugins/kimi/hooks/" + _HOOK:                  {"cwd-root-fallback": 2, "expanduser-tilde": 1, "getenv-path-default": 2},
    "plugins/gemini/hooks/" + _GEM:                 {"cwd-root-fallback": 2, "expanduser-tilde": 1, "getenv-path-default": 2, "tilde-hestia": 1},
}

_FAILS: list[str] = []
_HITS: dict[str, dict | None] = {}  # rel -> {class: count}; None = unreadable
_PROSE: list[str] = []
_ALLOWED_HITS: list[str] = []


def runtime_set() -> list[str]:
    manifest = os.path.join(ROOT, "plugins", "_shared", "RUNTIME_MANIFEST.txt")
    try:
        names = [ln.strip() for ln in open(manifest, encoding="utf-8")
                 if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError as exc:
        _FAILS.append(f"manifest unreadable: {manifest}: {exc}")
        return []
    if not names:
        _FAILS.append(f"manifest is empty: {manifest}")
        return []
    files = ["plugins/_shared/" + n for n in names]
    files += ["plugins/claude-code/hooks/" + _HOOK, "plugins/codex/hooks/" + _HOOK,
              "plugins/kimi/hooks/" + _HOOK, "plugins/gemini/hooks/" + _GEM]
    if "hestia_single_gate.py" in names:
        files.append("plugins/_template/shim_template.py")
    return files


def _prose_lines(src: str):
    comments, docstrings = set(), set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                comments.add(tok.start[0])
            elif tok.type == tokenize.STRING and tok.string.startswith(('"""', "'''")):
                docstrings.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        pass  # everything counts as code — fail closed
    return comments, docstrings


def scan(rel: str) -> int:
    path = os.path.join(ROOT, rel)
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as exc:
        _FAILS.append(f"{rel}: unreadable ({exc}) — never clean by absence")
        _HITS[rel] = None
        return -1
    comments, docstrings = _prose_lines(src)
    per: dict[str, int] = {}
    n = 0
    for ln, line in enumerate(src.split("\n"), 1):
        prose = ln in docstrings or line.lstrip().startswith("#")
        code_part = "" if prose else (line.split("#", 1)[0] if ln in comments else line)
        for cls, pat, _why in PATTERNS:
            if prose:
                if re.search(pat, line):
                    _PROSE.append(f"{rel}:{ln}  [{cls}]  {line.strip()[:88]}")
                continue
            if not re.search(pat, code_part):
                continue
            allowed = next((a for a in ALLOWED if a[0] == cls and a[1] in line), None)
            if allowed:
                _ALLOWED_HITS.append(f"{rel}:{ln}  [{cls}]  allowed: {allowed[2]}")
                continue
            _FAILS.append(f"{rel}:{ln}  [{cls}]  {line.strip()[:88]}")
            per[cls] = per.get(cls, 0) + 1
            n += 1
    _HITS[rel] = per
    return n


def _scan_all() -> None:
    if _HITS:
        return
    for rel in runtime_set():
        scan(rel)


def test_no_new_path_literals():
    """RED if any runtime file gained a literal in any class (release-blocking, fires the day it
    lands), and RED if any class lost one without the pin being updated (record the good news)."""
    _scan_all()
    assert PINNED_BASELINE is not None, (
        "PINNED_BASELINE is unset: measure origin/main and record it. An unset pin cannot pass.")
    unreadable = [r for r, per in _HITS.items() if per is None]
    assert not unreadable, f"unreadable runtime files (never clean by absence): {unreadable}"
    unpinned = [r for r in _HITS if r not in PINNED_BASELINE]
    rose, fell, rose_keys = [], [], set()
    for rel, per in _HITS.items():
        pin = PINNED_BASELINE.get(rel, {})
        for cls in sorted(set(per) | set(pin)):
            a, b = pin.get(cls, 0), per.get(cls, 0)
            if b > a:
                rose.append(f"{rel} [{cls}]: pinned {a}, now {b}")
                rose_keys.add((rel, cls))
            elif b < a:
                fell.append(f"{rel} [{cls}]: pinned {a}, now {b}")
    assert not rose, (
        "NEW hardcoded path(s) in the runtime tree — the directive is zero and this is the "
        "release-blocking half:\n  " + "\n  ".join(rose)
        + "\n  hits:\n    " + "\n    ".join(
            h for h in _FAILS if any(h.startswith(r + ":") and f"[{c}]" in h for r, c in rose_keys)))
    assert not unpinned, (
        "runtime file(s) not in the pin — a new runtime module must land with its literals "
        "recorded (or at zero): " + ", ".join(f"{r} {_HITS[r]}" for r in unpinned))
    assert not fell, (
        "literal count FELL — good; update PINNED_BASELINE so the pin holds the new line:\n  "
        + "\n  ".join(fell))


def test_the_directive_is_not_yet_met():
    """Green while the total is above zero. RED the day it reaches zero — and that is the
    signal to delete both pins and make `assert total == 0` the whole test."""
    _scan_all()
    total = sum(sum(per.values()) for per in _HITS.values() if per)
    assert total > 0, (
        "the runtime tree has ZERO path literals. Delete PINNED_BASELINE and this test; "
        "make test_no_new_path_literals assert a total of zero. The directive is met.")


ALL = [test_no_new_path_literals, test_the_directive_is_not_yet_met]


def main() -> int:
    _scan_all()
    print(f"no-path-literals — runtime tree under {ROOT}")
    for rel, per in _HITS.items():
        pin = (PINNED_BASELINE or {}).get(rel)
        if per is None:
            flag, n = "UNREAD", -1
        else:
            n = sum(per.values())
            if pin is None:
                flag = "UNPIN "
            elif any(per.get(c, 0) > pin.get(c, 0) for c in per):
                flag = "RISE  "
            elif any(per.get(c, 0) < pin.get(c, 0) for c in pin):
                flag = "FELL  "
            else:
                flag = "ok    "
        print(f"  {flag}  {rel:<46} code={n:<3} {dict(sorted(per.items())) if per else ''}")
    total = sum(sum(per.values()) for per in _HITS.values() if per)
    print(f"\n  total code hits: {total}   prose-only: {len(_PROSE)}   allowed: {len(_ALLOWED_HITS)}")
    if _ALLOWED_HITS:
        print("  declared exceptions:")
        for h in _ALLOWED_HITS:
            print("    " + h)
    failed = []
    for t in ALL:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__} :: {e}")
    if os.getenv("NO_PATH_LITERALS_LIST") == "1":
        print("\nall code hits:")
        for h in _FAILS:
            print("   ", h)
    print()
    print("OK" if not failed else f"FAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
