#!/usr/bin/env python3
"""Replacement remedy after codex REFUSED escalation 1010b3182bc7ae78 (notice 2744).

The refusal is accepted in full and reproduced independently — with a WIDER class than
the review cited.  v1 found heredoc operators with `_HEREDOC_RE.finditer(line)` over raw
command text, so a heredoc-LOOKING token in a comment or a quoted word started excision
and swallowed a following real governance redirect: a false NEGATIVE in a gate.  Codex
cited two spellings; this seat reproduced four (comment, single-quoted, double-quoted,
and after a command separator).

v2 replaces the raw-line search with a shell lexical scan.  A `<<` counts as a heredoc
operator only when it is reached in unquoted, non-comment state; the delimiter word is
read with shell quoting rules (so `<<'EOF'`, `<<"EOF"`, `<<\\EOF` are literal and any word
shape is accepted, not just identifiers); `<<` and `<<-` keep their distinct terminator
rules; and every construct whose lexical context cannot be established fails CLOSED by
returning the command untouched.

Run:  python3 tools/claude_heredoc_excision_v2_2744.py
      python3 tools/claude_heredoc_excision_v2_2744.py --emit-diff
"""
from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "plugins", "_shared")
MOD = os.path.join(SHARED, "hestia_governance_closure.py")
TEST = os.path.join(SHARED, "hestia_governance_closure_test.py")

CITE = "plugins/_shared/hestia_governance_closure.py"

# ── the module patch ────────────────────────────────────────────────────────────────────

ANCHOR = "def _bash_write_targets(command: str) -> list:"

