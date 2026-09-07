#!/usr/bin/env python3
"""#977: the outcome must close the action the GATE authorized, not a second one.

WHAT WENT WRONG, and why a unit arm exists for it at all. The PostToolUse hook called
`hestia_begin_action` unconditionally and recorded the outcome against that action, while the
PreToolUse gate had already begun, decided on, and cached a different one. Nothing failed. Both
rows were well-formed, both carried `action_id`, and every surface that printed them looked
coherent — so the defect was invisible to every test in the tree and to the dashboards, and was
found only by intersecting the two sets on a live chain: 4,121 outcome rows and 450 gated
`policy_decision` rows over 2.5 days on CBP, sharing ZERO `action_id` values.

That is the shape these arms are built against. A test that merely asserts "an outcome was
recorded" passes on the defect. Each arm below asserts WHICH action was closed, and the cold
paths assert that a discontinuity NAMES itself rather than looking like the bug it replaces.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from projection_fixture import write_projection  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def load_witness(home: Path):
    """Import the hook against a fixture projection, the way the launcher would."""
    os.environ["HESTIA_HOME"] = str(home)
    write_projection(home, "claude-code", {"HESTIA_PLUGIN_ID": "claude-code"})
    spec = importlib.util.spec_from_file_location(
        "witness_under_test", HERE.parent / "hooks" / "witness.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    """Records every tool call and replays scripted replies."""

    def __init__(self, replies: dict[str, list[dict]]):
        self.replies = replies
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, args: dict) -> dict:
        self.calls.append((name, args))
        queue = self.replies.get(name)
        if not queue:
            raise AssertionError(f"unscripted call to {name}")
        return {"result": {"structuredContent": queue.pop(0)}}

    def named(self, name: str) -> list[dict]:
        return [a for n, a in self.calls if n == name]


def intent_for(w, action_id):
    return {
        "tool_name": "Bash", "target": "ls", "success": True, "magnitude": 0.5,
        "error": None, "host_session_id": "host-1", "client_ts": 1.0,
        "action_id": action_id,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        w = load_witness(home)
        print("A. the warm path closes the AUTHORIZED action")

        # A1: an id from the gate's cache is closed directly; NO second begin.
        client = FakeClient({"hestia_record_outcome": [{"ok": True}]})
        verdict = w.witness_one(client, "sess-1", intent_for(w, "GATED-1"))
        check("A1 recorded", verdict == "recorded", verdict)
        check("A1 no second begin_action is issued",
              client.named("hestia_begin_action") == [],
              json.dumps(client.calls))
        recs = client.named("hestia_record_outcome")
        check("A1 the outcome closes the gate's action id",
              len(recs) == 1 and recs[0]["action_id"] == "GATED-1", json.dumps(recs))
        # THE REGRESSION GUARD. Under the defect this asserted nothing, because the id
        # recorded was one this hook had just minted — always present, always wrong.
        check("A1 the recorded id is the one that was handed in, not a fresh one",
              recs[0]["action_id"] == "GATED-1", json.dumps(recs))

        print("B. cold paths name themselves")

        # B1: no cached id at all -> begin here, typed, then record against it.
        client = FakeClient({
            "hestia_begin_action": [{"actionId": "COLD-1"}],
            "hestia_record_outcome": [{"ok": True}],
        })
        verdict = w.witness_one(client, "sess-1", intent_for(w, None))
        check("B1 recorded", verdict == "recorded", verdict)
        begins = client.named("hestia_begin_action")
        check("B1 exactly one begin", len(begins) == 1, json.dumps(begins))
        check("B1 the begin declares WHY it is cold, on the row",
              begins[0].get("intent") == w.COLD_NO_CACHE, json.dumps(begins))
        check("B1 the outcome closes that action",
              client.named("hestia_record_outcome")[0]["action_id"] == "COLD-1",
              json.dumps(client.calls))

        # B2: a cached id the daemon no longer holds (restart between decision and
        # outcome, or a spool row replaying an already-closed act).
        client = FakeClient({
            "hestia_record_outcome": [
                {"_hestia_error": {"code": "hestia.action_not_found", "message": "gone"}},
                {"ok": True},
            ],
            "hestia_begin_action": [{"actionId": "COLD-2"}],
        })
        verdict = w.witness_one(client, "sess-1", intent_for(w, "GATED-STALE"))
        check("B2 recorded", verdict == "recorded", verdict)
        check("B2 the authorized id was TRIED first",
              client.named("hestia_record_outcome")[0]["action_id"] == "GATED-STALE",
              json.dumps(client.calls))
        check("B2 the fallback begin says the authorized action was not resident",
              client.named("hestia_begin_action")[0].get("intent") == w.COLD_STALE,
              json.dumps(client.calls))
        check("B2 and the outcome lands on the replacement",
              client.named("hestia_record_outcome")[1]["action_id"] == "COLD-2",
              json.dumps(client.calls))
        check("B2 the two cold reasons are distinguishable",
              w.COLD_NO_CACHE != w.COLD_STALE, f"{w.COLD_NO_CACHE} {w.COLD_STALE}")

        # B3: a real rejection is still a rejection — the fallback must not launder one.
        client = FakeClient({
            "hestia_record_outcome": [{"_hestia_error": {"code": "hestia.bad_request"}}],
        })
        check("B3 a non-not-found error is rejected, not retried",
              w.witness_one(client, "s", intent_for(w, "GATED-2")) == "rejected"
              and client.named("hestia_begin_action") == [],
              json.dumps(client.calls))

        print("C. the correlation file")
        w.ACTIONS_DIR = Path(tmp) / "actions"
        w.ACTIONS_DIR.mkdir()
        (w.ACTIONS_DIR / "tu-1.json").write_text(
            json.dumps({"action_id": "FROM-CACHE", "tool_name": "Bash", "ts": 1.0}))
        check("C1 the cached id is read back", w.cached_action_id("tu-1") == "FROM-CACHE")
        check("C2 a missing file is None, not an error", w.cached_action_id("nope") is None)
        check("C3 no id is None", w.cached_action_id(None) is None)
        (w.ACTIONS_DIR / "tu-2.json").write_text("{not json")
        check("C4 an unreadable file is None, not a crash", w.cached_action_id("tu-2") is None)
        w.retire_cached_action("tu-1")
        check("C5 retiring removes exactly that file",
              not (w.ACTIONS_DIR / "tu-1.json").exists()
              and (w.ACTIONS_DIR / "tu-2.json").exists(),
              str(sorted(p.name for p in w.ACTIONS_DIR.iterdir())))
        w.retire_cached_action("already-gone")
        check("C6 retiring a file that is not there is not an error", True)

        print("D. the two-phase handoff: release the cache only once the act is DURABLE")
        # The first version of this change released the correlation file as soon as the id
        # was in memory, arguing that a decision with no outcome is a truthful state. It is —
        # but keeping the file does not make it less truthful, and it records WHICH unfinished
        # action the decision belonged to. Dying in that gap destroyed the last durable carrier
        # of the identity for nothing (#977 review). `spool_save` therefore has to REPORT
        # durability, and both of its drop paths must report failure.
        def hand_off(tool_use_id: str) -> bool:
            """The wiring under test, as `main` composes it."""
            if w.spool_save({"client_ts": 1.0, "tool_name": "Bash"}):
                w.retire_cached_action(tool_use_id)
                return True
            return False

        w.SPOOL_DIR = Path(tmp) / "spool"
        (w.ACTIONS_DIR / "keep-1.json").write_text(json.dumps({"action_id": "KEEP-1"}))
        check("D1 a successful spool reports durable", hand_off("keep-1") is True)
        check("D1 and only then is the cache released",
              not (w.ACTIONS_DIR / "keep-1.json").exists())

        # A FULL spool drops this row — the backlog is the alarm — so it is not durable.
        (w.ACTIONS_DIR / "keep-2.json").write_text(json.dumps({"action_id": "KEEP-2"}))
        saved_max, w.SPOOL_MAX_ENTRIES = w.SPOOL_MAX_ENTRIES, 1
        check("D2 a full spool reports NOT durable", hand_off("keep-2") is False)
        check("D2 and the cache SURVIVES, still naming the unfinished action",
              w.cached_action_id("keep-2") == "KEEP-2",
              str(sorted(p.name for p in w.ACTIONS_DIR.iterdir())))
        w.SPOOL_MAX_ENTRIES = saved_max

        # A write failure is the other drop path: same rule.
        w.SPOOL_DIR = Path(tmp) / "not-a-dir" / "spool"
        (Path(tmp) / "not-a-dir").write_text("this is a file, so mkdir must fail")
        check("D3 a failed spool write reports NOT durable", hand_off("keep-2") is False)
        check("D3 and the cache still survives", w.cached_action_id("keep-2") == "KEEP-2")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
