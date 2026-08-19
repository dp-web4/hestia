#!/usr/bin/env python3
"""Discriminating arms for the governance closure: heredoc bodies, fd digits, out-of-grammar.

WHY THIS FILE IS IN tools/ AND NOT BESIDE THE MODULE IT TESTS
--------------------------------------------------------------
Every other closure suite lives in `plugins/_shared/`. This one cannot, and the reason
is the closure's own design, working as intended:

    LITERAL_FLOOR.dir_markers carries ("plugins", "_shared") — "a NEW file dropped beside
    the core is a closure write" — so `plugins/_shared/<anything>_test.py` is a governance
    write for EVERY member, refused, escalation-only.

That marker is correct and should stay. A file in that directory sits on `sys.path` for
the closure's own importers and is executed by the `plugin tests (python)` job, so it is
an import-shadowing surface and a code-execution surface inside the protected tree. There
is no safe "tests are exempt" carve-out: `*_test.py` cannot shadow a stdlib name, but it
IS run by CI, and that is enough.

The consequence, stated plainly because it is a governance fact and not a detail: the
closure's regression suite can only be EXTENDED by an operator-approved write. Coverage of
the gate grows at the pace of a human decision channel, and the defects hardest to pin are
exactly the gate's own. The cheap remedy is this file's placement — `tools/ci_discovery.py`
discovers by NAME, from `git ls-files`, not by location, so a suite here is run by the same
job with the same bare `python3 F` as one in the protected directory. Nothing is worked
around: the closure is not written, only imported, and importing is a READ, which the rule
allows and witnesses. The eleven suites already inside `plugins/_shared/` are unaffected —
and un-extendable by any member.

WHAT IS PINNED, AND WHICH DIRECTION EACH ARM MOVES
---------------------------------------------------
Measured 2026-08-19 against three closures, same probe, neutral cwd, LITERAL_FLOOR:

    baseline  origin/main  fcb91ab  (module blob 323c13b2)          5/8 on the first eight
    fix       #538         8c6edd2  heredoc-line-aware + fd-digit    8/8
    sibling   #534         6924914  bare-digit-is-a-file-descriptor  5/8

  DISCRIMINATORS — baseline and #534 disagree with #538; this suite sides with #538
    B   shell keyword in a quoted heredoc body   baseline write -> read   FP: over-refusal
    E   redirect quoted in a heredoc body        baseline write -> read   FP: over-refusal
    K   `cp SRC <core> 2>/dev/null`              baseline read  -> write  DOOR: under-refusal

  CONTROLS — identical on all three; the fix must not move them
    A   prose body naming the marker                         read   (+ benign twin: none)
    I   write on the heredoc operator's line                 write  (+ benign twin: none)
    J   write after the terminator line                      write  (+ benign twin: none)
    K2  `cp SRC /tmp/x/ 2>/dev/null`                         none
    L   `echo x 2> <core>`                                   write

  SUBSUMPTION — the six rows of #534's own PR table, reproduced. #534 and #538 agree on
    all six; #538 additionally closes arm K, which #534 leaves open. Landing both leaves
    #534's in-branch fd-skip unreachable, because #538 pops the digit earlier. These arms
    exist so that claim is a test rather than a paragraph.

  OPEN DEFECT PINS — green on ALL THREE closures, including the fix. TWO independent
    out-of-grammar over-refusal classes, neither closed by #538. Both share a shape: once
    ANYTHING throws the command out of grammar, the ENTIRE token vocabulary is matched
    under the broader rules, and a quoted heredoc body stops being inert. The body is
    never the trigger — with the trigger removed, the identical body is a read.

    FP12  a control-flow keyword anywhere in the command flips it out of grammar, so a
          plain READ of the closure is refused as a write. Not fixed by #538. Pinned at
          the CURRENT (wrong) verdict so the suite is green; a RED here means someone
          repaired it and this arm should be inverted, not deleted. Encountered live
          while building this file: `for w in A B; do PYTHONPATH=$w/<dir> ...; done` was
          refused, and the same command un-looped was allowed. The benign twin (a loop
          naming no closure vocabulary) stays "none", so the trigger is keyword + marker,
          not the keyword alone. NOTE the near-miss: the `$VAR` assignment is NOT the
          cause — rows for `ASSIGN=$VAR/<dir>` and `ASSIGN=/literal/<dir>` are both
          "read". Blaming the assignment would have mis-filed this as FP13.

    OOG   a substitution in a WRITE POSITION (`cat > $V/a.md`) does the same, and this one
          has a price on record: it refused a note ABOUT the gate whose destination path
          was built from a variable, and opened escalation 28b6bc2af908e148 for an
          operator to decide. Paired control run 5 minutes apart at the time: identical
          body, literal destination, allowed. A variable in an assignment VALUE or in a
          READ position is also allowed — it is the write position specifically.

Arms I, J and K carry BENIGN TWINS in the same assertion. Without them each would be
satisfied by a classifier that answers "write" to anything naming a marker — which the
baseline very nearly is, so a suite of over-refusal arms alone would be a one-way gradient
that a more-refusing classifier always passes.

Basenames are assembled from fragments (house convention, plugins/_shared/shell_grammar_test.py):
this file's own text would otherwise be closure vocabulary to the gate that reads it.
Pinned to LITERAL_FLOOR and a neutral temp cwd — the live registry is nondeterministic and
classification is cwd-sensitive by design.

check() RAISES so a pytest runner sees each case; __main__ collects and refuses a
zero-case run (house convention: an empty collection must not read as a pass).

Run:  ./tools/governance_closure_arms_test.py
"""

