#!/usr/bin/env python3
"""MRH scope differential: ONE command through the shared `command_in_scope`, varying only what
the member did not write -- the workspace root the seat resolved, and the event cwd.

The closure differential (`gate_differential.py`, #759) pins three MRH-layer refusals at `none`
and says the layer "has no differential of its own". #760 asks for one. This is it, seeded
with what was measured live on the claude-code seat on CBP, 2026-09-02 (seven refusals in
one hour, every one a read):

    'python' is not granted      echo "ci python test step"           (#744, twice)
    'exec' is not granted        exec(compile(...)) in a heredoc body
    '*' is not granted           ls -d <root>/*/
    '#' is not granted           sed "s#<root>#<P>#g"
    'ai-agents' is not granted   the word in prose; and EVERY genuine out-of-scope reach

None of these is a command being checked against a tool allowlist, which is how #744 and #760
read them. `command_in_scope` has two passes. Pass 1 splits the command TEXT on the resolved
workspace root and reads the next path segment as a repo name: a glob, a sed delimiter, or
the empty segment (naming the root itself) arrive there. Pass 2 takes every bare token of the
command -- quoted or not -- and, if it equals the name of a directory that exists beside the
granted repos under the resolved root, probes the filesystem under the EVENT CWD and every
granted root; an existing out-of-scope hit is a deny. So `python` denies exactly when (a) the
seat's root has a sibling directory called `python` and (b) the event cwd is where that
directory is. On CBP the claude-code seat resolves its root from the session cwd (no
HESTIA_WORKSPACE in its hook line, unlike codex and gemini; no `.hestia-workspace` marker), one
level ABOVE the directory the grants live under. That level has 22 siblings, among them
`python`, `exec`, `misc`, `archive`, and `ai-agents` -- which is also why every real deny at
that root names 'ai-agents' as the offender: it is the first segment under the wrong root.

This instrument builds that layout in a tempdir (no host path is baked) and runs each case at
four cells: root in {wrong, right} x cwd in {the root, a granted repo}. A member's act does
not change meaning with the seat's cwd, so the expectation is ONE verdict per case, and a
case whose cells disagree is reported as a root/cwd split -- the same act, two answers.

PINS record today's measured cells, false positives included. Default mode exits 1 when a
cell moves off its pin in EITHER direction: a regression, or a fix that must update the pin
in the same change. `--strict` exits 1 on any cell that disagrees with the expectation --
the acceptance for #760's replacement model. `--record` prints the pin block.

EXIT: 0 every cell on its pin (or, --strict, on its expectation); 1 otherwise; 2 unmeasured.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins" / "_shared"))
import hestia_gate_core as core  # noqa: E402

ALLOW, DENY = "allow", "deny"


def build_fixture(base: Path) -> dict:
    """<base>/wrong/ holds the siblings a session one level too high sees; <base>/wrong/ai-agents/
    is the real workspace the grants live under."""
    wrong = base / "wrong"
    right = wrong / "ai-agents"
    for d in ("python", "exec", "misc", "archive", "ye"):
        (wrong / d).mkdir(parents=True)
    for d in ("hestia/tools", "hestia/.github/workflows", "sibling-repo", "docs", "scripts"):
        (right / d).mkdir(parents=True)
    (right / "hestia" / "README.md").write_text("x\n")
    (right / "hestia" / ".github" / "workflows" / "ci.yml").write_text("x\n")
    (right / "sibling-repo" / "notes.md").write_text("x\n")
    os.symlink(".", right / "ai-agents")        # the stray self-link measured on CBP (2025-11-21)
    return {"wrong": str(wrong), "right": str(right), "hestia": str(right / "hestia"),
            "grants": [f"path:{right / 'hestia'}", f"path:{right / 'docs'}"]}


def cases(fx: dict) -> list:
    H, R, W = fx["hestia"], fx["right"], fx["wrong"]
    return [
        # name, command, expected verdict (None = undecided: pinned, never scored as FP/FN)
        ("744.echo-label-simple", 'echo "ci python test step"', ALLOW),
        ("744.echo-label-compound", f'cd {H} && ls tools/ | head; echo "--- ci python test step:"; sed -n "1,5p" .github/workflows/ci.yml', ALLOW),
        ("744.grep-pattern-compound", f'cd {H} && grep -n "pytest\\|python -m" .github/workflows/ci.yml | head -8', ALLOW),
        ("0902.exec-in-heredoc-body", f"cd {H} && python3 - <<'PY'\nsrc = open('x').read()\nexec(compile(src, 'x', 'exec'))\nPY", ALLOW),
        ("0902.sed-delimiter-after-root", f'grep -n W {H}/README.md | sed "s#{W}#<P>#g"', ALLOW),
        ("0902.bare-word-in-prose", 'echo "repos live in ai-agents"', ALLOW),
        ("0902.verb-shaped-sibling-at-right-root", 'echo "see docs for the scripts"', ALLOW),
        ("0902.glob-under-wrong-root", f"ls -d {W}/*/", None),
        ("0902.name-the-right-root", f"ls {R}", None),
        ("ctl.interpreter-head", f"cd {H} && python3 tools/meter.py", ALLOW),
        ("ctl.granted-absolute-read", f"cat {H}/README.md", ALLOW),
        ("ctl.granted-relative-read", "cat tools/meter.py", None),        # meaning depends on cwd by design
        ("ctl.ungranted-sibling-repo", f"cat {R}/sibling-repo/notes.md", DENY),
        ("ctl.traversal-out-of-grant", f"cat {H}/../sibling-repo/notes.md", DENY),
    ]


# Measured 2026-09-02 on origin/main at 4aa2260. Each cell is (verdict, offender). Re-record with
# --record when the predicate changes, and say in the change which cells moved and why.
PINS = {
    ('0902.bare-word-in-prose', 'right', 'repo'): ('allow', None),
    ('0902.bare-word-in-prose', 'right', 'root'): ('deny', 'ai-agents'),
    ('0902.bare-word-in-prose', 'wrong', 'repo'): ('allow', None),
    ('0902.bare-word-in-prose', 'wrong', 'root'): ('deny', 'ai-agents'),
    ('0902.exec-in-heredoc-body', 'right', 'repo'): ('allow', None),
    ('0902.exec-in-heredoc-body', 'right', 'root'): ('allow', None),
    ('0902.exec-in-heredoc-body', 'wrong', 'repo'): ('allow', None),
    ('0902.exec-in-heredoc-body', 'wrong', 'root'): ('deny', 'exec'),
    ('0902.glob-under-wrong-root', 'right', 'repo'): ('allow', None),
    ('0902.glob-under-wrong-root', 'right', 'root'): ('allow', None),
    ('0902.glob-under-wrong-root', 'wrong', 'repo'): ('deny', '*'),
    ('0902.glob-under-wrong-root', 'wrong', 'root'): ('deny', '*'),
    ('0902.name-the-right-root', 'right', 'repo'): ('deny', '<workspace root>'),
    ('0902.name-the-right-root', 'right', 'root'): ('deny', '<workspace root>'),
    ('0902.name-the-right-root', 'wrong', 'repo'): ('deny', 'ai-agents'),
    ('0902.name-the-right-root', 'wrong', 'root'): ('deny', 'ai-agents'),
    ('0902.sed-delimiter-after-root', 'right', 'repo'): ('allow', None),
    ('0902.sed-delimiter-after-root', 'right', 'root'): ('allow', None),
    ('0902.sed-delimiter-after-root', 'wrong', 'repo'): ('deny', '#'),
    ('0902.sed-delimiter-after-root', 'wrong', 'root'): ('deny', '#'),
    ('0902.verb-shaped-sibling-at-right-root', 'right', 'repo'): ('allow', None),
    ('0902.verb-shaped-sibling-at-right-root', 'right', 'root'): ('deny', 'scripts'),
    ('0902.verb-shaped-sibling-at-right-root', 'wrong', 'repo'): ('allow', None),
    ('0902.verb-shaped-sibling-at-right-root', 'wrong', 'root'): ('allow', None),
    ('744.echo-label-compound', 'right', 'repo'): ('allow', None),
    ('744.echo-label-compound', 'right', 'root'): ('allow', None),
    ('744.echo-label-compound', 'wrong', 'repo'): ('allow', None),
    ('744.echo-label-compound', 'wrong', 'root'): ('deny', 'python'),
    ('744.echo-label-simple', 'right', 'repo'): ('allow', None),
    ('744.echo-label-simple', 'right', 'root'): ('allow', None),
    ('744.echo-label-simple', 'wrong', 'repo'): ('allow', None),
    ('744.echo-label-simple', 'wrong', 'root'): ('deny', 'python'),
    ('744.grep-pattern-compound', 'right', 'repo'): ('allow', None),
    ('744.grep-pattern-compound', 'right', 'root'): ('allow', None),
    ('744.grep-pattern-compound', 'wrong', 'repo'): ('allow', None),
    ('744.grep-pattern-compound', 'wrong', 'root'): ('deny', 'python'),
    ('ctl.granted-absolute-read', 'right', 'repo'): ('allow', None),
    ('ctl.granted-absolute-read', 'right', 'root'): ('allow', None),
    ('ctl.granted-absolute-read', 'wrong', 'repo'): ('allow', None),
    ('ctl.granted-absolute-read', 'wrong', 'root'): ('allow', None),
    ('ctl.granted-relative-read', 'right', 'repo'): ('allow', None),
    ('ctl.granted-relative-read', 'right', 'root'): ('allow', None),
    ('ctl.granted-relative-read', 'wrong', 'repo'): ('allow', None),
    ('ctl.granted-relative-read', 'wrong', 'root'): ('allow', None),
    ('ctl.interpreter-head', 'right', 'repo'): ('allow', None),
    ('ctl.interpreter-head', 'right', 'root'): ('allow', None),
    ('ctl.interpreter-head', 'wrong', 'repo'): ('allow', None),
    ('ctl.interpreter-head', 'wrong', 'root'): ('allow', None),
    ('ctl.traversal-out-of-grant', 'right', 'repo'): ('deny', 'sibling-repo'),
    ('ctl.traversal-out-of-grant', 'right', 'root'): ('deny', 'sibling-repo'),
    ('ctl.traversal-out-of-grant', 'wrong', 'repo'): ('deny', 'ai-agents'),
    ('ctl.traversal-out-of-grant', 'wrong', 'root'): ('deny', 'ai-agents'),
    ('ctl.ungranted-sibling-repo', 'right', 'repo'): ('deny', 'sibling-repo'),
    ('ctl.ungranted-sibling-repo', 'right', 'root'): ('deny', 'sibling-repo'),
    ('ctl.ungranted-sibling-repo', 'wrong', 'repo'): ('deny', 'ai-agents'),
    ('ctl.ungranted-sibling-repo', 'wrong', 'root'): ('deny', 'ai-agents'),
}


def measure(fx: dict) -> dict:
    out = {}
    for name, cmd, _ in cases(fx):
        for root_label in ("wrong", "right"):
            root = fx[root_label]
            for cwd_label, cwd in (("root", root), ("repo", fx["hestia"])):
                ok, tok = core.command_in_scope(cmd, fx["grants"], root, cwd=cwd)
                out[(name, root_label, cwd_label)] = (ALLOW if ok else DENY, None if ok else tok)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="score against the expectation, not the pin")
    ap.add_argument("--record", action="store_true", help="print the PINS block for the current predicate")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as raw:
        fx = build_fixture(Path(raw))
        got = measure(fx)
        expect = {name: exp for name, _, exp in cases(fx)}
    if args.record:
        print("PINS = {")
        for k in sorted(got):
            print(f"    {k!r}: {got[k]!r},")
        print("}")
        return 0

    cells = ("wrong/root", "wrong/repo", "right/root", "right/repo")
    print(f"{'case':<40} " + " ".join(f"{c:<18}" for c in cells) + " expect")
    fp = fn = split = moved = unpinned = 0
    for name in expect:
        row, verdicts = [], set()
        for c in cells:
            rl, cl = c.split("/")
            v, tok = got[(name, rl, cl)]
            verdicts.add(v)
            pin = PINS.get((name, rl, cl))
            mark = ""
            if pin is None:
                unpinned += 1
                mark = "?"
            elif (v, tok) != tuple(pin):
                moved += 1
                mark = "!"
            row.append((f"{v} '{tok}'" if tok else v) + mark)
        exp = expect[name]
        flag = ""
        if exp is not None:
            if exp == ALLOW and DENY in verdicts:
                fp += 1
                flag = "  <-- FP"
            if exp == DENY and ALLOW in verdicts:
                fn += 1
                flag = "  <-- FN"
        if len(verdicts) > 1:
            split += 1
            flag += "  [root/cwd split]"
        print(f"{name:<40} " + " ".join(f"{r[:18]:<18}" for r in row) + f" {exp or '-'}{flag}")
    print(f"\ncases with a false positive cell: {fp}   false negative: {fn}   root/cwd splits: {split}"
          f"   cells off their pin: {moved}   unpinned: {unpinned}")
    if unpinned and not args.strict:
        print("INDETERMINATE: unpinned cells; run --record and commit the block", file=sys.stderr)
        return 2
    if args.strict:
        return 1 if (fp or fn) else 0
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
