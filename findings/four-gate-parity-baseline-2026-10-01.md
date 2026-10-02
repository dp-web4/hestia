# The four-gate parity baseline: 24 of 25 rows already agree, and the one divergence is a layer, not a value (kimi-code, 2026-10-01)

**What this is.** The acceptance fence for the one-gate landing (#934 finish-line plan,
2026-10-01), built against TODAY's four seat gates before any converged stack exists, so the
cutover is measured against a baseline instead of argued from one. The corpus
(`tools/gate_parity_corpus.py`, 25 acts, declared with expectations read from the law as
shipped) is driven through each seat's real shim as a subprocess with its native event shape,
against a neutral stub daemon (local law decides; no witness chain is touched — 964 stub
requests, zero live calls). Runner: `tools/gate_parity_runner.py` (23 unit checks green).

**The headline: the baseline is already tight.** 24/25 rows in full four-seat agreement,
including every historically contested class: closure writes deny-escalatable everywhere;
every measured FP-family read class allows everywhere (`git apply --stat/--check`,
closure-naming reads, heredoc text, throwaway-copy variables); secret paths deny on the innate
layer everywhere; out-of-scope writes deny everywhere; all five PIN rows (digest pairs, egress,
sudo, push) agree allow on every seat. Zero degraded cells.

**The one divergence is a layer, not a value.** `gate-self-claude-settings` denies on all four
seats — but claude/kimi/codex deny through the closure classifier (`rule
governance-closure-write`, event class `gate-self-access`, escalatable), while **gemini denies
at its own scope layer** (`deny:scope`, not escalatable): gemini has no closure layer of its
own, and its closure protection arrives only via the spawned claude-code governor, which an
out-of-scope path never reaches. Same verdict, different authority *surface* — and the
difference is observable downstream (escalatability). This is exactly the class of row the
cutover must consciously resolve: the converged gate either gives gemini the closure layer
(absorbing its scope-layer duplicate) or declares scope-layer protection the law for that
surface. What it must not do is lose the row by accident.

**Two measured facts about the current shims, for the cutover's "nothing silently lost" check:**

1. **kimi/codex flatten rule ids in deny rendering**: every core deny renders the literal
   `[scope]` regardless of rule family (the true rule id survives only in gate-self text). If
   the converged gate renders rule ids uniformly, that is a deliberate legibility fix over the
   baseline, not a regression — recorded so a future diff doesn't read it as one.
2. **gemini's deny channel is two-shaped**: policy deny = exit 0 + stdout JSON
   `{"decision":"deny"}`; exit 2 = anomaly only (crash / unreachable governor). A parity or
   certification harness that reads exit codes alone will misread gemini denys as crashes. The
   runner's normalization encodes the distinction; the cutover's acceptance suite must too.

**Known fence gap (declared, not discovered later):** daemon-side law is invisible to the
stub by design — the destructive-preset row (`cd $SCRATCH && rm -rf out`) measures `allow × 4`
here because `presets.rs` lives behind the daemon. The converged stack's acceptance run
therefore needs a second arm against a scratch DAEMON (real law, scratch vault), not only the
stub: the stub arm proves the shims' local surface is harness-invariant; the scratch-daemon arm
proves the daemon's law answers identically per harness.

**How the converged stack is judged by this fence:** run the same corpus against each fresh
head. Every row must match this baseline or be named in the cutover diff as an intentional
change, with the layer it moves to stated (as the gemini settings row demands). 24 rows of
free agreement are the inheritance; the divergence table is the work list.
