import pathlib
p = pathlib.Path("/tmp/s1314e/battery_rev.py")
s = p.read_text()
def sub1(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)
sub1('''            ("1314-control-xh-output-scheme-word", f"cd {out_cwd} && xh -o http://newdir/f http://h/x", f"{ws}/granted"),
''', '''            ("1314-control-xh-output-scheme-word", f"cd {out_cwd} && xh -o http://newdir/f http://h/x", f"{ws}/granted"),
            # Codex HOLD on f46bc32b: a download mode writes a file whose NAME the client derives
            # from the URL (or the response), in the cwd. No word names it, so the URL operand is
            # the only trace of that write and cannot be exempted. curl `-O` may follow the URL.
            ("1314-control-curl-remote-name", f"cd {out_cwd} && curl -sSO http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-name-all", f"cd {out_cwd} && curl --remote-name-all http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-header-name", f"cd {out_cwd} && curl -sSOJ http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-remote-name-after-url", f"cd {out_cwd} && curl -sS http://h/fresh.txt -O", f"{ws}/granted"),
            ("1314-control-curl-remote-name-long", f"cd {out_cwd} && curl --remote-name http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-output-dir", f"cd {out_cwd} && curl --output-dir . -o f http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curl-expansion-may-be-O", f"cd {out_cwd} && curl $OPTS http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-curlie-remote-name", f"cd {out_cwd} && curlie -O http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-default", f"cd {out_cwd} && wget -q http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-bare", f"cd {out_cwd} && wget http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-recursive-stdout", f"cd {out_cwd} && wget -r -O- http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-background-log", f"cd {out_cwd} && wget -b -qO- http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-wget-execute", f"cd {out_cwd} && wget -O- -e output_document=x http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-httpie-download", f"cd {out_cwd} && http --download http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-xh-download-short", f"cd {out_cwd} && xh -d http://h/fresh.txt", f"{ws}/granted"),
            ("1314-control-https-download-cluster", f"cd {out_cwd} && https -bd https://h/fresh.txt", f"{ws}/granted"),
''')
sub1('''            ("1314-url-xh-after-flags", "xh -b -F https://h/x"),
''', '''            ("1314-url-xh-after-flags", "xh -b -F https://h/x"),
            # Codex HOLD on f46bc32b: the must-allow side of the download-mode rows. stdout, a
            # named granted destination, and wget's `--spider` (which saves nothing).
            ("1314-url-curl-stdout", "curl -sS http://h/x"),
            ("1314-url-wget-stdout-separate", "wget -q -O - http://h/x"),
            ("1314-url-wget-output-long", "wget --output-document=- http://h/x"),
            ("1314-url-wget-output-to-granted", f"wget -q -O {ws}/granted/out.txt http://h/x"),
            ("1314-url-wget-spider", "wget --spider http://h/x"),
            ("1314-url-httpie-download-to-granted", f"http --download -o {ws}/granted/out.txt http://h/x"),
            ("1314-url-curl-output-after-url", f"curl -sS http://h/x -o {ws}/granted/out.txt"),
''')
p.write_text(s)
print("ok")
