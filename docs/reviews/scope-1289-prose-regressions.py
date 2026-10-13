#!/usr/bin/env python3
"""Non-executing prose-option regression checks for PR #1289 / notice 21630.

Run with --repo CHECKOUT [--held SHA256] [--full-gate]. Held sources are
reconstructed in memory after checking the digest and every old hunk line.
No represented shell command is executed. Synthetic outside paths stay inside
the checkout on disk, but outside the test policy's narrower workspace.
The full-gate arm uses the repository's disposable policy stub, not a daemon.
Exit 1 means a scope invariant failed, including when reproducing the bug.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import types

sys.dont_write_bytecode = True


def reconstruct(repo, digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("--held must be a SHA256 digest")
    patch = (repo / "held" / (digest + ".patch")).read_bytes()
    if hashlib.sha256(patch).hexdigest() != digest:
        raise ValueError("held patch digest mismatch")
    sources = {}
    for section in patch.decode().split("diff --git ")[1:]:
        lines = section.splitlines(keepends=True)
        path = lines[0].rstrip("\n").split(" b/", 1)[1]
        if not path.startswith("plugins/_shared/") or not path.endswith(".py"):
            continue
        if ".." in Path(path).parts:
            raise ValueError("invalid patch path")
        old = (repo / path).read_text().splitlines(True)
        out, pos, active = [], 0, False
        for line in lines[1:]:
            if line.startswith("@@ "):
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
                if not match:
                    raise ValueError("unsupported hunk")
                start = max(0, int(match[1]) - 1)
                if start < pos:
                    raise ValueError("overlapping hunks")
                out.extend(old[pos:start])
                pos, active = start, True
            elif active and line[:1] in " +-":
                if line[0] in " -":
                    if pos >= len(old) or old[pos] != line[1:]:
                        raise ValueError(f"old context mismatch: {path}:{pos + 1}")
                    pos += 1
                if line[0] in " +":
                    out.append(line[1:])
            elif active and line.startswith("\\ No newline"):
                raise ValueError("unsupported missing-newline hunk")
        out.extend(old[pos:])
        sources[path] = "".join(out)
    return sources


def load(name, path, source):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--held")
    parser.add_argument("--full-gate", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    sources = reconstruct(repo, args.held) if args.held else {}
    sys.path[:0] = [str(repo / "plugins/_shared"), str(repo / "tools")]
    os.environ["HESTIA_CONTRACT_REPO"] = str(repo)
    os.environ["HESTIA_CONTRACT_OVERLAY"] = "{}"
    loaded = {}
    for name in ("hestia_gate_core", "hestia_governance_closure",
                 "hestia_gate_mechanism", "hestia_single_gate"):
        rel = f"plugins/_shared/{name}.py"
        source = sources[rel] if rel in sources else (repo / rel).read_text()
        loaded[name] = load(name, repo / rel, source)
    core = loaded["hestia_gate_core"]
    fixture = tempfile.TemporaryDirectory(prefix=".prose-review-", dir=repo)
    workspace = str(Path(fixture.name) / "ws")
    cwd = workspace + "/hestia"
    Path(cwd).mkdir(parents=True)
    target = shlex.quote(str(Path(fixture.name) / "outside/input"))
    cases = [
        ("grep-text", f"grep needle --text {target}", False),
        ("rg-text", f"rg needle --text {target}", False),
        ("diff-text", f"diff --text {target} /dev/null", False),
        ("readelf-notes", f"readelf --notes {target}", False),
        ("git-summary", f"git diff --no-index /dev/null --summary {target}", False),
        ("grep-text-unknown-variable", 'grep needle --text "$PROSE_REVIEW_UNSET"', False),
        ("direct-path-control", f"cat {target}", False),
        ("text-last-control", f"grep needle {target} --text", False),
        ("ordinary-reason-control", 'hestia gate deny X --reason "ordinary message"', True),
        ("quoted-echo-control", 'R="a * b"; echo "$R"', True),
        ("intended-reason-change", 'R="a * b"; hestia gate deny X --reason "$R"', bool(args.held)),
    ]
    failures, checks = [], 0

    def check(label, allowed, expected, rule="", evidenced=None):
        nonlocal checks
        checks += 1
        ok = allowed == expected and (evidenced is None or evidenced is True)
        if not expected and not label.startswith("helper/"):
            ok = ok and rule == "mrh.command"
        row = dict(case=label, expected_allow=expected, actual_allow=allowed,
                   rule=rule, passed=ok)
        if evidenced is not None:
            row["evidence_committed"] = evidenced
        print(json.dumps(row), flush=True)
        if not ok:
            failures.append(label)

    profile = core.HarnessProfile(member_id="review", identity_path=str(repo / "review-fixture/identity.json"),
                                  home_markers=())
    policy = core.AgentPolicy(member_id="review", scope=("hestia",), source="vault")
    for name, command, expected in cases:
        reach = core.command_scope_reach(command, ["hestia"], workspace, cwd, home_markers=[])
        decision = core.evaluate(core.NormalizedEvent(tool="Bash", command=command, cwd=cwd),
                                 profile, workspace, policy=policy)
        check("helper/" + name, reach[0], expected)
        check("core/" + name, decision.decision == "allow", expected, decision.rule)

    if args.full_gate:
        import one_gate_decide_contract_test as contract
        # Keep source loading pointed at the checkout; only the event's simulated
        # workspace/cwd changes. The stub policy already grants the hestia segment.
        contract.REPO = Path(cwd)
        mechanism = loaded["hestia_gate_mechanism"]
        gate = loaded["hestia_single_gate"]
        with tempfile.TemporaryDirectory(prefix="prose-review-stub-") as directory:
            home = Path(directory)
            stub = contract.Stub(contract.Policy())
            try:
                with contract._Env(mechanism, stub.url, home):
                    sequence = 0
                    for seat in contract.SEATS:
                        for name, command, expected in cases:
                            sequence += 1
                            decision, _ = contract._decide(gate, seat, "Bash",
                                {"command": command}, home, n=sequence)
                            check(seat + "/" + name, decision.decision == "allow", expected,
                                  decision.rule, decision.evidence_committed)
            finally:
                stub.close()
    print(json.dumps(dict(checks=checks, failures=len(failures), held=args.held,
                          full_gate=args.full_gate, failed_cases=failures)), flush=True)
    fixture.cleanup()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
