# held/: hestia#1598, BSD `sed -i '' SCRIPT FILE` reads the script as an in-place operand. NOT applied

| file | sha256 |
|---|---|
| `d5d9dc6706aa0598b1343830ee2f46e1d186c90cccc06f287bad486ffc8ead26.patch` | `d5d9dc6706aa0598b1343830ee2f46e1d186c90cccc06f287bad486ffc8ead26` (base main `d577bcf4`) |

## The defect

The closure classifier parsed `sed -i` the GNU way only. On macOS, BSD sed's bare `-i` takes the backup suffix as
the **next** argument. So `sed -i '' SCRIPT FILE` was read as:
- script = `''`;
- in-place operands = `SCRIPT FILE`.

A script whose text names a slash-led closure path was then refused as `gate.self_access`. That opened an
escalation a human has to retire, even though the edited file was outside the closure.

**Live:** McNugget, 2026-11-14, escalation `8af5057f7a77a15c`.

## The change (`hestia_governance_closure.py`, the `sed` branch of the write-target parse)

**When the BSD reading is taken.** All of these must hold:
- every `-i` occurrence is **bare** (no attached suffix, no `--in-place`);
- there's no `-e` / `--expression` / `-f` / `--file` script;
- there are **at least three** positionals;
- the first positional is empty or dot-led, i.e. a BSD suffix.

When they do, the second positional is the script and the rest are the operands.

**Why this admits no GNU write.** Read as GNU, that same command has the script `''`, which edits nothing, or a
dot-led script, which GNU sed rejects as a syntax error before it touches any file. Every real operand is still
an operand in the BSD reading.

## Tests: `tools/closure_bsd_sed_test.py` (new, 13 rows)

- **4 not-write rows**, all `write` on main:
  - `-i ''` and `-i .bak` with a closure path in the script;
  - `-n -i ''`;
  - two files outside.

  On the patched classifier these are `read` (the closure path appears as text, a witnessed and allowed read).
- **9 must-write rows**:
  - BSD `-i ''` / `-i .bak` on a closure file;
  - a closure file as the second operand;
  - GNU `-i` and `-i.bak`;
  - `-i '' -e`;
  - two positionals (the GNU reading is kept);
  - a non-suffix first positional;
  - `--in-place=`.

| suite (McNugget, base `d577bcf4`) | patched | main |
|---|---|---|
| `closure_bsd_sed_test` | **PASS 13/13** | FAIL 9/13 (the 4 rows above) |
| the other 17 tests importing the closure (`tools/`, `plugins/_shared`) | same result per test | same result per test |

Two of those 17 fail on main on this Mac, and fail identically on the patched classifier:
- `shell_grammar_test`'s real-shell comparison;
- `one_gate_decide_contract_test`'s kimi row.

## Apply

```
python3 held/build-1598/build.py <worktree at main> <EMPTY out dir>   # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/closure_bsd_sed_test.py                                 # PASS: 0 failing
```
The patch touches the closure classifier, its hooks-gt copy, and the hooks-gt manifests (`_shared` and the four
harnesses). All of these are governed paths. It also adds the test.
