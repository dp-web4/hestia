#!/usr/bin/env python3
import difflib
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

WT = pathlib.Path(sys.argv[1]).resolve()
BUILD = pathlib.Path(__file__).resolve().parent
MECHANISM = "plugins/_shared/hestia_gate_mechanism.py"
SINGLE_GATE = "plugins/_shared/hestia_single_gate.py"
CONTRACT = "tools/one_gate_decide_contract_test.py"
DECISION_CONTRACT = "tools/decision_witness_contract_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, (old[:120], text.count(old))
    return text.replace(old, new)


def patch_mechanism(src):
    src = once(src, '''                    action_id: Optional[str] = None,
                    correlation_key: Optional[str] = None,
                    deadline: Optional[float] = None) -> DecisionReceipt:
''', '''                    action_id: Optional[str] = None,
                    correlation_key: Optional[str] = None,
                    deadline: Optional[float] = None,
                    attempted_exact: bool = False) -> DecisionReceipt:
''')
    src = once(src, '''    `deadline`: an absolute `time.monotonic()` bound; no request starts after it. The caller's
      one invocation deadline (stage B) passes straight through — this helper mints no time.

    Returns a DecisionReceipt; `.committed` is True only on a receipt that names this decision.
''', '''    `deadline`: an absolute `time.monotonic()` bound; no request starts after it. The caller's
      one invocation deadline (stage B) passes straight through — this helper mints no time.
    `attempted_exact`: true only when the sender preserved the raw act byte-for-byte before
      bounded redaction, including whitespace. False is the safe default for older callers (#1588).

    Returns a DecisionReceipt; `.committed` is True only on a receipt that names this decision.
''')
    src = once(src, '''        "attempted": attempted_summary,
        "action_id": action_id,
''', '''        "attempted": attempted_summary,
        "attempted_exact": bool(attempted_exact),
        "action_id": action_id,
''')
    src = once(src, '''            "attempted": attempted_summary,
            "core_digest": record["core_digest"],
''', '''            "attempted": attempted_summary,
            "attempted_exact": bool(attempted_exact),
            "core_digest": record["core_digest"],
''')
    return once(src, '''        rpc = client.call_tool("hestia_witness_decision", args)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
''', '''        rpc = client.call_tool("hestia_witness_decision", args)
        kind, payload = _classify_decision_reply(rpc)
        if (kind == "ruled" and payload.get("code") == "hestia.witness_decision_unknown_arg"
                and payload.get("data", {}).get("unknownKeys") == ["attempted_exact"]):
            # ONE compatibility retry for an older daemon. If the input was already lossy, make
            # that visible to its pre-attempted_exact predicate too; never trade availability for
            # a false exact-retry identity (#1588 review).
            args.pop("attempted_exact")
            if (not attempted_exact
                    and not any(mark in attempted_summary for mark in ("…", "[REDACTED —", "***"))):
                args["attempted"] = attempted_summary + " …"
            rpc = client.call_tool("hestia_witness_decision", args)
            kind, payload = _classify_decision_reply(rpc)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
''')


def patch_single_gate(src):
    src = once(src, '''def _record(inv: _Invocation, d: GateDecision, attempted: Optional[str] = None):
    return mechanism.record_decision(
''', '''def _record(inv: _Invocation, d: GateDecision, attempted: Optional[str] = None):
    command = inv.event.tool_input.get("command")
    attempted_exact = (attempted is None and isinstance(command, str)
                       and " ".join(command.split()) == command)
    return mechanism.record_decision(
''')
    return once(src, '''        correlation_key=inv.key,
        deadline=inv.deadline,
    )
''', '''        correlation_key=inv.key,
        deadline=inv.deadline,
        attempted_exact=attempted_exact,
    )
''')


def diff(path, old, new):
    return f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for match in re.finditer(r"(?m)^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n", section):
        start = int(match.group(1)) - 1
        old, new = [], []
        tail = section[match.end():]
        for line in tail.splitlines(keepends=True):
            if line.startswith(("@@ ", "diff --git ")):
                break
            if line[:1] in " -":
                old.append(line[1:])
            if line[:1] in " +":
                new.append(line[1:])
        out.extend(lines[pos:start])
        assert lines[start:start + len(old)] == old, ("strict", start)
        out.extend(new)
        pos = start + len(old)
    out.extend(lines[pos:])
    return "".join(out)


def run_contract(root, mechanism, single_gate):
    overlay = root / "overlay"
    overlay.mkdir(parents=True)
    mechanism_copy = overlay / "hestia_gate_mechanism.py"
    gate_copy = overlay / "hestia_single_gate.py"
    mechanism_copy.write_text(mechanism, encoding="utf-8")
    gate_copy.write_text(single_gate, encoding="utf-8")
    env = dict(
        os.environ,
        HESTIA_CONTRACT_REPO=str(WT),
        HESTIA_CONTRACT_OVERLAY=json.dumps({
            "hestia_gate_mechanism": str(mechanism_copy),
            "hestia_single_gate": str(gate_copy),
        }),
        PYTHONDONTWRITEBYTECODE="1",
    )
    commands = [
        [sys.executable, str(WT / CONTRACT), "--only", "contract"],
        [sys.executable, str(WT / DECISION_CONTRACT)],
    ]
    runs = [
        subprocess.run(command, cwd=WT, env=env, text=True, capture_output=True)
        for command in commands
    ]
    return subprocess.CompletedProcess(
        commands,
        max(run.returncode for run in runs),
        "\n".join(run.stdout for run in runs),
        "\n".join(run.stderr for run in runs),
    )


def main():
    originals = {path: blob(path) for path in (MECHANISM, SINGLE_GATE)}
    candidates = {
        MECHANISM: patch_mechanism(originals[MECHANISM]),
        SINGLE_GATE: patch_single_gate(originals[SINGLE_GATE]),
    }
    work = pathlib.Path(tempfile.mkdtemp(prefix="run-", dir=BUILD))
    try:
        before = run_contract(work / "before", originals[MECHANISM], originals[SINGLE_GATE])
        print(before.stdout, end="")
        print(before.stderr, end="", file=sys.stderr)
        assert before.returncode != 0, "the new contract does not fail on the original sender"
        assert "raw-whitespace-exact" in before.stdout, "the fail-before arm did not run"

        after = run_contract(work / "after", candidates[MECHANISM], candidates[SINGLE_GATE])
        print(after.stdout, end="")
        print(after.stderr, end="", file=sys.stderr)
        assert after.returncode == 0, "the candidate sender failed the decision contract"
    finally:
        shutil.rmtree(work)

    body = "".join(diff(path, originals[path], candidates[path]) for path in originals)
    sha = hashlib.sha256(body.encode()).hexdigest()
    target = WT / "held" / (sha + ".patch")
    target.write_text(body, encoding="utf-8")
    for path, section in sections(body).items():
        assert strict_apply(originals[path], section) == candidates[path], path
        print("verified", path)
    print("patch", target)
    print("sha256", sha)


main()
