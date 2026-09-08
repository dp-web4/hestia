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

THE ONE BOOTSTRAP PATH (#1001). This is the only tool that seeds the namespace, and its only
write is one `POST /api/config/seed`, which the daemon commits all-or-nothing under its own
lock. `tools/seat_config_ratchet.py` used to do the same job as three sequential PUTs — a
failure after the first left a namespace neither empty nor complete, which this ratchet
then correctly refused to touch, forever. That file is now a wrapper over this one, kept
for the operators whose notes name it. Four lessons it carried came here with it:

  * the workspace is never guessed. `--workspace`, else `HESTIA_WORKSPACE`, else a directory
    that EXISTS among the known names; otherwise refuse. A cwd fallback once sent two seats
    after a shared library that was present and correct the whole time;
  * the endpoint written to the vault is the daemon's own `$HESTIA_HOME/endpoint`, and it
    must be the MCP URL. A bare base URL in the vault shadows the endpoint file and fails as
    a 405 that looks nothing like a config error;
  * the EFFECT is verified, not the call: a document the daemon accepted but did not render
    is the unbacked-projection state, and this exits non-zero on it;
  * either Ed25519 backend signs the operator challenge (PyNaCl or `cryptography`); a seat
    with one and not the other is still a seat.

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


#: The workspace names a box may use, tried in order when nothing names one explicitly.
#: Only a directory that EXISTS is taken — an absent one is never written into the vault.
WORKSPACE_CANDIDATES = ("ai-workspace", "ai-agents")


def resolve_workspace(home: Path, explicit: str | None) -> Path | None:
    """The workspace this box's seats share, or None when it cannot be known.

    An explicit name (flag or `HESTIA_WORKSPACE`) wins and must exist; otherwise the first
    existing candidate under `home`. NEVER a default and never the cwd: the retired seeder's
    hardest-won line was "if it cannot be resolved authoritatively, REFUSE rather than
    guess", after a cwd fallback rendered `<cwd>/hestia_shell_classifier.py` as though it
    were a configured location and sent two seats after a library that was fine.
    """
    if explicit:
        candidate = Path(os.path.expanduser(explicit))
        return candidate.resolve() if candidate.is_dir() else None
    return next((home / name for name in WORKSPACE_CANDIDATES if (home / name).is_dir()), None)


def endpoint_is_mcp(endpoint: str) -> bool:
    """Whether an endpoint is the daemon's MCP URL — the only shape the vault may carry.

    A seat's shim reads `HESTIA_ENDPOINT` straight from its projection and POSTs to it. The
    base URL (`http://host:7711`) answers that with a 405, which reads as a daemon fault,
    not as the config error it is. Measured on two seats before the retired seeder learned
    to refuse it.
    """
    return endpoint.rstrip("/").endswith("/mcp") and "://" in endpoint


def shared_env(home: Path, hestia_home: Path, endpoint: str, workspace: Path) -> dict:
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
         host: str, workspace: str | None = None) -> tuple[str, list[tuple[str, dict]]]:
    """The whole decision, as a pure function so the ratchet can be tested without a daemon.

    Returns `(verdict, documents)` where verdict is `seed`, `occupied`, `no-seats`,
    `no-workspace` or `bad-endpoint`. Refusals are ordered by what they cost to learn: an
    occupied namespace first (nothing else matters), then the two facts that would have been
    written WRONG rather than not at all.
    """
    shared_configured, configured = namespace_state(listing)
    if shared_configured or configured:
        return "occupied", []
    if not endpoint_is_mcp(endpoint):
        return "bad-endpoint", []
    resolved = resolve_workspace(home, workspace)
    if resolved is None:
        return "no-workspace", []
    documents: list[tuple[str, dict]] = [
        (SHARED_MEMBER, shared_env(home, hestia_home, endpoint, resolved))
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

    @staticmethod
    def _signer(seed: bytes):
        """Ed25519 by whichever backend this seat has. Same key, same 64-byte signature.

        `tools/gate-probe.py` uses PyNaCl; `cryptography` ships on more seats (a darwin seat
        had only that). Requiring one of them is a seat's-worth of difference for nothing.
        """
        try:
            from nacl.signing import SigningKey
            return lambda message: SigningKey(seed).sign(message).signature
        except ImportError:
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            except ImportError:
                raise SystemExit("need an Ed25519 backend: pip install pynacl OR cryptography")
            return Ed25519PrivateKey.from_private_bytes(seed).sign

    def open_session(self) -> str:
        cred = json.loads(self.key_path.read_text())
        sign = self._signer(bytes.fromhex(cred["secret_key_hex"])[:32])
        status, challenge = self.call("POST", "/api/operator/challenge")
        if status != 200:
            raise SystemExit(f"operator challenge refused ({status})")
        signature = sign(challenge["challenge"].encode()).hex()
        status, session = self.call("POST", "/api/operator/session", {
            "lct_id": cred["lct_id"], "challenge": challenge["challenge"],
            "signature": signature,
        })
        if status != 200:
            raise SystemExit(f"operator session refused ({status})")
        self.token = session["token"]
        return session.get("operator") or cred["lct_id"]


def verify_rendered(hestia_home: Path, documents: list[tuple[str, dict]]) -> list[str]:
    """Which seeded seats have NO projection on disk, or one missing a seeded key.

    The daemon accepted the documents; that is the call. The projection each seat reads is
    the effect, and a 200 that rendered nothing is exactly the state this tool exists to
    end. Shared keys render into every seat's file, so each seat file is checked for its
    own keys and the shared ones.
    """
    shared = dict(documents).get(SHARED_MEMBER, {})
    missing: list[str] = []
    for member, env in documents:
        if member == SHARED_MEMBER:
            continue
        rendered = hestia_home / "seats" / f"{member}.env"
        try:
            body = "\n" + rendered.read_text()
        except OSError:
            missing.append(f"{member}: {rendered} did not render")
            continue
        absent = [k for k in list(shared) + list(env) if f"\n{k}=" not in body]
        if absent:
            missing.append(f"{member}: rendered without {absent}")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed an EMPTY seat-config namespace.")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument("--workspace", default=os.environ.get("HESTIA_WORKSPACE"),
                        help="the shared workspace root (else HESTIA_WORKSPACE, else an "
                             "existing ~/ai-workspace or ~/ai-agents; never guessed)")
    args = parser.parse_args(argv)

    # THE BOOTSTRAP LOCATOR IS SUPPLIED, NEVER GUESSED (#944, and the #987 review). A
    # migration tool that falls back to `~/.hestia` reintroduces the default this cutover
    # exists to remove, in the one place nobody would look for it — and it would cheerfully
    # seed the wrong vault on a box whose home is elsewhere.
    configured_home = os.environ.get("HESTIA_HOME")
    if not configured_home:
        print("HESTIA_HOME is not set. The bootstrap locator is supplied by the launcher and")
        print("has no default, by design; this tool will not guess which vault to seed.")
        return 2
    hestia_home = Path(configured_home)
    # The harness homes are relative to the OS user's home, which is what each plugin's
    # `expects.json` states (`~/.claude`). That is the user's home, not a hestia root, and it
    # is not a default for anything the vault owns.
    home = Path(os.path.expanduser("~"))
    host = socket.gethostname().split(".")[0].lower()
    endpoint_file = hestia_home / "endpoint"
    try:
        endpoint = endpoint_file.read_text().strip()
    except OSError as e:
        print(f"no endpoint at {endpoint_file} ({e}). The daemon writes it; a box without one")
        print("is not a box this tool can seed. Start the daemon, or point HESTIA_HOME at the")
        print("configured home.")
        return 2
    if not endpoint:
        print(f"{endpoint_file} is empty; refusing to invent an endpoint")
        return 2
    if not endpoint_is_mcp(endpoint):
        print(f"{endpoint_file} holds '{endpoint}', which is not the daemon's MCP URL. Written")
        print("to the vault it would shadow the endpoint file and every seat would fail with a")
        print("405 that looks like a daemon fault. Nothing is attempted.")
        return 2

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
    verdict, documents = plan(listing, seats, home, hestia_home, endpoint, host,
                              workspace=args.workspace)

    if verdict == "no-workspace":
        print("\nNO WORKSPACE RESOLVED — nothing is written. Pass --workspace, set")
        print("  HESTIA_WORKSPACE, or have one of " + ", ".join(f"~/{n}" for n in WORKSPACE_CANDIDATES)
              + " exist. This tool does not fall back to the cwd: that fallback is what made a")
        print("  present-and-correct shared library report as missing on two seats.")
        return 2
    if verdict == "bad-endpoint":
        print(f"\nENDPOINT '{endpoint}' is not the daemon's MCP URL — nothing is written.")
        return 2
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

    # ONE ACT, NOT N WRITES (#987 review). This used to PUT each document in turn, which
    # meant a failure after the first left a namespace that was neither empty nor complete —
    # and this tool's own empty-only ratchet would then refuse to repair it, forever. The
    # daemon owns the compare-and-commit: it re-checks emptiness under its own lock, validates
    # and renders everything, and writes the vault once. This side is the planner.
    note = f"seeded on {host}: the seat-config namespace was empty (tools/seed_seat_config.py)"
    status, result = operator.call("POST", "/api/config/seed", {
        "documents": {member: {"env": env, "note": note} for member, env in documents},
    })
    if status == 409:
        print(f"\nREFUSED: the namespace was occupied between the plan and the commit.")
        print(f"  {json.dumps(result)[:300]}")
        print("  Nothing was written. Another writer won; that is the ratchet working.")
        return 0
    if status != 200:
        print(f"\nSEED REFUSED ({status}): {json.dumps(result)[:300]}")
        print("  Nothing was written — the namespace is byte-identical.")
        return 1

    for verdict in result.get("verdict") or []:
        if isinstance(verdict, dict):
            print(f"  {verdict.get('member', '?'):14} {verdict.get('status', verdict)}")
    print(f"\nSeeded {result.get('seeded')} in one act "
          f"(intent {str(result.get('intentEntryHash'))[:12]}).")

    # VERIFY THE EFFECT, not the call. The daemon renders `$HESTIA_HOME/seats/<seat>.env` as
    # part of the same act; a seat whose file is absent or short is a seat that will refuse
    # its next tool call while this tool has just said "seeded". Report it as the failure
    # it is, so the operator learns it from this line and not from the seat.
    unrendered = verify_rendered(hestia_home, documents)
    if unrendered:
        print("\nSEEDED BUT NOT RENDERED — the vault holds the documents and the seats cannot")
        print("  read them yet. The daemon is the renderer; check it is current and running.")
        for line in unrendered:
            print(f"  ! {line}")
        return 1
    print("Every seeded seat's projection rendered with its keys.")
    print("The seats can act; the operator grants anything beyond the minimum.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
