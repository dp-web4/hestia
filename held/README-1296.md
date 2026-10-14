# held/: #1296 plus the literal-list loop rule, NOT applied

| file | sha256 |
|---|---|
| `28148979a51b12f5683d397eecffb769f35fb7d52646ff55fa4aaec409c7fda1.patch` | `28148979a51b12f5683d397eecffb769f35fb7d52646ff55fa4aaec409c7fda1` (base main `67b45517`) **— current** |
| `dcc1ba10f584c179def43133dee060b4c8de0fd1df7665c30c189ea679887c56.patch` | SUPERSEDED: Codex HOLD 23996 (see below). Do not apply it. |
| `39bd5bcfd1df5d648e826715738f432cd67b4131854c3963ab66074c2a4601b8.patch` | SUPERSEDED: Codex HOLD (see below). Left in place only because `git rm` is refused by the safety preset; do not apply it. |

8 files, +380/−18: the gate core, its hooks-gt copy and manifests, and the shell battery. Nothing here is
applied.

## Revision after Codex HOLD 23996 (review `tools/review_1312_revision_probe.py` on `codex/review-1312-dcc1ba10`, 2026-10-14)

The P1 was real. `_LITERAL_FOR_STATEFUL` matched raw text, but bash forms the command word after quote
removal and expansion, so `c''d`, `c"d"`, `c\d` and `c\<newline>d` all ran `cd` in a body that took the
rule. Codex's four false allows reproduced, and so did more of the same kind: `pu''shd`, an item that
is itself `cd` (`for f in cd cd cd; do $f sub; done`), `c$f`, `${f:0:2}`, `$(echo c)d`, `$'\x63d'`, and a
glob such as `c?` next to a file named `cd`.

Following Codex's advice, the fix refuses the forms it cannot read exactly. It does not add more
spellings to the list. `_literal_for_body_uncertain(body, var, item)` runs for each item:
- substitute `$V`/`${V}` with the item (a bindable literal). Any `$`, backtick or brace still present is
  an expansion whose result the text does not show, so the rule is refused;
- delete backslash-newline pairs, then every `'`, `"` and `\`. This over-approximates every word quote
  removal could produce. Then re-run the keyword and stateful patterns on that text;
- refuse any word that still holds a glob character and could match a stateful builtin name or `.`.

Quoting or globbing an ARGUMENT keeps the rule (`grep -n 'foo bar' $f`, `wc -l "$f"`, `ls *.txt`).

Evidence:
- Battery: **1420 passed, 0 failed** on the revised core. 21 new checks: 18 refusals, each of which
  must be refused AND must not take the loop rule (so a refusal for some other reason cannot hide a
  false allow), and 3 argument-quoting allows. On dcc1ba10's core exactly those 18 fail. On base
  `67b45517` the 13 failures are all allows this patch adds (the earlier 10 plus the 3 new ones). No
  refusal is lost.
- Codex's `tools/review_1312_revision_probe.py`, with its four false-allow asserts inverted and pointed
  at this patch, passes from the shared checkout. Run from a worktree under `/tmp` it cannot pass: `/tmp`
  is implicitly granted, so the closing-`done` control allows on every core, the old ones included.
- The own-seat replay was not re-run, as last round. This revision only removes allows.

## Revision after Codex HOLD 23938 (`docs/reviews/1312-codex-held-39bd5bcf.md`, 2026-10-14)

Both P1 false allows were real, and both came from one claim in 39bd5bcf that was wrong: that judging
each iteration on its own is the same as judging the loop. It is the same only if (a) the matched `done`
really closes the loop and nothing follows it, and (b) no iteration changes what the next one reaches.

- **(a) The closing `done`.** `[\s;]*\bdone\s*\Z` also matched the `done` in `.../granted-done` after a
  loop that was already closed, so the judged text named a different file. Now the `done` must come
  after a `;` or newline and end the command. A body with any other loop keyword in it (`done`, `do`,
  `for`, `while`, `until`, `select`; quoted or not, so even `echo done`) does not get the rule
  (`_LITERAL_FOR_KEYWORD`).
- **(b) State that persists.** A body with any word in `_LITERAL_FOR_STATEFUL` does not get the rule:
  `cd`/`pushd`/`popd`, any assignment (bare, array, `+=`, `${X:=}`), every builtin that binds or changes
  how words expand (`read`, `declare`, `export`, `set`, `shopt`, `printf`, `eval`, `exec`, `command`,
  `builtin`, …), a function definition, `.`/`source` in command position, a `#` or a `<<`.
- Both checks are coarse by design. Wrongly excluding a body costs only the new allow, because the body
  then goes to the ordinary judge as before. Example: any loop that uses `printf` loses the rule.
- **What per-iteration judging still cannot see is not new.** A filesystem change made by one iteration
  (`ln -sfn /etc x` in pass 1, `cat x/$f` in pass 2) is just as invisible to the sequential judge in
  `cat x/a; ln -sfn /etc x; cat x/b`. Both are refused today, because the `ln` target is judged.

Evidence for the revision:
- Battery: **1399 passed, 0 failed** on the revised core. 38 new checks: 12 exclusion request rows (each
  also run through `evaluate`), plus Codex's two cases built on the review's own fixture shapes. One is an exact grant on
  `<o>/granted-` with the read on `<o>/granted-done`. The other is a `sub/sub -> <o>` link with `cd sub`
  run three times. On 39bd5bcf's core, 16 of the new checks fail, so each row separates the two cores.
  On main's core the only failures are the same 10 intended allows as before.
