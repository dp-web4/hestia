#!/usr/bin/env python3
"""Non-executing regression checks for the 2026-10-10 scope review.

Run with Python -B, --repo CHECKOUT, and optionally --held PATCH_SHA256.
The held mode reconstructs repository-owned modules in memory, verifying the
patch digest and old hunk context. It never applies a patch or runs a command
represented by a test case. Only trusted repository code should be supplied.

--full-gate additionally uses the existing disposable policy stub across four
seats. This is not a real-daemon test. Use a nested checkout (not one directly
under the temporary root) because the contract fixture treats REPO.parent as
its workspace. Exit 1 means a violated invariant, not successful reproduction.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types

sys.dont_write_bytecode = True

# These strings are classifier inputs only. The target does not need to exist.
TARGET = "/etc/hestia-scope-review-nonexistent"
CASES = [
    ("direct", f"cat {TARGET}", False),
    ("standalone-c", f"bash -c 'cat {TARGET}'", False),
    ("long-option-c", f"bash --noprofile -c 'cat {TARGET}'", False),
    ("combined-lc", f"bash -lc 'cat {TARGET}'", False),
    ("combined-ec", f"sh -ec 'cat {TARGET}'", False),
    ("exec-combined", f"exec bash -lc 'cat {TARGET}'", False),
    ("sudo-combined", f"sudo bash -lc 'cat {TARGET}'", False),
    ("builtin-eval", f"builtin eval 'cat {TARGET}'", False),
    ("command-eval", f"command eval 'cat {TARGET}'", False),
    ("ansi-c-quote", f"cat $'{TARGET}'", False),
    ("shell-here-string", f"bash <<< 'cat {TARGET}'", False),
    ("shell-pipe", f"printf 'cat {TARGET}' | bash", False),
    ("shell-descriptor", f"bash /dev/fd/3 3<<< 'cat {TARGET}'", False),
    ("allowed-temp-path", "cat /tmp/hestia-scope-review-nonexistent", True),
    ("inert-here-string", f"cat <<< 'cat {TARGET}'", True),
    ("inert-pipe", f"printf 'cat {TARGET}' | cat", True),
]


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
        old = [] if "new file mode " in section else (repo / path).read_text().splitlines(True)
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
    shared = repo / "plugins/_shared"
    sys.path[:0] = [str(shared), str(repo / "tools")]
    os.environ["HESTIA_CONTRACT_REPO"] = str(repo)
    os.environ["HESTIA_CONTRACT_OVERLAY"] = "{}"
    loaded = {}
    for name in ("hestia_gate_core", "hestia_governance_closure",
                 "hestia_gate_mechanism", "hestia_single_gate"):
        rel = f"plugins/_shared/{name}.py"
        source = sources[rel] if rel in sources else (repo / rel).read_text()
        loaded[name] = load(name, repo / rel, source)
    core = loaded["hestia_gate_core"]
    failures, checks = [], 0

    def check(label, allowed, expected, rule="", evidenced=None):
        nonlocal checks
        checks += 1
        ok = allowed == expected and (evidenced is None or evidenced is True)
        if not expected and not label.startswith("helper/"):
            # An unrelated transport failure must not masquerade as a scope fix.
            ok = ok and rule == "mrh.command"
        row = dict(case=label, expected_allow=expected, actual_allow=allowed,
                   rule=rule, passed=ok)
        if evidenced is not None:
            row["evidence_committed"] = evidenced
        print(json.dumps(row), flush=True)
        if not ok:
            failures.append(label)

    workspace = "/home/scope-review-fixture/ws"
    cwd = workspace + "/granted"
    profile = core.HarnessProfile(member_id="review", identity_path="/nonexistent/review.json",
                                  home_markers=())
    policy = core.AgentPolicy(member_id="review", scope=("granted",), source="vault")
    for name, command, expected in CASES:
        reach = core.command_scope_reach(command, ["granted"], workspace, cwd, home_markers=[])
        decision = core.evaluate(core.NormalizedEvent(tool="Bash", command=command, cwd=cwd),
                                 profile, workspace, policy=policy)
        check("helper/" + name, reach[0], expected)
        check("core/" + name, decision.decision == "allow", expected, decision.rule)

    if args.full_gate:
        import one_gate_decide_contract_test as contract
        mechanism = loaded["hestia_gate_mechanism"]
        gate = loaded["hestia_single_gate"]
        with tempfile.TemporaryDirectory(prefix="scope-review-stub-") as directory:
            home = Path(directory)
            stub = contract.Stub(contract.Policy())
            try:
                with contract._Env(mechanism, stub.url, home):
                    sequence = 0
                    for seat in contract.SEATS:
                        for name, command, expected in CASES:
                            sequence += 1
                            decision, _ = contract._decide(gate, seat, "Bash",
                                {"command": command}, home, n=sequence)
                            check(seat + "/" + name, decision.decision == "allow", expected,
                                  decision.rule, decision.evidence_committed)
            finally:
                stub.close()
    print(json.dumps(dict(checks=checks, failures=len(failures), held=args.held,
                          full_gate=args.full_gate, failed_cases=failures)), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
