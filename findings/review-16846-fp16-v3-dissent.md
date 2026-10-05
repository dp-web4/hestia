# FP16 v3: dissent on quoted heredoc text in a case pattern

Review request: `16846`. Verdict: **do not concur with this candidate**.

Reviewed patch SHA-256:
`0a22e5f7653dbfc01cd0ceb4fa8a952052a51367fcc637dc070d44aa5cbf895d`.
Verified base: `23ea932439e322c4078e2737a4093a6d2461072e`.

## P1 — accepting the header exposes a heredoc-stripping false allow

`_case_header_rule_applies` accepts this valid Bash command:

```bash
case x in '<<EOF') :;;
esac
printf x > /tmp/fp16-neutral-marker
```

The quoted pattern is literal text, not a heredoc. Bash executes the command
after `esac`. However, `_strip_heredoc_bodies` matches `<<EOF` inside the quoted
pattern and discards every remaining line while looking for its terminator.
The new header acceptance then accepts the surviving header and returns no
write targets. The substitution guard does not address this interaction.

At the verified base, the same surviving header raises `_OutOfGrammar`.
Consequently, a closure-path mention in the original command still triggers
the conservative write classification. In the candidate, that protection is
removed: an inert classifier-only check with a path under `plugins/_shared`
changes from `write / governance-closure-out-of-grammar` to `read / None`.

This is a pre-existing preprocessing defect made reachable by the proposed
grammar expansion. The proof that patterns do not execute is insufficient:
the parser must also retain the executable text following the pattern.

## Verification

The companion [probe](review-16846-fp16-heredoc-probe.py) checks the exact patch
digest, applies its source hunks in memory against the pinned base, and runs
all 39 candidate regression tests. All pass. It also reproduces:

- Baseline write walk: `_OutOfGrammar`.
- Candidate write walk: `[]`.
- Bash syntax check: success; execution creates a disposable neutral marker.
- Closure-path classification: `write` becomes `read` (classifier only).

Run `python3 findings/review-16846-fp16-heredoc-probe.py PATCH_FILE` from this
repository. Candidate governance code is never installed. The only executed
shell example writes within a temporary directory that the probe removes.

## Required repair

Keep the header rule disabled for heredoc-like raw text until heredoc detection
can distinguish shell syntax from quoted words. A conservative `<<` guard is
a possible narrow interim repair for this finding; it is not a claim that all
other parser interactions have been reviewed. Add this regression both at the
write-walk level and at the full classifier boundary. Any broader heredoc
parser repair needs its own quoted/unquoted and actual-heredoc coverage.

The earlier substitution findings are covered by the v3 guard and regression
battery. This dissent concerns a separate parser interaction. No escalation
concurrence is granted.
