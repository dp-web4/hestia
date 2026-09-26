"""Why does v6 refuse each real false positive? Design cost, or implementation crudeness?

v6 is safe on the whole generated battery (0 of 2250 unsafe, against v5's 234) but clears
only 1 of the 25 real corpus commands v5 clears. That number is worthless until it is
attributed: a clause that is load-bearing for safety is a real cost, a clause that is
merely coarse is a bug. This prints, per command, the FIRST v6 clause that refuses it.
"""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redirect_target_resolver_v6 as v6

DEMAND = os.environ.get("HESTIA_DEMAND_IN", "/tmp/redirect_demand.json")


def diagnose(command):
    """Return (reason, detail) for the first clause that stops every binding."""
    rendering = v6.pretty(command)
    if rendering is None:
        return "V1 bash did not parse (or no bash)", ""
    rendering = v6.strip_heredoc_bodies(rendering)
    hits = [w for w in v6._command_position_words(rendering)
            if w in v6._REBINDERS or os.path.basename(w) in v6._REBINDERS]
    if hits:
        return "V4 rebinder head anywhere", ",".join(sorted(set(hits))[:6])
    stmts = v6._top_level_statements(rendering)
    assigns = [(o, s, ln) for o, s, ln in stmts if v6._ASSIGN_STMT.match(s)]
    if not assigns:
        indented = [s for s in re.findall(r"(?m)^[ \t]+(\S+=\S*)", rendering)]
        return ("V2 no top-level NAME=literal statement",
                ("only indented: " + ",".join(indented[:3])) if indented else "")
    def bad(stmt, seg):
        t = seg.strip()
        return not t.startswith(stmt) or any(b in t[len(stmt):] for b in v6._BAD_AFTER)
    blocked = [s for o, s, sg in assigns if bad(s, sg)]
    if len(blocked) == len(assigns):
        return "V3 binding is guarded / piped / backgrounded", ",".join(blocked[:3])
    nonlit = [s for o, s, sg in assigns
              if not bad(s, sg) and not v6._is_literal(v6._ASSIGN_STMT.match(s).group(2))]
    survivors = [(o, s, sg) for o, s, sg in assigns
                 if not bad(s, sg) and v6._is_literal(v6._ASSIGN_STMT.match(s).group(2))]
    if not survivors:
        return "V2 value is not a literal", ",".join(nonlit[:3])
    multi = []
    for o, s, sg in survivors:
        name = v6._ASSIGN_STMT.match(s).group(1)
        bare = [m.start() for m in
                re.finditer(r"(?<![$\w}])" + re.escape(name) + r"(?![\w])", rendering)]
        if len(bare) != 1:
            multi.append(f"{name}x{len(bare)}")
    if len(multi) == len(survivors):
        return "V2 name occurs bare more than once", ",".join(multi[:4])
    return "resolved something", ",".join(
        v6._ASSIGN_STMT.match(s).group(1) for o, s, sg in survivors)


def main():
    rows = json.load(open(DEMAND))
    print(f"{len(rows)} commands v5 clears; attributing v6's refusal of each\n")
    counts = {}
    for i, row in enumerate(rows, 1):
        cmd = (row.get("input") or {}).get("command", "")
        reason, detail = diagnose(cmd)
        counts[reason] = counts.get(reason, 0) + 1
        head = cmd.split("\n")[0][:78]
        print(f"[{i:2d}] {reason:42s} {detail[:46]:46s} | {head}")
    print("\nsummary:")
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {k}")


if __name__ == "__main__":
    main()
