import re

def split(patch):
    files = {}
    cur = None
    for ln in patch.splitlines(keepends=True):
        if ln.startswith("diff --git "):
            cur = ln.split()[2][2:]
            if cur in files:
                raise ValueError(f"duplicate patch path: {cur}")
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
        if start < pos or start > len(s): raise ValueError(f"invalid hunk position: {start}")
        out += s[pos:start]; pos = start; i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            l = lines[i]
            if l.startswith("\\"): i += 1; continue
            t, body = l[0], l[1:]
            if t == " ":
                if s[pos] != body: raise ValueError(f"patch context mismatch at {pos}")
                out.append(body); pos += 1
            elif t == "-":
                if s[pos] != body: raise ValueError(f"patch removal mismatch at {pos}")
                pos += 1
            elif t == "+":
                out.append(body)
            else:
                raise ValueError(f"unexpected patch line at {pos}")
            i += 1
    out += s[pos:]
    return "".join(out)

