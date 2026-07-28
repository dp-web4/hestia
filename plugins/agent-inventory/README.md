# agent-inventory

**Who is installed here, what could govern them, and who is actually governed.**

hestia can only see what routes through hestia. An agent installed but ungoverned is
therefore *structurally invisible to it* — the absence has to be found from outside.
This is agent-atlas's read half (dp, 2026-07-26) doing that job: the registry says what
could be here, the filesystem says what is, and the delta is the answer.

## Three inventories, not one

The first cut conflated them, and the conflation hid the part you can act on:

| | inventory | source |
|---|---|---|
| **A** | **installed** orchestrators | a real executable on `PATH` |
| **B** | **available** hestia plugins | `hestia/plugins/*/` — built anywhere in the fleet |
| **C** | **governed** | installed ∧ plugin available ∧ wired ∧ the wiring resolves |

The gaps between A, B and C each have a different remedy, which is why they are reported
separately rather than as one "governed: n/m":

| gap | meaning | remedy |
|---|---|---|
| `miswired` | a **gate** event is wired to a target that does not exist, and the target is hestia's **or unattributable** | **worst state** — reads as covered while failing open. Fix now. |
| `miswired_3p` | same, but the target is *positively* someone else's tooling | fix it in their repo, or live with it — it does **not** demote `governed`, because no hestia work could clear it |
| `partial` | observation wired, **enforcement absent** | the state a machine sits in while it *looks* covered. Wire the gate. |
| `ungoverned` | installed, plugin exists, not wired | run that plugin's `install.sh` — cheapest fix |
| `ungovernable` | installed, no plugin exists | someone must build the adapter |
| `dormant_plugin` | plugin exists, harness not installed | nothing. Ready if it ever lands — a plugin built on nomad governs CBP the moment the CLI arrives. |
| `unknown` | a scope could not be established | **read `scope` in the report.** Not a clean result. |

`DEAD_HOOK` is `miswired`'s non-gate sibling: a hook that resolves to nothing on a
non-gate event. It loses evidence rather than opening a door, so it is reported without
changing status.

`FRAGILE` is orthogonal: governed, but the wiring is on `/tmp` (cleared by reboot) or on
the `/mnt/c` 9p mount (cold reads can outlast a hook timeout, and these hooks fail OPEN).

## Triggers

| when | how |
|---|---|
| on launch | `SessionStart` hook, `--workspace <ws> --brief`, 10s timeout |
| operator on demand | `hestia-agent-inventory --workspace <ws> [--brief] [--no-witness]` |
| periodic | `systemd --user` timer, hourly (`OnBootSec=3min`, `Persistent=true`) — **Linux only** |

`install.sh` wires **every trigger this platform can carry** — all three on Linux — and
writes the resolved workspace into each of them.
It has to: a systemd unit's `Environment=` is not the shell's environment and not the
hook's, so the first cut — which set `HESTIA_WORKSPACE` on the timer only — left the
other two triggers falling back to the compiled-in CBP default. Measured on Thor
(2026-07-26): the hourly timer read the right workspace while both the terminal and the
SessionStart hook answered `UNKNOWN | agent-atlas registry not readable at
/mnt/c/exe/projects/ai-agents/…`. Honest, per rule 4 — and inert, on every machine that
is not CBP. **Scope has to travel in the command, not in one trigger's environment.**

Resolution order is `--workspace` → `$HESTIA_WORKSPACE` → compiled-in default, and which
one answered is reported as `scope.workspace_source`.

**And the workspace `install.sh` writes must not depend on where `install.sh` was run
from.** It was `$SRC_DIR/../../..`, which is correct from the primary checkout and silently
`/tmp` from a detached worktree — baked into all three triggers at once, failing in the
reassuring direction (nothing ungoverned is ever found under `/tmp`). The sharp part is
that the fleet's own sibling-session protocol *requires* installing from a detached
worktree on a contended box, so the documented-safe path was the one that mis-scoped, and
the mitigation was knowledge held by whoever read the PR description. It now derives from
`git rev-parse --path-format=absolute --git-common-dir`, which resolves to the primary
repo's `.git` from either place, and **refuses rather than guessing** when that fails —
`HESTIA_WORKSPACE` is the documented override. A resolved workspace with no
`agent-atlas/talk-to` under it warns at install time, once, instead of as an `UNKNOWN` from
three triggers an hour.

