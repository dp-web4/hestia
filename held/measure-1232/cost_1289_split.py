"""#1289 HOLD 21675 revision cost (743dad83): main vs e2705d13 (scoped) vs 743dad83 (split), claude-code's
OWN records only. Writes every row whose verdict differs between scoped and split to <delta.txt>.

    HESTIA_WORKSPACE=<ws> MEASURE_CORES='{"main": "<core>", "scoped": "<core>", "split": "<core>"}' \
        python3 cost_1289_split.py <results.jsonl> <delta.txt>"""
import collections, json, multiprocessing as mp, os, pathlib, sys
D = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import corpus, replay
def main():
    WS = os.environ.get("HESTIA_WORKSPACE")
    if not WS:
        raise SystemExit("HESTIA_WORKSPACE must name the workspace to measure")
    repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
    grants = [l.strip() for l in open(D / "grants-proposed.txt") if l.strip() and not l.startswith("#")]
    seen, jobs = set(), []
    for r in corpus.claude_records():
        k = (r["seat"], r["session"], r["ts"], r["cmd"])
        if k not in seen:
            seen.add(k); jobs.append((r["seat"], r["ts"], r["cwd"] or WS, r["cmd"], repos, grants))
    print("claude-code commands:", len(jobs), flush=True)
    out, delta = sys.argv[1], sys.argv[2]
    rows = []
    with mp.Pool(2, initializer=replay.init) as pool, open(out, "w") as fh:
        for row in pool.imap(replay.judge, jobs, chunksize=64):
            fh.write(json.dumps(row) + "\n"); rows.append(row); row["cmd"] = jobs[len(rows) - 1][3]
    for tag in ("", "+g"):
        for a, b in (("main", "scoped"), ("main", "split"), ("scoped", "split")):
            c = collections.Counter((r[a + tag], r[b + tag]) for r in rows if r[a + tag] != r[b + tag])
            print(f"grants={'proposed' if tag else 'none'} {a}->{b}:", dict(c))
    with open(delta, "w") as fh:
        for r in rows:
            if r["scoped"] != r["split"]:
                fh.write(f"{r['scoped']}->{r['split']}\t{r['cmd'][:400]!r}\n")
if __name__ == "__main__":
    main()
