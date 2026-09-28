#!/usr/bin/env python3
"""One bootstrap path (#1001): the old name reaches the atomic seed door and NEVER a PUT.

The acceptance this issue wrote is about what a run can DO to the daemon, so these arms
drive the real `main()` of both tools against a recording operator surface — no network,
no key, no daemon — and assert on the request log. A fake daemon that fails the run on any
PUT is the proof that docs, notes and muscle memory naming the old file cannot reach the
sequential path any more.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load("seat_config_ratchet")
seeder = wrapper.seeder          # the wrapper's OWN seeder instance is the one it calls

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


class RecordingOperator:
    """Stands in for `seeder.Operator`: same constructor, same two methods, records all.

    GET /api/config/seat answers with `listing`; POST /api/config/seed renders the seat
    files under `render_into` (as the daemon's Author pass would) unless `render=False`;
    anything else — a PUT above all — is answered 500 and left in the log for the arm.
    """
    instances: list["RecordingOperator"] = []
    listing: dict = {}
    render_into: Path | None = None
    render = True

    def __init__(self, base: str, key_path: Path):
        self.base, self.key_path, self.calls = base, key_path, []
        RecordingOperator.instances.append(self)

    def open_session(self) -> str:
        return "fixture-operator"

    def call(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/api/config/seat":
            return 200, RecordingOperator.listing
        if method == "POST" and path == "/api/config/seed":
            docs = (body or {}).get("documents") or {}
            if RecordingOperator.render and RecordingOperator.render_into:
                shared = docs.get("_shared", {}).get("env", {})
                for member, doc in docs.items():
                    if member == "_shared":
                        continue
                    seat = RecordingOperator.render_into / "seats" / f"{member}.env"
                    seat.parent.mkdir(parents=True, exist_ok=True)
                    lines = [f"{k}={v}" for k, v in {**shared, **doc.get('env', {})}.items()]
                    seat.write_text("# rendered by the fixture daemon\n" + "\n".join(lines) + "\n")
            return 200, {"seeded": sorted(docs), "intentEntryHash": "fixture-intent",
                         "verdict": [{"member": m, "status": "seeded"} for m in docs]}
        return 500, {"error": f"the fixture daemon does not serve {method} {path}"}


def writes(op: RecordingOperator) -> list[tuple[str, str]]:
    return [(m, p) for m, p, _ in op.calls if m != "GET"]


def run_seeder(argv: list[str], **fixture) -> tuple[int, RecordingOperator | None]:
    RecordingOperator.instances.clear()
    RecordingOperator.listing = fixture.get("listing", {"shared": {"configured": False}, "seats": []})
    RecordingOperator.render = fixture.get("render", True)
    rc = seeder.main(argv)
    return rc, (RecordingOperator.instances[0] if RecordingOperator.instances else None)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        hestia_home = home / ".hestia"
        hestia_home.mkdir()
        (hestia_home / "endpoint").write_text("http://127.0.0.1:7711/mcp\n")
        (hestia_home / "operator.key").write_text("{}")     # never read: the operator is a fixture
        (home / "ai-workspace").mkdir()
        (home / ".claude" / "hestia-instance").mkdir(parents=True)
        (home / ".codex").mkdir()
        os.environ["HOME"] = str(home)                      # the harness homes resolve under it
        os.environ["HESTIA_HOME"] = str(hestia_home)
        os.environ.pop("HESTIA_WORKSPACE", None)
        seeder.Operator = RecordingOperator
        RecordingOperator.render_into = hestia_home

        print("A. the seeder's only write is ONE POST /api/config/seed")
        rc, op = run_seeder(["--apply"])
        check("A rc 0", rc == 0, str(rc))
        check("A exactly one write, and it is the atomic seed door",
              writes(op) == [("POST", "/api/config/seed")], str(op.calls))
        check("A no PUT reached the daemon",
              not any(m == "PUT" for m, _, _ in op.calls), str(op.calls))
        seed_body = next(b for m, p, b in op.calls if p == "/api/config/seed")
        check("A the shared set and every installed seat travel in the one body",
              set(seed_body["documents"]) == {"_shared", "claude-code", "codex"},
              str(sorted(seed_body["documents"])))
        check("A the vault endpoint is the MCP URL, verbatim from the endpoint file",
              seed_body["documents"]["_shared"]["env"]["HESTIA_ENDPOINT"] == "http://127.0.0.1:7711/mcp",
              str(seed_body["documents"]["_shared"]["env"]))
        check("A the effect was verified: both projections rendered",
              (hestia_home / "seats" / "claude-code.env").exists()
              and (hestia_home / "seats" / "codex.env").exists())

        print("B. a dry run writes nothing at all")
        rc, op = run_seeder([])
        check("B rc 0 and zero writes", rc == 0 and writes(op) == [], f"{rc} {op.calls}")

        print("C. an occupied namespace is refused before any write")
        rc, op = run_seeder(["--apply"], listing={"shared": {"configured": True},
                                                  "seats": [{"member": "codex", "configured": True}]})
        check("C rc 0 and zero writes", rc == 0 and writes(op) == [], f"{rc} {op.calls}")

        print("D. seeded-but-unrendered is reported as the failure it is")
        for f in (hestia_home / "seats").glob("*.env"):
            f.unlink()
        rc, op = run_seeder(["--apply"], render=False)
        check("D the seed went through (one POST) but rc is 1",
              rc == 1 and writes(op) == [("POST", "/api/config/seed")], f"{rc} {op.calls}")

        print("E. the two facts that would be written WRONG are refused, not defaulted")
        (hestia_home / "endpoint").write_text("http://127.0.0.1:7711\n")     # base URL, no /mcp
        rc, op = run_seeder(["--apply"])
        check("E a non-MCP endpoint refuses before the operator surface is even opened",
              rc == 2 and op is None, f"{rc} {op and op.calls}")
        (hestia_home / "endpoint").write_text("http://127.0.0.1:7711/mcp\n")
        rc, op = run_seeder(["--apply", "--workspace", str(home / "nowhere")])
        check("E an explicit workspace that does not exist refuses with zero writes",
              rc == 2 and (op is None or writes(op) == []), f"{rc} {op and op.calls}")
        (home / "ai-workspace").rename(home / "elsewhere")
        rc, op = run_seeder(["--apply"])
        check("E no known workspace on the box refuses with zero writes (never the cwd)",
              rc == 2 and (op is None or writes(op) == []), f"{rc} {op and op.calls}")
        (home / "elsewhere").rename(home / "ai-workspace")

        print("F. the old name is a wrapper: it translates and calls the seeder ONCE")
        called: list[list[str]] = []
        real_main = seeder.main
        seeder.main = lambda argv: (called.append(list(argv)), 0)[1]
        try:
            env = {"HESTIA_HOME": str(hestia_home)}
            argv, notes = wrapper.translate(
                ["--seat", "claude-code", "--role", "role:constellation:interactive-dev",
                 "--workspace", "/w", "--apply"], env)
            check("F --workspace and --apply pass through, nothing else does",
                  argv == ["--workspace", "/w", "--apply"], str(argv))
            check("F --seat and --role are each NAMED as ignored",
                  any("--seat" in n for n in notes) and any("--role" in n for n in notes), str(notes))
            env = {}
            argv, notes = wrapper.translate(["--home", str(hestia_home)], env)
            check("F --home supplies HESTIA_HOME to the seeder (the operator doing the launcher's job)",
                  env.get("HESTIA_HOME") == str(hestia_home) and argv == [], f"{env} {argv}")
            argv, notes = wrapper.translate(["--apply"], {})
            check("F no locator anywhere -> refuses; no default is filled in",
                  argv is None and any("HESTIA_HOME" in n for n in notes), f"{argv} {notes}")

            rc = wrapper.main(["--seat", "codex", "--apply"])
            check("F main() calls the seeder exactly once with the translated argv",
                  rc == 0 and called == [["--apply"]], f"{rc} {called}")
            os.environ.pop("HESTIA_HOME")
            rc = wrapper.main(["--apply"])
            check("F main() without a locator returns 2 and never reaches the seeder",
                  rc == 2 and called == [["--apply"]], f"{rc} {called}")
        finally:
            seeder.main = real_main

        print("G. nothing in the repo directs an operator to the sequential path")
        repo = HERE.parent
        offenders = []
        for path in list(repo.glob("docs/**/*.md")) + list(repo.glob("tools/*.py")) + [repo / "README.md"]:
            if not path.is_file() or path.name == Path(__file__).name:
                continue
            text = path.read_text(errors="replace")
            if 'PUT", "/api/config/seat"' in text or "PUT /api/config/seat" in text:
                offenders.append(str(path.relative_to(repo)))
        check("G no tool or doc issues or prescribes PUT /api/config/seat", not offenders, str(offenders))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
