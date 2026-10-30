import pathlib, re
p = pathlib.Path("/tmp/s1314e/core_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

def cut_between(start, end):
    """Remove from `start` (inclusive) up to `end` (exclusive), each present once."""
    global s
    assert s.count(start) == 1 and s.count(end) == 1, (start[:50], end[:50])
    i, j = s.index(start), s.index(end)
    assert i < j
    s = s[:i] + s[j:]

# Codex HOLD on c5e8c860 (seventh on the URL exemption): `curl -w '%output{f}…'` and an output
# template `-o 'out#1'` with a URL glob both write files no word names. The network-URL exemption
# is withdrawn from #1314 and tracked on its own issue; URL operands are judged as on main.
sub1('''#: URL CLIENTS: commands whose positional arguments are URLs. For these, `host:port[/…]` is a URL
#: too (curl assumes http when no scheme is given), not a relative path.
#: wget is NOT one (Codex HOLD on 570f6e82): it saves a file in the cwd unless its final option
#: state says otherwise, and that state has negations (`--no-spider`) and overrides. So its operands
#: are judged as on main.
_URL_HEADS = frozenset(("curl", "http", "https", "xh", "xhs", "curlie"))
_HOSTPORT = re.compile(r"^(?:localhost|[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                       r"(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*|\\[[0-9A-Fa-f:.]+\\])"
                       r":\\d{1,5}(?:[/?#]|$)")
_URL_WITH_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_FILE_URL''', '''#: A NETWORK URL operand (`curl http://h/x` after `cd O`) is still judged as a relative path, as on
#: main. Exempting it was held seven times (PR #1328): each hold found another way for curl or
#: HTTPie to write a file no word names (`-O`, abbreviations, `-w '%output{f}'`, `-o 'f#1'` with a
#: URL glob). That needs a model of the client's whole output language; it is its own issue.
_FILE_URL''')

cut_between('''def _network_url(value: str, head: Optional[str]) -> bool:''',
            '''def _leading_absolute_cd(cmd: str) -> Optional[str]:''')

cut_between('''    def url_argument(word, head):''', '''    def in_force():''')

sub1('''                     jq_data=set(), url_operand=True, url_output=False)''',
     '''                     jq_data=set())''')
sub1('''            if base in _URL_HEADS:
                state["url_output"] = _url_output_established(toks, idx, base)
''', '')
sub1('''            state["url_operand"] = _url_option_frees_next(head, w)
''', '')
sub1('''        url_operand, state["url_operand"] = state["url_operand"], True
''', '')
sub1('''        if not uglob and url_operand and state["url_output"] and url_argument(w, head):
            continue
''', '')
cut_between('''    urls = [(s_, g_) for s_, k_, g_ in candidates if k_ == "url"]''',
            '''    rels = [(s_, g_) for s_, k_, g_ in candidates if k_ == "rel"]''')
for w in ("_URL_HEADS", "_network_url", "_url_output", "url_operand", "_URL_FLAGS", '"url"'):
    assert w not in s, w
p.write_text(s)
print("ok")
