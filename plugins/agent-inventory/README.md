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
| `miswired` | wired, but the hook target does not exist | **worst state** — reads as covered while failing open. Fix now. |
| `ungoverned` | installed, plugin exists, not wired | run that plugin's `install.sh` — cheapest fix |
| `ungovernable` | installed, no plugin exists | someone must build the adapter |
| `dormant_plugin` | plugin exists, harness not installed | nothing. Ready if it ever lands — a plugin built on nomad governs CBP the moment the CLI arrives. |

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

## Status on CBP (2026-07-26)

`OK` — 4 installed (claude, codex, gemini, kimi_code_cli), 6 plugins available, 4
governed. 2 dormant (cursor, openclaw). 3 FRAGILE: claude, codex and kimi hooks all
resolve onto `/mnt/c`.
