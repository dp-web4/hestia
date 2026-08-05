#!/usr/bin/env python3
"""The bundle we ship to other machines carries a different scope policy than the repo states.

WHAT HAPPENED (LEGION, 2026-07-31, thread supervisor-role-2026-07-31). CBP measured
`mrh.in_scope` across three deployed members and found one policy instantiated three
ways, then made the point the whole thread converged on: none of the divergences arrived
through a bad write. One arrived through a generator that never ran. So a supervisor
validating writes catches none of them; what is missing is not an authority, it is a
comparison.

This file is that comparison, one layer up from the data CBP measured -- because the
same disease had reached the code that computes the policy, and nothing in the repo
compared THOSE two copies either.

`plugins/codex/` exists twice: the canonical tree, and `marketplace/plugins/hestia-codex/`,
which `plugins/codex/README.md` calls "the portable form for other machines" and which
`codex plugin marketplace add` installs. Five files are shared. On the day this test was
written, FOUR of the five had diverged, both copies last touched by the same commit
(d4a7297, a chmod fix) -- so no one had synced content since whenever the bundle was cut:

  - hydrate.sh          PRIVATE_EXCEPTIONS = {"shared-context"} vs canonical's three
  - identity.seed.json  23 mrh.in_scope entries vs 25 (no repo:memory, no repo:private-context)
  - pre_tool_use.py     11,529 bytes vs 42,091 -- the gate itself, ~558 changed lines
  - hooks.json          structural, correct, and the reason an exceptions file exists
  - observe.sh          identical

The first two are the ones that matter. A member installed from the bundle regenerates
its scope, every session end, against a base that does not contain `memory` or
`private-context` -- and CBP's other finding was that the merge rule
(`accrued = [s for s in cur if s.split(":",1)[-1] not in allowed_base]`) can widen and can
never narrow. Accrual only preserves what is already there. A fresh bundle install never
had those two entries to accrue, so nothing will ever add them. The narrowing arrives
pre-installed and is permanent by the same construction that makes widening permanent.

No write did this. Somebody edited one copy correctly and did not edit the other, which is
the only thing anyone was ever going to do. That is why this is a test and not a role.

WHAT THE REPO ALREADY HAD, AND DID NOT HAVE. `plugins/member-mesh/tests/install_drift_test.py`
compares the repo against the DEPLOYMENT ("a merged fix that never reaches the hooks dir is
not a fix"). Nothing compared the repo against the ARTIFACT IT SHIPS. Both are copies with
no comparator; only one had grown its comparator.

Properties asserted:

  A. EVERY SHARED FILE IS COMPARED. Byte-identical, or named in
     marketplace/PARITY_EXCEPTIONS.txt with a sentence above it. Not a hardcoded
     list of the files that happened to exist when this was written -- discovered
     from the trees, so a sixth file is gated the day someone adds it.
  B. A CANONICAL HOOK MISSING FROM THE BUNDLE IS REPORTED. `witness.py` is absent
     today. Withholding a capability from the portable form may be right; doing it
     without a sentence is the same silence as the drift.
  C. A STALE EXCEPTION IS RED. A path listed that is now identical, or that no longer
     exists in either tree, fails -- the ci_excluded_tests.txt rule, same reason: a
     stale excuse reads as a known gap while the gap is closed.
  D. POLICY PARITY IS ABOUT DIRECTION, NOT EQUALITY, and this is the property the
     file is for. The scope constants are compared on MEANING, not bytes: hydrate's
     PRIVATE_EXCEPTIONS set, and the seed's mrh.in_scope set. A path in the
     exceptions file suppresses A, never D.

     THE FIRST VERSION ASSERTED EQUALITY AND WAS WRONG (codex/gpt open-PR audit,
     2026-08-04). It went red because the bundle lacks two of this operator's
     private repos -- reporting CORRECT behaviour as drift, and inviting a "fix"
     that would have copied private grants into the portable artifact. That turns a
     drift detector into an AUTHORITY LEAK: a public bundle carrying one operator's
     private repo names into every installation that unpacks it.

     The three trees -- canonical source, portable bundle, installed copy -- differ
     along two independent axes, and the first version conflated them:

       MECHANISM  gate logic, hook coverage, witnessing, fail-closed behaviour.
                  MUST match. Asserted by A/B/C and D5/D6.
       AUTHORITY  MRH grants, private exceptions, operator overlays.
                  MUST differ per installation. A bundle that matches here is broken.

     So D now asserts the direction: the portable artifact may hold FEWER grants
     than canonical, never more (D2, D4) -- extra is a leak, fewer is the point --
     and every withheld grant must be DECLARED (D4b). Narrower is correct; silently
     narrower is how the original finding hid, because the identity merge rule only
     ever widens, so a base the bundle lacks is one a bundle install can never
     accrue. A marketplace member therefore has a real, permanent capability gap
     versus a repo member. That is a deliberate boundary, and D4b makes it knowledge
     rather than folklore.

     The original finding stands unchanged and is preserved above: four of five
     shared files had diverged and nothing compared them. What changed is the
     invariant, not the evidence.

Hermetic: reads the checkout it lives in. No network, no daemon, no fixtures.

surface: plugins/codex/tests/marketplace_parity_test.py   act: none (read-only comparison)
S: low/reversible [construct: opens no path a caller can drive; reads two trees, prints, exits]
R: n/a   W: n/a
O: n/a [construct: no side effect to order]   A: n/a [construct: emits no record]
V: n/a
verdict: PASS
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CANON = os.path.join(REPO, "plugins", "codex")
BUNDLE = os.path.join(CANON, "marketplace", "plugins", "hestia-codex")
EXCEPTIONS = os.path.join(CANON, "marketplace", "PARITY_EXCEPTIONS.txt")

failures = []


def check(cond, label, detail=""):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        if detail:
            for line in str(detail).rstrip().splitlines():
                print(f"         {line}")
        failures.append(label)


def rel(path):
    """Repo-relative, the form PARITY_EXCEPTIONS.txt speaks."""
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def walk(root):
    """Every tracked-shaped file under root, keyed by its path relative to root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "marketplace")]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, root).replace(os.sep, "/")] = full
    return out


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def load_exceptions():
    """Declared paths, in canonical repo-relative form. Absent file == no exceptions."""
    if not os.path.exists(EXCEPTIONS):
        return []
    declared = []
    for line in open(EXCEPTIONS, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            declared.append(line)
    return declared


# ---------------------------------------------------------------- policy readers
# Deliberately textual and deliberately narrow. These parse the ONE construct each
# copy uses to express scope, so that a rewrite which changes the construct fails
# loudly here rather than passing by returning an empty set. A policy reader that
# silently finds nothing is the fail-soft this whole thread is about.

def private_exceptions(hydrate_path):
    src = open(hydrate_path, encoding="utf-8").read()
    m = re.search(r"^PRIVATE_EXCEPTIONS\s*=\s*\{([^}]*)\}", src, re.M)
    if not m:
        return None
    return frozenset(re.findall(r'"([^"]+)"', m.group(1)))


def seed_in_scope(seed_path):
    try:
        d = json.load(open(seed_path, encoding="utf-8"))
    except Exception:
        return None
    scope = (d.get("mrh") or {}).get("in_scope")
    if scope is None:
        return None
    return frozenset(scope)


def hooked_events(hooks_json_path):
    try:
        d = json.load(open(hooks_json_path, encoding="utf-8"))
    except Exception:
        return None
    h = d.get("hooks")
    return frozenset(h.keys()) if isinstance(h, dict) else None


# ---------------------------------------------------------------------- the run
print(f"canonical: {rel(CANON)}")
print(f"bundle:    {rel(BUNDLE)}")

if not os.path.isdir(BUNDLE):
    print(f"\nFAIL the bundle is gone from {rel(BUNDLE)} — the layout moved, and this "
          f"test cannot tell that from parity")
    sys.exit(1)

canon = walk(CANON)
bundle = walk(BUNDLE)
declared = load_exceptions()
declared_set = set(declared)
shared = sorted(set(canon) & set(bundle))
used = set()

print(f"\nA. every shared file is byte-identical or declared ({len(shared)} shared)")
check(bool(shared), "A0. the two trees share at least one file — otherwise this compares nothing",
      f"canonical={len(canon)} bundle={len(bundle)}")
for name in shared:
    key = rel(canon[name])
    same = read_bytes(canon[name]) == read_bytes(bundle[name])
    if same:
        check(True, f"A. {name} identical")
        continue
    used.add(key)
    check(key in declared_set,
          f"A. {name} differs and is declared in PARITY_EXCEPTIONS.txt",
          f"canonical {os.path.getsize(canon[name])}B vs bundle "
          f"{os.path.getsize(bundle[name])}B; add '{key}' with a reason, or sync it")

print("\nB. a canonical hook absent from the bundle is declared, not silent")
for name in sorted(canon):
    if not name.startswith("hooks/") or name in bundle:
        continue
    key = rel(canon[name])
    used.add(key)
    check(key in declared_set,
          f"B. {name} is shipped nowhere and says so in PARITY_EXCEPTIONS.txt",
          f"add '{key}' with a reason, or add the file to the bundle")

print("\nC. no stale exception")
for key in declared:
    full = os.path.join(REPO, key)
    if not os.path.exists(full):
        check(False, f"C. {key} is declared but does not exist",
              "the path moved or was deleted; drop the entry")
        continue
    check(key in used,
          f"C. {key} is declared and really diverges",
          "it is identical to the bundle copy (or is not shared at all) — "
          "drop the entry rather than leave a closed gap reading as an open one")

print("\nD. scope policy matches on meaning — NOT exceptable by PARITY_EXCEPTIONS.txt")
ch, bh = os.path.join(CANON, "hooks", "hydrate.sh"), os.path.join(BUNDLE, "hooks", "hydrate.sh")
if os.path.exists(ch) and os.path.exists(bh):
    cpe, bpe = private_exceptions(ch), private_exceptions(bh)
    check(cpe is not None and bpe is not None,
          "D1. PRIVATE_EXCEPTIONS is readable in both hydrate copies",
          f"canonical={cpe} bundle={bpe} — the construct changed; teach this reader, "
          f"do not let it return nothing")
    if cpe is not None and bpe is not None:
        # THE DIRECTION IS THE INVARIANT, NOT EQUALITY (codex/gpt audit 2026-08-04).
        #
        # This asserted `cpe == bpe` and went red because the bundle lacks two of this
        # operator's private repos. That red was reporting CORRECT behaviour as drift, and
        # the "fix" it invited — copy the missing grants into the shipped artifact — would
        # have turned a drift detector into an AUTHORITY LEAK: a public bundle carrying one
        # operator's private repo names into every installation that ever unpacks it.
        #
        # The three trees (canonical source, portable bundle, installed copy) differ along
        # two independent axes and the first version conflated them:
        #
        #   MECHANISM   gate logic, hook coverage, witnessing, fail-closed behaviour.
        #               Must match. Asserted by D5/D6 and the byte-parity section above.
        #   AUTHORITY   MRH grants, private repo exceptions, operator overlays.
        #               MUST differ per installation. A bundle that matches here is broken.
        #
        # So the portable artifact may hold FEWER private exceptions than canonical, never
        # more: extra is a leak, fewer is the point.
        leaked = sorted(bpe - cpe)
        check(not leaked,
              "D2. the shipped hydrate leaks no private exception the canonical tree lacks",
              f"bundle-only={leaked}\nA portable artifact must not carry authority no one "
              f"granted in it. Fewer than canonical is correct; MORE is the leak.")

cs, bs = os.path.join(CANON, "instance", "identity.seed.json"), \
         os.path.join(BUNDLE, "instance", "identity.seed.json")
if os.path.exists(cs) and os.path.exists(bs):
    cin, bin_ = seed_in_scope(cs), seed_in_scope(bs)
    check(cin is not None and bin_ is not None,
          "D3. mrh.in_scope is readable in both seeds",
          f"canonical={cin is not None} bundle={bin_ is not None}")
    if cin is not None and bin_ is not None:
        # Same split as D2. The shipped seed SHOULD be narrower — it is installed on machines
        # that were granted nothing by this operator.
        over = sorted(bin_ - cin)
        check(not over,
              "D4. the shipped seed grants no scope the canonical seed does not",
              f"canonical={len(cin)} bundle={len(bin_)}\nbundle-only={over}\n"
              f"A bundle wider than canonical hands every installer authority nobody issued.")

        # AND THE DIFFERENCE MUST BE DECLARED, not merely permitted. Narrower is correct, but
        # silently narrower is how the original finding hid: an install accrues scope by a
        # merge rule that only ever widens, so a base the bundle lacks is one a bundle install
        # can NEVER reach. That is a real, permanent capability gap between a repo member and a
        # marketplace member — worth knowing deliberately rather than discovering when someone
        # asks why their install cannot see a repo.
        withheld = sorted(cin - bin_)
        # Read the ledger RAW, comments included: the declared paths are the machine-readable
        # half, but the REASON a thing is withheld is written in the prose above it, and that
        # prose is what a human needs. load_exceptions() strips it by design.
        ledger = open(EXCEPTIONS, encoding="utf-8").read() if os.path.exists(EXCEPTIONS) else ""
        undeclared = [w for w in withheld if w not in ledger]
        check(not undeclared,
              "D4b. every scope withheld from the bundle is declared in PARITY_EXCEPTIONS.txt",
              f"withheld={withheld}\nundeclared={undeclared}\n"
              f"Withholding private authority from a portable artifact is CORRECT. Doing it "
              f"without a written reason is how a capability gap becomes folklore.")

cj, bj = os.path.join(CANON, "hooks", "hooks.json"), os.path.join(BUNDLE, "hooks", "hooks.json")
if os.path.exists(cj) and os.path.exists(bj):
    ce, be = hooked_events(cj), hooked_events(bj)
    check(ce is not None and be is not None,
          "D5. the hook event set is readable in both hooks.json copies",
          f"canonical={ce} bundle={be}")
    if ce is not None and be is not None:
        check(ce == be,
              "D6. both register the same events — hooks.json may differ in paths, never in coverage",
              f"canonical={sorted(ce)}\nbundle   ={sorted(be)}\n"
              f"missing-from-bundle={sorted(ce - be)}")

print()
if failures:
    print(f"failures={len(failures)}")
    for f in failures:
        print(f"  - {f}")
    print("\nA red under D is the point of this file, not a flake: the artifact we tell other "
          "\nmachines to install ships a narrower scope policy than the repo declares, and no "
          "\nwrite to any identity.json will show it. See the thread supervisor-role-2026-07-31.")
    sys.exit(1)
print("canonical codex plugin and its marketplace bundle agree, or say where they don't")
