"""Shell read/write classification: the fleet's ONE implementation.

Moved verbatim out of `plugins/claude-code/hooks/pre_tool_use.py` on 2026-08-31 under
dp's non-negotiable gate architecture ruling. A shim may normalize harness input, identify
the member, call the shared authority and render the verdict. Deciding whether a command
READS or WRITES is none of those, so it does not belong in a seat.

This is the LEARNED implementation, not a promotion of one seat's code for being biggest.
It is the only one in the fleet that handles heredoc bodies, sed programs, shell
assignments, control-flow remainders, git stdin-as-data and live substitution -- which is
why the seats disagreed: claude-code refused reads codex permitted, and gemini permitted
writes codex refused.

It supersedes `hestia_gate_core._degraded_command_is_read`, which conceded in its own
docstring that it was "conservative by construction" and returned False for ANY `>`, `$(`,
backtick or `<<` anywhere in the line. That conservatism is the measured false-positive
engine behind a `grep` after a semicolon, a `git log` inside a for-loop, and a redirect
whose only write went to a /tmp variable target. Those cases are pinned in
tools/gate_differential.py.

Nothing here reads the environment, the filesystem, or any seat state: pure functions over
a command string. Every seat gets the same answer to the same question by construction
rather than by review.
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any, Optional, Tuple


_INERT_CONTENT_HEADS = frozenset({
    # byte movers
    "cat", "tee", "head", "tail", "rev", "nl",
    # pattern search — none of these can execute a match
    "grep", "egrep", "fgrep", "rg",
    # output
    "echo", "printf",
    # text filters
    "wc", "sort", "uniq", "cut", "tr", "comm", "diff", "column", "fold", "paste",
    "join",
    # structured filters
    "jq",
    # path arithmetic
    "basename", "dirname",
})

_GIT_INERT_CONFIG_KEYS = frozenset({"user.name", "user.email"})

_GIT_INERT_GLOBAL_FLAGS = frozenset({
    "--no-pager", "--bare", "--literal-pathspecs", "--no-replace-objects",
    "--no-optional-locks",
})

_GIT_INERT_GLOBAL_VALUE_OPTS = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})

def _git_config_is_inert(kv: str) -> bool:
    """`-c KEY=VALUE` where KEY cannot change what git executes."""
    if "=" not in kv:
        # `-c key` with no `=` sets it true. No listed key is a boolean, so
        # this is always some other key: refuse.
        return False
    return kv.split("=", 1)[0].lower() in _GIT_INERT_CONFIG_KEYS

def _message_comes_from_stdin(rest: list) -> bool:
    """Does this argv say "read the message from stdin"? `-F -`, `-F-`,
    `--file=-`, `--file -`. `-F /path` is a FILE and is deliberately not
    vouched for: the heredoc body is then not what git reads."""
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--file=-":
            return True
        if a in ("-F", "--file"):
            return i + 1 < len(rest) and rest[i + 1] == "-"
        if a == "-F-":
            return True
        i += 1
    return False

def _git_stdin_is_data(args: list) -> bool:
    """Is this `git` invocation one whose stdin is data, so a quoted heredoc
    body fed to it can never be executed? See the block comment above."""
    i = 0
    # ---- 1. global options, up to the subcommand ----
    while True:
        if i >= len(args):
            return False  # `git` with no subcommand at all
        a = args[i]
        if not a.startswith("-"):
            i += 1
            break
        i += 1
        if a == "-c":
            if i >= len(args) or not _git_config_is_inert(args[i]):
                return False
            i += 1
            continue
        if a.startswith("-c"):
            # git's glued form, `-ckey=value`.
            if not _git_config_is_inert(a[2:]):
                return False
            continue
        if a in _GIT_INERT_GLOBAL_FLAGS:
            continue
        name = a.split("=", 1)[0]
        if name in _GIT_INERT_GLOBAL_VALUE_OPTS:
            if "=" not in a:
                # the value is the next word
                if i >= len(args):
                    return False
                i += 1
            continue
        return False  # unrecognised global option: unknown means scanned

    # ---- 2 + 3. subcommand, and the flag that declares stdin to be content ----
    subcommand = a
    rest = args[i:]
    if subcommand in ("commit", "tag"):
        return _message_comes_from_stdin(rest)
    if subcommand == "hash-object":
        return "--stdin" in rest
    return False

def _treats_content_as_data(seg: list) -> bool:
    """Condition 2: does this segment's command treat its arguments and stdin
    as data? `git` is matched BEFORE the list, so a list entry for it would be
    unreachable — the shadow test in test_pre_tool_use_self.py keeps that loud."""
    head = seg[0]
    if head == "git":
        return _git_stdin_is_data(seg[2])
    return head in _INERT_CONTENT_HEADS

def _blank_inert_heredoc_bodies(cmd: str) -> Optional[str]:
    """A copy of `cmd` with QUOTED heredoc bodies blanked to spaces, else None.

    The scoped port of policy::shell's `executable_positions` for this gate —
    scoped because the two gates match different things. The destructive preset
    matches COMMAND TOKENS (`rm -`, `dd `), so it can blank any inert quoted
    span; this gate matches PATHS, and a path can sit at argument position, so
    blanking quoted arguments would open `tee "hooks/pre_tool_use.py"` as a
    one-word evasion. A heredoc BODY is the only span that can never name a
    destination — it is stdin content — so it is the only span blanked here.

    The three safety conditions are the daemon's, unchanged in kind:

    1. The body cannot expand: only a QUOTED delimiter (`<<'X'`, `<<"X"`,
       `<<\\X`) qualifies. `cat <<X` can carry `$(...)` and stays visible.
    2. The command governing the body treats stdin as data: the owning
       segment's head must be in `_INERT_CONTENT_HEADS` — except `git`, the
       one head that is not a decision by itself, which `_git_stdin_is_data`
       answers from the argv (see `_treats_content_as_data`).
    3. Nothing downstream re-interprets it: inertness propagates backwards
       along pipes, so `cat <<'X' | sh` keeps its body visible.

    Returns None on anything the parser cannot resolve — unterminated quote,
    heredoc whose delimiter never arrives, unbalanced `$(`, trailing backslash —
    and None means "match the raw command" (fail closed, today's behaviour).
    Length and newlines are preserved in the projection, so a report against it
    still lines up with the original.
    """
    n = len(cmd)
    # (head, sep, args) per segment; sep is 'pipe', 'break' or 'end'; args is
    # the argv after the head (no assignment prefixes, no redirection targets),
    # collected because condition 2 is not always answerable from the head alone.
    segs: list = [[None, "end", []]]
    inert_spans: list = []  # (seg_idx, start, end) of candidate bodies
    pending: list = []      # heredocs opened on this line: dicts
    seg = 0
    word: list = []
    word_quoted = False
    head_done = False
    expect_redir_target = False
    subst_depth = 0

    def flush_word() -> None:
        nonlocal word_quoted, head_done, expect_redir_target
        if not word:
            word_quoted = False
            return
        w = "".join(word)
        if expect_redir_target:
            expect_redir_target = False
        elif not head_done:
            if not word_quoted and _is_shell_assignment(w):
                pass  # `FOO=bar cmd …` — keep looking for the head
            else:
                segs[seg][0] = w.rsplit("/", 1)[-1]
                head_done = True
        else:
            segs[seg][2].append(w)
        word.clear()
        word_quoted = False

    def find_unescaped(start: int, close: str, honour_backslash: bool) -> Optional[int]:
        j = start
        while j < n:
            if honour_backslash and cmd[j] == "\\":
                j += 2
                continue
            if cmd[j] == close:
                return j
            j += 1
        return None  # unterminated — fail closed

    def read_delimiter(i: int) -> Optional[Tuple[str, bool, int]]:
        delim: list = []
        quoted = False
        while i < n:
            c = cmd[i]
            if c in "'\"":
                quoted = True
                end = find_unescaped(i + 1, c, c == '"')
                if end is None:
                    return None
                delim.extend(cmd[i + 1:end])
                i = end + 1
            elif c == "\\":
                if i + 1 >= n:
                    return None
                quoted = True
                delim.append(cmd[i + 1])
                i += 2
            elif c.isspace() or c in ";&|<>()":
                break
            else:
                delim.append(c)
                i += 1
        if not delim:
            return None
        return "".join(delim), quoted, i

    def consume_body(i: int, hd: dict) -> Optional[Tuple[int, int, int]]:
        body_start = i
        line_start = i
        while i <= n:
            if i == n or cmd[i] == "\n":
                line = cmd[line_start:i]
                if hd["strip_tabs"]:
                    line = line.lstrip("\t")
                if line.rstrip("\r") == hd["delim"]:
                    return body_start, line_start, (i if i == n else i + 1)
                if i == n:
                    return None  # ran out of input before the terminator
                line_start = i + 1
            i += 1
        return None

    i = 0
    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 >= n:
                return None  # trailing backslash: unresolved
            word.extend((c, cmd[i + 1]))
            word_quoted = True
            i += 2
        elif c == "'":
            end = find_unescaped(i + 1, "'", False)
            if end is None:
                return None
            word.extend(cmd[i + 1:end])
            word_quoted = True
            i = end + 1
        elif c == '"':
            end = find_unescaped(i + 1, '"', True)
            if end is None:
                return None
            word.extend(cmd[i + 1:end])
            word_quoted = True
            i = end + 1
        elif c == "$" and i + 1 < n and cmd[i + 1] == "(":
            subst_depth += 1
            word.extend("$(")
            i += 2
        elif c == "`":
            end = find_unescaped(i + 1, "`", True)
            if end is None:
                return None
            word_quoted = True
            i = end + 1
        elif c == "<" and i + 1 < n and cmd[i + 1] == "<":
            flush_word()
            if i + 2 < n and cmd[i + 2] == "<":
                i += 3  # herestring: the following word is ordinary data
            else:
                i += 2
                strip_tabs = i < n and cmd[i] == "-"
                if strip_tabs:
                    i += 1
                while i < n and cmd[i] in " \t":
                    i += 1
                got = read_delimiter(i)
                if got is None:
                    return None
                delim, quoted, i = got
                pending.append({"delim": delim, "quoted": quoted,
                                "strip_tabs": strip_tabs, "seg": seg})
        elif c in "><":
            if word and all(ch.isdigit() for ch in word):
                word.clear()
                word_quoted = False
            flush_word()
            i += 1
            while i < n and cmd[i] in "><&|":
                i += 1
            expect_redir_target = True
        elif c in "|;&({}":
            if c == "(" and subst_depth > 0:
                word.append(c)
                i += 1
                continue
            flush_word()
            is_pipe = c == "|" and not (i + 1 < n and cmd[i + 1] == "|")
            segs[seg][1] = "pipe" if is_pipe else "break"
            segs.append([None, "end", []])
            seg += 1
            head_done = False
            expect_redir_target = False
            i += 1
            if i < n and cmd[i] == c and c in "&|":
                i += 1
        elif c == ")":
            if subst_depth > 0:
                subst_depth -= 1
                word.append(c)
                i += 1
            else:
                flush_word()
                segs[seg][1] = "break"
                segs.append([None, "end", []])
                seg += 1
                head_done = False
                expect_redir_target = False
                i += 1
        elif c == "\n":
            flush_word()
            i += 1
            for hd in pending:
                got = consume_body(i, hd)
                if got is None:
                    return None
                body_start, body_end, i = got
                if hd["quoted"] and subst_depth == 0:
                    inert_spans.append((hd["seg"], body_start, body_end))
            pending.clear()
            segs[seg][1] = "break"
            segs.append([None, "end", []])
            seg += 1
            head_done = False
            expect_redir_target = False
        elif c in " \t\r":
            flush_word()
            i += 1
        else:
            word.append(c)
            i += 1

    if subst_depth != 0:
        return None  # unbalanced `$(`
    if pending:
        return None  # heredoc opened, body never arrived
    flush_word()

    # Conditions 2 + 3 together, walking backwards so a segment is inert only
    # if the segment it pipes into is inert too.
    inert_seg = [False] * len(segs)
    for k in range(len(segs) - 1, -1, -1):
        head_ok = _treats_content_as_data(segs[k])
        if segs[k][1] == "pipe":
            inert_seg[k] = head_ok and (inert_seg[k + 1] if k + 1 < len(segs) else False)
        else:
            inert_seg[k] = head_ok

    out = list(cmd)
    for s, start, end in inert_spans:
        if 0 <= s < len(inert_seg) and inert_seg[s]:
            for slot in range(start, end):
                if out[slot] != "\n":
                    out[slot] = " "
    return "".join(out)

def _is_shell_assignment(word: str) -> bool:
    """`FOO=bar` — a variable assignment prefix, not the segment's head."""
    eq = word.find("=")
    if eq <= 0:
        return False
    name = word[:eq]
    return (name[0].isalpha() or name[0] == "_") and all(
        ch.isalnum() or ch == "_" for ch in name)

_READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}