The runtime copy lives at `~/.local/bin/` on **ext4**, not in the repo on 9p — this check
must not become an instance of the fragility it reports. Re-run `install.sh` after editing
`inventory.py`; it converges the `SessionStart` hook to **exactly one** entry running this
binary — rewriting the first, deleting any others, and asserting the invariant rather than
arguing it, because "no stale entries left" was silently false twice: first when the match
was on the whole command string, then again when a stale entry and an already-correct entry
coexisted and both were rewritten to the same string.

Every run witnesses to the chain as `agent_inventory`, **including clean results**: a
record that only ever holds failures cannot distinguish "checked, fine" from "never
checked".

## Scope is the finding

Thor reviewed the first cut (`209e154`) and found it reporting `OK` on a machine with two
configured, enabled, **dead** `PreToolUse` gates. Re-running that review on CBP found the
same two dead gates here. Five blind spots, one error: **the check treated "where I
looked" as "where it is"** — and every one of them failed in the *reassuring* direction.

| it looked | the truth lived | consequence |
|---|---|---|
| `$HOME/.claude` | project + local scope too | on both machines the enforcement half lives *entirely* in the last two |
| the working tree | `origin/main` | a feature-branch checkout flips the remedy from `install.sh` to "build an adapter" |
| depth-1 children of the workspace | repos nest | a third dead `PreToolUse` gate, in `synchronism/manuscripts/`, was simply out of reach of the glob |
| a compiled-in default path | `$HESTIA_WORKSPACE` | correct on CBP, `UNKNOWN` everywhere else |
| the substring `hestia` | real gates never say it | deleting codex's live gate still reported `OK` |
| `$PATH` | `~/.nvm`, `~/.pyenv`, … | `1 installed` from a hook, `3 installed` from a shell, same machine, same minute |

So the check now **reports the scope it achieved** — `scope` in the JSON carries the
workspace and where it was resolved from, every executable search root, every config file
read, the project scan depth, and both the ref `plugins_available` was resolved from
(`plugins_source`, `plugins_ref`) and the ref the checkout happens to be sitting on
(`worktree_ref`). And **any scope it could not establish degrades to `UNKNOWN`, never to
`OK`.**

## A sixth blind spot: the degradation was the wrong size

McNugget reviewed this file from a Mac mini with no `agent-atlas` clone and found the
guard above doing the thing the table is about, one level up. `UNKNOWN in 0.079s`, before
`search_roots()`, before the walk, before a single hook target was `stat`'d — **"could not
look" applied to dimensions it could look at.** A dead `PreToolUse` gate is a `stat` call,
not a registry lookup; so are the A inventory, `FRAGILE`, and `hook_timeout_finding`.
Inventory B is read from `plugins/` at `origin/main` and never touched atlas either. The
three dead gates this README is proudest of catching would have been caught on an
atlas-less machine — the guard just never got there.

What atlas actually supplies is the **enumeration**: the universe of agent ids to go
looking for. So that is what its absence now costs, and only that. The run falls back to
`ALIASES` ∪ the plugin registry, walks everything, and carries the gap in `unknown[]` so
the status ladder can never reach `OK`. Measured on CBP the same day, atlas present vs.
atlas hidden:

```
atlas   : OK      45 ids enumerated   4 installed, 6 plugins, 4 governed   dormant=[cursor, openclaw]
degraded: UNKNOWN 12 ids enumerated   4 installed, 6 plugins, 4 governed   dormant=[cursor, openclaw]
                                      + ENUMERATION PARTIAL on the brief line
```

Identical findings, 33 fewer ids looked for, and it still refuses to say `OK` — which is
the whole property. Sabotage-checked: delete the `unknowns.append`, and the degraded run
reports `OK` with the same warning printed next to it. The warning is not the guard.

`scope.agent_enumeration` and `scope.agent_enumeration_complete` say which list was used,
so a fleet dashboard can tell *"McNugget has no codex"* from *"McNugget never looked for
one."* The old UNKNOWN payload was `{status, machine, reason}` — no `scope` key at all, in
the one case where scope was the entire story. There is now no path that emits without it.

## The check has to find its own missing trigger

Same review, on the same box: `install.sh` is `set -euo pipefail` and step 2 called
`systemctl --user daemon-reload` unconditionally. On Darwin that is **exit 127**, and the
script dies there — *after* step 1 has installed the binary and pinned the workspace into
it, and *before* step 3 wires the `SessionStart` hook. Reproduced here on Linux by hiding
`systemctl` from `PATH`: binary present, `settings.json` untouched, exit 127 at line 119.

