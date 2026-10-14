# Hestia gate evidence versus explanatory inference

Source: https://arxiv.org/abs/2512.18792 (The Dead Salmons of AI Interpretability, 2025). This is an adaptation of methodological lessons, not a claim that the paper experimentally validates our architecture.

Core distinction: behavioral observation != causal explanation != normative governance judgment. Interpretability evidence must specify target question/distribution, admissible explanation class, disagreement/validation metric, and null controls. Randomization controls are necessary sanity checks, never proofs of a uniquely identified mechanism.

## Principle
A deterministic gate receipt can establish that a request was evaluated under a particular policy/context and received a particular disposition. It **does not** prove the actor's intent, hidden reasoning, or one unique cause of the request. Never present generated rationale as if it were a witnessed enforcement fact.

## Three levels
1. **Observed/enforced:** actor/LCT subject, request scope, delegated authority context, policy/rule and version, gate verdict, timestamp, immutable receipt/witness reference, appeals and subsequent actions when present. These are only as reliable as the capture boundary and signatures.
2. **Inferred:** explanation such as deliberate privilege escalation, stale delegation, tool error, or ambiguous law. Record hypothesis, evidence links, assumptions, alternative explanations, applicable scope, and uncertainty. No implied causal certainty from a plausible narrative.
3. **Governance disposition:** maintain/revoke/delegate/appeal/escalate under named society rule and authority; label decision separately from observed facts and inferred explanation.

## Worked case
Observed: request to call tool X with scope S rejected by policy R at T with receipt hash H. Plausible mechanisms include stale delegation, accidental parameters, adversarial instruction, conflicting policies. Prohibited leap: 'denial proves malicious intent.' A successful denial also does not prove all adjacent requests are covered. The authority reviews provenance, available context and appeal evidence before updating trust or authorizations.

## Proposed review checklist (documentary only)
- Is every claimed fact traceable to an actual receipt or corroborated witness?
- Are rule version, decision boundary, actor/delegation binding and epistemic scope stated?
- Are inferred causes clearly marked as hypotheses with plausible alternatives?
- Can an external reviewer reconstruct the outcome from available records without trusting the explanation text?
- Can affected outsiders present contrary evidence and access relevant review/escalation processes where law permits?
- Are missing receipts, unavailable context and witness failures labeled unknown rather than clean?

## Experiments / acceptance
Assemble synthetic or consented real gate decisions with known ground truth: denied permission, stale delegation, ambiguous configuration, attempted misuse, and tool-hook execution order anomalies. Have reviewers classify observations independently of hypotheses. Measure unsupported causal assertions, exact-receipt reconstruction, alternative explanations surfaced, and appeal correction. Preserve original receipts; do not retcon history to fit outcome.

No API/schema/protocol changes are proposed here. Any future representational requirement belongs in a separate reviewed specification linked to Web4. No implication that interpretability research can certify agent motives.