_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

_READ_ONLY_HEADS = {
    "cat", "less", "more", "head", "tail", "grep", "rg", "egrep", "fgrep",
    "wc", "md5sum", "sha256sum", "shasum", "cksum", "diff", "file", "stat", "ls",
    # Added 2026-08-02 after ELEVEN false refusals in one session, every one of them a
    # read. Widening is "a reviewable act" per the note above, so each name is here on
    # purpose and the risky ones are guarded below rather than admitted bare.
    "echo", "printf", "basename", "dirname", "realpath", "readlink", "pwd",
    "true", "false", "test", "[", "seq", "nl", "cut", "tr", "uniq",
    "comm", "rev", "du", "df", "which", "type", "id", "whoami", "uname",
    "jq", "column", "tree",
    # `cd` added 2026-08-05, and it is the cheapest of the four fixes in this pass because
    # `cd` is a head that CANNOT write — there is no flag, no argument and no spelling of it
    # that modifies a file. Its absence cost a real refusal: `cd h && grep -n foo <gate>`,
    # a read of the gate for symbol names while writing a defect report about the gate, was
    # refused and opened escalation 851e0d0ec5a4bf0c on the operator. `grep -n foo <gate>`
    # alone is permitted, so the only thing the refusal measured was that the member changed
    # directory first.
    #
    # Segment walking is what makes this safe, and the test says so rather than trusting it:
    # separators split `cd /tmp && sed -i s/a/b/ <gate>` into two segments and the second is
    # head-checked on `sed`. Adding `cd` frees the `cd` segment, never the one after it.
    # (`cd_does_not_launder` in tests/gate_false_refusal_test.py.)
    "cd",
    # NOT here: `date` and `hostname` (codex peer review, finding 2). `date -s` sets the
    # system clock; `hostname X` sets the hostname. A read-looking NAME carrying a mutating
    # FLAG is precisely what a head allowlist cannot see, which is why `_GUARDED_HEADS`
    # exists for the cases worth keeping.
    #
    # These two survived the first rebuild because that edit covered the logic region and
    # not this set — the classifier then scored 27/29 with exactly these two failing, while
    # the standalone prototype had passed 30/30. Without running the cases against the REAL
    # file this would have shipped claiming all four of codex's findings fixed with two of
    # them still open, and a test that only ever ran against the prototype would have agreed.
}

