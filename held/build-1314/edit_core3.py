import pathlib
p = pathlib.Path("/tmp/s1314e/core_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

# Codex HOLD on 570f6e82: wget `--spider --no-spider` kept the spider evidence. Rather than model
# negation too, wget is no longer a URL client here: its operands are judged as on main.
sub1('''_URL_HEADS = frozenset(("curl", "wget", "http", "https", "xh", "xhs", "curlie"))''',
     '''#: wget is NOT one (Codex HOLD on 570f6e82): it saves a file in the cwd unless its final option
#: state says otherwise, and that state has negations (`--no-spider`) and overrides. So its operands
#: are judged as on main.
_URL_HEADS = frozenset(("curl", "http", "https", "xh", "xhs", "curlie"))''')
sub1('''#: ends in a value-taking letter) may consume the next word as a file, so a URL-shaped word there
#: is judged as a path: `curl --create-dirs -o http://newdir/f URL` writes `./http:/newdir/f`.
#: An ATTACHED value (`-ofile`, `-qO-`, `--output=x`) consumes nothing more. Letters per curl 8,
#: wget 1.21 and httpie 3 / xh `--help`.''',
     '''#: ends in a value-taking letter) may consume the next word as a file, so a URL-shaped word there
#: is judged as a path: `curl --create-dirs -o http://newdir/f URL` writes `./http:/newdir/f`.
#: An ATTACHED value (`-ofile`, `--output=x`) consumes nothing more. Letters per curl 8 and
#: httpie 3 / xh `--help`.''')
sub1('''_URL_FLAGS = {
    "curl": _CURL_FLAGS, "curlie": _CURL_FLAGS,
    "wget": ("46bcdEFhHkKLmNpqrSvVx", frozenset((
        "--quiet", "--verbose", "--no-verbose", "--server-response", "--spider", "--continue",
        "--timestamping", "--recursive", "--no-parent", "--no-clobber", "--no-directories",
        "--no-host-directories", "--no-check-certificate", "--show-progress", "--mirror",
        "--page-requisites", "--convert-links", "--adjust-extension", "--content-disposition",
        "-nv", "-nc", "-nd", "-nH", "-np"))),
}''', '''_URL_FLAGS = {"curl": _CURL_FLAGS, "curlie": _CURL_FLAGS}''')
sub1('''#: #1314 (Codex HOLD on f46bc32b): option words that make a URL client WRITE A FILE whose name it
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
_URL_IMPLICIT_SHORT = {"curl": "OJK", "curlie": "OJK", "wget": "rmpbei"}''',
'''#: #1314 (Codex HOLD on f46bc32b): option words that make a URL client WRITE A FILE whose name it
#: derives (from the URL or the response) rather than one the command names: curl `-O`/
#: `--remote-name[-all]`/`-J`, HTTPie / xh `--download` (`-d`). Also every word that can change
#: the output mode unseen: a config (`curl -K`), curl `--output-dir`. Not modelled: a `~/.curlrc`
#: that sets a remote-name mode.
_URL_IMPLICIT_LONG = {
    "curl": frozenset(("--remote-name", "--remote-name-all", "--remote-header-name", "--config",
                       "--output-dir")),
}
_URL_IMPLICIT_LONG["curlie"] = _URL_IMPLICIT_LONG["curl"]
_URL_IMPLICIT_SHORT = {"curl": "OJK", "curlie": "OJK"}''')
sub1('''def _url_output_established(toks, at, head) -> bool:
    """#1314: does the URL client whose command word is `toks[at]` write only to stdout or to a
    destination the command names? Reads EVERY word of the simple command first, because an
    output-mode option may follow the URL (`curl URL -O`). Every option word is checked, including
    one that is really another option's value: a false match only judges the URL as a path, which
    is main's behaviour. A word that may expand to an option (`$OPTS`, a glob, `{a,b}`, `-$X`)
    leaves it unestablished, as does any option listed in `_URL_IMPLICIT_*`. When this is False,
    no operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote
    `O/fresh.txt` under an exact grant on O).

    Evidence FOR an established output (wget `-O`/`--spider`, HTTPie `-o`) is the other way round:
    it counts only where the word is certainly an option, never where it may be the previous
    option's value. `wget -U -O- URL` sends `-O-` as the user agent and still saves `fresh.txt` in
    the cwd (Codex HOLD on 68e951fc). So it does not count after any option that is not known to
    take no value (`_url_option_frees_next`), nor after any `--`, which may end the options. A
    `--` no longer stops the scan: it may itself be a value (`wget -U -- -r URL` recurses)."""
    longs = _URL_IMPLICIT_LONG.get(head, frozenset())
    shorts = _URL_IMPLICIT_SHORT.get(head, "")
    letters = _URL_FLAGS.get(head, ("", frozenset()))[0]
    named_output = download = spider = False
    skip = False
    maybe_value = options_may_end = False                  # see the docstring's last paragraph
    for i in range(at + 1, len(toks)):''',
'''def _url_output_established(toks, at, head) -> bool:
    """#1314: does the URL client whose command word is `toks[at]` write only to stdout or to a
    destination the command names? Reads EVERY word of the simple command first, because an
    output-mode option may follow the URL (`curl URL -O`). Every option word is checked, including
    one that is really another option's value, and a `--` does not stop the scan (it may itself be
    a value): a false match only judges the URL as a path, which is main's behaviour. A word that
    may expand to an option (`$OPTS`, a glob, `{a,b}`, `-$X`) leaves it unestablished, as does any
    option listed in `_URL_IMPLICIT_*` and any HTTPie / xh `--download`. When this is False, no
    operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote
    `O/fresh.txt` under an exact grant on O).

    Only evidence AGAINST is read. There is no evidence FOR: curl and HTTPie write to stdout unless
    told otherwise, and a client whose default writes a file (wget, `http --download`) is never
    established. Positive evidence was held three times (Codex HOLDs on 68e951fc and 570f6e82: an
    output option in a value position, then `--spider --no-spider`), because it has to describe
    the client's final option state, negations and overrides included."""
    longs = _URL_IMPLICIT_LONG.get(head, frozenset())
    shorts = _URL_IMPLICIT_SHORT.get(head, "")
    letters = _URL_FLAGS.get(head, ("", frozenset()))[0]
    skip = False
    for i in range(at + 1, len(toks)):''')
sub1('''        if uglob or _BRACE in w or (spans and (spans[0][0] == 0 or w.startswith("-"))):
            return False                                   # may be, or hide, an option
        option = not (maybe_value or options_may_end)      # certainly an option, if `-`-shaped
        if w == "--":
            options_may_end = True
        if not w.startswith("-") or w in ("-", "--"):
            maybe_value = False
            continue
        maybe_value = not _url_option_frees_next(head, w)
        name = w.partition("=")[0]
        if name in longs:
            return False
        if name == "--download":
            download = True
        elif option and name in ("--output-document", "--output"):
            named_output = True
        elif option and name == "--spider":
            spider = True
        if w.startswith("--"):
            continue
        for ch in w[1:]:
            if ch in shorts:
                return False
            if ch == "d":
                download = True
            if ch not in letters:
                if option and ((head == "wget" and ch == "O")
                               or (head in _HTTPIE_HEADS and ch == "o")):
                    named_output = True
                break                                      # a value letter: the rest is its value
    if head == "wget":
        return named_output or spider
    if head in _HTTPIE_HEADS:
        return named_output or not download
    return True''',
'''        if uglob or _BRACE in w or (spans and (spans[0][0] == 0 or w.startswith("-"))):
            return False                                   # may be, or hide, an option
        if not w.startswith("-") or w in ("-", "--"):
            continue
        name = w.partition("=")[0]
        if name in longs or (head in _HTTPIE_HEADS and name == "--download"):
            return False
        if w.startswith("--"):
            continue
        for ch in w[1:]:
            if ch in shorts or (head in _HTTPIE_HEADS and ch == "d"):
                return False
            if ch not in letters:
                break                                      # a value letter: the rest is its value
    return True''')
p.write_text(s)
print("ok")
