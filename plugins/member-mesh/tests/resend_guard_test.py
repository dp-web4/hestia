#!/usr/bin/env python3
"""A louder success line does not stop a duplicate send. The write has to refuse.

WHAT HAPPENED, TWICE, SAME SEAT, 23 DAYS APART.

  2026-08-03, notices 743/744 (claude-code -> kimi-code). The same pointer queued twice,
  5.6s apart. The first send SUCCEEDED; the caller read it through `| tail -5` and saw
  the tail of `recipient_liveness_evidence` and a closing brace — nothing that said it
  worked. #135 fixed that by adding confirm(): one loud stderr line naming `queued_id`,
  flushed last so it survives `2>&1 | tail -N`. That docstring is still in the file.

  2026-08-26, eight notices (claude-code -> codex, kimi-code, hestia). A script sent all
  eight, rc=0 on every one, confirm() printing correctly. The caller piped the RUN
  through `tail -40`, lost its own per-send summary lines, and RE-RAN THE SCRIPT TO SEE
  THEM. Every peer received the notice twice, each bound to the same `in_reply_to`.

The second occurrence is not a regression of the first fix — it is proof the fix was
aimed one layer off. confirm() answers "did it work?"; the re-run was never asking that.
The sender did not doubt delivery, it wanted the output, and re-running a send script is
how you get output from a surface with no dry-run and no read-back. A report cannot
defend against a caller who is not reading it as a report.

So the guard belongs on the WRITE. `already_sent()` keeps a local jsonl ledger keyed on
the whole tuple (plugin, to, kind, pointer_uri, in_reply_to) and refuses a byte-identical
repeat inside HESTIA_MESH_RESEND_WINDOW (default 900s) with rc=5, NOTHING SENT.

WHAT IT DELIBERATELY DOES NOT DO. It is not an idempotency key on the daemon — that is
the correct fix and needs a protocol field `hestia_member_notify` does not have. It is
not a rate limit: a genuine second disposition on the same pointer, or the same pointer
bound to a different notice, differs in the tuple and passes. And it is not load-bearing:
every failure path fails OPEN, because a guard that blocks the mesh on its own corrupt
state is worse than the duplicate it prevents.

Seven properties, against the real module and a real filesystem — no seam, no mocks:

  1. A byte-identical repeat inside the window is REFUSED, and a first send is not.
  2. Each field of the tuple is load-bearing: change any ONE of to/kind/pointer/
     in_reply_to and the send is permitted. (Red if the guard keys on the pointer alone,
     which would eat the fan-out case: five debts sharing one file, five distinct
     anchors.)
  3. The window is real: the same tuple outside it is permitted again.
  4. HESTIA_MESH_RESEND=1 forces through, and RESEND_WINDOW=0 disables the guard
     entirely — an operator who wants the duplicate can always have it.
  5. FAIL-OPEN, on EVERY path, not just the remembered one: a corrupt ledger, a
     malformed HESTIA_MESH_RESEND_WINDOW, a matching row with an undateable `at`, and a
     row that is valid JSON but not an object all permit the send and say so on stderr.
     The last three raised past the fail-open try and exited rc=1 before notify until
     codex's review of PR #649 — the contract only covered the read someone thought
     of. The fallback is the DEFAULT window, not a disabled guard (5e): failing open
     means "do not block a send", not "stop noticing duplicates". Also: the recorded row
     carries `queued_id`, so the refusal message can name the notice the caller has.
  6. The ledger lives under `HESTIA_MESH_STATE` and is named for the sending seat — a
     test run must never be able to append to the operator's real ledger.
  7. The mesh ENDPOINT is part of the identity: one ledger per seat spans every daemon
     that seat talks to, so without it the first send to a second mesh reads as a repeat.

Plus one doc pin: rc=5 must appear in the module's exit-code table. A guard whose exit
code is undocumented is a new silent failure for every caller that branches on rc.
"""
import importlib.util
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "hestia-mesh.py")

failures = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name)
    if not ok:
        if detail:
            print("       " + detail.replace("\n", "\n       ")[:900])
        failures.append(name)


