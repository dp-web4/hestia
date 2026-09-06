#!/usr/bin/env python3
"""A member must be able to see the petitions IT has open.

WHY. `hestia_member_unanswered` answers "what have you not replied to" and is
folded into every primer. The mirror question — "what have you ASKED that is
still open" — had no surface at all. That matters because the member is the only
party that can retire a MOOT petition, and because it is rarely the author:
measured on CBP 2026-08-19, 30 of 30 recorded lapses were auto-minted by the gate
on a refused write, and `gate_escalation_withdrawn` had fired twice in the mesh's
lifetime. The escalation id is printed once, into a refusal, in a wake that has
usually ended before the TTL runs out, so the member could not name its own open
petitions even in principle.

  A. FOLD (behavioural, against the real helper, through the same
     stdin-pipe the watcher uses).
  B. RENDER (behavioural).
  C. ADOPTION (static, derived from the scripts — the property-B discipline of
     last_words_test.py, because a producer with no call site is dead code that
     reads as covered).

The arms that matter are the NEGATIVE ones. A filter that drops everything
passes any test that only asserts "the peer's row is absent", so A2 asserts both
sides of the same input; and an absent fold that renders as silence is
indistinguishable from "you hold none", so B1 pins that it does not.

Usage: ./open_petitions_test.py      (runtime ~1s)
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.dirname(HERE)
HELPER = os.path.join(MESH, "open-petitions.py")

# Every other arm drives the helper as a SUBPROCESS, which is right: that is how
# the watcher runs it. But one property — "the tool is prescribed only when it
# resolves" — has two arms and the box can only ever be in one of them, so the
# absent/present arm has to be injected. Loading by path because the filename
# carries a hyphen and is not importable by name.
import importlib.util
_spec = importlib.util.spec_from_file_location("open_petitions_helper", HELPER)
op = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(op)

failures = []


def check(label, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  <- {detail}"))
    if not ok:
        failures.append(label)


def fold(payload, who):
    r = subprocess.run([sys.executable, HELPER, "fold", who],
                       input=json.dumps(payload), capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_stdout": r.stdout, "_stderr": r.stderr}


def render(fold_obj, tmp):
    p = os.path.join(tmp, "primer.json")
    with open(p, "w") as fh:
        json.dump({"notices": [], "open_petitions": fold_obj}, fh)
    r = subprocess.run([sys.executable, HELPER, "render", p],
                       capture_output=True, text=True)
    return r.stdout


def row(who, esc, **kw):
    # Shaped on what the RUNNING daemon returned on 2026-08-19, not on what the
    # chain's `gate_escalation_opened` event carries — the two differ, and the
    # difference is exactly the field a fixture is most tempted to invent.
    # `bar` is ABSENT here because the live payload omits it; B7 pins that.
    d = {
        "asked_by": who,
        "escalation_id": esc,
        "marker": "hestia/hooks",
        "tool_name": "Bash",
        "opened_at": 1787135723,
        "secs_remaining": 1800,
        "stated_reason": "Bash: cat > forum/note.md <<'MD' ...",
        "stated_detail": ("Auto-opened by the gate on a refused write; the member "
                          "stated no rationale because it did not choose to escalate."),
        "peer_participation": {"invited": [], "concurred": 0, "dissented": 0,
                               "absent": 0, "invited_without_reader": 0},
    }
    d.update(kw)
    return d


print("A. fold — which rows are this member's")

# A1: the happy path, so the positive control exists before anything is asserted
# absent.
f = fold({"count": 1, "pending": [row("claude-code", "aaa1")]}, "claude-code")
check("A1 own row kept", [r["escalation_id"] for r in f["mine"]] == ["aaa1"], json.dumps(f))
check("A1 `asked` true when the list came back", f.get("asked") is True, json.dumps(f))

# A2: THE ARM THAT DISCRIMINATES. A filter that returns [] unconditionally passes
# "the peer's row is absent". Both sides are asserted against ONE input whose two
# rows differ only in `asked_by`, so a broken filter fails in whichever direction
# it is broken.
f = fold({"pending": [row("claude-code", "mine1"), row("kimi-code", "theirs1")]},
         "claude-code")
ids = [r["escalation_id"] for r in f["mine"]]
check("A2 peer's row excluded", "theirs1" not in ids, str(ids))
check("A2 own row still present in the same call (not an empty-filter pass)",
      ids == ["mine1"], str(ids))

# A2b: the same input read AS the peer must return the mirror image — otherwise
# the filter could be keyed on something incidental to this fixture.
f = fold({"pending": [row("claude-code", "mine1"), row("kimi-code", "theirs1")]},
         "kimi-code")
check("A2b filter follows the argument, not the fixture",
      [r["escalation_id"] for r in f["mine"]] == ["theirs1"], json.dumps(f))

# A3: a failed RPC is NOT an empty holding. `asked` is the only thing that
# separates them, and nothing downstream can recover it if the fold drops it.
for bad in ({}, {"_hestia_error": {"code": "hestia.internal_error"}}, {"pending": None}):
    f = fold(bad, "claude-code")
    check(f"A3 no list -> asked:false ({json.dumps(bad)[:40]})",
          f.get("asked") is False and f.get("mine") == [], json.dumps(f))

# A4: garbage on stdin must not crash the watcher's pipeline — the fold is
# built inside the primer write, and an exception there costs the whole work list.
r = subprocess.run([sys.executable, HELPER, "fold", "claude-code"],
                   input="not json at all", capture_output=True, text=True)
check("A4 unparseable stdin exits 0 with asked:false",
      r.returncode == 0 and json.loads(r.stdout).get("asked") is False,
      f"rc={r.returncode} out={r.stdout!r}")

# A5: the row is TRIMMED — `asked_by` is redundant once filtered, and carrying
# unbounded daemon fields into a file the fire template reads is how a digest
# stops being a digest.
f = fold({"pending": [row("claude-code", "aaa1", extra_field="x" * 100)]}, "claude-code")
check("A5 unknown daemon fields dropped", "extra_field" not in f["mine"][0], json.dumps(f))
check("A5 the fields the renderer needs survive",
      {"escalation_id", "secs_remaining", "stated_detail"} <= set(f["mine"][0]),
      json.dumps(f))
# A6: `bar` is carried WHEN PRESENT. It is not in the live payload today, so the
# fold must neither require it (A5) nor drop it if the daemon starts sending it.
f = fold({"pending": [row("claude-code", "aaa1", bar="sovereign_plus_peer")]}, "claude-code")
check("A6 bar carried through when the daemon does send it",
      f["mine"][0].get("bar") == "sovereign_plus_peer", json.dumps(f))


print()
print("B. render — what the wake is told")

import tempfile
with tempfile.TemporaryDirectory() as tmp:
    # B1: NOT-MEASURED is the arm this whole helper exists for. If a failed read
    # renders as silence, the member reads "no open petitions" off an absence —
    # the exact inference every other fold in this directory was built to stop.
    out = render({"asked": False, "mine": []}, tmp)
    check("B1 unmeasured fold says so", "NOT MEASURED" in out, repr(out))
    check("B1 and refuses the inference explicitly",
          "not evidence that you hold none" in out, repr(out))
    check("B1 a failed READ is attributed to the read",
          "read failed" in out and "WATCHER predates" not in out, repr(out))

    # B1b: the OTHER cause of asked:false, and the reason it needed separating.
    # A watcher too old to fold writes no `open_petitions` key at all, and until
    # 2026-08-26 that rendered as "the pending-escalations read failed" — a flat
    # assertion about a read nobody attempted. Measured that day: the claude and
    # kimi watchers were running a8dccda (2026-08-06), which has no fold, so both
    # seats read a false cause every wake. The two want opposite responses (chase
    # the daemon vs restart the watcher), so the renderer must not merge them.
    p = os.path.join(tmp, "primer-no-key.json")
    with open(p, "w") as fh:
        json.dump({"notices": []}, fh)          # NO open_petitions key
    out_absent = subprocess.run([sys.executable, HELPER, "render", p],
                                capture_output=True, text=True).stdout
    check("B1b key-absent still says NOT MEASURED", "NOT MEASURED" in out_absent,
          repr(out_absent))
    check("B1b key-absent is still separated from the failed read",
          "read failed" not in out_absent, repr(out_absent))
    check("B1b key-absent still refuses the inference",
          "not evidence that you hold none" in out_absent, repr(out_absent))

    # B1c: the FALSIFIER B1b did not have. Absence dates the primer's PRODUCER,
    # and that is not the same fact as the vintage of the watcher running now.
    # Codex gave two live counterexamples on PR #634 in which a fully current
    # watcher launches a keyless primer: a retained primer written before the
    # restart is retried after it, and the current watcher's own composition
    # fallback (`... || echo "$OUT" > "$PRIMER"`) emits a keyless primer when the
    # final step fails. So the first version of this branch — "your WATCHER
    # predates the fold ... restarting the watcher is what fixes this" — asserted
    # a cause and prescribed a remedy the artifact does not entail. That is the
    # same overclaim-from-absence the branch exists to stop, committed by the
    # branch itself, which is why the wording is pinned and not just spot-checked.
    check("B1c key-absent does NOT claim the RUNNING watcher predates the fold",
          "WATCHER predates" not in out_absent, repr(out_absent))
    check("B1c key-absent does NOT prescribe a restart as the entailed remedy",
          "estarting the watcher is what fixes" not in out_absent, repr(out_absent))
    check("B1c key-absent attributes the absence to the PRODUCER of this primer",
          "PRODUCER" in out_absent and "primer" in out_absent, repr(out_absent))
    check("B1c key-absent names BOTH admissible producers",
          "without the fold" in out_absent and "composition fallback" in out_absent,
          repr(out_absent))
    # B1c-referent: the old form of this check was
    #     check("... points at the tool that DOES discriminate them",
    #           "process_vintage.py units" in out_absent)
    # and it was green for a week on a box where that tool does not exist and
    # never has. `tools/process_vintage.py` is PR #634 — opened 2026-08-26,
    # still open — while the sentence naming it merged the same day (#642). An
    # existence pin over a CONSTANT certifies that the renderer can print a
    # string; it says nothing about whether the reader can run what it names.
    # So pin the RESOLUTION, and drive both arms explicitly: the local box can
    # only ever witness one of them, and a test that sees one arm pins the box
    # rather than the behaviour.
    check("B1c prescribes the tool ONLY when the tool resolves",
          "`%s units` is what tells them apart." % op.VINTAGE_TOOL
          in op.vintage_hint(present=True), repr(op.vintage_hint(present=True)))
    check("B1c says so, and does not prescribe, when the tool is ABSENT",
          "is not on this box" in op.vintage_hint(present=False)
          and "units` is what tells them apart" not in op.vintage_hint(present=False),
          repr(op.vintage_hint(present=False)))
    check("B1c the rendered arm agrees with what is actually on THIS box",
          (("%s units" % op.VINTAGE_TOOL) in out_absent)
          == os.path.exists(os.path.join(op._REPO_ROOT, op.VINTAGE_TOOL)),
          repr(out_absent))

    # B1c2: having removed a prescription the reader cannot run, do not leave the
    # reader with nothing. The block names two producers; the primer's own KEY SET
    # settles one of them for free, and the renderer was throwing that evidence
    # away — `render` is handed the FOLD, and the fold is the thing that is
    # missing, so the envelope has to be passed down deliberately.
    #
    # The two questions are NOT the same and the block ran them together: the key
    # set dates the PRODUCER OF THIS ARTIFACT; `process_vintage.py` dates the
    # WATCHER RUNNING NOW. Codex's #634 counterexamples live exactly in that gap.
    composed = os.path.join(tmp, "primer-composed-old.json")
    with open(composed, "w") as fh:
        # The composer RAN — only it writes `unanswered`/`for_plugin` — and still
        # emitted no `open_petitions`. Nothing else can produce this shape.
        json.dump({"evicted": 0, "notices": [], "peeked": False, "total": 1,
                   "for_plugin": "claude-code",
                   "unanswered": {"i_owe": [], "owed_to_me": []}}, fh)
    out_composed = subprocess.run([sys.executable, HELPER, "render", composed],
                                  capture_output=True, text=True).stdout
    check("B1c2 a composed primer with no petitions fold DATES ITS PRODUCER",
          "composition SUCCEEDED" in out_composed
          and "predates the petitions fold" in out_composed, repr(out_composed))

    drain = os.path.join(tmp, "primer-raw-drain.json")
    with open(drain, "w") as fh:
        json.dump({"evicted": 0, "notices": [], "peeked": False, "total": 1}, fh)
    out_drain = subprocess.run([sys.executable, HELPER, "render", drain],
                               capture_output=True, text=True).stdout
    check("B1c2 the raw-drain shape is reported as raw drain",
          "raw drain response" in out_drain, repr(out_drain))
    # The honest half. Two producers write byte-identical raw drains — a current
    # watcher's composition fallback, and a watcher that never folded — and a
    # restart fixes only the second. Claiming either one here would be the same
    # overclaim-from-absence B1c exists to stop.
    check("B1c2 the raw-drain arm does NOT pick between its two producers",
          "does not separate those two" in out_drain
          and "composition SUCCEEDED" not in out_drain, repr(out_drain))
    check("B1c2 the two shapes get DIFFERENT verdicts",
          ("raw drain response" in out_drain)
          and ("raw drain response" not in out_composed), repr(out_composed))
    # An unreadable shape must produce no verdict at all. `{"notices": []}` (the
    # B1b fixture) is neither a full drain nor a composed primer.
    check("B1c2 an unrecognised shape yields NO producer claim",
          op.producer_from_keys(["notices"]) is None
          and op.producer_from_keys([]) is None
          and op.producer_from_keys(None) is None,
          repr(op.producer_from_keys(["notices"])))
    check("B1c2 the older 3-key drain (no `evicted`) is still a drain",
          op.producer_from_keys(["notices", "peeked", "total"]) is not None)

    # B1d: a diagnosis is not a remedy. Both not-measured arms named the CAUSE
    # and stopped, and the only action either ever named was a watcher restart —
    # which is the one action a woken member structurally cannot take, because
    # restarting its own watcher kills the wake that is reading the sentence.
    # The read is one RPC and the fold is in this file, so a member on ANY
    # watcher vintage can answer the question for itself. Both arms, not just
    # the key-absent one: a failed read is equally self-servable, and a remedy
    # wired into one arm fixes one cause rather than the class — the same
    # single-seat mistake arm C exists to stop, one level down.
    for label, block in (("key-absent", out_absent), ("failed-read", out)):
        check(f"B1d {label} names the RPC that answers it",
              "hestia_gate_pending_escalations" in block, repr(block))
        check(f"B1d {label} names the fold that filters it to this member",
              "open-petitions.py fold" in block, repr(block))
        check(f"B1d {label} says the route needs no restart",
              "without a restart" in block, repr(block))
        check(f"B1d {label} says what a MEASURED zero looks like",
              "asked:true" in block and "mine" in block, repr(block))
        # B1e: a mesh wake often has no `hestia_*` MCP surface at all, so the
        # member reaches for the CLI. `hestia gate pending` DEFAULTS to a
        # human-readable table; piping that to the fold returns `asked:false`,
        # which this file publishes as THE READ FAILED. The member is handed a
        # false "could not measure" immediately after measuring successfully —
        # the same shape as prescribing an absent tool, one route over.
        check(f"B1e {label} names the CLI route for a wake with no MCP surface",
              "hestia gate pending" in block, repr(block))
        check(f"B1e {label} says --json is load-bearing, not optional",
              "--json" in block and "TABLE" in block, repr(block))

    # B1e-referent: same discipline as B1c — do not let the advice name a flag
    # that does not exist. Pinned against the flag's DEFINITION rather than the
    # built binary, so this is checkable in a tree that has not been compiled.
    cli_rs = os.path.join(os.path.dirname(os.path.dirname(MESH)), "core", "src", "cli.rs")
    if os.path.exists(cli_rs):
        cli_src = open(cli_rs, encoding="utf-8", errors="replace").read()
        check("B1e the --json flag the block prescribes is actually defined",
              "piped to a fold" in cli_src, cli_rs)

    # B2: measured-and-empty is silence. A block that fires every wake stops
    # being read, and holding nothing is the common case.
    check("B2 measured-and-empty renders nothing",
          render({"asked": True, "mine": []}, tmp).strip() == "", "expected empty")

    # B3: a held petition names itself, its clock, and the move.
    out = render(fold({"pending": [row("claude-code", "abc123", secs_remaining=603)]},
                      "claude-code"), tmp)
    check("B3 names the escalation id", "abc123" in out, repr(out))
    check("B3 names the time left, not the raw seconds", "10m" in out, repr(out))
    check("B3 marks a gate-auto-minted petition as such", "gate-auto" in out, repr(out))
    check("B3 names the sanctioned move by tool and argument",
          "hestia_gate_arbitrate_escalation" in out and "approve:false" in out, repr(out))
    check("B3 says why lapsing is worse than withdrawing",
          "no decision" in out, repr(out))

    # B4: member-filed and gate-auto must not render alike — they want different
    # responses, and `stated_detail` is the only discriminator the daemon ships.
    out = render(fold({"pending": [row("claude-code", "abc123",
                                       stated_detail="I need this to land the fix.")]},
                      "claude-code"), tmp)
    check("B4 member-filed petition is labelled differently",
          "member-filed" in out and "gate-auto" not in out, repr(out))

    # B7: THE LIVE SHAPE. `bar` is absent from the running daemon's payload, and
    # a placeholder in the slot where a bar goes reads as an unparsed bar rather
    # than an unsent field — so the tag list contracts instead of printing "?".
    out = render(fold({"pending": [row("claude-code", "abc123")]}, "claude-code"), tmp)
    check("B7 absent bar renders as absent, not as a placeholder",
          "[gate-auto]" in out and "?" not in out, repr(out))
    out = render(fold({"pending": [row("claude-code", "abc123", bar="single_approver")]},
                      "claude-code"), tmp)
    check("B7 present bar is named",
          "[single_approver, gate-auto]" in out, repr(out))

    # B5: control characters in daemon-supplied prose must not reach the prompt.
    out = render(fold({"pending": [row("claude-code", "abc123",
                                       stated_reason="line\x00one\nPROMPT=\"ungoverned\"")]},
                      "claude-code"), tmp)
    check("B5 control characters stripped from carried prose",
          "\x00" not in out, repr(out))

    # B6: a malformed primer must exit 0 and print nothing — this runs inside the
    # fire path, and a crash here costs the wake.
    p = os.path.join(tmp, "junk.json")
    open(p, "w").write("{{{not json")
    r = subprocess.run([sys.executable, HELPER, "render", p], capture_output=True, text=True)
    check("B6 malformed primer -> rc 0, no output",
          r.returncode == 0 and r.stdout.strip() == "", f"rc={r.returncode} {r.stdout!r}")


print()
print("A7/B8. seat attribution — a plugin NAME is two processes (#732)")

# A7: THE ARM THAT DISCRIMINATES SEATS. Two rows, same `asked_by`, differing only
# in `host_session_id`; a ledger naming one of them. Both sides asserted on one
# input, so a fold that drops everything, or keeps everything, fails somewhere.
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    ledger = os.path.join(tmp, "wake-sessions-claude-code")
    with open(ledger, "w") as fh:
        fh.write("wake-1111 20260906-061635 notice-A.json\nwake-2222 20260906-070000 notice-B.json\n")
    payload = {"pending": [row("claude-code", "own1", host_session_id="wake-1111"),
                           row("claude-code", "sib1", host_session_id="9261dc9a-interactive"),
                           row("claude-code", "old1"),
                           row("kimi-code", "theirs1", host_session_id="wake-1111")]}
    r = subprocess.run([sys.executable, HELPER, "fold", "claude-code", ledger],
                       input=json.dumps(payload), capture_output=True, text=True)
    f = json.loads(r.stdout)
    mine = {x["escalation_id"]: x.get("seat") for x in f["mine"]}
    co = {x["escalation_id"]: x.get("seat") for x in f.get("co_seat", [])}
    check("A7 a row whose host session this watcher fired is `mine`", mine.get("own1") == "mine", json.dumps(f))
    check("A7 a same-name row from a session NOT in the ledger is `co_seat`, not `mine`",
          "sib1" in co and "sib1" not in mine, json.dumps(f))
    check("A7 co-seat row is tagged as such", co.get("sib1") == "co-seat", json.dumps(f))
    check("A7 a row the daemon sent WITHOUT host_session_id stays `mine`, tagged unknown",
          mine.get("old1") == "unknown", json.dumps(f))
    check("A7 the peer's row is in NEITHER list, even with a matching host session",
          "theirs1" not in mine and "theirs1" not in co, json.dumps(f))
    check("A7 host_session_id survives the trim (the renderer names it)",
          any(x.get("host_session_id") == "9261dc9a-interactive" for x in f["co_seat"]), json.dumps(f))
    # A7b: NO ledger -> the OLD reading, tagged unknown, never "none are yours".
    r = subprocess.run([sys.executable, HELPER, "fold", "claude-code"],
                       input=json.dumps(payload), capture_output=True, text=True)
    f2 = json.loads(r.stdout)
    check("A7b without a ledger every same-name row is `mine` (degrades to the old fold)",
          sorted(x["escalation_id"] for x in f2["mine"]) == ["old1", "own1", "sib1"], json.dumps(f2))
    check("A7b and each is tagged unknown, not asserted as owned",
          all(x.get("seat") == "unknown" for x in f2["mine"]), json.dumps(f2))
    check("A7b co_seat is an empty LIST (a measured none), not absent", f2.get("co_seat") == [], json.dumps(f2))
    # A7c: an unreadable ledger path is the same as no ledger.
    r = subprocess.run([sys.executable, HELPER, "fold", "claude-code", os.path.join(tmp, "nope")],
                       input=json.dumps(payload), capture_output=True, text=True)
    f3 = json.loads(r.stdout)
    check("A7c a missing ledger file degrades like no ledger (rc 0, all `mine`, unknown)",
          r.returncode == 0 and len(f3["mine"]) == 3 and f3["co_seat"] == [], json.dumps(f3))

    # B8: the render. A co-seat row must be VISIBLE (the wake may be about to
    # touch the same path) and must NOT carry the WITHDRAW prescription.
    co_only = {"asked": True, "mine": [], "co_seat": [dict(row("claude-code", "sib1",
               host_session_id="9261dc9a-1703-4964"), seat="co-seat")]}
    out = render(co_only, tmp)
    check("B8 co-seat-only fold renders (not the measured-empty silence)", "sib1" in out, repr(out))
    check("B8 co-seat block says NOT yours", "NOT yours" in out, repr(out))
    check("B8 co-seat block names the host session prefix", "9261dc9a" in out, repr(out))
    check("B8 co-seat block does NOT prescribe WITHDRAW", "WITHDRAW" not in out, repr(out))
    check("B8 co-seat block does NOT say `Petitions YOU have open`", "Petitions YOU have open" not in out, repr(out))
    mixed = {"asked": True,
             "mine": [dict(row("claude-code", "own1", host_session_id="wake-1111"), seat="mine")],
             "co_seat": co_only["co_seat"]}
    out = render(mixed, tmp)
    i_mine, i_with, i_co = out.find("own1"), out.find("WITHDRAW"), out.find("NOT yours")
    check("B8 mixed fold renders both rows", "own1" in out and "sib1" in out, repr(out))
    check("B8 mixed: WITHDRAW sits between the own row and the co-seat block, binding only the first",
          -1 < i_mine < i_with < i_co, f"mine={i_mine} withdraw={i_with} co={i_co}")
    check("B8 an owned row with a known seat carries no UNKNOWN caveat",
          "seat: UNKNOWN" not in out.split("NOT yours")[0], repr(out))
    unk = {"asked": True, "mine": [dict(row("claude-code", "old1"), seat="unknown")], "co_seat": []}
    out = render(unk, tmp)
    check("B8 an unknown-seat row says the match was on NAME only", "seat: UNKNOWN" in out and "plugin name only" in out, repr(out))
    check("B8 and points at the chain field that discriminates", "host_session_id" in out, repr(out))
    legacy = {"asked": True, "mine": [row("claude-code", "abc123")]}   # pre-#732 fold, no seat/co_seat keys
    out = render(legacy, tmp)
    check("B8 a legacy fold (no seat, no co_seat) still renders the own row", "abc123" in out, repr(out))

print()
print("C. adoption — the call sites exist")

watch = open(os.path.join(MESH, "hestia-watch-member.sh")).read()
check("C1 watcher asks the daemon for pending escalations",
      "hestia_gate_pending_escalations" in watch, "no RPC")
check("C2 watcher pipes the response through the shared fold",
      re.search(r'open-petitions\.py"\s+fold\s+"\$PLUGIN"', watch) is not None, "no fold call")
check("C3 watcher writes the fold into the primer",
      '"open_petitions"' in watch or "open_petitions" in watch, "not written")
check("C4 a failed fold still yields a well-formed asked:false",
      '{"asked":false,"mine":[]}' in watch, "no fallback")
check("C5 WATCH_DIR derived from the source path the drift snapshot hashes",
      'WATCH_DIR="$(cd "$(dirname "$WATCH_SOURCE")" && pwd)"' in watch, "no WATCH_DIR")

templates = [f for f in os.listdir(MESH) if re.fullmatch(r"fire-[a-z0-9-]+\.sh", f)]
check("C6 at least the three known templates exist",
      {"fire-kimi.sh", "fire-claude.sh", "fire-codex.sh"} <= set(templates), str(templates))
for tpl in sorted(templates):
    src = open(os.path.join(MESH, tpl)).read()
    # EVERY template, not just claude's. A member that cannot see its own
    # petitions is not one seat's property, and a renderer wired into one
    # template fixes one seat rather than the class.
    check(f"C7 {tpl}: calls the renderer, time-bounded and failure-tolerated",
          '$(timeout 5 python3 "$HERE_DIR/open-petitions.py" render "$PRIMER" 2>/dev/null || true)'
          in src, tpl)
    check(f"C8 {tpl}: splices $PETITIONS_BLOCK into PROMPT",
          re.search(r'PROMPT="[^"]*\$PETITIONS_BLOCK', src, re.S) is not None
          or "$DIGEST$DEBT_BLOCK$PETITIONS_BLOCK$LAST_WORDS_BLOCK" in src, tpl)

# C9: the seat discriminator is WIRED, not just implemented. The watcher hands the
# fold its ledger; the claude fire chooses the session id, records it in that
# same ledger, and launches under it. One of the three missing and every wake
# reads `seat: unknown` forever, which is the pre-#732 behaviour with a label.
check("C9 watcher passes its wake-session ledger to the fold",
      re.search(r'fold\s+"\$PLUGIN"\s*\\\s*\n\s*"\$STATE/wake-sessions-\$PLUGIN"', watch) is not None,
      "fold not given the ledger")
fire_claude = open(os.path.join(MESH, "fire-claude.sh")).read()
check("C9 fire-claude chooses the wake's session id before launch",
      re.search(r'^WAKE_SID="\$\(uuidgen', fire_claude, re.M) is not None, "no WAKE_SID")
check("C9 fire-claude appends it to the ledger the watcher reads (same STATE root, same file name)",
      'wake-sessions-claude-code' in fire_claude and '>> "$WAKE_LEDGER"' in fire_claude, "no ledger append")
check("C9 fire-claude launches claude under that id",
      re.search(r'claude -p [^\n]*--session-id "\$WAKE_SID"', fire_claude) is not None, "no --session-id")
check("C9 the ledger is written BEFORE the launch line, so a killed wake is still attributable",
      fire_claude.find('>> "$WAKE_LEDGER"') < fire_claude.find('--session-id "$WAKE_SID"'), "order")

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
