import pathlib
p = pathlib.Path("/tmp/s1314e/battery_rev.py")
s = p.read_text()
def sub1(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)
sub1('''            ("1314-control-https-download-cluster", f"cd {out_cwd} && https -bd https://h/fresh.txt", f"{ws}/granted"),
''', '''            ("1314-control-https-download-cluster", f"cd {out_cwd} && https -bd https://h/fresh.txt", f"{ws}/granted"),
            # Codex HOLD on 68e951fc: an output option in a VALUE position is the value. wget
            # sends `-O-` / `--spider` as the user agent and saves `fresh.txt` in the cwd.
            ("1314-control-wget-U-eats-stdout", f"cd {out_cwd} && wget -q -U -O- http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-user-agent-eats-spider", f"cd {out_cwd} && wget -q --user-agent --spider http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-dashdash-value-hides-recursion", f"cd {out_cwd} && wget -O- -U -- -r http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-httpie-session-eats-output", f"cd {out_cwd} && http --download --session -o http://h/fresh.txt", f"{ws}/granted"),
''')
sub1('''            ("1314-url-curl-output-after-url", f"curl -sS http://h/x -o {ws}/granted/out.txt"),
''', '''            ("1314-url-curl-output-after-url", f"curl -sS http://h/x -o {ws}/granted/out.txt"),
            # Codex HOLD on 68e951fc: the same options, after a value that IS consumed.
            ("1314-url-wget-stdout-after-agent", "wget -q -U agent -O- http://h/x"),
            ("1314-url-wget-spider-after-agent", "wget -q --user-agent=agent --spider http://h/x"),
            ("1314-url-httpie-output-after-session", f"http --download --session s -o {ws}/granted/out.txt http://h/x"),
''')
p.write_text(s)
print("ok")