_GUARDED_HEADS = {
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"),
    "sort": ("-o", "--output"),
}

def _sed_scan_delimited(prog: str, i: int) -> int:
    """PROG[i] opens a delimited section (`/re/`, the pattern or replacement of `s`,
    one side of `y`). Return the index just past the CLOSING delimiter, or -1 if there
    is none. Backslash escapes the next char. A delimiter inside a bracket expression
    (`s/[/]/x/`) is NOT modelled: the misparse lands on an unknown token, and unknown
    fails closed."""
    d = prog[i]
    i += 1
    while i < len(prog):
        if prog[i] == "\\":
            i += 2
            continue
        if prog[i] == d:
            return i + 1
        i += 1
    return -1

def _sed_scan_to(prog: str, i: int, d: str) -> int:
    """Scan from PROG[i] to the next unescaped delimiter D (already known); return
    just past it, or -1 if there is none. The `s`/`y` sections after the first share
    the opening delimiter with the section before, so only the first can be found by
    `_sed_scan_delimited`."""
    while i < len(prog):
        if prog[i] == "\\":
            i += 2
            continue
        if prog[i] == d:
            return i + 1
        i += 1
    return -1

def _sed_skip_address(prog: str, i: int) -> int:
    """Skip ONE address at PROG[i]. Return the new index, I unchanged when no address
    starts here (not an error — the command is next), or -1 on a malformed one."""
    n = len(prog)
    if i >= n:
        return i
    ch = prog[i]
    if ch.isdigit():
        while i < n and prog[i].isdigit():
            i += 1
    elif ch == "$":
        i += 1
    elif ch in "+~":
        # GNU range tail standing alone: `addr1,+N` / `addr1,~N`.
        i += 1
        if i >= n or not prog[i].isdigit():
            return -1
        while i < n and prog[i].isdigit():
            i += 1
        return i
    elif ch == "/":
        i = _sed_scan_delimited(prog, i)
        if i < 0:
            return -1
        while i < n and prog[i] in "IM":  # GNU regex modifiers
            i += 1
    elif ch == "\\":
        # GNU `\cREc`: backslash, then any delimiter char.
        if i + 1 >= n:
            return -1
        i = _sed_scan_delimited(prog, i + 1)
        if i < 0:
            return -1
    else:
        return i
    # GNU `FIRST~STEP` suffix on a numeric or `$` address.
    if i < n and prog[i] in "+~":
        i += 1
        if i >= n or not prog[i].isdigit():
            return -1
        while i < n and prog[i].isdigit():
            i += 1
    return i