The residue is this plugin's own subject matter. `command -v hestia-agent-inventory`
succeeds, the on-demand surface answers, and **the two triggers that make it a *regular*
check are absent with nothing after the fact reporting it.** Failing loudly at line 119 of
a 230-line installer is honest at the terminal and silent a day later.

Two changes, and the second is the one that matters:

1. **The platform question is asked before step 1, not discovered at step 2.** Not by
   aborting first — steps 1 and 3 are a wrapper script and a JSON edit, platform-neutral
   both, and dropping two working triggers to punish the third is a worse trade than the
   bug. `install.sh` names the periodic backend up front, wires what the platform supports,
   and exits 0 having said what it skipped.
2. **The gap outlives the terminal.** `scope.periodic_trigger` is `stat`'d on every run,
   and `--brief` carries `NO PERIODIC TRIGGER` when the binary is installed with no
   schedule. Not Darwin-specific and the platform is not the finding: a Linux box whose
   install aborted at step 2, or whose units were removed later, reads identically. The
   states are named for how much they claim — `enabled` is systemd's own
   `timers.target.wants` symlink, `installed-not-enabled` is a unit file without it,
   neither promises a fire (a `--user` timer with lingering off does not run without a
   session). Stats only, no subprocess: this runs inside a hook with a budget.

**Darwin is in scope; the launchd agent is not written.** `install.sh` therefore installs
two of three triggers on a Mac and says so, and the check reports the third missing on
every run. That is a known, visible gap where there was an unknown, invisible one — but it
is still a gap, and closing it needs a box that can test it.

## The budget is part of the scope

CBP reviewed the depth-3 cut and found it right about *where* to look and wrong about what
that costs: **1.15s → 4m22s on CBP**, against a `SessionStart` budget of **10s**. A hook
killed at 10s does not degrade to `UNKNOWN` — it emits nothing, and nothing reads as clean.
So the fix for "answers `UNKNOWN` on every machine that is not CBP" had shipped "answers
nothing on CBP": the same error, one dimension over.

> **A check that cannot finish inside its trigger's timeout has not degraded to `UNKNOWN`.
> It has degraded to silence, which reads as clean.**

The cost was never the walk. It was `Path.resolve()` on all 3143 directories (a full
realpath chain each, on 9p), a redundant `is_dir()` re-stating what the dirent already
answered, the whole walk repeated once per agent, and then `.is_file()` on every candidate
× every glob. `scan_projects()` walks **once**, memoised, with `os.scandir`, resolves only
entries that are actually symlinks, and notices `.claude`/`.codex`/`.gemini` *in the dirent
list it is already holding* instead of stat-ing for them:

| | CBP wall-clock | `newfstatat` (Thor) | subprocess spawns |
|---|---|---|---|
| as submitted | 262s | 157,035 | 47 |
| walk rewrite | **5.8s** | **1,707** | **8** |

Same 30 findings on CBP, same 10 on Thor — this is a cost change, not a scope change. (The
spawns are `Registry.expects()`, which ran `git show` for all 45 atlas ids, 36 of them for
plugin dirs the registry already knew were absent.)

Two things that make this structural rather than a benchmark:

- **Scan `DEPTH+1`, descend `DEPTH`.** A directory only becomes a candidate project root
  once something has read *its* entries, so the deepest level must be scanned even though
  it is never descended into. Getting this wrong silently drops every project root at the
  deepest level — which is the exact class of miss that motivated going deeper at all.
- **An explicit walk deadline** (`HESTIA_INVENTORY_SCAN_BUDGET`). When it fires,
  `scope.scan_truncated` goes true, the stopping point is reported, and the `--brief` line
  — the surface a session actually reads — says `SCAN TRUNCATED`. Without that last part a
  short walk still prints a confident status, because the part it never reached
  contributes no findings.

### A budget that always fires is not a bound, it is a redefinition

The deadline shipped at 5s, and CBP's re-review found that 5s **never fit CBP**. Four
full-depth walks of the same 3143 directories:

| run | wall-clock |
|---|---|
| warm, quiet | 6.79s |
| cold (`drop_caches`) | 7.15s |
| cold (`drop_caches`) | 7.84s |
| warm, sibling `claude -c` working the tree | **9.31s** |

So it truncated on every run (3/3: 2373 / 2184 / 2157 of 3143 dirs) — and **both** scopes
it dropped were the depth-3 ones. The walk is level-order, so its budget goes breadth-first
and truncation is never a random sample: the loss is always at maximum depth, which is
exactly the level `DEPTH+1` was added to reach. Truncating honestly and reproducibly at the
one level that motivated the change is clause 5's failure in a smaller hat.

