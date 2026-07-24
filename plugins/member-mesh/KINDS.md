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
