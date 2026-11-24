#!/usr/bin/env python3
"""ACX regression for runtime.python_ambient_import and ADR 0019.

The process arms run real Python in temporary directories. The malicious module only returns a
marker string: no credentials, network, or filesystem outside the fixture is touched.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "_shared"))
import hestia_gate_core as gate  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def signal(command: str, cwd: str, workspace: str | None = None, scopes=()):
    return gate.python_ambient_import_verdict(command, cwd, workspace or cwd, scopes)


def evaluate(command: str, cwd: str, scopes=()):
    event = gate.NormalizedEvent(tool="Bash", command=command, cwd=cwd)
    profile = gate.HarnessProfile(member_id="acx", identity_path="")
    return gate.evaluate(event, profile, cwd, gate.AgentPolicy(member_id="acx", scope=scopes))


def run_python(args: list[str], cwd: Path,
               extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(extra_env or {})
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=10, check=False)


def main() -> int:
    print("ACX-01 — ambient shadowing and the visible risk signal")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "base64.py").write_text('VALUE = "shadowed"\n')
        (root / "helper.py").write_text("import base64\nprint(base64.__file__)\n")
        ordinary = run_python(["helper.py"], root)
        isolated = run_python(["-I", "helper.py"], root)
        check("ordinary Python demonstrates ambient import shadowing",
              ordinary.returncode == 0 and str(root / "base64.py") in ordinary.stdout,
              ordinary.stdout + ordinary.stderr)
        check("python -I removes that specific import path",
              isolated.returncode == 0 and str(root / "base64.py") not in isolated.stdout,
              isolated.stdout + isolated.stderr)
        command = f"cd {shlex.quote(tmp)} && python3 helper.py"
        verdict = signal(command, tmp)
        check("the gate emits runtime.python_ambient_import",
              verdict is not None and verdict.rule == "runtime.python_ambient_import"
              and verdict.decision == "warn", repr(verdict))
        check("the witnessed evidence names cwd and the isolated-mode remedy",
              verdict is not None and tmp in verdict.reason and "-I" in verdict.remedy,
              repr(verdict))
        check("the same warning reaches the complete evaluate path",
              evaluate(command, tmp, [f"path:{tmp}"]).rule == "runtime.python_ambient_import",
              repr(evaluate(command, tmp, [f"path:{tmp}"])))

    print("ACX-02 — declared local package execution is not a blanket -I denial")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pyproject.toml").write_text('[project]\nname = "acx-local"\nversion = "0.0.0"\n')
        (root / "sibling.py").write_text('VALUE = "local"\n')
        (root / "helper.py").write_text("from sibling import VALUE\nprint(VALUE)\n")
        result = run_python(["helper.py"], root)
        check("legitimate sibling import works", result.returncode == 0 and "local" in result.stdout,
              result.stdout + result.stderr)
        command = "python3 -c 'from sibling import VALUE; print(VALUE)'"
        check("a cloned package marker alone is NOT authority",
              signal(command, tmp) is not None
              and signal(command, tmp).rule == "runtime.python_ambient_import",
              "without an explicit path grant, the risk signal must remain")
        grants = [f"path:{tmp}"]
        check("an explicitly granted package root suppresses the signal",
              signal(command, tmp, scopes=grants) is None, repr(signal(command, tmp, scopes=grants)))
        check("the complete evaluate path preserves the local workflow",
              evaluate(command, tmp, grants).decision == "allow", repr(evaluate(command, tmp, grants)))
        (root / "nested").mkdir()
        (root / "nested" / "helper.py").write_text("from sibling import VALUE\nprint(VALUE)\n")
        nested_command = f"cd /tmp && python3 {root / 'nested' / 'helper.py'}"
        check("file execution uses the script directory, not the invocation cwd",
              signal(nested_command, "/tmp", workspace=tmp, scopes=grants) is None,
              repr(signal(nested_command, "/tmp", workspace=tmp, scopes=grants)))
        with tempfile.TemporaryDirectory() as untrusted:
            (Path(untrusted) / "helper.py").write_text("print('untrusted')\n")
            outside = f"python3 {untrusted}/helper.py"
            check("a trusted invocation cwd does not make an untrusted script trusted",
                  signal(outside, tmp, workspace=tmp, scopes=grants) is not None
                  and signal(outside, tmp, workspace=tmp, scopes=grants).rule
                  == "runtime.python_ambient_import",
                  repr(signal(outside, tmp, workspace=tmp, scopes=grants)))
            (root / "cwd_probe.py").write_text("from cwd_only import VALUE\nprint(VALUE)\n")
            (Path(untrusted) / "cwd_only.py").write_text('VALUE = "cwd"\n')
            empty_path = run_python([str(root / "cwd_probe.py")], Path(untrusted),
                                    {"PYTHONPATH": ":"})
            check("CPython empty PYTHONPATH entries import from the invocation cwd",
                  empty_path.returncode == 0 and empty_path.stdout.strip() == "cwd",
                  empty_path.stdout + empty_path.stderr)
            empty_command = f"PYTHONPATH=: python3 {root / 'cwd_probe.py'}"
            verdict = signal(empty_command, untrusted, workspace=tmp, scopes=grants)
            check("an empty PYTHONPATH entry cannot hide an untrusted invocation cwd",
                  verdict is not None and verdict.target == str(Path(untrusted).resolve()),
                  repr(verdict))
        check("the combined -Iu spelling is recognized as isolated",
              signal("python3 -Iu helper.py", tmp) is None)
        check("the separate -I -c spelling is recognized as isolated",
              signal("python3 -I -c 'from sibling import VALUE; print(VALUE)'", tmp) is None)
        check("a PYTHONPATH prefix is parsed but does not create package trust",
              signal("PYTHONPATH=/tmp python3 helper.py", tmp) is not None
              and signal("PYTHONPATH=/tmp python3 helper.py", tmp).rule
              == "runtime.python_ambient_import")
        with tempfile.TemporaryDirectory() as ambient:
            (Path(ambient) / "injected.py").write_text('VALUE = "ambient"\n')
            injected_code = "from injected import VALUE; print(VALUE)"
            injected = run_python(["-c", injected_code], root, {"PYTHONPATH": ambient})
            check("CPython imports an untrusted PYTHONPATH module beneath a trusted cwd",
                  injected.returncode == 0 and injected.stdout.strip() == "ambient",
                  injected.stdout + injected.stderr)
            injected_command = (
                f"PYTHONPATH={shlex.quote(ambient)} python3 -c {shlex.quote(injected_code)}")
            check("a trusted package root does not launder an untrusted PYTHONPATH",
                  signal(injected_command, tmp, scopes=grants) is not None
                  and signal(injected_command, tmp, scopes=grants).target == ambient,
                  repr(signal(injected_command, tmp, scopes=grants)))
            declared_command = (
                f"PYTHONPATH={shlex.quote(tmp)} python3 -c {shlex.quote(injected_code)}")
            check("a declared PYTHONPATH beneath the trusted package root stays allowed",
                  signal(declared_command, tmp, scopes=grants) is None,
                  repr(signal(declared_command, tmp, scopes=grants)))

    print("ACX-03 — explicit sys.path manipulation remains outside -I's claim")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "base64.py").write_text('VALUE = "shadowed"\n')
        (root / "helper.py").write_text(
            f"import sys\nsys.path.insert(0, {str(root)!r})\nimport base64\nprint(base64.__file__)\n")
        bypass = run_python(["-I", "helper.py"], root)
        check("explicit sys.path insertion still shadows under -I",
              bypass.returncode == 0 and str(root / "base64.py") in bypass.stdout,
              bypass.stdout + bypass.stderr)
        check("isolated mode alone is not represented as containment",
              signal("python3 -I helper.py", tmp) is None,
              "the signal is about launch hygiene; stronger effects need a capability boundary")

    print("ACX-04 — a child gets its own identity and context, not ambient parent trust")
    with tempfile.TemporaryDirectory() as parent_tmp, tempfile.TemporaryDirectory() as child_tmp:
        (Path(parent_tmp) / "pyproject.toml").write_text('[project]\nname = "parent"\nversion = "0.0.0"\n')
        child_code = """import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location('hestia_gate_core', sys.argv[1])