import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "plugins", "_shared"))
import hestia_governance_closure as g  # noqa: E402

FLOOR = g.LITERAL_FLOOR

CORE = "hestia_gate_" + "core.py"
SHARED_DIR = "plugins/" + "_shared"
MARK = SHARED_DIR + "/" + CORE
BENIGN = "/tmp/benign.txt"

_NEUTRAL_CWD = tempfile.mkdtemp(prefix="closure-arms-neutral-")
_BENIGN_PATCH = os.path.join(_NEUTRAL_CWD, "benign.patch")
_CLOSURE_PATCH = os.path.join(_NEUTRAL_CWD, "closure.patch")

with open(_BENIGN_PATCH, "w", encoding="utf-8") as fh:
    fh.write("--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-x\n+y\n")
with open(_CLOSURE_PATCH, "w", encoding="utf-8") as fh:
    fh.write("--- a/" + MARK + "\n+++ b/" + MARK + "\n@@ -1 +1 @@\n-x\n+y\n")


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def cls(cmd):
    return g.classify(
        "Bash", {"command": cmd}, cwd=_NEUTRAL_CWD, closure=FLOOR
    ).classification


def verdict(cmd):
    """classification/rule/resource — the three fields an escalation shows a human."""
    v = g.classify("Bash", {"command": cmd}, cwd=_NEUTRAL_CWD, closure=FLOOR)
    return (v.classification, v.rule, v.resource)


# ── DISCRIMINATORS ──────────────────────────────────────────────────────────────────────

def test_prose_body_naming_the_marker_is_read():
    """CONTROL — read on all three. Twin: a body naming nothing is none."""
    got = cls("cat > /tmp/a.md <<'EOF'\nthe marker is " + MARK + "\nEOF")
    check("A_prose_only", got == "read", f"a quoted body is data; got {got}")
    twin = cls("cat > /tmp/a.md <<'EOF'\nnothing here\nEOF")
    check("A_benign_twin", twin == "none", f"no marker, no closure read; got {twin}")


def test_shell_keyword_in_body_does_not_flip_out_of_grammar():
    """DISCRIMINATOR — baseline and #534: write. #538: read."""
    got = cls("cat > /tmp/a.md <<'EOF'\nfor x in 1 2; do echo $x; done\n"
              "the marker is " + MARK + "\nEOF")
    check("B_keyword_in_body", got == "read",
          f"a keyword in BODY TEXT must not flip the command out of grammar; got {got}")


