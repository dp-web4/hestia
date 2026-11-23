# held/: hestia#1611, portable `sed -i` in the shell-grammar differential. NOT applied

| file | sha256 |
|---|---|
| `148d16f37f2cd9fdc14220627a874669ab73d92edbade2659e91e988ece419c4.patch` | `148d16f37f2cd9fdc14220627a874669ab73d92edbade2659e91e988ece419c4` |

Base: main `b28574dc1bf3d728cd89d0f5787e16faf277b2ec`.

## The change

`plugins/_shared/shell_grammar_test.py`'s real-shell differential probes `sed --version`. GNU hosts keep
`sed -Ei 's/orig/edited/' FILE`; other hosts use BSD sed's explicit empty backup suffix,
`sed -Ei '' 's/orig/edited/' FILE`. Only the test fixture changes. The closure classifier and its
ground-truth copies are untouched. Diffstat: one file, +13 −1.

## Validation

- The builder strictly reconstructs the patched test from `HEAD` in memory.
- `git apply --check` passes on base `b28574dc`.
- On Linux, both the base test and the generated patched test pass: 4 suites, 42 explicit cases,
  6 differential cases, 9 block/body read pairs, 52 generated write pairs, 3 neutral cases and 2 pins.
- The issue reporter measured the same BSD spelling in the differential on McNugget and saw the suite pass.
  This exact digest still needs a native macOS rerun after application; this workspace is Linux.

## Apply

```sh
python3 held/build-1611/build.py <worktree at main> <EMPTY out dir>   # re-cut if main moved
git apply --check <out dir>/<sha>.patch
git apply <out dir>/<sha>.patch
SHELL_GRAMMAR_SHARED=<worktree>/plugins/_shared python3 plugins/_shared/shell_grammar_test.py
```
