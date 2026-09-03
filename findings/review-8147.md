# Review record — notice 8147 / escalation f9a517d6b3176580

**Reviewer:** codex  
**Disposition:** bounded **CONCUR**  
**Pointer received:** `hestia://escalation/f9a517d6b3176580#corroborate-or-dissent`

## Verdict

I concur with the authorized purpose: remove the live legacy fallback from the
Claude hook registration. The repository audit establishes that the fallback
could run an old gate from a working tree when the daemon was unavailable, so
removing that registration reduces a documented enforcement split
(`docs/GATE_HEURISTIC_AUDIT_2026-08-28.md`, section 7).

This is not a byte-level attestation. The escalation records a `cp` from a
scratch file to `~/.claude/settings.json`, but it does not contain the copied
bytes. The public incident record identifies the payload as a one-line hook
re-registration, while also recording that the eventual installed write was
performed by the operator (`findings/one-act-two-rulings-claim-timeout-20260901.md`).
I did not inspect the home-directory target.

## Witnessed lifecycle

A full chain walk recovered the row 15,655 entries behind the head:

- `gate_escalation_opened`, position 207728, hash `688e36a18e163255...`,
  2026-09-01T06:41:51Z. The act was `cp <scratch>/settings.json.new
  ~/.claude/settings.json`, digest `d30ce3cf5c2421f...`, under
  `single_approver`.
- `gate_escalation_decided`, position 207736, hash `0e933a608bcbac5e...`,
  2026-09-01T06:42:07Z. The operator approved it 17 seconds into the window.
- `gate_escalation_claimed`, position 207742, hash `bd615f05c9786f53...`,
  2026-09-01T06:42:27Z. The claimed act text matches the opened act; the row
  reports 14 seconds from decision to use and 31 seconds from open to use.

These rows establish authorization and claim of the stated act. They do not
establish the source file's content or that the hook admitted the write; the
incident record shows the claim acknowledgement was lost and the hook refused.

## Factor filing result

On 2026-09-03 I attempted to file this bounded concurrence through
`hestia_gate_escalation_corroborate`. The daemon refused it as an unknown id.
The row has been reaped from the live store; the ordinary pointer resolver also
missed it because it searched only the newest 1,000 entries. That refusal means
no formal codex factor was added. It is not evidence against the original
escalation: the durable chain rows above preserve the ask, decision, and claim.

