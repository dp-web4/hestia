import pathlib
p = pathlib.Path("/tmp/s1314e/core_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

# Codex HOLD on f08a274b: curl accepted `--remote-name-a` (an unambiguous prefix of
# `--remote-name-all`) and wrote O/fresh.txt. Matching only full spellings was evidence of absence
# read from a set curl does not use. A long option now establishes nothing unless it is an EXACT
# known name: abbreviations, case variants, `--no-`/`--expand-` forms and options this table has
# never heard of all leave the output unestablished.
sub1('''_URL_IMPLICIT_LONG["curlie"] = _URL_IMPLICIT_LONG["curl"]
_URL_IMPLICIT_SHORT = {"curl": "OJK", "curlie": "OJK"}
''', '''_URL_IMPLICIT_LONG["curlie"] = _URL_IMPLICIT_LONG["curl"]
_URL_IMPLICIT_SHORT = {"curl": "OJK", "curlie": "OJK"}

#: #1314 (Codex HOLD on f08a274b): the ONLY long option words that leave a URL client's output
#: established, matched exactly. curl and HTTPie (argparse) both accept an unambiguous PREFIX of a
#: long option (`--remote-name-a` is `--remote-name-all`; curl 8.5 also matches case-insensitively),
#: so the absence of a full spelling from `_URL_IMPLICIT_LONG` proves nothing. Any long word not
#: listed here, an abbreviation of a safe option included, leaves the output unestablished, and the
#: URL is judged as a path, as on main. Value-taking options are listed so that ordinary commands
#: (`curl --header ... --output F URL`) keep the exemption; their values are judged by the caller.
_CURL_VALUE_LONG = frozenset((
    "--output", "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
    "--request", "--user-agent", "--user", "--referer", "--max-time", "--connect-timeout",
    "--retry", "--retry-delay", "--retry-max-time", "--write-out", "--cookie", "--form",
    "--range", "--resolve", "--proxy", "--oauth2-bearer", "--url", "--max-redirs",
    "--limit-rate", "--max-filesize", "--speed-time", "--speed-limit", "--cacert", "--interface",
))
_HTTPIE_VALUE_LONG = frozenset((
    "--output", "--auth", "--auth-type", "--timeout", "--pretty", "--style", "--print",
    "--verify", "--max-redirects", "--proxy", "--cert", "--cert-key", "--format-options",
    "--session", "--session-read-only",
))
_URL_SAFE_LONG = {
    "curl": (_CURL_FLAGS[1] | _CURL_VALUE_LONG) - _URL_IMPLICIT_LONG["curl"],
    "curlie": (_CURL_FLAGS[1] | _CURL_VALUE_LONG) - _URL_IMPLICIT_LONG["curl"],
}
for _h in _HTTPIE_HEADS:
    _URL_SAFE_LONG[_h] = (_HTTPIE_FLAGS[1] | _HTTPIE_VALUE_LONG) - {"--download"}
''')
sub1('''    longs = _URL_IMPLICIT_LONG.get(head, frozenset())
    shorts = _URL_IMPLICIT_SHORT.get(head, "")
''', '''    longs = _URL_IMPLICIT_LONG.get(head, frozenset())
    safe_longs = _URL_SAFE_LONG.get(head, frozenset())
    shorts = _URL_IMPLICIT_SHORT.get(head, "")
''')
sub1('''        if w.startswith("--"):
            continue
        for ch in w[1:]:
            if ch in shorts or (head in _HTTPIE_HEADS and ch == "d"):''',
     '''        if w.startswith("--"):
            if name not in safe_longs:
                return False                               # an abbreviation, or unknown (f08a274b)
            continue
        for ch in w[1:]:
            if ch in shorts or (head in _HTTPIE_HEADS and ch == "d"):''')
sub1('''    option listed in `_URL_IMPLICIT_*` and any HTTPie / xh `--download`. When this is False, no''',
     '''    option listed in `_URL_IMPLICIT_*`, any HTTPie / xh `--download`, and any long option that is
    not an exact name in `_URL_SAFE_LONG` (an abbreviation like `--remote-name-a`, Codex HOLD on
    f08a274b). When this is False, no''')
sub1('    f08a274b). When this is False, no\n    operand is exempted as a URL (Codex HOLD on f46bc32b: `cd O && curl -sSO URL` wrote\n    `O/fresh.txt` under an exact grant on O).',
     '    f08a274b). When this is False, no operand is exempted as a URL (Codex HOLD on f46bc32b:\n    `cd O && curl -sSO URL` wrote `O/fresh.txt` under an exact grant on O).')
p.write_text(s)
print("ok")