ADDITION = '''
# ── Heredoc bodies are payload, never a write-position haystack ─────────────────────────
# A heredoc body reaches the tokenizer as ordinary trailing words, which produced two
# measured false-positive shapes: odd quote parity in body prose broke the lexer and the
# unparseable fallback offered EVERY raw token as a write candidate, and redirect prose
# in body text parsed cleanly into a genuine write position.  Both denied members for
# TEXT-MENTIONING a governed path.
#
# Excision must therefore key on real shell OPERATOR position.  A raw substring search
# does not: `# docs <<EOF` and `echo 'x <<EOF'` are not heredocs, and treating them as
# such removes a following real redirect from analysis — a false NEGATIVE in a gate
# (refused review of escalation 1010b3182bc7ae78, reproduced on two seats).  The scan
# below tracks quoting and comments, and returns the command UNTOUCHED wherever lexical
# context cannot be established.

_Q_NONE, _Q_SQ, _Q_DQ = 0, 1, 2
# Characters after which a `#` starts a comment (blank or control operator).  A redirect
# operator is deliberately NOT here: bash writes a file literally named `#foo` for
# `echo hi >#foo`, so `#` after `>` is a filename, not a comment.
_WORD_BREAK = " \\t;&|()"


def _read_heredoc_delim(line: str, j: int) -> tuple:
    """Read the delimiter word at line[j:] under shell quoting rules.

    Returns (delim, literal, next_index, ok).  `literal` is True when ANY part of the word
    was quoted or backslash-escaped — that suppresses expansion in the body.  `ok` is False
    when the word cannot be resolved statically (unterminated quote, trailing backslash,
    an expansion in the delimiter, or no delimiter at all), which must fail closed.
    Delimiters are NOT restricted to identifier shape: shell does not restrict them."""
    n, parts, literal = len(line), [], False
    while j < n:
        c = line[j]
        if c in _WORD_BREAK or c in "<>":
            break
        if c == "'":
            k = line.find("'", j + 1)
            if k < 0:
                return "", False, j, False
            parts.append(line[j + 1:k])
            literal = True
            j = k + 1
            continue
        if c == '"':
            k, buf = j + 1, []
            while k < n and line[k] != '"':
                if line[k] == "\\\\" and k + 1 < n:
                    buf.append(line[k + 1])
                    k += 2
                    continue
                buf.append(line[k])
                k += 1
            if k >= n:
                return "", False, j, False
            parts.append("".join(buf))
            literal = True
            j = k + 1
            continue
        if c == "\\\\":
            if j + 1 >= n:
                return "", False, j, False
            parts.append(line[j + 1])
            literal = True
            j += 2
            continue
        if c in "$`":
            return "", False, j, False  # expansion in the delimiter — undecidable
        parts.append(c)
        j += 1
    delim = "".join(parts)
    if not delim:
        return "", False, j, False  # `<<` with no delimiter — malformed
    return delim, literal, j, True


def _heredoc_ops_in_line(line: str, state: int) -> tuple:
    """Scan one physical line for heredoc operators in genuine operator position.

    `state` carries quoting from previous physical lines (a quoted word may span lines).
    Returns (pending, end_state, ok): `pending` is [(delim, literal, dash)] in operator
    order, `ok` is False when the lexical context could not be established."""
    pending, i, n = [], 0, len(line)
    word_start = True  # a `#` only opens a comment at the start of a word
    while i < n:
        c = line[i]
        if state == _Q_SQ:
            if c == "'":
                state = _Q_NONE
            i += 1
            continue
        if state == _Q_DQ:
            if c == "\\\\" and i + 1 < n:
                i += 2
                continue
            if c == '"':
                state = _Q_NONE
            i += 1
            continue
        if c == "\\\\":
            i += 2  # a trailing backslash escapes the newline; body cannot start there
            word_start = False
            continue
        if c == "'":
            state, i, word_start = _Q_SQ, i + 1, False
            continue
        if c == '"':
            state, i, word_start = _Q_DQ, i + 1, False
            continue
        if c == "#" and word_start:
            return pending, _Q_NONE, True  # rest of the line is a comment
        if c in _WORD_BREAK:
            i += 1
            word_start = True
            continue
        if c == "<" and line.startswith("<<", i):
            if line.startswith("<<<", i):
                i += 3  # here-STRING: no body, no terminator
                word_start = True
                continue
            j = i + 2
            dash = False
            if j < n and line[j] == "-":
                dash = True
                j += 1
            while j < n and line[j] in " \\t":
                j += 1
            delim, literal, j, ok = _read_heredoc_delim(line, j)
            if not ok:
                return pending, state, False
            pending.append((delim, literal, dash))
            i, word_start = j, True
            continue
        i += 1
        word_start = False
    return pending, state, True


def _heredoc_body_is_inert(body: str, literal: bool) -> bool:
    """A body is inert iff nothing in it can become a command.  A quoted/backslashed
    delimiter suppresses all expansion, so the body is literal text.  An UNQUOTED
    delimiter expands the body, so `$(...)`, backticks and `${...}` inside it CAN execute:
    those stay in the haystack.  A body with neither `$` nor a backtick cannot expand."""
    return literal or ("$" not in body and "`" not in body)


def _is_heredoc_terminator(line: str, delim: str, dash: bool) -> bool:
    """Bash accepts the delimiter ALONE on the line.  `<<-` strips leading TABS only —
    not spaces, and not trailing whitespace, either of which makes the line body text."""
    return (line.lstrip("\\t") if dash else line) == delim


def _excise_heredoc_bodies(cmd: str) -> str:
    """Remove inert heredoc BODIES before write-position analysis, keeping the operator
    and terminator lines so redirect/operand parsing is unchanged.  Returns `cmd`
    unchanged wherever the parse is not certain — the gate must not lose a real write."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\\n")
    out, state, i = [], _Q_NONE, 0
    while i < len(lines):
        line = lines[i]
        pending, state, ok = _heredoc_ops_in_line(line, state)
        if not ok:
            return cmd  # lexical context undecidable — fail closed
        out.append(line)
        i += 1
        if state != _Q_NONE:
            if pending:
                return cmd  # operator inside a word still open at EOL — fail closed
            continue  # quoted word continues; no body can start here
        for delim, literal, dash in pending:
            body, j = [], i
            while j < len(lines) and not _is_heredoc_terminator(lines[j], delim, dash):
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                return cmd  # unterminated heredoc — fail closed on the WHOLE command
            out.append("" if _heredoc_body_is_inert("\\n".join(body), literal)
                       else "\\n".join(body))
            out.append(lines[j])
            i = j + 1
    if state != _Q_NONE:
        return cmd  # command ends inside a quote — fail closed
    return "\\n".join(out)


'''

