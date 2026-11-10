# held/: hestia#1494 + #1314, the gate's two largest false-deny causes, NOT applied

| file | sha256 |
|---|---|
| `cafcfd93f6a9e7459c3f367151fa6b3e960b22cc1a633f7a01c3d2216b331a85.patch` | `cafcfd93f6a9e7459c3f367151fa6b3e960b22cc1a633f7a01c3d2216b331a85` (base main `fd8142e4`) |

Nothing here is applied. The patch touches the gate core, its hooks-gt copy and the five manifests, which are
governed paths. dp applies it:

```
python3 held/build-1494/build.py <worktree at main> <out dir>     # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
held/build-1494/measure.sh <worktree at main> <out dir>           # suites, patched core vs main's
```

`build.py` makes every edit by an exact-once anchor in HEAD's core, so if main moves the patch is re-cut, not
re-derived. It emits the GT copy and manifests with main's own `tools/hooks_gt.emit_patch`, with the core read
served from the patched copy. It then verifies that the patch, applied in memory to HEAD, reproduces every
intended file. No forbidden token is spelled in the build script or the test; both read it from `FORBIDDEN_DEFAULT`.

## The measurement (McNugget, claude-code, 2026-11-03 08:20Z to 11-10)

Every gate decision on the chain for the week: **2,052 allows, 89 denies (4.2%)**. The chain stores only the rule
id and a target truncated at about 220 chars, so each deny was replayed through `core.evaluate` with claude-code's
live policy snapshot (WS `~/repos`, cwd `~/ai-workspace`) to recover the token and reason. Each was then
classified by hand.

| n | kind | cause |
|---:|---|---|
| 24 | expected | deploy preflight probes (`touch ~/.hestia/deploy.hold`, a `/var/folders` probe) |
| 24 | designed | unenumerated: `$var`, `$(...)`, process substitution (the rewrite is asked for) |
| 10 | true | out of scope: `~/.claude` (memory, primers) |
| 8 | true | out of scope: `~/.local/state` hub-mesh thread logs |
| 3 | true | out of scope: `~/.hestia`, `~/.sage` |
| 3 | true | `gate.self_access`: governance writes (escalated) |
| 3 | true | nonexistent path named |
| 2 | true | out of scope: `/opt/homebrew` |
| 2 | true | out of scope at the time (member-mesh paths, granted later that day) |
| 2 | true | unquoted `--include=*.py`: the shell does expand it against the cwd (one also lists `~/.hestia/deploy` before its grant) |
| 1 | true | destructive preset: chained `rm` outside /tmp |
| **4** | **FALSE** | **`egress.secret`: the env-file token inside a word.** 3 are `os.environ` (a `gh search` query, and two Python heredocs editing `hestia-mesh.py`). 1 is a grep regex for the token itself. |
| **3** | **FALSE** | **`mrh.command`: a `gh --jq` expression read as a relative path** (`.state`, `.reviews[-1].body`, `.comments[-2:][]`, the last a glob, so a cwd read) |

**False-deny rate: 7 of 89 denies (7.9%), 0.33% of all decisions.** Excluding the expected probes, it is 7 of 65.
This patch fixes **6 of the 7**. The remaining one is the grep regex `\.env`, which stays denied on purpose (see below).

Further live instances while building this, not in the window: `grep -c "os.environ" <file>` (refused
`egress.secret`), and `grep -rn 'venv.EnvBuilder'` from #1494 itself.

## The change

1. **The env-file token is matched as a file name** (`forbidden_hit`, both gate 1a text sweeps). It is a hit unless
   the token is glued inside one identifier on both sides.
   - Now allowed: `os.environ`, `venv.EnvBuilder`.
   - Still denied: `.env`, `./.env.local`, `.envrc`, `prod.env`, `app.env.bak`, `.ENV`, `\.env`, `process.env.X`.

   All other tokens keep the substring match. The symlink-target checks keep the substring match too: they judge
   a resolved path, not text.
