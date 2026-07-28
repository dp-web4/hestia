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
| periodic | Linux: `systemd --user` timer, hourly (`OnBootSec=3min`, `Persistent=true`) |
| | Darwin: `launchd` user agent `io.hestia-agent-inventory`, hourly (`StartInterval=3600`, `RunAtLoad`) |

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

**Darwin is in scope, and the launchd agent is now written and run.** `install.sh`
completes on macOS (26.5, McNugget, 2026-07-28 — the first time it has), wiring all three
triggers. The agent was bootstrapped, fired by `RunAtLoad`, and exited 0 having written a
real report; `launchctl print` reports `run interval = 3600 seconds`.

The two backends are **not** equivalent, and the differences are named rather than
smoothed over, because each is a gap in coverage that a shared state name would hide:

| systemd | launchd | consequence |
|---|---|---|
| `OnUnitActiveSec=1h` | `StartInterval=3600` | equivalent |
| `OnBootSec=3min` | `RunAtLoad` | fires *at* load, not 3min after; costs boot quiet, not coverage |
| `RandomizedDelaySec=90` | — | no jitter for `StartInterval`; one local walk, so recorded as absent rather than fine |
| `Persistent=true` | — | **a fire missed while asleep happens once at next load, not once per missed hour.** systemd catches up; launchd does not |
| `loginctl enable-linger` | — | a `gui/` agent runs only while the user is logged in, and there is no user-agent equivalent of lingering. The honest remedy is a `LaunchDaemon`, which is a privilege escalation an observation-only check has no business asking for |

**A plist's existence was never the schedule.** Writing the launchd half surfaced that the
detector answered `launchd-agent-installed` from the glob alone — so a LaunchAgent with
`RunAtLoad` and no schedule key, which `launchctl bootstrap` accepts silently and `ls`
cannot distinguish, read as an hourly check. Measured against the pre-change detector: it
returned `launchd-agent-installed` and the `--brief` line was clean. That is the systemd
`installed-not-enabled` distinction with no state to hold it, on the side where the
positive answer was already the weaker one — and the first such artifact would have been
the one `install.sh` writes. The keys are now read with `plistlib` (in-process, no
`launchctl` subprocess, hook budget intact), and the states say how much they claim:
`launchd-agent-installed`, `-installed-no-schedule`, `-unparseable`. A non-dict root
counts as unparseable, not unscheduled: `plistlib.loads(b"<plist/>")` returns `None`
rather than raising, so "it parsed" is not "it is a job description".

**The installer asks launchd, not the filesystem.** `plutil -lint` is a parser, not a
validator — measured on macOS 26.5, `<<<junk` appended after `</plist>` still lints `OK`,
because it stops at the closing tag. So an unlinted plist is *removed* rather than left
where `ls` and the detector's glob would both read it as a wired schedule, and a linted
one is then checked against `launchctl print gui/$UID/<label>` for the interval launchd
actually holds. `launchctl load` succeeds on a valid plist and says nothing about the job.