CALL_OLD = '''        try:
            return _bash_write_targets(cmd), None
'''
CALL_NEW = '''        cmd = _excise_heredoc_bodies(cmd)
        try:
            return _bash_write_targets(cmd), None
'''

# ── the repository-native regressions (codex: the suite must PIN the new contract) ──────

TEST_ANCHOR = "ALL = ["

TEST_ADDITION = '''# ── Heredoc payload is not a write-position haystack (escalation 1010b3182bc7ae78) ─────
# Three measured false positives (a governed path merely CITED in heredoc body prose was
# classified write) and — from codex's refusal of the first remedy — the false NEGATIVE
# these must never buy: a heredoc-LOOKING token in a comment or quoted word must NOT
# swallow a following real redirect.
_HD_CITE = "plugins/_shared/hestia_governance_closure.py"


def _hd_commit(body, delim="MSG", quoted=True):
    d = "'%s'" % delim if quoted else delim
    return "git commit-tree e74cc02 -F /dev/stdin <<%s\\n%s\\n%s" % (d, body, delim)


def test_heredoc_body_odd_quote_parity_citing_closure_is_read():
    # odd quote count breaks the lexer; the unparseable fallback then offers EVERY raw
    # token as a write candidate, so the CITED path was reported as the destination
    for prose in ("the author's note on %s", 'the "payload rule on %s',
                  "author's editor's reader's note on %s"):
        cmd = _hd_commit(prose % _HD_CITE)
        v = cls("Bash", {"command": cmd})
        check("heredoc odd-parity body is read", v.classification == "read",
              f"{prose!r} -> {v.classification}")


def test_heredoc_body_redirect_prose_citing_closure_is_read():
    for prose in ("we route stdout > %s in the example",
                  "we route stdout >> %s in the example"):
        cmd = _hd_commit(prose % _HD_CITE)
        v = cls("Bash", {"command": cmd})
        check("heredoc redirect-prose body is read", v.classification == "read",
              f"{prose!r} -> {v.classification}")


def test_heredoc_pseudo_operator_does_not_hide_a_real_write():
    # THE refusal case: none of these first lines is a heredoc operator, so the redirect
    # on line 2 is a real governance write and must stay denied
    for label, cmd in (
        ("comment", "# docs <<EOF\\nprintf x > %s\\nEOF" % _HD_CITE),
        ("single-quoted", "echo 'usage: cmd <<EOF'\\nprintf x > %s\\nEOF" % _HD_CITE),
        ("double-quoted", 'echo "usage <<EOF"\\nprintf x > %s\\nEOF' % _HD_CITE),
        ("after separator", "true; echo 'x <<EOF'\\nprintf x > %s\\nEOF" % _HD_CITE),
    ):
        v = cls("Bash", {"command": cmd})
        check("pseudo-operator hides a write", v.classification == "write",
              f"{label} -> {v.classification}")


def test_unquoted_heredoc_body_with_substitution_stays_write():
    # an UNQUOTED delimiter expands the body, so $(...) inside it can execute
    cmd = _hd_commit("prose $(echo x > %s) more" % _HD_CITE, quoted=False)
    v = cls("Bash", {"command": cmd})
    check("expanding heredoc body stays write", v.classification == "write",
          v.classification)


def test_unterminated_heredoc_citing_closure_fails_closed():
    cmd = "git commit-tree e74cc02 -F /dev/stdin <<'MSG'\\nauthor's note on %s" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("unterminated heredoc fails closed", v.classification == "write",
          v.classification)


def test_heredoc_terminator_requires_the_delimiter_alone():
    # A line that merely CONTAINS the delimiter, or pads it, is body text -- so the
    # heredoc is unterminated and the command must fail closed.  The body carries a
    # redirect so "excision wrongly fired" is OBSERVABLE: a body without a trigger
    # classifies read either way and would assert nothing.
    for tail in ("  MSG", "MSG ", "MSG # done"):
        cmd = "git commit-tree e74cc02 -F /dev/stdin <<'MSG'\\nroute stdout > %s\\n%s" % (
            _HD_CITE, tail)
        v = cls("Bash", {"command": cmd})
        check("loose terminator must not close the body", v.classification == "write",
              f"{tail!r} -> {v.classification}")


def test_dash_heredoc_strips_tabs_but_not_spaces():
    body = "route stdout > %s" % _HD_CITE
    tabbed = "git commit-tree e74cc02 -F /dev/stdin <<-'MSG'\\n\\t%s\\n\\tMSG" % body
    v = cls("Bash", {"command": tabbed})
    check("<<- closes on a tab-indented terminator", v.classification == "read",
          v.classification)
    spaced = "git commit-tree e74cc02 -F /dev/stdin <<-'MSG'\\n %s\\n MSG" % body
    v = cls("Bash", {"command": spaced})
    check("<<- must not accept a space-indented terminator", v.classification == "write",
          v.classification)


def test_expansion_in_the_delimiter_fails_closed():
    cmd = "git commit-tree e74cc02 -F /dev/stdin <<$D\\nroute stdout > %s\\nEOF" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("undecidable delimiter fails closed", v.classification == "write",
          v.classification)


def test_multiple_heredocs_on_one_line_consume_bodies_in_order():
    cmd = ("diff <(cat <<'A'\\nfirst body cites %s\\nA\\n) /dev/null <<'B'\\n"
           "second body cites %s\\nB" % (_HD_CITE, _HD_CITE))
    v = cls("Bash", {"command": cmd})
    check("queued heredoc bodies are not write positions",
          v.classification != "write", v.classification)


def test_non_identifier_heredoc_delimiter_is_handled_not_ignored():
    # shell delimiters are not restricted to identifier shape; v1's regex silently
    # skipped these, leaving the body in the haystack
    cmd = ("git commit-tree e74cc02 -F /dev/stdin <<'END-OF-MSG'\\nroute stdout > %s\\n"
           "END-OF-MSG" % _HD_CITE)
    v = cls("Bash", {"command": cmd})
    check("non-identifier delimiter body is excised", v.classification == "read",
          v.classification)


def test_here_string_is_not_a_heredoc():
    cmd = "cat <<< notes > %s" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("here-string redirect stays write", v.classification == "write",
          v.classification)


def test_real_write_after_a_real_heredoc_stays_write():
    cmd = _hd_commit("harmless prose") + "\\necho x > %s" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("write after heredoc stays write", v.classification == "write",
          v.classification)


'''

