import re, subprocess, sys, pathlib
REPO = "/home/dp/ai-workspace/hestia"
BASE = "2d79644f"
OUT = pathlib.Path("/tmp/s1314e")

def split(patch):
    files = {}
    cur = None
    for ln in patch.splitlines(keepends=True):
        if ln.startswith("diff --git "):
            cur = ln.split()[2][2:]
            files[cur] = []
        elif cur is not None:
            files[cur].append(ln)
    return files

def apply(src, lines):
    s = src.splitlines(keepends=True)
    out = []; pos = 0; i = 0
    while i < len(lines):
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
        if not m:
            i += 1; continue
        start = int(m.group(1)) - 1
        if m.group(2) == "0": start += 1
        out += s[pos:start]; pos = start; i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            l = lines[i]
            if l.startswith("\\"): i += 1; continue
            t, body = l[0], l[1:]
            if t == " ":
                assert s[pos] == body, (pos, s[pos], body); out.append(body); pos += 1
            elif t == "-":
                assert s[pos] == body, (pos, s[pos], body); pos += 1
            elif t == "+":
                out.append(body)
            i += 1
    out += s[pos:]
    return "".join(out)

