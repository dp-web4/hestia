#!/usr/bin/env python3
"""Battery for the fused-boundary-punct arm (remedy6) against the DEPLOYED closure.

Two seats agreed the arm (claude reply-2575 spec, kimi reply-2583 adoption):
inside the punct branch, a token made only of punctuation that carries any of
`; & | )` ends the simple command -> flush `cur`, then reset `stdin_src`.

This battery is written to run against whatever closure is importable, so the
same file answers "is the hole live?" before the patch and "is it closed?" after.
It also asks one question neither reply measured: does a fused token made only of
`(` characters reach the arm, or does it fall through the way `);` did?

Rows print as: NAME | write-targets | posture
Write targets use a neutral /tmp path; no governed path appears in any payload.
"""
import importlib.util
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "plugins" / "_shared"
INSTALLED = Path.home() / ".claude" / "_shared" / "hestia_governance_closure.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass resolution needs the module registered
    spec.loader.exec_module(mod)
    return mod


CASES = [
    # name, command
    ("J-fused-subshell", "f() ( cp /tmp/src /tmp/x_target ); f"),
    ("J-spaced-subshell", "f() ( cp /tmp/src /tmp/x_target ) ; f"),
    ("stdin-fused", "(cat < /tmp/benign.patch); git apply"),
    ("stdin-spaced", "(cat < /tmp/benign.patch) ; git apply"),
    ("stdin-legit-patch", "patch -p1 < /tmp/real.patch"),
    ("paren-only-fused", "( ( cp /tmp/src /tmp/x_target ) )"),
    ("arith-double-paren", "(( x=1 )); cp /tmp/src /tmp/x_target"),
    ("cd-persists", "cd /tmp && cp /tmp/src x_target"),
    ("pipe-fused", "echo hi |& cp /tmp/src /tmp/x_target"),
]


BOUNDARY_PUNCT = frozenset(";&|)")  # `(` opens, it does not close — see the paren rows


def patched_bash_write_targets(g, command):
    """The loop with remedy6's arm, transcribed from the pinned blob.

    Identical to `g._bash_write_targets` except for the six lines marked REMEDY6.
    Transcribed rather than applied because the governed file is not member-writable
    (gate-self-access); this is how the post-patch column gets measured at all.
    """
    toks = g._tokenize(command)
    targets, cur = [], []
    stdin_src = None
    eff = ""
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in g._SEPARATORS:
            if cur:
                eff = g._flush_simple_command(cur, eff, targets, stdin_src)
                cur = []
            stdin_src = None
            i += 1
            continue
        if g._is_punct(t):
            if ">" in t:
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and "&" in t and nxt.isdigit():
                    i += 2
                    continue
                if nxt is not None and nxt not in g._SEPARATORS and not g._is_punct(nxt):
                    if g._has_subst(nxt):
                        raise g._OutOfGrammar()
                    targets.append(g._join_eff(eff, nxt))
                    i += 2
                    continue
                i += 1
                continue
            if t in ("<", "<<", "<<<", "<<-"):
                if t == "<" and i + 1 < len(toks) and not g._is_punct(toks[i + 1]):
                    stdin_src = toks[i + 1]
                i += 2
                continue
            if frozenset(t) & BOUNDARY_PUNCT:  # REMEDY6 (6 lines, this arm)
                if cur:                        # a fused boundary (`);`, `))`, `;&`) ends
                    eff = g._flush_simple_command(cur, eff, targets, stdin_src)
                    cur = []                   # the simple command exactly as a bare
                stdin_src = None               # separator does — the boundary is a property
            i += 1                             # of the CHARACTERS, not of the spelling.
            continue
        cur.append(t)
        i += 1
    if cur:
        eff = g._flush_simple_command(cur, eff, targets, stdin_src)
    return targets


def run(mod, label, patched=False):
    print(f"=== {label}  (blob under test: {mod.__file__})")
    if patched:
        fn = lambda cmd: patched_bash_write_targets(mod, cmd)  # noqa: E731
        fn.__name__ = "patched_bash_write_targets"
    else:
        fn = mod._bash_write_targets
    print(f"    entry: {fn.__name__}")
    for name, cmd in CASES:
        try:
            out = fn(cmd)
            posture = "ok"
        except Exception as exc:  # noqa: BLE001 - posture is the datum
            out = []
            posture = type(exc).__name__
        rendered = []
        for t in out:
            rendered.append(t if isinstance(t, str) else type(t).__name__)
        print(f"    {name:22s} | {rendered} | {posture}")
    print()


def seed_fixtures():
    """The `patch < f` control is INERT unless f exists and parses: the patch reader
    fail-closes to _OpaqueWriter on an unreadable/unparseable source, which looks exactly
    like the refusal the remedy is supposed to leave alone. Seed a real unified diff so
    the control can actually distinguish 'still reads' from 'now refuses'."""
    diff = (
        "--- a/tmp_probe_target.txt\n"
        "+++ b/tmp_probe_target.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    for name in ("real.patch", "benign.patch"):
        Path("/tmp", name).write_text(diff)


if __name__ == "__main__":
    seed_fixtures()
    targets = [(SHARED / "hestia_governance_closure.py", "TREE", False)]
    if INSTALLED.exists():
        targets.append((INSTALLED, "INSTALLED", False))
        targets.append((INSTALLED, "INSTALLED+REMEDY6", True))
    for path, label, patched in targets:
        key = f"closure_{label.lower().replace('+', '_')}"
        run(load(path, key), label, patched=patched)
