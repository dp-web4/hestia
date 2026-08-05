#!/usr/bin/env python3
"""Census the `#undelivered:` echoes in a member's retained primer corpus.

Producer for the numbers in
shared-context/forum/cbp-rc-124-is-anti-evidence-of-undelivery-2026-08-05.md

An echo is a notice whose pointer carries `#undelivered:` — composed by
`report_unreachable()` in hestia-watch-member.sh when a fire command exits
nonzero. It asserts that the notice it is bound to (`in_reply_to`) was never
delivered.

This script tests that assertion against the same corpus: if some OTHER notice
in the corpus is a non-echo reply bound to the same id, the peer answered, and
the echo's assertion is false.

KNOWN BIAS, one-sided: the watcher removes a primer when its fire SUCCEEDS, so
the retained corpus is enriched for failed fires and UNDERCOUNTS genuine
replies. A "no genuine reply visible" row is therefore NOT evidence the echo
was true; a "FALSE" row is solid. Read the false count as a lower bound.

Usage: census-undelivered-echoes.py [primer-dir ...]
Default dir is the claude-code session primer drop.
"""
import collections
import glob
import json
import os
import re
import sys

DEFAULT_DIRS = [os.path.expanduser("~/.claude/hestia-mesh-primers")]

RC_RE = re.compile(r"#undelivered:fire-rc=([^;]*);?(?:why=([^;]*))?")


def load(dirs):
    """Return (echoes by id, genuine replies keyed by the id they answer, seen ids)."""
    echoes, genuine, seen = {}, collections.defaultdict(list), set()
    files = []
    for d in dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "notice-*.json"))))
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue  # a half-written primer is not evidence either way
        for n in d.get("notices", []):
            ptr = str(n.get("pointer_uri") or "")
            nid = n.get("id")
            seen.add(nid)
            if "#undelivered:" in ptr:
                echoes[nid] = n
            elif n.get("in_reply_to") is not None:
                genuine[n["in_reply_to"]].append(nid)
    return echoes, genuine, seen, files


def main():
    dirs = sys.argv[1:] or DEFAULT_DIRS
    echoes, genuine, seen, files = load(dirs)
    print(f"primer files: {len(files)}   distinct notices: {len(seen)}   echoes: {len(echoes)}")

    by_rc = collections.Counter()
    for n in echoes.values():
        m = RC_RE.search(n["pointer_uri"])
        by_rc[(m.group(1) if m else "?", (m.group(2) if m else None) or "-")] += 1
    print("\nrc / why:")
    for (rc, why), count in sorted(by_rc.items(), key=lambda kv: -kv[1]):
        print(f"  rc={rc:<6} why={why:<16} {count}")

    print("\ndoes the notice each echo reports on ALSO have a genuine (non-echo) reply?")
    tally = collections.Counter()
    for nid, n in sorted(echoes.items()):
        target = n.get("in_reply_to")
        answers = genuine.get(target, [])
        m = RC_RE.search(n["pointer_uri"])
        rc = m.group(1) if m else "?"
        tally[(rc, bool(answers))] += 1
        verdict = f"FALSE — genuine reply {answers} exists" if answers else "no genuine reply visible (see BIAS)"
        print(f"  echo {nid:<5} from {str(n.get('from_plugin')):<12} "
              f"reports {str(target):<5} rc={rc:<5} {str(n.get('queued_at'))[:19]}  -> {verdict}")

    print("\nsplit by rc (false / total):")
    for rc in sorted({k[0] for k in tally}):
        false_n = tally[(rc, True)]
        total = false_n + tally[(rc, False)]
        print(f"  rc={rc:<6} {false_n}/{total} demonstrably false")


if __name__ == "__main__":
    main()
