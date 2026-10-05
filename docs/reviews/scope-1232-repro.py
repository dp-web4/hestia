#!/usr/bin/env python3
"""Non-executing command probes for PR 1232 at a589ed9.

Run from the repository root: python3 docs/reviews/scope-1232-repro.py
Shell strings below are input DATA to the classifier, never executed. The only
network calls are to the contract suite's temporary local stub. No live daemon
is contacted and no real scope approval is spent. PASS means the reported bug
was reproduced, not that the implementation is correct.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import one_gate_decide_contract_test as contract


def main():
    mechanism, gate, _ = contract.load_engine()
    checks = 0

    def reproduced(label, condition):
        nonlocal checks
        assert condition, f"NOT reproduced: {label} (implementation may have changed)"
        checks += 1
        print(f"REPRODUCED: {label}")

    def digest(tool, payload):
        raw = contract.native_event("claude-code", tool, payload, str(REPO), 1)
        summary = gate.attempted_of(contract.to_event(gate, "claude-code", raw))
        # handler.rs: tool_scope_claim takes 400 chars before scope_act_digest.
        return hashlib.sha256((tool + "\x1f" + summary[:400]).encode()).hexdigest()

    pairs = [
        ("Write contents omitted", "Write",
         {"file_path": "/etc/review-probe", "content": "one"},
         {"file_path": "/etc/review-probe", "content": "two"}),
        ("Edit replacement omitted", "Edit",
         {"file_path": "/etc/review-probe", "old_string": "a", "new_string": "one"},
         {"file_path": "/etc/review-probe", "old_string": "a", "new_string": "two"}),
        ("credential masking collision", "Bash",
         {"command": "TOKEN=one cat /etc/review-probe"},
         {"command": "TOKEN=two cat /etc/review-probe"}),
        ("400-character truncation collision", "Bash",
         {"command": ": " + "x" * 410 + "; cat /etc/review-probe"},
         {"command": ": " + "x" * 410 + "; echo changed > /etc/review-probe"}),
        ("quoted whitespace collision", "Bash",
         {"command": "printf 'a  b' > /etc/review-probe"},
         {"command": "printf 'a b' > /etc/review-probe"}),
    ]
    for label, tool, first, second in pairs:
        reproduced(label, first != second and digest(tool, first) == digest(tool, second))

    # A synthetic workspace, never read or created. /etc exists; the classifier
    # checks the nearest existing ancestor even when review-probe does not exist.
    workspace = "/home/scope-review-fixture/ws"

    def reach(command):
        return gate.core.command_scope_reach(
            command, [], workspace, workspace, forbidden=[], home_markers=[])[0]

    reproduced("direct path is refused (control)", not reach("cat /etc/review-probe"))
    reproduced("unquoted data heredoc drops executable substitution",
               reach("cat <<EOF\n$(cat /etc/review-probe)\nEOF"))
    reproduced("quoted data heredoc remains data (control)",
               reach("cat <<'EOF'\n$(cat /etc/review-probe)\nEOF"))
    reproduced("64th path is refused (control)",
               not reach("cat " + " ".join(["/tmp/review-probe"] * 63 + ["/etc/review-probe"])))
    reproduced("65th path is never judged",
               reach("cat " + " ".join(["/tmp/review-probe"] * 64 + ["/etc/review-probe"])))
    reproduced("root glob discarded for cat", reach("cat /*"))
    reproduced("root glob refused for ls (control)", not reach("ls /*"))

    with tempfile.TemporaryDirectory(prefix="scope-review-stub-") as directory:
        home = pathlib.Path(directory)
        scenarios = [
            ("fifth path still refused after four spends",
             [f"/etc/review-probe-{i}" for i in range(5)], None, "mrh.command", 4),
            ("society denies after scope approval spent",
             ["/etc/review-probe"], lambda _: "deny", "society.safety", 1),
        ]
        for label, paths, query, expected_rule, expected_spends in scenarios:
            stub = contract.Stub(contract.Policy(scope_claim=lambda _: "approved", query=query))
            try:
                with contract._Env(mechanism, stub.url, home):
                    decision, _ = contract._decide(
                        gate, "codex", "Bash", {"command": "cat " + " ".join(paths)}, home)
                claims = [args for args, _ in stub.named("hestia_scope_claim")]
                spends = sum(args.get("spend", False) for args in claims)
                reproduced(label, decision.decision == "deny"
                           and decision.rule == expected_rule and spends == expected_spends)
                print(f"  final={decision.decision}/{decision.rule}; spend calls={spends}")
            finally:
                stub.close()
    print(f"PASS: {checks} review observations reproduced")


if __name__ == "__main__":
    main()