**The interpreter is pinned, like the workspace.** The wrapper said `python3` and let
`PATH` resolve it. Measured with a throwaway LaunchAgent that printed its own environment:
launchd hands a `gui/` agent `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, so `python3` resolved to
`/usr/bin/python3` (3.9.6) under the timer and `/opt/homebrew/bin/python3` (3.14.4) in the
shell. Both printed a byte-identical `--brief` line here, so today it is benign — but step
3 derives the `SessionStart` timeout by running the binary under the *shell's* python3, and
the pair `--print-hook-timeout` exists to keep from drifting was pinned on one side only.
Not Darwin-specific: a systemd `--user` unit sets no `PATH` either. Not measured here, and
said as unmeasured: on a Mac without the Xcode command line tools `/usr/bin/python3` is a
stub, and the unpinned wrapper would be exit 127 from launchd while `launchctl print` still
showed a healthy job with the interval set.

**And on Linux the pin needs a floor** (cbp, 2026-07-28 — the cross-platform review the
shared edit asked for, and it did bite). `command -v python3` is a *stable* path on a Mac
and routinely an *ephemeral* one here: a venv, a conda prefix, a pyenv shim, a checkout
under `/tmp`. Measured on cbp — install with a venv active, then delete the venv:

```
pinned wrapper    env: '/tmp/hli-venv/bin/python3': No such file or directory   exit 127
unpinned wrapper  [agent-inventory] OK on cbp: 4 installed, 6 plugins, 4 governed  exit 0
```

The pin turned a survivable environment change into a permanent 127 — and did it
**silently**: `periodic_trigger()` still answered `systemd-user-timer-enabled` with
`installed_bin` set, the strongest state this plugin has, while every hourly fire was 127
and every `SessionStart` hook emitted nothing. That is exactly the shape named above for a
Mac without the Xcode CLT and marked *not measured*; on Linux it is reachable by a far more
ordinary route than a missing toolchain, so it is measured here.

The pin is still right — it fixed a real five-minor-version split between two triggers — so
this does not revert it. It gives it a floor: **pinned when the pin is there, `PATH` when
it is not, and the degradation reported rather than fatal.** The wrapper exports
`HESTIA_INTERPRETER_PIN_BROKEN`, and `interpreter_finding()` turns it into an `unknown[]`
entry and an `INTERPRETER PIN BROKEN` clause on `--brief`; `scope.interpreter` now carries
`sys.executable` on every run, broken or not, so two triggers can be differenced. A check
whose own wrapper exits 127 is an instance of the failure it exists to find. `install.sh`
also warns at install time when the pin is *already* known to be ephemeral, since that is
the one moment a human is watching.

Both halves are sabotage-probed to red, and the interesting probe is the first: **neuter
`interpreter_finding()` and the run recovers silently** — clean `--brief`, exit 0, pin
broken. The fallback is not the guard. The report is.

**And the fallback has to be probed, not found** (McNugget, 2026-07-28 — the Darwin side of
that review, measured end to end through a real launchd agent in a sandboxed `$HOME`).
`-x` and `command -v` answer *exists*; a floor needs *runs*. On a Mac without the Xcode
command line tools `/usr/bin/python3` is an xcrun stub — executable, 118KB, and once the
pinned directory is gone it is the **first** `python3` on the PATH launchd hands a `gui/`
agent (`/usr/bin:/bin:/usr/sbin:/sbin`). `command -v` finds it, so the `-z` branch never
fires, and it exits 1 without running a line of this file. What that looked like from the
operator's side, on the fired agent:

```
launchctl last exit code = 1
stdout (agent-inventory.log)   0 bytes          <- the --brief surface
unknown[]                      no entry         <- no INTERPRETER PIN BROKEN
scope.periodic_trigger         launchd-agent-installed   } strongest state,
scope.installed_bin            <the wrapper>             } every fire a no-op
stderr (agent-inventory.err)   xcrun: error: ...
```

Which is the same silence the floor was written to end, one platform over — installed,
scheduled, and never once run, with the one line of evidence sitting in a file nothing
reads. So the wrapper now runs the fallback once (`"$PY" -c ''`) before trusting it and
exits **loudly** if it cannot, and `install.sh` asks the same question of the pin before
writing it — the stub is exactly what `command -v python3` resolves to on a fresh Mac, so
the pin can be dead on arrival. 13ms, once, and on the install path or the
already-degraded path only. The general rule this makes twice on this thread: **the
degraded branch needs a check of its own, because it is the branch nobody is watching.**

**And the same question, asked of the pin** (cbp, 2026-07-28, the Linux side of that
review). The rule above was applied to one of the wrapper's two branches: `command -v` on
the fallback got probed, `-x` on the **pin** did not — and `-x` answers *exists* for the
same reason `command -v` does. A pin that is present, `0755` and unrunnable reached
neither guard: not `-x`-false, so no fallback, no `HESTIA_INTERPRETER_PIN_BROKEN`, no
finding. Straight to the `exec`, and dead there. The Linux route is as ordinary as the
Mac's stub, and this script *already warns about it three lines further down*: install
with a version-manager shim first on `PATH` (`pyenv`'s `shims/python3` — "re-resolves from
ITS own environment"), then let that version go. The shim stays executable forever and
exits 127 without starting python. Measured, sandboxed `$HOME`:

```
                                   before            after
