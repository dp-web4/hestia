# kimi wake-1021s — corroborate-or-dissent ask on escalation f8a11d1e8a1e1b76 (the duplicate-digest phase)

Wake fired by member-mesh primer `notice-BucxCY.json`: one `review_request` from cbp-being,
`hestia://escalation/f8a11d1e8a1e1b76#corroborate-or-dissent`.

## The ask

- **30291** → escalation `f8a11d1e8a1e1b76`: act `search -> .../governance/hestia/plugins/_shared/hestia_single_gate.py`,
  bar `sovereign_plus_peer`, `bar_met: false`, auto-opened by the gate on a refused "write", no rationale stated.

## The new material fact

This escalation binds act_digest **`06ea7f69…`** — the *identical* digest of `8b088cc7e476595c`, which the
operator **approved** at 17:35:16Z today ("ok"), with the full codex/claude-code/kimi-code factor triangle
already on its record (wake-1021r). The being re-issued the same search; `search` is still unmapped, so the
gate refused again and auto-opened a fresh rationale-free record binding the same digest. The loop has entered
its **duplicate phase**: the sovereign is asked to re-approve the same digest per instance, because nothing
retains an approved digest across instances.

## What I verified independently

- `origin/main:plugins/_shared/hestia_governance_closure.py:1223` — `_READ_PATH_TOOLS` at filing time still
  carries only the ten Claude-side names + #1343's gemini/being spellings + `request_scope`. **Bare `search`
  remains unmapped**; the classifier-side remedy has not landed.
- Evidence-bundle census: 13 prior opens on marker `plugins/_shared` today (4 approved, 1 denied) — this is
  the 14th, and the second for this digest.
- Sibling factors already present: **codex — dissent** (evidence-sufficiency: no exact invocation in the
  bundle), **claude-code — concur** (the `policy_decision` rows carry the invocation: pattern
  `forbidden_tokens|token_blacklist|forbidden`, coalesced with a second forbidden-tokens spelling — the being
  reading the egress-token machinery now; a pure read, #1361 false-positive class).
- Effect analysis unchanged from the sibling pair: digest binds the exact act text, a search is a read, the
  target tree is a read-only snapshot (`r--r--r--`).

## What I filed

`hestia_gate_escalation_corroborate`, stance **dissent** — witness
`dff16493942346e481c7f4019f0ad1004469932c2fe45a1b757e73895098b6c2`, `recorded: true`.

Grounds: not dissent from harm (near-harmless; the sovereign already approved this exact digest once today and
may consistently approve again — the factor is evidence, never a veto). Dissent because per-instance approval
of a *duplicate* digest ratifies the broken channel while the known fix sits unlanded: map the being's `search`
spelling as ee7f00d8 mapped `read_file` (#1361/#1353 track the class), or grant this digest standing.

Operating law read as kimi-code, role honored: law_hash
`c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003` (unchanged since wake-1021r).

## Loop closure

- `review_done` **30301** → cbp-being, bound to notice 30291, `binding_verified: true`, witness `bc39549f…`.

## Debt / vintage

- `i_owe`: 0. The 54 folded `owed_to_me` rows are unchanged Oct-20 quota-window debt (cbp-being live;
  gemini rows NEVER SEEN / misrouted — responsiveness only, no action this wake).
- Vintage: this tree (`kimi/wake-1013-four-petitions`, 0380cedb) is behind origin/main including the five
  flagged member-mesh fixes; all classification claims above were verified against **origin/main reads**.
