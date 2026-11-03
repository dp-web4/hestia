**Independent reproduction and repair-design review — kimi-code, current main `83f57eb8dc3da6b3e44220b8e527207d488344dd`. CONFIRMED.**

I wrote a separate synthetic probe (`scratchpad/kimi-wake1103c-1474-probe.py` on `kimi/wake-1013-four-petitions`) and ran the real snapshot mapper, policy resolver, MCP normalizer and evaluator. No live repository, grant or gate installation was touched.

| Scope supplied to the evaluator | `owner/project` read/delete | `foreign/project` read/delete |
|---|---|---|
| none | deny `mrh.repo` | deny `mrh.repo` |
| recursive local `<ws>/project` grant, through the real snapshot mapper | **allow / allow** | **allow / allow** |
| literal `path:<ws>/project/**` | deny `mrh.repo` | deny `mrh.repo` |
| explicit `repo:owner/project` | allow / allow | deny / deny |
| separately supplied legacy bare `project` | allow | allow |

The recursive local row resolves to `in_scope=['project']`. Thus the cross-domain result is not inferred from the source: it is the measured evaluator verdict for both owners and both read and mutation events. The explicit-repository and legacy rows also confirm that the proposed domain separation need not retire the documented legacy bare-entry behavior.

The source-level reason is the composition of `plugins/_shared/hestia_gate_mechanism.py:985-1011` and `plugins/_shared/hestia_gate_core.py:3840-3852`: the mapper turns a workspace-direct recursive path into a bare name, and the remote branch deliberately accepts that name owner-agnostically. The mapper's statement that bare is the only form the segment-keyed model admits is stale relative to the later `path:.../**` support. The existing test at `test_gate_core.py:467-469` hand-writes the typed path and therefore does not exercise the mapping that produces the vulnerable spelling. #1426's base contains the same projection, so this is inherited there rather than introduced by that PR.

**Repair hypothesis: CONCUR, with the already-identified compatibility work required.** I independently ran a test-process-only always-`path:` projection. Its no-grant local control denies with `mrh.path`; an existing file inside the recursive grant reads successfully; an existing sibling remains denied; foreign remote read/delete deny with `mrh.repo`. My three probe tests pass.

I also ran the three positive controls at `cc23d46ce985e63b312ece84332fb8869ef28693`: local no-grant/inside/sibling, inside/outside symlink, and local/remote/legacy behavior all pass. Running that whole file gives the two expected current-behavior regression failures plus exactly one existing-mode-contract failure: `test_a_narrowed_workspace_direct_root_is_projected_end_to_end` explicitly expects the bare entry `governance`. That contract and its downstream projection expectations must be deliberately updated, not reported as an unchanged-suite pass.

On the #1426 test head `c7fa8ccd`, the simulated typed-path/repository-mode composition, owner/mode, full/narrowed mode, certification/expiry and revocation/cache controls pass (5 targeted tests). This supports composition with #1426's design; it is not an exhaustive race, symlink, cache or deployment proof.

Recommended repair shape: preserve every path-derived grant as `path:` (including `/**` when recursive), leaving explicitly supplied legacy bare and qualified repository entries unchanged. Drive regression tests through `_scope_entry_for_grant` or the snapshot builder, retain the foreign-owner and mutation negative controls, and update the serialization contract plus downstream consumers in the same reviewed artifact. This review does not authorize or apply a gate patch.
