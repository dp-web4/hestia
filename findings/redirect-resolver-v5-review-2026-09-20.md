# PR #1082: v5 still clears writes whose destinations it has not proved

Review of `fb91fb78fcf1e98fac2d9560ff819f38f0b728b6`, answering notices
13378 and 13379. **Dissent: do not land this resolver.** Ten additional
commands change from `write` on main (`40903d6`) to `read` with v5 injected.
Bash resolves every final destination to the governed file. Three controls
distinguish safe assignments and an actual governed assignment.

The published table also reproduces: all 26 `[HOLE]` rows in its 42 cases
still classify `write` (the notice reports 24; the source labels 26).
That closes the reported examples, not the grammar.
The historical transcript census was not rerun for this review.

Reproduce from this branch:

```sh
python3 tools/redirect_target_resolver_v5_review.py
```

The probe loads both implementations from immutable git objects. It classifies
the actual proposed commands but does not execute their writes. Its Bash oracle
replaces the final redirection command with a builtin `printf` of `OUT`, retaining
the preceding binding/control-flow syntax. Bash starts with `OUT` equal to the
relative governed path below. No destination file is opened or changed.

In the following table, `M` abbreviates
`plugins/_shared/hestia_governance_closure.py`, `S` abbreviates
`/tmp/review-safe`, and every prefix is followed by `echo M > "$OUT"`.
The runnable probe contains literal commands, without these abbreviations.

| Prefix | Why the resolver's binding is not Bash's value |
|---|---|
| `false &&` newline `OUT=S;` | The newline continues the AND list; the assignment never runs. |
| `true \|\|` newline `OUT=S;` | The newline continues the OR list; the assignment never runs. |
| `echo ignored \|` newline `OUT=S;` | Assignment runs in a pipeline subshell. |
| `OUT=S && true &` | The complete AND list runs asynchronously, including the assignment. |
| `if false; then echo fi; OUT=S; fi;` | The argument `fi` decrements the resolver's nesting count; Bash skips the body. |
| `OUT=S; OUT[0]=M;` | Scalar-to-array rebinding changes `$OUT`; `_ASSIGN` does not count it. |
| `OUT=plugins/; OUT+=_shared/hestia_governance_closure.py;` | Append assignment changes `$OUT`; `_ASSIGN` does not count it. |
| `'OUT=S';` | Quoting makes this a command name, not an assignment. The command fails, and the following write uses inherited `OUT`. |
| `false && # continuation` newline `OUT=S;` | A comment and newline do not end the conditional list. |
| `echo for OUT in S;` | The loop recognizer treats ordinary arguments as an actual loop header and invents a binding. |

The array and append cases establish the governed destination within the command
itself; they do not depend on inherited `OUT`. The other eight use the inherited
value that the resolver incorrectly replaces with its invented safe binding.

The three controls are a plain safe assignment, a safe assignment followed by
`&& echo ignored | cat;`, and a literal governed assignment. The middle control
matters: a later pipeline does not necessarily put the earlier assignment in a
subshell, while a trailing `&` backgrounds the whole AND list.

The claimed four local proofs do not hold on this token representation:

- P1 interprets words as reserved keywords without their grammatical position.
- P2 mistakes continuation newlines for unconditional command boundaries.
- P3 ignores the scope of an asynchronous AND/OR list.
- P4 counts only `NAME=value`, not all Bash assignment forms.
- The loop exception and assignment recognition also lack command-position and
  quote information.

Calling this deny-by-default does not make it so: its positive recognizers still
accept syntax they cannot prove. The next design needs either a bounded grammar
whose entire statement structure is validated, preserving lexical context, or
a shell parser with explicit rejection of unsupported structures. Adding these
ten rows alone will not establish that invariant.

This review adds a probe and evidence only. Production classification is unchanged.
