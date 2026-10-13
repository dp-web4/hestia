"""#1287 revision cost (e2705d13): main vs 78386f56 (narrow) vs e2705d13 (scoped), claude-code's OWN records
only (every verdict 78386f56 changed was claude-code's, so no other seat's home is read).

    HESTIA_WORKSPACE=<ws> MEASURE_CORES='{"main": "<core>", "narrow": "<core>", "scoped": "<core>"}' \
        python3 cost_1287_scoped.py <results.jsonl>"""
import collections, json, multiprocessing as mp, os, pathlib, sys
D = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import corpus, replay
def main():
    WS = "/home/dp/ai-workspace"
    repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
    grants = [l.strip() for l in open(D / "grants-proposed.txt") if l.strip() and not l.startswith("#")]
    seen, jobs = set(), []
    for r in corpus.claude_records():
        k = (r["seat"], r["session"], r["ts"], r["cmd"])
        if k not in seen:
            seen.add(k); jobs.append((r["seat"], r["ts"], r["cwd"] or WS, r["cmd"], repos, grants))
    print("claude-code commands:", len(jobs), flush=True)
    out = sys.argv[1]
    rows = []
    with mp.Pool(2, initializer=replay.init) as pool, open(out, "w") as fh:
        for row in pool.imap(replay.judge, jobs, chunksize=64):
            fh.write(json.dumps(row) + "\n"); rows.append(row)
    for tag in ("", "+g"):
        for a, b in (("main", "narrow"), ("main", "scoped"), ("narrow", "scoped")):
            c = collections.Counter((r[a + tag], r[b + tag]) for r in rows if r[a + tag] != r[b + tag])
            print(f"grants={'proposed' if tag else 'none'} {a}->{b}:", dict(c))
if __name__ == "__main__":
    main()
