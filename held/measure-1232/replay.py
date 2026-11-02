"""Refusal-rate replay for #1232 (reference; run from anywhere).

    HESTIA_WORKSPACE=<workspace> MEASURE_CORES='{"main": "<core.py>", "lit": "<core.py>"}' \
        python3 replay.py grants-proposed.txt results.jsonl

Every repo in the workspace counts as granted (only the OUTSIDE effect is measured), each seat keeps
its home marker, and each command is judged by every core with and without the grant file. Rows:
seat, timestamp, and one verdict class per core (allow | path | request | incomplete | error).
`main` is the baseline the delta is taken against (aggregate.py)."""
import importlib.util
import json
import multiprocessing as mp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORES = json.loads(os.environ["MEASURE_CORES"])
WS = os.environ["HESTIA_WORKSPACE"]
MARKER = {"claude-code": "~/.claude", "codex": "~/.codex", "kimi-code": "~/.kimi-code"}
G = {}


def init():
    for n, p in CORES.items():
        spec = importlib.util.spec_from_file_location(f"core_{n}", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"core_{n}"] = mod
        spec.loader.exec_module(mod)
        G[n] = mod


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
            try:
                try:
                    res = mod.command_scope_reach(cmd, scopes, WS, cwd, home_markers=(MARKER[seat],))
                except TypeError:          # a core without home markers (main before #1232)
                    res = mod.command_scope_reach(cmd, scopes, WS, cwd)
                out[n + tag] = klass(*res)
            except Exception as e:  # noqa: BLE001
                out[n + tag] = "error:" + type(e).__name__
    return out


def main():
    sys.path.insert(0, HERE)
    import corpus
    repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
    with open(sys.argv[1]) as fh:
        grants = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    seen, jobs = set(), []
    for src in (corpus.claude_records, corpus.codex_records, corpus.kimi_records):
        for r in src():
            key = (r["seat"], r["session"], r["ts"], r["cmd"])
            if key not in seen:
                seen.add(key)
                jobs.append((r["seat"], r["ts"], r["cwd"] or WS, r["cmd"], repos, grants))
    print(f"corpus: {len(jobs)} commands", flush=True)
    with mp.Pool(int(os.environ.get("REPLAY_WORKERS", "2")), initializer=init) as pool, \
            open(sys.argv[2], "w") as fh:
        for row in pool.imap(judge, jobs, chunksize=64):
            fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