def test_redirect_quoted_in_body_is_a_mention_not_a_write():
    """DISCRIMINATOR — baseline and #534: write. #538: read."""
    got = cls("cat > /tmp/a.md <<'EOF'\nthe probe was: echo x > " + MARK + "\nEOF")
    check("E_quoted_redirect_in_body", got == "read",
          f"a redirect QUOTED in body text is a mention; got {got}")


def test_write_on_the_operator_line_stays_visible():
    """CONTROL — write on all three, with benign twin.

    Verified in a real shell: the rest of a heredoc's operator line IS executed. A
    remedy that skips from the delimiter word to the terminator opens this as a live
    write door on the gate's own core.
    """
    got = cls("cat <<'A' ; echo x > " + MARK + "\nharmless\nA")
    check("I_write_same_line_as_op", got == "write",
          f"the rest of the operator line is executed; got {got}")
    twin = cls("cat <<'A' ; echo x > " + BENIGN + "\nharmless\nA")
    check("I_benign_twin", twin == "none",
          f"benign target is not a closure write; got {twin}")


def test_write_after_the_terminator_stays_visible():
    """CONTROL — write on all three, with benign twin."""
    got = cls("cat <<'A'\nharmless\nA\necho x > " + MARK)
    check("J_write_after_close", got == "write",
          f"code after the terminator is executed; got {got}")
    twin = cls("cat <<'A'\nharmless\nA\necho x > " + BENIGN)
    check("J_benign_twin", twin == "none",
          f"benign target is not a closure write; got {twin}")


def test_fd_digit_does_not_displace_the_copy_destination():
    """DISCRIMINATOR and the door only #538 closes. Baseline and #534: read.

    The leading fd digit of `2>` lands in argv, becomes cp's last argument, and displaces
    the real destination out of the write position — so OVERWRITING the gate's own core is
    recorded as READING it. #534 fixes the same digit inside the `git apply` branch only;
    the cp/mv/install last-argument write position is untouched there.
    """
    got = cls("cp a.py " + MARK + " 2>/dev/null")
    check("K_fd_displaces_destination", got == "write",
          f"an fd digit must not displace the copy destination; got {got}")
    twin = cls("cp a.py " + MARK)
    check("K_no_redirect_twin", twin == "write",
          f"the same copy without a redirect is a write; got {twin}")


def test_fd_digit_does_not_manufacture_a_write():
    """CONTROL — none on all three; the fix must not over-fire."""
    got = cls("cp a.py /tmp/x/ 2>/dev/null")
    check("K2_benign_fd_prefix", got == "none",
          f"a benign copy with a stderr redirect names no closure; got {got}")


def test_fd_redirect_at_the_marker_is_a_write():
    """CONTROL — write on all three; dropping the fd digit must not drop the redirect."""
    got = cls("echo x 2> " + MARK)
    check("L_fd_redirect_to_marker", got == "write",
          f"fd 2 redirected AT the marker is a real write; got {got}")


# ── SUBSUMPTION: the six rows of #534's PR table ────────────────────────────────────────

