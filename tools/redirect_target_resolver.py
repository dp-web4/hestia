"""v5: resolve a write target only from a binding in an UNCONDITIONAL, UNNESTED position.

v1-v3 were a blacklist -- resolve, then subtract the shapes bash would not honour. codex
found 2 holes in v1; I found 3 more while fixing those; codex then found 6 more in v3
(notices 13363/13364, all six reproduced write->read here). The hole space is the shell
grammar, so the blacklist cannot close by enumeration.

v5 inverts the default: a name is resolvable ONLY if all four hold.

  (P1) the binding is a standalone assignment segment at nesting depth 0 -- not inside any
       ( ), { }, if/while/until/case/for body. A nested binding may not have run, and one
       inside ( ) or a pipeline runs in a subshell the parent never sees.
  (P2) the separator BEFORE it is `;`, a newline, or the start of the command. Anything
       else (`&&`, `||`, `|`, `&`) means the assignment itself may never have run --
       codex's `false && OUT=... || write` and `true || OUT=... && write`.
  (P3) the separator AFTER it is `;`, a newline, or `&&`. `|` makes it a pipeline
       component and `&` backgrounds it: in both, bash discards the binding at the
       subshell boundary -- codex's `OUT=... | write` and `OUT=... & write`.
  (P4) the name is assigned EXACTLY ONCE in the whole token stream, at ANY depth, and no
       rebinder head (read/export/eval/...) appears anywhere. A second assignment the
       depth-0 scan never reaches still changes the value at the point of use -- codex's
       `OUT=/tmp/safe; if true; then OUT=<governed>; fi; write`.

Each clause is a property of ONE token's neighbourhood, so none of them requires reasoning
about which branch of which operator executed -- which is the reasoning that failed three
times. The `for NAME in <literal words>` binding is kept and is subject to (P4): the body
runs only if the header ran, so it is proven by construction rather than by position.

Everything else refuses exactly as the shipped module does today. The fail direction is
unchanged: when in doubt, do not resolve.
"""
import os, re

_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_ASSIGN = re.compile(r"\A([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", re.S)
_GLOB = re.compile(r"[*?\[]")
_FANOUT_CAP = 32
# Nesting: a binding inside any of these is at depth > 0 and fails (P1). `(` is included
# because a subshell's assignment never reaches the parent.
_OPENERS = frozenset({"if", "while", "until", "for", "case", "function", "select",
                      "{", "((", "[[", "("})
_CLOSERS = frozenset({"fi", "done", "esac", "}", "))", "]]", ")"})
# (P3) separators that may FOLLOW a binding. `;`/newline end the list; `&&` still runs the
# assignment in this shell. `|` makes it a pipeline component and `&` backgrounds it --
# both put it in a subshell whose binding the parent never sees.
_AFTER_OK = frozenset({";", "\n", "&&"})
# (P2) separators that may PRECEDE a binding: the only ones that prove it ran at all.
# `&&`/`||` make running it conditional on something else's exit status.
_UNCOND_SEPS = frozenset({";", "\n"})
_REBINDERS = frozenset({"read", "export", "declare", "typeset", "local", "let", "eval",
                        "source", ".", "mapfile", "readarray", "printf", "getopts", "unset"})


def _is_literal(word):
    return isinstance(word, str) and word and not _GLOB.search(word) \
        and not word.startswith("~") and "$" not in word and "`" not in word


def make(g):
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

    def _assignment_census(toks):
        """name -> how many times it is assigned ANYWHERE, at any depth. Also whether any
        rebinder head appears at all."""
        counts, rebinder = {}, False
        for i, t in enumerate(toks):
            if not isinstance(t, str):
                continue
            m = _ASSIGN.match(t)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
                continue
            base = os.path.basename(t)
            if t in _REBINDERS or base in _REBINDERS:
                rebinder = True
            if t == "for" and i + 2 < len(toks) and toks[i + 2] == "in" \
                    and g._FOR_NAME.match(toks[i + 1] or ""):
                counts[toks[i + 1]] = counts.get(toks[i + 1], 0) + 1
        return counts, rebinder

    def _bindings(toks, counts, rebinder):
        """(P1)-(P4). One pass, no branch reasoning: for each standalone assignment segment
        we look only at the separator before it, the separator after it, and its depth."""
        env = {}
        if rebinder:
            return env
        depth, seg, prev_sep, seg_at = 0, [], ";", 0   # start of command == unconditional
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in _OPENERS:
                depth += 1; seg.append(t); i += 1; continue
            if t in _CLOSERS:
                depth = max(0, depth - 1); seg.append(t); i += 1; continue
            if t in g._SEPARATORS:
                if seg and depth == 0 and prev_sep in _UNCOND_SEPS \
                        and t in _AFTER_OK and all(_ASSIGN.match(w) for w in seg):
                    for w in seg:
                        m = _ASSIGN.match(w)
                        if _is_literal(m.group(2)) and counts.get(m.group(1)) == 1:
                            env[m.group(1)] = (i, [m.group(2)])
                seg, prev_sep, seg_at = [], t, i + 1
                i += 1; continue
            seg.append(t); i += 1
        # trailing segment: end-of-command counts as `;` for (P3)
        if seg and depth == 0 and prev_sep in _UNCOND_SEPS and all(_ASSIGN.match(w) for w in seg):
            for w in seg:
                m = _ASSIGN.match(w)
                if _is_literal(m.group(2)) and counts.get(m.group(1)) == 1:
                    env[m.group(1)] = (len(toks), [m.group(2)])
        return env

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
        toks = g._tokenize(g._strip_heredoc_bodies(command))
        counts, rebinder = _assignment_census(toks)
        # name -> (token index of the binding, values). A binding becomes visible only
        # once the walk has PASSED it: a use EARLIER in the stream reads whatever the
        # caller inherited, which is codex's v1 hole `write > "$OUT"; OUT=/tmp/safe`.
        pending = _bindings(toks, counts, rebinder)
        env, loop_env = {}, {}
        targets, cur = [], []
        stdin_src, eff = None, ""
        loop_scope, depth = [], 0
        i = 0

        def view():
            merged = dict(env); merged.update(loop_env); return merged

        def promote(upto):
            for n, (at, vals) in list(pending.items()):
                if at < upto:
                    env[n] = vals; del pending[n]

        def flush_segment():
            nonlocal eff, cur, stdin_src
            if not cur:
                return
            if all(_ASSIGN.match(w) for w in cur):
                cur = []; return
            eff = _flush(cur, eff, targets, stdin_src, view())
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
                            cands = _expand(nxt, view())
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
            if t == "for" and i + 2 < len(toks) and g._FOR_NAME.match(toks[i + 1] or "") \
                    and toks[i + 2] == "in":
                words, j = [], i + 3
                while j < len(toks) and toks[j] not in g._SEPARATORS and toks[j] != "do":
                    words.append(toks[j]); j += 1
                name = toks[i + 1]
                if words and all(_is_literal(w) for w in words) and counts.get(name) == 1 \
                        and not rebinder:
                    loop_env[name] = words
                else:
                    loop_env.pop(name, None)
                loop_scope.append((name, depth)); depth += 1
                cur = []; i = j; continue
            if t in ("if", "while", "until", "case", "function", "select", "{", "((", "[["):
                depth += 1
            elif t in ("fi", "done", "esac", "}", "))", "]]"):
                depth = max(0, depth - 1)
                while loop_scope and loop_scope[-1][1] >= depth:
                    loop_env.pop(loop_scope.pop()[0], None)
            cur.append(t); i += 1
        flush_segment()
        return targets

    return _bash_write_targets, _expand
