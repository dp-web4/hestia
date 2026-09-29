#!/usr/bin/env python3
"""Every function in every shim carries an explicit, CURRENT justification for being in the shim.

dp's ruling (GATE_ARCHITECTURE section 2): a line may live in a shim only if it is demonstrably
unique to that harness, and the burden of proof is on the shim. The collapse meter caps a
per-seat percentage and grades forks; it never asks a function why it exists.

This is not a metric. dp, 2026-09-02: "heuristics are useful tools, but very specific and
limited in scope. when governing reasoners, there must be reason-in-the-loop because every
heuristic can be gamed by a competent reasoner." So this tool judges nothing about the
justification. It guarantees three things a reasoner cannot skip:

  EXISTS    every top-level def/class in a shim's gate module has a row
  CURRENT   the row carries a hash of the function's source; change the function and the
            row is stale until someone re-justifies it in the same change, which puts the
            reasoning in the diff the reviewer reads
  OWNED     law admitted to be in the shim (LAW-DEBT) names the issue that owns its removal

The ledger is plugins/_shared/SHIM_LEDGER.md: the common gate owns the list of what the shims
may keep, the way it owns the reach table, and it sits inside the governance closure so
editing it is a gate-self write like editing the shim. One section per seat:

    | `name` | class | src | justification |

class is one of the five things the architecture allows a shim to own, plus the wiring that
reaches the gate, plus admitted debt:

    event-shape       how THIS harness spells its event; translation only, no meaning
    refusal-channel   how THIS harness is told no (exit code, stdout payload, fail-open default)
    registration      where THIS harness records its hooks and how that file is read
    identity          the plugin id / role this seat acts under, passed to the gate
    launch            platform launch / restart verbs
    wiring            the installed-only loader, endpoint discovery, thin one-call delegation
    LAW-DEBT          law still in the shim; MUST cite the issue that owns its removal

src is the first 8 hex of sha256 over the function's source with trailing whitespace stripped
per line. `--emit SEAT` prints the rows for a seat with current hashes (class and
justification left for a person to write), and `--refresh` rewrites only the src column of
rows whose function changed, so re-justifying is an edit to the row, not a hash chore.

The meter's lexical law classification is printed as a pointer for the reviewer, never as a
verdict: a body that speaks of deny/escalate/classify while its row says event-shape is the
row to read first.

EXIT: 0 every function justified and current, debt owned; 1 otherwise; 2 no ledger / gates
not discoverable.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate_collapse_meter as meter  # noqa: E402

CLASSES = ("event-shape", "refusal-channel", "registration", "identity", "launch", "wiring", "LAW-DEBT")
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([A-Za-z-]+)\s*\|\s*([0-9a-f]{8}|-)\s*\|\s*(.*?)\s*\|\s*$")
SECTION = re.compile(r"^##\s+(\S+)\s*$")
ISSUE = re.compile(r"#\d+")
MIN_JUSTIFICATION = 40


def parse_ledger(text: str) -> dict:
    """{seat: {name: (class, src, justification)}}; a name listed twice in one section is an error."""
    out, seat, errors = {}, None, []
    for ln in text.splitlines():
        m = SECTION.match(ln)
        if m:
            seat = m.group(1)
            out.setdefault(seat, {})
            continue
        m = ROW.match(ln)
        if m and seat:
            name, cls, src, just = m.groups()
            if name in out[seat]:
                errors.append(f"{seat}: `{name}` listed twice")
            out[seat][name] = (cls, src, just)
    if errors:
        raise ValueError("; ".join(errors))
    return out


def source_hash(segment: str) -> str:
    norm = "\n".join(ln.rstrip() for ln in segment.splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


def top_level(path: Path) -> list[dict]:
    """Every top-level def/class with its source hash, plus the meter's lexical flags."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fns, _ = meter.module_functions(path)
    flags = {f["name"]: f for f in fns if f["top_level"]}
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seg = ast.get_source_segment(src, n) or ""
            f = flags.get(n.name, {})
            out.append({"name": n.name, "src": source_hash(seg), "sloc": n.end_lineno - n.lineno + 1,
                        "law": bool(f.get("law_bearing")), "thin": bool(f.get("delegates"))})
    return out


def check_seat(seat: str, gate: Path, rows: dict) -> tuple[list[str], list[dict]]:
    violations, table = [], []
    live = top_level(gate)
    names = {e["name"] for e in live}
    for e in live:
        row = rows.get(e["name"])
        entry = dict(e, seat=seat, cls=None, stale=False, pointer=False)
        if row is None:
            violations.append(f"{seat}: `{e['name']}` has no justification row")
        else:
            cls, src, just = row
            entry["cls"] = cls
            if cls not in CLASSES:
                violations.append(f"{seat}: `{e['name']}` class '{cls}' is not one of {', '.join(CLASSES)}")
            if len(just) < MIN_JUSTIFICATION:
                violations.append(f"{seat}: `{e['name']}` justification is not a sentence ({len(just)} chars)")
            if cls == "LAW-DEBT" and not ISSUE.search(just):
                violations.append(f"{seat}: `{e['name']}` is LAW-DEBT with no owning issue (#NNN)")
            if src != e["src"]:
                entry["stale"] = True
                violations.append(f"{seat}: `{e['name']}` changed since it was justified "
                                  f"(ledger {src}, source {e['src']}); re-justify it in this change")
            entry["pointer"] = e["law"] and not e["thin"] and cls != "LAW-DEBT"
        table.append(entry)
    for name in rows:
        if name not in names:
            violations.append(f"{seat}: ledger row `{name}` names no top-level def/class in {gate.name} (stale row)")
    return violations, table


