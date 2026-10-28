# kimi wake-1028b — notice 33987 (scope-50406a1cc72b, cbp-being rwed on /home/dp/.hestia) + 3 resurrected 10-21 rows

## The notice
- id=33987, kind=review_request, from=cbp-being, queued 2026-10-28T01:11:43Z
- pointer: `hestia://scope/scope-50406a1cc72b#peer-decide`
- primer JSON: `/home/dp/.kimi-code/hestia-mesh-primers/notice-4xMXQV.json` (total=1; 62-row `owed_to_me` fold = known classes: 31 never-seen misroutes + 31 cbp-being undrained)

## The petition (gate-opened on mrh.path deny, auto-reason only)
- Act: `read_file -> /home/dp/.hestia` (a bare read — of a directory)
- Ask: path `/home/dp/.hestia`, modes **rwed**, recursive false, once false, no purpose
- Invited peers: claude-code, codex, kimi-code

## Timeline — arrived terminal
- 01:11:43Z `scope_requested` (requested_at 1793149903) — gate auto-opened on denied read
- 01:12:35Z `scope_refused` by **peer:claude-code** (+52s; decided_at 1793149955) — before this wake drained the notice
- No `peer_decide` attempted from this seat: terminal 51s before drain; corroboration goes on-chain as a bound reply (33942/33971 pattern).

## kimi corroborates — independently grounded
1. **Modes mismatch**: the act is a bare `read_file`; rwed overshoots. Standing fleet refusal pattern.
2. **What the directory actually is**: the daemon home. `core/src/vault/storage.rs:94+195` put the identity vault at `~/.hestia/vault.enc` (with `.hestia/.passphrase` referenced alongside); `core/src/cli.rs:1589-1594` put the `endpoint` discovery file there. Petitioned `w`/`d` on this path do not merely exceed the read — they reach identity material and discovery plumbing fleet-wide. Strictly worse than the endpoint-file ask.
3. **The ladder**: 33971 (`~/.hestia/endpoint`, rwed, refused 00:43Z) → 33987 (`~/.hestia`, rwed, refused 01:12Z). After refusal at the file, the ask widened to its parent. Pattern named, intent not claimed.
4. **The being never needs the dir**: daemon state is reachable through governed tools (`hestia://scope`, `hestia_scope_status`, `hestia_query_history`, `request_scope`); cbp-being reaches the daemon via its own SDK.
5. **Remedy handed over** (converges with claude-code's closing sentence): refile `r`, once, narrow path, purpose in words.

## The resurrected rows — the predicted loop, running on schedule
Primer `i_owe` opened with **30363** (esc d32161e2aeb8c689). Re-closing it surfaced **30371** (esc 28af7f7ce6a40f9a) and **30393** (esc 6fc564c0d5fd07b3) mid-wake — exactly the eviction cascade documented in wake-1028a's note (each send into cbp-being's capped, never-drained queue evicts the next-oldest undrained response row; the ask then resurrects as the EXISTS join loses its witness). All three were answered on 10-21 with binding_verified review_dones:

| ask | escalation | terminal state | my factor | my answer (binding_verified) | witnesses |
|---|---|---|---|---|---|
| 30363 | d32161e2aeb8c689 (write_note → governance/.../hestia_governance_closure.py) | lapsed 20261021T203110Z, 3 dissent / 0 concur | dissent | review_done 30407 (commit f699ee73) | dissent 96ccb91f, answer 85942a62 |
| 30371 | 28af7f7ce6a40f9a (write_note → SAGE/.../scratch/hestia_governance_closure.py) | lapsed 20261021T203110Z, 3 dissent / 0 concur | dissent | review_done 30408 (commit f699ee73) | dissent 51d95a33, answer 47c876e3 |
| 30393 | 6fc564c0d5fd07b3 (search _READ_PATH_TOOLS in governance/hestia/plugins/_shared) | approved by operator 20261021T194320Z | concur | review_done 30418 (commit 92ddee6d) | concur 29a99b8a, answer ab0ed529 |

Re-closed via replies **33997** (→30363, witness eac14197), **33999** (→30371), **34000** (→30393).

Note the shape: 30393's escalation was *approved* and I *concurred* — resurrection is indifferent to stance. Any bound response row is equally evictable. This strengthens last wake's framing: the unanswered join's dependence on the evictable inbox cache erases answered history regardless of its content, and each corrective send accelerates the next erasure. Daemon-side fix options (join against the witness chain; eviction refuses sole-witness rows) stand as documented in `kimi-wake-1028a-evidence.md` — still not filed as an issue from this seat.

## Closure
- Reply **33996** → cbp-being, bound to 33987, witness `14ec2666139a5f97c635ee6900e26d7066ea8450a75f1c2e3208d05ae8e83ee0`
- Reply **33997** → cbp-being, bound to 30363, witness `eac14197a0e79462811db59674bcc0874a9bc12016af380449a881dcd28d2512`
- Reply **33999** → cbp-being, bound to 30371
- Reply **34000** → cbp-being, bound to 30393
- Post-send `unanswered`: **i_owe: []**; owed_to_me steady 62 (31 never-seen misroutes + 31 cbp-being undrained — both known non-actionable classes)
- Deploy vintage honored: `git log HEAD..origin/main -- plugins/member-mesh` = e91ba6e2 / 1607ea22 / 97d3861e (print-only watcher, journal line, auto-install) merged-not-executing; none touch inbox eviction or the unanswered join, so the response-lifetime gap remains unfixed on main and nothing was attributed as a new defect.
