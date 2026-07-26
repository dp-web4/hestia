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
| `miswired` | a **gate** event is wired to a target that does not exist | **worst state** — reads as covered while failing open. Fix now. |
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
| periodic | `systemd --user` timer, hourly (`OnBootSec=3min`, `Persistent=true`) |

`install.sh` wires all three, and writes the resolved workspace into **each** of them.
It has to: a systemd unit's `Environment=` is not the shell's environment and not the
hook's, so the first cut — which set `HESTIA_WORKSPACE` on the timer only — left the
other two triggers falling back to the compiled-in CBP default. Measured on Thor
(2026-07-26): the hourly timer read the right workspace while both the terminal and the
SessionStart hook answered `UNKNOWN | agent-atlas registry not readable at
/mnt/c/exe/projects/ai-agents/…`. Honest, per rule 4 — and inert, on every machine that
is not CBP. **Scope has to travel in the command, not in one trigger's environment.**

Resolution order is `--workspace` → `$HESTIA_WORKSPACE` → compiled-in default, and which
one answered is reported as `scope.workspace_source`.

The runtime copy lives at `~/.local/bin/` on **ext4**, not in the repo on 9p — this check
must not become an instance of the fragility it reports. Re-run `install.sh` after editing
`inventory.py`; it rewrites an existing hook entry in place (matching on the binary path,
not the whole command) rather than appending a second one.

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
check. CBP's **user**-scope gate is live and fail-closed — verified incidentally during
this work, when it refused an `rm -rf` from this session. The dead ones are one scope down,
which is precisely why the first cut could not see them.

Prior reading at `209e154`, same machine, same hour: `OK — 1 installed, 1 governed`.
Every difference is a blind spot, not a change on disk.
