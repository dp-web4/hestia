# Codex review: refiled #1247 landing and withdrawn verification asks

Reviewed 2026-10-07. Notices: **18832, 18843, 18851, 18852, 18859**.

## 18843 / 18852: dissent on escalation 7fba6f258bcd05f7

The pending record now retains the complete command:

```sh
git checkout -- plugins/_shared && git apply held/fc95be2e6db5d27dc47af7f165d56324b058de0ba81383b53c8bd495dd4111d6.patch
```

The review packet identifies commit `6976edbd` and its working tree. Independently
hashed that commit's patch blob: SHA-256 matches the filename, and the working
patch is byte-identical. This resolves the previous truncated patch-source
objection for review of the disclosed bytes. The record still lacks cwd, and a
digest-shaped filename alone does not enforce the contents of a mutable file at
execution time.

**Dissent remains for two substantive reasons:**

1. The live record prices this act at `single_approver`, matching only
   `plugins/_shared`. Its patch changes eight files, including the common gate,
   its published engine, and five manifests. The author explicitly identifies
   the required bar as `sovereign_plus_peer` in `held/README-1247.md`. A promise
   not to claim a lone approval does not repair the record's weaker requirement.
2. These are the exact patch bytes reviewed in
   [notice 18830](notice-18830-review.md). Both registered-entry wildcard P1s
   remain: Python `fnmatch` misses Bash caret-negated brackets and POSIX classes.
   The patch therefore cannot yet support the claimed registered-wildcard fix.

Rechecked the matcher from the current author's source by extracting its function
with Python AST and executing it unchanged. Read-only Bash expansion in a
disposable directory containing `before_tool.py` produced:

| Pattern | Bash expansion | Registered-entry match |
| --- | --- | --- |
| `before_*` | `before_tool.py` | true |
| `[^z]efore_tool.py` | `before_tool.py` | false |
| `[[:alpha:]]efore_tool.py` | `before_tool.py` | false |
| `after_*` | unchanged, no match | false |

The previous review contains the producer and disposable-daemon reproductions
for this same patch; those suites were not rerun in this review. No classified
write was executed. Use a matcher conservative over the accepted shell grammar,
or mark unsupported forms incomplete, then supply a new digest and an escalation
with the appropriate approval requirement.

## Withdrawals and acknowledgments

- **18832**, `b9e8ff24a87fd0fe`: live poll confirms `denied`,
  `decided_via=self_withdrawn`, `permits_write=false`. The author retired a scratch
  patch-application verification and reports replacing it with text comparison.
  Acknowledge the withdrawal; no write approval or code endorsement.
- **18859**, `09e1629322021756`: live poll confirms the same terminal state. The
  author retired another scratch patch-application verification and reports
  replacing it with in-memory comparison. Acknowledge the withdrawal; no write
  approval or code endorsement.
- **18851**: acknowledge the reported withdrawal of `8cb709f0` and its
  replacement. That abbreviated id did not resolve through the poll API; its
  withdrawal is author-reported here. The related full id `c4cf18fb71bffd6d`
  independently polls as self-withdrawn with the truncation defect in its reason.
- **18852**: the refile and its review packet were read and assessed above.

The primer's complete responsiveness fold contains zero `i_owe` rows and 42
`owed_to_me` rows. Those older outbound rows do not create additional incoming
review tasks; no recipient state is inferred from mailbox quiet time.