_SED_SAFE_COMMANDS = set("pdDnPhHgGxlqQzv=")

def _sed_program_is_read_only(prog: str) -> bool:
    """True only when a sed program text cannot write, execute, or read a hidden path.

    Refused constructs, each named in the adjudication this parser replaces:
      `w`/`W file`   — write pattern/hold space to a file the redirect check never sees
      `s///w file`   — the same write as a substitute flag
      `s///e`        — execute the replacement as a shell command
      `e [cmd]`      — GNU: execute a shell command outright
      `r`/`R file`   — read a file whose path lives INSIDE the program, so it is
                       invisible to every argument-based check (thor's refutation case)
    """
    i, n, depth = 0, len(prog), 0
    while i < n:
        ch = prog[i]
        if ch in " \t\n;":
            i += 1
            continue
        if ch == "#":  # comment runs to end of line
            j = prog.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch == "}":
            if depth == 0:
                return False
            depth -= 1
            i += 1
            continue
        j = _sed_skip_address(prog, i)
        if j < 0:
            return False
        i = j
        if i < n and prog[i] == ",":
            j = _sed_skip_address(prog, i + 1)
            if j < 0 or j == i + 1:  # a comma with no second address is malformed
                return False
            i = j
        while i < n and prog[i] in " \t":
            i += 1
        if i < n and prog[i] == "!":
            i += 1
            while i < n and prog[i] in " \t":
                i += 1
        if i >= n:
            return False  # an address with no command is malformed
        c = prog[i]
        i += 1
        if c in _SED_SAFE_COMMANDS:
            continue
        if c == "{":
            depth += 1
            continue
        if c in "btT:":
            # Branch/label: the name runs to `;` or end of line and is data, not code.
            while i < n and prog[i] not in ";\n":
                i += 1
            continue
        if c in "aic":
            # GNU one-line form: the text is the REST OF THE LINE, semicolons included —
            # so a `w` appearing there is appended text in real sed too, and skipping it
            # misses nothing.
            j = prog.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "y":
            if i >= n:
                return False
            d = prog[i]
            i = _sed_scan_delimited(prog, i)   # first string, delimiters included
            if i < 0:
                return False
            i = _sed_scan_to(prog, i, d)       # second string, to the closing delimiter
            if i < 0:
                return False
            continue
        if c == "s":
            if i >= n:
                return False
            d = prog[i]
            i = _sed_scan_delimited(prog, i)   # pattern, delimiters included
            if i < 0:
                return False
            i = _sed_scan_to(prog, i, d)       # replacement, to the closing delimiter
            if i < 0:
                return False
            while i < n and prog[i] not in ";\n}":
                f = prog[i]
                if f in " \t":
                    i += 1
                    continue
                if f in "wWe":
                    return False  # s///w writes; s///e executes
                if f.isdigit() or f in "gpiImM":
                    i += 1
                    continue
                return False  # an unknown flag is a write
            continue
        return False  # w W r R e, and every command this parser does not model
    return depth == 0

