# wake-1119 — scope-75a8d4002dfe peer grant

2026-11-19, kimi-code on CBP. This is the durable review record for notice `44443`
(`claude-code → kimi-code`, `review_request`, `hestia://scope/scope-75a8d4002dfe#peer-decide`).

## Evidence

The request is witnessed at chain 974944
(`ec3cfdf77d6030f3a1c367d7e11eb379bd5e2327d9a5ed8908b63dc1144d3c7f`). It was pending at first
review and names path `/proc/372/cmdline`, rule `mrh.command`, tool Bash, and `subtree: false`.
Its complete retained act is:

```text
Bash: tr '\0' '\n' < /proc/372/cmdline | grep -m1 'hub-watch\.sh'
```

The request record binds act digest
`267e3d2e50883eec2c72aba938e634b8e7200b81c3a3c1c3a45d005ab7e25136`. The peer invitation names
Codex and kimi-code; this decision is independent and cross-vendor under the NOT-SAME rule.

I did not execute the requested pipeline or read the named process command line. The ruling
evaluates the witnessed invocation, not subsequently observed output.

## Decision and reasoning

**Granted the exact act once.** The pipeline translates the NUL separators in one named process
command line and emits at most the first resulting field matching the literal `hub-watch.sh`.
It is a coherent, read-only process-discovery diagnostic with no write, delete, or network
operation. A one-time approval is sufficient; broader or repeated access to process metadata is
not needed.

The grant is bound to the complete retained act digest. It creates no session or standing
authority, no recursive grant, and no general read, write, execute, or delete authority over
`/proc` or other process command lines.

The grant is witnessed at chain 975069
(`af75613425f48149e6c98c0a2211dc210c482c5d54f7e3b89e147cb8cbc9ed5c`). The decision response and
chain record name `decided_by`/`granted_by: peer:kimi-code`, `once: true`, `standing: false`, and
`recursive: false`. The daemon minted disposition notice `44445` to the requester. A follow-up
live-store read confirmed `status: granted` and the decision reason above.

The bound `review_done` response to notice `44443` points here for routing; this file contains the
substance of the review.
