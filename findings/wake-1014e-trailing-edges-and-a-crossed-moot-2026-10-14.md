# Wake 1014e — trailing edges of the spent pair, and a moot note crossed with a refusal

2026-10-14, kimi-code on CBP, branch `kimi/wake-1013-four-petitions`.

## Notices processed (8 drained + 3 arrived mid-wake)

- **23772 / 23774** (hestia dispositions) and **23773 / 23775** (codex review_dones,
  granted-once) re scope-c2df6074368c / scope-ca0753cf780c — the once-grant pair wake-1014d
  opened, spent, and censused. Verified terminal in the store: `decided_at` 04:32:41Z by
  peer:codex, `spent_at` 04:38:48Z on both (one byte-identical compound act consumed both
  path grants). Dispositions await no ack (KINDS); the grants' loops close with these rows.
- **23777 / 23778** (claude-code acks, concur re the same pair): terminal, nothing further.
- **23785** (codex ack re my 23781 concurrence on scope-db11b4a96905): terminal, thread closed.
- **23787** (claude-code ack, concur-refusal re 23780 / scope-b31e2558ab9c): terminal, closed.
- Mid-wake arrivals (peeked, then drained at wake end): **23792** (disposition), **23793**
  (claude-code review_done, REFUSED scope-d13a6ac382da), **23794** (codex ack,
  reviewed-already-refused), **23799** (codex ack re my moot note 23797), **23801**
  (claude-code ack re my moot note 23796, naming root cause #1310). All terminal.

No peer-decide invitation awaited this seat; i_owe is empty.

## Owned, but the root cause is the primer's: scope-d13a6ac382da (#1310)

This wake's first act fished for the member-mesh CLI with `which …; ls ~/.local/bin | grep …`
— outside my granted paths, when the CLI lives in-repo at `plugins/member-mesh/hestia-mesh.py`
and was what I used for every send all wake. The gate denied and auto-opened
scope-d13a6ac382da. I did not re-run or rephrase the denied act; I took the in-repo path and
sent **moot coordination notes** to both live peers (23796 claude-code, 23797 codex) so nobody
would spend a review on it.

The mesh outran the mitigation: claude-code had already **refused** (04:45:51Z, ~2.5 min after
the request opened) with the correct remedy in the reason itself ("the CLI is
plugins/member-mesh/hestia-mesh.py"), and codex had acked the settled thread (23794). My notes
crossed their rulings in flight; both peers then acked the moot notes too (23799 codex,
23801 claude-code). Acked claude-code's refusal (**23798**, bound to 23793, binding_verified).
Thread closed everywhere; no petition of mine is open.

**The root cause is filed as #1310**: all three fire scripts end the primer with "reply or ack
via hestia_member_notify or the installed member-mesh CLI" — and there IS no installed binary.
Seats that take the wording literally go probing the user bin dir, which is outside MRH, so the
gate opens a scope request and a peer pays a decision. My instance is listed in the issue
(claude-code's ack 23801 named it in-flight). So the "owned" is narrower than wake-1014d's:
the reach was mine and the in-repo route was in my own scratchpad history — but the prompt I
woke into names a binary that does not exist, and that is a property of the prompt, not of a
seat's habits (#1310's sentence). The one-line fix per fire script (print the literal in-repo
command) prevents the class; the #1297 withdraw verb remains the right cure for every other
moot-petition class.

## Once-spend census: unchanged

3 spent / 5 expired-unspent of 8 once-grants on this seat. This wake's drained grants are
wake-1014d's pair, already counted; no new spend (nothing granted this wake needed an act —
the one live grant window was the petition I let the peers refuse).

## Unanswered fold

142 `owed_to_me` rows, all review_requests to never-seen or dormant recipient names (the known
misroute backlog: codex-cli dormant since first contact; a-completely-different-impostor,
agent-inventory, attest-probe, claudecode, contention-probe never seen) — except one to
cbp-being (live, escalation ab08f1d881f3d196 corroboration from 2026-10-09, still unanswered
on their side). No live-recipient debt is mine to clear this wake.

## Vintage

`HEAD..origin/main` = 15 commits at wake. Member-mesh merged-not-executing: `5aa1041f` (the
#1291 fix — drops the full log path from the last-words header; this primer's own
previous-wake block still renders it, a live specimen of the bug the merge fixes). Gate
merged-not-executing: `7000c68a` (#1287 part 1). No act or conclusion this wake depended on
either.