gate = importlib.util.module_from_spec(spec)
sys.modules['hestia_gate_core'] = gate
spec.loader.exec_module(gate)
event = gate.NormalizedEvent(tool='Bash', command='python3 helper.py', cwd=sys.argv[2])
profile = gate.HarnessProfile(member_id='child', identity_path='')
policy = gate.AgentPolicy(member_id='child', scope=())
verdict = gate.evaluate(event, profile, sys.argv[2], policy)
print(json.dumps({'pid': os.getpid(), 'decision': verdict.decision, 'rule': verdict.rule}))
"""
        child_env = os.environ.copy()
        child_env["HESTIA_PARENT_SCOPE"] = f"path:{parent_tmp}"
        child = subprocess.run(
            [sys.executable, "-I", "-c", child_code, gate.__file__, child_tmp],
            cwd=child_tmp, env=child_env, capture_output=True, text=True, timeout=10, check=False)
        payload = json.loads(child.stdout) if child.returncode == 0 else {}
        check("the real child process has a distinct attributable identity",
              child.returncode == 0 and payload.get("pid") != os.getpid(), child.stderr)
        parent_verdict = evaluate("python3 helper.py", parent_tmp, [f"path:{parent_tmp}"])
        check("the child gate does not inherit the parent's trusted package root",
              parent_verdict.decision == "allow"
              and payload.get("rule") == "runtime.python_ambient_import"
              and payload.get("decision") == "warn",
              f"parent={parent_verdict} child={payload} stderr={child.stderr}")

    print("ACX-05 — remediation is provenance/policy work, not a universal kill ban")
    with tempfile.TemporaryDirectory() as tmp:
        remediation = evaluate("kill -TERM 12345", tmp)
        check("a process termination act is not denied by the new Python signal",
              remediation.rule != "runtime.python_ambient_import", repr(remediation))
        unrelated = evaluate("rm -rf /", tmp)
        check("an unrelated destructive act remains refused",
              unrelated.blocks and unrelated.rule != "runtime.python_ambient_import",
              repr(unrelated))

    print("ACX-06 — interpreter option parsing matches CPython")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        code = "import sys; print(sys.flags.isolated)"
        ordinary = run_python(["-c", code, "-I"], root)
        check("CPython treats -I after -c as a program argument",
              ordinary.returncode == 0 and ordinary.stdout.strip() == "0",
              ordinary.stdout + ordinary.stderr)
        verdict = signal(f"python3 -c {shlex.quote(code)} -I", tmp)
        check("the gate does not treat -I after -c as isolation",
              verdict is not None and verdict.rule == "runtime.python_ambient_import",
              repr(verdict))

        (root / "probe.py").write_text(
            "import sys\nprint(sys.flags.isolated)\nprint(sys.path[0])\n")
        module = run_python(["-m", "probe", "granted/helper.py", "-I"], root)
        lines = module.stdout.splitlines()
        check("CPython -m imports from cwd and leaves later arguments to the module",
              module.returncode == 0 and lines[:1] == ["0"]
              and Path(lines[1]).resolve() == root.resolve(),
              module.stdout + module.stderr)
        (root / "granted").mkdir()
        (root / "granted" / "pyproject.toml").write_text("[project]\nname = 'decoy'\n")
        verdict = signal("python3 -m probe granted/helper.py -I", tmp,
                         scopes=[f"path:{root / 'granted'}"])
        check("a path-shaped module argument cannot supply package trust",
              verdict is not None and verdict.rule == "runtime.python_ambient_import"
              and verdict.target == str(root), repr(verdict))

        clustered = run_python(["-uI", "-c", code], root)
        check("CPython recognizes the -uI short-option cluster as isolated",
              clustered.returncode == 0 and clustered.stdout.strip() == "1",
              clustered.stdout + clustered.stderr)
        check("the gate recognizes -uI as isolated",
              signal(f"python3 -uI -c {shlex.quote(code)}", tmp) is None)

        path_code = "import sys; print(sys.path[0])"
        command_path = run_python(["-c", path_code, "granted/helper.py"], root)
        check("CPython -c imports from cwd despite a path-shaped argument",
              command_path.returncode == 0 and not command_path.stdout.strip(),
              command_path.stdout + command_path.stderr)
        verdict = signal(f"python3 -c {shlex.quote(path_code)} granted/helper.py", tmp,
                         scopes=[f"path:{root / 'granted'}"])
        check("a path-shaped -c argument cannot supply package trust",
              verdict is not None and verdict.target == str(root), repr(verdict))
        clustered_script = run_python(["-uI", "probe.py"], root)
        check("CPython recognizes -uI before a script",
              clustered_script.returncode == 0
              and clustered_script.stdout.splitlines()[:1] == ["1"],
              clustered_script.stdout + clustered_script.stderr)
        check("the gate recognizes -uI before a script",
              signal("python3 -uI probe.py", tmp) is None)
        check("a short-option cluster ending in -W consumes its separate value",
              signal(f"python3 -uW granted/helper.py -c {shlex.quote(code)}", tmp,
                     scopes=[f"path:{root / 'granted'}"]) is not None)
        (root / "-I").write_text("import sys\nprint(sys.flags.isolated)\n")
        double_dash = run_python(["--", "-I"], root)
        check("CPython -- makes a following -I the script filename",
              double_dash.returncode == 0 and double_dash.stdout.strip() == "0",
              double_dash.stdout + double_dash.stderr)
        check("the gate does not parse a filename after -- as an isolation flag",
              signal("python3 -- -I", tmp) is not None)

        check("which python3 is not a Python invocation",
              signal("which python3", tmp) is None)
        check("a grep pattern naming python is not a Python invocation",
              signal("grep python3 setup.cfg", tmp) is None)
        check("env preserves a direct Python command position",
              signal(f"env python3 -c {shlex.quote(code)}", tmp) is not None)
        check("a later non-isolated interpreter is not hidden by an earlier -I",
              signal("python3 -I probe.py && python3 probe.py", tmp) is not None)
        (root / "granted" / "probe.py").write_text("print('granted')\n")
        trusted_cd = f"cd {shlex.quote(str(root / 'granted'))} && python3 probe.py"
        check("a preceding cd supplies the interpreter's package evidence",
              signal(trusted_cd, tmp, scopes=[f"path:{root / 'granted'}"]) is None,
              repr(signal(trusted_cd, tmp, scopes=[f"path:{root / 'granted'}"])))

        trusted_newline = f"cd {shlex.quote(str(root / 'granted'))}\npython3 probe.py"
        check("a newline supplies the same command boundary as a semicolon",
              signal(trusted_newline, tmp, scopes=[f"path:{root / 'granted'}"]) is None,
              repr(signal(trusted_newline, tmp, scopes=[f"path:{root / 'granted'}"])))
        conditional = f"false && cd {shlex.quote(str(root / 'granted'))}; python3 probe.py"
        verdict = signal(conditional, tmp, scopes=[f"path:{root / 'granted'}"])
        check("a failed conditional cd cannot manufacture package trust",
              verdict is not None and verdict.target == str(root), repr(verdict))
        missing = f"cd {shlex.quote(str(root / 'missing'))} && python3 probe.py"
        check("a failed cd stops the dependent interpreter invocation",
              signal(missing, tmp, scopes=[f"path:{root / 'granted'}"]) is None,
              repr(signal(missing, tmp, scopes=[f"path:{root / 'granted'}"])))
        nested = root / "granted" / "downloads" / "untrusted"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text("[project]\nname='nested-untrusted'\n")
        (nested / "probe.py").write_text("print('nested')\n")
        nested_command = f"cd {shlex.quote(str(nested))} && python3 probe.py"
        verdict = signal(nested_command, tmp, scopes=[f"path:{root / 'granted'}"])
        check("an exact grant does not bless every nested package directory",
              verdict is not None and verdict.target == str(nested), repr(verdict))
        with tempfile.TemporaryDirectory() as ambient:
            exported = f"export PYTHONPATH={shlex.quote(ambient)}; python3 -c 'import x'"
            verdict = signal(exported, tmp, scopes=[f"path:{root / 'granted'}"])
            check("an exported untrusted PYTHONPATH is not lost between segments",
                  verdict is not None and verdict.target == ambient, repr(verdict))
        check("pypy is an interpreter alias, not an unobserved Python runtime",
              signal("pypy3 probe.py", tmp) is not None)
        alias = root / "py"
        alias.symlink_to(sys.executable)
        check("a symlinked interpreter alias is resolved before matching",
              signal(f"{shlex.quote(str(alias))} probe.py", tmp) is not None)

    print("ACX-07 — non-shell events never parse stdin as a shell command")
    with tempfile.TemporaryDirectory() as tmp:
        class NoRead:
            def read(self, *args):
                raise AssertionError("stdin was read for a None command")

            def readline(self, *args):
                raise AssertionError("stdin was read for a None command")

        original_stdin = sys.stdin
        try:
            sys.stdin = NoRead()
            none_verdict = signal(None, tmp)
            event = gate.NormalizedEvent(
                tool="Edit", paths=[str(Path(tmp) / "ordinary.py")], command=None, cwd=tmp)
            profile = gate.HarnessProfile(member_id="acx", identity_path="")
            edit_verdict = gate.evaluate(event, profile, tmp, gate.AgentPolicy(member_id="acx"))
        finally:
            sys.stdin = original_stdin
        check("a direct None command returns without reading stdin", none_verdict is None)
        check("an Edit event with command=None keeps its ordinary verdict",
              edit_verdict.decision == "allow"
              and edit_verdict.rule != "runtime.python_ambient_import", repr(edit_verdict))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
