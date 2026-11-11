#!/usr/bin/env python3
"""Terminal-set controls for #540: claims and corroborations are not outcomes."""

from escalation_outcomes import TERMINAL_EVENTS, terminal_escalation_ids

assert set(TERMINAL_EVENTS) == {
    "gate_escalation_decided",
    "gate_escalation_expired",
    "gate_escalation_withdrawn",
}


def event(kind, escalation_id="esc-1"):
    return {"eventType": kind, "eventData": {"escalation_id": escalation_id}}


assert terminal_escalation_ids([
    event("gate_escalation_opened"),
    event("gate_escalation_claimed"),
]) == set(), "a claim without a decision is not terminal"
assert terminal_escalation_ids([
    event("gate_escalation_opened"),
    event("gate_escalation_corroborated"),
]) == set(), "a corroboration without a ruling is not terminal"
assert terminal_escalation_ids([
    event("gate_escalation_opened"),
    event("gate_escalation_decided"),
    event("gate_escalation_claimed"),
]) == {"esc-1"}
assert terminal_escalation_ids([event("gate_escalation_expired")]) == {"esc-1"}
assert terminal_escalation_ids([event("gate_escalation_withdrawn")]) == {"esc-1"}

lifecycle = [
    event("gate_escalation_opened"),
    event("gate_escalation_coalesced"),
    event("gate_escalation_corroborated"),
    event("gate_escalation_claimed"),
    event("gate_escalation_decided"),
    event("gate_escalation_claimed"),
    event("gate_escalation_expired"),
    event("gate_escalation_withdrawn"),
]
assert terminal_escalation_ids(lifecycle) == {"esc-1"}, \
    "one escalation counts once across coalesced/claimed/decided/expired/withdrawn rows"
assert terminal_escalation_ids(lifecycle + lifecycle) == {"esc-1"}, \
    "replayed evidence cannot inflate the terminal count"

legacy = {"eventType": "gate_escalation_decided",
          "eventData": {"escalation_id": "esc-legacy", "status": "approved"}}
assert terminal_escalation_ids([legacy]) == {"esc-legacy"}, \
    "pre-attempt-key chain rows remain valid census inputs"

print("OK — terminal set, claim exclusion, corroboration exclusion, single-count lifecycle, and legacy rows")
