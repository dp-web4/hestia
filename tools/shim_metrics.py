#!/usr/bin/env python3
"""#1103: common fidelity (M1) and exception size (M2), code lines only.

M1 is the multiset of normalized certified-template lines a seat carries, divided by the
certified line count. Fleet M1 intersects all seats. M2 is every line in a divergent permitted
function or a seat-only function, divided by that same certified count. Comments, docstrings and
blank lines never move either metric.

Repo mode measures the checked-out shims against plugins/_template/shim_template.py. --home
requires the daemon's current VERIFIED integrity verdict first and measures the deployed shims;
PENDING, MODIFIED, UNKNOWN and NO_STATUS never turn a developer-tree comparison into certification.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tokenize

REPO = Path(os.getenv("HESTIA_REPO_ROOT") or Path(__file__).resolve().parents[1])
TEMPLATE = REPO / "plugins" / "_template" / "shim_template.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CERT = _load("shim_certification", REPO / "tools" / "shim_certification.py")
VERDICT = _load("gate_verdict", REPO / "tools" / "gate_verdict.py")


def _mask_spans(lines: list[list[str]], spans: list[tuple[int, int, int, int]]) -> None:
    for start_line, start_col, end_line, end_col in spans:
        for number in range(start_line, end_line + 1):
            if number < 1 or number > len(lines):
                continue
            first = start_col if number == start_line else 0
            last = end_col if number == end_line else len(lines[number - 1])
            for column in range(first, min(last, len(lines[number - 1]))):
                lines[number - 1][column] = " "


def code_lines(src: str) -> dict[int, str]:
    """Normalized nonblank code by physical line, with comments and docstrings masked."""
    tree = ast.parse(src)
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            doc = body[0].value
            spans.append((doc.lineno, doc.col_offset, doc.end_lineno, doc.end_col_offset))
    comments = [(token.start[0], token.start[1], token.end[0], token.end[1])
                for token in tokenize.generate_tokens(io.StringIO(src).readline)
                if token.type == tokenize.COMMENT]
    lines = [list(line) for line in src.splitlines()]
    _mask_spans(lines, spans)
    _mask_spans(lines, comments)
    return {index: " ".join("".join(line).split())
            for index, line in enumerate(lines, 1) if "".join(line).strip()}


def function_lines(path: Path) -> tuple[dict[str, list[str]], int]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    code = code_lines(src)
    functions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = [text for number, text in sorted(code.items())
                                    if node.lineno <= number <= node.end_lineno]
    return functions, sum(map(len, functions.values()))


def measure(template: Path, seats: dict[str, Path]) -> dict:
    certified, total = function_lines(template)
    if not total:
        raise ValueError(f"certified template {template} contains no function code lines")
    rows = {}
    fleet_counters = {}
    for seat, path in seats.items():
        actual, _ = function_lines(path)
        common = 0
        exceptions = 0
        exception_functions = []
        for name, wanted in certified.items():
            got = actual.get(name, [])
            common += sum((Counter(wanted) & Counter(got)).values())
            fleet_counters.setdefault(name, []).append(Counter(got))
            if got != wanted:
                exceptions += len(got)
                exception_functions.append(name)
        for name, got in actual.items():
            if name not in certified:
                exceptions += len(got)
                exception_functions.append(name)
        rows[seat] = {
            "m1": common / total,
            "identical_sloc": common,
            "m2": exceptions / total,
            "exception_sloc": exceptions,
            "exception_functions": sorted(exception_functions),
            "divergent": sorted(name for name in certified if name in actual
                                and actual[name] != certified[name]),
            "missing": sorted(set(certified) - set(actual)),
        }
    fleet_common = 0
    for name, counters in fleet_counters.items():
        if len(counters) == len(seats):
            shared = Counter(certified[name])
            for other in counters:
                shared &= other
            fleet_common += sum(shared.values())
    return {"certified_sloc": total, "seats": rows,
            "fleet": {"m1": fleet_common / total, "identical_sloc": fleet_common}}


def bound_failures(report: dict, min_fleet: float | None,
                   min_seats: dict[str, float], max_seats: dict[str, float]) -> list[str]:
    failures = []
    fleet = report["fleet"]["m1"]
    if min_fleet is not None and fleet < min_fleet:
        failures.append(f"fleet M1 {fleet:.4f} < required {min_fleet:.4f}")
    for seat, floor in min_seats.items():
        if seat not in report["seats"]:
            failures.append(f"--min-seat-m1 names unknown seat {seat}")
        elif report["seats"][seat]["m1"] < floor:
            failures.append(f"{seat} M1 {report['seats'][seat]['m1']:.4f} < required {floor:.4f}")
    for seat, ceiling in max_seats.items():
        if seat not in report["seats"]:
            failures.append(f"--max-seat-m2 names unknown seat {seat}")
        elif report["seats"][seat]["m2"] > ceiling:
            failures.append(f"{seat} M2 {report['seats'][seat]['m2']:.4f} > allowed {ceiling:.4f}")
    return failures


def verified_home(home: Path) -> str | None:
    verdict = VERDICT.assess(home)
    if verdict["verdict"] == "VERIFIED":
        return None
    return f"{verdict['verdict']}: {verdict.get('reason') or 'the daemon has not verified these bytes'}"


def seat_map(deployed: bool) -> dict[str, Path]:
    return {seat: CERT.shim_path(seat, deployed) for seat in CERT.REPO_SHIMS}


def bounds(items: list[str]) -> dict[str, float]:
    out = {}
    for item in items:
        seat, sep, raw = item.partition("=")
        if not sep:
            raise ValueError(f"bound {item!r} must be SEAT=RATIO")
        out[seat] = float(raw)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", help="measure deployed shims only after this HESTIA_HOME verifies")
    parser.add_argument("--min-fleet-m1", type=float)
    parser.add_argument("--min-seat-m1", action="append", default=[], metavar="SEAT=RATIO")
    parser.add_argument("--max-seat-m2", action="append", default=[], metavar="SEAT=RATIO")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.home:
            failure = verified_home(Path(os.path.expanduser(args.home)))
            if failure:
                print(f"certification unavailable: {failure}", file=sys.stderr)
                return 1
        report = measure(TEMPLATE, seat_map(bool(args.home)))
        failures = bound_failures(report, args.min_fleet_m1,
                                  bounds(args.min_seat_m1), bounds(args.max_seat_m2))
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"cannot measure: {exc}", file=sys.stderr)
        return 2
    scope = "deployed" if args.home else "repo"
    if args.json:
        print(json.dumps({"scope": scope, "template": str(TEMPLATE), **report,
                          "failures": failures}, indent=2, sort_keys=True))
    else:
        print(f"certified template: {TEMPLATE} ({report['certified_sloc']} code lines; {scope})")
        for seat, row in report["seats"].items():
            print(f"{seat:<14} M1={row['m1']:.2%} M2={row['m2']:.4f} "
                  f"identical={row['identical_sloc']} exception={row['exception_sloc']} "
                  f"divergent={row['divergent']} missing={row['missing']}")
        print(f"{'fleet':<14} M1={report['fleet']['m1']:.2%} "
              f"identical={report['fleet']['identical_sloc']}")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
