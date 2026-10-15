# PR #1328: review of cb68c3fc

Reviewed PR head `8b242ba97336b7f2d10117b76398b7ed1d548f84`, against
main base `2d79644f`, for mesh notice `26008`.

Held patch SHA-256:
`cb68c3fc11b06de5dffcf7620ce4683027a5ffaedb32f6ce0e3b38aed61c6ddc`.

**PASS for this exact digest.** This clears my technical HOLD on the reduced
patch. It does not supply dp's approval or authority to apply it.

The network-URL exemption has been removed. The five curl write-out and
output-template cases from my previous HOLD now refuse, as on main. The
remaining source changes cover leading absolute `cd`, jq/gh text arguments,
and judging both interpretations of `file:` arguments. No new blocking finding
in that reduced diff.

Independent checks:

- Verified the patch digest and reconstructed all nine files in memory.
- Verified the ground-truth mirror, all five manifest versions, their file
  digests, and their shared-engine pins.
- Revised shell battery: **1,560 passed, zero failed**.
- Same revised battery on main: **1,544 passed, 16 expected differences**:
  eleven intended cd/jq allows and five `file:` tightenings. No new refusal
  expectation fails on main.
- All five previous curl reproductions now refuse under the held core and
  main. Explicit references to their actual output files also refuse.
- Re-executed those five curl cases against a disposable test server with
  curl 8.5.0: each exits zero and writes the expected file contents. This
  verifies the meaning of the refused commands independently of the parser.
- Prior wget negation and HTTPie download controls remain refused; the old
  curl/HTTPie stdout and named-output exemptions are now refused too.
- Decision contract: **23 passed**, with **shim parity 29 x 4** passing.
  The optional real-daemon arm was not run; the suite used its isolated stub.

The adjacent probe reconstructs the named digest from Git. Run it with
`--repo REPO --battery --main-battery --real`. Expected main differences print
as FAIL rows before the final comparison assertion. `--contract-stage`
exports disposable core and contract copies for the existing
`HESTIA_CONTRACT_OVERLAY` test seam; it does not install a gate.

For #1329, measuring how often the exact-directory grant shape occurs is a
useful next step. A recursive grant also authorizes those child-file writes;
it is appropriate only when that broader authority is intended. The URL
false-denial problem remains open, and this review does not claim that curl's
output language is now modelled or safe in every grant shape.

No historical replay was rerun. Checked `git log HEAD..origin/main` and used
the named main base, not the stale shared checkout. No active gate source was
changed and the held patch was not applied.

— Codex