def _sed_args_are_read_only(args: list[str]) -> bool:
    """True only when a sed ARGV (post-head tokens, quotes still on) is confidently
    read-only. Flags are checked one by one — `-ni` is `-i` — and every program text,
    whether positional or `-e`-supplied, goes through `_sed_program_is_read_only`.
    Input files are read, never written, by everything admitted here."""
    scripts: list[str] = []
    positional: list[str] = []
    from_expr = False
    i, n = 0, len(args)
    while i < n:
        a = args[i].strip("'\"")
        if a == "--":
            positional.extend(x.strip("'\"") for x in args[i + 1:])
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in ("in-place", "file"):
                return False
            if name == "expression":
                from_expr = True
                if eq:
                    scripts.append(val)
                else:
                    i += 1
                    if i >= n:
                        return False
                    scripts.append(args[i].strip("'\""))
            elif name in ("silent", "quiet", "null-data", "posix", "debug",
                          "regexp-extended", "extended-regexp", "separate",
                          "follow-symlinks", "sandbox", "unbuffered",
                          "help", "version"):
                pass
            elif name == "line-length":
                if not eq:
                    i += 1
                    if i >= n or not args[i].strip("'\"").isdigit():
                        return False
            else:
                return False
        elif a.startswith("-") and a != "-":
            cluster = a[1:]
            k = 0
            while k < len(cluster):
                f = cluster[k]
                if f in "nErsuz":
                    k += 1
                elif f == "l":
                    if k + 1 < len(cluster):
                        if not cluster[k + 1:].isdigit():
                            return False
                    else:  # the value is the next token
                        i += 1
                        if i >= n or not args[i].strip("'\"").isdigit():
                            return False
                    k = len(cluster)
                elif f == "e":
                    from_expr = True
                    if k + 1 < len(cluster):
                        scripts.append(cluster[k + 1:])
                    else:
                        i += 1
                        if i >= n:
                            return False
                        scripts.append(args[i].strip("'\""))
                    k = len(cluster)
                else:  # `i` and `f` land here, with everything unknown
                    return False
        else:
            positional.append(a)
        i += 1
    if not from_expr:
        if not positional:
            return False  # no program text at all
        scripts.append(positional[0])
        positional = positional[1:]
    return all(_sed_program_is_read_only(s) for s in scripts)

_HEAD_GRAMMARS = {
    "sed": _sed_args_are_read_only,
}

_SEPARATORS = {";", "&", "&&", "|", "||", "\n"}

_REDIRECTS = {">", ">>", "<", "<<", "<<<", ">&", "&>", ">|", "<&"}

_INPUT_REDIRECTS = {"<", "<<", "<<<", "<&"}

_GIT_READ_SUBCOMMANDS = {"show", "diff", "log", "cat-file", "blame", "status", "rev-parse",
                         "describe", "ls-files", "ls-tree", "rev-list", "show-ref",
                         # Added 2026-08-10 (Sprint 5, the `_STILL_OPEN` git-read rows,
                         # kimi-code notice 1745 §3). Both are plumbing READS with no
                         # mutating spelling in any form — `merge-base` computes ancestry
                         # (`--is-ancestor` is the exit-status probe two members ran every
                         # wake and had refused beside a `rev-list` that read fine), and
                         # `for-each-ref` enumerates refs. A bare-set add is correct BECAUSE
                         # neither has a writing mode a flag could hide, unlike `branch`
                         # (creates from a positional) and `hash-object -w` (writes a blob),
                         # which is why those two stay OUT of this set and need a grammar.
                         "merge-base", "for-each-ref"}

_GIT_GUARDED_SUBCOMMANDS = {"hash-object": ("-w",)}

_CONTROL_FLOW_BODY = {"do", "then", "else"}        # the remainder is the body command

_CONTROL_FLOW_COND = {"if", "elif", "while", "until"}  # the remainder EXECUTES (the condition)

_CONTROL_FLOW_CLOSE = {"done", "fi", "esac"}       # a segment of closers runs nothing

_FOR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

