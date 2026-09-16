#!/usr/bin/env python3
"""Read and write a member's transport binding (#1030) through this box's operator surface.

WHY THIS EXISTS. A transport binding decides whose hub key signs a member's routed acts, and
the daemon only accepts it from a challenge-signed operator session (`POST
/api/transport/binding`). There is no dashboard panel for it yet, so without this the only way
to bind a being was a hand-built signed request. This is that request, planned first and sent
only with `--apply`, with its effect read back.

It is an OPERATOR tool. It signs with `$HESTIA_HOME/operator.key`, reads the key and never
prints it. A seat must not run it on its own authority: choosing a member's carrier is the
operator's act, which is why the daemon offers members no write path at all.

    python3 tools/transport_binding.py list
    python3 tools/transport_binding.py set cbp-being direct_required \\
        --reason "no hub identity file yet; stop seat-signed sends"          # plan only
    python3 tools/transport_binding.py set cbp-being direct --carrier 7ba65c0d-... \\
        --reason "cbp-sage identity file written" --apply
    python3 tools/transport_binding.py remove cbp-being --reason "..." --apply

See docs/TRANSPORT_BINDINGS.md for the modes, the rollout order and what each fault means.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("seed_seat_config", HERE / "seed_seat_config.py")
_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed)
Operator = _seed.Operator

MODES = ("direct", "relay", "direct_required")


def resolve_base(hestia_home: Path) -> str:
    """The daemon base URL from the daemon's own endpoint file. Never guessed."""
    endpoint = (hestia_home / "endpoint").read_text().strip()
    if not _seed.endpoint_is_mcp(endpoint):
        raise SystemExit(f"{hestia_home / 'endpoint'} holds '{endpoint}', not the daemon's MCP URL")
    return endpoint.rsplit("/mcp", 1)[0]


def build_body(args) -> dict:
    body = {"member": args.member, "mode": args.mode, "reason": args.reason}
    for key, val in (("carrier_lct", args.carrier), ("reply_to_lct", args.reply_to),
                     ("delegation_ref", args.delegation)):
        if val:
            body[key] = val
    return body


def show(bindings: list) -> None:
    if not bindings:
        print("  (no bindings: every member is unbound; the drain chooses who signs)")
    for b in bindings:
        print(f"  {b.get('member')}  mode={b.get('mode')}  carrier={b.get('carrier_lct') or '-'}  "
              f"reply_to={b.get('reply_to_lct') or '-'}  version={b.get('version')}  hub={b.get('hub')}")
        print(f"      reason: {b.get('reason')}")


def main(argv=None, operator=None) -> int:
    p = argparse.ArgumentParser(description="Transport bindings (#1030), operator-only.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("set")
    s.add_argument("member")
    s.add_argument("mode", choices=MODES)
    s.add_argument("--carrier", help="hub member LCT that signs (direct: the member's own; relay: the courier)")
    s.add_argument("--reply-to", help="identity replies belong to (phase C routes on it)")
    s.add_argument("--delegation", help="relay only: what authorises the carrier to sign for the member")
    s.add_argument("--reason", required=True)
    s.add_argument("--apply", action="store_true")
    r = sub.add_parser("remove")
    r.add_argument("member")
    r.add_argument("--reason", required=True)
    r.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)

    if operator is None:
        home = os.environ.get("HESTIA_HOME")
        if not home:
            print("HESTIA_HOME is not set; this tool will not guess which daemon to write to.")
            return 2
        operator = Operator(resolve_base(Path(home)), Path(home) / "operator.key")
    who = operator.open_session()
    status, current = operator.call("GET", "/api/transport/binding")
    if status != 200:
        print(f"the daemon refused the binding listing ({status}): {current}")
        print("a daemon older than #1031 has no transport bindings; deploy first")
        return 1
    print(f"operator {who}; generation {current.get('generation')}")
    show(current.get("bindings") or [])
    if args.cmd == "list":
        return 0

    if args.cmd == "set":
        body, path = build_body(args), "/api/transport/binding"
    else:
        body, path = {"member": args.member, "reason": args.reason}, "/api/transport/binding/remove"
    print(f"\n{'SENDING' if args.apply else 'PLAN (dry run; pass --apply)'}: POST {path}")
    print("  " + json.dumps(body))
    if not args.apply:
        return 0
    status, out = operator.call("POST", path, body)
    print(f"  -> {status} {json.dumps(out)}")
    if status != 200:
        return 1
    # The effect, not the call: read the store back and check the member's row.
    status, after = operator.call("GET", "/api/transport/binding")
    rows = [b for b in (after.get("bindings") or []) if b.get("member") == args.member]
    if args.cmd == "set":
        ok = bool(rows) and rows[0].get("mode") == args.mode and rows[0].get("carrier_lct") == (args.carrier or None)
    else:
        ok = not rows
    print(f"\nread back: {'OK' if ok else 'MISMATCH'}")
    show(rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
