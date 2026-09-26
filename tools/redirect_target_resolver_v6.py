"""v6: REFUTED 2026-09-20. Kept as the measured record; the candidate is v7.

The battery that cleared v6 had no ORDER dimension -- every generated case put the
binding before the write, so (V5) was the one invariant it could not vary. With that
dimension added, v6 has 48 unsafe rows of 17,490: v6 enforces (V5) over the RAW token
stream while proving (V2)-(V4) over bash's rendering, and the pretty-printer strips
comments that `_tokenize` keeps. See tools/redirect_target_resolver_v7.py and
findings/v6-is-refuted-the-order-dimension-2026-09-20.md.

v6: ask bash for its parse, then require the name to be single-assignment in it.

WHY v1-v5 ALL FAILED, MEASURED. v1-v3 were a blacklist over `g._tokenize`'s token stream;
codex found 2, then 6 holes. v5 inverted the default to four local proofs (P1)-(P4) and
codex found 10 more. tools/redirect_resolver_battery.py generalises codex's ten hand-written
cases into the product space they sample -- 15 binding forms x 26 contexts x 2 separators x
3 write spellings -- and finds **42 distinct (context, binding) hole shapes, 234 cases**, all
adjudicated by bash itself. Enumeration is not behind; it is losing by a factor of four.

The holes split into exactly two families, and neither is a missing clause:

  Family A -- the binding does not run, or does not survive into the parent shell
              (guards, pipelines, `&`, subshells, skipped bodies, continuation newlines,
              comments). Deciding this needs the PARSE.
  Family B -- the text is not a binding at all, or is one the scanner cannot see
              (`'OUT=x'`, `"OUT=x"`, `OUT\=x`, `OUT[0]=`, `OUT+=`, `echo for OUT in x`,
              `printf -v`, `read`). Deciding this needs QUOTING and COMMAND POSITION.

`g._tokenize` destroys both: it strips quotes and it has no notion of command position. A
proof obligation stated over a representation that cannot express its own preconditions is
unprovable, however many clauses you add. That -- not any particular missing case -- is why
five rounds did not converge.

WHAT IS NEW HERE. `bash --pretty-print -n <file>` parses without executing and re-renders
bash's OWN parse tree. Measured on the hole shapes above, it:

  * joins continuation newlines           (closes the `&&`/`||`/`|`-then-newline family)
  * strips comments                       (closes `false && # c` + newline)
  * renders compound commands on their own indented lines with canonical keywords
                                          (closes `if false; then echo fi; OUT=...; fi`,
                                           where the argument `fi` no longer looks like a closer)
  * splits a real `for` header across lines, leaving `echo for OUT in x` inline
                                          (closes the invented-loop family)
  * preserves surface spelling exactly    (so `'OUT=x'`, `OUT[0]=`, `OUT+=`, `OUT\=` stay
                                           visibly distinct from `OUT=x`)

So bash hands us command position and quoting for free, and we stop simulating the lexer.

THE INVARIANT. A name resolves only if its ENTIRE surface history in bash's canonical
rendering is one unconditional top-level binding followed by reads:

  (V1) bash parses the command (`-n`, nothing executed). No parse -> resolve nothing.
  (V2) exactly ONE occurrence of the bare name anywhere in the rendering, and it is a
       statement-initial `NAME=<literal>` on a line at indent 0. Every other occurrence of
       the name must be `$NAME` or `${NAME}` exactly -- so `OUT[0]=`, `OUT+=`, `OUT\=`,
       `'OUT=x'`, `${OUT:=evil}`, `read OUT`, `echo for OUT in x` and `trap 'OUT=x'` all
       refuse, because each puts a second bare occurrence in the text.
  (V3) the statement's line carries no `&&`, `||`, `|`, `&`, `(`, `)` or backtick, so the
       binding is not conditional, not a pipeline component, not backgrounded, and not in a
       subshell. Indent 0 means bash rendered it outside every compound command.
  (V4) no rebinder head (`eval`, `source`, `.`, `declare`, `local`, `read`, ...) appears
       anywhere -- these are the only ways to change a variable without naming it.
  (V5) the binding precedes every use, by offset in the rendering (v1's hole, kept).

(V2) is the load-bearing one and it is a WHITELIST over the name, not a blacklist over the
grammar: the question "could this construct rebind OUT?" is replaced by "does the text
mention OUT anywhere except as a read?". Command substitution `$(...)` is deliberately NOT
banned -- it runs in a subshell and cannot rebind the parent, which is why real commands
keep working.

COST. One `bash -n` fork per Bash classification. Measure it before landing; if the hook
budget cannot afford a fork, this design is not available and the honest answer is to leave
the false positive standing rather than ship another simulator.

FAIL DIRECTION. Unchanged: anything unproven resolves to nothing, and an unresolved
destination is classified `write`.
"""
import os, re, shutil, subprocess, tempfile