Two things the measurement corrected, recorded because this file's ethic is that the number
sits next to the claim:

- **Cold is ~1.1×, not an order of magnitude.** The deadline had been argued for on "warm
  is not cold" while nobody had taken the cold number. It is 7.15 / 7.84 cold against 6.79
  warm — a lower bound, since `drop_caches` clears the Linux page cache and the Windows
  side of 9p stays warm. The deadline is still right, but for the *original* reason (an
  unbounded 9p stall), not the one it shipped with.
- **Contention costs more than cold does.** The slowest run was warm with a sibling session
  working the tree — and on this fleet a contended box is the normal state.

The budget is therefore **12s**, clearing the slowest run measured anywhere. This costs
fast machines nothing: it is a *ceiling, not a cost*, and Thor (ext4, 1837 dirs) runs in
0.16s either way. A small budget does not buy speed; it buys guaranteed loss of the deepest
scopes on slow machines.

### The timeout is derived, not written down twice

Clause 5 couples two numbers in two files — the scan budget in `inventory.py`, and a
`timeout` that `install.sh` writes into `~/.claude/settings.json`. Either one moved alone
rebuilds the cliff (a 12s walk against a 15s SIGKILL is silence again), and nothing but
prose held them together. That is the mitigation rule 3 refuses, so there are now two seams:

- `install.sh` asks the binary (`--print-hook-timeout`, budget + 8s reserve = **20s**)
  instead of carrying its own copy, and *asserts* the written value afterwards. It also no
  longer leaves an existing entry's `timeout` alone — `setdefault` meant the machine most
  in need of the raise, one that already had the hook, was the one that never got it.
- `inventory.py` re-reads the installed hook at run time and reports drift as `UNKNOWN`
  (`hook_timeout_finding`). Install-time derivation stops them separating; this catches
  them being pulled apart afterwards by a hand edit, a second installer, or an
  `HESTIA_INVENTORY_SCAN_BUDGET` raised past a timeout already on disk. A check whose
  failure mode is silence is obliged to run itself against its own trigger.

### Where a truncated walk stopped

Because the walk is level-order, "how far did it get" is one integer, and the report says
it: `project_scan_levels_complete`, `project_scan_truncated_at_level`, and
`project_scan_level_progress` (`4/302` — parents done over parents at that level). This
replaces `unscanned_frontier`, which reported `len(frontier)` for the level in progress:
it counted parents already scanned and omitted every deeper level, reading `876 + 2305 =
3181` against a true 3143 on CBP. It erred toward alarming, which is the safe direction and
not the standard — a number emitted next to a claim has to be falsifiable.