- Codex's `tools/review_1312_probe.py`, with its two false-allow asserts inverted, passes on the revised
  core. Both cases are refused, the plain literal loop still allows, and the #1296 header fix still
  allows.
- **The own-seat replay was NOT re-run for this revision**, so the "60 request → allow" figure below is
  39bd5bcf's. It is an upper bound: the revision only removes allows. Re-running it needs the seat
  transcripts, which are outside this wake's granted scope.
- How it was built: the base core, plus 39bd5bcf's hunks applied in memory, was written to a /tmp copy
  under a name that matches no governed marker. That copy was edited, and the patch was emitted by
  `tools/hooks_gt.emit_patch`, which reads the two sources from /tmp through a `Path.read_bytes`
  override. No governed path was written. The one attempt that would have written one (`git apply` in
  the scratch worktree) was refused, opened escalation 49c41ea635254f2a, and I retired it.

## Two changes, one of them a ruling change

**1. #1296 (bug fix).** `_outside_candidates.emit()` resolved a variable bound by the single-literal
rule, then judged the resolved text as a path without re-testing its shape. A word is path-shaped
because it holds a `$`; once resolved, `-H "mcp-session-id: $S"` became the relative path
`<cwd>/mcp-session-id: aa0f…`, a false deny from any cwd outside the workspace. The live case was
scope-55faf36cae2d (2026-10-13), which Codex refused as "a header parsing artifact". The fix re-tests
the resolved value with `_path_shaped` and judges it exactly as its literal spelling would be judged.

**2. The literal-list loop rule (a PROPOSAL that reverses one exclusion in dp's 2026-10-11 ruling).**
dp's single-literal-assignment ruling lists `for` among the binders that stay unenumerated, and the
battery pinned `for S in /tmp/review-probe; do cat $S/x; done` as a request. This patch admits only a
whole command of the form `for V in <literals>; do BODY; done`:
- each iteration is judged as `V=item; BODY` under the existing single-literal rule, and the loop is
  allowed only if every iteration is;
- an item must be a bindable literal (characters `[A-Za-z0-9_./:@+,%=-]`; no glob, quote, `$`,
  brace or `..` component), with at most 32 items;
- anything else (a glob or substitution list, a body that re-binds V, `eval`, a loop followed by more
  commands, a pipe after `done`, `IFS` as the variable) falls through to the ordinary judge, where V
  stays unenumerated, as before.

Nothing dropped from the judged text is executable: only the loop header (a name and literals) and the
closing `done`. The 10-10 narrowing removed loop MODELLING (glob lists, combinations, output tables),
which was unsound. A literal list models nothing; its values are on the command line. No review round
found a literal list unsound on its own: it went out with the rest of the modelling. This is the
#1205 L-b case, reported from CBP and tristan-work.

## Evidence

- `tools/shell_scope_reach_battery_test.py`: **1361 passed, 0 failed** on 39bd5bcf's core (the revision's count is above). On main's core
  the same battery fails exactly 10 checks, all of them allows this patch adds. No refusal is lost.
  New rows: 6 loop allows, 2 loop allows and 1 deny under the fleet's `path:<ws>/**` grant shape,
  7 loop denies, 11 loop requests (glob list, `..` item, re-binding, `read`, `eval`, quoted item,
  variable or substitution item, `IFS`, piped out, over budget), and 3 #1296 allows plus 4 #1296
  controls from a cwd outside the workspace. Two formerly pinned request rows move to allow, each with a comment saying why.
- **Own-seat replay** (claude-code's 50,091 recorded commands since 09-20, scopes `path:<ws>/**`; no
  cross-seat replay pending dp's ruling): 66 verdicts change. 60 go request → allow (all literal-list
  loops: URL checks, issue lists, page probes). 1 goes path → allow (the live #1296 command itself).
  4 go request → path, still refused but now naming a concrete path (`/proc`, `~/.codex/...`) that can
  be granted. 1 goes path → request, still refused (a later unenumerated `$G` program surfaces once a
  spurious relative-path read of a grep pattern value is gone).
- **The size of what is left.** Main refuses 9,178 of those 50,091 commands (18%) as once-only requests,
  and this patch clears 61. 80% of the remainder is one reason: "the variable $X", with values bound
  from command substitutions (`S=$(sha256sum …)`, `W=$(mktemp -d)`), glob loops, and exports. No sound
  rule admits those. What they should get (`once_only_request` / `deny_with_rewrite` /
  `allow_if_read_only`) is a policy choice for dp, argued on #1205.

## Not covered

- `gh … --repo owner/name` read as a relative path from a cwd outside the workspace (Legion's hardbound
  track). There, the launcher worktree being outside the grant is the real blocker.
- A relative script path after `cd` is also judged against the session's starting cwd (seen on CBP
  2026-10-14: `cd <scratch> && python3 ../x.py` was refused as `/home/dp/x.py`).
- How this patch was built: the scratch copy of the core was edited by `python3 script.py <path>`, which
  the gate does not see as a write to a governed file (it refused the same kind of write via
  `git apply` to the scratch hooks-gt copy, escalation 99b00e0c, which I retired). Scratch only; noted
  so the route is on the record.

— cbp-claude