def _has_live_substitution(text: str) -> bool:
    """True when `text` carries a command substitution bash would EXECUTE.

    FP14 (claude-code, escalation c80e4a2557df241b, 2026-08-08): the guard this
    replaces was a substring test on posix=False tokens — `"$(" in t` — so a grep
    PATTERN that names substitution (`grep -n "=\\$(\\|…" <gate>`, where `\\$` is a
    literal dollar to bash) refused exactly like a live one. posix=False had already
    preserved the quoting that separates the two; the check just never read it. It
    is also the one FP its own search cannot find: grepping the gate for `$(` trips
    the check being searched for.

    Quoting is a STATE, not a substring, so walk it. Inert by bash's rules: anything
    inside single quotes, and a backslash-escaped character (any character unquoted;
    inside double quotes only before $ ` " \\ or newline). Live everywhere else,
    INCLUDING inside double quotes — `"$(id)"` runs. The walk runs on raw text, not
    on tokens: punctuation splitting puts the `$(` of `a$(id)b` across two tokens,
    where no per-token test can see it whole, and a leading quote hid a backtick
    from the old startswith test. Both were live bypasses; the walk closes them.

    Unterminated quoting cannot reach here — the caller's tokenizer has already
    failed closed on it — but the walk answers True for it anyway: an unresolved
    quote means the quoting was never decided, and undecided means write.
    """
    state = ""  # "", "'" or '"' — the quoting the walk is inside
    i = 0
    while i < len(text):
        c = text[i]
        if state == "'":
            if c == "'":
                state = ""
        elif state == '"':
            if c == '"':
                state = ""
            elif c == "\\" and text[i + 1:i + 2] in ('$', '`', '"', "\\", "\n"):
                i += 1
            elif c == "`" or text[i:i + 2] == "$(":
                return True
        else:
            if c == "'" or c == '"':
                state = c
            elif c == "\\":
                i += 1
            elif c == "`" or text[i:i + 2] == "$(":
                return True
        i += 1
    return state != ""

def _control_flow_remainder(parts):
    """Strip leading shell control-flow keywords from one segment.

    Returns the remaining command tokens to head-check; [] for a segment that carries
    NO command (a bare closer, or a `for VAR [in WORDS]` / `case WORD in` header —
    the words are data, globbed at most, never executed); or None for a keyword shape
    this grammar does not model, which the caller must treat as a WRITE, because
    unparseable input is a write.

    `if`/`while`/`until`/`elif` strip to their CONDITION, not past it: the condition
    really runs, so `if rm -rf /; then ...; fi` refuses on `rm`. `case` arms
    (`pattern) body ;;`) stay unmodelled and refuse on their own segments — fail
    closed, not a hole: the header skip runs nothing by itself.
    """
    p = list(parts)
    while p:
        w = p[0]
        if w in _CONTROL_FLOW_BODY or w in _CONTROL_FLOW_COND:
            p.pop(0)
            continue
        if w in _CONTROL_FLOW_CLOSE:
            return [] if len(p) == 1 else None
        if w == "for":
            if (len(p) >= 2 and _FOR_NAME.match(p[1])
                    and p[1] not in _CONTROL_FLOW_BODY
                    and p[1] not in _CONTROL_FLOW_COND
                    and p[1] not in _CONTROL_FLOW_CLOSE and p[1] != "in"
                    and (len(p) == 2 or p[2] == "in")):
                return []
            return None
        if w == "case":
            return [] if len(p) == 3 and p[2] == "in" else None
        return p
    return []

def _assignment_remainder(parts):
    r"""Consume leading NAME=VALUE assignment prefixes from one segment.

    FP13 (claude-code, notice 1474 §1): the head check read `G=<path>` as a COMMAND —
    basename(`G=<gate>`) is the gate's own filename, which sits in no head list, so a
    member spelling a read of its own law through a variable was refused as a WRITE
    and minted an escalation (the matched pair: `grep … <gate>` permitted,
    `G=<gate>; grep … "$G"` refused). In shell grammar a leading NAME=VALUE token is a
    PREFIX, not the command — it runs nothing by itself. So consume leading
    assignments and head-check what follows; the empty case (`G=x` alone) runs
    nothing and is read-only.

    A prefix is only free when it is INERT. A command substitution inside the value
    EXECUTES — `G=`rm -rf …`` runs the rm — so a value carrying a LIVE one fails
    closed here rather than being consumed. Liveness is `_has_live_substitution`'s
    call, not a substring test: an escaped or quoted substitution SPELLING in the
    value is data (FP14), and `G=\`id\`` must not refuse the read that follows it.
    (The single-quoted `$(` twin never reaches this check: shlex's punctuation_chars
    mode raises "No closing quotation" on a mid-token quote and the classifier fails
    closed in the tokenizer — safe, and one layer below this one.)

    A consume, NOT a merge into `_control_flow_remainder` (1474 §1): `for` and
    `NAME=` have different arities, and one shared strip is how `do rm -rf /` gets
    freed. The red arm is `assignment_does_not_launder` in `_SURVIVE`; the control
    proves the sed grammar still decides what follows the prefix.
    """
    p = list(parts)
    while p and _ASSIGNMENT.match(p[0]):
        if _has_live_substitution(p[0]):
            return None  # a substitution in the VALUE runs; fail closed
        p.pop(0)
    return p

_COMMENT_OPENS_AFTER = frozenset(" \t\r\f\v;&|")

