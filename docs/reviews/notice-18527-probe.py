#!/usr/bin/env python3
"""Focused PR #1262 review probe; run from its checkout. No live services used.

Print measured results rather than pretending a reproduced defect is a passing
regression test. The shell invokes only a temporary script that prints a marker.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugins" / "_shared"))
import hestia_single_gate as gate


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="review-18527-") as tmp:
        root = pathlib.Path(tmp)
        shim = root / "gate_hook.py"
        shim.write_text("print('review-hook-ran')\n")
        config = root / "fixture.json"
        harness = {
            "event": "PreToolUse", "timeout_unit_seconds": 1,
            "margin_seconds": 1.5, "on_timeout": "fixture",
            "registrations": ({"reader": "json-hook-commands",
                               "layout": "nested", "path": str(config)},),
        }
        exact = {"command": f"python3 {shim}", "timeout": 15}

        def hooks(entries):
            return {"PreToolUse": [{"hooks": entries}]}

        def measure(label, raw, **evidence):
            config.write_text(raw)
            bound = gate.harness_bound(harness, str(shim), 100, env={"HOME": str(root)})
            results.append({"case": label, **evidence,
                            "timeout_seconds": bound.timeout_seconds,
                            "deadline": bound.deadline,
                            "why": bound.why.replace(str(root), "<fixture>")})

        spellings = [
            ("relative-control", "python3 ./gate_hook.py"),
            ("semicolon-control", "python3 ./gate_hook.py;"),
            ("quoted-fragment", "python3 ./gate_'hook'.py"),
            ("escaped-character", r"python3 ./gate_\hook.py"),
            ("quoted-fragment-semicolon", "python3 ./gate_'hook'.py;"),
        ]
        for label, command in spellings:
            ran = subprocess.run(["sh", "-c", command], cwd=root,
                                 capture_output=True, text=True, timeout=5)
            assert ran.returncode == 0 and ran.stdout.strip() == "review-hook-ran", ran
            raw = json.dumps({"hooks": hooks([exact, {"command": command, "timeout": 5}])})
            measure(label, raw, shell_ran_hook=True, command=command)

        measure("other-basename-control", json.dumps({"hooks": hooks([
            exact, {"command": "python3 ./gate_hook.py.bak", "timeout": 5}])}))
        entry = json.dumps(exact)
        event_groups = json.dumps(hooks([exact])["PreToolUse"])
        h = json.dumps(hooks([exact]))
        measure("duplicate-top-hooks-agreeing", '{"hooks":' + h + ',"hooks":' + h + '}')
        measure("duplicate-event-agreeing", '{"hooks":{"PreToolUse":' + event_groups
                + ',"PreToolUse":' + event_groups + '}}')
        measure("duplicate-group-hooks-agreeing", '{"hooks":{"PreToolUse":[{"hooks":['
                + entry + '],"hooks":[' + entry + ']}]}}')
        duplicate_entry = entry[:-1] + ',"timeout":15}'
        measure("duplicate-entry-timeout-control", '{"hooks":{"PreToolUse":[{"hooks":['
                + duplicate_entry + ']}]}}')
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
