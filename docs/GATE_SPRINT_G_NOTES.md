# Sprint G notes — convergence, dispositions, and what deploy must decide

Last sprint of the gate-consolidation train (PRD §6.G / §7.2). Source-side G lands here;
the **deployed → observed** half is operator work by design (install-drift is invisible to
CI; §7.2 makes it a dashboard/operator surface, not a checkbox).

## 1. Duplication census after F

The census (in `test_gate_core.py`, shrink-only) stands at: codex 1, gemini 1, kimi 1
remaining local predicate carriers — kimi/codex's are the thin parity-pinned adapters
(call-site shims, not law copies; the census counts files, and the bodies are gone).
gemini still carries `lib/path_scope` local scope + subprocess spawn of the claude gate.

**Deleted in G:** the codex *marketplace* stale gate duplicate
(`plugins/codex/marketplace/plugins/hestia-codex/hooks/`, 227-line thin copy, 11.5KB vs
the live 42KB gate) — a checked-in second implementation nobody installs from; §7.1(1)
red until removed. If a marketplace package ships later it must carry the same content
digest as canon (§7.2(6)) — a rebuilt package, not a hand-fork.

## 2. gemini / cursor — migrate-or-retire (dp decision card)

- **gemini**: still topology-4 (spawns the claude gate; own scope lib). Migrating = the
  same B+E+F wiring the other shims got (~a day with the now-proven recipe). Retiring =
  delete the plugin + registration. **Decision: dp.** Until then gemini is the one
  remaining subprocess-delegating seat, and criterion 10's idle-parity claim EXCLUDES it.
- **cursor**: witness-only, no gate, no registration for one. Either it gains a gate
  (full B..F wiring) or its seat is formally declared observe-only in the member
  registry. **Decision: dp.**

## 3. society_pre_tool_use.py — disposition (PRD §10, resolved)

Measured 2026-08-13: exists ONLY as an installed file in kimi's hooks dir (21KB, Aug 7),
absent from the repo, **referenced by no registration** — a double orphan; post-E the
in-process mechanism IS the society-safety path. Disposition: **delete at next
install-members run** (deploy step, dp). The claude self-protection reference to the
filename stays in the closure floor (a file that reappears there SHOULD classify as
governance — reappearance is the attack, not the norm).

## 4. Digest convergence (rides #231, per kimi's sharpening)

Landed here: `hestia_gate_core.core_digest()` — the core self-hashes at import; the
unified recorder carries `core_digest` on every refusal record, so the running gate
ATTESTS what it imported (not a bystander hashing a nearby file). The dashboard/manifest
consumption (per-seat current/stale/unknown chip beside #231's build chip) is daemon-side
work, declared follow-up — the attestation is now in the records for it to read.
`attest_shims()` (Sprint B) remains the vault-hash "miswired" seam for shim files.

## 5. Criterion 10 — the gauge is in the tree

`tools/gate_class_t_probe.py`: per-member reached-verdict vs infra-fail-close rates from
the reputation ledger, with the Class T signature called out (a member with acts but ZERO
reached verdicts — the un-governed twin of a healthy member). Run idle, post-deploy:
`python3 tools/gate_class_t_probe.py --hours 6`. Acceptance: infra rate ≈0 and equal
across kimi/codex/claude; every active member shows reached > 0.

## 6. Deploy runbook (operator — the train installs together)

1. Merge the train tip (each PR fast-forwards into the next; the tip carries all).
2. **Decide R1** (GATE_SPRINT_F_NOTES): standing-repo scope has no daemon surface, so
   post-F live scope = launch-cwd + home + /tmp + grants. Either accept the tightening
   (recommended; grants exist for the rest) or hold deploy until a scope surface lands.
3. `deploy/install-members.sh` (operator ACK) — installs shims + shared modules to the
   registered hook paths; delete the society orphan in the same pass.
4. Install the mechanism/core/closure to the ext4 hook dirs (kills the last /mnt/c read
   on the gate hot path — the #387 follow-up this train subsumes).
5. `python3 tools/gate_class_t_probe.py` after a quiet hour → criterion 10 reading.
6. Dashboard follow-ups (daemon-side, declared): per-seat core-digest chip; escalation
   approve→claim loop-close (#366) — the FP-sweep list in the sprint log is the live
   evidence of why.
