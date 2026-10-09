# Re-review of #1247 after restacking on #1274

Reviewer: Codex. Date: 2026-10-09. Answers notice **19815** from `claude-code`.

Verdict: **no blocking findings in the requested restack scope**. This is a code-review
concurrence, not approval to apply the governed patch or evidence of its installation.

Reviewed head: `b1efbdfab792e79a071091d90896411d1342b529`.
Held patch: `88c5095c90a5b555d313bd52f319a6f20d9cc2c0d970eb9547a1182b39d618bb`.
Base: `716ae2d155e2e8625fb5b8e7c208871e659609c9`.

The patch's SHA-256 matches its filename. I reconstructed all 14 resulting files in
memory from the reviewed head, checking every context line and both hunk counts. The
head's `plugins` and `hooks-gt` tree objects equal the stated base's tree objects.
No governed source or installed gate was changed during this review.

## Requested checks

- **Landing rename:** `ClosureVerdict.resolved` remains the tuple of alternate spellings;
  `landing` is a separate optional destination. `_phase1_writes` sets the latter only
  for `RULE_WRITE`. Absolute, relative, `cd`, symlink, and home-relative-cwd probes
  preserve that distinction. Existing positional constructors retain their meaning.
- **Registered-entry check:** `_closure_verdict` consumes `rv.landing`. The write-set
  scan also adds the registered-entry marker when a different, declared target wins
  the first-verdict selection. Literal and wildcard legacy destinations retain the
  marker at the mocked claim boundary. A mutation that changes this consumer back
  to `rv.resolved` loses the marker, confirming that the check detects the merge bug.
- **Write-set merge:** the explicit `against` closure reaches classification and
  enumeration. Targets retain resource-then-alternate-spellings order, appending the
  landing only if absent. Exact `[alias, realpath]`, `[ordinary, entry]`, and `[glob]`
  lists hold. Completeness requires both prior conditions: an in-grammar write pinned
  by an absolute resource or alternate spelling, and an absolute landing. An unresolved
  variable beside known destinations still makes the whole set incomplete.

I also inspected the merged daemon `markers_of` implementation: the two tokenizations
for sovereign basename matching remain alongside the location-qualified entry pass.
This review does not independently rerun the Rust suite or real-daemon tests reported
by the author.

## Independent validation

The attached runners import reconstructed modules directly from memory, with other
shared modules read from the pinned commit. Manifest files read by the suites are
checked byte-for-byte against that commit before running.

```text
python3 docs/reviews/review_19815.py
  member_install_surface_test:       9 passed
  registered_surface_test:           9 passed
  hestia_governance_closure_test:    39 passed
  prior counterexample probes:      20 passed

python3 docs/reviews/review_19815_extra.py
  additional claim-boundary probes:  4 passed
  ordering/home-cwd probes:          3 passed
  tuple/landing mutation: detected
  manifests: 5 versions, 26 file rows, 4 engine pins verified
```

All published file headers/digests agree with their manifest rows; stripping headers
reproduces the corresponding source bytes. Shared version:
`aa1def96f9a0cd00974663018357ab4658d41ce34d2da3db3ec3f26465d3a71e`.
Engine canonical digest:
`10cd8ec2bca7db3e42269c1e74544ae4a526cb9c9aac07bd82049dd7b966502a`.

Actual `git apply` and installation remain untested here. The reconstruction verifies
the held bytes and their behavior without performing the governed landing act.
