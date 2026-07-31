#!/usr/bin/env python3
r"""Fidelity model of gemini-cli's hook-result parser: what does the RUNNER decide?

Why this exists: every gemini gate test so far asserted the gate's **exit code**, which was a fine
proxy only while "non-zero == deny" was the whole contract. It is not the contract - it is one branch
of it. The runner's actual decision is a function of (exit_code, stdout, stderr) together, and there
are shapes where the exit code and the decision disagree in both directions:

  - exit 2 with EMPTY output   -> no decision object at all -> the tool RUNS (a fail-open the
    exit-code assertion cannot see: the test passes, the gate leaks);
  - exit 0 with stdout JSON `{"decision":"deny"}` -> the tool is BLOCKED (an exit-code assertion
    reads this as "allow" and fails a correct gate).

So tests assert THIS function, not the exit code. Transcribed from the installed bundle of
gemini-cli 0.52.0 (`bundle/chunk-7LQRUKPT.js`, the `child.on("close")` handler +
`convertPlainTextToHookOutput` + `HookAggregator.mergeWithOrDecision`); the upstream sources are
`packages/core/src/hooks/hookRunner.ts` and `hookAggregator.ts`. Re-derive it if the CLI is upgraded:
`grep -o 'convertPlainTextToHookOutput.\{0,900\}' bundle/chunk-*.js`.

Usage (library):   decide(exit_code, stdout, stderr) -> ("allow"|"deny"|"ask", reason, banner)
Usage (CLI):       runner_decision.py <exit_code> <stdout_file> <stderr_file>   # prints e.g. "deny 0"
                   -> field 1 = decision, field 2 = 1 if the operator sees the yellow
                      "Hook(s) [...] failed" banner, else 0.
"""
import json
import sys

EXIT_CODE_SUCCESS = 0
EXIT_CODE_NON_BLOCKING_ERROR = 1


def _convert_plain_text(text, exit_code):
    """hookRunner.convertPlainTextToHookOutput - the non-JSON fallback.

    Note the asymmetry that decides our deny channel: the SAME unparseable text is an ALLOW at
    exit 0 and a DENY at exit 2. Corruption of a deny payload therefore fails OPEN on the exit-0
    path and CLOSED on the exit-2 path.
    """
    if exit_code == EXIT_CODE_SUCCESS:
        return {"decision": "allow", "systemMessage": text}
    if exit_code == EXIT_CODE_NON_BLOCKING_ERROR:
        return {"decision": "allow", "systemMessage": "Warning: " + text}
    return {"decision": "deny", "reason": text}


def decide(exit_code, stdout, stderr):
    """Return (decision, reason, banner) for one hook result on a BeforeTool event.

    `banner` is the operator-facing yellow "Hook(s) [...] failed for event BeforeTool" warning, which
    `logHookExecution` emits whenever a hook result has success == false, and per-result
    `success = (exit_code == 0)`. It is a UI feedback event ("user-feedback"), NOT model context - it
    never reaches the model, so it is a signal-quality question, not a safety one.
    """
    banner = exit_code != EXIT_CODE_SUCCESS
    # `const textToParse = stdout.trim() || stderr.trim()` - stdout WINS; stderr is read only when
    # stdout is empty. A stray print on stdout therefore shadows a stderr reason entirely.
    text = stdout.strip() or stderr.strip()
    output = None
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):      # the runner double-parses a JSON string
                parsed = json.loads(parsed)
            if isinstance(parsed, dict):     # arrays/numbers fall through to `output = undefined`
                output = parsed
        except Exception:
            output = _convert_plain_text(text, exit_code)
    if output is None:
        # No output object -> mergeOutputs([]) -> undefined -> nothing blocks. The tool RUNS.
        return "allow", "", banner
    decision = output.get("decision")
    if decision in ("block", "deny"):        # isBlockingDecision()
        return "deny", output.get("reason") or "", banner
    if decision == "ask":                    # isAskDecision()
        return "ask", output.get("reason") or "", banner
    return "allow", output.get("systemMessage") or "", banner


def main():
    if len(sys.argv) != 4:
        sys.stderr.write(__doc__)
        return 2
    code = int(sys.argv[1])
    out = open(sys.argv[2], encoding="utf-8", errors="replace").read()
    err = open(sys.argv[3], encoding="utf-8", errors="replace").read()
    decision, _reason, banner = decide(code, out, err)
    print(f"{decision} {1 if banner else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
