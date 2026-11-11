#!/usr/bin/env python3
"""Census historical adjudication subject-role attribution without mutating the chain."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from typing import Any, Iterable

from chain_walk import ChainWalker, payload

DEFAULT_MAX_ENTRIES = 1_000_000
DEFAULT_ROLE = "role:constellation:member"


def census(entries: Iterable[dict[str, Any]], max_entries: int = DEFAULT_MAX_ENTRIES) -> dict[str, Any]:
    walked = 0
    head = None
    oldest = None
    adjudications = 0
    roles: collections.Counter[str] = collections.Counter()
    null_or_empty = 0
    writers: collections.Counter[str] = collections.Counter()
    keysets: collections.Counter[str] = collections.Counter()
    explicit_siblings: dict[tuple[Any, Any, Any], set[str]] = {}
    omitted_records: list[tuple[str | None, tuple[Any, Any, Any]]] = []
    all_hashes = []
    omitted_hashes = []

    for entry in entries:
        if walked >= max_entries:
            break
        walked += 1
        if head is None:
            head = entry.get("hash")
        oldest = entry
        if entry.get("eventType") != "adjudication":
            continue
        adjudications += 1
        all_hashes.append(entry.get("hash"))
        data = payload(entry)
        key = (data.get("subject_plugin_id"), data.get("axis"), data.get("ref"))
        if "subject_role" not in data:
            omitted_hashes.append(entry.get("hash"))
            by = data.get("adjudicated_by")
            writer = (
                by.get("plugin_id")
                if isinstance(by, dict)
                else data.get("adjudicator", "<unattributed>")
            )
            writers[str(writer)] += 1
            keysets[",".join(sorted(data))] += 1
            omitted_records.append((entry.get("hash"), key))
            continue
        role = data.get("subject_role")
        if role is None or role == "":
            null_or_empty += 1
            continue
        roles[str(role)] += 1
        if role != DEFAULT_ROLE:
            explicit_siblings.setdefault(key, set()).add(str(role))

    omitted_with_sibling = 0
    sibling_examples = []
    for entry_hash, key in omitted_records:
        sibling_roles = explicit_siblings.get(key)
        if not sibling_roles:
            continue
        omitted_with_sibling += 1
        if len(sibling_examples) < 20:
            sibling_examples.append({
                "hash": entry_hash,
                "subject": key[0],
                "axis": key[1],
                "non_default_roles": sorted(sibling_roles),
            })

    oldest_position = (oldest or {}).get("chainPosition", (oldest or {}).get("chain_position"))
    complete = bool(
        oldest is not None
        and (oldest_position == 0 or not oldest.get("prevHash"))
        and walked < max_entries
    )
    return {
        "as_of_head": head,
        "entries_walked": walked,
        "complete_to_genesis": complete,
        "truncated_at_max_entries": walked >= max_entries,
        "oldest_hash": (oldest or {}).get("hash"),
        "oldest_prev_hash": (oldest or {}).get("prevHash"),
        "oldest_chain_position": oldest_position,
        "oldest_timestamp": (oldest or {}).get("timestamp"),
        "oldest_has_predecessor": bool((oldest or {}).get("prevHash")),
        "adjudications": adjudications,
        "explicit_roles": dict(roles),
        "subject_role_omitted": len(omitted_records),
        "subject_role_null_or_empty": null_or_empty,
        "omitted_writer_shapes": dict(writers),
        "omitted_keysets": dict(keysets),
        "omitted_with_non_default_role_sibling": omitted_with_sibling,
        "omitted_without_non_default_role_sibling": len(omitted_records) - omitted_with_sibling,
        "sibling_examples": sibling_examples,
        "adjudication_hash_sha256": hashlib.sha256("\n".join(all_hashes).encode()).hexdigest(),
        "omitted_hash_sha256": hashlib.sha256("\n".join(omitted_hashes).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--endpoint", default="http://127.0.0.1:7711/mcp")
    args = parser.parse_args()
    walker = ChainWalker(endpoint=args.endpoint)
    print(json.dumps(census(walker.walk(max_entries=args.max), args.max), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