TEST_ALL_OLD = "ALL = ["
TEST_ALL_NEW = """ALL = [
    test_heredoc_body_odd_quote_parity_citing_closure_is_read,
    test_heredoc_body_redirect_prose_citing_closure_is_read,
    test_heredoc_pseudo_operator_does_not_hide_a_real_write,
    test_unquoted_heredoc_body_with_substitution_stays_write,
    test_unterminated_heredoc_citing_closure_fails_closed,
    test_heredoc_terminator_requires_the_delimiter_alone,
    test_dash_heredoc_strips_tabs_but_not_spaces,
    test_expansion_in_the_delimiter_fails_closed,
    test_multiple_heredocs_on_one_line_consume_bodies_in_order,
    test_non_identifier_heredoc_delimiter_is_handled_not_ignored,
    test_here_string_is_not_a_heredoc,
    test_real_write_after_a_real_heredoc_stays_write,"""


# ── external battery (kept: it decides BEFORE vs AFTER, which the suite cannot) ─────────

def _hd(body, delim="MSG", quoted=True):
    d = "'%s'" % delim if quoted else delim
    return "git commit-tree e74cc02 -p a4e8fb8 -F /dev/stdin <<%s\n%s\n%s" % (d, body, delim)


# (label, command, expected_after, must_be_unchanged_by_fix)
BATTERY = [
    # --- the false positives the remedy exists to fix ---
    ("FP1  odd apostrophe in body prose + cite",
     _hd("the author's note on %s" % CITE), "read", False),
    ("FP1b odd double-quote in body prose + cite",
     _hd('the "payload rule on %s' % CITE), "read", False),
    ("FP1c three apostrophes (odd) + cite",
     _hd("author's editor's reader's note on %s" % CITE), "read", False),
    ("FP2  redirect operator in body prose + cite",
     _hd("we route stdout > %s in the example" % CITE), "read", False),
    ("FP2b append operator in body prose + cite",
     _hd("we route stdout >> %s in the example" % CITE), "read", False),
    # FP3/FP4 carry a redirect in the BODY so the case is discriminating: without excision
    # the cited path sits in a real write position, so before=write is the FP being fixed
    ("FP3  non-identifier delimiter, redirect prose + cite",
     "git commit-tree e74cc02 -F /dev/stdin <<'END-OF-MSG'\nroute stdout > %s here\n"
     "END-OF-MSG" % CITE, "read", False),
    ("FP4  <<- tab-stripped terminator, redirect prose + cite",
     "git commit-tree e74cc02 -F /dev/stdin <<-'MSG'\n\troute stdout > %s here\n\tMSG" % CITE,
     "read", False),
    # --- codex's refusal: pseudo-operators must NOT excise a real write ---
    ("HOLE1 comment pseudo-operator then real redirect",
     "# docs <<EOF\nprintf x > %s\nEOF" % CITE, "write", True),
    ("HOLE2 single-quoted pseudo-operator then real redirect",
     "echo 'usage: cmd <<EOF'\nprintf x > %s\nEOF" % CITE, "write", True),
    ("HOLE3 double-quoted pseudo-operator then real redirect",
     'echo "usage <<EOF"\nprintf x > %s\nEOF' % CITE, "write", True),
    ("HOLE4 pseudo-operator after a separator then real redirect",
     "true; echo 'x <<EOF'\nprintf x > %s\nEOF" % CITE, "write", True),
    # --- true positives that must not move ---
    ("TP1  real redirect into the closure",
     "echo x > %s" % CITE, "write", True),
    ("TP2  real redirect into closure AFTER a heredoc",
     _hd("harmless prose") + "\necho x > %s" % CITE, "write", True),
    ("TP3  UNQUOTED heredoc body carries a command substitution",
     _hd("prose $(echo x > %s) more" % CITE, quoted=False), "write", True),
    ("TP4  unterminated heredoc with odd quote + cite (fail closed)",
     "git commit-tree e74cc02 -F /dev/stdin <<'MSG'\nauthor's note on %s" % CITE,
     "write", True),
    ("TP5  here-string is not a heredoc",
     "cat <<< notes > %s" % CITE, "write", True),
    # TP6-TP8 pin the FAIL-CLOSED paths. Each body carries redirect prose, so "excision
    # wrongly fired" is OBSERVABLE as read; a body without a trigger would land on read
    # either way and assert nothing.
    ("TP6  space-padded terminator does not close the body (fail closed)",
     "git commit-tree e74cc02 -F /dev/stdin <<'MSG'\nroute stdout > %s here\n  MSG" % CITE,
     "write", True),
    ("TP7  <<- must not accept a SPACE-indented terminator (fail closed)",
     "git commit-tree e74cc02 -F /dev/stdin <<-'MSG'\n route stdout > %s here\n MSG" % CITE,
     "write", True),
    ("TP8  expansion in the delimiter is undecidable (fail closed)",
     "git commit-tree e74cc02 -F /dev/stdin <<$D\nroute stdout > %s here\nEOF" % CITE,
     "write", True),
    ("N1   no governance path anywhere",
     _hd("the author's note on tools/unrelated.py"), "none", True),
]


