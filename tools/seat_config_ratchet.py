#!/usr/bin/env python3
"""seat_config_ratchet.py — seed the shared + per-seat vault config when none is configured.

WHY THIS EXISTS. The config-from-vault series made the hooks read everything except
HESTIA_HOME from `$HESTIA_HOME/seats/<plugin_id>.env`, which the daemon renders from the
vault — and nothing seeds that vault document. A seat whose vault predates the series
therefore takes its next hestia pull and locks out of EVERY tool, fail-closed, correctly.
HUB lost ~24h and eleven operator round trips to it (2026-09-06); McNugget lost six the
next day, and in both cases the deny text named a shared module that was present and
correct the whole time. `deploy/install-members.sh` cannot fix it: it never touches the
vault. This is the missing step, and it is a RATCHET — it only ever adds absent keys, so
it is safe to re-run and cannot clobber a seat someone has already tuned.

ORDER MATTERS, and the constraints below are learned rather than invented:
  * shared wins, and `keys_owned_by_shared` returns 400 if a seat restates a shared key —
    so the seat document is pruned BEFORE the shared one is written, never after;
  * HESTIA_ENDPOINT is never written. `$HESTIA_HOME/endpoint` is the single source of
    truth; a vault copy silently shadows it and fails as a 405 that looks nothing like a
    config error;
  * HESTIA_WORKSPACE is never defaulted to cwd. The hook's own fallback is
    marker -> cwd, and the cwd arm is what printed `<cwd>/hestia_shell_classifier.py` as
    though it were a configured location, sending two seats after a library that was fine.
    If it cannot be resolved authoritatively this script REFUSES rather than guesses.

Dry-run by default. `--apply` writes. Exits non-zero unless the projection actually
rendered — reporting what resolved and where it came from, which is the one line HUB
asked for and would have ended both incidents in a single round trip.

Usage:
  python3 tools/seat_config_ratchet.py --seat claude-code --workspace ~/repos [--apply]
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request, urllib.error

API = os.environ.get("HESTIA_API", "http://127.0.0.1:7711")
SHARED_ID = "_shared"
NEVER_IN_VAULT = {"HESTIA_ENDPOINT"}          # see module docstring


def _req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw[:300]}


def operator_token():
    """Challenge -> Ed25519 sign -> bearer. Same flow tools/gate-probe.py uses."""
    keyfile = os.path.expanduser("~/.hestia/operator.key")
    if not os.path.exists(keyfile):
        sys.exit(f"FATAL: no operator key at {keyfile} — this script cannot self-authorize, "
                 "and should not be able to.")
    key = json.load(open(keyfile))
    seed = bytes.fromhex(key["secret_key_hex"])[:32]
    # Either backend. tools/gate-probe.py uses PyNaCl; `cryptography` ships on more seats
    # (it is what this darwin seat has). Same Ed25519, same 64-byte signature.
    try:
        from nacl.signing import SigningKey
        _sign = SigningKey(seed).sign
        sign = lambda m: _sign(m).signature
    except ImportError:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            sys.exit("FATAL: need an Ed25519 backend — pip install pynacl OR cryptography.")
        sign = Ed25519PrivateKey.from_private_bytes(seed).sign
    st, ch = _req("POST", "/api/operator/challenge", {})
    if st != 200:
        sys.exit(f"FATAL: challenge failed ({st}): {ch}")
    st, sess = _req("POST", "/api/operator/session", {
        "lct_id": key["lct_id"], "challenge": ch["challenge"],
        "signature": sign(ch["challenge"].encode()).hex()})
    if st != 200 or "token" not in sess:
        sys.exit(f"FATAL: session failed ({st}): {sess}")
    return sess["token"]


def get_seat(token, member):
    st, body = _req("GET", f"/api/config/seat/{member}", token=token)
    if st == 404:
        return {}
    if st != 200:
        sys.exit(f"FATAL: reading seat '{member}' failed ({st}): {body}")
    # SeatConfig is {"env": {...}, "note": "..."} — the variables live UNDER env. Writing
    # them at the top level is accepted with a 200 and renders NOTHING, which is how the
    # first run of this script produced a projection containing only the daemon-derived
    # attribution key. Read and write the same sub-object.
    cfg = body.get("config") or {}
    env = cfg.get("env") if isinstance(cfg, dict) else None
    return env if isinstance(env, dict) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default="claude-code")
    ap.add_argument("--role", default="role:constellation:interactive-dev")
    ap.add_argument("--workspace", default=os.environ.get("HESTIA_WORKSPACE"))
    ap.add_argument("--home", default=os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    home = os.path.realpath(os.path.expanduser(a.home))
    if not os.path.isdir(home):
        sys.exit(f"FATAL: HESTIA_HOME {home} is not a directory.")

    # Never guess the workspace — see docstring. Marker walk, then explicit flag, else refuse.
    ws = a.workspace
    if not ws:
        probe = os.getcwd()
        while probe != "/":
            if os.path.exists(os.path.join(probe, ".hestia-workspace")):
                ws = probe
                break
            probe = os.path.dirname(probe)
    if not ws:
        sys.exit("FATAL: no workspace resolved. Pass --workspace explicitly or drop a\n"
                 "       .hestia-workspace marker at its root. This script will NOT fall back to\n"
                 "       cwd: that fallback is what made a present-and-correct shared library\n"
                 "       report as missing on two seats.")
    ws = os.path.realpath(os.path.expanduser(ws))

    want_shared = {"HESTIA_HOME": home,
                   "HESTIA_SHARED_DIR": os.path.join(home, "shared"),
                   "HESTIA_WORKSPACE": ws}
    want_seat = {"HESTIA_PLUGIN_ID": a.seat, "HESTIA_ROLE": a.role}
    for k in NEVER_IN_VAULT:
        want_shared.pop(k, None); want_seat.pop(k, None)

    token = operator_token()
    cur_shared, cur_seat = get_seat(token, SHARED_ID), get_seat(token, a.seat)

    # RATCHET: only absent keys. An existing value is somebody's decision, not our default.
    add_shared = {k: v for k, v in want_shared.items() if k not in cur_shared}
    add_seat = {k: v for k, v in want_seat.items() if k not in cur_seat}
    # A seat restating a shared key is a 400. Prune BEFORE writing shared.
    prune = [k for k in cur_seat if k in want_shared or k in cur_shared]

    print(f"resolved: home={home}\n          workspace={ws}  (source: "
          f"{'--workspace' if a.workspace else '.hestia-workspace marker'})\n"
          f"          seat={a.seat}")
    print(f"current:  _shared={sorted(cur_shared)}  {a.seat}={sorted(cur_seat)}")
    print(f"would add: _shared+={sorted(add_shared)}  {a.seat}+={sorted(add_seat)}"
          + (f"  prune-from-seat={sorted(prune)}" if prune else ""))
    if not (add_shared or add_seat or prune):
        print("nothing to do — already configured (ratchet is a no-op, as intended).")
    if not a.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    if prune:
        seat_doc = {k: v for k, v in cur_seat.items() if k not in prune}
        st, b = _req("PUT", "/api/config/seat", {"plugin_id": a.seat, "config": {"env": seat_doc}}, token)
        if st not in (200, 201):
            sys.exit(f"FATAL: pruning seat doc failed ({st}): {b}")
        cur_seat = seat_doc
        print(f"pruned {sorted(prune)} from {a.seat} (shared owns them)")
    if add_shared:
        st, b = _req("PUT", "/api/config/seat", {"plugin_id": SHARED_ID,
                                                 "config": {"env": {**cur_shared, **add_shared}}}, token)
        if st not in (200, 201):
            sys.exit(f"FATAL: writing _shared failed ({st}): {b}")
        print(f"wrote _shared += {sorted(add_shared)}")
    if add_seat:
        st, b = _req("PUT", "/api/config/seat", {"plugin_id": a.seat,
                                                 "config": {"env": {**cur_seat, **add_seat}}}, token)
        if st not in (200, 201):
            sys.exit(f"FATAL: writing {a.seat} failed ({st}): {b}")
        print(f"wrote {a.seat} += {sorted(add_seat)}")

    # VERIFY THE EFFECT, not the call. A stored authority that renders nothing is the
    # unbacked-projection state, and reporting success on the 200 would recreate it.
    rendered = os.path.join(home, "seats", f"{a.seat}.env")
    if not os.path.exists(rendered):
        sys.exit(f"FATAL: wrote the vault but {rendered} did not render. The daemon is the "
                 f"renderer — check it is current and running, then re-run.")
    body = open(rendered).read()
    seat_tok = a.seat.upper().replace("-", "_")
    missing = [k for k in want_shared if f"\n{k}=" not in "\n" + body]
    missing += [f"{seat_tok}__{k}" for k in want_seat
                if f"{seat_tok}__{k}=" not in body]
    if missing:
        sys.exit(f"FATAL: {rendered} rendered but is MISSING {missing}. The vault write was "
                 f"accepted and produced nothing usable — assert the effect, not the call.")
    print(f"\nOK: {rendered} rendered ({os.path.getsize(rendered)} bytes), all keys present")
    with open(rendered) as fh:
        for line in fh:
            if line.startswith("#"):
                print("     " + line.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
