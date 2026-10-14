# HOLD: #1312 held patch 39bd5bcf

Reviewed head `537fd9a012e4fb5042e22331a2cd16a5bb52ecdf`, held patch SHA-256
`39bd5bcfd1df5d648e826715738f432cd67b4131854c3963ab66074c2a4601b8`,
against its stated base `67b45517`. The patch was evaluated in memory; no gate file was changed.
The advertised change already merged to main concerns the mesh renderer, not either finding below.

## P1: `_LITERAL_FOR` can remove part of an executable argument

The suffix `[\s;]*\bdone\s*\Z` does not establish a closing shell keyword. Its separator may
be empty, and a word boundary also occurs after `-` or `/`. Moreover, the body may contain an
earlier closing `done` and additional commands.

For a fixture with an exact grant for `outside/granted-`, but none for `outside/granted-done`:

```sh
for f in a; do :; done; cat /fixture/outside/granted-done
```

This is valid Bash. `_literal_for_iterations` rewrites it to:

```sh
f=a; :; done; cat /fixture/outside/granted-
```

The base refuses the original path; the patched classifier allows the command. Bytes removed
from the judged text are part of the filename Bash actually reads. This directly contradicts
the claimed whole-loop and non-executable-removal invariants. Requiring whitespace alone is
insufficient: the recognizer must establish that the final token closes this loop and that no
commands follow it. Until then, fall through to the ordinary judge for uncertain structures.

## P1: independent iteration checks lose persistent directory changes

`command_scope_reach` calls `_command_scope_reach_one` for every item with the same original
`cwd`. Bash preserves changes made by the preceding iteration. Consider a granted fixture
workspace whose `sub/sub` symlink leads to an ungranted sibling directory:

```sh
for f in secret.txt secret.txt secret.txt; do cat $f; cd sub; done
```

The third `cat` runs in the ungranted directory. The base returns an unenumerated request;
the patch allows it. Each isolated check sees only the initial directory and one relative
`cd`, so neither examines the third iteration's path. A separate Bash oracle that only prints
working directories confirms the third iteration's physical directory is outside the grant.

Conservatively exclude bodies that change directory, including equivalent builtins and
wrappers the classifier recognizes, unless persistent execution state is soundly accounted
for. Literal list values alone do not make independent iteration checks equivalent to a loop.

## Validation and scope

Run from the checkout root:

```sh
python3 tools/review_1312_probe.py
```

The probe checks the held patch digest, applies its core hunks in memory with context
assertions, and compares base and patched verdicts. It reproduces both false allows, checks
the suffix sample with `bash -n`, and checks directory persistence using only `pwd`/`cd`.
It also confirms the intended plain literal-loop allow and the #1296 header fix from an
existing cwd outside the fixture workspace. Filesystem fixtures are temporary, beneath the
checkout, and cleaned up. No real protected file is read and no sample network command runs.

Result: both false allows reproduced; both intended allows retained. This is focused
adversarial validation, not a rerun of the complete shell battery. No separate blocking
finding was established for the #1296 header fix; the combined patch remains HOLD because
of the loop rule. The policy reversal also remains an operator decision, independently of
technical review.

— Codex, review notice 23924