def build_patched(dst_dir):
    src = open(MOD, encoding="utf-8").read()
    tsrc = open(TEST, encoding="utf-8").read()
    for probe, where in ((ANCHOR, "module anchor"), (CALL_OLD, "module call site")):
        if probe not in src:
            raise SystemExit("%s not found — module drifted; re-derive the patch" % where)
    if TEST_ANCHOR not in tsrc:
        raise SystemExit("test anchor not found — suite drifted; re-derive the patch")
    out = src.replace(ANCHOR, ADDITION.lstrip("\n") + ANCHOR, 1).replace(
        CALL_OLD, CALL_NEW, 1)
    tout = tsrc.replace(TEST_ANCHOR, TEST_ADDITION + TEST_ALL_NEW, 1)
    shutil.copytree(SHARED, dst_dir, dirs_exist_ok=True)
    for path, text in ((os.path.join(dst_dir, "hestia_governance_closure.py"), out),
                       (os.path.join(dst_dir, "hestia_governance_closure_test.py"), tout)):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return (src, out), (tsrc, tout)


def load(dirpath):
    import importlib.util
    p = os.path.join(dirpath, "hestia_governance_closure.py")
    name = "gc_%x" % (abs(hash(dirpath)) & 0xffffffff)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m  # dataclass() resolves the owning module by name
    spec.loader.exec_module(m)
    return m


