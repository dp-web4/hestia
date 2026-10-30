import pathlib
p = pathlib.Path("/tmp/s1314e/core_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

sub1('''    leaves it unestablished, as does any option listed in `_URL_IMPLICIT_*`. When this is False,
    no operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote
    `O/fresh.txt` under an exact grant on O)."""''',
'''    leaves it unestablished, as does any option listed in `_URL_IMPLICIT_*`. When this is False,
    no operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote
    `O/fresh.txt` under an exact grant on O).

    Evidence FOR an established output (wget `-O`/`--spider`, HTTPie `-o`) is the other way round:
    it counts only where the word is certainly an option, never where it may be the previous
    option's value. `wget -U -O- URL` sends `-O-` as the user agent and still saves `fresh.txt` in
    the cwd (Codex HOLD on 68e951fc). So it does not count after any option that is not known to
    take no value (`_url_option_frees_next`), nor after any `--`, which may end the options. A
    `--` no longer stops the scan: it may itself be a value (`wget -U -- -r URL` recurses)."""''')
sub1('''    named_output = download = spider = False
    skip = False
    for i in range(at + 1, len(toks)):''',
'''    named_output = download = spider = False
    skip = False
    maybe_value = options_may_end = False                  # see the docstring's last paragraph
    for i in range(at + 1, len(toks)):''')
sub1('''        if w == "--":
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
                break                                      # a value letter: the rest is its value''',
'''        option = not (maybe_value or options_may_end)      # certainly an option, if `-`-shaped
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
                break                                      # a value letter: the rest is its value''')
p.write_text(s)
print("edited")
