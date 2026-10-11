"""Refusal-rate measurement for #1232's narrowing, over the real shell corpus (read-only).

Methodology carried over from the 2026-10-05 replay (`scopestage/replay.py`): every repo in the
workspace is treated as granted (so only the OUTSIDE-the-workspace effect is measured), each seat
keeps its home marker, and only the DELTA counts — commands main's core allows and the candidate
refuses. `--grants` adds the proposed standing-grant set to every seat.

One pass, four cores per command (each with and without the grants):
  main     — origin/main's core (the baseline the delta is taken against)
  orig     — the 01e68a1c core exactly as reviewed (recovered, base 23ea9324)
  before   — 01e68a1c merged onto main, NOT narrowed (the output models)
  after    — narrowed (dp, 2026-10-10): nothing an expansion produces is modelled

Each verdict is classed: allow | path (a concrete path refused — a scope request a session or
standing grant can answer) | request (the unenumerated/overflow sentinel — a scope request only a
one-time approval can answer) | incomplete (the old cores' plain unmodelled refusal: no request) |
error. Writes results.jsonl (one row per command) for aggregation by window.
"""
import importlib.util
import json
import multiprocessing as mp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
CORES = {
    "main": os.path.join(SP, "stage1232", "theirs", "gcore.py"),
    "orig": os.path.join(SP, "recover", "scopestage", "work", "gcore.py"),
    "before": os.path.join(SP, "stage1232", "prenarrow", "gcore.py"),
    "after": os.path.join(SP, "stage1232", "narrow", "gcore.py"),
}
WS = "/home/dp/ai-workspace"
MARKER = {"claude-code": "~/.claude", "codex": "~/.codex", "kimi-code": "~/.kimi-code"}
G = {}


def load(name, path):
    spec = importlib.util.spec_from_file_location(f"core_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"core_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def init():
    for n, p in CORES.items():
        G[n] = load(n, p)


def klass(ok, tok, resolved):
    if ok:
        return "allow"
    r = str(resolved or "")
    if r.startswith("hestia:unpriceable:"):
        return "request"
    if str(tok or "").startswith("<incomplete") and not r.startswith("/"):
        return "incomplete"
    return "path"


def judge(job):
    seat, ts, cwd, cmd, repos, grants = job
    out = {"seat": seat, "ts": ts}
    for n, mod in G.items():
        for tag, scopes in (("", repos), ("+g", repos + grants)):
            if n == "main" and tag:
                # main is the baseline twice over: the delta with grants is taken against main
                # WITH the same grants, so a grant never counts as the change's relief.
                pass
            try:
                if n == "main":
                    res = mod.command_scope_reach(cmd, scopes, WS, cwd)
                else:
                    res = mod.command_scope_reach(cmd, scopes, WS, cwd, home_markers=(MARKER[seat],))
                out[n + tag] = klass(*res)
            except Exception as e:  # noqa: BLE001
                out[n + tag] = "error:" + type(e).__name__
    return out


def main():
    sys.path.insert(0, HERE)
    import mine
    repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
    with open(os.path.join(HERE, "grants-proposed.txt")) as fh:
        grants = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    seen, jobs = set(), []
    for src in (mine.claude_records, mine.codex_records, mine.kimi_records):
        for r in src():
            key = (r["seat"], r["session"], r["ts"], r["cmd"])
            if key in seen:
                continue
            seen.add(key)
            jobs.append((r["seat"], r["ts"], r["cwd"] or WS, r["cmd"], repos, grants))
    print(f"corpus: {len(jobs)} commands", flush=True)
    workers = int(os.environ.get("REPLAY_WORKERS", "3"))
    with mp.Pool(workers, initializer=init) as pool, \
            open(os.path.join(HERE, "results.jsonl"), "w") as fh:
        for i, row in enumerate(pool.imap(judge, jobs, chunksize=64)):
            fh.write(json.dumps(row) + "\n")
            if i % 5000 == 0:
                print(f"  {i}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