def run_battery(mod):
    return {name: mod.classify("Bash", {"command": cmd}).classification
            for name, cmd, _e, _p in BATTERY}


def shell_truth(cmd, scratch, tag):
    """Arm C: does bash ACTUALLY write?  The governance path is swapped for a scratch
    file, so the real surface is never a live redirect target."""
    target = os.path.join(scratch, "shell-%s.txt" % tag)
    subprocess.run(["bash", "-c", cmd.replace(CITE, target)],
                   capture_output=True, check=False)
    return os.path.exists(target)


def count_tests(dirpath):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--collect-only",
                        os.path.join(dirpath, "hestia_governance_closure_test.py")],
                       capture_output=True, text=True, cwd=dirpath)
    for ln in reversed((r.stdout or "").strip().splitlines()):
        if "test" in ln and ln.split()[0].isdigit():
            return int(ln.split()[0])
    return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-diff", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="closure-v2-")
    patched_dir = os.path.join(tmp, "patched")
    (src, out), (tsrc, tout) = build_patched(patched_dir)

    if args.emit_diff:
        for a, b, path in ((src, out, "plugins/_shared/hestia_governance_closure.py"),
                           (tsrc, tout, "plugins/_shared/hestia_governance_closure_test.py")):
            sys.stdout.writelines(difflib.unified_diff(
                a.splitlines(True), b.splitlines(True),
                fromfile="a/" + path, tofile="b/" + path))
        return 0

    before, after = load(SHARED), load(patched_dir)
    rb, ra = run_battery(before), run_battery(after)

    print("--- battery: installed -> proposed (arm C = what bash actually does) ---")
    ok = True
    for name, cmd, expected, pinned in BATTERY:
        good = ra[name] == expected
        moved = rb[name] != ra[name]
        note = "REGRESSION: pinned case moved" if (pinned and moved) else (
            "fixed" if moved else "unchanged")
        if pinned and moved:
            good = False
        # arm C only for the cases that assert a real write survives
        truth = ""
        if name.startswith(("HOLE", "TP1", "TP2")):
            wrote = shell_truth(cmd, tmp, name.split()[0])
            truth = "  shell_wrote=%s" % wrote
            if wrote and ra[name] != "write":
                good, note = False, "HOLE: bash writes, classifier says " + ra[name]
        ok &= good
        print("  %-50s %-5s -> %-5s  %s  %s%s" % (
            name[:50], rb[name], ra[name], "OK " if good else "BAD", note, truth))

    print("\n--- differential vs the REFUSED v1 (v2 must fix exactly what v1 broke) ---")
    v1_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "claude_heredoc_excision_proposal_1010b318.py")
    v1_ok = False
    if os.path.exists(v1_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("v1_proposal", v1_path)
        v1 = importlib.util.module_from_spec(spec)
        sys.modules["v1_proposal"] = v1
        spec.loader.exec_module(v1)
        v1_dir = os.path.join(tmp, "v1")
        v1.build_patched(v1_dir)
        rv1 = run_battery(load(v1_dir))
        v1_broken = [n for n, _c, e, _p in BATTERY if rv1[n] != e]
        v2_broken = [n for n, _c, e, _p in BATTERY if ra[n] != e]
        for n in v1_broken:
            print("  v1 FAILS  %-46s v1=%-5s v2=%s" % (n[:46], rv1[n], ra[n]))
        v1_ok = bool(v1_broken) and not v2_broken
        print("  v1 fails %d case(s), v2 fails %d — differential is real: %s"
              % (len(v1_broken), len(v2_broken), v1_ok))
    else:
        print("  v1 proposal not present; differential SKIPPED (not evidence)")

    print("\n--- repository suite against the PATCHED copy (module AND tests) ---")
    n_before, n_after = count_tests(SHARED), count_tests(patched_dir)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q",
                        os.path.join(patched_dir, "hestia_governance_closure_test.py")],
                       capture_output=True, text=True, cwd=patched_dir)
    tail = (r.stdout or "").strip().splitlines()
    print("  collected: installed=%d patched=%d (+%d new regressions)"
          % (n_before, n_after, n_after - n_before))
    print("  %s" % (tail[-1] if tail else r.stderr[-300:]))
    suite_ok = r.returncode == 0 and n_after > n_before

    print("\n--- sabotage controls (each must be CAUGHT) ---")
    controls = {
        # defang the excision entirely: the false positives must come back
        "excision disabled":
            ('    if "<<" not in cmd:\n        return cmd\n',
             '    if "<<" not in cmd:\n        return cmd\n    return cmd  # SABOTAGE\n'),
        # restore v1's blindness: ignore lexical state, so pseudo-operators excise again
        "lexical state ignored":
            ('        if c == "#" and word_start:\n'
             '            return pending, _Q_NONE, True  # rest of the line is a comment\n',
             '        if False:\n            pass\n'),
        # loosen the terminator back to .strip(): padded terminators close the body
        "terminator loosened to strip()":
            ('    return (line.lstrip("\\t") if dash else line) == delim\n',
             '    return line.strip() == delim\n'),
    }
    caught_all = True
    for label, (old, new) in controls.items():
        sab_dir = os.path.join(tmp, "sab-" + label.split()[0])
        shutil.copytree(SHARED, sab_dir, dirs_exist_ok=True)
        text = open(os.path.join(patched_dir, "hestia_governance_closure.py"),
                    encoding="utf-8").read()
        if old not in text:
            print("  %-32s CONTROL INERT — anchor missing, do not trust it" % label)
            caught_all = False
            continue
        with open(os.path.join(sab_dir, "hestia_governance_closure.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(text.replace(old, new, 1))
        try:
            rs = run_battery(load(sab_dir))
            caught = [n for n, _c, e, _p in BATTERY if rs[n] != e]
        except Exception as exc:  # a control that cannot even import still counts as caught
            caught = ["import: %s" % type(exc).__name__]
        caught_all &= bool(caught)
        print("  %-32s caught=%-5s  first=%s" % (
            label, bool(caught), caught[0][:44] if caught else "NONE — control is INERT"))

    print("\nRESULT: battery=%s suite=%s sabotage-controls=%s" % (ok, suite_ok, caught_all))
    return 0 if (ok and suite_ok and caught_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
