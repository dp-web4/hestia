#!/usr/bin/env python3
"""Pins for `escalation_payload_census.classify`.

The census answers "what fraction of escalations expose no act text to a reviewing peer",
and the whole answer rests on one function deciding whether a `stated_reason` string holds
a command body or just a destination. So that function is what gets pinned.

Every fixture below is a VERBATIM `stated_reason` observed on the CBP chain between
2026-08-18 and 2026-08-26 (25,000-hop walk, 137 `gate_escalation_opened` rows), except the
two marked SYNTHETIC, which encode the shapes the fleet does not currently produce and
which must not silently start scoring as unattestable if a seat ever emits them.

The first draft of this classifier keyed on a `Tool: ` prefix and scored kimi's rows --
which carry the command BARE -- as unclassifiable. That regression is what `test_kimi_
bare_command_is_attestable` exists to prevent: three seats spell the prefix three ways,
so any test that only exercises this seat's spelling passes on a broken discriminator.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from escalation_payload_census import classify  # noqa: E402


# ---- destination-only: the `_attempted_summary` path fallback, both spellings ----

def test_claude_edit_fallback_is_destination_only():
    """This seat renders `Tool -> path`. Nothing of old_string/new_string reaches it."""
    assert classify("Edit -> /mnt/c/exe/projects/ai-agents/hestia/plugins/_shared/x.py") \
        == "destination-only"


def test_kimi_edit_fallback_is_destination_only():
    """kimi renders the SAME fallback as a bare path -- observed on 289e46bfe1be5a3e."""
    assert classify(
        "/mnt/c/exe/projects/ai-agents/hestia/plugins/_shared/shell_grammar_test.py") \
        == "destination-only"


def test_write_fallback_is_destination_only():
    assert classify("Write -> /home/dp/.claude/hooks/hestia/pre_tool_use.py") \
        == "destination-only"


# ---- attestable: a command body, however the seat prefixes it ----

def test_claude_bash_prefixed_command_is_attestable():
    assert classify("Bash: git show origin/main:plugins/_shared/core.py | grep -n foo") \
        == "attestable"


def test_kimi_bare_command_is_attestable():
    """No `Tool: ` prefix at all. A prefix-keyed classifier scores this wrong -- that was
    the first-draft bug, caught by the live row, not by review."""
    assert classify(
        'mkdir -p /tmp/meter-new/tools && cd /tmp/wt-kimi-pr612/plugins && '
        'for d in */; do ln -sfn "$PWD/${d%/}" "/tmp/meter-new/plugins/${d%/}"; done') \
        == "attestable"


def test_codex_apply_patch_is_attestable():
    """codex's harness sends the patch text, so its write acts ARE reviewable. This is the
    existence proof that the Edit gap is a hook choice, not a protocol limit."""
    assert classify("apply_patch: *** Begin Patch\n*** Update File: tools/x.py") \
        == "attestable"


def test_command_that_merely_starts_with_a_path_is_attestable():
    """SYNTHETIC. A command invoked by absolute path is not a destination -- the space is
    what separates the two, and a leading `/` alone must not condemn it."""
    assert classify("/usr/bin/env python3 -c 'print(1)'") == "attestable"


# ---- the two edges that must not be folded into either bucket ----

def test_redacted_is_its_own_class():
    """Withheld ON PURPOSE. Counting it as a missing payload would inflate the finding with
    rows where the mechanism did exactly what it should."""
    assert classify(
        "Bash [REDACTED — names a credential-shaped token; 412 chars withheld rather "
        "than copied into the record]") == "redacted"


def test_missing_reason_is_absent():
    """Observed twice: bb120cbc3cdee1cf (Bash) and 301cefe885d1ec8d (Write) carry null.

    Was a parametrize mark over the three values. Under bare `python3` -- which is how CI
    runs this glob -- the mark does NOTHING: the function is called once with `value`
    unbound and dies on TypeError, or is never called at all. The loop is the same three
    cases with the same coverage and no runner to be wrong about.
    """
    for value in (None, "", "   "):
        assert classify(value) == "absent", repr(value)


def test_path_with_trailing_space_is_still_destination_only():
    """SYNTHETIC. Trailing whitespace is a transport artefact, not a payload."""
    assert classify("  Edit -> /home/dp/.claude/settings.json  ") == "destination-only"


# ---- the finding itself, as an executable claim ----

def test_no_edit_or_write_shape_survives_as_attestable():
    """The falsifier this census published, run against the shapes the three seats emit.

    Across 137 opened rows in 7.2 days, zero Edit/Write/NotebookEdit escalations carried a
    command body. If a seat ever starts sending one, THIS test is what should fail first --
    it is the pin that says the gap closed, so delete it rather than edit it.
    """
    for shape in ("Edit -> /a/b/c.py",
                  "Write -> /a/b/c.py",
                  "NotebookEdit -> /a/b/c.ipynb",
                  "/a/b/c.py"):
        assert classify(shape) == "destination-only", shape


# Listed by name rather than handed to a runner. `tools/ci_selfexec_test.py` answers
# "is this test wired up?" by walking `ast.Name`, so dispatch through a runner -- like a
# `globals()` sweep -- is invisible to it and the whole file reads as inert. Third PR to
# pay for that: #171, #468 (a week red), and this one. The staleness check below is what
# stops the explicit list from becoming the very defect the guard exists to catch.
TESTS = [
    test_claude_edit_fallback_is_destination_only,
    test_kimi_edit_fallback_is_destination_only,
    test_write_fallback_is_destination_only,
    test_claude_bash_prefixed_command_is_attestable,
    test_kimi_bare_command_is_attestable,
    test_codex_apply_patch_is_attestable,
    test_command_that_merely_starts_with_a_path_is_attestable,
    test_redacted_is_its_own_class,
    test_missing_reason_is_absent,
    test_path_with_trailing_space_is_still_destination_only,
    test_no_edit_or_write_shape_survives_as_attestable,
]


if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        sys.exit(1)
    for f in TESTS:
        f()
        print("ok", f.__name__)
    print(f"{len(TESTS)} passed")