2. **gh's `--jq`/`-q` value is a string** (`_CMD_SPECS["gh"]`). In `gh help reference` (gh 2.x) it takes a jq
   expression in all 55 subcommands that have it. `--template` and `-t` are deliberately not listed, because
   under `repo edit` and `auth status` they are booleans and would swallow the next word.
3. **jq's filter is its first operand** (`_CMD_SPECS["jq"]`, `pattern_first`), unless `-f`/`--from-file` supplies
   the program. `-L` is judged.
4. **A hole found while measuring, closed (tightening).** With the program from a FILE (`grep -f P`,
   `--file=P`, `-fP`, `sed -f`, `awk -f`, `rg -f`), the first operand was still taken as the pattern and never
   judged. On main, `grep -f <granted file> /etc/hosts` is ALLOWED. So are `grep -rf /etc/hosts <granted dir>`
   and `grep -nf<granted file> /etc/hosts`, through the clustered spelling. A file option now sets
   `pattern_given`, so every operand is judged.
   - Clustered short options (`-rf P`, `-nfP`) are read as getopt reads them: the file letter takes the rest of
     the word, or the next word.
   - The cluster rule matters for jq too. Without it, item 3 would have opened `jq -rf /outside/prog.jq` (main
     judges it, because jq had no spec). If an earlier letter in the cluster itself takes a value, the rule can
     only judge more.

**Not changed, deliberately:**
- An unquoted glob option value (`--include=*.py`) stays judged, because the shell expands it against the cwd.
- #1494's second shape, `gh issue list --search '".env"'`, stays denied: the token is quoted data there, but
  telling that apart needs a per-command query-argument carve-out like #1330's prose flags. That is a separate
  change.
- `\.env` in a regex and `process.env` stay denied. A word or backslash before the token followed by a non-word
  is also how a real env-file path reads, and over-denying is the safe direction.

## Tests (`tools/gate_false_deny_test.py`, new; strings only, a fake workspace, never the live daemon)

47 rows: 12 false-deny shapes that must be ALLOWED, and 35 must-deny rows (14 env-file spellings that must
stay `egress.secret`, 21 outside reaches that must stay `mrh.command`, including through every new exemption
and every clustered spelling). It raises on failure.

Measured on base `fd8142e4`, McNugget (macOS), with `measure.sh` and an overlay runner over every
`tools/*_test.py` that imports the core:

| suite | patched core | main's core |
|---|---|---|
| `gate_false_deny_test` | **PASS 47/47** | FAIL 28/47: the 11 false-deny rows and 8 unjudged-operand rows |
| decide contract | 1 fail, `scope-read-escalates` | same 1 (macOS has no `/etc/hostname`) |
| shell battery | 1431/3 | 1431/3, the same 3 macOS `TMPDIR` rows |
| `egress_prose_test` | PASS 13 + 18 | PASS 13 + 18 |
| all core-importing `tools/*_test.py` | 20 pass, 4 fail | the same 20 pass, the same 4 fail (exit status identical for all 24 tests) |

The 4 failures shared by both cores, all pre-existing on main at `fd8142e4` on this Mac:
- `gate_grep_patterns_and_toolchain_grant_test`: 2 rows, a substitution after or into grep.
- `one_gate_decide_contract_test`: under the overlay runner, a `kimi-untimed` deadline row (load-dependent; it
  passes in `measure.sh`). Directly, the macOS `/etc/hostname` row.
- `public_boundary_test`: "codex configured identity path rendered".
- The shell battery's 3 macOS `TMPDIR` rows.

Live-policy probe (claude-code's real snapshot, 41 acts, `~/repos/.cam-test/fp_probe2.py`): main 26/41 as
expected, patched **41/41**.

## After deploy

Re-run the census on decisions after the deploy point (`deny_census.py` with the new cutoff, `deny_replay.py`,
`deny_classify.py`) and the live probe against the deployed core. The expected result is that the `os.environ`
and `--jq` causes are gone and nothing previously denied is now allowed.
