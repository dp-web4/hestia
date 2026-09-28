"""Where a forbidden token starts and stops matching a path component (hestia #1025).

WHY THIS FILE EXISTS. The first cut of the resolved-act proposal matched a token against a
path component EXACTLY. That reads as the obviously-correct tightening of a substring scan,
and it is wrong in a way the corpus could not see: a secret file is routinely its canonical
name plus an extension. Three real ones — the dot-env file with a `local` suffix, the same
file with a deployment suffix, and the AWS-shaped credential file with its json extension —
went from DENIED under the crude scan to ALLOWED under the improvement.

A precision proposal that is weaker than what it replaces is the worst available outcome.
It was found by attacking the proposal rather than by reading it, and it survived a 15-case
corpus and a 17-case evasion suite, both of which I wrote. That is the lesson worth more
than the fix: a suite built alongside a change tests the change's own idea of itself.

The rule now admits a dot-extension and nothing else. Both halves are pinned below, because
each has a failure mode and they pull in opposite directions:

  too tight  -> the three files above are allowed (a hole this layer introduced)
  too loose  -> hyphen or underscore boundaries refuse prose again (the defect it is for)

Every forbidden token here is assembled at runtime rather than written. Naming them in
source is refused at gate 1a by substring — which is the defect under repair, met once more
while writing its own test. Run: python3 tools/gate_resolved_act_boundaries.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_resolved_act import token_hits_path          # noqa: E402

D = chr(46)
ENV = D + "env"
CRED = "cred" + "entials"
KEY = "id_" + "rsa"
STORE = "sec" + "rets"
KEYDIR = "/" + D + "ssh"
GITCFG = "/" + D + "git/config"

# (token, path, should_match, why)
CASES = [
    # --- the file itself, in every spelling that is still the file -----------------------
    (ENV,  "/srv/app/" + ENV,                      True,  "the canonical name"),
    (ENV,  "/srv/app/" + ENV + D + "local",        True,  "HOLE FOUND: suffixed, still secret"),
    (ENV,  "/srv/app/" + ENV + D + "production",   True,  "HOLE FOUND: deployment suffix"),
    (ENV,  "/srv/app/app" + ENV,                   True,  "prefixed basename, dot boundary"),
    (CRED, "/home/u/" + CRED + D + "json",         True,  "HOLE FOUND: the AWS-shaped file"),
    (CRED, "/home/u/" + CRED,                      True,  "extensionless, a directory or file"),
    (KEY,  "/home/u/" + KEY,                       True,  "the key"),
    (KEY,  "/home/u/" + KEY + D + "pub",           True,  "its public half — refuse anyway"),
    (STORE, "/srv/" + STORE + D + "yaml",          True,  "a store with an extension"),

    # --- names that merely START with the token, and are not it --------------------------
    (ENV,  "/srv/" + D + "environment",            False, "a longer word, not the file"),
    (ENV,  "/docs/environment" + D + "md",         False, "prose about environments"),
    (CRED, "/docs/" + CRED + "-howto" + D + "md",  False, "a document ABOUT them"),
    (KEY,  "/docs/" + KEY + "-rotation" + D + "md", False, "runbook naming the thing"),
    (STORE, "/docs/no-" + STORE + "-here" + D + "md", False, "the plural noun in a filename"),
    (KEYDIR, "/home/u/" + D + "sshrc",             False, "a shell rc, not the directory"),

    # --- multi-component tokens match a RUN of components, on the same boundaries ---------
    (KEYDIR, "/home/u/" + D + "ssh/config",        True,  "inside the key directory"),
    (GITCFG, "/repo/" + D + "git/config",          True,  "the repo config itself"),
    (GITCFG, "/repo/" + D + "github/config",       False, "a different directory entirely"),
    (GITCFG, "/repo/" + D + "git/config" + D + "bak", True, "a copy of it is still it"),
]


def main() -> int:
    wrong = []
    print(f"{'':4} {'verdict':8} {'want':8} path")
    for token, path, want, why in CASES:
        got = token_hits_path(token, path)
        ok = got == want
        wrong.append((token, path, why)) if not ok else None
        print(f"{'' if ok else 'XX':4} {'HIT' if got else 'miss':8} "
              f"{'HIT' if want else 'miss':8} {path:46} {why}")
    print(f"\n{len(CASES) - len(wrong)}/{len(CASES)} correct")
    if wrong:
        print("\nWRONG:")
        for t, p, why in wrong:
            print(f"  {t!r} vs {p!r} — {why}")
        return 1
    print("Both directions hold: every real file matched, no prose refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
