#!/usr/bin/env python3
"""The classifier against REAL BASH: everything bash executes, the gate must classify.

WHY A DIFFERENTIAL AND NOT MORE ROWS
------------------------------------
`gate_false_refusal_test.py` is a corpus: every row is a shape someone was bitten by or
argued about. It is the right instrument for a known defect and the wrong one for a
tokenizer, because a tokenizer's failures are in the shapes nobody thought to write down.
The newline hole is the proof — `_SEPARATORS` listed `"\n"` from the day it was written,
the corpus had `multiline_reads` PASSING beside it, and the hole still lived for however
long the set had existed. The corpus said "multi-line commands are fine" and it was right;
it just had no way to say WHY they were fine, and the why was "line two was absorbed as
argv", not "line two was classified".

So this file asks the only question that does not depend on anyone's imagination:

    for a generated command, does bash EXECUTE the payload position?
    if yes, the gate MUST NOT call that command read-only.

Ground truth comes from running bash. The gate never runs anything.

THE ASYMMETRY, STATED
---------------------
`bypass` (bash runs it, gate permits it) is a hole in the gate's self-protection and this
file FAILS on a single one. Before `_command_lines` landed on 2026-08-10 the count was
712 of 1088 live cases; it is 0 now, and that pair of numbers is the only summary of the
newline hole that does not depend on which shapes anyone thought to write down.

The opposite sign is NOT asserted as zero, because bash declines to run a payload for
reasons the gate cannot see and must not model. Three partitions, each counted and printed
rather than failed, and each with a stated reason:

  - CONDITIONAL (`&&`, `||`) — `echo x || touch f` runs nothing here only because `echo`
    succeeded. Measured with a failing left side, the payload runs. A classifier that
    permitted these would be reading exit statuses it does not have.
  - UNPARSEABLE — bash -n itself rejects it (the generator produces `\n;` by accident).
    These get their own assertion in the other direction instead: the classifier's docstring
    rules that unknown syntax is a write, so a command bash cannot parse must not be
    permitted.
  - HEAD ALLOWLIST — the payload became argv to a head like `:` that is absent from
    `_READ_ONLY_HEADS`, so the refusal is not the parser's. Verified parser-independent
    before being excused (see `_EXPLAINED_BY_HEAD_ALLOWLIST`), and the members are named
    individually so a new arrival cannot hide inside a count.

What IS asserted on that side: an inert payload in NONE of those three. There the text was
swallowed — by the comment rule, or by heredoc body handling — and refusing it means
refusing text bash never treats as a command at all. That is a real false refusal, and the
assertion is emptiness rather than a threshold.

HOW THE FIRST VERSION OF THIS FILE WAS WRONG, kept because it is the same bug one layer up
------------------------------------------------------------------------------------------
Liveness was originally `"DANGER_RAN" in stdout`, with the payload `echo DANGER_RAN`. It
reported 65 bypasses, all false. When a wrapper absorbs the payload as ARGV to a leading
`echo` — which is exactly what a line continuation does — `echo` PRINTS the payload text
without executing it, and a stdout probe cannot tell printed from executed. That is the
defect under repair, wearing the instrument's clothes: absorbed-as-argument read as
happened. Liveness is now a FLAG FILE existing, which only an executed command can create.

Safety of running generated shell: every payload is `touch <flag>` inside a fresh temp dir,
and no generated wrapper contains an output redirect, so nothing outside that dir is
writable by this test. The gated spelling — `cp evil.py <gate>` — is classified and NEVER
run.
"""

import functools
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
HOOK = os.path.join(REPO, "plugins", "claude-code", "hooks", "pre_tool_use.py")
# The seat resolves shared law ONLY from an explicit HESTIA_SHARED_DIR or the installed
# engine (#747); the tree is no longer an implicit fallback. This names the reviewed tree
# under test explicitly: a fixture, chosen and visible, not an authority fallback.
os.environ.setdefault("HESTIA_SHARED_DIR", os.path.join(REPO, "plugins", "_shared"))

FAILURES = []
SKIPPED = []
_BARE = False


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
        return True
    FAILURES.append(name)
    print(f"  FAIL  {name}  {detail}")
    return False


def skip(name, why):
    """A check that could not run HERE — recorded, never counted as a pass."""
    print(f"  skip  {name}  ({why})")
    SKIPPED.append(f"{name}: {why}")