def emit(seat: str, gate: Path, rows: dict) -> str:
    """Rows for a seat with current hashes; existing class/justification kept, else left blank."""
    out = [f"## {seat}", "", "| function | class | src | justification |", "|---|---|---|---|"]
    for e in top_level(gate):
        cls, _, just = rows.get(e["name"], ("", "-", ""))
        out.append(f"| `{e['name']}` | {cls} | {e['src']} | {just} |")
    return "\n".join(out) + "\n"


def refresh(ledger: Path, gates: dict, rows: dict) -> int:
    """Rewrite only the src column of rows whose function changed. Returns rows refreshed."""
    text = ledger.read_text(encoding="utf-8")
    current = {seat: {e["name"]: e["src"] for e in top_level(g)} for seat, g in gates.items()}
    out, seat, n = [], None, 0
    for ln in text.splitlines():
        m = SECTION.match(ln)
        if m:
            seat = m.group(1)
        m = ROW.match(ln)
        if m and seat in current and m.group(1) in current[seat] and m.group(3) != current[seat][m.group(1)]:
            ln = ln.replace(f"| {m.group(3)} |", f"| {current[seat][m.group(1)]} |", 1)
            n += 1
        out.append(ln)
    ledger.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="repo root (default: discovered)")
    ap.add_argument("--ledger", default=None, help="ledger path (default: plugins/_shared/SHIM_LEDGER.md)")
    ap.add_argument("--gate", action="append", default=[], metavar="SEAT=PATH",
                    help="override discovery with explicit gates (tests)")
    ap.add_argument("--emit", metavar="SEAT", help="print this seat's rows with current hashes and exit")
    ap.add_argument("--refresh", action="store_true",
                    help="rewrite the src column of rows whose function changed, then check")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else meter.repo_root(HERE)
    ledger = Path(args.ledger) if args.ledger else root / "plugins" / "_shared" / "SHIM_LEDGER.md"
    if args.gate:
        gates = {k: Path(v) for k, _, v in (g.partition("=") for g in args.gate)}
    else:
        found, unclassified = meter.discover_gates(root)
        if unclassified:
            print(f"INDETERMINATE: unclassified hook modules {unclassified}", file=sys.stderr)
            return 2
        gates = {seat: path for seat, path in found}      # discover_gates yields (seat, path)
    rows = {}
    if ledger.is_file():
        try:
            rows = parse_ledger(ledger.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
    if args.emit:
        if args.emit not in gates:
            print(f"no gate discovered for seat {args.emit}; have {sorted(gates)}", file=sys.stderr)
            return 2
        print(emit(args.emit, gates[args.emit], rows.get(args.emit, {})), end="")
        return 0
    if not ledger.is_file():
        print(f"INDETERMINATE: no ledger at {ledger}; every shim function is unjustified", file=sys.stderr)
        return 2
    if args.refresh:
        n = refresh(ledger, gates, rows)
        print(f"refreshed src on {n} row(s)")
        rows = parse_ledger(ledger.read_text(encoding="utf-8"))

    violations, tables = [], {}
    for seat in sorted(gates):
        v, t = check_seat(seat, gates[seat], rows.get(seat, {}))
        if seat not in rows:
            v.insert(0, f"{seat}: ledger has no section")
        violations += v
        tables[seat] = t
    for seat in rows:
        if seat not in gates:
            violations.append(f"ledger section `{seat}` matches no discovered gate")

    print(f"{'seat':<13}{'function':<32}{'class':<17}{'sloc':>5}  for the reviewer")
    for seat, t in tables.items():
        for e in t:
            note = []
            if e["stale"]:
                note.append("CHANGED since justified")
            if e["pointer"]:
                note.append("meter reads law here; read this row first")
            if e["thin"]:
                note.append("thin delegation")
            print(f"{seat:<13}{e['name']:<32}{(e['cls'] or 'UNLISTED'):<17}{e['sloc']:>5}  {'; '.join(note)}")
        debt = sum(1 for e in t if e["cls"] == "LAW-DEBT")
        ptr = sum(1 for e in t if e["pointer"])
        print(f"{seat:<13}{len(t)} functions, {debt} LAW-DEBT, {ptr} pointer(s) for review (not a verdict)")
    if violations:
        print("\nFAIL:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("\nok: every shim function carries a current justification and every admitted debt names its issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
