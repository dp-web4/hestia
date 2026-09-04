#!/usr/bin/env python3
"""The primer's debt fold must survive a large payload, and must never manufacture a zero.

WHY. Two defects, one block.

1. THE CARRIER. The composer exported the whole `hestia_member_unanswered` result as a
   single environment string. `execve` caps ONE string at MAX_ARG_STRLEN = 32 pages =
   131,072 B. Measured on CBP 2026-09-04 the live fold for `claude-code` was 442,074 B --
   3.37x -- so the interpreter never started, `|| echo "$OUT" > "$PRIMER"` wrote the raw
   drain response, and `unanswered`, `open_petitions` AND `for_plugin` were all lost. The
   size is per-seat and not monotone (codex's own fold shipped at 118,995 B the same day),
   so this cannot be pinned by a date or a floor -- only by driving a payload over the cap.

2. THE VERDICT. Every failure of that read became `{"i_owe": [], "owed_to_me": []}`, which
   a reader cannot distinguish from "you owe nobody". A channel error was rendered as a
   positive all-clear. That is the same absence-as-verdict class the carrier fix is about,
   so a carrier fix alone would have re-created it one layer down: `mktemp` failing, or a
   half-written file, still yields empty lists.

   It ran 15 days undetected for a reason worth pinning separately: the RENDERER was silent.
   `.get("unanswered") or {}` gave an absent key, an empty fold and a real zero the same
   output -- nothing. The sibling `open_petitions` gap was caught the same day because its
   renderer prints `asked:false` in words. So the third state is only a repair if it is
   audible, and arms C cover the renderer, not just the composer.

  A. CARRIER (behavioural, against the REAL shell hunk extracted from the watcher --
     including its own `mktemp`, its own redirect and its own inline interpreter. An
     earlier version of this test drove a python reimplementation and was correctly
     rejected in review for bypassing the shell carrier, which is the part that broke).
  B. TRI-STATE (behavioural, same hunk, with the carrier sabotaged four ways).
  C. RENDERER (behavioural, against the REAL heredoc extracted from each fire script).

The arms that matter are the negative ones. A composer that always wrote `asked:false`
would pass every "failure is not a zero" arm, so A3 pins that a real empty fold is
reported as a MEASURED zero; and a renderer that printed the warning unconditionally
would pass every C arm, so C5 pins that a populated fold does not claim to be unmeasured.

Usage: ./primer_fold_carrier_test.py      (runtime ~3s)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.dirname(HERE)
WATCHER = os.path.join(MESH, "hestia-watch-member.sh")

failures = []


def check(label, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  <- {detail}"))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------- the real hunk
# Extracted by text from the watcher, not retyped here. If the composer is edited the
# extraction either still covers it or fails loudly; a copy in this file would silently
# go on testing code that no longer ships.
SRC = open(WATCHER, encoding="utf-8").read()

# A0 is checked against the WHOLE watcher, before extraction, on purpose. Reverting the
# carrier also destroys the extraction anchors, and an extraction failure alone would
# report "the anchors moved" -- true, but it would not name what actually regressed.
check("A0 the composer does not pass the fold through the environment",
      'UN="$UN" PET=' not in SRC,
      "an env carrier is capped at MAX_ARG_STRLEN and this fold exceeds it")

_m = re.search(
    r'\n(    UN_FILE=\$\(mktemp.*?\n    \[ -n "\$UN_FILE" \] && rm -f "\$UN_FILE"\n)',
    SRC, re.DOTALL)
check("hunk extracted from the shipping watcher", _m is not None,
      'anchors are `UN_FILE=$(mktemp` .. `rm -f "$UN_FILE"`')
if not _m:
    print("\nFAILED: cannot drive the composer without the hunk; A and B arms did not run.")
    sys.exit(1)
HUNK = _m.group(1)


def compose(unanswered_body, plugin="claude-code", mktemp_fails=False, drain=None):
    """Run the REAL composer hunk with `unanswered` stubbed. Returns the parsed primer."""
    drain = drain or {"total": 1, "notices": [{"id": 1, "kind": "reply",
                                               "from_plugin": "codex",
                                               "pointer_uri": "hestia://x"}]}
    with tempfile.TemporaryDirectory() as td:
        body = os.path.join(td, "body")
        open(body, "w", encoding="utf-8").write(unanswered_body)
        primer = os.path.join(td, "primer.json")
        # `unanswered` and `open_petitions` are the two reads the hunk makes; both are
        # stubbed so the test needs no daemon. Everything between them is the real code.
        harness = f"""
