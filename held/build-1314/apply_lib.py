import re

def split(patch):
    files = {}
    cur = None
    for ln in patch.splitlines(keepends=True):
        if ln.startswith("diff --git "):
            parts = ln.split()
            if (len(parts) != 4 or not parts[2].startswith("a/")
                    or not parts[3].startswith("b/") or parts[2][2:] != parts[3][2:]):
                raise ValueError("unsupported patch path or rename")
            cur = parts[2][2:]
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
            if lines[i].startswith("@@"): raise ValueError("malformed hunk header")
            i += 1; continue
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        new_count = int(m.group(4)) if m.group(4) is not None else 1
        start = int(m.group(1)) - 1
        if old_count == 0: start += 1
        new_start = int(m.group(3)) - 1 + (new_count == 0)
        if start < pos or start > len(s): raise ValueError(f"invalid hunk position: {start}")
        out += s[pos:start]
        if new_start != len(out): raise ValueError(f"invalid new hunk position: {new_start}")
        pos = start; i += 1; old_used = 0; new_used = 0
        while i < len(lines) and not lines[i].startswith("@@"):
            l = lines[i]
            if l.startswith("\\"): raise ValueError("no-newline patch markers are unsupported")
            t, body = l[0], l[1:]
            if t == " ":
                if pos >= len(s) or s[pos] != body: raise ValueError(f"patch context mismatch at {pos}")
                out.append(body); pos += 1; old_used += 1; new_used += 1
            elif t == "-":
                if pos >= len(s) or s[pos] != body: raise ValueError(f"patch removal mismatch at {pos}")
                pos += 1; old_used += 1
            elif t == "+":
                out.append(body); new_used += 1
            else:
                raise ValueError(f"unexpected patch line at {pos}")
            i += 1
        if (old_used, new_used) != (old_count, new_count):
            raise ValueError("hunk counts do not match header")
    out += s[pos:]
    return "".join(out)

