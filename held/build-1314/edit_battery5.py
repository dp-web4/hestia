import pathlib
p = pathlib.Path("/tmp/s1314e/battery_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

WITHDRAWN = [
    '            ("1314-url-hostport-after-cd", f"cd {out_cwd} && curl -s -m 3 localhost:8760/health"),\n',
    '            ("1314-url-scheme-after-cd", f"cd {out_cwd} && curl -s -m 3 http://127.0.0.1:8760/health"),\n',
    '            ("1314-url-after-git-C", f"git -C {out_cwd} status && curl -s https://api.github.com/x"),\n',
    '            ("1314-url-curl-stdout-after-cd", f"cd {out_cwd} && curl -sS http://h/x"),\n',
    '            ("1314-url-curl-exact-long-flags-after-cd", f"cd {out_cwd} && curl --silent --show-error --location http://h/x"),\n',
    '            ("1314-url-curl-exact-long-value-after-cd", f"cd {out_cwd} && curl --silent --header=A:b --output {ws}/granted/out.txt http://h/x"),\n',
    '            ("1314-url-httpie-exact-long-after-cd", f"cd {out_cwd} && http --body --follow http://h/x"),\n',
    '            ("1314-url-curl-output-to-granted-after-cd", f"cd {out_cwd} && curl -sS -o {ws}/granted/out.txt http://h/x"),\n',
    '            ("1314-url-httpie-stdout-after-cd", f"cd {out_cwd} && http -b http://h/x"),\n',
    '            ("1314-url-httpie-output-to-granted-after-cd", f"cd {out_cwd} && http -o {ws}/granted/out.txt http://h/x"),\n',
]
for row in WITHDRAWN:
    sub1(row, "")
sub1('''            # In the `cd O &&` shape, where main judges the URL as a path under O (Codex asked
            # to keep real stdout and granted-destination controls for what stays exempted).
''', '')
sub1('''        # `<it>/<word>` is not): a URL after a directory change, a relative path after a leading
        # `cd /abs &&`, and a jq program.''', '''        # `<it>/<word>` is not): a relative path after a leading `cd /abs &&`, and a jq program.''')

# The withdrawn rows are kept as must-refuse ("as on main"): a later URL-exemption patch flips
# them on purpose, and Codex's two findings on c5e8c860 guard it when it does.
sub1('''        # Codex HOLD on 19952a05 (P1 b): `cat` and the shell do not read a `file:` URL. A word''',
'''        # Codex HOLD on c5e8c860 (the seventh on the network-URL exemption): `-w '%output{f}…'`
        # writes `f` (curl >= 8.3), and `-o 'out#1'` with a URL glob writes `out1`, `out2`, never
        # the granted literal `out#1`. The exemption is withdrawn from #1314 (its own issue), so a
        # URL operand after `cd O &&` is judged as a path under O, as on main. These rows, and the
        # former must-allow rows, are refused; a later URL patch flips the latter on purpose.
        tmpl_scopes = cwd_exact + (f"path:{out_cwd}/out#1",)
        for name, cmd in (
            ("1314-control-curl-write-out-output", f"cd {out_cwd} && curl -q -sS --write-out '%output{{fresh.txt}}marker' http://h/fresh.txt"),
            ("1314-control-curl-w-output", f"cd {out_cwd} && curl -q -sS -w '%output{{fresh.txt}}marker' http://h/fresh.txt"),
            ("1314-control-curl-w-attached-output", f"cd {out_cwd} && curl -q -sS -w%output{{fresh.txt}}marker http://h/fresh.txt"),
            ("1314-control-curl-output-template-glob", f"cd {out_cwd} && curl -q -sS -o 'out#1' 'http://h/[1-2]'"),
            ("1314-control-curl-output-long-template-glob", f"cd {out_cwd} && curl -q -sS --output 'out#1' 'http://h/[1-2]'"),
''' + "".join(r.replace('("1314-url-', '("1314-url-withdrawn-') for r in WITHDRAWN) + '''        ):
            r = fx.reach(cmd, scopes=tmpl_scopes, cwd=out_cwd)
            check(f"deny-outside-cwd:{name}", r[0] is False, f"{cmd!r} -> {r}")
        # Codex HOLD on 19952a05 (P1 b): `cat` and the shell do not read a `file:` URL. A word''')
p.write_text(s)
print("ok")
