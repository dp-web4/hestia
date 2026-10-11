"""What the narrowed core's once-only requests are made of (re-judges only those commands)."""
import collections
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mine  # noqa: E402

spec = importlib.util.spec_from_file_location("core_after", os.path.join(SP, "stage1232", "narrow", "gcore.py"))
G = importlib.util.module_from_spec(spec)
sys.modules["core_after"] = G
spec.loader.exec_module(G)
WS = "/home/dp/ai-workspace"
MARKER = {"claude-code": "~/.claude", "codex": "~/.codex", "kimi-code": "~/.kimi-code"}
repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
with open(os.path.join(HERE, "grants-proposed.txt")) as fh:
    grants = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]

results = [json.loads(ln) for ln in open(os.path.join(HERE, "results.jsonl"))]
want = {(r["seat"], r["ts"]) for r in results if r.get("main+g") == "allow" and r.get("after+g") == "request"}

classes = collections.Counter()
loopy = collections.Counter()
seen = set()
for src in (mine.claude_records, mine.codex_records, mine.kimi_records):
    for r in src():
        key = (r["seat"], r["session"], r["ts"], r["cmd"])
        if key in seen or (r["seat"], r["ts"]) not in want:
            continue
        seen.add(key)
        ok, tok, res = G.command_scope_reach(r["cmd"], repos + grants, WS, r["cwd"] or WS,
                                             home_markers=(MARKER[r["seat"]],))
        if ok:
            continue
        why = str(tok)[len(G._UNMODELLED_PREFIX):-1] if str(tok).startswith(G._UNMODELLED_PREFIX) else str(tok)
        m = re.match(r"the variable \$(\w+)", why)
        if m:
            name = m.group(1)
            cmd = r["cmd"]
            if re.search(rf"\bfor\s+{name}\s+in\b", cmd):
                cls = "variable: a for-loop variable"
            elif re.search(rf"\bread\b[^;|&\n]*\b{name}\b", cmd):
                cls = "variable: a `read` variable (stdin)"
            elif re.search(rf"(?:^|[\s;&|(]){name}=", cmd):
                vals = re.findall(rf"(?:^|[\s;&|(]){name}=(\S*)", cmd)
                literal = all(("$" not in v and "`" not in v) for v in vals)
                sub = bool(re.search(rf"\(\s*[^)]*\b{name}=", cmd))
                cls = ("variable: assigned a LITERAL in the same command"
                       + (" (one assignment)" if len(vals) == 1 else " (several)")
                       if literal else "variable: assigned an EXPANSION in the same command")
            else:
                cls = "variable: from the environment / unknown"
        elif why.startswith("the parameter expansion"):
            cls = "parameter expansion ${…}"
        elif why.startswith("a command substitution") or why.startswith("a backtick"):
            cls = "command substitution used as a path"
        elif why.startswith("the positional parameter"):
            cls = "positional parameter"
        else:
            cls = re.sub(r"`[^`]*`|'[^']*'|\$\w+", "…", why)[:60]
        classes[cls] += 1
tot = sum(classes.values())
print(f"once-only requests after the proposed grants: {tot}")
for k, v in classes.most_common(25):
    print(f"  {v:6d}  {100.0 * v / max(1, tot):5.1f}%  {k}")
