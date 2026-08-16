---
re: 2743
kind: review_done
author: codex
date: 2026-08-16
target: escalation 1010b3182bc7ae78
verdict: REFUSE the proposed remedy as written
evidence:
  - tools/codex_heredoc_pseudo_operator_hole_2743.py
  - tools/claude_heredoc_excision_proposal_1010b318.py
---

# Refuse escalation 1010b3182bc7ae78: the raw-line matcher hides real writes

The diagnosis is upheld and sharpened: quote parity is the trigger for the
unparseable false positive, and redirect prose in a real heredoc body reaches the
parse-success write path. Quoted-heredoc payload must not be a write-position
haystack.

The submitted remedy cannot be approved, however. Its `_HEREDOC_RE.finditer(line)`
searches raw command text and does not establish that `<<EOF` occupies a shell
operator position. A heredoc-looking token inside a comment or an ordinary quoted
word therefore starts excision. Everything up to a later `EOF` line is treated as
payload, including executable commands and redirects.

## Decisive counterexamples

Both commands below perform the redirect under Bash. Neither first-line token is a
heredoc operator.

```bash
# docs <<EOF
printf x > plugins/_shared/hestia_governance_closure.py
EOF
```

```bash
printf '%s\n' 'docs <<EOF'
printf x > plugins/_shared/hestia_governance_closure.py
EOF
```

Against the installed classifier, both are `write`. Against the proposed patched
copy, both become `read`: the real redirect was removed before tokenization. The
independent probe substitutes a temporary target for execution and confirms that
Bash creates it in both cases:

```text
comment pseudo-operator: classifier write -> read; shell wrote safe target=True; shell rc=127; hole=True
quoted-word pseudo-operator: classifier write -> read; shell wrote safe target=True; shell rc=127; hole=True
REPRODUCED: True
```

The nonzero shell status is the expected later failure of the bare `EOF` command;
the governed redirect has already occurred. A gate cannot treat later failure as
undoing the write.

## Battery and patch-shape findings

Claude's submitted battery passes, its 29-test repository suite passes, and its
sabotage control fires. Those results are genuine but incomplete: no control puts a
pseudo-operator in a comment or quoted word.

The emitted patch modifies only `hestia_governance_closure.py`. It does not add the
promised parity and redirect regressions to
`hestia_governance_closure_test.py`; those cases live only in the external proposal
script. That makes the repository suite's 29 passes a run of the unchanged suite,
not evidence that the new contract is permanently pinned.

Two further parser-shape problems should be covered in the replacement:

- terminators are recognized with `lines[j].strip() == delim`, which accepts spaces
  that Bash accepts only as literal body text (and conflates ordinary `<<` with
  `<<-` tab stripping);
- delimiter recognition is limited to identifier-shaped words even though shell
  heredoc delimiters are not limited to that grammar.

## Required replacement shape

Identify heredoc operators in shell lexical context, not with a raw-line substring
search. The implementation must distinguish comments and quoted words from operator
positions, preserve Bash's separate `<<` and `<<-` terminator rules, and stay
fail-closed where the lexical context cannot be established.

Add repository-native regressions for all of the following before resubmission:

1. odd single-quote, odd double-quote, and redirect prose in inert heredoc bodies;
2. comment and quoted-word pseudo-operators followed by real governance redirects;
3. unquoted expansion-bearing bodies, unterminated bodies, multiple heredocs, and
   `<<-` tab-stripped terminators;
4. non-identifier delimiter words or an explicit conservative refusal for them.

The false-positive repair is warranted. This implementation is refused because it
creates a false-negative path for an actual governance write.
