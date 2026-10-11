#!/usr/bin/env python3
"""Mine shell commands (claude-code Bash, codex exec_command, kimi Bash) in a 14-day window and
classify absolute path tokens inside/outside the seat workspace. READ-ONLY over the logs."""
import glob, json, os, re, shlex, sys, collections, datetime

HOME = os.getenv("HOME") or "/home/dp"
WS = "/home/dp/ai-workspace"
OUT = os.path.dirname(os.path.abspath(__file__))
T0 = datetime.datetime(2026, 9, 20, tzinfo=datetime.timezone.utc)
T0_EPOCH = T0.timestamp()
TOPDIRS = set(os.listdir("/"))
HOME_MARKER = {"claude-code": HOME + "/.claude", "codex": HOME + "/.codex", "kimi-code": HOME + "/.kimi-code"}
TEMP_ROOTS = ("/tmp", "/var/tmp")


def parse_ts(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return s / 1000.0 if s > 1e11 else float(s)
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------- sources
def claude_records():
    files = glob.glob(HOME + "/.claude/projects/*/*.jsonl") + glob.glob(HOME + "/.claude/projects/*/*/subagents/*.jsonl")
    for f in files:
        if os.path.getmtime(f) < T0_EPOCH:
            continue
        proj = f.split("/.claude/projects/")[1].split("/")[0]
        sub = "/subagents/" in f
        try:
            fh = open(f, errors="replace")
        except Exception:
            continue
        for line in fh:
            if '"tool_use"' not in line or '"Bash"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = parse_ts(d.get("timestamp"))
            if ts is None or ts < T0_EPOCH:
                continue
            msg = d.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmd = (c.get("input") or {}).get("command")
                    if isinstance(cmd, str):
                        yield dict(seat="claude-code", session=d.get("sessionId") or os.path.basename(f)[:36],
                                   ts=ts, cwd=d.get("cwd") or "", cmd=cmd, proj=proj, sub=sub)


JS_CMD = re.compile(r"""exec_command\(\s*\{\s*"?cmd"?\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)(.*?)\}\s*\)""", re.S)
JS_WD = re.compile(r""""?workdir"?\s*:\s*("(?:[^"\\]|\\.)*")""")


def js_str(lit):
    q = lit[0]
    body = lit[1:-1]
    if q == '"':
        try:
            return json.loads(lit)
        except Exception:
            return body
    try:
        return json.loads('"' + body.replace('"', '\\"').replace("\\'", "'") + '"')
    except Exception:
        return body


def codex_records():
    for f in glob.glob(HOME + "/.codex/sessions/**/*.jsonl", recursive=True):
        if os.path.getmtime(f) < T0_EPOCH:
            continue
        sess = os.path.basename(f)[-42:-6]
        cwd0 = ""
        for line in open(f, errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            p = d.get("payload") or {}
            if not isinstance(p, dict):
                continue
            if d.get("type") in ("session_meta", "turn_context") and p.get("cwd"):
                cwd0 = p.get("cwd")
            ts = parse_ts(d.get("timestamp"))
            if ts is None or ts < T0_EPOCH:
                continue
            t = p.get("type")
            if t == "custom_tool_call":
                inp = p.get("input") or ""
                for m in JS_CMD.finditer(inp):
                    wd = JS_WD.search(m.group(2) or "")
                    yield dict(seat="codex", session=sess, ts=ts, cwd=(js_str(wd.group(1)) if wd else cwd0),
                               cmd=js_str(m.group(1)), proj="codex", sub=False)
            elif t == "function_call" and p.get("name") in ("exec_command", "shell", "local_shell"):
                try:
                    a = json.loads(p.get("arguments") or "{}")
                except Exception:
                    continue
                cmd = a.get("cmd") or a.get("command")
                if isinstance(cmd, list):
                    cmd = " ".join(cmd[2:]) if cmd[:2] in (["bash", "-lc"], ["bash", "-c"]) else " ".join(cmd)
                if isinstance(cmd, str):
                    yield dict(seat="codex", session=sess, ts=ts, cwd=a.get("workdir") or cwd0, cmd=cmd, proj="codex", sub=False)
            elif t == "local_shell_call":
                cmd = ((p.get("action") or {}).get("command")) or []
                yield dict(seat="codex", session=sess, ts=ts, cwd=cwd0, cmd=" ".join(cmd), proj="codex", sub=False)


def kimi_records():
    for f in glob.glob(HOME + "/.kimi-code/sessions/*/*/agents/*/wire.jsonl"):
        if os.path.getmtime(f) < T0_EPOCH:
            continue
        sdir = f.split("/agents/")[0]
        sess = os.path.basename(sdir)
        cwd = ""
        try:
            cwd = json.load(open(sdir + "/state.json")).get("cwd", "")
        except Exception:
            pass
        for line in open(f, errors="replace"):
            if '"tool.call"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ev = d.get("event") or {}
            if ev.get("type") != "tool.call" or ev.get("name") not in ("Bash", "Shell", "shell"):
                continue
            ts = parse_ts(d.get("time"))
            if ts is None or ts < T0_EPOCH:
                continue
            cmd = (ev.get("args") or {}).get("command")
            if isinstance(cmd, str):
                yield dict(seat="kimi-code", session=sess, ts=ts, cwd=cwd, cmd=cmd,
                           proj=os.path.basename(os.path.dirname(sdir)), sub=f.split("/agents/")[1].split("/")[0] != "main")


# ---------------------------------------------------------------- extraction
URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
PATHRE = re.compile(r"""(?:(?<=^)|(?<=[\s='"(:,\[{<>|;&`]))((?:\$\{HOME\}|\$HOME|~)?/[A-Za-z0-9._@%+\-/~*{},]*)""")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n(.*?)\n\s*\2\s*(?:\n|$)", re.S)
WRITE_VERBS_DEST = {"cp", "mv", "install", "rsync", "ln", "scp"}
WRITE_VERBS_ALL = {"mkdir", "rm", "rmdir", "touch", "truncate", "chmod", "chown", "shred", "unlink"}


def norm(tok):
    t = tok
    for pre in ("${HOME}", "$HOME", "~"):
        if t.startswith(pre + "/") or t == pre:
            t = HOME + t[len(pre):]
            break
    t = t.rstrip(",:;")
    if not t.startswith("/"):
        return None
    if t.startswith("//"):
        return None
    # stop at glob/brace for normalisation, keep prefix
    t2 = re.split(r"[*{]", t, 1)[0]
    t2 = os.path.normpath(t2) if t2 not in ("", "/") else "/"
    if t2 == "/":
        return "/" if tok.strip() in ("/", "/*") else None
    first = t2.split("/")[1]
    if first not in TOPDIRS:
        return None
    return t2


def write_targets(cmd):
    """Cheap write detection: redirection targets, tee, cp/mv dest, mkdir/rm/touch args, sed -i."""
    w = set()
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except Exception:
        toks = cmd.split()
    seg = []
    segs = []
    for i, t in enumerate(toks):
        if t in (">", ">>", "&>", ">|", "2>", "2>>") or (t.endswith(">") and t[:-1].isdigit()):
            if i + 1 < len(toks):
                w.add(toks[i + 1])
            continue
        if t in (";", "&&", "||", "|", "&", "(", ")", "\n"):
            segs.append(seg); seg = []
            continue
        seg.append(t)
    segs.append(seg)
    for s in segs:
        if not s:
            continue
        j = 0
        while j < len(s) and (("=" in s[j] and not s[j].startswith(("/", "-"))) or s[j] in ("sudo", "env", "nohup", "timeout", "command")):
            j += 1
        if j >= len(s):
            continue
        verb = os.path.basename(s[j]); args = [a for a in s[j + 1:] if not a.startswith("-")]
        if verb in WRITE_VERBS_DEST and args:
            w.add(args[-1])
        elif verb in WRITE_VERBS_ALL:
            w.update(args)
        elif verb == "tee":
            w.update(args)
        elif verb == "sed" and any(a.startswith("-i") for a in s[j + 1:]):
            w.update(args[1:])
        elif verb == "dd":
            w.update(a[3:] for a in s[j + 1:] if a.startswith("of="))
    out = set()
    for t in w:
        n = norm(t)
        if n:
            out.add(n)
    return out


def extract(cmd):
    """Return dict path -> {'heredoc_only':bool}; text-level scan (the gate's own model is a text scan)."""
    c = URL.sub(" ", cmd)
    bodies = " ".join(m.group(3) for m in HEREDOC.finditer(c))
    stripped = HEREDOC.sub("<<HD\n", c)
    found = {}
    for m in PATHRE.finditer(stripped):
        n = norm(m.group(1))
        if n:
            found[n] = False
    for m in PATHRE.finditer(bodies):
        n = norm(m.group(1))
        if n and n not in found:
            found[n] = True
    return found, write_targets(stripped)


def inside(p, ws=WS):
    return p == ws or p.startswith(ws + "/")


def root_of(p):
    h = HOME
    if p == "/":
        return "/ (filesystem root)"
    if p == "/dev/null":
        return "/dev/null"
    if re.match(r"^/dev/(stdout|stderr|stdin|fd|tty)", p):
        return "/dev/std*|fd|tty"
    if p.startswith("/dev/"):
        return "/dev/** (other)"
    if p.startswith("/tmp/claude-1000"):
        return "/tmp/claude-1000/** (agent scratchpads)"
    if p == "/tmp" or p.startswith("/tmp/"):
        return "/tmp/** (other)"
    if p.startswith("/var/tmp"):
        return "/var/tmp/**"
    for r in ("/proc", "/sys", "/etc", "/usr", "/run", "/var", "/opt", "/snap", "/root", "/boot", "/srv", "/media"):
        if p == r or p.startswith(r + "/"):
            return r + "/**"
    for r in ("/bin", "/sbin", "/lib", "/lib64"):
        if p == r or p.startswith(r + "/"):
            return "/bin,/sbin,/lib**"
    if p.startswith("/mnt/wsl"):
        return "/mnt/wsl/**"
    if p.startswith("/mnt/c/Users/"):
        parts = p.split("/")
        if len(parts) >= 6 and parts[5] in ("AppData",):
            return "/mnt/c/Users/*/AppData/**"
        return "/mnt/c/Users/*/** (non-AppData)"
    if p.startswith("/mnt/"):
        parts = p.split("/")
        return "/".join(parts[:5]) + "/**" if len(parts) > 4 else p
    if p.startswith(h + "/"):
        rest = p[len(h) + 1:].split("/")
        if rest[0] == ".local" and len(rest) > 2 and rest[1] in ("state", "share", "bin", "lib"):
            if rest[1] == "state" and rest[2].startswith("hestia"):
                return "~/.local/state/" + rest[2] + "/**"
            return "~/.local/" + rest[1] + "/" + rest[2] + "/**"
        if rest[0] == ".local":
            return "~/.local/" + (rest[1] if len(rest) > 1 else "") + "/**"
        if rest[0] in (".config", ".cache") and len(rest) > 1:
            return "~/" + rest[0] + "/" + rest[1] + "/**"
        if rest[0].startswith("."):
            return "~/" + rest[0] + ("/**" if len(rest) > 1 or os.path.isdir(p) else "")
        return "~/" + rest[0] + ("/**" if len(rest) > 1 else "")
    if p == h:
        return "~ (home dir itself)"
    if p.startswith("/home/"):
        return "/home/<other>/**"
    return "/" + p.split("/")[1] + "/**"


def exempt_now(p, seat):
    """Already in scope under today's Read rule (path_in_scope): own home marker or temp root."""
    hm = HOME_MARKER.get(seat)
    if hm and (p == hm or p.startswith(hm + "/")):
        return True
    return any(p == r or p.startswith(r + "/") for r in TEMP_ROOTS)


def private_example(p):
    if p.startswith("/mnt/c/Users/"):
        parts = p.split("/")
        return "/".join(parts[:6]) + "/**" if len(parts) > 5 else "/".join(parts[:5]) + "/**"
    return p


# ---------------------------------------------------------------- main
def main():
    per_seat = collections.Counter()
    per_seat_out = collections.Counter()
    per_seat_out_nonexempt = collections.Counter()
    sessions_cwd = collections.Counter()
    roots = collections.defaultdict(lambda: dict(cmds=set(), paths=collections.Counter(), seats=collections.Counter(),
                                                 writes=0, reads=0, heredoc_only=0, exempt=0, sessions=set()))
    appdata = collections.defaultdict(lambda: dict(n=0, date=None, cwd=None, seat=None))
    raw = open(os.path.join(OUT, "raw-outside-paths.jsonl"), "w")
    seen = set()
    n = 0
    for src in (claude_records, codex_records, kimi_records):
        for r in src():
            key = (r["seat"], r["session"], r["ts"], r["cmd"])
            if key in seen:
                continue
            seen.add(key)
            n += 1
            seat = r["seat"]
            per_seat[seat] += 1
            cwd = r["cwd"] or ""
            cwd_class = "workspace" if inside(cwd) else ("/mnt/c/exe/projects/**" if cwd.startswith("/mnt/c/exe/projects") else
                                                        ("~/.local/state/hub/mesh/threads/**" if "/.local/state/hub/mesh/threads" in cwd else (cwd or "?")))
            sessions_cwd[(seat, cwd_class)] += 1
            found, writes = extract(r["cmd"])
            outside = [p for p in found if not inside(p)]
            if not outside:
                continue
            per_seat_out[seat] += 1
            cid = len(seen)
            nonex = False
            for p in outside:
                rt = root_of(p)
                R = roots[rt]
                R["cmds"].add(cid); R["paths"][p] += 1; R["seats"][seat] += 1; R["sessions"].add(r["session"])
                if p in writes:
                    R["writes"] += 1
                else:
                    R["reads"] += 1
                if found[p]:
                    R["heredoc_only"] += 1
                ex = exempt_now(p, seat)
                if ex:
                    R["exempt"] += 1
                elif rt not in ("/dev/null", "/dev/std*|fd|tty"):
                    nonex = True
                if rt == "/mnt/c/Users/*/AppData/**":
                    a = appdata[(seat, r["session"])]
                    a["n"] += 1; a["seat"] = seat; a["cwd"] = cwd
                    dte = datetime.datetime.utcfromtimestamp(r["ts"]).strftime("%Y-%m-%d")
                    a["date"] = min(a["date"] or dte, dte)
            if nonex:
                per_seat_out_nonexempt[seat] += 1
            raw.write(json.dumps(dict(seat=seat, session=r["session"], ts=datetime.datetime.utcfromtimestamp(r["ts"]).isoformat(),
                                      cwd=cwd, proj=r["proj"],
                                      outside=[dict(path=private_example(p), root=root_of(p), write=p in writes,
                                                    heredoc_only=found[p], exempt_now=exempt_now(p, seat)) for p in outside])) + "\n")
    raw.close()
    res = dict(total_cmds=n, per_seat=per_seat, per_seat_with_outside=per_seat_out,
               per_seat_with_nonexempt_outside=per_seat_out_nonexempt,
               cwd_classes={f"{a}|{b}": v for (a, b), v in sessions_cwd.items()},
               roots={k: dict(commands=len(v["cmds"]), distinct_paths=len(v["paths"]), seats=dict(v["seats"]),
                              sessions=len(v["sessions"]), reads=v["reads"], writes=v["writes"],
                              heredoc_only=v["heredoc_only"], exempt_under_read_rule=v["exempt"],
                              top=[(private_example(p), c) for p, c in v["paths"].most_common(8)])
                      for k, v in sorted(roots.items(), key=lambda kv: -len(kv[1]["cmds"]))},
               appdata=[dict(session=k[1], **v) for k, v in appdata.items()])
    json.dump(res, open(os.path.join(OUT, "summary.json"), "w"), indent=1, default=list)
    print(json.dumps({k: res[k] for k in ("total_cmds", "per_seat", "per_seat_with_outside", "per_seat_with_nonexempt_outside", "cwd_classes")}, indent=1))
    print("roots:", len(res["roots"]))
    for k, v in res["roots"].items():
        print(f"{v['commands']:6d} {v['distinct_paths']:5d} R{v['reads']} W{v['writes']} hd{v['heredoc_only']} ex{v['exempt_under_read_rule']} {k} {v['seats']} {v['top'][:5]}")
    print("appdata:", res["appdata"])


if __name__ == "__main__":
    main()
