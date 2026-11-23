#!/usr/bin/env python3
"""#1163: the governance ledger renders dissent as dissent, with its evidence attached."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
RUST = (ROOT / "core/src/server/governance_ledger.rs").read_text()
FAILURES = []


def check(name: str, condition: bool) -> None:
    if not condition:
        FAILURES.append(name)


def main() -> int:
    check("structured corroborations replace name-only rows",
          "pub struct Corroboration" in RUST and "pub corroborations: Vec<Corroboration>" in RUST)
    check("projection carries stance", "pub stance: String" in RUST)
    check("projection carries independence", "pub independence: Option<String>" in RUST)
    check("projection carries the factor timestamp", "pub at: String" in RUST)
    check("projection carries bounded argument and full-text hash",
          "pub argument: Option<String>" in RUST and "pub chain_hash: String" in RUST)
    check("UI distinguishes dissent from support",
          "c.stance === 'dissent'" in UI and "ledger-dissent" in UI)
    check("UI shows the argument", "<summary>argument</summary>" in UI)
    check("UI links the full factor, not a truncated command",
          "/api/chain?filter.hash=${encodeURIComponent(c.chain_hash)}" in UI)
    check("the old name-only join is gone", "r.corroborations.join(', ')" not in UI)
    if FAILURES:
        print("FAIL\n  " + "\n  ".join(FAILURES))
        return 1
    print("ok: governance-ledger corroborations carry stance, independence, argument and full-text link")
    return 0


def teardown_module(module):
    assert not FAILURES, FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
