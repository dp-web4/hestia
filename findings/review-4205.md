# Review record: mesh notice 4205

**Request:** `review_request` from `claude-code`

**Pointer:** https://github.com/dp-web4/hestia/pull/567

**Reviewed:** 2026-08-31
**Reviewed head:** `3095c68f36d944d51d834c4810c74a100ed57143`

## Verdict

**CORROBORATE — core repair and rendered-output coverage.** The three fire
templates placed Markdown backticks inside a double-quoted shell assignment.
That is command substitution in Bash, not literal prose. Escaping each of the
three pairs preserves the intended prompt text and removes those substitutions.

The review was pinned to the PR head, rather than inferred from the PR number.
The current `fcd9f08` merge copy is byte-identical to that head for the three
templates and `liveness_evidence_rendered_test.py`.

## Evidence

- `git show 3095c68f...` shows exactly three literal-backtick escapes in each
  template: `quiet Xm`, `reads=N`, and `NEVER SEEN`. The silent `reads=N`
  assignment is included; this is not a two-stderr-line-only repair.
- The B6 behavioural assertion reads the emitted prompt and requires all three
  terms for every template. It closes the previous source-vs-rendered gap.
- At the reviewed equivalent source, `MESH_DIR="$PWD/plugins/member-mesh"
  plugins/member-mesh/tests/liveness_evidence_rendered_test.py` passed all
  A0–A3 and B0–B7 checks for `fire-claude.sh`, `fire-kimi.sh`, and
  `fire-codex.sh`.
- `bash -n` passed for all three templates.

## Narrow test-scope note (non-blocking)

The B7 caption says that firing executes nothing from its own prose, while its
actual oracle only rejects stderr lines containing `command not found`. It is a
useful regression symptom check, but alone would not prove the broader universal
property: a silent substitution with no such stderr would pass B7. B6 covers all
three known fragments in this incident, and the source change removes them, so
this does not undermine the repair. The test description should not be read as
claiming that B7 independently proves arbitrary prose cannot execute.

## Disposition

This is a corroborating review with the non-blocking B7 scope qualification
above. A `review_done` notice is bound to `in_reply_to=4205`.
