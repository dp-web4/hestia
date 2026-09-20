"""Proposed repair: resolve statically-resolvable write targets before declaring a
command out of grammar. Developed against the shipped module IN MEMORY (no file copy of
the governed module is made, and none is written) — see gate escalations 22d1e3f55fde5acc
and d824238062adfd9c."""
import os, re
from typing import Optional

_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_ASSIGN = re.compile(r"\A([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", re.S)
_FANOUT_CAP = 32


def make(g):
    """Return (collect_env, expand, bash_write_targets, flush_simple_command) bound to the
    shipped module `g`, so every helper under test is the real one."""

    def _collect_env(toks):
        env = {}

        def bind(name, values):
            if name in env and env[name] != values:
                env[name] = None
            elif name not in env:
                env[name] = values

        seg, i = [], 0
        while i <= len(toks):
            if i == len(toks) or toks[i] in g._SEPARATORS:
                if seg and all(_ASSIGN.match(w) for w in seg):
                    for w in seg:
                        m = _ASSIGN.match(w)
                        val = m.group(2)
                        bind(m.group(1), None if g._has_subst(val) else [val])
                seg = []
                i += 1
                continue
            t = toks[i]
            if t == "for" and i + 2 < len(toks) and g._FOR_NAME.match(toks[i + 1] or "") \
                    and toks[i + 2] == "in":
                words, j = [], i + 3
                while j < len(toks) and toks[j] not in g._SEPARATORS and toks[j] != "do":
                    words.append(toks[j])
                    j += 1
                bind(toks[i + 1], None if any(g._has_subst(w) for w in words) else words)
                seg = []
                i = j
                continue
            seg.append(t)
            i += 1
        return env

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
                name = m.group(1) or m.group(2)
                vals = env.get(name)
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

    def _flush_simple_command(words, eff, targets, stdin_src=None, env=None):
        env = env or {}
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
                    cands = _expand(d, env)          # REPAIR: a resolvable cd is tracked
                    if not cands or len(cands) != 1:
                        return eff
                    d = cands[0]
                eff = d if (os.path.isabs(d) or d.startswith("~")) \
                    else os.path.normpath(os.path.join(eff or ".", d))
            return eff
        for tg in g._command_write_targets(words, stdin_src):
            if g._has_subst(tg):
                cands = _expand(tg, env)             # REPAIR
                if cands is None:
                    raise g._OutOfGrammar()
                for c in cands:
                    targets.append(g._join_eff(eff, c))
                continue
            targets.append(g._join_eff(eff, tg))
        return eff

    def _bash_write_targets(command):
        toks = g._tokenize(g._strip_heredoc_bodies(command))
        env = _collect_env(toks)                     # REPAIR: one pre-pass, whole command
        targets, cur = [], []
        stdin_src = None
        eff = ""
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in g._SEPARATORS:
                if cur:
                    eff = _flush_simple_command(cur, eff, targets, stdin_src, env)
                    cur = []
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
                            cands = _expand(nxt, env)   # REPAIR
                            if cands is None:
                                raise g._OutOfGrammar()
                            for c in cands:
                                targets.append(g._join_eff(eff, c))
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
            cur.append(t)
            i += 1
        if cur:
            eff = _flush_simple_command(cur, eff, targets, stdin_src, env)
        return targets

    return _collect_env, _expand, _bash_write_targets, _flush_simple_command
