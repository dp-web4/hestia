#!/usr/bin/env python3
"""`hooks_repair_hint` must name the cause it actually hit, not the one that shares its prefix.

WHY THIS EXISTS (CBP, 2026-08-31, measured from /home/dp/.hestia/deploy.log).

Two producers put a value starting with `refused(` into `$hooks`, and they need OPPOSITE
advice:

  * `refused(governed session)` — the installer's own rc=3, its gate declining to run inside
    a governed session. The timer is not a session, so the NEXT CYCLE GENUINELY REPAIRS IT.
  * `refused(FAILED(...))` — `install_hooks` refusing on a `preflight_gate` verdict. The
    preflight runs on every path into the members' install, the timer's and `--hooks-only`'s
    alike, so the next cycle re-runs it and REFUSES IDENTICALLY. Nothing repairs it but the
    operator act the verdict names.

The hint's `case` keyed on the glob `refused*`, written when rc=3 was the only producer. The
preflight producer was added later and silently inherited the rc=3 remedy. CBP then printed

    HALF-DEPLOYED v0.0.4-529-g6a12873: ... hooks=refused(FAILED(rule-0: ...));
    the members' installer refuses inside a governed session (CLAUDECODE/HESTIA_ROLE set);
    the next timer cycle repairs it, or run hestia-deploy --hooks-only from an operator shell

on 7 consecutive cycles, 2026-08-30T03:18:27Z .. 2026-08-31T03:18:26Z — every cycle since the
rule-0 auditor landed. A sentence whose stated cause was not the one hit and
whose promised repair is refuted by the next seven lines of the same log. Both halves of the
advice were false for that arm: `--hooks-only` hits the identical preflight. Meanwhile the
members' governance surface stayed pinned at the older build while the daemon moved on.

WHAT IS PINNED. Not the prose — the DISCRIMINATION. A hint that cannot tell the two producers
apart fails here, whatever words it uses. Plus the control-flow fact the wording rests on: the
preflight is inside `install_hooks`, which is what makes "no timer cycle repairs this" true. If
someone moves the preflight off the shared path, this test goes red and the wording gets
revisited, rather than quietly becoming wrong again.

Run: python3 deploy/from-main/hooks_repair_hint_test.py   (from the repo root, or anywhere)
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True, check=True,
                   cwd=pathlib.Path(__file__).resolve().parent).stdout.strip()
)
SCRIPT = REPO / "deploy" / "from-main" / "hestia-deploy.sh"

FAILURES = []


def check(name, ok, detail=""):
    if ok:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f"\n        {detail}" if detail else ""))
        FAILURES.append(name)


def extract_function(text, fname):
    """The function's source, from `name() {` to the first line that is exactly `}`.

    ABSENCE IS ITS OWN ARM. A rename or a move must land as a loud failure, never as an
    empty string that every assertion below then vacuously passes — that is the
    reads-as-clean class this deploy script has already been bitten by three times.
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(fname)}\(\)\s*\{{\s*$", ln):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j] == "}":
            return "\n".join(lines[start:j + 1])
    return None


def hint_for(fn_src, hooks_value):
    """Run the real function with $hooks set, in a bash of its own."""
    prog = f'{fn_src}\nhooks={hooks_value!r}\nhooks_repair_hint\n'
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return f"<bash rc={r.returncode}: {r.stderr.strip()[:200]}>"
    return r.stdout


def main():
    if not SCRIPT.is_file():
        check("the deploy script is where this test expects it", False, str(SCRIPT))
        return 1
    text = SCRIPT.read_text(encoding="utf-8")

    fn = extract_function(text, "hooks_repair_hint")
    check("hooks_repair_hint() is present and extractable", fn is not None,
          "not found — renamed or reshaped; this test cannot pin what it cannot find")
    if fn is None:
        return 1

    governed = hint_for(fn, "refused(governed session)")
    rule0 = hint_for(fn, "refused(FAILED(rule-0: settings.json: /w/gate.py in /w))")
    benign = hint_for(fn, "refused(FAILED(gate refuses a benign read))")
    rc7 = hint_for(fn, "FAILED(rc=7)")
    rc0 = hint_for(fn, "FAILED(installer rc=0, manifest 'none')")

    # 1. THE DEFECT ITSELF: the two `refused(` producers must not get the same sentence.
    check("a preflight refusal and a governed-session refusal get DIFFERENT hints",
          rule0.strip() != governed.strip(),
          "both produce:\n        " + governed.strip()[:300])

    # 2. The rc=3 arm keeps the advice that is TRUE for it.
    check("refused(governed session) still promises the timer repair",
          "next timer cycle repairs it" in governed, governed.strip()[:300])
    check("refused(governed session) still names the governed-session constraint",
          "governed session" in governed, governed.strip()[:300])

    # 3. The preflight arms must not promise a repair that cannot happen, and must not
    #    attribute the refusal to a cause they did not hit.
    for label, out in (("rule-0", rule0), ("benign-read", benign)):
        promises = re.search(r"next timer cycle repairs it|let the next timer cycle repair it",
                             out)
        check(f"refused(FAILED({label})) does NOT promise a timer repair",
              promises is None, out.strip()[:300])
        # Narrow on purpose. The rule-0 hint may legitimately SAY "a governed session has
        # no in-band route to this remedy" — that is why the fix is an operator act. What it
        # must never do is ATTRIBUTE the refusal to rc=3's cause, which is this sentence and
        # this env-var pair.
        check(f"refused(FAILED({label})) does NOT blame the installer's governed-session rc=3",
              "installer refuses inside a governed session" not in out
              and "CLAUDECODE" not in out, out.strip()[:300])
        check(f"refused(FAILED({label})) says the preflight refused",
              "preflight" in out.lower(), out.strip()[:300])

    # 4. The rule-0 arm points at the one thing that ends it: the REGISTRATION, in both
    #    spellings. A hint that names only hooks[].command leaves the env spelling in place
    #    and the next cycle refuses again — which is how this arm stays live.
    check("the rule-0 hint names the registration as the thing to move",
          "REGISTRATION" in rule0 or "registration" in rule0, rule0.strip()[:300])
    check("the rule-0 hint names the env spelling too (HESTIA_LEGACY_FALLBACK)",
          "HESTIA_LEGACY_FALLBACK" in rule0, rule0.strip()[:300])

    # 5. Untouched arms stay untouched.
    check("FAILED(installer rc=0 ...) keeps its own hint",
          "exited 0 without writing the manifest" in rc0, rc0.strip()[:200])
    check("FAILED(rc=N) keeps the generic fix-the-cause hint",
          "fix the cause" in rc7, rc7.strip()[:200])

    # 6. THE CONTROL-FLOW FACT THE WORDING RESTS ON. "No timer cycle repairs this" is true
    #    only because the preflight is inside the function every path calls. Pin it.
    install_hooks = extract_function(text, "install_hooks")
    check("install_hooks() is present and extractable", install_hooks is not None)
    if install_hooks:
        check("the preflight runs INSIDE install_hooks (so every path hits it)",
              "preflight_gate" in install_hooks,
              "preflight moved off the shared path — the 'no timer cycle repairs this' "
              "wording is no longer justified and must be revisited")
        check("install_hooks turns a FAILED preflight into a refused( ) hooks value",
              re.search(r'hooks="refused\(\$preflight\)"', install_hooks) is not None,
              "the producer this test's premise names is gone; re-derive the table")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
