"""The shell-command corpus #1232's measurement replays: every claude-code Bash call, codex
exec_command and kimi Bash call since 2026-09-20, read from each harness's own session logs under
the invoking user's home. READ-ONLY. (Extracted from the 2026-10-05 measurement's reader.)"""
import datetime
import glob
import json
import os
import re

HOME = os.path.expanduser("~")
T0 = datetime.datetime(2026, 9, 20, tzinfo=datetime.timezone.utc)
T0_EPOCH = T0.timestamp()


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
