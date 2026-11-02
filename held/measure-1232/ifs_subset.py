"""The 20972 repair changes only `ifs_touched`, and only by adding "IFS appears in the command text"
to the 20554 token test. So only commands containing IFS (after backslash-newline removal) can change
verdict. Replay exactly those through both cores, with and without the proposed grants.
Run with HESTIA_WORKSPACE and MEASURE_CORES (two cores: "f4a5" and "ifs") exported, as for replay.py."""
import collections, json, os, sys
M = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, M)
import replay, corpus
WS = os.getenv("HESTIA_WORKSPACE")
repos = [d for d in os.listdir(WS) if os.path.isdir(os.path.join(WS, d)) and not d.startswith(".")]
grants = [l.strip() for l in open(os.path.join(M, "grants-proposed.txt")) if l.strip() and not l.startswith("#")]
seen, total, jobs = set(), 0, []
for src in (corpus.claude_records, corpus.codex_records, corpus.kimi_records):
    for r in src():
        key = (r["seat"], r["session"], r["ts"], r["cmd"])
        if key in seen:
            continue
        seen.add(key); total += 1
        if "IFS" in r["cmd"].replace("\\\n", ""):
            jobs.append((r["seat"], r["ts"], r["cwd"] or WS, r["cmd"], repos, grants))
replay.init()
changed = collections.Counter()
rows = []
for j in jobs:
    out = replay.judge(j)
    rows.append((j[0], j[3][:160], out))
    for tag in ("", "+g"):
        if out["f4a5" + tag] != out["ifs" + tag]:
            changed[(tag or "none", out["f4a5" + tag], out["ifs" + tag], j[0])] += 1
print(f"corpus {total} commands; {len(jobs)} contain IFS")
for k, v in sorted(changed.items()):
    print("changed", k, v)
for seat, c, out in rows:
    if any(out["f4a5" + t] != out["ifs" + t] for t in ("", "+g")):
        print(" ", seat, json.dumps(c), out)
