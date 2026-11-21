# held/: hestia#485 comment/quote desynchronization. NOT applied

| file | sha256 |
|---|---|
| `09adcc54726efd01349f1591e552fae1732eb998b2139f4c555dd0a67a267c82.patch` | `09adcc54726efd01349f1591e552fae1732eb998b2139f4c555dd0a67a267c82` |

Base: main `59f2478eb70314a26c1538c166d9e938738e73fc`.

## The change

The base closure lexer keeps comments visible instead of enabling `shlex` comment stripping. After
tokenization, a `#`-led token followed by a NEWLINE EMBEDDED IN A LATER TOKEN now raises the
existing out-of-grammar posture. That shape means a quote in comment text made shlex consume a
command boundary Bash honors. A governed write behind it is therefore refused instead of reading as
`none`/`read`; a command with no closure vocabulary keeps the existing `none` behavior.

This is the remaining comment/quote slice of #485. Draft #1577 separately handles ANSI-C `$'…'`;
this patch is based on main and does not duplicate that work. Both touch the closure lexer and need
the usual rebase if one lands first.

The patch updates the closure source, its hooks-gt copy and five manifests, and adds
`tools/closure_comment_quote_test.py` (100755).

## Differential and controls

Real Bash writes the hook in all three new specimens; the unpatched classifier misses the first:

- `echo x # it's` + write + `echo done # '` (Bash rc 0);
- `echo x # say "hi` + write + `: "` (Bash rc 2, write still happens);
- `echo $(( 1 )) # it's` + write + `: '` (Bash rc 2, write still happens).

The patched classifier returns `governance-closure-out-of-grammar` for all three. Mid-word `#` and
ordinary comment/quoted-hash read controls stay non-write.

**Measured fallback cost:** `echo "#x" "a\nb"` followed by a read of the governed file is refused too.
The token model cannot distinguish that quoted hash from a comment opener, so the conservative arm is
explicitly pinned in `test_fallback_cost_for_a_quoted_hash_is_explicit` rather than presented as free.

## Validation

- Unpatched base: the new differential and fallback-cost tests fail; the other two controls pass.
- Patched: **4/4** new comment/quote tests pass, including real-Bash differentials.
- Revised module preloaded into existing suites:
  - `closure_output_writes_test`: **4 tests, 103 write/read pairs**;
  - `hestia_governance_closure_test`: **39 tests**;
  - `shell_grammar_test`: **4 suites**, 42 explicit cases, 6 differential, 9 block/body read pairs,
    52 generated write pairs, 3 neutral cases and 2 pins.
- Builder strictly reproduces all eight patched files and `git apply --check` passes on the base.

## Apply

```sh
python3 held/build-485-comments/build.py <worktree at main> <EMPTY out dir>  # re-cut if main moved
git apply --check <out dir>/<sha>.patch
git apply <out dir>/<sha>.patch
python3 tools/closure_comment_quote_test.py
```
