# held/: hestia#1560, the cluster rule over-judges a pattern letter's value, NOT applied

| file | sha256 |
|---|---|
| `af23b84537d63ca29334689bf41272dd55032d57dd80e791fbdf2c8cb72bb174.patch` | `af23b84537d63ca29334689bf41272dd55032d57dd80e791fbdf2c8cb72bb174` (base main `ce6ddd5c`) |

Follow-up to #1550 from legion-claude's v2 review, kept out of #1550 so its reviewed sha didn't change.

## The defect

#1550's cluster rule (`grep -rf P`, `jq -nL DIR`) scans a short-option cluster for the first letter whose value is
a file or other value. It skipped letters whose value is a **pattern**. So in `grep -nefoo FILE` it went on past
`e` (getopt hands `foo` to `-e`) to the `f` inside `foo`, and judged `oo` as a `-f` program file.

**Direction:** over-judge only. Every operand is still judged. Measured on McNugget with claude-code's live
policy (cwd `~/ai-workspace`, outside the grant): a relative phantom like `oo` is refused quietly or allowed,
so `grep -nefoo <granted>` is **allowed on main**. The false deny needs the text after the misread `f` to name
an existing out-of-scope path:
- `grep -nef/etc/hosts FILE`: grep reads the pattern `f/etc/hosts`;
- main judged `/etc/hosts` as a program file and denied.

It is rare. The fix is small and also makes the scan match getopt.

## The change (`_outside_candidates`, the cluster scan)

1. The scan stops at the first letter that takes a value, **including pattern and delimiter letters**
   (`pattern_opts`, `delim_opts`). That letter owns the rest of the word, or the next word if it is last.
2. **How its value is handled:**
   - a pattern letter sets `pattern_given`, so every operand is still judged as a file;
   - an attached value is skipped, as the attached spelling `-efoo` already is;
   - an attached value with an **unquoted glob** is judged, because the shell expands it.
3. **Deliberately not string options** (`string_opts`). They are head-wide, and some are booleans in another
   subcommand: git's `-m` is a message under `commit`, a flag under `checkout`. So `git checkout -fm PATH` keeps
   the old scan and judges `PATH`.
4. The GNU `sed -if` rule is unchanged: `-i` before the letter still takes the rest as its backup suffix.

## Tests: `tools/gate_false_deny_test.py` gains 12 rows, now 67

- **must allow:**
  - `grep -nefoo`, `grep -inef`, `grep -nefoo/bar` on a granted file;
  - `grep -nef/etc/hosts`, `grep -ief/etc/hosts` on a granted file. These two **fail on main** (the false deny).
- **must deny:**
  - `grep -nefoo /etc/hosts`, `grep -ne foo /etc/hosts`, `grep -nef /etc/hosts`;
  - `grep -nefoo <granted> /etc/hosts`, `sed -ne p /etc/hosts`;
  - `git checkout -fm /etc/hosts`;
  - `grep -ne/etc/* <granted>`. This one **fails on main**: the unquoted glob in a clustered pattern value went
    unjudged, a small tightening. The shell expands it as a relative path under the cwd. It is judged as
    the attached `-e/x/*` already is.

| suite (McNugget, base `ce6ddd5c`) | patched core | main's core |
|---|---|---|
| `gate_false_deny_test` | **PASS 67/67** | FAIL 64/67 (the 3 rows above) |
| shell battery | 1431 / 3 | 1431 / 3 (the same 3 macOS `TMPDIR` rows) |
| all core-importing `tools/*_test.py` | see the PR | see the PR |

Live policy probe (claude-code's snapshot, cwd `~/ai-workspace`): every #1560 shape gives the expected verdict
on the patched core.

## Apply

```
python3 held/build-1560/build.py <worktree at main> <out dir>     # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/gate_false_deny_test.py                              # PASS: 67/67
```
The patch touches the gate core, its hooks-gt copy and the five manifests (governed paths), plus the test.
