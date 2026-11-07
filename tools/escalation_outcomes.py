"""Canonical escalation outcome classification for chain censuses (#540)."""

TERMINAL_EVENTS = (
    "gate_escalation_decided",
    "gate_escalation_expired",
    "gate_escalation_withdrawn",
)


def terminal_escalation_ids(events):
    """Ids with a terminal ruling; claims and corroborations do not supply one."""
    return {
        event.get("eventData", {}).get("escalation_id")
        for event in events
        if event.get("eventType") in TERMINAL_EVENTS
        and event.get("eventData", {}).get("escalation_id")
    }