set -u
PLUGIN={plugin!r}
PRIMER={primer!r}
WATCH_DIR={MESH!r}
OUT={json.dumps(json.dumps(drain, separators=(',', ':')))}
unanswered() {{ cat {body!r}; }}
open_petitions() {{ echo '{{}}'; }}
{'mktemp() { return 1; }' if mktemp_fails else ''}
{HUNK}
"""
        r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
        try:
            return json.load(open(primer, encoding="utf-8")), r
        except Exception as e:
            return {"__unparseable__": str(e), "__raw__": open(primer, encoding="utf-8").read()[:200]}, r


def rows(n, tag="i_owe"):
    return [{"id": 1000 + i, "kind": "reply", "from_plugin": "codex",
             "to_plugin": "claude-code", "queued_at": "2026-09-04T10:00:00Z",
             "pointer_uri": "hestia://escalation/" + ("%064x" % i)} for i in range(n)]


print("\nA. CARRIER -- the fold reaches the primer regardless of size")

fold = {"i_owe": rows(3), "owed_to_me": []}
d, r = compose(json.dumps(fold))
check("A1 a small fold composes", d.get("unanswered", {}).get("asked") is True, json.dumps(d)[:200])
check("A1b its rows survive intact",
      [x["id"] for x in d.get("unanswered", {}).get("i_owe", [])] == [1000, 1001, 1002])
check("A1c `for_plugin` is stamped", d.get("for_plugin") == "claude-code")
check("A1d `open_petitions` is present", "open_petitions" in d)

# The regression that matters. 2,000 rows is ~400 KB compact -- the size measured live on
# this seat -- and comfortably over the 131,072 B cap the environment carrier ran into.
big = {"i_owe": rows(2000), "owed_to_me": rows(800, "owed_to_me")}
big_bytes = len(json.dumps(big, separators=(",", ":")))
CAP = 32 * 4096
check(f"A2 the test payload actually exceeds the cap ({big_bytes:,} B > {CAP:,} B)",
      big_bytes > CAP, "otherwise this arm proves nothing")

# Sabotage control: the SAME payload through a single environment string, which is what
# the composer used to do. If this does not fail, the cap moved and A2b is not load-bearing.
env_failed = False
try:
    pid = os.fork()
    if pid == 0:
        try:
            os.execve("/bin/true", ["/bin/true"], {"UN": json.dumps(big, separators=(",", ":"))})
        except OSError:
            os._exit(7)
        os._exit(0)
    env_failed = os.waitpid(pid, 0)[1] >> 8 == 7
except Exception as e:
    check("A2a sabotage control could not run", False, str(e))
check("A2a control: the same payload through ONE env string still fails E2BIG",
      env_failed, "if this passes, MAX_ARG_STRLEN changed and A2b proves nothing")

d, r = compose(json.dumps(big))
check("A2b the shipping carrier composes it anyway",
      d.get("unanswered", {}).get("asked") is True, json.dumps(d)[:200])
check("A2c all 2,800 rows survive",
      len(d.get("unanswered", {}).get("i_owe", [])) == 2000
      and len(d.get("unanswered", {}).get("owed_to_me", [])) == 800)
check("A2d `for_plugin` survives the large fold too", d.get("for_plugin") == "claude-code",
      "this is the key whose loss made 319 primers unattributable")

# The arm that stops `asked:false` from being a free pass.
d, r = compose(json.dumps({"i_owe": [], "owed_to_me": []}))
u = d.get("unanswered", {})
check("A3 a genuinely empty fold is a MEASURED zero, not a refusal",
      u.get("asked") is True and u.get("i_owe") == [] and u.get("owed_to_me") == [],
      json.dumps(d)[:200])


print("\nB. TRI-STATE -- no carrier failure may be read as `you owe nobody`")

for label, body, kw in [
    ("B1 mktemp fails", json.dumps(fold), {"mktemp_fails": True}),
    ("B2 the fold file is empty (write failed before any byte)", "", {}),
    ("B3 the fold is truncated mid-write", '{"i_owe": [{"id": 1000, "kin', {}),
    ("B4 the read returned an error envelope, not a fold",
     '{"error": "daemon refused", "code": -32000}', {}),
    ("B5 `i_owe` is present but not a list", '{"i_owe": {}, "owed_to_me": []}', {}),
]:
    d, r = compose(body, **kw)
    u = d.get("unanswered")
    check(f"{label} -> asked:false",
          isinstance(u, dict) and u.get("asked") is False, json.dumps(d)[:200])
    check(f"{label} -> the other two keys still compose",
          d.get("for_plugin") == "claude-code" and "open_petitions" in d,
          "a carrier failure must not cost the keys that did not depend on it")


print("\nC. RENDERER -- the third state has to be audible")

# The real renderer, extracted from each fire script the same way.
def renderer_for(script):
    src = open(os.path.join(MESH, script), encoding="utf-8").read()
    m = re.search(r"DEBT=\$\(python3 - \"\$PRIMER\" <<'PY'\n(.*?)\nPY\n", src, re.DOTALL)
    return m.group(1) if m else None


def render(script, primer_obj, cap=None):
    code = renderer_for(script)
    env = dict(os.environ)
    if cap is not None:
        env["HESTIA_DEBT_ROWS_SHOWN"] = str(cap)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "primer.json")
        json.dump(primer_obj, open(p, "w", encoding="utf-8"))
        r = subprocess.run([sys.executable, "-", p], input=code,
                           capture_output=True, text=True, env=env)
        return r.stdout


BASE = {"total": 1, "notices": [], "for_plugin": "claude-code"}
for script in ("fire-claude.sh", "fire-codex.sh", "fire-kimi.sh"):
    seat = script.split("-")[1].split(".")[0]
    check(f"C0 {seat}: renderer extracted", renderer_for(script) is not None)

    out = render(script, {**BASE, "unanswered": {"asked": False, "i_owe": [], "owed_to_me": []}})
    check(f"C1 {seat}: a failed carrier says NOT MEASURED", "NOT MEASURED" in out, repr(out[:160]))
    check(f"C1b {seat}: and does not render as silence", out.strip() != "", repr(out[:160]))

    out = render(script, dict(BASE))
    check(f"C2 {seat}: an ABSENT fold says NOT MEASURED", "NOT MEASURED" in out, repr(out[:160]))

    out = render(script, {**BASE, "unanswered": {"asked": True, "i_owe": [], "owed_to_me": []}})
    check(f"C3 {seat}: a measured zero says so", "MEASURED ZERO" in out, repr(out[:160]))
    check(f"C3b {seat}: and is not confused with a failure", "NOT MEASURED" not in out, repr(out[:160]))

    out = render(script, {**BASE, "unanswered": {"asked": True, "i_owe": rows(2), "owed_to_me": []}})
    check(f"C4 {seat}: rows render, with the liveness legend to head them",
          "id=1000" in out and "quiet Xm" in out, repr(out[:200]))
    check(f"C5 {seat}: a populated fold never claims to be unmeasured",
          "NOT MEASURED" not in out and "MEASURED ZERO" not in out, repr(out[:200]))

    # Legacy primers, written before `asked` existed, must not be relabelled as failures.
    out = render(script, {**BASE, "unanswered": {"i_owe": rows(1), "owed_to_me": []}})
    check(f"C6 {seat}: a pre-`asked` primer with rows still renders them",
          "id=1000" in out and "NOT MEASURED" not in out, repr(out[:200]))

print("\nD. DISPLAY CAP -- a truncation must be as loud as an absence")

# Repairing the carrier means the whole fold now arrives: 1,102 rows / ~205 KB of prompt
# measured on this seat 2026-09-04. Capping is right; capping SILENTLY would re-commit
# the error this change exists to fix, one layer along.
big_fold = {**BASE, "unanswered": {"asked": True, "i_owe": rows(60), "owed_to_me": rows(5)}}
for script in ("fire-claude.sh", "fire-codex.sh", "fire-kimi.sh"):
    seat = script.split("-")[1].split(".")[0]
    out = render(script, big_fold, cap=25)
    check(f"D1 {seat}: the cap holds", out.count("id=10") <= 40, f"{out.count('id=10')} rows")
    check(f"D2 {seat}: truncation is announced with BOTH numbers",
          "NOT SHOWN" in out and "35 further" in out and "60 in the fold" in out,
          repr(out[-400:]))
    check(f"D3 {seat}: the under-cap direction is NOT falsely announced",
          "`nobody has answered you` rows NOT SHOWN" not in out, repr(out[-400:]))
    check(f"D4 {seat}: the cap names itself as display, not measurement",
          "DISPLAY cap" in out and "NOT a measurement" in out, repr(out[-300:]))

    # The arm that matters. With the cap at 0 no row survives, but the debt is real --
    # branching on `rows` instead of on the fold's own count would report a measured zero
    # on the strength of a display setting.
    out = render(script, big_fold, cap=0)
    check(f"D5 {seat}: CAP=0 does not turn real debt into `you owe nobody`",
          "MEASURED ZERO" not in out and "NOT SHOWN" in out, repr(out[:300]))

    # And a fold under the cap must not grow a truncation notice it did not earn.
    out = render(script, {**BASE, "unanswered": {"asked": True, "i_owe": rows(2), "owed_to_me": []}})
    check(f"D6 {seat}: an uncapped fold carries no cap notice",
          "NOT SHOWN" not in out and "DISPLAY cap" not in out, repr(out[-200:]))

# Each seat keeps its own prompt wording; this repair moved the header, it did not merge
# three seats' text into one.
heads = {s: re.search(r'HEADER = (.*)', renderer_for(s)).group(1) for s in
         ("fire-claude.sh", "fire-codex.sh", "fire-kimi.sh")}
check("C7 codex keeps its own (shorter) header rather than being homogenised",
      heads["fire-codex.sh"] != heads["fire-claude.sh"],
      "the wrappers differed before this change and must still differ")


print()
if failures:
    print(f"FAILED {len(failures)}: " + "; ".join(failures))
    sys.exit(1)
print("all arms pass")
