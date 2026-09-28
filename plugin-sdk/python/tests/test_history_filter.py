"""HistoryFilter carries exactly the keys the daemon honours (limit, hash, tool_name)."""
from __future__ import annotations

import pytest

from hestia_plugin_sdk import HistoryFilter


def test_removed_filters_are_refused_at_construction() -> None:
    # The daemon refused these outright; constructing one must fail loudly, not at the wire.
    for removed in ("since", "outcome", "target_pattern"):
        with pytest.raises(TypeError):
            HistoryFilter(**{removed: "x"})


def test_honoured_keys_construct() -> None:
    f = HistoryFilter(tool_name="Bash", limit=10, hash="abc")
    assert (f.tool_name, f.limit, f.hash) == ("Bash", 10, "abc")
