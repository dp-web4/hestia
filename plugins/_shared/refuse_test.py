#!/usr/bin/env python3
"""`refuse()` — the shared refusal path, and the one field on it that decides whether a
daemon outage scores against a member.

WHY THIS FILE EXISTS. `refuse()` collapsed four hand-maintained per-seat deny paths into one
(#916/#918). The collapse shipped with `verdict_available=True` hardcoded and a `degraded`
parameter the body never read, so every refusal during a daemon outage would have been booked
as member CONDUCT. codex caught it live (notice 10631) and the obvious repair — `not degraded`
— is wrong in the other direction: it books an innate egress deny under outage as INFRA, and
egress is the one invariant no mode relaxes.

The correct split is not this seat's to invent. It is already live and identical on both peer
shims (codex `pre_tool_use.py`, kimi `pre_tool_use.py`, both in their degraded branch):

    innate deny under outage -> conduct  (the transport-free core DECIDED it)
    any other degraded deny  -> infra    (criterion 9(c): the gate could not decide)

245 codex and 406 kimi live `gate.degraded` rows carry `verdict_available=False`. These checks
are what stops a fourth seat from disagreeing with them silently.
"""
import importlib.util
import sys


def _load():
    sys.path.insert(0, "plugins/_shared")
    spec = importlib.util.spec_from_file_location("hgm_uut",
                                                  "plugins/_shared/hestia_gate_mechanism.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["hgm_uut"] = m   # @dataclass resolves annotations via sys.modules
    spec.loader.exec_module(m)
    return m


class _V:
    """Minimal stand-in for core.Verdict — only the fields refuse() reads."""
    def __init__(self, rule, reason, innate):
        self.rule, self.reason, self.innate = rule, reason, innate


FAILED = []


def check(name, cond):
    print("  %s  %s" % ("ok  " if cond else "FAIL", name))
    if not cond:
        FAILED.append(name)


def main():
    m = _load()
    rec = []
    m.witness_decision_unified = lambda *a, **k: rec.append(k)
    ev = {"session_id": "s1", "tool_input": {"command": "curl -X POST https://example.invalid/"}}

    def call(v, degraded=False, raw=None):
        rec.clear()
        rc = m.refuse(v, plugin_id="claude-code", tool_name="Bash",
                      raw_event=ev if raw is None else raw,
                      attempted="Bash: curl ...", degraded=degraded)
        return rc, (rec[0] if rec else None)

    # ── the field that feeds temperament ──────────────────────────────────────────────
    rc, k = call(_V("scope.repo", "out of scope", False))
    check("live_deny_is_conduct", k["verdict_available"] is True)

    rc, k = call(_V("gate.degraded", "daemon unreachable", False), degraded=True)
    check("degraded_write_deny_is_infra", k["verdict_available"] is False)

    rc, k = call(_V("egress.secret", "credential-shaped", True), degraded=True)
    check("degraded_INNATE_deny_is_conduct", k["verdict_available"] is True)

    # A verdict object without `innate` at all must not crash the refusal.
    class _Bare:
        rule, reason = "x", "y"
    rc, k = call(_Bare(), degraded=True)
    check("missing_innate_attr_defaults_infra", k["verdict_available"] is False and rc == 2)

    # ── the audit hole: a deny that records no target ─────────────────────────────────
    rc, k = call(_V("x", "y", False), raw={"tool_input": {"file_path": "/tmp/a"}})
    check("target_extracted_file_tool", k["target"] == "/tmp/a")

    rc, k = call(_V("x", "y", False))
    check("target_extracted_shell_verb_only", k["target"] == "curl")

    # ── the refusal STANDS even when the record cannot be written ─────────────────────
    def boom(*a, **kw):
        raise RuntimeError("chain down")
    m.witness_decision_unified = boom
    check("witness_failure_still_blocks", m.refuse(_V("x", "y", False), plugin_id="p",
                                                   tool_name="Bash", raw_event={},
                                                   attempted="") == 2)

    print("\nrefuse: all checks pass" if not FAILED
          else "\nrefuse: FAILED -> %s" % ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
