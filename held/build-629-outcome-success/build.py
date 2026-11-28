#!/usr/bin/env python3
"""Build the held patch for hestia #629: explicit exit statuses are outcome evidence.

argv: <hestia worktree at the base> <out dir>
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_witness_core.py"
TEST = "plugins/_shared/hestia_witness_core_test.py"
GT = "hooks-gt/_shared/hestia_witness_core.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    src = once(src, """import os
import sys
""", """import os
import re
import sys
""")
    return once(src, '''def derive_success(event: dict) -> tuple[bool, Optional[str]]:
    """Best-effort success flag across the harnesses' outcome shapes."""
    forced = OUTCOME_EVENTS.get(event.get("hook_event_name"))
    if forced is False:  # kimi's PostToolUseFailure: the event IS the failure
        err = event.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        return False, str(err or "tool error")[:500]
    resp = event.get("tool_response")
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError"):
            err = resp.get("error") or resp.get("message") or "tool error"
            return False, str(err)[:500]
        if resp.get("error"):  # gemini's AfterTool carries a populated `error` on failure
            err = resp["error"]
            if isinstance(err, dict):
                err = err.get("message") or json.dumps(err)
            return False, str(err)[:500]
    return True, None
''', '''_EXIT_CODE_KEYS = ("exit_code", "exitCode", "returncode", "return_code")


def _exit_status(value) -> Optional[int]:
    """A numeric process status, never a boolean or arbitrary output text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


_SHELL_RESULT_TOOLS = frozenset({"Bash", "Shell", "run_shell_command", "shell", "exec_command", "bash"})
_SHELL_EXIT_RE = re.compile(r"^Exit [Cc]ode: (\\d+)\\s*$", re.MULTILINE)


def _rendered_exit_status(tool_name, response) -> Optional[int]:
    """Read a shell tool's labeled result footer, never an arbitrary number in its output.

    The last label wins: the tool's own footer follows anything the command printed.
    """
    if tool_name not in _SHELL_RESULT_TOOLS:
        return None
    candidates = [response] if isinstance(response, str) else [
        response.get(key) for key in ("llmContent", "returnDisplay")
    ] if isinstance(response, dict) else []
    for text in candidates:
        if not isinstance(text, str):
            continue
        matches = _SHELL_EXIT_RE.findall(text)
        if matches:
            return int(matches[-1])
    return None


def derive_success(event: dict) -> tuple[bool, Optional[str]]:
    """Best-effort success flag across the harnesses' outcome shapes.

    An explicit nonzero process status is a failed act even when the tool envelope itself was
    well formed. Missing status evidence keeps the legacy best-effort answer. Only a documented
    shell result's labeled exit footer is parsed; arbitrary output text is not searched.
    """
    forced = OUTCOME_EVENTS.get(event.get("hook_event_name"))
    if forced is False:  # kimi's PostToolUseFailure: the event IS the failure
        err = event.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        return False, str(err or "tool error")[:500]
    resp = event.get("tool_response")
    if isinstance(resp, str):
        try:
            decoded = json.loads(resp)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            resp = decoded
    statuses = []
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError"):
            err = resp.get("error") or resp.get("message") or "tool error"
            return False, str(err)[:500]
        if resp.get("error"):  # gemini's AfterTool carries a populated `error` on failure
            err = resp["error"]
            if isinstance(err, dict):
                err = err.get("message") or json.dumps(err)
            return False, str(err)[:500]
        for key in _EXIT_CODE_KEYS:
            status = _exit_status(resp.get(key))
            if status is None:
                continue
            statuses.append(status)
            if status != 0:
                err = resp.get("stderr") or resp.get("message")
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err)
                detail = f": {err}" if err else ""
                return False, f"exit status {status}{detail}"[:500]
        if resp.get("interrupted") is True:
            return False, "tool interrupted"
    rendered = _rendered_exit_status(event.get("tool_name"), resp)
    if rendered:
        return False, f"exit status {rendered}"
    if rendered == 0 or 0 in statuses:
        return True, None
    return True, None
''')


def patch_test(src):
    src = once(src, """    check("B a non-outcome event is not witnessed", core.intent_from({"hook_event_name": "SessionStart"}) is None)
