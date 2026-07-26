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
| on launch | `SessionStart` hook, `--brief`, 10s timeout |
| operator on demand | `hestia-agent-inventory [--brief] [--no-witness]` |
| periodic | `systemd --user` timer, hourly (`OnBootSec=3min`, `Persistent=true`) |

`install.sh` wires all three. The runtime copy lives at `~/.local/bin/` on **ext4**, not
in the repo on 9p — this check must not become an instance of the fragility it reports.
Re-run `install.sh` after editing `inventory.py`.

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
| a compiled-in default path | `$HESTIA_WORKSPACE` | correct on CBP, `UNKNOWN` everywhere else |
| the substring `hestia` | real gates never say it | deleting codex's live gate still reported `OK` |
| `$PATH` | `~/.nvm`, `~/.pyenv`, … | `1 installed` from a hook, `3 installed` from a shell, same machine, same minute |

So the check now **reports the scope it achieved** — `scope` in the JSON carries the
workspace, whether it came from the environment, every executable search root, every
config file read, and the ref `plugins_available` was resolved from. And **any scope it
could not establish degrades to `UNKNOWN`, never to `OK`.**

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
and fail-closed. The headline was unfixable by any amount of hestia work, which makes it
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

All three dead gates above are gone, and **none of them was cleared by the owner split**.
The two `settings.local.json` gates were emptied when the plugin moved (still on the
operator queue: restore or ratify). The `ruvector` one was fixed at its source — its nine
hook commands were rewritten to `$CLAUDE_PROJECT_DIR`, correct in the devcontainer *and*
in every clone (`ruvector 1cb963c2`), by a sibling session, between this change's baseline
run and its verification run.

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