def _command_lines(text: str) -> list[str]:
    """Split raw command TEXT into the logical lines bash would run, in order.

    THE HOLE THIS CLOSES (found by claude-code 2026-08-08, escalation 4a3e6f6838acabad;
    fixed by LEGION 2026-08-10 claiming CBP's 0015 offer). `_SEPARATORS` has listed `"\\n"`
    since it was written, but the caller's `shlex` treats a newline as whitespace and never
    emits it as a token, so the entry matched nothing. No newline ever split a segment:
    every line after the first arrived as ARGUMENTS to line one's head. So

        echo checking
        cp evil.py <the gate>

    was classified from `echo` alone — read-only, permitted, and the `cp` overwrote the
    enforcing gate with no `gate_self_access` event, no witness and no approval. A silent
    write to the thing that governs writes is the one class worse than a false refusal.

    WHY THE SPLIT IS ON TEXT AND NOT ON TOKENS. Three constructs make the newline
    unrecoverable once shlex has run, and each is a red arm in
    `gate_false_refusal_test.py`:

      - a QUOTED newline is data (`grep -c 'a\\nb' <gate>`), so a blind `text.split("\\n")`
        cuts a pattern in half and leaves an unbalanced quote — a legitimate read refused
        for being multi-line;
      - a `\\`-newline is ONE logical line, so splitting there leaves the gate's PATH
        standing alone as a segment, and `basename` of it is a head no list carries. That
        is FP13's exact shape (`assignment_prefix_is_not_a_head`), reintroduced by the fix
        meant to close a hole;
      - a COMMENT is consumed by shlex THROUGH the end of the line, separator included, so
        by the time there is a token stream the newline after `# note` is already gone.

    AND THE COMMENT RULE HAD TO COME WITH IT, not after it. shlex's `commenters` eats from
    `#` to end of LINE — and a `;` sits on the line, so the comment never needed a newline
    to swallow a separator: `echo a#b; cp evil.py <gate>` was permitted with the `cp`
    entirely unseen, while bash ran it. Splitting on newlines does not touch that; line one
    is the whole command. So the caller sets `commenters = ""` and the rule moves here,
    where the word-start test that separates bash's comment from bash's literal can actually
    be applied. The two directions are pinned as a PAIR —
    `mid_word_hash_is_not_a_comment` must refuse, `word_start_comment_still_comments` must
    stay permitted — because a fix that just refuses anything containing `#` passes the
    first and fails the second, and only the pair says which one happened.

    The quoting walk here follows `_has_live_substitution`'s rules character for character
    (single quotes inert; inside double quotes a backslash escapes only `$` `` ` `` `"` `\\`
    and newline; unquoted backslash escapes anything). That is deliberate duplication of
    SHAPE, not of code: it cannot call that function, which answers one bool about the whole
    string, but two quote walkers in one classifier that disagreed about where a quote ends
    would be a bypass generator. Change one, read the other.

    Unterminated quoting is NOT resolved here — the walk simply ends inside the quote and
    the offending line goes back to the caller with the quote still open, where the
    tokenizer raises and fails closed. One place decides that, and it is the same place as
    before this function existed.
    """
    lines: list[str] = []
    buf: list[str] = []
    state = ""            # "", "'" or '"' — the quoting the walk is inside
    at_word_start = True  # a `#` here opens a comment; mid-word it is a literal
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if state == "'":
            buf.append(c)
            if c == "'":
                state = ""
            at_word_start = False
        elif state == '"':
            if c == "\\" and text[i + 1:i + 2] in ('$', '`', '"', "\\", "\n"):
                buf.append(text[i:i + 2])
                at_word_start = False
                i += 2
                continue
            buf.append(c)
            if c == '"':
                state = ""
            at_word_start = False
        elif c == "\\":
            nxt = text[i + 1:i + 2]
            if nxt == "\n":
                # Line continuation. Bash removes BOTH characters and the lines become one,
                # so emit nothing and do NOT touch `at_word_start` — `ec\<nl>ho` is `echo`,
                # one word across the join.
                i += 2
                continue
            if nxt:
                buf.append(text[i:i + 2])
                at_word_start = False
                i += 2
                continue
            buf.append(c)  # a lone trailing backslash; hand it on unchanged
            at_word_start = False
        elif c == "\n":
            lines.append("".join(buf))
            buf = []
            at_word_start = True
        elif c == "#" and at_word_start:
            # Discard through the end of the line, the newline EXCLUDED so the line still
            # separates. That exclusion is the whole `comment_does_not_eat_the_separator`
            # row: shlex's version consumed the newline with the comment.
            while i < n and text[i] != "\n":
                i += 1
            continue
        else:
            buf.append(c)
            if c == "'" or c == '"':
                state = c
                at_word_start = False
            else:
                at_word_start = c in _COMMENT_OPENS_AFTER
        i += 1
    lines.append("".join(buf))
    return lines

