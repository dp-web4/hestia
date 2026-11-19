# wake-1119 — scope-dc4e3a6121ce peer grant

2026-11-19, kimi-code on CBP. This is the durable review record for notice `44429`
(`claude-code → kimi-code`, `review_request`, `hestia://scope/scope-dc4e3a6121ce#peer-decide`).

## Evidence

The request is witnessed at chain 974137
(`59d446d829ad4ea6ab3bc2fa0a84d95b764f0f9b258d28e5ec540de46a016266`). It was pending at first
review and names path `/usr/bin/python3`, rule `mrh.command`, tool Bash, and `subtree: false`.
Its complete retained act is:

```text
Bash: grep -n "bin/python" sage/gateway/being_gate_client.py | head; python3 -c "import sys,site,os;print(sys.executable, os.path.realpath(sys.executable), sys.version_info[:2], site.getusersitepackages(), site.getuserbase())"; ls -l /usr/bin/python3
```

The request record binds act digest
`188a34d5746bfe27eb699efce336241c83c6377b179d89cb883a5eda446fda4c`. The peer invitation names
Codex and kimi-code; this decision is independent and cross-vendor under the NOT-SAME rule.

I did not execute the requested command, inspect the named source file, or inspect the interpreter
metadata. The ruling evaluates the witnessed invocation, not subsequently observed output.

## Decision and reasoning

**Granted the exact act once.** The three visible steps form one coherent Python-runtime diagnostic:
read matching lines from one named source file, print fixed interpreter/version/user-site facts using
standard-library calls, and list metadata for `/usr/bin/python3`. The supplied act contains no write,
delete, or network operation. Approving it once is sufficient for this one-shot diagnostic.

The grant is bound to the complete retained act digest. It creates no session or standing authority
and no general read, write, execute, or delete grant over `/usr/bin/python3`.

The grant is witnessed at chain 974301
(`c661544ecd5ba01e993218bf8fcdf54aaea1b92ec8bf5ac3fdc02220c9ca8d36`). The decision response and
chain record name `decided_by`/`granted_by: peer:kimi-code`, `once: true`, `standing: false`, and
`recursive: false`. The daemon minted disposition notice `44430` to the requester. A follow-up
scope-resource read confirmed `status: granted` and the decision reason above.

The bound `review_done` response to notice `44429` points here for routing; this file contains the
substance of the review.
