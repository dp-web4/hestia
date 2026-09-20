"""Does the resolver's hole class occur in the wild, or only when someone writes it?

codex's review of v5 (findings/redirect-resolver-v5-review-2026-09-20.md) confirmed ten
CRAFTED commands that go write -> read with the candidate injected. It also recorded that
"the historical transcript census was not rerun for this review". This is that census, and
it asks the question the crafted battery cannot: over every Bash command this fleet has
actually issued, how often does the candidate change a verdict at all, and in which
direction?

Method: dedup every Bash tool_use input in the transcript corpus, classify each one twice
against the SAME closure module (shipped `_bash_write_targets`, then the candidate injected),
and bucket the disagreements. Nothing is executed. The full disagreement set is written out
so every row can be read by hand rather than summarised.

Roots come from HESTIA_TRANSCRIPT_ROOTS (colon-separated) or default to every project dir
under $HOME/.claude/projects. Revisions come from HESTIA_BASE_REV / HESTIA_CANDIDATE_REV.
"""
import collections, glob, json, os, subprocess, sys, time, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("HESTIA_BASE_REV", "40903d6")
CANDIDATE = os.environ.get("HESTIA_CANDIDATE_REV", "fb91fb7")
CLOSURE = "plugins/_shared/hestia_governance_closure.py"
RESOLVER = "tools/redirect_target_resolver.py"
OUT = Path(os.environ.get("HESTIA_CENSUS_OUT", "/tmp/resolver_wild_census.json"))


def load(name, revision, path):
    source = subprocess.check_output(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, text=True)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, f"{revision}:{path}", "exec"), module.__dict__)
    return module


def corpus_roots():
    env = os.environ.get("HESTIA_TRANSCRIPT_ROOTS")
    if env:
        return [p for p in env.split(":") if p]
    base = Path.home() / ".claude" / "projects"
    return [str(p) for p in sorted(base.iterdir())] if base.is_dir() else []


def harvest():
    """Every distinct Bash command in the corpus, with one example cwd and timestamp."""
    seen = {}
    files = 0
    for root in corpus_roots():
        for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
            files += 1
            try:
                fh = open(fp, errors="replace")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if '"Bash"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    msg = rec.get("message") or {}
                    content = msg.get("content")
                    for b in (content if isinstance(content, list) else []):
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        if b.get("name") != "Bash":
                            continue
                        inp = b.get("input") or {}
                        cmd = inp.get("command")
                        if not isinstance(cmd, str) or not cmd:
                            continue
                        if cmd not in seen:
                            seen[cmd] = (rec.get("cwd"), rec.get("timestamp"), fp)
    return seen, files


def main():
    sys.dont_write_bytecode = True
    g = load("wild_governance", BASE, CLOSURE)
    r = load("wild_candidate", CANDIDATE, RESOLVER)
    shipped = g._bash_write_targets
    candidate, _ = r.make(g)

    t0 = time.time()
    seen, files = harvest()
    print(f"corpus: {files} transcript files, {len(seen)} DISTINCT Bash commands "
          f"({time.time()-t0:.1f}s)")

    pairs = collections.Counter()
    diffs = []
    t0 = time.time()
    for n, (cmd, (cwd, ts, fp)) in enumerate(seen.items(), 1):
        inp = {"command": cmd}
        g._bash_write_targets = shipped
        try:
            b = g.classify("Bash", inp, cwd=cwd)
            bc = b.classification
        except Exception as e:
            bc = "EXC:" + type(e).__name__
        g._bash_write_targets = candidate
        try:
            a = g.classify("Bash", inp, cwd=cwd)
            ac = a.classification
        except Exception as e:
            ac = "EXC:" + type(e).__name__
        pairs[(bc, ac)] += 1
        if bc != ac:
            diffs.append({"before": bc, "after": ac, "cwd": cwd, "ts": ts,
                          "src": fp, "command": cmd})
        if n % 20000 == 0:
            print(f"  ... {n}/{len(seen)} ({time.time()-t0:.0f}s)")
    g._bash_write_targets = shipped

    print(f"\nclassified {len(seen)} commands in {time.time()-t0:.0f}s")
    print(f"{'shipped':>12s} -> {'candidate':<12s}  n")
    for (bc, ac), n in sorted(pairs.items(), key=lambda kv: -kv[1]):
        flag = ""
        if bc != ac:
            flag = "   <== DISAGREE" + ("  (write -> read: the risk direction)"
                                        if bc == "write" and ac != "write" else "")
        print(f"{bc:>12s} -> {ac:<12s}  {n:7d}{flag}")
    OUT.write_text(json.dumps(diffs, indent=1))
    print(f"\n{len(diffs)} disagreements written to {OUT}")
    d2 = collections.Counter((d["before"], d["after"]) for d in diffs)
    print("disagreement directions:", dict(d2))


if __name__ == "__main__":
    main()