**Stamping the ref was not enough.** The first cut reported `plugins_ref` and kept reading
the working tree, on the theory that a visible number is a falsifiable one. But B is what
A and C are *differenced against*, so an under-read propagates into the verdict rather
than sitting beside it. On Thor, whose shared checkout sits 103 commits behind main on a
sibling's branch, the same script at the same instant returned `claude: governed, status
UNKNOWN` from the tree and `claude: MISWIRED` from `origin/main` — and the stale one was
the reassuring one. `plugins_available` and `expects.json` are now read from `origin/main`
(a fetched read-only ref: no network, and safe while a sibling holds the checkout dirty),
falling back to the tree only when there is no fetched main — and saying so when it does.

Two consequences worth stating plainly:

- **Dead-target detection is not hestia-scoped.** A gate that resolves to nothing fails
  open no matter who wrote it (missing command → exit 127 → `GATE_PROFILE.md` §3 rule 2
  → ALLOW), so every hook target is stat'd regardless of owner.
- **Witnessing is not gating.** Post-hoc observation *cannot* fail closed. Plugins declare
  which events they must occupy in `plugins/<name>/expects.json`
  (`{"gate": ["PreToolUse"], "observe": ["PostToolUse"]}`) and a machine with observation
  but no enforcement reads `partial`, not `governed`.

Ownership is decided by **reading the target**, not by its path: hestia deploys its own
gate to `~/.codex/hooks/pre_tool_use.py`, which says "hestia" nowhere in its name and 36
times in its text. Judging by the path is the same judge-by-name error as `command -v`
matching shell builtins, one level up.

### Findings are owner-agnostic; verdicts are owner-scoped

Both halves of that sentence are load-bearing, and getting either wrong fails silently in
a different direction.

A dead gate is reported whoever wrote it — that half is above. But `governed` is a claim
about *hestia's* enforcement, and letting an owner-agnostic finding negate it pinned CBP
at `MISWIRED` over a devcontainer path in a third-party repo, with hestia's own gate live
and enforcing. The headline was unfixable by any amount of hestia work, which makes it
an alarm nobody can act on — the fastest way to train a fleet to ignore one.

So a dead **gate** splits by owner, and the default is what matters:

| evidence | tag | demotes `governed`? |
|---|---|---|
| hestia marker in the command or target | `MISWIRED` | yes |
| a marker from `THIRD_PARTY_MARKERS` | `MISWIRED-3P` | **no** |
| neither — *unattributable* | `MISWIRED` | **yes** |

The last row is the one to defend. For a missing target, content evidence is unavailable
*by construction* — the file is gone — so only the name is left, and hestia's own gates
deliberately live at nameless ext4 paths (`~/.claude/hooks/pre_tool_use.py`). If
unattributable meant "not ours", deleting hestia's migrated gate would read as
**governed with enforcement gone**. Ownership judged by name errs toward innocence; for a
gate, that is backwards (kimi-code, 2026-07-26).

`THIRD_PARTY_MARKERS` is therefore an allowlist of *strangers*, never an exemption of
ourselves, and it **will drift** — a new stranger tool is miswired-by-default until
someone adds it. That is the direction to drift in: a stale list of strangers fails loud,
a stale exemption of ourselves fails silent. The list is emitted in `scope` so a reader
can see which names bought a clean verdict.

`MISWIRED-3P` does not appear in the status ladder, on the `FRAGILE` precedent: real,
loud in `gaps` and in the one-line output, and not a gap in hestia's coverage of this
machine.

### Named future amendment: repo-provenance as a second attribution signal

Not built. Recorded so the design is on paper before the second case arrives, and so the
build is triggered by evidence rather than by taste (agreed claude-code ↔ kimi-code,
2026-07-26).

**Rule.** Walk up from the declaring `settings*.json` to its enclosing git repo and read
`origin`. A remote outside our orgs is stranger evidence, on equal footing with a marker:
`marker OR provenance → MISWIRED-3P`. Everything else in the table above is unchanged.

**Why it is worth adding.** It is available in exactly the case where the marker list is
weakest. For a missing hook target, content evidence is gone by construction — but the
`settings.json` that declares it still exists, and so does the repo around it. And a
remote does not drift on rename: it is not a name a tool author picked for a file. The
motivating case (`hook-handler.cjs`) offered nothing but a *helper filename*, the weakest
kind of name evidence there is.

**Its known hole fails in the safe direction, which is the actual argument.** A fork of a
stranger's repo reads as ours, so provenance misattributes a stranger's hook *to hestia* —
which demotes `governed`, loudly, and someone comes looking. Compare the marker list,
whose hole is an unlisted stranger reading as unattributable — also demotes, also loud,
but via a list that drifts on every rename. Neither failure mode touches the dangerous
direction, which is exempting *ourselves*; that is the property this whole section exists
to preserve, and provenance preserves it.

**Constraints on the build, all three load-bearing:**

1. **Additional signal, never a replacement.** The marker path stays. Provenance can only
   *add* `MISWIRED-3P`, never withdraw one.
2. **Record which evidence fired,** in the finding text, the same way `attribute()` carries
   its `why`. A future reader must be able to see what bought the exemption — a marker, a
   remote, or both.
3. **Build on the second live case, not this one.** One observed example is a thin base for
   a rule; speculative generality on a single example is how the marker list got its drift
   in the first place. Wrong-but-loud is tolerable until then.

## Three things it refuses to get wrong

Each is a defect this fleet actually shipped.

1. **`command -v` is not an installed-ness test.** It matches shell builtins — `continue`
   is a bash keyword and appeared as a phantom installed agent in the first hand-run.
   Resolve to a real file; never judge by name. (Same error as the gate's judge-by-mention
   bug, twice.)
2. **A config dir is not an installed agent.** `~/.foo` outliving an uninstall is
   `RESIDUE`. Installation is evidenced by an executable.
3. **A configured hook is not a working hook, and empty is not clean.** gemini-cli on CBP
   had `hooksConfig.enabled: true` pointing at `/tmp/gemini-live/hook.sh`, deleted by two
   reboots — enabled, resolving to nothing, failing open, presenting as configured. So
   the hook *target* is stat'd. And if the registry can't be read the status is `UNKNOWN`,
   never "nothing ungoverned" rendered out of "could not look".

The witness path itself shipped defect 3 in miniature: the first version fired one
unauthenticated POST, got 422, and printed a clean report that recorded nothing. It now
does the full MCP handshake with an attributed identity and reports success only off the
returned chain hash. An inventory of who is governed is itself an act; an unattributed
act is the thing this file exists to find.

## Three things it refuses to get wrong — and a fourth

4. **A check must report the scope it achieved.** A governance check whose blind spots all
   read as clean manufactures exactly the confidence it exists to withhold. See
   *Scope is the finding* above. This is rule 3 (`empty is not clean`) generalised from
   the registry to every dimension the check reads.

## Status on CBP (2026-07-26)

**`MISWIRED`** — 4 installed (claude, codex, gemini, kimi_code_cli), 6 plugins available,
3 governed, 0 unknown. `claude` is miswired: three enabled `PreToolUse` gates resolve to
nothing.

```
private-context/.claude/settings.local.json  PreToolUse -> web4/claude-code-plugin/hooks/pre_tool_use.py  (gone)
Synchronism/.claude/settings.local.json      PreToolUse -> web4/claude-code-plugin/hooks/pre_tool_use.py  (gone)
ruvector/.claude/settings.json               PreToolUse -> /workspaces/ruvector/...  (devcontainer path)
                                             [VOID 2026-07-27 — see below]
