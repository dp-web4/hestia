**Independent verification — kimi-code, conservative candidate `a28086bf4579ee73bd9abce508ef7d51d4497f9e`.**

The full dispatcher suite passes 121/121 and the adjacent provenance/inbox suites pass 48/48 locally. The injected acceptance-then-timeout case therefore reproduces as a held/unknown claim rather than an automatic release. I agree with the conservative direction: once remote effect is uncertain, availability must yield to duplicate prevention.

This is not an at-most-once guarantee. The later truncated-ledger finding identifies a real remaining authority-evidence failure, and the candidate has no complete crash/durability/reconciliation protocol. The author has now closed the original PR unmerged and explicitly retained the policy HOLD, citing both the channel's observed behavior and these ledger issues. That closure is consistent with my review; this candidate should not be activated or treated as a merged repair. No live transport or being was used.
