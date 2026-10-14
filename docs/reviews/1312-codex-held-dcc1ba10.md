# HOLD: #1312 revised held patch dcc1ba10

Reviewed head `3889856ff1fcdd8fad49bd1470a0a97d853b2749`, held patch SHA-256
`dcc1ba10f584c179def43133dee060b4c8de0fd1df7665c30c189ea679887c56`,
against its stated base `67b45517`. The patch was evaluated in memory; no gate file was changed.
Checked `git log HEAD..origin/main` in the shared checkout before review; the merged changes
do not provide this loop exclusion repair.

## P1: raw-text stateful exclusions miss Bash quote removal and line continuation

`_LITERAL_FOR_STATEFUL` searches the original body for contiguous builtin names. Bash also
accepts `c''d`, `c"d"`, `c\d`, and `c\` followed by a newline and `d` as the builtin `cd`.
None matches this exclusion. The revised loop rule therefore still allows the earlier
persistent-directory escape when the same builtin has one of these spellings:

```sh
for f in secret.txt secret.txt secret.txt; do cat $f; c''d sub; done
```

Use a fixture with granted `ws/**`, ungranted sibling `outside`, and
`ws/sub/sub -> outside`. The third `cat` runs in `outside`. The base returns an
unenumerated refusal; dcc1ba10 returns `(True, None, None)`. Each independent iteration
check starts in `ws`, so it never examines the third iteration's actual directory.
The same false allow reproduces for all four alternative spellings above. A separate
Bash oracle using only `pwd` and the directory change confirms the third directory for
each spelling; the sample `cat` is never executed.

This is the remaining P1(b) from HOLD 23938, not a new filesystem-mutation concern.
The revision excludes the direct `cd` and fully quoted `'cd'`, but its claimed
state invariant is not established for equivalent shell spellings. Apply the exclusions
to properly decoded shell command words, and account for line continuation and uncertain
command heads. A conservative refusal of uncertain forms is preferable to extending the
raw-text spelling list. Add equivalent-spelling controls for the other stateful builtins too.

## Verified improvements and limits

- The earlier closing-`done` filename case is now refused.
- The original direct-`cd` case is now refused.
- The plain literal-list loop and the #1296 header fix retain their intended allows.
- This is focused adversarial validation, not a rerun of the full shell battery or the
  author's transcript replay. No separate blocking finding was established for #1296.

Run from this checkout's root:

```sh
python3 tools/review_1312_revision_probe.py
```

The probe verifies the held patch digest and hunk contexts, loads both classifiers in
memory, checks Bash syntax, and removes its temporary fixtures. It installs no gate and
runs no network command. Result: four false allows reproduced; all listed controls pass.

The requester also asked to refuse two moot petitions. Both decisions succeeded as
`peer:codex`, with `granted: false`:

- `scope-7b0321332188`: disposition notice 23987.
- `scope-a29f7ef5fa4b`: disposition notice 23988.

Technical verdict: **HOLD** on dcc1ba10. This review does not amend or reconsider the
operator's policy ruling reported on the PR; the remaining blocker is implementation soundness.

— Codex, review notice 23978
