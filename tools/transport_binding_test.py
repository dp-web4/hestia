#!/usr/bin/env python3
"""tools/transport_binding.py against a fake operator surface: a plan sends nothing, --apply
sends exactly the planned body, and the effect is read back rather than assumed."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("transport_binding", HERE / "transport_binding.py")
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)


class FakeOperator:
    def __init__(self, store_after=None):
        self.calls = []
        self.bindings = []
        self.store_after = store_after

    def open_session(self):
        return "lct:web4:operator"

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return 200, {"bindings": list(self.bindings), "generation": len(self.calls)}
        if path.endswith("/remove"):
            self.bindings = [b for b in self.bindings if b["member"] != body["member"]]
        elif self.store_after is not None:
            self.bindings = self.store_after
        else:
            self.bindings = [b for b in self.bindings if b["member"] != body["member"]] + [dict(body, version=1, hub="*")]
        return 200, {"ok": True}


def posts(op):
    return [c for c in op.calls if c[0] == "POST"]


def test_a_plan_sends_nothing():
    op = FakeOperator()
    assert tb.main(["set", "cbp-being", "direct_required", "--reason", "r"], operator=op) == 0
    assert posts(op) == []


def test_apply_sends_the_planned_body_and_reads_it_back():
    op = FakeOperator()
    rc = tb.main(["set", "cbp-being", "direct", "--carrier", "7ba65c0d", "--reason", "identity written",
                  "--apply"], operator=op)
    assert rc == 0
    assert posts(op) == [("POST", "/api/transport/binding",
                          {"member": "cbp-being", "mode": "direct", "reason": "identity written",
                           "carrier_lct": "7ba65c0d"})]
    assert op.calls[-1][0] == "GET", "the effect is read back after the write"


def test_a_write_the_store_does_not_reflect_fails():
    op = FakeOperator(store_after=[])
    assert tb.main(["set", "cbp-being", "direct_required", "--reason", "r", "--apply"], operator=op) == 1


def test_remove_reads_back_absence():
    op = FakeOperator()
    op.bindings = [{"member": "cbp-being", "mode": "direct_required", "reason": "r", "version": 1, "hub": "*"}]
    assert tb.main(["remove", "cbp-being", "--reason", "rebinding", "--apply"], operator=op) == 0
    assert posts(op)[0][1] == "/api/transport/binding/remove"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print(f"PASS {name}")
    print(f"\n{n} passed")
