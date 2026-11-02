"""EXPERIMENT ONLY (never in the held patch): narrow/gcore.py plus a literal-assignment rule, to
MEASURE what that one candidate exception would recover. Writes narrow_exp/gcore.py.

The rule: `$N` / `${N}` resolves to a LITERAL value only when N is assigned exactly once in the
whole command (lifted substitution bodies included), as a standalone top-level statement (paren
and keyword depth 0), entered from the start, `;` or a newline (never after `&&` / `||`), ended
by `;`, a newline or `&&` (never `&`, `|`, or a command it would prefix), with a value containing
no expansion, glob or brace; and N is never a `for` / `read` / `export` / `local` / `declare` /
`typeset` / `readonly` / `unset` operand; and the command has no `eval`, `source`, `.` or function
definition. Uses BEFORE the assignment stay unenumerated.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
src = (HERE / "narrow" / "gcore.py").read_text()
out = HERE / "narrow_exp"
out.mkdir(exist_ok=True)


def rep(s, old, new):
    assert s.count(old) == 1, (old[:60], s.count(old))
    return s.replace(old, new)


# _word_value consults a module-level map of names known to hold a literal.
src = rep(src, '''def _word_value(value: str) -> str:''', '''_KNOWN_LITERALS: dict = {}


def _word_value(value: str) -> str:''')
src = rep(src, '''        elif ref in _PLACEHOLDER_PARAMS:
            out.append(_PLACEHOLDER_PARAMS[ref])
        else:
            raise _Unenumerated(_expansion_kind(ref))''', '''        elif ref in _PLACEHOLDER_PARAMS:
            out.append(_PLACEHOLDER_PARAMS[ref])
        elif (ref[1:] if not ref.startswith("${") else ref[2:-1]) in _KNOWN_LITERALS:
            out.append(_KNOWN_LITERALS[ref[1:] if not ref.startswith("${") else ref[2:-1]])
        else:
            raise _Unenumerated(_expansion_kind(ref))''')

# A pre-pass over the tokens decides which names qualify; the scan commits each at its statement.
src = rep(src, '''    toks = _shell_words(cmd)
    state = {}
''', '''    toks = _shell_words(cmd)
    state = {}
    if depth == 0:
        _KNOWN_LITERALS.clear()
    qualifying = _literal_candidates(toks)
    pending_lit = None
    prev_sep = ";"
    pdepth = kdepth = 0
''')
src = rep(src, '''    for kind, w, uglob in toks:
        p, prev = prev, (kind, w)
''', '''    for kind, w, uglob in toks:
        p, prev = prev, (kind, w)
        if pending_lit is not None:
            name_, val_ = pending_lit
            pending_lit = None
            if kind == "sep" and w in (";", "&&"):
                _KNOWN_LITERALS[name_] = val_
        if kind == "sep" and w == "(":
            pdepth += 1
        elif kind == "sep" and w == ")":
            pdepth = max(0, pdepth - 1)
        elif kind == "word" and state.get("head") is None and w in ("if", "while", "until", "for", "case", "{"):
            kdepth += 1
        elif kind == "word" and state.get("head") is None and w in ("fi", "done", "esac", "}"):
            kdepth = max(0, kdepth - 1)
''')
src = rep(src, '''                if name not in _NONPATH_ASSIGNMENTS:
                    if literal:
                        emit(val, uglob)
                    elif state["env_expansion"] is None:
                        state["env_expansion"] = name
                continue
            base = os.path.basename(w)''', '''                if name not in _NONPATH_ASSIGNMENTS:
                    if literal:
                        emit(val, uglob)
                    elif state["env_expansion"] is None:
                        state["env_expansion"] = name
                if (literal and name in qualifying and pdepth == 0 and kdepth == 0
                        and prev_sep in (";", "\\n") and not uglob and _BRACE not in val):
                    pending_lit = (name, _word_value(val))
                continue
            base = os.path.basename(w)''')
# remember the separator a statement was entered from
src = rep(src, '''        if kind == "sep" or (kind == "word" and state["head"] is None and w in _SHELL_KEYWORDS):
            seg_words = []
            new_segment()
            continue''', '''        if kind == "sep" or (kind == "word" and state["head"] is None and w in _SHELL_KEYWORDS):
            seg_words = []
            new_segment()
            prev_sep = w if kind == "sep" else "kw"
            continue''')
src = rep(src, '''def _dir_bases(dirs, cwd: str):''', '''def _literal_candidates(toks) -> set:
    """Names assigned exactly once in the token stream and never otherwise bound."""
    count, banned = {}, set()
    words = [w for k, w, _g in toks if k == "word"]
    if any(w in ("eval", "source", ".") for w in words) or any(
            k == "sep" and w == "(" and i > 0 and toks[i - 1][0] == "word" and toks[i - 1][1].endswith("()")
            for i, (k, w, _g) in enumerate(toks)):
        return set()
    for i, w in enumerate(words):
        if w in ("for", "read", "export", "local", "declare", "typeset", "readonly", "unset"):
            for nxt in words[i + 1:i + 8]:
                n = nxt.split("=", 1)[0]
                if n.isidentifier():
                    banned.add(n)
        if w.endswith("()"):
            return set()
        n, eq, _v = w.partition("=")
        if eq and n.isidentifier():
            count[n] = count.get(n, 0) + 1
    return {n for n, c in count.items() if c == 1 and n not in banned and n != "HOME"}


def _dir_bases(dirs, cwd: str):''')
(out / "gcore.py").write_text(src)
print("experimental core written")
