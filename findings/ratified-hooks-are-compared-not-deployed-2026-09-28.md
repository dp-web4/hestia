# Ratified hooks are compared against, never deployed from

**2026-09-28, cbp-claude.** Researched at dp's request while specifying the Discover bypass/restore
switch. dp said the vault MUST hold the location and SHA of each ratified hook, against which the
live hooks are compared **and from which they are deployed on restart and restore**. He also said
that if this is not the case, the reason should be researched and documented, but not yet fixed.
Measured on origin/main at `9dc610c`.

## The requirement, clause by clause

| clause | state | where |
|---|---|---|
| the vault holds the location and SHA of each ratified hook | **in place** | `core/src/vault/gate_integrity.rs`: `GateExpectations` = {path → `sha256`, `plugin_id`, `ratified_at`, `note`}; written only by the operator-gated ratify (#1132, per gate in #1150) |
| live hooks are compared against it | **in place** | `/api/gates/verify`; `server/gate_watch.rs` at startup and on every worker tick (#1085), witnessed as `gate_integrity_finding` / `gate_integrity_resolved`, and projected to `status/gate-integrity.json` |
| live hooks are deployed FROM it on restart | **not implemented** | see below |
| live hooks are deployed FROM it on restore | **not implemented** | see below |

## Why the deploy half does not exist

1. **Repair was scoped out when the monitor was built.** `gate_watch.rs` says so in its module
   doc: *"What this does not do: repair, ratify, or refuse. A rewritten gate is reported."* That
   followed dp's choice of option 1 on #1085 (*"the daemon verifies, the installer reads"*). #294
   asked for monitoring against a vault-stored version and hash. #481 asked that the deployed gate
   be defined as one artifact. Neither issue carries "deploy from the ratified record" as a
   deliverable, so the requirement was never assigned to anyone.
2. **The vault holds hashes, not bytes.** A digest can verify a file but cannot re-create one.
   The only content-addressed byte store is `$HESTIA_HOME/shared.builds`, and it holds the shared
   decision engine (`RUNTIME_MANIFEST.txt`), not the hook entrypoints. No store could serve the
   bytes of a ratified hook.
3. **The registration edge is not in the vault at all.** Which command each harness runs on
   PreToolUse lives only in the harness's own config (`~/.claude/settings.json`,
   `~/.codex/config.toml`, `~/.kimi-code/config.toml`, `~/.gemini/settings.json`), and
   `deploy/register-members.py` renders it from repo templates. A change that re-points the
   registration and leaves the ratified file untouched is therefore not a change to anything the
   vault records. The Discover bypass switch makes exactly that change.
4. **A restart runs no install.** `hestia-deploy` compares the checkout's `git describe` with the
   running daemon and, when they match, *"log[s] 'current' and stop[s] (most cycles)"*.
   `install-members.sh` runs only when main has moved. So restarting the daemon re-projects no
   hooks.
5. **When an install does run, its source is main, not the ratification.**
   `install-members.sh` installs from the deploy checkout and records `current-build.json`. The
   ratified expectation is consulted afterwards, as a comparison, never as the source. A deploy
   can therefore install bytes nobody ratified, and has no way to put back the bytes somebody did
   ratify. The other hook writer, `orchestrators::install` (the dashboard's orchestrator Connect,
   `http.rs` `orchestrator_connect`), installs from templates compiled into the daemon. That is
   also not the ratification.
6. **Registration repair is additive by basename.** `register-members.py` adds only hooks whose
   target basename is missing from an event, and never rewrites an existing entry. So even an
   install run cannot undo a re-pointed PreToolUse entry. Whether it leaves the stub alone or adds
   a second gate entry beside it is what the bypass PR's isolated test measures.

## What would have to exist (not built here, per dp)

- **A ratified hook set that is content-addressed**, meaning bytes and not only digests, keyed by
  the same path → sha the vault holds. One possible shape: `shared.builds` extended to hook
  entrypoints.
- **The registration edge in the ratified record.** For each member and event, the command the
  harness must run, so that a re-pointed registration is a finding, and the ratified command is
  something that can be restored.
- **A projection step at daemon startup, and on restore, that writes the ratified bytes and the
  ratified registration**, then verifies them with the existing `gate_watch` pass. That pass would
  stay report-only, because the projection is a separate, witnessed act.
- **The installer made subordinate to the ratification.** Installing bytes that nobody has
  ratified would become a proposal that a human ratifies, not the new state of the machine.

## How this will be tested

The Discover bypass/restore PR is an instrument for these claims. It re-points one member's
PreToolUse registration to a fail-open stub, in an isolated home with an isolated daemon, then
measures four things:
- which existing detector fires (predicted by this reading: the verify pass reports FINDINGS, with
  the original file verified and the stub unratified, not MODIFIED);
- whether actions are still logged;
- whether a daemon restart re-projects the ratified hook (predicted by this reading: no);
- how long live drift detection takes.

A prediction here that the measurement contradicts is a correction to this document.

## Measured (#1158, isolated daemon, 2026-09-28): one prediction was wrong, and in the worse direction

| prediction | measured |
|---|---|
| verify reports FINDINGS: original gate `verified` and the stub `unratified` | **wrong.** `status: VERIFIED, findings: 0`. The bypassed gate reads `verified, discovered: false`; the stub is not discovered as a gate at all. With no other gated member, verify answers `UNKNOWN` ("no gate-role hooks discovered"). The `gate_watch` tick 2m50s later wrote VERIFIED, with no chain row. (#1156) |
| a restart re-projects nothing | **confirmed.** After a restart the stub is still registered. (#1157) |
| register-members cannot undo a re-pointed entry | **confirmed, and worse for codex.** It appended a second gate block beside the stub. For claude-code there is no template yet (#1142), so it skipped. (#1157, #330) |
| actions are still logged while bypassed | **confirmed.** The member's real witness landed an outcome row. |
| the vault holds location + sha | **confirmed.** |

Why my prediction was wrong: `gate_integrity::verify` hashes each ratified PATH and never asks
whether that path is still the one REGISTERED. The stub is not hestia's, so it never enters the
discovered gate set. So the cheapest bypass there is (leave the ratified file on disk and re-point
the registration) is invisible to every gate-integrity surface. Only agent-inventory's MISWIRED
verdict catches it, and that verdict reaches neither the chain nor the tick. This is point 3 above,
measured: **the registration edge is the thing the vault does not hold, so it is the thing nobody
checks.**
