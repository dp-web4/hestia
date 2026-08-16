#!/usr/bin/env python3
"""Third remedy, after codex DISSENTED from v2 (notice 2751, review of 87a65831d15c5f01).

v1 was refused for four pseudo-operator spellings.  v2 was dissented from for three MORE
constructs bash lexes differently: `((1 << 2))` and `$((1 << 2))` are arithmetic LEFT
SHIFTS, not heredoc operators, and bash removes a backslash-newline BEFORE deciding where
a body starts, so `cat <<EOF \\` + `> governed` is one logical line whose redirect is real.
All three reproduce on this seat; each converted a real Bash write from `write` to `read`.

Enumerating spellings is losing: two reviews, seven constructs, and the class is bash's
grammar.  v3 therefore changes three things rather than adding a fourth spelling list:

  1. arithmetic contexts (`((`, `$((`, `$[`) are skipped, and a delimiter carrying `]`
     or `}` — the shape a subscript produces — fails closed by RULE rather than by the
     accident that no later line happens to match it;
  2. physical lines are folded into LOGICAL lines before a body boundary is decided;
  3. the body model is exact instead of coarse.  v2 kept an entire unquoted body whenever
     it held any `$`, which left codex's false positives open.  Bash does not re-parse an
     expansion RESULT as shell syntax, so only `$(...)`, backticks and `${...}` CONTENTS
     can run; the surrounding prose cannot.

  4. and the part that answers the structural criticism rather than the three cases:
     `--fuzz` GENERATES the construct space (arithmetic, continuations, quoting, comments,
     delimiters, terminators, bodies, suffix redirects) and decides every case against
     bash itself, so an unmodelled construct is found by search rather than by review.

Run:  python3 tools/claude_heredoc_excision_v3_2751.py
      python3 tools/claude_heredoc_excision_v3_2751.py --fuzz
      python3 tools/claude_heredoc_excision_v3_2751.py --emit-diff

Superseded context — the refusal v2 answered (kept: v3 must not reopen it):

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


def _skip_arithmetic(line: str, i: int, opener: str, closer: str) -> int:
    """Index just past the arithmetic region opening at line[i:], or -1 if it does not
    close on this line (which must fail closed).

    Inside arithmetic, `<<` is a LEFT SHIFT and consumes no body.  Verified against bash:
    `((1 << 2))` and `$((1 << 2))` followed by more lines run those lines as commands,
    while a heredoc would have swallowed them.  Reading such a shift as an operator is
    how v2 removed a following real redirect (codex, notice 2751)."""
    depth, j, n = 1, i + len(opener), len(line)
    while j < n:
        if closer == "]":
            if line[j] == "[":
                depth += 1
            elif line[j] == "]":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
            continue
        if line.startswith("((", j):
            depth += 1
            j += 2
            continue
        if line.startswith("))", j):
            depth -= 1
            j += 2
            if depth == 0:
                return j
            continue
        j += 1
    return -1


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
    if "]" in delim or "}" in delim:
        # `a[1<<2]=q` and `${a[1<<2]}` are arithmetic SUBSCRIPTS, not heredocs (bash runs
        # the following lines).  v2 survived these only because no later line happened to
        # equal `2]=q`; that is luck, not a rule.  Fail closed by rule instead.
        return "", False, j, False
    return delim, literal, j, True


def _heredoc_ops_in_line(line: str, state: int) -> tuple:
    """Scan one physical line for heredoc operators in genuine operator position.

    `state` carries quoting from previous physical lines (a quoted word may span lines).
    Returns (pending, end_state, ok, continued): `pending` is [(delim, literal, dash)] in
    operator order, `ok` is False when the lexical context could not be established, and
    `continued` is True when the line ends in an escaped newline — bash removes that
    backslash-newline BEFORE deciding where a body starts, so the caller must fold the
    next physical line into this one rather than reading it as body text."""
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
            if c == "\\\\":
                if i + 1 >= n:
                    return pending, state, True, True  # continuation inside "..."
                i += 2
                continue
            if c == '"':
                state = _Q_NONE
            i += 1
            continue
        if c == "\\\\":
            if i + 1 >= n:
                return pending, state, True, True  # escaped newline: the line continues
            i += 2
            word_start = False
            continue
        if c == "(" and line.startswith("((", i):
            k = _skip_arithmetic(line, i, "((", "))")
            if k < 0:
                return pending, state, False, False
            i, word_start = k, False
            continue
        # `$((expr))` needs no branch of its own: the scan reaches its `((` on the next
        # character and the arithmetic skip above consumes it.  A separate `$((` branch
        # was written first and its sabotage control stayed GREEN, which is what exposed
        # it as dead code.  `$[expr]` is the deprecated spelling and has no `((`.
        if c == "$" and line.startswith("$[", i):
            k = _skip_arithmetic(line, i, "$[", "]")
            if k < 0:
                return pending, state, False, False
            i, word_start = k, False
            continue
        if c == "'":
            state, i, word_start = _Q_SQ, i + 1, False
            continue
        if c == '"':
            state, i, word_start = _Q_DQ, i + 1, False
            continue
        if c == "#" and word_start:
            return pending, _Q_NONE, True, False  # rest of the line is a comment
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
                return pending, state, False, False
            pending.append((delim, literal, dash))
            i, word_start = j, True
            continue
        i += 1
        word_start = False
    return pending, state, True, False


def _heredoc_body_residue(body: str, literal: bool) -> str:
    """The part of a heredoc body that can still become a command.

    A quoted or backslashed delimiter suppresses ALL expansion, so nothing in the body can
    run and the residue is empty.  With an UNQUOTED delimiter the body IS expanded — but
    bash does not re-parse the expansion RESULT as shell syntax.  Only the text inside
    `$(...)`, backticks and `${...}` can execute; the prose around them is data.  v2 kept
    the ENTIRE body whenever it contained any `$`, which left `$USER docs say > governed`
    denied although bash writes nothing (codex, notice 2751).  Keeping only substitution
    CONTENTS is exact.  Anything that cannot be delimited statically returns the whole
    body: too much residue is a false positive the member can appeal, too little is a hole
    in the gate."""
    if literal or ("$" not in body and "`" not in body):
        return ""
    keep, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\\\" and i + 1 < n:
            i += 2  # `\\$` and an escaped backtick do not expand
            continue
        if c == "`":
            k = body.find("`", i + 1)
            if k < 0:
                return body  # unbalanced — fail closed
            keep.append(body[i + 1:k])
            i = k + 1
            continue
        if c == "$" and (body.startswith("$(", i) or body.startswith("${", i)):
            op, cl = ("(", ")") if body[i + 1] == "(" else ("{", "}")
            depth, j = 1, i + 2
            while j < n and depth:
                if body[j] == "\\\\":
                    j += 2
                    continue
                if body[j] == op:
                    depth += 1
                elif body[j] == cl:
                    depth -= 1
                j += 1
            if depth:
                return body  # unbalanced — fail closed
            keep.append(body[i + 2:j - 1])
            i = j
            continue
        i += 1
    return "\\n".join(k for k in keep if k.strip())


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
        while True:
            pending, nstate, ok, continued = _heredoc_ops_in_line(line, state)
            if not ok:
                return cmd  # lexical context undecidable — fail closed
            if not continued:
                break
            if i + 1 >= len(lines):
                return cmd  # command ends on an escaped newline — fail closed
            # bash removes the backslash-newline BEFORE deciding where a body starts, so
            # the next PHYSICAL line belongs to this LOGICAL one and is not body text
            line = line[:-1] + lines[i + 1]
            i += 1
        state = nstate
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
            out.append(_heredoc_body_residue("\\n".join(body), literal))
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


def test_unquoted_delimiter_inert_body_is_still_excised():
    # the only excision route through _heredoc_body_is_inert rather than the
    # literal-delimiter shortcut: an UNQUOTED delimiter whose body cannot expand
    # (no $ and no backtick) is still payload, not a write position
    for prose in ("route stdout > %s here", "route stdout >> %s here"):
        cmd = _hd_commit(prose % _HD_CITE, quoted=False)
        v = cls("Bash", {"command": cmd})
        check("unquoted inert heredoc body is excised", v.classification == "read",
              f"{prose!r} -> {v.classification}")


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


def test_arithmetic_shift_is_not_a_heredoc_operator():
    # codex, notice 2751: `<<` inside arithmetic is a LEFT SHIFT.  Reading it as an
    # operator made the NEXT line a body and removed a real redirect from the haystack.
    # Verified against bash: these commands consume no body and DO create the file.
    for label, cmd in (
        ("arithmetic command", "((1 << 2))\\nprintf x > %s\\n2" % _HD_CITE),
        ("arithmetic expansion",
         "printf '%%s\\\\n' $((1 << 2))\\nprintf x > %s\\n2" % _HD_CITE),
        ("deprecated $[ ]", "x=$[1 << 2]\\nprintf x > %s\\n2" % _HD_CITE),
    ):
        v = cls("Bash", {"command": cmd})
        check("arithmetic shift hides a write", v.classification == "write",
              f"{label} -> {v.classification}")


def test_subscript_delimiter_shape_fails_closed():
    # `a[1<<2]=q` and `${a[1<<2]}` are subscripts, not heredocs.  A delimiter carrying
    # `]` or `}` is rejected by RULE; v2 survived these only because no later line
    # happened to equal `2]=q`.
    for cmd in ("a[1<<2]=q\\nprintf x > %s\\n2]=q" % _HD_CITE,
                "echo ${a[1<<2]}\\nprintf x > %s\\n2]}" % _HD_CITE):
        v = cls("Bash", {"command": cmd})
        check("subscript shape must not excise", v.classification == "write",
              v.classification)


def test_escaped_newline_folds_before_the_body_boundary():
    # bash removes the backslash-newline FIRST, so the redirect is on the same logical
    # line as the operator and executes; the body starts only on the line after that.
    cmd = "cat <<EOF \\\\\\n> %s\\npayload\\nEOF" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("continued operator line hides a write", v.classification == "write",
          v.classification)


def test_expansion_result_is_not_reparsed_as_shell():
    # v2 kept an ENTIRE unquoted body whenever it held any `$`, so ordinary prose was
    # denied for CITING a governed path.  bash expands the body but never re-parses the
    # RESULT as shell syntax: only substitution CONTENTS can run.
    for body in ("$USER documentation says > %s",
                 "$(printf harmless) documentation says > %s",
                 "prose ${UNSET:-x} says > %s"):
        cmd = "cat >/dev/null <<MSG\\n%s\\nMSG" % (body % _HD_CITE)
        v = cls("Bash", {"command": cmd})
        check("expansion result is not shell", v.classification == "read",
              f"{body!r} -> {v.classification}")
    # ...but the CONTENTS still are, so a write inside the substitution stays a write
    cmd = "cat >/dev/null <<MSG\\nprose $(printf x > %s) more\\nMSG" % _HD_CITE
    v = cls("Bash", {"command": cmd})
    check("substitution contents stay in the haystack", v.classification == "write",
          v.classification)


'''

TEST_ALL_OLD = "ALL = ["
TEST_ALL_NEW = """ALL = [
    test_heredoc_body_odd_quote_parity_citing_closure_is_read,
    test_heredoc_body_redirect_prose_citing_closure_is_read,
    test_heredoc_pseudo_operator_does_not_hide_a_real_write,
    test_unquoted_delimiter_inert_body_is_still_excised,
    test_unquoted_heredoc_body_with_substitution_stays_write,
    test_unterminated_heredoc_citing_closure_fails_closed,
    test_heredoc_terminator_requires_the_delimiter_alone,
    test_dash_heredoc_strips_tabs_but_not_spaces,
    test_expansion_in_the_delimiter_fails_closed,
    test_multiple_heredocs_on_one_line_consume_bodies_in_order,
    test_non_identifier_heredoc_delimiter_is_handled_not_ignored,
    test_here_string_is_not_a_heredoc,
    test_real_write_after_a_real_heredoc_stays_write,
    test_arithmetic_shift_is_not_a_heredoc_operator,
    test_subscript_delimiter_shape_fails_closed,
    test_escaped_newline_folds_before_the_body_boundary,
    test_expansion_result_is_not_reparsed_as_shell,"""


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
    # FP5/FP6: UNQUOTED delimiter, inert body, redirect prose. Gap found by kimi-code
    # (review 2742): this is the only excision route that goes through
    # _heredoc_body_is_inert rather than the literal-delimiter shortcut, and the battery
    # had no instance of it. Bash confirms the body is stdin data either way.
    ("FP5  UNQUOTED delimiter, inert body, > prose + cite",
     _hd("route stdout > %s here" % CITE, quoted=False), "read", False),
    ("FP6  UNQUOTED delimiter, inert body, >> prose + cite",
     _hd("route stdout >> %s here" % CITE, quoted=False), "read", False),
    # --- codex's refusal: pseudo-operators must NOT excise a real write ---
    ("HOLE1 comment pseudo-operator then real redirect",
     "# docs <<EOF\nprintf x > %s\nEOF" % CITE, "write", True),
    ("HOLE2 single-quoted pseudo-operator then real redirect",
     "echo 'usage: cmd <<EOF'\nprintf x > %s\nEOF" % CITE, "write", True),
    ("HOLE3 double-quoted pseudo-operator then real redirect",
     'echo "usage <<EOF"\nprintf x > %s\nEOF' % CITE, "write", True),
    ("HOLE4 pseudo-operator after a separator then real redirect",
     "true; echo 'x <<EOF'\nprintf x > %s\nEOF" % CITE, "write", True),
    # --- codex's DISSENT from v2 (notice 2751): three constructs bash lexes differently.
    # Each reproduced on this seat as write -> read with bash actually creating the file.
    ("HOLE5 arithmetic command shift is not a heredoc operator",
     "((1 << 2))\nprintf x > %s\n2" % CITE, "write", True),
    ("HOLE6 arithmetic EXPANSION shift is not a heredoc operator",
     "printf '%%s\\n' $((1 << 2))\nprintf x > %s\n2" % CITE, "write", True),
    ("HOLE7 escaped newline folds before the body boundary",
     "cat <<EOF \\\n> %s\npayload\nEOF" % CITE, "write", True),
    # --- codex's second point: the FP class v2 left open.  Bash writes nothing here; the
    # body is prose that merely EXPANDS.  An expansion result is not re-parsed as shell.
    # HOLE8/HOLE9 and FP9 exist because the first pass of these controls came back INERT:
    # every case was already saved by some OTHER mechanism, so nothing measured the one
    # under test.  Each of these discriminates exactly one.
    ("HOLE8 deprecated $[ ] shift then real redirect",
     "x=$[1 << 2]\nprintf x > %s\n2]" % CITE, "write", True),
    ("HOLE9 array subscript shift then real redirect",
     "a[1<<2]=q\nprintf x > %s\n2]=q" % CITE, "write", True),
    # only the $[ ] SKIP yields read here; the delimiter-shape rule fails the whole
    # command closed instead, so this case separates the two mechanisms
    ("FP9  $[ ] shift beside a real heredoc citing the path",
     "x=$[1 << 2]\ngit commit-tree e74cc02 -F /dev/stdin <<'MSG'\n"
     "route stdout > %s here\nMSG" % CITE, "read", False),
    ("FP7  parameter expansion beside redirect prose",
     "cat >/dev/null <<MSG\n$USER documentation says > %s\nMSG" % CITE, "read", False),
    ("FP8  benign substitution beside redirect prose",
     "cat >/dev/null <<MSG\n$(printf harmless) documentation says > %s\nMSG" % CITE,
     "read", False),
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


# ── the generator (codex 2751: hold a partial parser to an adversarial grammar boundary) ─
# Two reviews found seven constructs by reading the code.  Enumeration is the losing move:
# the class is bash's grammar, not a spelling list.  This generates the construct space and
# decides EVERY case against bash itself, so an unmodelled construct is found by search.
# The hole predicate is one-sided on purpose: bash writes and the classifier does not say
# `write`.  The reverse (classifier says write, bash does not) is a false POSITIVE — a deny
# the member can appeal — so it is reported as a quality number, never as a failure.

_FUZZ_PREFIX = (
    "", "true", "# docs <<EOF", "echo 'x <<EOF'", 'echo "x <<EOF"',
    "true; echo 'x <<EOF'",
    "((1 << 2))", "printf '%s\\n' $((1 << 2))", "a[1<<2]=q", "x=$[1<<2]",
    "echo ${a[1<<2]}", "let a<<2", "declare -i n=1<<2",
)
_FUZZ_OP = (
    "",  # no heredoc operator at all: codex's arithmetic case gets its `<<` from the
         # PREFIX, so a generator that always emits an operator line cannot find it
    "cat <<{d}", "cat <<'{d}'", 'cat <<"{d}"', "cat <<\\{d}", "cat <<-{d}",
    "cat <<-'{d}'", "cat <<{d} >/dev/null", "cat <<{d} \\\n> {t}",
    "cat <<'{d}' \\\n> {t}", "cat <<{d} \\\n  -", "diff <(cat <<'{d}'\nsub\n{d}\n) - <<{d}",
)
_FUZZ_DELIM = ("EOF", "2", "END-OF-MSG", "MSG")
_FUZZ_BODY = (
    "harmless prose",
    "the author's note",
    "route stdout > {t} here",
    "route stdout >> {t} here",
    "$USER documentation says > {t}",
    "$(printf harmless) docs say > {t}",
    "prose $(printf x > {t}) more",
    "prose `printf x > {t}` more",
    "prose ${{UNSET:-x}} > {t}",
    "line one \\\n> {t}",
)
_FUZZ_TERM = ("{d}", " {d}", "\t{d}", "{d} ")
_FUZZ_SUFFIX = ("", "printf x > {t}", "2", "printf x > {t}\n2")


def _fuzz_cases(target):
    """Deterministic product over the construct space (no RNG: a case that fails must be
    reproducible by name on another seat)."""
    seen, cases = set(), []
    for pre in _FUZZ_PREFIX:
        for op in _FUZZ_OP:
            for d in _FUZZ_DELIM:
                for body in _FUZZ_BODY:
                    for term in _FUZZ_TERM:
                        for suf in _FUZZ_SUFFIX:
                            parts = [p for p in (
                                pre,
                                op.format(d=d, t=target),
                                body.format(t=target),
                                term.format(d=d),
                                suf.format(t=target)) if p != ""]
                            cmd = "\n".join(parts)
                            if cmd in seen:
                                continue
                            seen.add(cmd)
                            cases.append(cmd)
    return cases


def _bash_wrote(cmd, target):
    if os.path.exists(target):
        os.remove(target)
    try:
        subprocess.run(["bash", "-c", cmd], capture_output=True, check=False,
                       stdin=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired:
        return None  # undecided by the oracle: neither a hole nor a clean case
    return os.path.exists(target)


def run_fuzz(mods, limit):
    """mods: [(label, module)].  Returns {label: (holes, fps, decided)} with example holes."""
    scratch = tempfile.mkdtemp(prefix="closure-fuzz-")
    target = os.path.join(scratch, "governed-target.txt")
    cases = _fuzz_cases(target)
    if limit and len(cases) > limit:
        # stride, never head: the product is nested, so the first N cases all share one
        # prefix and a truncated head silently tests ONE axis (measured: at N=400 the
        # generator missed v2's known holes entirely and the control said so)
        cases = cases[::max(1, len(cases) // limit)][:limit]
    truth, undecided = {}, 0
    for cmd in cases:
        w = _bash_wrote(cmd, target)
        if w is None:
            undecided += 1
        truth[cmd] = w
    report = {}
    for label, mod in mods:
        holes, fps = [], 0
        for cmd in cases:
            if truth[cmd] is None:
                continue
            # the generator writes the scratch path directly; the classifier keys on the
            # governed path, so swap it back before asking for a verdict
            probe = cmd.replace(target, CITE)
            got = mod.classify("Bash", {"command": probe}).classification
            if truth[cmd] and got != "write":
                holes.append((got, cmd))
            elif not truth[cmd] and got == "write":
                fps += 1
        report[label] = (holes, fps, len(cases) - undecided)
    return report, len(cases), undecided


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
    ap.add_argument("--fuzz", action="store_true",
                    help="generate the construct space and decide it against bash")
    ap.add_argument("--fuzz-limit", type=int, default=4000)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="closure-v3-")
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

    if args.fuzz:
        # v2 is the POSITIVE CONTROL for the generator itself.  Three of its holes are
        # known; a generator that reports zero holes in v2 is blind and its zero for v3
        # would mean nothing.
        mods = [("installed", before), ("v3", after)]
        v2_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "claude_heredoc_excision_v2_2744.py")
        if os.path.exists(v2_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("v2_ctl", v2_path)
            v2m = importlib.util.module_from_spec(spec)
            sys.modules["v2_ctl"] = v2m
            spec.loader.exec_module(v2m)
            v2dir = os.path.join(tmp, "v2ctl")
            v2m.build_patched(v2dir)
            mods.insert(1, ("v2 (control)", load(v2dir)))
        report, n, undecided = run_fuzz(mods, args.fuzz_limit)
        print("--- generated construct space: %d cases, %d undecided by the oracle ---"
              % (n, undecided))
        for label, (holes, fps, decided) in report.items():
            print("  %-14s holes=%-4d false-positives=%-5d decided=%d"
                  % (label, len(holes), fps, decided))
            for got, cmd in holes[:6]:
                print("      HOLE (bash wrote, classifier said %s): %r" % (got, cmd))
        ctl = report.get("v2 (control)")
        ok = not report["v3"][0]
        if ctl is not None and not ctl[0]:
            print("  GENERATOR IS BLIND: v2's known holes were not generated — "
                  "v3's zero proves nothing")
            ok = False
        print("\nRESULT: v3-holes=%d generator-control=%s"
              % (len(report["v3"][0]), "caught" if ctl and ctl[0] else "MISSING"))
        return 0 if ok else 1

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
        # Arm C runs BOTH directions (the read direction was kimi-code's gap in review
        # 2742): a case the fix moves to `read` while bash actually writes is a false
        # negative BOUGHT BY THE FIX — the same defect codex refused v1 for, one arm over.
        truth = ""
        if name.startswith(("HOLE", "TP1", "TP2", "FP")):
            wrote = shell_truth(cmd, tmp, name.split()[0])
            truth = "  shell_wrote=%s" % wrote
            if wrote and ra[name] != "write":
                good, note = False, "HOLE: bash writes, classifier says " + ra[name]
        ok &= good
        print("  %-50s %-5s -> %-5s  %s  %s%s" % (
            name[:50], rb[name], ra[name], "OK " if good else "BAD", note, truth))

    print("\n--- differential vs BOTH predecessors (v3 must fix what each was refused for) ---")
    here = os.path.dirname(os.path.abspath(__file__))
    prior = (("v1 (refused, 1010b318)", "claude_heredoc_excision_proposal_1010b318.py"),
             ("v2 (dissented, 2751)", "claude_heredoc_excision_v2_2744.py"))
    v3_broken = [n for n, _c, e, _p in BATTERY if ra[n] != e]
    diff_ok = not v3_broken
    for label, fname in prior:
        path = os.path.join(here, fname)
        if not os.path.exists(path):
            print("  %-22s NOT PRESENT — differential SKIPPED (not evidence)" % label)
            diff_ok = False
            continue
        import importlib.util
        name = "prior_" + fname.split(".")[0]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        pdir = os.path.join(tmp, name)
        mod.build_patched(pdir)
        rp = run_battery(load(pdir))
        broken = [n for n, _c, e, _p in BATTERY if rp[n] != e]
        # A prior version failing a case in the READ direction while bash WRITES is the
        # hole it was refused for; print the direction so the two refusals stay distinct.
        for n in broken:
            print("  %-22s FAILS %-42s prior=%-5s v3=%s" % (label, n[:42], rp[n], ra[n]))
        diff_ok &= bool(broken)
        print("  %-22s fails %d case(s), v3 fails %d" % (label, len(broken), len(v3_broken)))
    print("  differential is real: %s" % diff_ok)
    v1_ok = diff_ok

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
             '            return pending, _Q_NONE, True, False'
             '  # rest of the line is a comment\n',
             '        if False:\n            pass\n'),
        # loosen the terminator back to .strip(): padded terminators close the body
        "terminator loosened to strip()":
            ('    return (line.lstrip("\\t") if dash else line) == delim\n',
             '    return line.strip() == delim\n'),
        # --- the three v3 mechanisms.  Each defangs ONE, so a control that stays green
        # says its mechanism is not load-bearing and the battery case is passing for some
        # other reason.
        "arithmetic skip disabled":
            ('        if c == "(" and line.startswith("((", i):\n',
             '        if False and line.startswith("((", i):\n'),
        "deprecated $[ ] skip disabled":
            ('        if c == "$" and line.startswith("$[", i):\n',
             '        if False and line.startswith("$[", i):\n'),
        "continuation fold disabled":
            ('            line = line[:-1] + lines[i + 1]\n            i += 1\n',
             '            break  # SABOTAGE: body boundary decided on the PHYSICAL line\n'),
        "subscript delimiter rule removed":
            ('    if "]" in delim or "}" in delim:\n',
             '    if False:\n'),
        "body residue widened back to v2 (keep whole body)":
            ('    if literal or ("$" not in body and "`" not in body):\n        return ""\n',
             '    if literal or ("$" not in body and "`" not in body):\n        return ""\n'
             '    return body  # SABOTAGE\n'),
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
