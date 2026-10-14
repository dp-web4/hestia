# NOT-SAME review: #1316 held unenumerated-refusal patch

Codex, 2026-10-14. Answer to member notice 24234.

**PASS for the reviewed patch; no blocking finding.** This reviews the held bytes, not a deployment or an authorization to apply them.

- PR head: `26042ef3fc9d92b6843747ecfbd330e27ea4f3ef`.
- Patch SHA-256: `e98ebef4316c1b4d3696d3680c203f74cac15a77ac1690d0ec7cd749e65288d2`.
- Declared base: `5e1ba8e4`. Verified the digest and clean `git apply --check`.
- Checked `git log HEAD..origin/main` in the shared checkout before reviewing; tests used an isolated checkout of the PR, with the held core reconstructed into a test overlay. The shared checkout and installed gate were not changed.

## Why request suppression holds

`evaluate()` returns `mrh.command.unenumerated` for the parser's unmodelled result. That rule is absent from `SCOPE_ESCALATING_RULES`, so `_local_law()` returns the refusal without entering scope escalation.

The less obvious mixed case also holds. A concrete path or overflow can be the first refusal, entering `_scope_escalation()`. That function collects targets and re-evaluates locally **before** its first `claim_scope` call. When the trial reaches the unenumerated refusal, collection stops and returns it without asking the daemon about any collected target. Overflow therefore cannot conceal an unknown expansion from this check. Overflow alone remains eligible for its existing once-only request.

## Independent evidence

| Check | Result |
|---|---|
| Patched decide contract | 22 tests pass |
| Shim parity | 29 cases × 4 adapters pass |
| Patched shell scope battery | 1,434 pass, 0 fail |
| Core unit checks | Pass; live MCP registry check skipped |
| Sprint D checks | 82 pass, 0 fail |
| Additional mixed-input probes | 11 cases × 4 adapters pass |

The additional probes covered an unknown variable; concrete-before-unknown and unknown-before-concrete ordering; absolute and relative overflow plus an unknown variable; a literal-list loop containing an unknown variable; reassigned HOME; an unterminated quote; and process substitution. Each returned the new rule with **zero `hestia_scope_claim` calls** on Codex, Claude, Kimi, and Gemini adapters. The two positive controls, literal overflow and a concrete outside path, each returned `mrh.command` and made one claim.

The fixtures evaluate command strings; they do not execute the shell specimens. The battery and core tests initially encountered an unwritable default cache location. Their disposable copies were adjusted to put fixture roots under the review workspace. Copying the core test also initially broke two source-location assertions; preserving its original `__file__` resolved those harness errors. No policy logic was changed for these adaptations.

## Downstream audit

- The daemon's scope-claim handler accepts only `mrh.path` and `mrh.command`. That is consistent with the new rule never reaching it.
- The gate's `_record()` forwards the verdict rule unchanged. The witness handler and reputation record carry the supplied rule string; neither requires an exact `mrh.command` match.
- The appeal entry point checks the witnessed refusal and appellant identity, not this exact rule string.
- The Decide page displays the request's rule generically. Existing requests remain representable; the patch does not remove their records.
- The decision census preserves the full dotted rule token. No production exact-match consumer needing an update was found in the searched tracked source.

## Limits and follow-up

The isolated real-daemon contract arm was skipped because no test endpoint was configured. The no-request measurements above use the contract stub; downstream Rust/UI conclusions are source review. No installed-gate or deployment claim is made.

The documented loss of the existing once-only approval route is real: the new rule prevents even the lookup that could find an old approval. This is the explicitly stated trade-off, not an undisclosed regression.

Nonblocking documentation cleanup: comments around `UNENUMERATED_TARGET`, `_claimed_scope_entry()`, `_scope_request_path()`, and `_command_scope_reach_one()` still describe an unenumerated act opening a request. Their production reachability changed, even though their code remains useful for overflow or direct core callers. Update that prose to avoid reintroducing the old path on the strength of stale comments.

Co-Authored-By: Codex <codex@openai.com>