def load(state_dir, plugin="claude-code", endpoint=None):
    os.environ["HESTIA_MESH_PLUGIN"] = plugin
    os.environ["HESTIA_MESH_STATE"] = state_dir
    os.environ.pop("HESTIA_MESH_RESEND", None)
    os.environ.pop("HESTIA_MESH_RESEND_WINDOW", None)
    # EP is read at import time, so a second endpoint means a second module object.
    if endpoint is None:
        os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        os.environ["HESTIA_ENDPOINT"] = endpoint
    spec = importlib.util.spec_from_file_location("hestia_mesh_under_test", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def notice(to="codex", kind="reply", pointer="hestia://escalation/abc#x", re_id=6147):
    return {"to_plugin_id": to, "kind": kind, "pointer_uri": pointer,
            "in_reply_to": re_id, "session_id": "sess"}


def main():
    tmp = tempfile.mkdtemp(prefix="resend-guard-")
    m = load(tmp)

    # ---- 1. THE MEASURED CASE: send, then send the identical thing again.
    a = notice()
    check("1a. a first send is permitted (no ledger yet)", m.already_sent(a) is None)
    m.record_sent(a, {"queued_id": 6153})
    dup = m.already_sent(a)
    check("1b. a byte-identical repeat inside the window is REFUSED",
          dup is not None, f"already_sent returned {dup!r}")
    check("1c. the refusal names the notice the caller already has",
          (dup or {}).get("queued_id") == 6153, f"row={json.dumps(dup)[:300]}")

    # ---- 2. EVERY FIELD OF THE TUPLE IS LOAD-BEARING.
    # The fan-out case is why: five debts sharing one forum file had five DISTINCT
    # anchors and were five claims, not duplicates. A pointer-only key would eat four.
    for label, other in (
            ("a different recipient", notice(to="kimi-code")),
            ("a different kind", notice(kind="ack")),
            ("a different pointer (same thread, different anchor)",
             notice(pointer="hestia://escalation/abc#y")),
            ("the same pointer bound to a DIFFERENT notice", notice(re_id=6152)),
    ):
        check(f"2. {label} is permitted", m.already_sent(other) is None,
              f"wrongly refused: {json.dumps(m.already_sent(other))[:300]}")

    # ---- 3. THE WINDOW IS REAL.
    check("3a. inside a 900s window the repeat is refused",
          m.already_sent(a, now=time.time() + 899) is not None)
    check("3b. outside it the same tuple is permitted again",
          m.already_sent(a, now=time.time() + 901) is None)

    # ---- 4. THE OPERATOR CAN ALWAYS HAVE THE DUPLICATE.
    os.environ["HESTIA_MESH_RESEND"] = "1"
    check("4a. HESTIA_MESH_RESEND=1 forces through", m.already_sent(a) is None)
    os.environ.pop("HESTIA_MESH_RESEND")
    os.environ["HESTIA_MESH_RESEND_WINDOW"] = "0"
    check("4b. HESTIA_MESH_RESEND_WINDOW=0 disables the guard", m.already_sent(a) is None)
    os.environ.pop("HESTIA_MESH_RESEND_WINDOW")

    # ---- 5. FAIL-OPEN. A guard that blocks the mesh on its own broken state is worse
    # than the duplicate it prevents — same contract as keep_a_copy().
    with open(m.resend_ledger_path(), "w", encoding="utf-8") as f:
        f.write("{not json at all\n")
    check("5a. a corrupt ledger PERMITS the send (fail-open)",
          m.already_sent(a) is None)

    # 5b-5d are codex's dissent on PR #649, reproduced. The docstring said "any error
    # reading the ledger warns and permits", but three reads sat OUTSIDE the try that
    # made that true, and each one exits rc=1 BEFORE notify. A fail-open contract that
    # only covers the paths someone remembered is not a contract; these pin the escapes.
    # Note what a passing 5a could not tell us: it exercises the ONE path inside the
    # guard. The defect lived in the arithmetic on either side of it.
    def permits_without_raising(label, prepare, env=None):
        prepare()
        if env is not None:
            os.environ["HESTIA_MESH_RESEND_WINDOW"] = env
        try:
            got = m.already_sent(a)
            check(label, got is None, f"refused instead: {json.dumps(got)[:200]}")
        except Exception as e:
            check(label, False, f"raised {type(e).__name__}: {e} (rc=1, nothing sent)")
        finally:
            os.environ.pop("HESTIA_MESH_RESEND_WINDOW", None)

    def write_rows(*lines):
        def go():
            with open(m.resend_ledger_path(), "w", encoding="utf-8") as fh:
                fh.write("".join(l + "\n" for l in lines))
        return go

    permits_without_raising(
        "5b. a malformed HESTIA_MESH_RESEND_WINDOW does not block the send",
        write_rows(), env="invalid")
    permits_without_raising(
        "5c. a matching row with an undateable `at` permits (warn, not raise)",
        write_rows(json.dumps({"key": m.resend_key(a), "at": "not-a-time"})))
    permits_without_raising(
        "5d. a row that is valid JSON but not an object permits (warn, not raise)",
        write_rows("42", '"a string row"'))

    # ...and the fallback is the DEFAULT window, not a disabled guard: a typo in the
    # env var must not silently turn the duplicate refusal off.
    write_rows()()
    m.record_sent(a, {"queued_id": 6153})
    os.environ["HESTIA_MESH_RESEND_WINDOW"] = "invalid"
    check("5e. the malformed-window fallback still REFUSES a real duplicate",
          m.already_sent(a) is not None,
          "a bad env value silently disabled the guard")
    check("5f. and the fallback window is the documented 900s default",
          m.resend_window() == 900.0, repr(m.resend_window()))
    os.environ.pop("HESTIA_MESH_RESEND_WINDOW")

    # 5g: the reader treated window<=0 as OFF but the writer string-compared to "0", so
    # "0.0" and "-1" grew a ledger nobody consults. One predicate, both sides.
    os.environ["HESTIA_MESH_RESEND_WINDOW"] = "0.0"
    before = open(m.resend_ledger_path(), encoding="utf-8").read()
    m.record_sent(notice(to="nobody"), {"queued_id": 1})
    check("5g. a disabled guard does not keep writing rows ('0.0', not just '0')",
          open(m.resend_ledger_path(), encoding="utf-8").read() == before)
    os.environ.pop("HESTIA_MESH_RESEND_WINDOW")

    # ---- 6. THE LEDGER LIVES UNDER HESTIA_MESH_STATE, AND NOWHERE ELSE.
    # CI found this the expensive way: mesh_send_confirm_line_test.py never set the
    # state dir, so a test run would have appended to the OPERATOR'S REAL ledger. A
    # test that mutates live member state is a worse bug than the duplicate the guard
    # prevents, and nothing in the suite would have said so. Pinned here so the next
    # person who moves the path has to move this line too.
    check("6a. the ledger path is inside HESTIA_MESH_STATE",
          os.path.abspath(m.resend_ledger_path()).startswith(os.path.abspath(tmp)),
          f"ledger at {m.resend_ledger_path()} but state dir is {tmp}")
    check("6b. the ledger is named for the sending seat, not shared across seats",
          os.path.basename(m.resend_ledger_path()) == "claude-code.jsonl",
          m.resend_ledger_path())

    # ---- 8. THE ENDPOINT IS PART OF THE IDENTITY (codex's tuple follow-up on #649).
    # HESTIA_ENDPOINT is configurable and the ledger is one file per seat, so the same
    # semantic notice aimed at a SECOND mesh looked like a repeat of the first and was
    # refused. That is the fan-out failure again, one axis over.
    tmp8 = tempfile.mkdtemp(prefix="resend-endpoint-")
    m1 = load(tmp8, endpoint="http://127.0.0.1:7711/mcp")
    b = notice()
    m1.record_sent(b, {"queued_id": 9001})
    check("8a. the same endpoint still refuses the repeat", m1.already_sent(b) is not None)
    m2 = load(tmp8, endpoint="http://127.0.0.1:7799/mcp")
    check("8b. the same tuple to a DIFFERENT endpoint is permitted",
          m2.already_sent(b) is None,
          f"wrongly refused: {json.dumps(m2.already_sent(b))[:200]}")
    m3 = load(tmp8, endpoint="http://127.0.0.1:7711/mcp/")
    check("8c. a trailing slash is the same endpoint, not a second one",
          m3.already_sent(b) is not None,
          "normalization did not collapse a trailing slash")
    load(tmp, endpoint=None)  # restore the module under test for the doc pin below

    # ---- doc pin: the exit code has to be findable by a caller that branches on rc.
    doc = open(CLI, encoding="utf-8").read()
    check("7a. rc=5 is documented in the module's exit-code table",
          "| 5 " in doc and "REFUSED LOCALLY" in doc,
          "exit-code table does not mention 5 / REFUSED LOCALLY")
    check("7b. the override is documented where the rc is",
          "HESTIA_MESH_RESEND=1" in doc)

    print()
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(failures))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