exit                               127               0
stdout (the --brief surface)       0 bytes           the line, + INTERPRETER PIN BROKEN
unknown[]                          no entry          the finding, naming pin and fallback
--json                             0 bytes           scope.interpreter_pin_broken set
```

Note what it cost the floor specifically: the floor put `scope.interpreter` on **every**
run and turned a broken pin into a finding — but both live *inside* `inventory.py`, and
this is the one case where `inventory.py` never starts. **A report needs something alive to
emit it**, which is the sentence above pointed at the branch it did not cover. So gone and
cannot-run are now one case with one handling: fall back and **report** (never exit — that
is reserved for when the fallback cannot run either, the only state with nothing left
alive to report with). Cost, measured rather than asserted: one interpreter start per run,
30ms here against a ~4.6s `--brief` over the fleet workspace — 0.6%, cheap only because
that walk is 9p. On a local-SSD workspace it is a larger fraction, so it is a real trade.

**A third thing, found by installing it rather than reading it:** that review comment was
written into `install.sh`'s wrapper heredoc, which is **unquoted** — it has to be, it
interpolates `$PYTHON`, `$BIN` and `$WORKSPACE`. So its body is prose to a reader and
shell input to `bash`. The markdown backticks around `` `-x` `` and
`` `launchd-agent-installed` `` were **command substitution**: both ran during install
("command not found" ×2 on a clean install), and the shipped wrapper had holes where the
quoted words used to be — *"Found by , so the -z branch never fires"*. Nothing executable
broke, but only because those words named nothing; the backtick count was even **by luck**,
and an odd count is a hard `bad substitution` that writes a **zero-byte wrapper**. `bash
-n` does not catch it — it is valid shell — and no output of the plugin changes when it
happens. Since prose-in-shell-comments is this file's house style, that is a standing
hazard rather than a typo, so the backticks are escaped and `test_wrapper_heredoc_is_inert`
fails if an unescaped one comes back.

For symmetry with the Darwin numbers: on cbp a systemd `--user` unit resolves
`/usr/bin/python3` 3.12.3 and the shell resolves the identical path, so the pin buys
nothing here and cost the 127 above — which is why it needs a floor and not a Linux
exemption.

**The hazard is the heredoc, not the wrapper** (McNugget, 2026-07-28, measured on macOS
26.5 by installing it). `install.sh` writes **three** unquoted heredocs — `WRAP`, the
systemd `.service` unit, and the launchd plist — and the last two carry prose comments in
the same house style, with no guard. Probed: a markdown backtick pair inside an XML comment
in the plist heredoc, `<!-- ProcessType Background: throttled for `` `id -un` `` -->`. It
**ran** at install time and the shipped plist carried the installing user's name; `plutil
-lint` said `OK`, `bash -n` said clean, and the suite said `ok: 0 failure(s)`. And the
`$(`/`${` half of that guard had a hole of its own: it skipped any line containing `\$`
*anywhere*, which is nearly every prose line in `WRAP`, because they all quote `` `\$PY` ``.
Probed: `# prose about \$PY and the pin under ${HOME}/bin` passed green and the installed
wrapper had the sandbox path baked into its own sentence. Escapes are per **token**. So the
check now strips escapes per token and scans every unquoted heredoc; unescaped backticks
and `$(` are refused in all three (command substitution in a generated file is never
wanted), and `${` stays refused in `WRAP` only, because the unit and the plist exist to
interpolate. Four sabotage probes, all red, all with `bash -n` still clean.

**And the report about who the job runs as was the one thing taken on trust.** The
lingering report used `$USER` — on **both** platforms (`loginctl show-user "$USER"` on
Linux, the `gui/` session line on Darwin). Under `set -euo pipefail` an unset `USER` is a
hard abort, and it lands mid-install: measured with `env -i`, `rc=1`, stdout ending on
*"installed: hourly launchd agent … run interval = 3600s"*, an hourly job **loaded** in
`gui/501`, and **no SessionStart hook** — half-installed and reading as success, the same
shape as the Darwin abort that opened this thread, one variable instead of one missing
binary. `USER` is set by login shells and absent from scrubbed ones — containers, CI, and
anything `launchd` or `systemd` starts, which is exactly the automation that would run an
installer unattended. It is now `id -un`, which cannot be unset and is how `UID_N` three
lines away already did it. With `USER` unset the install completes all three steps, `rc=0`,
stderr empty.

**The cost number, on the other box** (McNugget's answer to the 0.6%). The probe is 17.9ms
on this box's pinned homebrew python3 3.14.4 and 13.8ms on `/usr/bin/python3` 3.9.6 (20
runs each) — cheaper than cbp's 30ms. The *run* is much cheaper too: `--brief` over a real
78G local-SSD workspace is **0.13s** warm and 0.30s cold, and 0.05s on this box's ordinary
atlas-less path. So the probe is **~14% of a warm run here, not 0.6%** — the ratio is 20×
worse on APFS-local, because on 9p the walk *is* the run and it hides everything. The trade
still stands, but not on that ratio: the denominator that matters is the derived hook
timeout the installer just wrote, **20s**, against which 17.9ms is 0.09%. A percentage of
the walk measures the workspace's storage; a percentage of the budget measures whether the
trigger still fits.

**The `$` half was still scoped the way the backtick half had just stopped being** (cbp,
2026-07-28, measured on Linux by installing). "Scan every heredoc, not the one where the
bug was found" got applied to backticks and `$(`. The `$` expansion check stayed **WRAP-only
and brace-only** — bare `$NAME` was refused nowhere. The probe is the `${HOME}` one directly
above with two characters deleted: `# prose about \$PY and the pin under $HOME/.local/bin`
passed the new guard green, `bash -n` clean, and shipped a wrapper reading *"the pin under
/tmp/hli7/home/.local/bin"*. That is the likelier typo, not the rarer one — this file's
house style writes `\$PY`, `\$PYTHON`, `\$HOME`, `\$PYENV_ROOT`, each one backslash from
expanding, and `${` was the harder form to type and the only form guarded.

Fixed as a **whitelist, not a wider ban** — a ban cannot work, because the unit and the
plist exist to interpolate, but the set that may expand is small, known, and was already
written down in prose: `WRAP` may expand `$PYTHON`/`$BIN`/`$WORKSPACE`, the unit
`$SRC_DIR`/`$BIN`/`$WORKSPACE`, the plist those plus `$HOME`/`$LAUNCHD_LABEL`/
`$LAUNCHD_PATH`/`$LOG_DIR`. Anything else — braced, bare, or unnamed (`$(`, `$$`, `$?`) —
fails, in all three, and an unrecognised heredoc gets the empty set so a new generated file
refuses every expansion until someone says what it meant. Eight sabotage probes: McNugget's
four still red, plus bare `$HOME` in `WRAP`, bare `$USER` in the plist, bare `$HOSTNAME` in
the unit, and `$$` in `WRAP`; `bash -n` clean in all eight. Ninth probe, the one that makes
the other eight mean something: adding `HOME` to `WRAP`'s set turns the bare-`$HOME` probe
green again, so the whitelist is what denies and not something else.

**`HOME` is the same sentence about the load-bearing variable** (cbp, 2026-07-28, measured
on Linux). The `USER` note is exactly right — a variable set by login shells and absent
from scrubbed ones is not one this script may assume — and it is true of `HOME`, which is
where all three triggers get *installed*. On bash 5.2 an unset `HOME` is **not** defaulted
(`PATH` and `SHELL` are; `HOME` and `USER` are not), so `env -i` died at the `BIN=` line
before step 1 with a bare `line 61: HOME: unbound variable`. **This is not the `USER`
shape** — it is a clean refusal with nothing installed, the right direction — so the change
is a diagnostic, not a behaviour change: it explains itself the way every other refusal in
the file does, and it is *refused, not derived*, because `id -un` can replace `USER` (the
kernel knows) while nothing knows which home an unattended install meant. It also closes a
measurement gap: the `USER` finding was measured with `env -i` on Darwin, where bash 3.2
supplies `HOME`; on Linux that same command never reaches line 411, so **the claim "with
`USER` unset the install completes all three steps, rc=0" is Darwin-only** and could not be
reproduced here until this guard existed. With `HOME` set and `USER` unset, Linux does
match it: rc=0, all three steps, hook at timeout 20s, `lingering: OFF`.

**The two queued nits, taken by whoever touched the file next.** The provenance line was a
real wrong output — `${HESTIA_WORKSPACE:+from HESTIA_WORKSPACE}${HESTIA_WORKSPACE:-…}`
prints the label *and then the value*, so a set `HESTIA_WORKSPACE` read `from
HESTIA_WORKSPACE/mnt/c/exe/projects/ai-agents`; now `from HESTIA_WORKSPACE`. The bare
`python3` in step 3 is **hygiene, not a defect**, and that is the honest size of it:
`install.sh` never modifies `PATH` and `PYTHON` is `command -v python3` from the same
process, so the two always resolved to the same file, and the xcrun-stub case cannot bite
because step 1 probes `$PYTHON` and exits before step 3 exists. No run on Linux
distinguishes them. Changed anyway, because "every trigger runs the interpreter we pinned"
is the invariant, and one of four call sites naming it a second way is how an invariant
stops being checkable.

**A negative result, recorded because it was worth checking:** the narrow launchd `PATH`
does **not** shrink the A inventory. The obvious worry — `claude` lives in
`~/.local/bin`, which is on the shell's `PATH` and not on launchd's, so the hourly run
would report fewer installed agents than the operator does, silently and in the reassuring
direction — is already closed by `EXTRA_BIN_GLOBS`. `search_roots()` searches `PATH` **∪**
the `$HOME` version-manager roots, and `.local/bin` is one of them. Measured, same binary,
same real `$HOME`, `env -i` with launchd's exact `PATH`: byte-identical `--brief` line to
the full-shell run. Rule #1's fix for nvm on CBP covers launchd on a Mac for free. The
divergence first seen here (`installed: []` from the agent, `['claude']` from the shell)
was a sandbox `$HOME` in the test rig, not a defect — chased to the bottom rather than
shipped as a finding.

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

The cost model was 9p-and-ext4 only until McNugget took the third filesystem
(2026-07-28), which was the one open number in this section:

| machine | filesystem | dirs @ depth 3 | walk |
|---|---|---|---|
| CBP | 9p, contended | 3143 | **9.31s** |
| Thor | ext4 | 1837 | 0.16s |
| McNugget | APFS, local NVMe | 1448 | 0.034 / 0.035 / 0.044s |

~270× headroom on APFS, so 12s is a ceiling there too and not a cliff. Warm, and reported
as warm — no `drop_caches` equivalent without sudo, though on local NVMe the cold delta is
small. Method worth keeping: `main()` cannot reach the walk on a machine with no atlas
clone, so the number was taken by importing `inventory.py`, rebinding `WORKSPACE` and
calling `scan_projects()` directly with `os.scandir` wrapped for the count — the walk
itself, not a proxy. That the number needed a workaround to measure at all is the same
guard this README's *sixth blind spot* section is about; the fallback enumeration means the
next machine can just run it.

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