def test_patch_writer_verdicts_are_decided_by_the_patch_not_the_fd():
    """#534's own table, all six rows. #534 and #538 agree; #538 also closes arm K.

    Row 2 is the load-bearing one: the baseline denied the CLOSURE case for the wrong
    reason — on the fd digit, never having read the patch. With a redirect present,
    `git apply` stopped being classified on content at all, so the false positive and the
    accidentally-correct true positive had one cause. A fix is only real if row 2 flips
    its REASON, not just its verdict; that is why this arm asserts rule and resource.
    """
    benign_pipe = verdict("git apply --3way " + _BENIGN_PATCH + " 2>&1 | tail -5")
    check("S1_benign_with_fd_and_pipe", benign_pipe[0] == "none",
          f"a benign patch is not a governance write; got {benign_pipe}")

    closure_pipe = verdict("git apply --3way " + _CLOSURE_PATCH + " 2>&1 | tail -5")
    check("S2_closure_patch_verdict", closure_pipe[0] == "write",
          f"a patch whose target is the closure is a write; got {closure_pipe}")
    check("S2_closure_patch_reason", closure_pipe[1] == g.RULE_WRITE,
          f"the reason must be the PATCH TARGET, not an opaque fd; got rule {closure_pipe[1]}")
    check("S2_closure_patch_resource", closure_pipe[2] and CORE in closure_pipe[2],
          f"the resource shown to a human must name the core, not a digit; got {closure_pipe[2]}")

    no_redirect = verdict("git apply --3way " + _BENIGN_PATCH)
    check("S3_benign_no_redirect", no_redirect[0] == "none",
          f"unchanged from baseline; got {no_redirect}")

    to_logfile = verdict("git apply " + _BENIGN_PATCH + " 2>" + _NEUTRAL_CWD + "/apply.log")
    check("S4_benign_fd_to_file", to_logfile[0] == "none",
          f"a stderr redirect to a file is not a patch target; got {to_logfile}")

    missing = verdict("git apply /tmp/does-not-exist-arms.patch 2>&1")
    check("S5_unreadable_patch_still_refused", missing[0] == "write",
          f"an unreadable patch has an unknowable write set and stays refused; got {missing}")
    check("S5_names_the_patch", missing[2] == "/tmp/does-not-exist-arms.patch",
          f"the refusal must name the patch it could not read; got {missing[2]}")

    on_pipe = verdict("git apply 2>&1")
    check("S6_content_on_stdin_refused", on_pipe[0] == "write",
          f"patch content arriving on a pipe is unknowable and refused; got {on_pipe}")
    check("S6_names_stdin_not_a_digit", on_pipe[2] == "stdin",
          f"the resource is stdin, not the fd digit; got {on_pipe[2]}")


# ── OPEN DEFECT PIN: green today on ALL THREE, including the fix ────────────────────────

def test_pin_a_control_flow_keyword_refuses_a_plain_read():
    """OPEN DEFECT, pinned at the WRONG verdict so this suite stays green.

    A RED here means someone repaired FP12. That is the good outcome: invert this arm to
    assert "read" and move it up into the discriminators. Do NOT relax the assertion to
    make it pass again.

    Encountered live 2026-08-19 while building this file, on a command that only READ the
    closure directory. Un-looped, the identical read is allowed — so the loop keyword is
    the whole cause.
    """
    looped = "for w in /tmp/a /tmp/b; do PYTHONPATH=$w/" + SHARED_DIR + " python3 t.py; done"
    got = verdict(looped)
    check("FP12_loop_over_refuses_a_read", got[0] == "write",
          "FP12 APPEARS FIXED — a loop naming the closure now classifies "
          f"{got[0]!r}. Invert this pin to assert 'read'; do not weaken it.")
    check("FP12_reason_is_out_of_grammar", got[1] == g.RULE_OUT_OF_GRAMMAR,
          f"the over-refusal should still be the grammar rule; got {got[1]}")

    twin = cls("for w in /tmp/a /tmp/b; do cat $w/readme; done")
    check("FP12_benign_twin", twin == "none",
          f"a loop naming no closure vocabulary must stay none; got {twin}")

    unlooped = cls("PYTHONPATH=$w/" + SHARED_DIR + " python3 t.py")
    check("FP12_unlooped_is_a_read", unlooped == "read",
          f"the same read without the loop is allowed; got {unlooped}")

    literal = cls("PYTHONPATH=/tmp/a/" + SHARED_DIR + " python3 t.py")
    check("FP12_assignment_is_not_the_cause", literal == "read",
          "a literal-valued assignment naming the closure is also a read — the $VAR is "
          f"not what triggers FP12; got {literal}")