```

The first two are the same defect Thor reported on Thor, on the machine that wrote the
check. CBP's **user**-scope gate is live and enforcing — verified incidentally during this
work, when a daemon deny refused an `rm -rf` from this session — but it is **fail-open**:
`HESTIA_PRE_FAIL_CLOSED` is unset, and on 2026-07-26 the legacy fallback engine decided 73
recorded calls (74 attempted; one record destroyed by a torn write in `~/.web4/r6/`). The
dead ones are one scope down, which is precisely why the first cut could not see them.

Prior reading at `209e154`, same machine, same hour: `OK — 1 installed, 1 governed`.
Every difference is a blind spot, not a change on disk.

### Later the same day: `UNKNOWN` — 4 installed, 4 governed

**Superseded 2026-07-27 — the earlier account of these three was wrong in both directions.**

- **`ruvector`** — VOID, not fixed. The `$CLAUDE_PROJECT_DIR` rewrite was **reverted**: the
  repo is a fork of `ruvnet/RuVector` (external work), and rewriting a third party's
  devcontainer config to make our dashboard read clean was the wrong act. The local clone
  has since been deleted entirely, so the finding no longer has a subject. Attributing the
  fix to "a sibling session" was also wrong — it was this tool's own author.
- **The two `settings.local.json` gates** — NOT gone. They returned, and a third turned up
  at `Synchronism/manuscripts/.claude/` once the project scan got deeper (#47/#48).

Because the root cause was never the configs. It is
`claude-code/plugins/web4-governance/settings.template.json`, which still points every
project it installs at `web4/claude-code-plugin/hooks/` — a tombstone holding only a
README, since the plugin moved to `claude-code/plugins/web4-governance/hooks/`. Those dead
gates were not stale leftovers being cleaned up; they were being **manufactured**, which is
why they kept reappearing after each fix.

The lesson this section is now an example of: **a governance tool's own documentation is
state, and it goes stale like any other.** Two of the three claims above were false by the
time anyone read them, in the README of the check whose entire purpose is reporting
accurate state. Findings need an expiry discipline, or they become the thing they warn
about.



Two things worth keeping, because both cut against the change that shipped here:

- **Running the old code against the current filesystem gives the identical line.** The
  split is a no-op on this machine today. Its evidence is `test_inventory.py`, not the
  live report — and the reason that test file exists is that the live state was edited by
  another member mid-change. A verdict this load-bearing cannot be checked by "run it and
  look at today's machine."
- **The proposal's premise was too strong.** It argued the remedy "lives in a repo we do
  not own" — and then the repo turned out to be ownable and the config simply wrong
  upstream, where fixing it helps every clone rather than just this box. *Fix the
  stranger's config* is a third remedy neither member named, and it is the better one when
  it is available. The split is still right for the case where it genuinely is not; it is
  no longer justified by the example that motivated it.

`UNKNOWN`, not `OK`, because `HESTIA_WORKSPACE` is unset in this shell — rule 4 working
as intended.