def asserting(fn):
    """Deliver failures to pytest as exceptions and to the bare runner as a full table.

    Same snapshot-and-delta as `gate_false_refusal_test.py:asserting`, and adopted here
    because `tools/ci_selfexec_test.py` flagged the first draft of this file for exactly the
    defect that guard exists to catch: `check()` appended to `FAILURES`, `FAILURES` was read
    only inside `__main__`, and under `python3 -m pytest` the checks would record and return
    normally while pytest printed PASSED. A test whose failures reach one invocation only.

    Worth recording that the repo's own guard caught it, since this file's subject is
    instruments that report a green they have not measured — and the first draft was one.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        before = len(FAILURES)
        result = fn(*args, **kwargs)
        new = FAILURES[before:]
        if new and not _BARE:
            raise AssertionError(
                f"{len(new)} check(s) failed in {fn.__name__}: {new}. "
                f"Run `python3 {os.path.relpath(__file__, REPO)}` from the repo root for "
                f"the full detail lines — that is how CI invokes it.")
        return result
    return wrapper


def _load_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# Left-hand sides. Each is read-only on its own, and each carries one construct that has
# historically confused the tokenizer: an unquoted mid-word `#` (bash: literal), a word-start
# `#` (bash: comment), quoted separators, an escaped `#`, a real newline inside quotes.
_PRE = [
    "echo checking",
    "echo a#b",
    "echo a # note",
    "echo 'q;x'",
    'echo "d;x"',
    "echo a\\#b",
    "cd /tmp",
    ":",
    "echo '#'",
    'echo "#"',
    "echo x#",
    "grep -c def {g}",
    "echo 'multi\nline'",
    'echo "multi\nline"',
    "echo tab\there",
    "echo trail  ",
]

# The joins. This is where the hole lived: any of these that bash honours as a command
# boundary must produce a boundary in the token stream too.
_SEP = [
    "\n", ";", "\n\n", " ; ", "\r\n", " &&\n", "\n# note\n", " # note\n",
    "\n   ", ";#c\n", " \\\n", "\n\\\n", " |\n", "&\n", "\n#\n", "  #x\n",
    "\n\t", " || \n", "\n;", ";\n",
]

_POST = ["", "\n", " # trailing", "\n# trailing"]

# Inert-and-refused cases that are NOT false refusals: bash declined to run the payload
# because of a conditional operator whose outcome depends on an exit status the gate cannot
# see. Refusing these is correct — `echo x || touch f` runs the touch the moment the left
# side fails (measured 2026-08-10 with a failing `grep`), so the gate must treat the payload
# as live regardless of how this particular left side happened to exit.
_CONDITIONAL = ("&&", "||")

# Left-hand sides whose inert-and-refused cases are a HEAD ALLOWLIST gap, not a parser one,
# and are therefore explained rather than failed. Named individually so a new arrival cannot
# hide inside a count.
#
# `:` — the null command. `: touch f` runs nothing (bash absorbs the rest as argv to a
# builtin that ignores it), and the gate refuses because `:` is absent from
# `_READ_ONLY_HEADS`. MEASURED as parser-independent 2026-08-10, three ways: the same refusal
# on ONE line (`: touch f`), the same refusal on the pre-`_command_lines` gate, and the same
# refusal with a plainly read-only payload (`: cat /etc/hostname`). Adding `:` to the bare set
# is a WIDENING of what the gate permits, which needs its own claim and its own NOT-SAME
# review; it is not smuggled in beside a hole fix. Left here as an accurate, cheap record of
# where the line is.
_EXPLAINED_BY_HEAD_ALLOWLIST = {":"}


def _cases():
    for pre, sep, post in itertools.product(_PRE, _SEP, _POST):
        yield pre.format(g=HOOK), sep, post


@asserting
def test_bash_executes_nothing_the_gate_calls_read_only():
    if not shutil.which("bash"):
        skip("bash_differential", "no bash on this host; ground truth is unobtainable")
        return
    mod = _load_gate()
    tmp = tempfile.mkdtemp(prefix="gate-differential-")
    flag = os.path.join(tmp, "ran.flag")
    live = inert = bypass = unparseable = head_allowlist_refusals = 0
    swallowed_refusals = []
    unparseable_permitted = []
    conditional_refusals = 0
    try:
        for pre, sep, post in _cases():
            probe = f"{pre}{sep}touch {flag}{post}"
            gated = f"{pre}{sep}cp evil.py {HOOK}{post}"
            if os.path.exists(flag):
                os.unlink(flag)
            try:
                subprocess.run(["bash", "-c", probe], capture_output=True, text=True,
                               timeout=10, cwd=tmp)
            except subprocess.TimeoutExpired:
                continue
            ran = os.path.exists(flag)
            permitted = mod._is_read_only("Bash", {"command": gated})
            parses = subprocess.run(["bash", "-n", "-c", gated],
                                    capture_output=True).returncode == 0
            if not parses:
                unparseable += 1
                if permitted is True:
                    unparseable_permitted.append(gated)
                continue
            if ran:
                live += 1
                if permitted is True:
                    bypass += 1
                    if bypass <= 6:
                        print(f"        bypass: {probe!r}")
            else:
                inert += 1
                if permitted is not True:
                    if any(op in sep or op in post for op in _CONDITIONAL):
                        conditional_refusals += 1
                    elif pre in _EXPLAINED_BY_HEAD_ALLOWLIST:
                        head_allowlist_refusals += 1
                    else:
                        swallowed_refusals.append(probe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"        {live + inert + unparseable} generated commands: {live} executed the "
          f"payload under bash, {inert} parsed and did not, {unparseable} bash itself "
          f"refuses to parse")
    print(f"        {conditional_refusals} inert-and-refused via &&/|| (correct: "
          f"conditionally live), {head_allowlist_refusals} via a head outside the "
          f"allowlist (not the parser)")

    # THE PROPERTY. One is a hole in the gate's self-protection, so the bar is zero, not
    # a ratio. Before `_command_lines` landed (2026-08-10) this number was 712 of 1088.
    check("no_bypass__bash_runs_it_and_the_gate_permits_it",
          bypass == 0,
          f"{bypass} of {live} commands bash EXECUTES are classified read-only, so the "
          f"gate would let a `cp` onto its own source through. Each printed above is a "
          f"live protection hole, not classifier noise")

    # The other sign, pinned rather than asserted-zero. A refusal here means the gate is
    # refusing text bash does not treat as a command — swallowed by a comment or by heredoc
    # body handling — with no conditional operator to justify it.
    # The gate's own doctrine, made testable: "Unparseable input is a write. Unknown syntax
    # is a write." If bash -n will not parse it, nobody knows what it runs, and the one
    # answer that cannot be wrong is refuse. Free to check here — the generator produces
    # these by accident (a `;` alone at the start of a line) rather than by design, which is
    # the only reason this corner is covered at all.
    check("bash_cannot_parse_it_so_the_gate_must_not_permit_it",
          not unparseable_permitted,
          f"{len(unparseable_permitted)} command(s) bash -n rejects are classified "
          f"read-only: {unparseable_permitted[:3]}. The classifier's docstring rules that "
          f"unknown syntax is a write; these got a verdict instead of a refusal")

    check("no_unexplained_refusal_of_text_bash_never_runs",
          not swallowed_refusals,
          f"{len(swallowed_refusals)} command(s) whose payload bash never runs, and with "
          f"no &&/|| to make it conditionally live, are refused: "
          f"{swallowed_refusals[:4]}. Either the comment rule in `_command_lines` is "
          f"eating less than bash does, or a new construct needs handling there")


def teardown_module(module):
    """Deliver the skip record to pytest — same reason as gate_false_refusal_test.py.

    A host with no bash records a skip and returns; under pytest that read as PASSED for a
    check that never ran. The property to assert is DELIVERY, not emptiness: a host without
    bash is an environment, not a defect, and failing there would price the environment.
    """
    for s in SKIPPED:
        warnings.warn(f"check not run on this host: {s}", stacklevel=1)


if __name__ == "__main__":
    _BARE = True
    print("gate vs bash — differential")
    test_bash_executes_nothing_the_gate_calls_read_only()
    print()
    if SKIPPED:
        print(f"NOT MEASURED HERE: {len(SKIPPED)}")
        for s in SKIPPED:
            print(f"  - {s}")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print(f"all checks pass ({len(SKIPPED)} skipped)" if SKIPPED else "all checks pass")
