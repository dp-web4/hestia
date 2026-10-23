#!/usr/bin/env python3
"""Command scope: grep-family PATTERN operands, and a toolchain reached by GRANT (SAGE #368, #1241 recut).

Measured 2026-10-05 on 2,187 legion-being calls replayed through the one gate with the being under
its SEAT's workspace (dp's ruling: a being judged by anything else is judged by a different law
than its seat): SAGE #368, which hands the gate the composed command, denied 37/37 `check` and
84/84 `game` ("'miniforge3' is not granted": the sandbox's `--ro-bind <home>/miniforge3` and the
interpreter itself) and one `search` ("'[^' is not granted": a fragment of the being's own regex).

The recut (cbp-claude's review of #1241, 2026-10-14): patterns are recognised INSIDE the shell
grammar (`_CMD_SPECS`, `_Found.patterns`), never by rewriting the command text. #1241's text mask
re-quoted `"$(...)"` as an inert `'$(...)'` and admitted acts main refuses; those rows are the
must-deny regressions below.

The toolchain (#1377, Nova's HOLD): the first apply exempted roots named by an environment variable,
HESTIA_TOOL_ROOTS. Nothing proved a governed member could not set it (a seat's systemd unit is inside
its own grant on Legion), and the exemption was lexical, so a symlink under the root read an ungranted
repo. Removed. The being's interpreter is reached by an operator's recursive `path:<root>/**` grant:
vault-held, witnessed, revocable, matched on the realpath.

Run:  ./tools/gate_grep_patterns_and_toolchain_grant_test.py
      HESTIA_SCOPE_BATTERY_CORE=<path> ./tools/gate_grep_patterns_and_toolchain_grant_test.py   (a staged core)
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
    ws = tempfile.mkdtemp(prefix="ws-")
    for d in ("granted/sub", "tools/conda/bin", "other"):
        os.makedirs(f"{ws}/{d}")
    open(f"{ws}/other/x", "w").close()
    open(f"{ws}/granted/f", "w").close()
    scopes = ("granted",)

    def reach(c):
        return G.command_scope_reach(c, scopes, ws, cwd=f"{ws}/granted")

    def denied(c, off=None):
        ok, o, _ = reach(c)
        return (not ok) and (off is None or o == off or (o or "").startswith(off)), o

    # ---- the toolchain is an operator's RECURSIVE PATH GRANT, never an environment variable ----
    conda = f"{ws}/tools/conda"
    check_line = (f"bwrap --ro-bind {conda} {conda} --setenv PATH {conda}/bin:/usr/bin "
                  f"{conda}/bin/python3 -m pytest {ws}/granted/sub")
    granted_tool = scopes + (f"path:{conda}/**",)

    def reach_with(c, sc):
        return G.command_scope_reach(c, sc, ws, cwd=f"{ws}/granted")

    ok, off, _ = reach(check_line)
    check("without a grant, the interpreter is an ungranted reach (unchanged)", not ok and off == "tools", off)
    ok, off, _ = reach_with(check_line, granted_tool)
    check("an operator's recursive grant on the toolchain admits the check-shaped line", ok, off)
    ok, off, _ = reach_with(f"{conda}/bin/python3 {ws}/other/stepper.py --instance {ws}/granted", granted_tool)
    check("operands outside the granted toolchain are still judged (game-shaped line)", not ok and off == "other", off)
    ok, off, _ = reach_with(f"cat {ws}/tools/condaX/secret", granted_tool)
    check("a sibling of the granted root is not under it (boundary, not prefix)", not ok, off)
    ok, off, _ = reach_with(f"{conda}/bin/python3 -c pass", scopes + (f"path:{conda}",))
    check("an EXACT grant on the root does not reach its interpreter", not ok, off)

    os.symlink(f"{ws}/other", f"{conda}/escape")
    ok, off, _ = reach_with(f"cat {conda}/escape/x", granted_tool)
    check("must deny: a symlink under the granted toolchain into an ungranted dir (realpath)", not ok and off == "other", off)
    secret = tempfile.mkdtemp(prefix="s-")
    os.makedirs(f"{secret}/.ssh")
    open(f"{secret}/.ssh/id_x", "w").close()
    os.symlink(f"{secret}/.ssh/id_x", f"{conda}/link")
    ok, off, _ = reach_with(f"cat {conda}/link", granted_tool)
    check("egress is judged before the grant: a link to a forbidden target denies", not ok and ".ssh" in (off or ""), off)

    # A caller-set environment is not authority: the variable #1377 first shipped does nothing,
    # whether it is in the gate's own environment or written as a prefix on the command.
    name = "HESTIA_TOOL_" + "ROOTS"
    os.environ[name] = conda
    try:
        ok, off, _ = reach(check_line)
        check("must deny: HESTIA_TOOL_ROOTS in the gate's environment grants nothing", not ok and off == "tools", off)
        ok, off, _ = reach(f"{name}={conda} {check_line}")
        check("must deny: HESTIA_TOOL_ROOTS as a command prefix grants nothing", not ok, off)
        ok, off, _ = reach(f"cat {conda}/escape/x")
        check("must deny: the symlink escape #1377 admitted under HESTIA_TOOL_ROOTS", not ok and off in ("tools", "other"), off)
    finally:
        os.environ.pop(name, None)
    check("the gate core carries no tool-roots declaration", not hasattr(G, "TOOL_ROOTS_ENV") and not hasattr(G, "_tool_roots"))

    # ---- grep-family PATTERN operands are text, recognised by the grammar ----
    ok, off, _ = reach(f"git --no-pager -C {ws}/granted grep -n -I -E --max-count=15 -e 'ft09\\.py.*bytes|{ws}[^ ]*ft09\\.py' -- {ws}/granted/sub")
    check("a git grep -e pattern is text, not a path (search-shaped line)", ok, off)
    ok, off, _ = reach(f"git --no-pager -C {ws}/granted grep -n -e 'x' -- {ws}/other")
    check("git grep's pathspec after -- is still judged", not ok and off == "other", off)
    ok, off, _ = reach(f"git -C {ws}/granted grep -C 3 '{ws}/other/x' -- {ws}/granted/sub")
    check("git grep's -C is context lines, and its positional pattern is text", ok, off)
    d, off = denied(f"git -C {ws}/other grep x")
    check("git's own -C before the subcommand is still a judged directory", d, off)
    ok, off, _ = reach(f"grep -rn '{ws}/other/never-opened' {ws}/granted/sub")
    check("grep's positional pattern is text", ok, off)
    ok, off, _ = reach(f"grep -rn needle {ws}/other")
    check("grep's file operand is still judged", not ok and off == "other", off)
    ok, off, _ = reach(f"grep -f {ws}/other/patterns {ws}/granted/sub")
    check("grep -f's operand IS a file and is judged", not ok and off == "other", off)
    ok, off, _ = reach(f"rg --regexp={ws}/other/x {ws}/granted")
    check("rg --regexp=... is text", ok, off)
    ok, off, _ = reach(f"grep -e{ws}/other/x {ws}/granted")
    check("an attached -e pattern is text", ok, off)
    ok, off, _ = reach(f"cat {ws}/other/x | grep -e '{ws}/other' ")
    check("per simple command: cat's operand is still judged", not ok and off == "other", off)
    d, off = denied(f"grep -e 'unbalanced {ws}/other/x")
    check("an unreadable line is judged as before, never less", d, off)

    # ---- the same text as a pattern AND an operand: the operand is judged ----
    d, off = denied(f"grep '{ws}/other' {ws}/other")
    check("a path that is both the pattern and the operand is judged", d and off == "other", off)
    d, off = denied(f"grep -e '{ws}/other/x' -- {ws}/other/x")
    check("a pattern does not cover its own text named again as a file", d and off == "other", off)

    # ---- anything an expansion decides stays live (cbp-claude's must-deny rows) ----
    for c, why in ((f'grep -n x "$(cat /etc/shadow)"', "a substitution in a grep file operand"),
                   (f'grep x f; echo "$(cat /root/secret)"', "a substitution after a grep"),
                   ('grep -e foo "`cat /root/x`"', "backticks in a grep operand"),
                   ("grep x <<EOF\n$(cat /root/y)\nEOF", "a substitution in a heredoc to grep")):
        d, off = denied(c)
        check(f"must deny: {why}", d, off)
    d, off = denied(f'grep "$(cat {ws}/other/x)" {ws}/granted/f')
    check("must deny: a substitution INSIDE a pattern is lifted out and judged", d and off == "other", off)
    d, off = denied(f'P={ws}/other/x; grep "$P" {ws}/granted/f')
    check("must deny: a pattern from a variable is not a recorded literal", d and off == "other", off)
    d, off = denied(f"grep {ws}/other/* {ws}/granted/f")
    check("must deny: an UNQUOTED glob in the pattern position expands first", d and off == "other", off)

    # ---- only grep-family heads: other programs' arguments are judged as before ----
    d, off = denied(f"cat '{ws}/other/x'")
    check("a quoted operand of a non-pattern command is judged", d and off == "other", off)
    d, off = denied(f"python3 -c 'print(1)' {ws}/other/x")
    check("a non-grep program's operand is judged", d and off == "other", off)
    for c in (f"echo '{ws}/other/x'", f"git commit -m 'see {ws}/other/x'", f"tr '{ws}/other/x' y < {ws}/granted/f"):
        d, off = denied(c)
        check(f"a non-grep DATA operand is judged as before: {c.split()[0]}", d and off == "other", off)
    # sed and awk share grep's pattern-first grammar, but their PROGRAMS read and write files
    # (`sed 'w F'`, awk's `print > "F"`): only grep-family heads are exempt.
    for c in (f"sed 'w {ws}/other/x' {ws}/granted/f", f"sed -n '1r {ws}/other/x' {ws}/granted/f",
              f"awk '{{print > \"{ws}/other/x\"}}' {ws}/granted/f"):
        d, off = denied(c)
        check(f"must deny: a {c.split()[0]} program naming a file is judged", d and off == "other", off)
    # An unquoted expansion in the pattern position can split into an option (`X=-f` makes
    # `$X<ws>/...` a FILE operand). It is not recorded as a pattern, and pass 3 refuses it as
    # unenumerated too: two layers, so this row stays red if either holds.
    d, off = denied(f"grep $X{ws}/other/x {ws}/granted/f")
    check("must deny: an unquoted expansion in the pattern position", d, off)

    print("\nall checks pass" if not FAIL else f"\n{len(FAIL)} FAILED: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