""", """    for name, response, status in (
            ("snake-case", {"exit_code": 1, "stderr": "deliberate failure"}, 1),
            ("camel-case", {"exitCode": 124, "stderr": "deliberate failure"}, 124),
            ("numeric-string", {"returncode": "127", "stderr": "deliberate failure"}, 127),
            ("json-response", json.dumps({"return_code": 2, "stderr": "deliberate failure"}), 2)):
        failed = core.intent_from({**P["claude-code"][1], "tool_response": response})
        check(f"B explicit nonzero status is failure: {name}",
              failed and failed["success"] is False
              and failed["error"] == f"exit status {status}: deliberate failure", json.dumps(failed))
    for name, event, response in (
            ("gemini-content", P["gemini"][1],
             {"llmContent": "Command: false\\nExit Code: 1\\nSignal: (none)"}),
            ("gemini-display", P["gemini"][1], {"returnDisplay": "Exit Code: 1"}),
            ("codex-string", P["codex"][1], "Exit Code: 1")):
        rendered = core.intent_from({**event, "tool_response": response})
        check(f"B documented shell footer is failure: {name}",
              rendered and rendered["success"] is False
              and rendered["error"] == "exit status 1", json.dumps(rendered))
    final_zero = core.intent_from({**P["codex"][1], "tool_response": "Exit Code: 1\\nExit Code: 0"})
    check("B the final shell footer controls, not command output",
          final_zero and final_zero["success"] is True, json.dumps(final_zero))
    unlabelled = core.intent_from({**P["codex"][1], "tool_response": "exit status 1"})
    check("B arbitrary output is not parsed for a status",
          unlabelled and unlabelled["success"] is True, json.dumps(unlabelled))
    zero = core.intent_from({**P["claude-code"][1],
                             "tool_response": {"exit_code": 0, "stderr": "warning only"}})
    check("B zero status with stderr is still success",
          zero and zero["success"] is True and zero["error"] is None, json.dumps(zero))
    boolean = core.intent_from({**P["claude-code"][1], "tool_response": {"exit_code": False}})
    check("B a boolean is not a process status",
          boolean and boolean["success"] is True, json.dumps(boolean))
    interrupted = core.intent_from({**P["claude-code"][1], "tool_response": {"interrupted": True}})
    check("B an interrupted act is failure",
          interrupted and interrupted["success"] is False
          and interrupted["error"] == "tool interrupted", json.dumps(interrupted))
    legacy = core.intent_from(P["claude-code"][1])
    check("B missing status evidence keeps the legacy answer",
          legacy and legacy["success"] is True and legacy["error"] is None, json.dumps(legacy))
    check("B a non-outcome event is not witnessed", core.intent_from({"hook_event_name": "SessionStart"}) is None)
""")
    return once(src, """        print("D. control: without the key the gate caches nothing and the witness goes cold")
""", """        print("C2. a top-level nonzero exit reaches the outcome record on every harness")
        for member, (pre, post) in P.items():
            daemon.calls.clear()
            core.configure(plugin_id=member)
            verdict = mech.query_society_safety(
                pre, plugin_id=member, host_agent=member, host_session_id=pre.get("session_id"),
                correlation_key=mech.correlation_key(pre))
            gated = verdict.action_id
            failed = {**post, "tool_response": {"exit_code": 1, "stderr": "deliberate failure"}}
            if member == "kimi-code":
                failed["hook_event_name"] = "PostToolUse"
                failed.pop("error", None)
            if member == "gemini":
                failed["tool_response"] = {"llmContent": "Command: false\\nExit Code: 1"}
            want_error = "exit status 1" if member == "gemini" else "exit status 1: deliberate failure"
            daemon.calls.clear()
            core.run(failed)
            recs = daemon.named("hestia_record_outcome")
            check(f"C2 {member}: exit 1 closes the gate's action as a failure",
                  len(recs) == 1 and recs[0].get("action_id") == gated
                  and recs[0].get("success") is False
                  and recs[0].get("error") == want_error,
                  json.dumps(daemon.calls))

        print("D. control: without the key the gate caches nothing and the witness goes cold")
""")


def diff(path, old, new):
    hdr = f"diff --git a/{path} b/{path}\n"
    return hdr + "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def hunks(section):
    out, cur = [], None
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))?", line)
            cur = {"start": int(m.group(1)) - 1, "old": [], "new": []}
            out.append(cur)
        elif cur is not None and line[:1] in " +-" and not line.startswith(("--- ", "+++ ")):
            if line[0] in " -":
                cur["old"].append(line[1:])
            if line[0] in " +":
                cur["new"].append(line[1:])
    return out


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True)
    out, pos = [], 0
    for h in hunks(section):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0)
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core = patch_core(blob(CORE))
    test_new = patch_test(blob(TEST))
    (OUT / "hestia_witness_core.py").write_text(core, encoding="utf-8")
    (OUT / "hestia_witness_core_test.py").write_text(test_new, encoding="utf-8")
    (OUT / "hestia_single_gate.py").write_text(blob("plugins/_shared/hestia_single_gate.py"), encoding="utf-8")
    (OUT / "RUNTIME_MANIFEST.txt").write_text(blob("plugins/_shared/RUNTIME_MANIFEST.txt"), encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    src_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return core.encode() if self.resolve() == src_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(CORE, blob(CORE), core) + gt_out.read_text(encoding="utf-8") + diff(TEST, blob(TEST), test_new)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")
    for path, sec in sections(body).items():
        got = strict_apply(blob(path), sec)
        want = core if path == CORE else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree[GT]) == core.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
