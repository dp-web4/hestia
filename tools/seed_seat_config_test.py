#!/usr/bin/env python3
"""The seeder's ratchet and its plan, driven on fixtures rather than on a live daemon.

WHAT THESE ARMS ARE BUILT AGAINST. A seeder is a tool whose failure mode is silent and
expensive: it writes authority-adjacent documents to a box nobody is watching, and the box
then behaves as if a person had described it. So the arms are not "does it write" — they are
"what would make it write when it must not", and each names the state it refuses.

The decision lives in `plan()`, deliberately pure, so every arm below runs with no operator
key, no daemon and no network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("seeder", HERE / "seed_seat_config.py")
seeder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seeder)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def listing(shared: bool, members: list[str], unconfigured: list[str] = ()) -> dict:
    seats = [{"member": m, "configured": True} for m in members]
    seats += [{"member": m, "configured": False} for m in unconfigured]
    return {"shared": {"configured": shared}, "seats": seats}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        hestia_home = home / ".hestia"
        # Two harness homes exist on this fixture box; two do not.
        (home / ".claude" / "hestia-instance").mkdir(parents=True)
        (home / ".codex").mkdir(parents=True)
        (home / "ai-workspace").mkdir()      # the workspace must EXIST to be seeded (#1001)
        seats = [
            {"member": "claude-code", "harness_home": home / ".claude"},
            {"member": "codex", "harness_home": home / ".codex"},
            {"member": "kimi-code", "harness_home": home / ".kimi-code"},
            {"member": "gemini", "harness_home": home / ".gemini"},
        ]
        args = (home, hestia_home, "http://127.0.0.1:7711/mcp", "testbox")

        print("A. the ratchet — every non-empty state refuses")
        for name, body in (
            ("a fully configured box", listing(True, ["claude-code", "codex"])),
            ("only the shared set", listing(True, [])),
            ("only one seat", listing(False, ["codex"])),
            ("a seat configured and others not", listing(False, ["codex"], ["gemini"])),
        ):
            verdict, docs = seeder.plan(body, seats, *args)
            check(f"A refuses: {name}", verdict == "occupied" and docs == [], f"{verdict} {docs}")
        # The one state it acts on. `configured: False` rows are the daemon reporting seats it
        # KNOWS about but has no document for — that is an empty namespace, not a partial one.
        verdict, docs = seeder.plan(listing(False, [], ["claude-code", "codex"]), seats, *args)
        check("A seeds: known-but-unconfigured seats are an EMPTY namespace",
              verdict == "seed", verdict)

        print("B. the plan describes this box, and only what is on it")
        verdict, docs = seeder.plan(listing(False, []), seats, *args)
        members = [m for m, _ in docs]
        check("B verdict is seed", verdict == "seed", verdict)
        check("B the shared set is written first",
              members[0] == "_shared", str(members))
        check("B only harness homes that EXIST are seeded",
              members[1:] == ["claude-code", "codex"], str(members))
        env = dict(docs)["claude-code"]
        check("B the seat names itself", env["HESTIA_PLUGIN_ID"] == "claude-code", str(env))
        check("B the identity key uses the harness spelling, not the member id",
              env["HESTIA_CLAUDE_IDENTITY"].endswith("identity.json"), str(env))
        check("B a state dir is included only when it exists",
              "HESTIA_STATE_DIR" in env and "HESTIA_STATE_DIR" not in dict(docs)["codex"],
              f"{env} / {dict(docs)['codex']}")

        print("C. it seeds DESCRIPTION, never authority")
        # The line this tool exists to hold. A key that grants — scope, standing, a role, a
        # capability — must never appear in a seeded document; the operator grants those.
        banned = ("SCOPE", "STANDING", "GRANT", "ROLE", "TOKEN", "SECRET", "KEY", "CAPABILIT")
        offenders = [(m, k) for m, e in docs for k in e
                     if any(b in k.upper() for b in banned)]
        check("C no seeded key grants anything", not offenders, str(offenders))
        shared = dict(docs)["_shared"]
        check("C the shared set is four society facts",
              sorted(shared) == ["HESTIA_ENDPOINT", "HESTIA_HOME", "HESTIA_SHARED_DIR",
                                 "HESTIA_WORKSPACE"], str(sorted(shared)))

        print("C2. the two facts the retired seeder refused to guess are refused here too")
        verdict, docs = seeder.plan(listing(False, []), seats, home, hestia_home,
                                    "http://127.0.0.1:7711", "testbox")
        check("C2 a base URL (no /mcp) is bad-endpoint, not a document",
              verdict == "bad-endpoint" and docs == [], f"{verdict} {docs}")
        verdict, docs = seeder.plan(listing(False, []), seats, *args,
                                    workspace=str(home / "does-not-exist"))
        check("C2 an explicit workspace that does not exist is no-workspace",
              verdict == "no-workspace" and docs == [], f"{verdict} {docs}")
        check("C2 no candidate on the box resolves to None, never to a made-up path",
              seeder.resolve_workspace(home / "empty", None) is None)
        verdict, docs = seeder.plan(listing(False, []), seats, *args,
                                    workspace=str(home / "ai-workspace"))
        check("C2 an explicit existing workspace is written as given",
              verdict == "seed" and dict(docs)["_shared"]["HESTIA_WORKSPACE"]
              == str((home / "ai-workspace").resolve()), str(docs[:1]))

        print("C3. the effect is verified per seat, shared keys included")
        seats_dir = hestia_home / "seats"
        seats_dir.mkdir(parents=True)
        shared_env, seat_env = dict(docs)["_shared"], dict(docs)["claude-code"]
        (seats_dir / "claude-code.env").write_text(
            "\n".join(f"{k}={v}" for k, v in {**shared_env, **seat_env}.items()) + "\n")
        missing = seeder.verify_rendered(hestia_home, docs)
        check("C3 the seat with a full projection passes; the seat with none is named",
              len(missing) == 1 and missing[0].startswith("codex:"), str(missing))
        (seats_dir / "claude-code.env").write_text("HESTIA_PLUGIN_ID=claude-code\n")
        missing = seeder.verify_rendered(hestia_home, docs)
        check("C3 a projection missing a SHARED key is reported, not passed on the 200",
              any(m.startswith("claude-code:") and "HESTIA_HOME" in m for m in missing), str(missing))

        print("D. a box with no seat is not seeded at all")
        bare = [{"member": "kimi-code", "harness_home": home / ".kimi-code"}]
        verdict, docs = seeder.plan(listing(False, []), bare, *args)
        check("D no installed seat -> refuses, rather than writing a lone shared set",
              verdict == "no-seats" and docs == [], f"{verdict} {docs}")

        print("E. the repo's own declarations are read, and gaps are named not guessed")
        repo = Path(__file__).resolve().parent.parent
        found, skipped = seeder.declared_seats(repo, home)
        by_member = {s["member"] for s in found}
        check("E every plugin declares a member id (none skipped)",
              not skipped, str(skipped))
        check("E the seat ids are the ones the daemon uses",
              {"claude-code", "codex", "kimi-code", "gemini"} <= by_member, str(by_member))
        check("E kimi is declared kimi-code, not its directory name",
              "kimi-code" in by_member and "kimi" not in by_member, str(by_member))
        check("E every declared member has an identity-key spelling",
              all(s["member"] in seeder.IDENTITY_KEY for s in found),
              str([s["member"] for s in found if s["member"] not in seeder.IDENTITY_KEY]))

        # A plugin that declares no member is skipped BY NAME. Silent omission is how a box
        # gets seeded for three of its four seats and nobody notices the fourth.
        fake = home / "repo" / "plugins" / "mystery"
        fake.mkdir(parents=True)
        (fake / "expects.json").write_text(json.dumps({"install": {"dest": "~/.mystery"}}))
        found2, skipped2 = seeder.declared_seats(home / "repo", home)
        check("E a plugin with no declared member is skipped and NAMED",
              found2 == [] and any("mystery" in s for s in skipped2), str(skipped2))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