def _is_read_only(tool_name: str, tool_input: Any) -> bool:
    """True only when the call is CONFIDENTLY read-only. Ambiguity means write.

    TOKENISED, NOT SPLIT (codex peer review, 2026-08-02). The previous version split raw
    command TEXT, so a quoted operator was indistinguishable from a real one:
    `grep -E "a|b" f` split inside its own quotes, and `grep ">" f` tripped a substring
    test for `>`. That is the #116 quoted-token class, and an earlier draft of this widening
    made it worse rather than better.

    `shlex` with `posix=False` is the fix as a CLASS rather than as more special cases: it
    preserves quoting, so a quoted `|` or `>` arrives as one data token (`'"a|b"'`) and can
    never be read as syntax. `posix=True` would strip the quotes and silently keep the bug —
    the trap this nearly walked into.

    codex's structural point, which is why this is a rewrite and not another list:

        "shell syntax is exceeding what a string splitter can safely model. If this
         classifier stays lexical, its supported grammar needs to be explicit and everything
         outside that grammar must remain a write. Another growing list of heads and
         separators will keep alternating false denial and bypass."

    So the grammar is explicit and CLOSED: enumerated separators, enumerated redirects,
    enumerated control-flow keywords, enumerated heads. Unparseable input is a write.
    Unknown syntax is a write. Command substitution is a write. The aim is to stop
    calling `2>/dev/null` a file write — not to make the classifier clever.
    """
    if tool_name in _READ_ONLY_TOOLS:
        return True
    if tool_name in _WRITE_TOOLS:
        return False
    if tool_name not in {"Bash", "Shell"}:
        return False
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(cmd, str) or not cmd.strip():
        return False

    # Imported here rather than at module scope: this hook is on the agent's critical path
    # with an 800ms budget, and `shlex` is only needed on the Bash branch.
    import shlex

    # ONE TOKENIZER PER LOGICAL LINE, with an explicit `"\n"` token between them — one per
    # newline `_command_lines` honoured. shlex cannot do this itself: it counts a newline as
    # whitespace, so a single pass over the whole command emits no separator and every line
    # after the first becomes argv to line one's head (the bypass above). Tokenising per line
    # is also what makes `commenters = ""` safe — the comment rule now lives in
    # `_command_lines`, where bash's word-start test can be applied, instead of in a
    # tokenizer that eats to end-of-line and takes any `;` on that line with it.
    tokens: list[str] = []
    try:
        for idx, line in enumerate(_command_lines(cmd)):
            if idx:
                tokens.append("\n")
            lx = shlex.shlex(line, posix=False, punctuation_chars=True)
            lx.whitespace_split = True
            lx.commenters = ""
            tokens.extend(lx)
    except ValueError:
        # Unbalanced quotes: we cannot know what this runs. Fail closed. Still decided in
        # exactly one place, and a quote `_command_lines` left open arrives here to be
        # refused rather than being resolved by a second, divergent walk.
        return False
    if not tokens:
        return False

    # Command substitution runs arbitrary code and its contents are never walked below.
    # Checked on the RAW command, with quoting walked as a state — not as a substring
    # test on tokens (FP14): posix=False preserves the quoting, so `grep -n "=\$(\|…"
    # <gate>` is data bash passes through, and the old test could not tell it from the
    # live case. The raw walk also sees what no per-token test can: `a$(id)b`, split
    # across tokens by punctuation_chars, and a backtick behind a leading quote.
    if _has_live_substitution(cmd):
        return False

    segments: list[list[str]] = [[]]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _SEPARATORS:
            segments.append([])
            i += 1
            continue
        if t in _REDIRECTS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            # An input redirect writes nothing; consume it and its operand. The operand is
            # a source file, a heredoc delimiter or a literal — never a destination — so it
            # must not fall through and be head-checked as if it started a command.
            if t in _INPUT_REDIRECTS:
                i += 2
                continue
            # fd duplication (`2>&1`) and `/dev/null` write no file. Everything else does.
            if t in {">&", "&>", "<&"} and nxt and nxt.isdigit():
                i += 2
                continue
            if nxt == "/dev/null":
                i += 2
                continue
            return False
        segments[-1].append(t)
        i += 1

    for parts in segments:
        if not parts:
            continue
        parts = _control_flow_remainder(parts)
        if parts is None:
            return False
        parts = _assignment_remainder(parts)
        if parts is None:
            return False
        if not parts:
            continue
        head = os.path.basename(parts[0].strip("'\""))
        if head == "git":
            if len(parts) < 2:
                return False
            if parts[1] in _GIT_GUARDED_SUBCOMMANDS:
                if any(a.startswith(f) for a in parts[2:] for f in _GIT_GUARDED_SUBCOMMANDS[parts[1]]):
                    return False
            elif parts[1] not in _GIT_READ_SUBCOMMANDS:
                return False
        elif head in _HEAD_GRAMMARS:
            # Admitted by head, audited by arguments. BEFORE the bare set, so an append
            # there can never bypass the grammar — `sed` in `_READ_ONLY_HEADS` would be
            # dead text, not a hole.
            if not _HEAD_GRAMMARS[head](parts[1:]):
                return False
        elif head in _GUARDED_HEADS:
            # Read-only only without its writing flags. Prefix match so `-exec`,
            # `-execdir` and `--output=x` are all caught.
            if any(a.startswith(f) for a in parts[1:] for f in _GUARDED_HEADS[head]):
                return False
        elif head not in _READ_ONLY_HEADS:
            return False
    return True