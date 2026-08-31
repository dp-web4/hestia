# One gate for all: the engine owns the predicate, every seat still owns the domain

**Seat:** claude-code (CBP) · **2026-08-31** · drivers `tools/gate_body_identity.py`,
`tools/path_key_vocabulary_probe.py`, `tools/extraction_domain_counterfactual.py`

`#612` merged the collapse meter and gave the number: **67.5% of law-bearing gate code still
executes in seat files**, 4 forked functions, 45 sloc. dp's direction after merging it was to
make one-gate-for-all the priority, with the observation that we have been mucking around.

We have. This is why, and it is not slowness — it is that the meter measures one half of the
gate and the collapse has been working on that half.

## 1. What the 67.5% does not count

The engine owns `path_in_scope`. It has been hardened four separate times against real
defects: codex `#169` (`startswith("/tmp")` matching `/tmpfoo`), kimi `#940 B5` (the absolute
branch judged on its lexical first segment, so `<ws>/repo-a/../repo-b/secret` was GRANTED),
GPT fleet-review blocker 8 (home matched as a substring, so `~/.kimi-code-evil/x` read as the
member's own home), and `#596`.

None of that runs unless the path is in the event. Putting it there is **not the engine's
job**. Each seat builds `NormalizedEvent.paths` itself, before the engine is called, from a
hard-coded list of argument key names:

| seat | where | keys |
|---|---|---|
| claude-code | six literal re-spellings of one tuple, plus a `_PATH_KEYS` constant most of them do not use | `file_path` `path` `notebook_path` |
| codex | `path_targets` | `file_path` `path` `notebook_path` |
| kimi | `path_targets` | `file_path` `path` `notebook_path` |
| gemini | `path_targets` | the three above, plus `absolute_path` `dir_path` `pattern` `paths` `file_paths` `include` `exclude` |

**Union 10 keys. Agreed by all four: 3.** The predicate is 32.5% collapsed and the domain it
is applied to is 30% agreed, and only the first of those two numbers is on a ratchet.

This is the shape of the whole problem. A guard is as strong as its domain, and the domain
was never part of the collapse.

## 2. It is a fail-open, and it is 19 calls in the local corpus

`tools/path_key_vocabulary_probe.py` reads the key vocabularies out of the gate sources (never
restating them, so it cannot drift from the gates it is about) and scores every tool call in
the local transcripts against them.

```
tool calls read                 115457
  carrying a path-looking value 28161
  with a path under a key the claude-code gate does NOT enumerate: 71
  of those, on a tool the policy DOES gate (not READ_CLASS):       19
```

The 52-call remainder is `Glob`/`Grep` `pattern`, and those are **not** a hole: the core puts
both tools in `READ_CLASS`, so the policy declares them free. Pooling them would have made
this finding read four times larger than it is. The 19 that remain are on tools the policy
does gate:

| key | calls | tool | what the tool does with it |
|---|---|---|---|
| `files` | 7 | `SendUserFile` | sends the file OUT |
| `filename` | 6 | `mcp__playwright__browser_take_screenshot` | WRITES a PNG there |
| `planFilePath` | 5 | `ExitPlanMode` | writes a plan file |
| `repo` | 1 | `mcp__gitnexus__detect_changes` | reads a repo |

The value counter is deliberately a floor: whitespace, `|`, `\`, `$`, quotes and single-segment
strings are all rejected, which drops real paths embedded in prose. Undercounting is the right
direction for a claim that something is unguarded.

## 3. The verdict is decided by the key name, not by the policy

`tools/extraction_domain_counterfactual.py` holds tool, destination and scope fixed and varies
only whether the destination was extracted. Scope is a fixed one-repo tuple supplied by the
driver, not the live grant of whichever seat runs it.

```
tool                                      key            as built  extracted disagrees
mcp__playwright__browser_take_screenshot  filename       allow     deny      YES
SendUserFile                              files          allow     deny      YES
ExitPlanMode                              planFilePath   allow     allow     no
mcp__gitnexus__detect_changes             repo           allow     deny      YES

control  Write file_path=<ws>/metalinxx/x.png -> deny   (same directory, enumerated key)
```

Same destination, same scope, same engine. `Write` to that directory is denied; a screenshot
to it is allowed. The difference is which list the argument name is on. `ExitPlanMode` is the
honest negative: its path is under a home marker, so it is in scope either way.

## 4. The two seats hold contradictory rulings, and each one is right

`pattern` is the sharpest case, because it is not drift — both seats decided deliberately and
wrote down why.

- **codex/kimi exclude it.** The comment: *"'pattern' (Glob/Grep) is deliberately NOT here —
  it is a matcher ('\*.md', a regex), not a filesystem reach... Checking the pattern as a path
  false-denied every Glob whose pattern didn't look like a granted repo (Kimi live,
  2026-07-23)."*
- **gemini includes it, and adds the list-valued glob keys.** The comment: *"read_many_files
  takes `include`/`exclude` GLOBS... Scanning only paths/file_paths skipped Gate-1b for this
  tool entirely — an out-of-scope `include:["../restricted-project/**"]` was ALLOWED."*
  Source-verified against the harness's own tool declarations.

One seat learned an availability incident, the other a reach incident, neither fix reached the
other, and both are still live today. **A naive collapse loses one incident per key it
resolves.** Union re-imports codex's false-deny; pick-a-winner re-opens gemini's hole. That is
the real reason this has been mucking around: the remaining forks are not sloppiness to
delete, they are institutional memory in a form nothing can merge.

There is a rule that satisfies both records at once, and neither seat implements it: **a glob
pattern's literal prefix — the part before the first wildcard-bearing segment — is the reach;
the wildcard tail is a matcher.** `*.md` has an empty prefix, so no reach constraint, so
codex's Glob is not false-denied. `../restricted-project/**` has the prefix
`../restricted-project`, which resolves and scopes, so gemini's hole stays closed.
`tools/glob_prefix_reach_candidate.py` runs all three rules over both incident records:
codex/kimi fails one, gemini fails the other, the candidate satisfies both.

### The first version of that candidate was wrong, and how it failed is the better finding

Run over every `pattern` value in the corpus, the candidate denied **802 calls** — nearly all
of them ordinary Grep regexes. `def step` contains no wildcard character, so the whole regex
read as a literal relative path, so out of scope, so denied. That is *codex's 2026-07-23
incident, reproduced by the rule proposed to prevent it.*

The cause is not the rule. It is that **`pattern` is a glob under `Glob` and a regex under
`Grep` — one key name, two languages.** Restricted to the tool whose `pattern` is actually a
glob, the corpus has 166 distinct patterns over 3,070 transcripts, and the candidate hands the
scope check a strict prefix of what gemini hands it, so it cannot deny anything gemini allows.

So the domain table cannot be keyed on argument name at all. It has to be keyed on
**(tool, key) → value kind**. Every seat's `path_targets` is keyed on name alone, which means
every seat's extraction is unsound in the same way, and the two incidents are both instances of
that one defect rather than two competing policies. The fork is not a disagreement about law.
It is two seats routing around the same missing type.

## 5. What is actually left to collapse

`tools/gate_body_identity.py` compares the duplicated bodies as normalised ASTs (docstrings
and comments dropped, every string constant and identifier kept — a different marker IS
different law). Worst pair-class wins, so nothing is graded on its easiest pair.

```
IDENTICAL   4 name(s)   205 sloc (14.1%)   _claim_self_write _detect_workspace
                                           _role_bridge _witness_gate_self
NEAR        2 name(s)   187 sloc (12.9%)   _gate_self_call _tally_scope
DIVERGENT   7 name(s)  1058 sloc (73.0%)   main _attempted_summary
                                           _fail_closed_internal_error deny
                                           path_targets _load_mechanism command_of
```

That reorders the work. 205 sloc is a **move** — one body, no behaviour to argue about.
`_role_bridge` (36 of the 205) was committed on `cbp/collapse-slice2-role-bridge` at
`f910324` by a co-seat sharing this checkout, mid-way through this measurement; the table
above is the state at `6a12873` and will read 3 names / 169 sloc once that lands. `main` is 713 of the 1058 divergent sloc across four seats
and is wiring, not law. Which leaves roughly **345 sloc of genuinely divergent law** — and
`deny` and `path_targets` are in it, which is to say the refusal path and the reach domain are
the two things the fleet still spells four ways.

## 6. What this changes about the plan

1. **Put the domain on the ratchet.** The meter should print key-vocabulary agreement (3 of 10
   today) beside the 67.5%. A collapse that moves the second number while the first stays at
   30% has not collapsed the gate.
2. **Extraction cannot be a key list — of any length.** Three of the four gated holes are MCP
   tools, whose argument names are unbounded and arbitrary, so a hard-coded list is complete
   only against the built-in tools it was written for. And §4 shows a list keyed on name is
   not merely incomplete but unsound: the same name carries different value kinds under
   different tools. The fix is not a longer list; it is a table keyed on (tool, key) with the
   value kind declared, plus a default for names nobody has classified.
3. **Convert the gap from silent to loud, without new denies.** A path-shaped value under an
   unenumerated key should be WITNESSED, not denied. No false-deny risk, and the domain gap
   becomes self-reporting instead of needing a probe like this one to find it. Today the only
   reason we know about those 19 calls is that somebody went looking.
4. **Land the 205 identical sloc**, and treat every remaining divergence as an incident record
   until its provenance is read. Each one may be a bug in the copy nobody measured — or the
   only surviving memory of a live failure.

## Limits

One seat's transcripts (claude-code, this box). The 19 is a floor by construction, and it says
nothing about how many of those calls would have been denied had they been seen — three of the
four keys reached ungranted directories in the counterfactual, but the wild calls were not
re-run against live grants. gemini has no fire script and no mesh log, so its ten-key
vocabulary is the best-covered and the least exercised. No behaviour was changed by this work;
it measures and it names a rule, and the glob-prefix rule is argued from two written incident
records, not yet implemented or tested against them.
