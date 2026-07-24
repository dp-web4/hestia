# Local member-mesh notice kinds (mirror of the fleet hub-mesh KINDS, one MRH down)

| kind | semantics |
|---|---|
| coordination | general work coordination; pointer -> forum/plan/file |
| review_request | please review the artifact at pointer |
| review_done | review verdict posted at pointer |
| reply | response in an ongoing thread at pointer |
| handoff | work handed to recipient; pointer -> the state to pick up |
| forum-note | FYI: forum post at pointer |
| ack | terminal acknowledgment (does NOT warrant a reply — loop terminator) |

Rules (inherited from fleet mesh): pointer-based (content lives at the pointer, never in
the notice); ack is terminal; every send is a witnessed `member_notice` chain event before
delivery; recipient-scoped consume-once drains; law can deny who may wake whom
(gate category `member_notify`).

## Hardening posture (post kimi review, 2026-07-24)

- **Attribution is proven, not inherited.** `member_notify` / `member_inbox` require the
  caller's own live `session_id` (from `hestia_connect`); there is no latest-session
  fallback on member surfaces. Missing/stale ids deny with `*_unattributed`.
- **The law gate is DEFAULT-ALLOW on a permissive base.** No shipped rule references
  category `member_notify`; who-may-wake-whom is operator law (role/instance overlays or
  hub law), deliberately not hard-coded. Until such law is ratified, treat the mesh as
  trusted-local-members-only and keep auto-fire (`hestia-watch-member.sh`) disabled on
  any deployment with untrusted members.
- **Structural bounds (daemon, not law):** pointer_uri must be single-line, ≤512 bytes,
  no control characters; per-sender flood guard of 30 notices / 10 min. Inbox cap is
  1000 notices per recipient with drop-oldest admission — under flood, unacted notices
  can be evicted (the flood guard exists to keep senders far from that cap).
- **Fire templates render a sanitized digest** (field-allowlisted, control-chars
  stripped), never raw notice JSON, into the fired CLI's prompt. Primers live in
  `~/.local/state/hestia-mesh/primers/` (0700), removed on successful fire, retained on
  failure (the drain is consume-once — a failed fire's primer is the only copy).
  One watcher per member, enforced by lockfile.
