import pathlib
p = pathlib.Path("/tmp/s1314e/battery_rev.py")
s = p.read_text()

def sub1(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)

# Codex HOLD on 570f6e82: wget and `http --download` are no longer exempted, so their must-allow
# rows leave the allow list and are refused as on main (the URL is judged as the relative path it
# also spells, under an exactly granted cwd).
sub1('''            ("1314-url-wget-attached-output", "wget -qO- http://h/x"),
''', '')
sub1('''            # Codex HOLD on f46bc32b: the must-allow side of the download-mode rows. stdout, a
            # named granted destination, and wget's `--spider` (which saves nothing).
            ("1314-url-curl-stdout", "curl -sS http://h/x"),
            ("1314-url-wget-stdout-separate", "wget -q -O - http://h/x"),
            ("1314-url-wget-output-long", "wget --output-document=- http://h/x"),
            ("1314-url-wget-output-to-granted", f"wget -q -O {ws}/granted/out.txt http://h/x"),
            ("1314-url-wget-spider", "wget --spider http://h/x"),
            ("1314-url-httpie-download-to-granted", f"http --download -o {ws}/granted/out.txt http://h/x"),
            ("1314-url-curl-output-after-url", f"curl -sS http://h/x -o {ws}/granted/out.txt"),
            # Codex HOLD on 68e951fc: the same options, after a value that IS consumed.
            ("1314-url-wget-stdout-after-agent", "wget -q -U agent -O- http://h/x"),
            ("1314-url-wget-spider-after-agent", "wget -q --user-agent=agent --spider http://h/x"),
            ("1314-url-httpie-output-after-session", f"http --download --session s -o {ws}/granted/out.txt http://h/x"),
''', '''            # Codex HOLD on f46bc32b: the must-allow side of the download-mode rows. stdout and a
            # named granted destination.
            ("1314-url-curl-stdout", "curl -sS http://h/x"),
            ("1314-url-curl-output-after-url", f"curl -sS http://h/x -o {ws}/granted/out.txt"),
            # In the `cd O &&` shape, where main judges the URL as a path under O (Codex asked
            # to keep real stdout and granted-destination controls for what stays exempted).
            ("1314-url-curl-stdout-after-cd", f"cd {out_cwd} && curl -sS http://h/x"),
            ("1314-url-curl-output-to-granted-after-cd", f"cd {out_cwd} && curl -sS -o {ws}/granted/out.txt http://h/x"),
            ("1314-url-httpie-stdout-after-cd", f"cd {out_cwd} && http -b http://h/x"),
            ("1314-url-httpie-output-to-granted-after-cd", f"cd {out_cwd} && http -o {ws}/granted/out.txt http://h/x"),
''')
sub1('''            ("1314-control-httpie-session-eats-output", f"cd {out_cwd} && http --download --session -o http://h/fresh.txt", f"{ws}/granted"),
''', '''            ("1314-control-httpie-session-eats-output", f"cd {out_cwd} && http --download --session -o http://h/fresh.txt", f"{ws}/granted"),
            # Codex HOLD on 570f6e82: `--no-spider` cancels `--spider`, and wget saves `fresh.txt`
            # (real GNU Wget 1.21.4). wget is no longer a URL client here, so every wget URL is
            # judged as on main, as is any `http --download` even with `-o`. These were must-allow
            # rows on 570f6e82 and earlier (without the `cd`, where no core judges the bare
            # relative word); in Codex's `cd O &&` shape main refuses each of them.
            ("1314-control-wget-spider-then-no-spider", f"cd {out_cwd} && wget --spider --no-spider -q http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-not-url-client-attached-output", f"cd {out_cwd} && wget -qO- http://h/x", f"{ws}/granted"),
            ("1314-control-wget-not-url-client-stdout", f"cd {out_cwd} && wget -q -O - http://h/x", f"{ws}/granted"),
            ("1314-control-wget-not-url-client-output-long", f"cd {out_cwd} && wget --output-document=- http://h/x", f"{ws}/granted"),
            ("1314-control-wget-not-url-client-output-to-granted", f"cd {out_cwd} && wget -q -O {ws}/granted/out.txt http://h/x", f"{ws}/granted"),
            ("1314-control-wget-not-url-client-spider", f"cd {out_cwd} && wget --spider http://h/x", f"{ws}/granted"),
            ("1314-control-httpie-download-named-output", f"cd {out_cwd} && http --download -o {ws}/granted/out.txt http://h/x", f"{ws}/granted"),
            ("1314-control-httpie-download-after-session", f"cd {out_cwd} && http --download --session s -o {ws}/granted/out.txt http://h/x", f"{ws}/granted"),
''')
p.write_text(s)
print("ok")
