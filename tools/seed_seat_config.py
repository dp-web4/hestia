#!/usr/bin/env python3
"""Seed a box's seat-config namespace when, and only when, it is EMPTY.

WHY THIS EXISTS. Since #959 a governed seat consumes `$HESTIA_HOME/seats/<plugin_id>.env`
and refuses to act without it. The deploy's preflight (#970) therefore refuses to install
hooks onto a box whose vault declares nothing — correctly, since installing them locks the
box out; that happened, on one box, in the two and a half hours between the consumer merging
and the preflight that guards it. The fleet consequence is a half-deploy: current daemon,
un-updated hooks, `deployment stale` on the dashboard, and an update button that fails
identically every time, because no timer cycle repairs a preflight verdict. Every box needs
its documents written once, and nothing wrote them.

WHAT IT SEEDS, AND WHAT IT REFUSES TO. Description only: where this box keeps each seat's
files, and the society facts every seat inherits. Nothing that GRANTS. Scope, standing scope
and every other authority stay operator-only and are not touched. The daemon already draws
that line for standing scope, where an absent authority is reported rather than invented
("this is a migration, not a fresh install"); seeding layout is not the same act as seeding
permission, and the value of this tool is that it never confuses them.

THE RATCHET. It writes only against an EMPTY namespace: no shared set, no seat document. A
box that is half-configured is a box somebody is configuring, and the missing half is a
choice this tool cannot read. Nothing is ever modified or deleted; the only write is the
first one.

    python3 tools/seed_seat_config.py            # measure, print the plan, change nothing
    python3 tools/seed_seat_config.py --apply    # write, only if the namespace is empty
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED_MEMBER = "_shared"

# The identity-key spelling each seat's shim reads, keyed by the member id its own
# `expects.json` declares. Kept here rather than derived from the member id because the two
# genuinely differ (`kimi-code` reads `HESTIA_KIMI_IDENTITY`), and a derivation that is right
# three times out of four is worse than a table that is visibly a table.
IDENTITY_KEY = {
    "claude-code": "HESTIA_CLAUDE_IDENTITY",
    "codex": "HESTIA_CODEX_IDENTITY",
    "kimi-code": "HESTIA_KIMI_IDENTITY",
    "gemini": "HESTIA_GEMINI_IDENTITY",
}


def declared_seats(repo: Path, home: Path) -> tuple[list[dict], list[str]]:
    """Every seat this REPO knows how to install, from its own `expects.json`.

    The harness home comes from `install.registration.path[0]` — the directory holding that
    harness's config file, the one place the repo already states it. No harness→home table
    is written here: a second table drifts against the installer's.

    Returns `(seats, skipped)`; a plugin that declares no member id is skipped and named,
    never guessed. Guessing is the drift this avoids — the installed manifest calls one seat
    `kimi` while the daemon, vault and chain call it `kimi-code`, because the installer used
    the plugin's directory name as its id.
    """
    seats: list[dict] = []
    skipped: list[str] = []
    for path in sorted(repo.glob("plugins/*/expects.json")):
        try:
            spec = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            skipped.append(f"{path.parent.name} (unreadable: {e})")
            continue
        install = spec.get("install") or {}
        member = install.get("member")
        registration = (install.get("registration") or {}).get("path") or []
        if not member or not registration:
            skipped.append(f"{path.parent.name} (no install.member or registration.path)")
            continue
        seats.append({"member": member, "harness_home": home / registration[0]})
    return seats, skipped


def shared_env(home: Path, hestia_home: Path, endpoint: str) -> dict:
    workspace = next((p for p in (home / "ai-workspace", home / "ai-agents") if p.is_dir()),
                     home / "ai-workspace")
    return {
        "HESTIA_HOME": str(hestia_home),
        "HESTIA_WORKSPACE": str(workspace),
        "HESTIA_SHARED_DIR": str(hestia_home / "shared"),
        "HESTIA_ENDPOINT": endpoint,
    }


def seat_env(seat: dict, host: str) -> dict:
    """The minimum a thin shim needs to act.

    Deliberately small. An operator adds what a seat turns out to read; a key nobody reads is
    how an authority surface starts describing a runtime that does not exist — measured on
    CBP, where one seat's document named an observe directory for a component that seat does
    not have and a path that did not exist.
    """
    harness: Path = seat["harness_home"]
    env = {
        "HESTIA_PLUGIN_ID": seat["member"],
        "HESTIA_HARNESS_HOME": str(harness),
        "HESTIA_MESH_PLUGIN": seat["member"],
        "HESTIA_MESH_HOST_AGENT": f"{seat['member']}-{host}",
    }
    identity_key = IDENTITY_KEY.get(seat["member"])
    if identity_key:
        env[identity_key] = str(harness / "hestia-instance" / "identity.json")
    state = harness / "hestia-instance"
    if state.is_dir():
        env["HESTIA_STATE_DIR"] = str(state)
    return env


def namespace_state(listing: dict | list) -> tuple[bool, list[str]]:
    """`(shared_configured, [configured members])` from a `GET /api/config/seat` body."""
    rows = (listing.get("seats") if isinstance(listing, dict) else listing) or []
    configured = [r.get("member") for r in rows
                  if isinstance(r, dict) and r.get("configured")]
    shared = listing.get("shared") if isinstance(listing, dict) else None
    return bool(shared and shared.get("configured")), [m for m in configured if m]


def plan(listing, seats: list[dict], home: Path, hestia_home: Path, endpoint: str,
         host: str) -> tuple[str, list[tuple[str, dict]]]:
    """The whole decision, as a pure function so the ratchet can be tested without a daemon.

    Returns `(verdict, documents)` where verdict is `seed`, `occupied` or `no-seats`.
    """
    shared_configured, configured = namespace_state(listing)
    if shared_configured or configured:
        return "occupied", []
    documents: list[tuple[str, dict]] = [
        (SHARED_MEMBER, shared_env(home, hestia_home, endpoint))
    ]
    for seat in seats:
        if seat["harness_home"].is_dir():
            documents.append((seat["member"], seat_env(seat, host)))
    if len(documents) == 1:
        return "no-seats", []
    return "seed", documents


# ---- the operator surface ------------------------------------------------------------


class Operator:
    """Challenge/sign/session against this box's own daemon, as `tools/gate-probe.py` does.

    The key is read, never printed, and never leaves the process.
    """

    def __init__(self, base: str, key_path: Path):
        self.base = base.rstrip("/")
        self.key_path = key_path
        self.token: str | None = None

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        if self.token:
            req.add_header("authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def open_session(self) -> str:
        from nacl.signing import SigningKey

        cred = json.loads(self.key_path.read_text())
        signing = SigningKey(bytes.fromhex(cred["secret_key_hex"])[:32])
        status, challenge = self.call("POST", "/api/operator/challenge")
        if status != 200:
            raise SystemExit(f"operator challenge refused ({status})")
        signature = signing.sign(challenge["challenge"].encode()).signature.hex()
        status, session = self.call("POST", "/api/operator/session", {
            "lct_id": cred["lct_id"], "challenge": challenge["challenge"],
            "signature": signature,
        })
        if status != 200:
            raise SystemExit(f"operator session refused ({status})")
        self.token = session["token"]
        return session.get("operator") or cred["lct_id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed an EMPTY seat-config namespace.")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = parser.parse_args(argv)

    home = Path(os.path.expanduser("~"))
    hestia_home = Path(os.environ.get("HESTIA_HOME") or (home / ".hestia"))
    host = socket.gethostname().split(".")[0].lower()
    try:
        endpoint = (hestia_home / "endpoint").read_text().strip()
    except OSError:
        endpoint = "http://127.0.0.1:7711/mcp"

    operator = Operator(endpoint.rsplit("/mcp", 1)[0], hestia_home / "operator.key")
    who = operator.open_session()
    print(f"host {host}, operator {who}")

    status, listing = operator.call("GET", "/api/config/seat")
    if status != 200:
        print(f"  the daemon refused the operator surface ({status}); nothing is attempted")
        return 1
    shared_configured, configured = namespace_state(listing)
    print(f"  shared set configured: {shared_configured}")
    print(f"  seats configured     : {configured or 'none'}")

    seats, skipped = declared_seats(REPO, home)
    for note in skipped:
        print(f"  ! skipped {note}")
    verdict, documents = plan(listing, seats, home, hestia_home, endpoint, host)

    if verdict == "occupied":
        print("\nNAMESPACE IS NOT EMPTY — nothing is written.")
        print("  This tool seeds a box that has never been configured. A box that is partly")
        print("  configured is one somebody is configuring, and the missing half is a choice")
        print("  this tool cannot read. Use the operator surface directly.")
        return 0
    if verdict == "no-seats":
        print("\nNO INSTALLED SEAT FOUND — nothing is written. Only the shared set would be,")
        print("  and a box with no harness home is not a box this repair helps. Check that")
        print("  the harness directories exist before seeding.")
        return 1

    print(f"\n{'WRITING' if args.apply else 'PLAN (dry run; pass --apply)'}: "
          f"{len(documents)} document(s)")
    for member, env in documents:
        print(f"  {member}")
        for key in sorted(env):
            print(f"      {key} = {env[key]}")
    if not args.apply:
        return 0

    note = f"seeded on {host}: the seat-config namespace was empty (tools/seed_seat_config.py)"
    for member, env in documents:
        status, result = operator.call("PUT", "/api/config/seat", {
            "plugin_id": member, "config": {"env": env, "note": note},
        })
        print(f"  {member}: {status} {json.dumps(result)[:120]}")
        if status != 200:
            print("  STOPPING — the write was refused; the namespace is left as it is")
            return 1

    status, listing = operator.call("GET", "/api/config/seat")
    for row in (listing.get("seats") if isinstance(listing, dict) else listing) or []:
        if isinstance(row, dict):
            print(f"  {row.get('member'):14} {(row.get('verdict') or {}).get('status')}")
    print("\nSeeded. The seats can act; the operator grants anything beyond the minimum.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
