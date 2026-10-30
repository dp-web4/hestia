import pathlib
p = pathlib.Path("/tmp/s1314e/core_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

NEW_FN = '''

#: #1314 (Codex HOLD on f46bc32b): option words that make a URL client WRITE A FILE whose name it
#: derives (from the URL or the response) rather than one the command names: curl `-O`/
#: `--remote-name[-all]`/`-J`, wget with no `-O` (its default is a file in the cwd), HTTPie / xh
#: `--download` with no `-o`. Also every word that can change the output mode unseen: a config
#: (`curl -K`, `wget -e`/`--config`), wget recursion or `-b` (which writes `wget-log`), curl
#: `--output-dir`. Not modelled: a `~/.curlrc` or `~/.wgetrc` that sets a remote-name mode.
_URL_IMPLICIT_LONG = {
    "curl": frozenset(("--remote-name", "--remote-name-all", "--remote-header-name", "--config",
                       "--output-dir")),
    "wget": frozenset(("--recursive", "--mirror", "--page-requisites", "--background",
                       "--execute", "--config", "--input-file", "--base")),
}
_URL_IMPLICIT_LONG["curlie"] = _URL_IMPLICIT_LONG["curl"]
_URL_IMPLICIT_SHORT = {"curl": "OJK", "curlie": "OJK", "wget": "rmpbei"}


def _url_output_established(toks, at, head) -> bool:
    """#1314: does the URL client whose command word is `toks[at]` write only to stdout or to a
    destination the command names? Reads EVERY word of the simple command first, because an
    output-mode option may follow the URL (`curl URL -O`). Every option word is checked, including
    one that is really another option's value: a false match only judges the URL as a path, which
    is main's behaviour. A word that may expand to an option (`$OPTS`, a glob, `{a,b}`, `-$X`)
    leaves it unestablished, as does any option listed in `_URL_IMPLICIT_*`. When this is False,
    no operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote
    `O/fresh.txt` under an exact grant on O)."""
    longs = _URL_IMPLICIT_LONG.get(head, frozenset())
    shorts = _URL_IMPLICIT_SHORT.get(head, "")
    letters = _URL_FLAGS.get(head, ("", frozenset()))[0]
    named_output = download = spider = False
    skip = False
    for i in range(at + 1, len(toks)):
        kind, w, uglob = toks[i]
        if kind in ("sep", "mark"):
            break
        if kind == "op":
            skip = True                                    # a redirection's target is not argv
            continue
        if skip:
            skip = False
            continue
        try:
            spans = _expansion_spans(w)
        except _Unmodelled:
            return False
        if uglob or _BRACE in w or (spans and (spans[0][0] == 0 or w.startswith("-"))):
            return False                                   # may be, or hide, an option
        if w == "--":
            break
        if not w.startswith("-") or w == "-":
            continue
        name = w.partition("=")[0]
        if name in longs:
            return False
        if name in ("--output-document", "--output"):
            named_output = True
        elif name == "--download":
            download = True
        elif name == "--spider":
            spider = True
        if w.startswith("--"):
            continue
        for ch in w[1:]:
            if ch in shorts:
                return False
            if ch == "d":
                download = True
            if ch not in letters:
                if (head == "wget" and ch == "O") or (head in _HTTPIE_HEADS and ch == "o"):
                    named_output = True
                break                                      # a value letter: the rest is its value
    if head == "wget":
        return named_output or spider
    if head in _HTTPIE_HEADS:
        return named_output or not download
    return True
'''

sub1('''for _h in ("http", "https", "xh", "xhs"):
    _URL_FLAGS[_h] = _HTTPIE_FLAGS
''', '''_HTTPIE_HEADS = frozenset(("http", "https", "xh", "xhs"))
for _h in _HTTPIE_HEADS:
    _URL_FLAGS[_h] = _HTTPIE_FLAGS
''' + NEW_FN)

sub1('''                     jq_data=set(), url_operand=True)''',
     '''                     jq_data=set(), url_operand=True, url_output=False)''')
sub1('''                state["jq_data"] = _jq_data_words(toks, idx)   # #1314: its program is text
''', '''                state["jq_data"] = _jq_data_words(toks, idx)   # #1314: its program is text
            if base in _URL_HEADS:
                state["url_output"] = _url_output_established(toks, idx, base)
''')
sub1('''        if not uglob and url_operand and url_argument(w, head):''',
     '''        if not uglob and url_operand and state["url_output"] and url_argument(w, head):''')
p.write_text(s)
print("edited")
