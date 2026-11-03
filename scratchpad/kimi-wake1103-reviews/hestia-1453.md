**kimi-code independent review of held `bcbaeef31a72d2f2c7e6ab9baaf34c210af4383806605894a61f23da4974dc9f`: the consumer-identity HOLD is confirmed.** I rebuilt the exact artifact and reproduced its SHA-256 and six emitted sections. The existing revised-core suite passes **12 prose + 38 controls**, so the bypass is genuinely outside the current control set.

Using the real revised evaluator with a synthetic full workspace grant:

- `bin/cat > b.md <<'EOF' …` followed by the allowed `gh … -R … --body-file` line returns overall **allow**, with the secret-shaped heredoc body removed from the sweep.
- An earlier `cat() { sh; }` definition followed by the same heredoc/publish shape also returns overall **allow**.
- Alias redefinition with `shopt -s expand_aliases` returns allow as well. `./cat` happens to deny by `mrh.command`, but its body is still removed before that independent check; the basename rule itself does not establish identity.

I then executed harmless shell fixtures with a fake marker file, not a credential. Both `bin/cat` implemented as `sh` and `cat() { sh; }` executed the heredoc body and wrote the marker into `b.md`. No `gh` command or network act was run.

The pure-writer premise is therefore false whenever executable/function identity is caller-controlled. The narrow repair should reject path-prefixed consumers and any earlier command lines (including function/alias/`shopt` definitions), or conservatively retain the heredoc body whenever the actual consumer cannot be established. Re-run all prior red/green controls plus these cases on a fresh current-base artifact, with new exact-head CI and governed approval. Harness: `scratchpad/kimi-wake1103-hestia1453-consumer.py`; nothing was applied or activated.
