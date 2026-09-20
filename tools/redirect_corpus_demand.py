"""What does the redirect resolver actually BUY? Dump the real commands it clears.

Loads both implementations from immutable git objects (codex's method in
tools/redirect_target_resolver_v5_review.py), scans the real transcript corpus for
tool_results that ARE a gate refusal, and prints every command whose classification
the candidate resolver changes from `write` to something else.

No hardcoded corpus paths: roots come from HESTIA_TRANSCRIPT_ROOTS (colon-separated)
or default to every project dir under $HOME/.claude/projects.
"""
import collections, glob, json, os, re, subprocess, sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("HESTIA_BASE_REV", "40903d6")
CANDIDATE = os.environ.get("HESTIA_CANDIDATE_REV", "fb91fb7")
CLOSURE = "plugins/_shared/hestia_governance_closure.py"
RESOLVER = "tools/redirect_target_resolver.py"


def load(name, revision, path, src=None):
    source = src if src is not None else subprocess.check_output(
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


START = re.compile(r"\A\s*(?:PreToolUse[^\n]*?hook error:[^\n]*?\n?)?\s*hestia: "
                   r"(?:ESCALATION [0-9a-f]{16} opened|deny \[gate-self-access\])")


def scan():
    calls, denied = {}, []
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
                    if "toolu_" not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    msg, cwd = rec.get("message") or {}, rec.get("cwd")
                    content = msg.get("content")
                    for b in (content if isinstance(content, list) else []):
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            calls[b.get("id")] = (b.get("name"), b.get("input"), cwd,
                                                  rec.get("timestamp"))
                        elif b.get("type") == "tool_result":
                            t = b.get("content")
                            if isinstance(t, list):
                                t = " ".join(x.get("text", "") for x in t
                                             if isinstance(x, dict))
                            if isinstance(t, str) and "gate-self-access" in t and START.match(t):
                                denied.append((b.get("tool_use_id"), t))
    return calls, denied, files


def main():
    sys.dont_write_bytecode = True
    g = load("corpus_governance", BASE, CLOSURE)
    src, label = None, CANDIDATE
    if "--file" in sys.argv:
        label = sys.argv[sys.argv.index("--file") + 1]
        src = Path(label).read_text()
    r = load("corpus_candidate", CANDIDATE, RESOLVER, src=src)
    shipped = g._bash_write_targets
    candidate, _ = r.make(g)
    calls, denied, files = scan()
    print(f"corpus: {files} transcript files, {len(calls)} tool_use, "
          f"{len(denied)} anchored refusals")
    rows, seen = [], set()
    for tid, _txt in denied:
        if tid not in calls:
            continue
        name, inp, cwd, ts = calls[tid]
        k = json.dumps(inp, sort_keys=True)[:4000]
        if k in seen:
            continue
        seen.add(k)
        g._bash_write_targets = shipped
        try:
            b = g.classify(name, inp, cwd=cwd)
        except Exception:
            b = None
        g._bash_write_targets = candidate
        try:
            a = g.classify(name, inp, cwd=cwd)
        except Exception:
            a = None
        rows.append((ts, name, b, a, inp, cwd))
    g._bash_write_targets = shipped
    still = [x for x in rows if x[2] and x[2].classification == "write"]
    cleared = [x for x in still if x[3] and x[3].classification != "write"]
    print(f"{len(rows)} distinct refused calls; {len(still)} still classified write today; "
          f"{len(cleared)} cleared by {label}")
    out = []
    for ts, name, b, a, inp, cwd in cleared:
        out.append({"ts": ts, "tool": name, "after": a.classification, "cwd": cwd,
                    "input": inp})
    Path(os.environ.get("HESTIA_DEMAND_OUT",
                        "/tmp/redirect_demand.json")).write_text(json.dumps(out, indent=1))
    allrows = [{"ts": ts, "tool": name, "cwd": cwd, "input": inp,
                "before": b.classification if b else None,
                "after": a.classification if a else None}
               for ts, name, b, a, inp, cwd in rows]
    Path("/tmp/redirect_refusals_all.json").write_text(json.dumps(allrows, indent=1))
    print("\n=== the commands the resolver exists to clear ===")
    for i, o in enumerate(out, 1):
        print(f"\n--- [{i}] {o['ts']} -> {o['after']}")
        print((o["input"] or {}).get("command", ""))


if __name__ == "__main__":
    main()