def test_pin_a_variable_in_a_write_position_sweeps_in_a_quoted_body():
    """OPEN DEFECT, pinned at the WRONG verdict. Second out-of-grammar class, distinct
    from FP12 and also unfixed by #538.

    A substitution in a WRITE POSITION raises _OutOfGrammar in _flush_simple_command;
    classify() then matches the command's FULL token vocabulary under the broader rules.
    A quoted heredoc body — inert while the command is in grammar — becomes write-position
    vocabulary the moment the redirect target contains a $VAR.

    The heredoc is NOT the trigger and neither is the variable: with a literal destination
    the identical body is a read (arm A), and a variable in an ASSIGNMENT VALUE or a READ
    position is also a read. It is specifically a variable in a write position, and the
    body is only the payload that gets swept in.

    Recorded because it has a price: this exact shape — a note ABOUT the gate, written to
    a $VAR-built path — refused a documentation write and opened escalation
    28b6bc2af908e148, which an operator then had to decide.

    A RED here means someone repaired it. Invert the arm; do not weaken it.
    """
    body_mark = "\nthe marker is " + MARK + "\nEOF"
    body_none = "\nnothing to see here\nEOF"

    got = verdict("cat > $V/a.md <<'EOF'" + body_mark)
    check("OOG_var_dest_sweeps_quoted_body", got[0] == "write",
          "THE WRITE-POSITION-VARIABLE OVER-REFUSAL APPEARS FIXED — a quoted body under a "
          f"$VAR destination now classifies {got[0]!r}. Invert this pin to assert 'read'.")
    check("OOG_reason_is_out_of_grammar", got[1] == g.RULE_OUT_OF_GRAMMAR,
          f"the over-refusal should still be the grammar rule; got {got[1]}")

    literal_dest = cls("cat > /tmp/a.md <<'EOF'" + body_mark)
    check("OOG_literal_dest_is_a_read", literal_dest == "read",
          f"the PAIRED CONTROL: identical body, literal destination, allowed; got {literal_dest}")

    no_vocab = cls("cat > $V/a.md <<'EOF'" + body_none)
    check("OOG_benign_twin", no_vocab == "none",
          f"out-of-grammar alone must not refuse; it needs closure vocabulary; got {no_vocab}")

    argv_mention = cls("echo " + MARK + " > $V/a.md")
    check("OOG_not_heredoc_specific", argv_mention == "write",
          "the same sweep happens with the marker in plain argv and no heredoc at all — "
          f"the heredoc is the payload, not the trigger; got {argv_mention}")

    read_position = cls("cp $V/" + MARK + " /tmp/a.py")
    check("OOG_variable_in_read_position_is_a_read", read_position == "read",
          f"a variable in a READ position does not throw the command out of grammar; got {read_position}")


def test_every_case_in_this_file_is_in_ALL():
    """An explicit ALL satisfies tools/ci_selfexec_test.py, which refuses a `def test_*`
    that no Name node references — reflection over globals() is invisible to a static
    check, so a file collected that way reads as inert. Conforming to the house
    convention is right, but a hand-written list drifts the day someone adds a case and
    forgets, and then it is inert for real. This arm closes that: the list is the runner,
    and this compares the list against the module.
    """
    declared = {fn.__name__ for fn in ALL}
    defined = {n for n, o in globals().items() if n.startswith("test_") and callable(o)}
    missing = sorted(defined - declared)
    check("ALL_is_complete", not missing,
          f"defined but not in ALL, so never run: {missing}")
    stale = sorted(declared - defined)
    check("ALL_has_no_ghosts", not stale, f"in ALL but not defined: {stale}")


ALL = [
    test_prose_body_naming_the_marker_is_read,
    test_shell_keyword_in_body_does_not_flip_out_of_grammar,
    test_redirect_quoted_in_body_is_a_mention_not_a_write,
    test_write_on_the_operator_line_stays_visible,
    test_write_after_the_terminator_stays_visible,
    test_fd_digit_does_not_displace_the_copy_destination,
    test_fd_digit_does_not_manufacture_a_write,
    test_fd_redirect_at_the_marker_is_a_write,
    test_patch_writer_verdicts_are_decided_by_the_patch_not_the_fd,
    test_pin_a_control_flow_keyword_refuses_a_plain_read,
    test_pin_a_variable_in_a_write_position_sweeps_in_a_quoted_body,
    test_every_case_in_this_file_is_in_ALL,
]


if __name__ == "__main__":
    if not ALL:
        print("NO CASES COLLECTED — a zero-case run is a failure, not a pass")
        sys.exit(1)
    failed = []
    for fn in ALL:
        try:
            fn()
            print(f"ok    {fn.__name__}")
        except AssertionError as e:
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(ALL) - len(failed)}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
