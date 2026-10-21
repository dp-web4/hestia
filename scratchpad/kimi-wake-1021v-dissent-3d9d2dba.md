# kimi wake-1021v — notice 30334, escalation 3d9d2dba2aa1e16e (seventh instance of digest 06ea7f69)

## Ask and live record

cbp-being asked for corroborate-or-dissent on
`hestia://escalation/3d9d2dba2aa1e16e` (notice 30334, queued 2026-10-21T18:58:07Z).
The retained act is `search -> /home/dp/ai-workspace/governance/hestia/plugins/_shared/hestia_single_gate.py`,
act_digest `06ea7f69be41…`, bar `sovereign_plus_peer`, auto-opened by the gate on a refused
"write", no member rationale (the being did not choose to escalate). Pending, ungranted,
unclaimed at final check.

## Independent verification

- Chain `policy_decision` rows at 18:58:07Z and 18:58:12Z carry the exact invocations:
  `search {"pattern": "_READ_PATH_TOOLS"}` and `search {"pattern": "_READ_PATH_TOOLS\s="}`
  on the deployed `hestia_single_gate.py` (correlation `content-b94ec4cee441…`). A search
  writes nothing; the target tree is the read-only snapshot (`r--r--r--`, Oct 19).
- Root cause re-verified against **origin/main** (not this branch's HEAD):
  `_READ_PATH_TOOLS` (`plugins/_shared/hestia_governance_closure.py:1707`; deployed copy
  l1223, identical membership) still lacks bare `search`. The unknown-tool rule classes it
  as a write; the `plugins/_shared` marker refuses. Issue #1361 remains OPEN (4 comments),
  no fix merged. `ee7f00d8` (#1343) mapped `read_file` and other being spellings — not
  `search`.
- **Correction to claude-code's factor**: the frozenset lives in
  `hestia_governance_closure.py`, NOT `hestia_single_gate.py`. The being's search of
  `hestia_single_gate.py` returns zero matches. The act is still a read and harmless, but
  the record should name the right file.
- Duplicate census (chain walk, `gate_escalation_opened` on digest `06ea7f69`): SEVEN opens
  today, ~75-min cadence — `8356ac78` 12:30, `910bbec8` 13:45, `a1d902db` 15:00,
  `cd00f6ed` 16:15, `8b088cc7` 17:07, `f8a11d1e` 17:47, this one 18:58. Instance
  `8b088cc7` was operator-approved "ok" at 17:35:16Z with the full cross-vendor factor
  triangle — and **lapsed unspent**; `f8a11d1e` expired unruled. Per-instance approval
  produces grants the loop never consumes, because nothing retains an approved digest
  across instances.

## Dissent filed

`hestia_gate_escalation_corroborate`, stance `dissent`, escalation `3d9d2dba2aa1e16e`.
Not dissent from harm — the act is a read, the digest binds tool+path, and the sovereign's
17:35 "ok" precedent stands. Dissent because a seventh per-instance ask ratifies the broken
channel while the remedy sits unlanded: map bare `search` classifier-side (#1361/#1353),
or grant this digest standing. Peer evidence, not a veto.

Factor set at filing: codex DISSENT (evidence insufficiency), claude-code concur
(read-only, #1361), kimi-code DISSENT.

**Self-report — duplicate factor**: a verification re-run of the filing script re-invoked
`hestia_gate_escalation_corroborate`, recording a second identical kimi dissent ~5 s after
the first. Both are witnessed: operative factor `98691f80356e0fe281b06fec59b4ad6672ed6043055776b750e425fa97adf0d4`
(19:08:32Z), duplicate `9a577c2d76cb34f642c35ae8da07c0a88189f16abdaf21fe282e1116f1cfbc37`
(19:08:37Z). The corroborate surface has no idempotency guard; the error was mine (the
script truncates its own output at 3000 chars, I re-ran to capture the witness hash, and
the re-run wrote a second factor). Recorded here and in the `review_done` pointer.

Operating law read as kimi-code, role honored: law_hash
`c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003` (unchanged).

## Loop closure and housekeeping

- `review_done` **30345** → cbp-being, `in_reply_to=30334`, `binding_verified: true`,
  witness `43e60ad7208c84fcdca7cd589a2ed11f517da37e260fbb6958b225f2a4714ade`,
  operation_id `kimi-wake-1021v-review-30334`.
- `i_owe = 0` at close; notice 30334 no longer owed. The 54 folded `owed_to_me` rows are
  the unchanged Oct-20 quota-window records (cbp-being live; gemini rows NEVER SEEN /
  misrouted) — responsiveness only, no action this wake.
- Vintage: this tree (`kimi/wake-1013-four-petitions`) is behind origin/main including the
  five flagged member-mesh fixes (#1357, #1321, #1326, #1309, #1292). All classification
  claims above were verified against origin/main reads, not the superseded checkout.
- The shared tree holds many unrelated untracked files; only this wake's two files were
  committed.
