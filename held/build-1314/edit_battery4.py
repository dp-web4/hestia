import pathlib
p = pathlib.Path("/tmp/s1314e/battery_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)

# Codex HOLD on f08a274b: curl 8.5.0 accepted `--remote-name-a` and wrote O/fresh.txt. Must-refuse:
# abbreviations and case variants of every implicit-output option, and an unknown long option.
# Must-allow: exact safe long names, with and without a value-taking option.
sub1('''            ("1314-control-curl-remote-name-long", f"cd {out_cwd} && curl --remote-name http://h/fresh.txt", f"{ws}/granted"),
''', '''            ("1314-control-curl-remote-name-long", f"cd {out_cwd} && curl --remote-name http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-name-all-abbrev", f"cd {out_cwd} && curl --remote-name-a -sS http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-name-all-abbrev-q", f"cd {out_cwd} && curl -q --remote-name-al -sS http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-name-uppercase", f"cd {out_cwd} && curl --REMOTE-NAME http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-header-abbrev", f"cd {out_cwd} && curl -O --remote-head http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-output-dir-abbrev", f"cd {out_cwd} && curl --output-d=. -O http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-config-abbrev", f"cd {out_cwd} && curl --conf=cfg http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-unknown-long", f"cd {out_cwd} && curl --some-future-option http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-httpie-download-abbrev", f"cd {out_cwd} && http --down http://h/fresh.txt", f"{ws}/granted"),
''')
sub1('''            ("1314-url-curl-stdout-after-cd", f"cd {out_cwd} && curl -sS http://h/x"),
''', '''            ("1314-url-curl-stdout-after-cd", f"cd {out_cwd} && curl -sS http://h/x"),
            ("1314-url-curl-exact-long-flags-after-cd", f"cd {out_cwd} && curl --silent --show-error --location http://h/x"),
            ("1314-url-curl-exact-long-value-after-cd", f"cd {out_cwd} && curl --silent --header=A:b --output {ws}/granted/out.txt http://h/x"),
            ("1314-url-httpie-exact-long-after-cd", f"cd {out_cwd} && http --body --follow http://h/x"),
''')
p.write_text(s)
print("ok")