_GLOB = re.compile(r"[*?\[]")
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_ASSIGN_STMT = re.compile(r"\A(" + _NAME + r")=(\S*)\Z")
# Operators that, in the binding's OWN statement, mean the binding is conditional, a
# pipeline component, or backgrounded. `&&` AFTER a binding is fine -- the assignment still
# ran in this shell -- so it is not here; `&&` BEFORE one is caught by requiring the binding
# to be the first command of its `;`-segment.
_BAD_AFTER = ("|", "&", "(", ")", "`")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_REBINDERS = frozenset({"eval", "source", ".", "declare", "typeset", "local", "let",
                        "read", "mapfile", "readarray", "printf", "getopts", "unset",
                        "export", "readonly", "set", "trap", "exec"})
_PRETTY_TIMEOUT = float(os.environ.get("HESTIA_PRETTY_TIMEOUT_S", "2"))
_FANOUT_CAP = 32
_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _bash():
    return os.environ.get("HESTIA_BASH_BIN") or shutil.which("bash")


def pretty(command):
    """bash's own parse, re-rendered. None when bash cannot parse it or is unavailable.

    `-n` means nothing in the command is executed: bash reads and parses, then exits. The
    script is handed over on a temp file rather than `-c` because `--pretty-print` renders
    a file argument; the file is removed before returning.
    """
    binary = _bash()
    if not binary:
        return None
    fd, path = tempfile.mkstemp(prefix="hestia-pp-", suffix=".sh")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(command if command.endswith("\n") else command + "\n")
        run = subprocess.run(
            [binary, "--noprofile", "--norc", "--pretty-print", "-n", path],
            capture_output=True, text=True, timeout=_PRETTY_TIMEOUT,
            env={"PATH": os.defpath, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if run.returncode != 0 or not run.stdout:
        return None
    return run.stdout


def _is_literal(value):
    return bool(value) and not _GLOB.search(value) and not value.startswith("~") \
        and "$" not in value and "`" not in value and '"' not in value \
        and "'" not in value and "\\" not in value


def strip_heredoc_bodies(rendering):
    """Blank out heredoc BODIES, keeping line count and offsets intact.

    bash's pretty-printer emits a heredoc body verbatim, at column 0. Two things break
    without this: a body line looks like a top-level statement to the line reader, and
    ordinary English inside a body ('you should read this') looks like a rebinder head.
    A body is data on a command's stdin, and the only commands that could turn it back
    into code in THIS shell -- `eval`, `source`, `.`, `read` -- are refused by (V4).
    """
    lines = rendering.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delims = [m.group(2) for m in _HEREDOC.finditer(line)]
        i += 1
        for delim in delims:
            while i < len(lines) and lines[i].strip() != delim:
                out.append("")
                i += 1
            if i < len(lines):
                out.append("")
                i += 1
    return "\n".join(out)


def _top_level_statements(rendering):
    """(offset, statement, segment) for every `;`-separated statement on an indent-0 line.

    bash's pretty-printer puts the body of every compound command on its own INDENTED
    line, so indent 0 is exactly 'outside every compound command'. Lines that are blank or
    indented are skipped: a binding inside an if/for/while/function body is not top level.
    The third element is the statement's own `;`-segment, not the whole line -- two
    statements separated by `;` are independent, and judging a binding by an unrelated
    neighbour's pipeline was v6's first and crudest error.
    """
    out, offset = [], 0
    for line in rendering.split("\n"):
        start = offset
        offset += len(line) + 1
        if not line or line[0] in " \t":
            continue
        pos = start
        for part in line.split(";"):
            stripped = part.strip()
            if stripped:
                out.append((pos + (len(part) - len(part.lstrip())), stripped, part))
            pos += len(part) + 1
    return out


def _command_position_words(rendering):
    """Every word bash would run as a command: the head of each statement.

    A statement head follows the start of a line or one of `; && || | & ( {`. This is what
    makes (V4) a rule about commands rather than a substring search -- `read` inside a
    quoted argument or a path is not the `read` builtin.
    """
    words = []
    for piece in re.split(r"(?:\|\||&&|[;&|\n(){}])", rendering):
        piece = piece.strip()
        if not piece:
            continue
        head = piece.split()[0]
        # skip a leading assignment prefix: `FOO=bar cmd` runs `cmd`
        while re.match(r"\A" + _NAME + r"=", head):
            rest = piece.split(None, 1)
            if len(rest) < 2:
                head = ""
                break
            piece = rest[1]
            head = piece.split()[0]
        if head:
            words.append(head)
    return words


def make(g):
    """Return (_bash_write_targets, _expand) bound to the shipped closure module `g`."""

    def _expand(tok, env):
        if not g._has_subst(tok):
            return [tok]
        out = [tok]
        for _ in range(4):
            nxt, changed = [], False
            for cand in out:
                m = _VAR_REF.search(cand)
                if m is None:
                    nxt.append(cand); continue
                vals = env.get(m.group(1) or m.group(2))
                if not vals:
                    return None
                changed = True
                for v in vals:
                    nxt.append(cand[:m.start()] + v + cand[m.end():])
                if len(nxt) > _FANOUT_CAP:
                    return None
            out = nxt
            if not changed:
                break
        return out if all(not g._has_subst(c) for c in out) else None

    def resolvable_bindings(command):
        """name -> (offset_of_binding, [value]) for names proved single-assignment."""
        raw = pretty(command)
        if raw is None:
            return {}, None
        rendering = strip_heredoc_bodies(raw)
        # (V4) a rebinder in COMMAND POSITION anywhere disqualifies the whole command.
        for word in _command_position_words(rendering):
            if word in _REBINDERS or os.path.basename(word) in _REBINDERS:
                return {}, rendering
        candidates = {}
        for offset, statement, segment in _top_level_statements(rendering):
            m = _ASSIGN_STMT.match(statement)
            if not m:
                continue
            # (V3) the binding must be the FIRST command of its `;`-segment -- nothing
            # conditional runs before it -- and its segment must not put it in a pipeline
            # or background it. `X=1 && cmd` is fine; `a && X=1`, `X=1 | c`, `X=1 &` are not.
            if segment.strip() != statement and not segment.strip().startswith(statement):
                continue
            tail = segment.strip()[len(statement):]
            if any(bad in tail for bad in _BAD_AFTER):
                continue
            if not _is_literal(m.group(2)):
                continue
            candidates[m.group(1)] = (offset, [m.group(2)])
        # (V2) the name's entire surface history: one bare occurrence, and it is that binding.
        env = {}
        for name, (offset, values) in candidates.items():
            bare = [mm.start() for mm in
                    re.finditer(r"(?<![$\w}])" + re.escape(name) + r"(?![\w])", rendering)]
            if len(bare) == 1 and bare[0] == offset:
                env[name] = (offset, values)
        return env, rendering

    def _flush(words, eff, targets, stdin_src, env):
        stripped = g._strip_wrappers(words)
        if not stripped:
            return eff
        head = stripped[0]
        base = os.path.basename(head) if isinstance(head, str) else ""
        if head in g._SHELL_BLOCK_KEYWORDS or base in g._SHELL_BLOCK_KEYWORDS:
            remainder = g._control_flow_remainder(stripped)
            if remainder is None:
                raise g._OutOfGrammar()
            if not remainder:
                return eff
            if remainder[0] in g._SHELL_BLOCK_KEYWORDS:
                raise g._OutOfGrammar()
            words = stripped = remainder
            head = stripped[0]
            base = os.path.basename(head) if isinstance(head, str) else ""
        if base == "eval":
            raise g._OutOfGrammar()
        if base in g._SUBSHELL_CMDS and any(a == "-c" for a in stripped[1:]):
            raise g._OutOfGrammar()
        if base == "cd":
            rest = [a for a in stripped[1:] if not a.startswith("-")]
            if rest:
                d = rest[0]
                if g._has_subst(d):
                    cands = _expand(d, env)
                    if not cands or len(cands) != 1:
                        return eff
                    d = cands[0]
                eff = d if (os.path.isabs(d) or d.startswith("~")) \
                    else os.path.normpath(os.path.join(eff or ".", d))
            return eff
        for tg in g._command_write_targets(words, stdin_src):
            if g._has_subst(tg):
                cands = _expand(tg, env)
                if cands is None:
                    raise g._OutOfGrammar()
                targets.extend(g._join_eff(eff, c) for c in cands)
                continue
            targets.append(g._join_eff(eff, tg))
        return eff

    def _bash_write_targets(command):
        proved, rendering = resolvable_bindings(command)
        toks = g._tokenize(g._strip_heredoc_bodies(command))
        # (V5) a binding becomes visible only once the scan has passed it. Offsets are in
        # the RENDERING, token indices are in the raw stream, so map by the order the names
        # were proved: a name proved at rendering offset k is released after the raw token
        # whose text is the binding. Conservative fallback: release nothing we cannot place.
        release = {}
        for name, (offset, values) in proved.items():
            needle = name + "=" + values[0]
            idx = next((i for i, t in enumerate(toks) if t == needle), None)
            if idx is not None:
                release[name] = (idx, values)
        env = {}
        targets, cur = [], []
        stdin_src, eff = None, ""
        i = 0

        def promote(upto):
            for n, (at, vals) in list(release.items()):
                if at < upto:
                    env[n] = vals
                    del release[n]

        def flush_segment():
            nonlocal eff, cur, stdin_src
            if not cur:
                return
            if all(re.match(r"\A" + _NAME + r"=", w or "") for w in cur):
                cur = []
                return
            eff = _flush(cur, eff, targets, stdin_src, dict(env))
            cur = []

        while i < len(toks):
            t = toks[i]
            promote(i)
            if t in g._SEPARATORS:
                flush_segment(); stdin_src = None; i += 1; continue
            if g._is_punct(t):
                if (">" in t or "<" in t) and cur and cur[-1].isdigit():
                    cur.pop()
                if ">" in t:
                    nxt = toks[i + 1] if i + 1 < len(toks) else None
                    if nxt is not None and "&" in t and nxt.isdigit():
                        i += 2; continue
                    if nxt is not None and nxt not in g._SEPARATORS and not g._is_punct(nxt):
                        if g._has_subst(nxt):
                            cands = _expand(nxt, dict(env))
                            if cands is None:
                                raise g._OutOfGrammar()
                            targets.extend(g._join_eff(eff, c) for c in cands)
                        else:
                            targets.append(g._join_eff(eff, nxt))
                        i += 2; continue
                    i += 1; continue
                if t in ("<", "<<", "<<<", "<<-"):
                    if t == "<" and i + 1 < len(toks) and not g._is_punct(toks[i + 1]):
                        stdin_src = toks[i + 1]
                    i += 2; continue
                i += 1; continue
            cur.append(t); i += 1
        flush_segment()
        return targets

    return _bash_write_targets, _expand
