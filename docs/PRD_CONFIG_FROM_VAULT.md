# PRD: config is generated from the vault, checked at runtime, and a mismatch is a miswire on the ledger

Status: DRAFT for ratification. Owner: hestia. Extends `PRD_GOVERNANCE.md` §4 principle 1 (governance config lives in the vault) and §2.12 item 4 (the config drift detector, restored to Sprint 0). Supersedes nothing. Parent evidence: `PRD_CONFIG_IN_VAULT.md`, kept as the record of #133.

## 0. Directive (dp, 2026-09-03, verbatim)

"we should not have machine-specific paths in editable configs. all that needs to live in the vault and set env variables, which should be periodically checked vs vault for integrity, just like the hook plaintext. we want hooks to be fully portable as we move towards production. the target: ALL config lives in vault, readable files and vars written from vault on startup, checked at runtime, immediately flagged as miswire (and logged in ledger) when detected as not matching."

## 1. What is new here, against the parents

The parents establish that governance config belongs in the vault and that a detector should compare vault against the on-disk shadow. This PRD adds the three things that make that a mechanism rather than an audit:

1. **Generation, not just comparison.** The on-disk config is WRITTEN from the vault at startup. Today it is authored by hand and the vault, where it exists, is a second opinion.
2. **Runtime checking, not only startup.** A file that matched at startup and was edited at noon is a miswire from noon, not from the next restart.
3. **A mismatch is a recorded governance event.** Flagged immediately and appended to the ledger, so drift has a timestamp and an actor rather than being noticed later by whoever happens to run a probe.

And it widens the scope: **machine-specific paths are config**, not an exception to it.

## 2. Measured today, five instances of one defect class

Every one of these is a live consequence of hand-authored config on this box.

| instance | what it is |
|---|---|
| kimi's dead knob | `~/.kimi-code/config.toml` sets `HESTIA_SOCIETY_GATE` to a hook file that does not exist. Both mentions in the shim are comments saying the knob was removed for #585. It reads as configured and is inert. |
| this seat's missing root | The claude gate hook carried no `HESTIA_WORKSPACE`, so it resolved its MRH root from the session cwd, one level above every grant, colliding with 22 sibling directories (#839). Nine read-only refusals in one hour. |
| codex and gemini | Both carry `HESTIA_WORKSPACE=<absolute path>` inline in their own hook lines. Correct today, and machine-specific text in an editable file. |
| the migration cost | Moving the workspace root means editing 24 hook-config lines across four seats and 10 systemd units by hand, plus re-issuing every path grant. From the vault it is one update and a restart. |
| the editability wall | These files are governance markers precisely because they are editable plaintext, so a member cannot fix its own miswire, and every correction costs an operator approval. |

The last row is the one that compounds: the current design makes hand-editing necessary and then forbids it.

## 3. Model

**The vault is the source.** For each member, it holds the config as data: the hook command's environment (workspace root, plugin id, role, budgets), the registration shape, and the paths the installer uses. No machine-specific string is authored in a file a human edits.

**Startup renders.** The daemon writes each seat's config file and environment from the vault, and records what it wrote: a digest per rendered artifact, in the same ledger that already records the installed hook bytes (`current-build.json` carries hook shas today; this is that pattern extended from code to config).

**Runtime verifies.** The rendered artifact is re-checked on a cadence and at the moments that matter (before a deploy, at seat start, on the gate's own periodic pass). A digest that no longer matches the vault's rendering is a **miswire**.

**A miswire is an event, not a log line.** It appends to the chain with the artifact, the expected and found digests, and the time it was first observed. It is visible to the member (its own config is wrong and it may not fix it), to the operator (someone or something edited a governance surface), and to the readiness table, which already reports MISWIRED for resident hook bytes and would gain the same verdict for config.

**Portability falls out.** A seat whose config is rendered from the vault carries no host layout in any file, which is what makes the same hook shippable to another machine.

## 4. What this does NOT do

- It does not make config unwritable. An operator can still change it, by changing the vault, which is the point: one authority instead of two.
- It does not remove the gate-self protection on the rendered files. A rendered file that a member could edit is still a governance surface; the difference is that the correct fix stops being a hand edit.
- It does not settle where secrets live. They are already vault-only; this is about the non-secret config that has been living beside them in plaintext.
- It does not replace `installed_seat_readiness.py`. It gives it a second column: resident hook bytes match the ledger, and rendered config matches the vault.

## 5. Acceptance

1. Render a seat's hook config from the vault into a temp home; the file's digest matches what the ledger recorded, byte for byte, across two runs.
2. Hand-edit one character of a rendered file. The runtime check reports MISWIRE within its cadence, names the artifact and both digests, and the event is on the chain.
3. Restore the file. The next check reports clean, and the chain shows both the miswire and its resolution, so drift has a duration and not merely an occurrence.
4. Move the workspace root in the vault alone. Every seat's rendered config follows on restart, with no hand edit, and the readiness table stays PASS.
5. A vault that cannot be read at startup renders nothing and the seat does not start with a stale file silently in place. Absence is INDETERMINATE, never a quiet pass.
6. Grep the tree: no machine-specific absolute path in any file a member or operator is expected to edit by hand.

Arm 5 is the one that decides whether this is worth building. A renderer that falls back to the file it found is a second authority with extra steps.

## 6. Sequencing note

This is the mechanism that would make the pending workspace move a single vault change rather than 34 hand edits, so the two are related but not blocking: the move can proceed by hand first, and every hand edit it costs is an argument for this document.

## 7. Open questions

1. Does the daemon render at startup, or does each seat's installer render on deploy? The installer already knows the member's declared files, and the deploy already writes hook bytes and records them.
2. What cadence for the runtime check? The deploy timer is 4-hourly and the disposition worker is 5-minutely; a config check probably belongs with the latter.
3. Does a miswire fail closed? A gate whose config is wrong may be enforcing the wrong law, which argues for refusing to act rather than acting on the found value. That is a stakes question and this PRD should not answer it alone.
