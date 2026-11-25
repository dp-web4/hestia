# Harvest disposition: closed certification and resolver proposals

**Issue:** #1173
**Reviewed:** 2026-11-22
**Sources:** #932 at `e62cc02287cff10db3f8cbd86bb8e75dda64ce7d`; #1082 at `55fdbc1cc695b949ef8bb99104e3c5774949ca5d`

This is an evidence harvest, not a revival of either merge proposal. The old runtime
implementations were not applied to current `main`, and the source branches are not
deleted by this change.

## #932 — certification precursor

The canonical `docs/PRD_SHIM_CERTIFICATION.md` and
`plugins/_template/shim_template.py` already landed through #1104 (`476a8e0e`) and have
since evolved. The versions from #932 are retired as superseded; they are not restored
over the current authority.

| Source item | Disposition |
|---|---|
| `findings/review-11122-a3557a7f-qualified-concurrence-20260904.md` | **Harvested.** Preserves the witnessed withdrawal, the closure classification, and the warning that the compound test command masked failures. An added correction records why the author's earlier private-helper attribution was reverted: the shared closure classified the compound act; `pre_tool_use._is_read_only` was not the deciding layer. |
| `findings/shim-certification-checker-restated-its-own-criterion-20260904.md` | **Harvested.** Preserves the measured duplicate-criterion defect and, prominently, the later refutation of its proposed repair. |
| `findings/wake-0904-the-redundancy-was-the-only-place-the-conflict-showed-2026-09-04.md` | **Harvested.** Preserves the design-conflict correction, the refuted FP15 attribution, and the limits of deriving one artifact from another before their designs are reconciled. |
| `plugins/claude-code/tests/gate_false_refusal_test.py` delta | **Retired, with no runtime assertion carried forward.** The added innate-substring test evaluates Python's own `token in command` expression, never the gate, so it cannot detect a gate fix. The FP15 interpreter attribution is explicitly refuted by the source's own later measurement and remains documented in the harvested wake finding. The useful `fp6_read_with_output_elsewhere` row already exists on current `main` and is unchanged. The reverted `a3557a7f` helper probes from `bfe643d7` / `21c9b67b` are not revived. |

No production code or current certification test is changed for #932.

## #1082 — withdrawn target resolver

The author withdrew the resolver series after command-identity and rebinding
counterexamples. No candidate is restored as a runtime dependency. Each harvested finding
now carries a harvest note so it cannot be read later as an approved implementation.

| Source item | Disposition |
|---|---|
| `findings/a-blacklist-cannot-close-by-enumeration-2026-09-20.md` | **Harvested** with the v1/v3 counterexamples and the later-series withdrawal notice. |
| `findings/review-13301-repaired-matcher-reproduces-2026-09-20.md` | **Harvested** as independent review evidence; its corroboration observations do not revive the resolver. |
| `findings/the-holes-are-a-product-space-2026-09-20.md` | **Harvested** with the v5 counterexamples, generated-space method, and explicit v6 supersession notice. |
| `findings/v6-is-refuted-the-order-dimension-2026-09-20.md` | **Harvested** with all 48 ORDER counterexamples, the corrected fail-direction analysis, and v7's unapproved status. |
| `findings/wake-0920-resolving-a-write-target-instead-of-refusing-the-spelling-2026-09-20.md` | **Harvested** with its original v3 supersession, later-series withdrawal notice, historical census counts, and unresolved-at-the-time claims kept in context. |
| Census and battery tooling | **Archived as evidence only** under `tools/redirect_resolver_1082/`. The battery and historical v5/v6/v7 candidates remain reproducible but are not production imports. Corpus probes require explicit roots and, for exposure, an explicit classifier. Generated-case counts are distinguished from historically observed transcript friction. Hardcoded suite/table runners and the superseded self-access census are explicitly retired in the archive README. |
| `plugins/_shared/test_gate_core.py` delta | **Currentized, not restored verbatim.** Current `main` already contains #1494's identifier narrowing and secret red arms. A new non-governed `tools/gate_egress_data_position_test.py` retains the still-open quoted-heredoc pin and the earned allow controls for a longer identifier, a shell comment, and an appeal comment. The single-quoted grep arm is redundant with the current source-grep pin. The old all-five-deny assertions are superseded and are not carried. |
| Separate here-string defect | **Remains independent:** #1089 was fixed by `2a96c4f4`, not by any resolver candidate. The archive README retains that link. |

Neither source branch is deleted. No file under `plugins/_shared/` changes in this harvest.
