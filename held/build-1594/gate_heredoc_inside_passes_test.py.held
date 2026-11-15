#!/usr/bin/env python3
"""Command scope: the in-workspace passes judge the same text pass 3 does, with data heredocs removed (#1594).

Pass 1 (the workspace-prefix scan) and pass 2 (relative tokens) read the RAW command, so they judged the body
of a QUOTED data heredoc that pass 3 strips (`_strip_data_heredocs`). Prose naming `<ws>/..` was refused
`mrh.command` and opened a scope request for the workspace's PARENT (McNugget, 2026-11-13, scope-577f201a0fce
for the home directory): `cat > notes.md <<'EOF'` with a row quoting `~/repos/..`.

Now all three passes judge one text. A body the shell runs (`sh <<EOF`), an interpreter's path literals
(`python3 <<EOF`), and every `$( … )` in an UNQUOTED-delimiter body are kept by `_strip_data_heredocs`, so
they stay judged.

Run:  ./tools/gate_heredoc_inside_passes_test.py
      HESTIA_SCOPE_BATTERY_CORE=<path> ./tools/gate_heredoc_inside_passes_test.py   (a staged core)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
_staged = os.getenv("HESTIA_SCOPE_BATTERY_CORE")
if _staged:
    _spec = importlib.util.spec_from_file_location("hestia_gate_core", _staged)
    G = importlib.util.module_from_spec(_spec)
    sys.modules["hestia_gate_core"] = G
    _spec.loader.exec_module(G)
else:
    import hestia_gate_core as G  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAIL.append(name)


def main() -> int:
    base = tempfile.mkdtemp(prefix="hd-")
    ws = f"{base}/ws"
    for d in ("granted", "other"):
        os.makedirs(f"{ws}/{d}")
    open(f"{ws}/other/secret", "w").close()
    out = f"{ws}/granted/note.md"
    scopes = ("granted",)

    def reach(c):
        return G.command_scope_reach(c, scopes, ws, cwd=f"{ws}/granted")

    def doc(body, delim="'EOF'", head=f"cat > {out}"):
        return f"{head} <<{delim}\n{body}\nEOF"

    # ---- quoted data bodies are text in EVERY pass ----
    ok, off, _ = reach(doc(f"see `{ws}/..` for the parent"))
    check("pass 1: '<ws>/..' in a quoted data body is text (the #1594 act)", ok, off)
    ok, off, _ = reach(doc(f"the secret lives at {ws}/other/secret"))
    check("pass 1: an ungranted <ws> path in a quoted data body is text", ok, off)
    ok, off, _ = reach(doc("relative mention: other/secret and ../other/secret"))
    check("pass 2: an ungranted relative path in a quoted data body is text", ok, off)
    ok, off, _ = reach(doc(f"{ws}/..", delim='"EOF"'))
    check("a double-quoted delimiter is literal too", ok, off)
    ok, off, _ = reach(doc(f"{ws}/..", delim="\\EOF"))
    check("a backslash-quoted delimiter is literal too", ok, off)
    ok, off, _ = reach(doc(f"{ws}/..", head=f"tee {out}"))
    check("tee as the consumer: data", ok, off)

    # ---- what stays judged ----
    ok, off, _ = reach(doc(f"cat {ws}/other/secret", delim="EOF", head="sh"))
    check("must deny: a body the SHELL runs is judged (pass 1)", not ok, off)
    ok, off, _ = reach(doc(f"open('{ws}/other/secret')", head="python3"))
    check("must deny: an interpreter's path literal is judged", not ok, off)
    ok, off, _ = reach(doc(f"$(cat {ws}/other/secret)", delim="EOF"))
    check("must deny: $( ) in an UNQUOTED data body runs and is judged", not ok, off)
    ok, off, _ = reach(f"cat > {out} <<'EOF' && cat {ws}/other/secret\nx\nEOF")
    check("must deny: a command chained on the heredoc's own line is judged", not ok, off)
    ok, off, _ = reach(f"cat {ws}/other/secret > {out} <<'EOF'\nx\nEOF")
    check("must deny: an operand on the heredoc line is judged", not ok, off)
    ok, off, _ = reach(doc("x") + f"\ncat {ws}/other/secret")
    check("must deny: a line after the terminator is a command again", not ok, off)
    ok, off, _ = reach(f"cat {ws}/../x")
    check("must deny: '<ws>/..' outside a heredoc is still judged where it lands", not ok, off)

    print(f"\n{'FAIL' if FAIL else 'PASS'}: {len(FAIL)} failing")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
