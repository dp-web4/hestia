"""Resolve statically-resolvable write targets before declaring a command out of grammar.

Developed against the shipped module IN MEMORY (no copy of the governed module is made and
none is written) — see gate escalations 22d1e3f55fde5acc and d824238062adfd9c.

v2, after codex's dissent on 22d1e3f55fde5acc (2026-09-20T19:41Z). v1 collected bindings in
a PRE-PASS over the whole token stream, which resolved two shapes bash would not:

    echo <marker> > "$OUT"; OUT=/tmp/safe.txt          # binding is LATER than the use
    false && OUT=/tmp/safe.txt; echo <marker> > "$OUT" # binding never RUNS

In both, an inherited `OUT` may name a governed file, and v1 answered `read`. codex's
remedy is the one implemented here: **a binding may be used only if it is proven to have
executed before the use.** Bindings are now collected in traversal order, only at top level
(depth 0), and only when the preceding separator is unconditional (`;`, newline, `&`) — an
`&&`/`||`/`|` guard leaves the name unbound, which refuses.

Three more binder holes are closed here, none of them in codex's factor:
  * a `for` word carrying a GLOB (`*?[`) is not a literal — bash expands it against the
    filesystem, and the match could be a governed path;
  * a value starting with `~` is not a literal either;
  * a later `read`/`export`/`declare`/`local`/`eval`/`source`/`mapfile`/`printf` can rebind
    a name that an earlier assignment bound, so any of those heads clears ALL bindings.
Every one of these leaves the target unresolvable, i.e. refused exactly as before the
repair. The fail direction is: when in doubt, do not resolve.
"""
import os, re

_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_ASSIGN = re.compile(r"\A([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", re.S)
_GLOB = re.compile(r"[*?\[]")
_FANOUT_CAP = 32
_COND_SEPS = frozenset({"&&", "||", "|", "|&"})
_REBINDERS = frozenset({"read", "export", "declare", "typeset", "local", "let", "eval",
                        "source", ".", "mapfile", "readarray", "printf", "getopts", "unset"})
_OPENERS = frozenset({"if", "while", "until", "for", "case", "function", "select",
                      "{", "((", "[["})
_CLOSERS = frozenset({"fi", "done", "esac", "}", "))", "]]"})


def _is_literal(word):
    return isinstance(word, str) and word and not _GLOB.search(word) \
        and not word.startswith("~") and "$" not in word and "`" not in word


def make(g):
    """Return (bash_write_targets, expand) bound to the shipped module `g`, so every helper
    under test is the real one."""

    def _expand(tok, env):
        if not g._has_subst(tok):
            return [tok]
        out = [tok]
        for _ in range(4):
            nxt, changed = [], False
            for cand in out:
                m = _VAR_REF.search(cand)
                if m is None:
                    nxt.append(cand)
                    continue
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
                        return eff          # a computed cd that is not single-valued
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
        toks = g._tokenize(g._strip_heredoc_bodies(command))
        targets, cur = [], []
        stdin_src, eff = None, ""
        env = {}                  # name -> [literal values]; ONLY proven-executed bindings
        cond_names = set()        # bindings made inside an &&/||/| chain — see below
        depth = 0                 # nesting of control-flow blocks; bind only at 0
        guarded = False           # this segment was reached through &&/||/|
        loop_scope = []           # (name, depth) — unbind the loop var at its `done`
        i = 0

        def flush_segment():
            nonlocal eff, cur, stdin_src
            if not cur:
                return
            # A standalone assignment command binds the shell variable — but only when it
            # is certain to have run: top level, and not behind a &&/||/| guard.
            if all(_ASSIGN.match(w) for w in cur):
                for w in cur:
                    m = _ASSIGN.match(w)
                    name, val = m.group(1), m.group(2)
                    if depth == 0 and _is_literal(val):
                        env[name] = [val]
                        # A binding reached through &&/||/| is proven only for uses LATER
                        # IN THE SAME CHAIN: if it did not run, nothing after it in the
                        # chain ran either. It stops being proven at the next `;`/newline,
                        # which is exactly codex's `false && OUT=…; echo … > "$OUT"`.
                        (cond_names.add if guarded else cond_names.discard)(name)
                    else:
                        env.pop(name, None)   # uncertain: the old value is no longer known
                        cond_names.discard(name)
                cur = []
                return
            head = g._strip_wrappers(cur)
            hb = os.path.basename(head[0]) if head and isinstance(head[0], str) else ""
            if hb in _REBINDERS or (head and head[0] in _REBINDERS):
                env.clear()       # any of these can rebind a name we resolved
            eff = _flush(cur, eff, targets, stdin_src, env)
            cur = []

        while i < len(toks):
            t = toks[i]
            if t in g._SEPARATORS:
                flush_segment()
                if t not in _COND_SEPS:
                    for n in cond_names:      # the chain ended; conditional bindings expire
                        env.pop(n, None)
                    cond_names.clear()
                guarded = t in _COND_SEPS
                stdin_src = None
                i += 1
                continue
            if g._is_punct(t):
                if (">" in t or "<" in t) and cur and cur[-1].isdigit():
                    cur.pop()
                if ">" in t:
                    nxt = toks[i + 1] if i + 1 < len(toks) else None
                    if nxt is not None and "&" in t and nxt.isdigit():
                        i += 2
                        continue
                    if nxt is not None and nxt not in g._SEPARATORS and not g._is_punct(nxt):
                        if g._has_subst(nxt):
                            cands = _expand(nxt, env)
                            if cands is None:
                                raise g._OutOfGrammar()
                            targets.extend(g._join_eff(eff, c) for c in cands)
                        else:
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
                i += 1
                continue
            # A `for NAME in <literal words>` header binds NAME for its body only.
            if t == "for" and i + 2 < len(toks) and g._FOR_NAME.match(toks[i + 1] or "") \
                    and toks[i + 2] == "in":
                words, j = [], i + 3
                while j < len(toks) and toks[j] not in g._SEPARATORS and toks[j] != "do":
                    words.append(toks[j])
                    j += 1
                name = toks[i + 1]
                # A for-header binding is scoped to the BODY, and the body runs only if
                # the header ran — so a guard on the header cannot make the binding wrong.
                if words and all(_is_literal(w) for w in words):
                    env[name] = words
                else:
                    env.pop(name, None)
                loop_scope.append((name, depth))
                depth += 1
                cur = []
                i = j
                continue
            if t in _OPENERS:
                depth += 1
            elif t in _CLOSERS:
                depth = max(0, depth - 1)
                while loop_scope and loop_scope[-1][1] >= depth:
                    env.pop(loop_scope.pop()[0], None)
            cur.append(t)
            i += 1
        flush_segment()
        return targets

    return _bash_write_targets, _expand
