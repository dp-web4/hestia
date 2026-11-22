#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
GOVERNED = "plugins/_shared/hestia_gate_core.py"
NOTES = "notes.txt"


def load_module(path):
    spec = importlib.util.spec_from_file_location("reviewed_closure", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def put(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def payload(target):
    return f"--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-x\n+y\n"


def verdict(module, command, cwd):
    result = module.classify("Bash", {"command": command}, cwd=cwd)
    return result.classification, result.rule, result.resource


def report(name, command, classification, expected, proc, changed):
    if proc.returncode != 0 or not changed:
        status = "REAL_SHELL_FAIL"
    elif classification[0] != expected:
        status = "UNDERFLAG" if expected == "write" else "OVERFLAG"
    else:
        status = "PASS"
    print(f"{status} {name}: class={classification[0]} expected={expected} "
          f"rc={proc.returncode} changed={changed} resource={classification[2]!r}")
    print(f"  {command}")
    if proc.stderr:
        print(f"  stderr={proc.stderr.strip()!r}")
    return status


def run_command_case(module, parent, name, command, expected, target=GOVERNED):
    root = os.path.join(parent, name)
    os.makedirs(root)
    put(os.path.join(root, "source"), "y\n")
    put(os.path.join(root, target), "x\n")
    if target != NOTES:
        put(os.path.join(root, NOTES), "x\n")
    classification = verdict(module, command, root)
    proc = subprocess.run(["bash", "-c", command], cwd=root,
                          capture_output=True, text=True)
    with open(os.path.join(root, target), encoding="utf-8") as handle:
        changed = handle.read() == "y\n"
    return report(name, command, classification, expected, proc, changed)


def run_patch_case(module, parent, attached, shell_kind, work_kind):
    spelling = "attached" if attached else "separated"
    name = f"patch_{spelling}_{shell_kind}_shell_{work_kind}_work"
    root = os.path.join(parent, name)
    os.makedirs(os.path.join(root, "work"))
    put(os.path.join(root, "x.diff"), payload(NOTES if shell_kind == "benign" else GOVERNED))
    put(os.path.join(root, "work", "x.diff"),
        payload(NOTES if work_kind == "benign" else GOVERNED))
    put(os.path.join(root, "work", NOTES), "x\n")
    put(os.path.join(root, "work", GOVERNED), "x\n")
    directory = "-dwork" if attached else "-d work"
    command = f"patch -p1 {directory} -i x.diff"
    classification = verdict(module, command, root)
    proc = subprocess.run(["bash", "-c", command], cwd=root,
                          capture_output=True, text=True)
    expected_target = GOVERNED if work_kind == "governed" else NOTES
    with open(os.path.join(root, "work", expected_target), encoding="utf-8") as handle:
        changed = handle.read() == "y\n"
    expected = "write" if work_kind == "governed" else "none"
    return report(name, command, classification, expected, proc, changed)


def run_relative_cd_case(module, parent, tool, form):
    name = f"relative_cd_{tool}_{form}"
    root = os.path.join(parent, name)
    process = os.path.join(root, "process")
    shell = os.path.join(root, "shell")
    for directory, target in ((process, NOTES), (shell, GOVERNED)):
        put(os.path.join(directory, "sub", "x.diff"), payload(target))
    put(os.path.join(shell, "sub", GOVERNED), "x\n")
    put(os.path.join(shell, "sub", NOTES), "x\n")
    if tool == "git":
        command = "cd sub && git apply" + (" < x.diff" if form == "stdin" else " x.diff")
    else:
        command = "cd sub && patch -p1" + (" < x.diff" if form == "stdin" else " -i x.diff")
    previous = os.getcwd()
    try:
        os.chdir(process)
        classification = verdict(module, command, shell)
    finally:
        os.chdir(previous)
    proc = subprocess.run(["bash", "-c", command], cwd=shell,
                          capture_output=True, text=True)
    with open(os.path.join(shell, "sub", GOVERNED), encoding="utf-8") as handle:
        changed = handle.read() == "y\n"
    return report(name, command, classification, "write", proc, changed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    args = parser.parse_args()
    module_path = os.path.abspath(args.module)
    with open(module_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print(f"module={module_path}")
    print(f"sha256={digest}")
    module = load_module(module_path)
    artifact_dir = os.path.dirname(os.path.abspath(__file__))
    statuses = []
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=artifact_dir) as parent:
        for tool in ("cp", "install", "rsync", "ln"):
            if shutil.which(tool) is None:
                print(f"SKIP trailing_comment_{tool}: executable unavailable")
                continue
            prefix = {"ln": "ln -f", "rsync": "rsync -c"}.get(tool, tool)
            command = f"{prefix} source {GOVERNED} # -t /tmp"
            statuses.append(run_command_case(module, parent, f"trailing_comment_{tool}",
                                             command, "write"))
        for attached in (True, False):
            for shell_kind, work_kind in (("benign", "governed"),
                                          ("governed", "benign")):
                statuses.append(run_patch_case(module, parent, attached,
                                               shell_kind, work_kind))
        for tool in ("git", "patch"):
            for form in ("stdin", "operand"):
                statuses.append(run_relative_cd_case(module, parent, tool, form))
        root = os.path.join(parent, "resource_contract")
        os.makedirs(os.path.join(root, "sub"))
        command = f"cd sub && cp source {GOVERNED}"
        results = module.write_verdicts("Bash", {"command": command}, cwd=root)
        resource = results[0].resource if results else None
        expected = f"sub/{GOVERNED}"
        status = "PASS" if resource == expected else "RESOURCE_REGRESSION"
        print(f"{status} resource_contract: resource={resource!r} expected={expected!r}")
        statuses.append(status)
    failures = [status for status in statuses if status != "PASS"]
    print(f"summary: cases={len(statuses)} mismatches={len(failures)} "
          f"statuses={sorted(set(statuses))}")


if __name__ == "__main__":
    main()
