# PRD: hook ground truth — the repo publishes, the vault certifies, the daemon projects

**Status:** DRAFT, with dp's decisions recorded (§5). This records dp's design (2026-09-28) against
the measured gaps. Nothing here is built yet.
**Closes, when built:**
- the deploy half of dp's vault requirement (findings/ratified-hooks-are-compared-not-deployed-2026-09-28.md);
- #1156 (a de-registered gate reads VERIFIED);
- #1157 (a restart re-projects nothing);
- the definition gap in #481.

## 0. Directive (dp, 2026-09-28, verbatim)

> the hestia repo needs to have a directory with tested and maintained hooks for supported
> harnesses. those are the ground truth. install should create a local directory. when hook is
> published to the repo its sha should be in the comment and metadata. on restart, daemon populates
> live hooks from ground-truth directory. sha updated in vault on certified releases. repair/restore
> copies from gt. if gt doesn't match published sha it's flagged as miswired.

Earlier the same day: *"the vault MUST contain location and sha of each ratified hook, against
which the live hooks are compared and from which they are deployed on restart and restore."*

## 1. Why: measured

The findings doc and the Discover bypass instrument (#1158, isolated daemon) measured this:

- **The vault holds path and sha, and compares against them. It deploys nothing.** There is
  nothing to deploy from: the vault holds digests, not bytes.
- **Nothing holds the registration.** Re-pointing a member's PreToolUse at a stub, with the
  ratified file left on disk, read `VERIFIED` on verify and on the live tick. Only the
  inventory's MISWIRED verdict saw it.
- **A restart re-projects nothing.** `hestia-deploy` installs only when main moves, and installs
  main, not the ratification.
- **The registration writer is additive.** For codex it added a second gate beside the stub.

## 2. The model

```
repo: hooks-gt/<harness>/            tested, maintained, PUBLISHED   (the ground truth)
        ├── manifest.json            files + registration + sha per file + release id
        ├── <hook files>             each carries its published sha in a header comment
        └── registration.json        what the harness must run, per event (the edge)
             │  install / certified release
             ▼
local: $HESTIA_HOME/hooks-gt/<release>/   content-addressed copy (like shared.builds)
             │  vault: certified release id + per-file sha + registration digest
             ▼
live:  the harness's hook dir + the harness's hook config
             ▲
             └─ the daemon POPULATES the live set from local GT on every start, and on restore/repair
```

Four authorities, each doing one job:
- **Repo GT** is what is published.
- **Local GT** is what this machine holds.
- **The vault** is what the operator certified.
- **Live** is what runs.

A mismatch at any edge is a named finding.

## 3. Requirements

- **G1. One GT directory in the repo, per supported harness, and each member's version is its
  complete closure.** A unit holds:
  - the hook entrypoints: gate, witness shim, observe/hydrate;
  - the **registration** (event → command template);
  - a `manifest.json`.

  The shared engine (`plugins/_shared` + `RUNTIME_MANIFEST.txt`) is published as its own unit.
  **Each member's manifest pins the exact engine version and every engine file digest, plus
  every declared cross-unit file it executes** (`install.requires`; gemini runs claude-code's
  gate as its governor). The member's `gt_version` is a content address over all of it (GPT
  review of #1160). So:
  - certifying a member identifies its whole decision behaviour;
  - an engine change changes every member's version;
  - a global `shared` link moving can never silently change an older certified member.

  Members still move independently, and identical blobs are stored once (slice 2). This is
  #481's invariant, *every byte and configuration edge that decides admission belongs to one
  content-addressed artifact*, applied per member.
- **G2. The published sha is in metadata, and in a header comment for humans.** A file cannot
  contain its own hash. The canonical digest is therefore sha256 over the file with its
  `hestia-gt-sha256:` header line normalised to a fixed placeholder. The manifest carries the
  same digest. The manifest is what is checked; the header is a readable copy, and a header that
  disagrees with the manifest is itself a finding. CI recomputes both and fails on drift, so a
  hook cannot be edited without re-publishing.
- **G3. Install creates the local GT directory.** Install copies a GT release into
  `$HESTIA_HOME/hooks-gt/<release>/`, verifies every digest there, and flips a `current` link
  atomically. This is `shared.builds`' existing discipline, extended. Install writes nothing live.
- **G4. On every daemon start, the daemon populates the live hooks from local GT:** files, then
  registration. It does this through one witnessed act per member (`hooks_projected`: member,
  release, per-file sha, registration digest) and verifies the result with the existing
  `gate_watch` pass. **The projection replaces HESTIA-OWNED registration entries only** (GPT review
  of 34d91a5). The declared events also carry other providers' hooks (snarc, memory services,
  claude-flow), and those are preserved byte for byte. Ownership is decided by the same
  provenance rules as agent-inventory (#1144) and qualified from agent-atlas. An entry whose
  ownership is ambiguous is **not** rewritten; it is reported as a finding naming the entry.
  Within hestia's own entries the projection is exact, not additive: a re-pointed or extra
  hestia gate entry is replaced by the certified one. That is the opposite of today's additive
  `register-members.py`.
- **G5. The vault's shas change only when a member is certified.** Certification is PER MEMBER
  (§5.2): the operator certifies one member's GT version. That is today's ratify, re-aimed from
  "the bytes that happen to be installed" to "this member's GT version". The record is the GT
  release id, the per-file shas, and the registration digest, keyed by member. A new GT version is
  a PROPOSAL for that member until it is certified. The member's live hooks keep projecting its
  last certified version. Anything else running on the member reads MISWIRED (§5.3), not refused.
- **G6. Repair and restore copy from local GT.** Restore after a Discover bypass (#1158), repair
  of a MODIFIED gate, and repair of a de-registered one: each is "project the certified GT for
  this member", the same code path as G4.
- **G7. A local GT that doesn't match the published or certified sha is MISWIRED.** The edges
  checked are:
  - local GT against its own manifest;
  - local GT against the vault's certified release;
  - live against local GT, for both bytes and registration.

  Each mismatch is a named finding on the chain and in the inventory. A de-registered gate (the
  #1156 shape) is a finding, and Forget is not offered while the member declares a gate role
  (the #1150 fix).
- **G8. Discover bypass stays a session-scoped override.** G4 undoes it on the next start by
  construction, so a bypass cannot outlive the daemon session unless someone re-applies it.
  Today it survives a restart (#1157).

## 4. What exists to build on

| need | existing piece | gap |
|---|---|---|
| content-addressed local copy | `$HESTIA_HOME/shared.builds` + atomic `shared` link (#481 stage 1) | covers only `_shared`; extend it to hook files + registration |
| per-file digests in a manifest | `RUNTIME_MANIFEST.txt`, `current-build.json` `shared_engine[]` | a declaration without digests; hooks are listed per member in `expects.json` |
| registration templates | `plugins/<member>/hooks/hooks.json` (codex, gemini; kimi in #1149; claude in #1142) | rendered additively; not in any digest |
| live comparison | `gate_watch` (#1085), `/api/gates/verify` | reads paths, not registration (#1156) |
| operator certification | ratify per gate (#1150) | certifies installed bytes, not a release |
| one witness per harness | `hestia_witness_core` + identical shims (#1149) | would be published as GT files like the gate |

## 5. Decisions (dp, 2026-09-28)

1. **Directory: both, on purpose.** dp: *"two copies are the redundancy check."* `plugins/<member>/`
   stays the working source. `hooks-gt/<harness>/` is the published, tested copy. CI compares
   them: a difference that is not a re-publish is an unpublished change, and it is reported.
2. **Certification is per member.** dp: *"too many harnesses and no need to lock them together."*
   The vault record is keyed by member: GT release id, per-file shas, registration digest. A
   member moves to a new GT version without re-certifying any other.
3. **Everything is populated from GT, and a deviation is flagged, not blocked.** dp: *"anything
   deviating flagged as miswired -- that allows testing to proceed unimpeded but properly flags
   deviations."* This covers seats that run hooks from a checkout (HUB). A deviation is MISWIRED
   and is never refused, so a tester can run a modified hook and the fleet still sees that
   member as off-GT.
4. **Harness hook caching: marked stale where known, a documented limitation where not.**

## 5a. Harness hook caching: what is known, and what G4 must respect

| harness | behaviour | basis | consequence for projection |
|---|---|---|---|
| claude-code | **snapshot at session start.** Edits to the settings files take effect only after `/hooks` review or a restart. | Anthropic's Claude Code docs (documented, not measured here) | Every session connected before a projection is marked **STALE** until it restarts. |
| codex | **trust keyed by the COMMAND STRING.** A leg whose command changed is silently SKIPPED in non-interactive runs until it is re-trusted. | PRD_GATE_CONSOLIDATION §13 (nomad, measured) | **Stricter than caching: a projection that changes a registered command string disables that hook, fail-OPEN.** G4 must keep codex's registered command strings byte-stable across releases and change only file bytes. A command change for codex is an operator re-trust event, surfaced as such. |
| kimi | unknown | not measured | known limitation; measure (below) |
| gemini | unknown | not measured | known limitation; measure (below) |

**Known limitation (to stay in this doc until every row is measured):** for a harness whose caching
is unknown, a projection fixes the hooks on disk, but a running session may keep executing what it
loaded. The daemon cannot tell which. For harnesses known to snapshot, "stale" is derivable: the
daemon knows each session's first connect, `hestia_connect` with its `host_session_id`, and the
time of the last projection.

**Measure each unknown row once and record it in agent-atlas `talk-to/<harness>/descriptor.md`**
(a new field, e.g. `hooks_reload: session-start | live | trust-keyed | unknown`), so the qualifier
is data and not prose here. The method is already on file
(memory: measuring harness hook behaviour from inside a session): run a headless harness
subprocess, edit its hook config mid-session, and see which command the next event runs.

## 6. Slices (proposed order)

1. **GT manifest + header digest + CI check (G1, G2).** Pure repo work; nothing is deployed.
2. **Local GT store (G3), inert.** Extend `shared.builds` to immutable, deduplicated blobs keyed
   by digest, with a per-member closure index. It is storage only: nothing reads it to deploy
   until slice 4.
3. **Certification per member (G5), before any projection is activated.** Re-aim ratify at a
   member's GT version. The vault record is the member's closure (G1) plus the registration
   digest. Nothing may project from an uncertified `current` link (GPT review of 34d91a5).
4. **Startup projection + restore/repair from GT (G4, G6, G8)**, projecting only each member's
   last CERTIFIED closure. It resolves that member's pinned engine (not the global link),
   replaces only hestia-owned entries, keeps codex's command strings stable (§5a), and marks
   sessions of snapshot harnesses STALE.
5. **The mismatch findings (G7)** and the atlas `hooks_reload` measurements (§5a). Includes #1156's de-registered-gate finding.
