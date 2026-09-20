#!/usr/bin/env python3
"""One unit, three copies: the launchd and systemd templates must parse, and must agree.

WHY THIS EXISTS (McNugget, 2026-09-19). Three times in three weeks a launchd seat was broken
by something the systemd seats had and it did not, and every time it was found by a person
staring at a dashboard rather than by anything that could fail:

  1. 2026-09-08  the daemon answered "deployment update unavailable". `hestia.service` carries
                 HESTIA_CURRENT_BUILD_FILE; the hand-made launchd plist on that seat did not.
  2. 2026-09-08  the deploy agent had never loaded. Its template's XML comment contained
                 `journalctl --user -u hestia-deploy`, and XML forbids `--` inside a comment.
                 `plutil -lint` accepts it; a strict parser refuses the whole file. The repo
                 template still carried it eleven days later, because the fix was made to one
                 seat's copy and nothing here could notice the difference.
  3. 2026-09-19  /api/agents answered UNKNOWN. `hestia.service` carries HESTIA_WORKSPACE; the
                 launchd template did not, so the daemon could not find the agent inventory.

And the daemon unit turned out to have a THIRD copy: deploy/fleet/install.sh writes its plist
from an inline heredoc instead of rendering the template. That copy lacked both keys.

WHAT IS PINNED.
  * Every plist template parses under a STRICT XML parser (plistlib/expat), not merely plutil.
  * For each unit, the set of environment KEYS is identical across its copies, except for the
    keys listed in PLATFORM_ONLY -- each with the reason it is legitimately one-sided. Adding a
    key to one copy without the others, or without a reason here, fails.

It pins keys, not values: `%h/.hestia` and `__HESTIA_HOME__` are the same fact in two syntaxes.

Run: python3 unit_templates_test.py     (no pytest; exit 1 on failure)
"""
from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent
FAILS: list[str] = []

# key -> why it may exist on one platform's copy only. Anything not listed must be everywhere.
PLATFORM_ONLY = {
    "daemon": {
        "MALLOC_ARENA_MAX": "systemd: a glibc malloc tunable; macOS's allocator has no such knob",
        "HOME": "launchd: a gui agent is not guaranteed HOME; systemd has the %h specifier instead",
    },
    "deploy": {
        "HESTIA_BIN": "launchd: README derives it from the daemon's registration, because the binary "
                      "is not always ~/.local/bin/hestia there (McNugget: /opt/homebrew/bin/hestia)",
    },
}


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def service_keys(path: Path) -> set[str]:
    return set(re.findall(r'^Environment="?([A-Za-z_][A-Za-z0-9_]*)=', path.read_text(), re.M))


def plist_keys(path: Path) -> set[str]:
    """Env keys of a plist template. A file that does not parse is ALREADY a finding (step 1
    reports it); it must not also hide the parity findings behind a traceback. The first cut
    of this test did exactly that when run against the tree it was written to indict: one
    ExpatError, and the two missing keys it existed to name never got printed. So fall back
    to reading the keys lexically, from the EnvironmentVariables dict only."""
    raw = path.read_bytes()
    try:
        return set(plistlib.loads(raw).get("EnvironmentVariables", {}))
    except Exception:  # noqa: BLE001
        text = raw.decode("utf-8", "replace")
        m = re.search(r"<key>EnvironmentVariables</key>\s*<dict>(.*?)</dict>", text, re.S)
        return set(re.findall(r"<key>([A-Za-z_][A-Za-z0-9_]*)</key>", m.group(1))) if m else set()


def heredoc_plist_keys(script: Path, delimiter: str) -> set[str]:
    """Env keys of a plist a shell script writes inline. Parsed as XML after neutralising the
    shell expansions, so it is held to the same strictness as the templates."""
    text = script.read_text()
    m = re.search(rf"<<{delimiter}\n(.*?)\n{delimiter}\n", text, re.S)
    assert m, f"no <<{delimiter} heredoc in {script.name}"
    body = re.sub(r"\\?\$\{[^}]*\}|\\?\$\([^)]*\)|\\?\$[A-Za-z_]+", "X", m.group(1))
    return set(plistlib.loads(body.encode()).get("EnvironmentVariables", {}))


def main() -> int:
    # 1. Strict parse. `plutil -lint` said OK to the file this would have refused.
    templates = sorted(DEPLOY.rglob("*.plist"))
    check("there are plist templates to check", len(templates) >= 2, True)
    for t in templates:
        try:
            plistlib.loads(t.read_bytes())
            ok = "parses"
        except Exception as e:  # noqa: BLE001 -- any parse failure is the finding
            ok = f"{type(e).__name__}: {e}"
        check(f"strict XML: {t.relative_to(DEPLOY)}", ok, "parses")

    # 2. Parity, per unit, across every copy of it.
    units = {
        "daemon": {
            "systemd template": service_keys(DEPLOY / "templates" / "hestia.service"),
            "launchd template": plist_keys(DEPLOY / "templates" / "io.hestia.tools.plist"),
            "fleet/install.sh heredoc": heredoc_plist_keys(DEPLOY / "fleet" / "install.sh", "PLIST"),
        },
        "deploy": {
            "systemd template": service_keys(DEPLOY / "from-main" / "hestia-deploy.service"),
            "launchd template": plist_keys(DEPLOY / "from-main" / "com.web4.hestia.deploy.plist"),
        },
    }
    for unit, copies in units.items():
        allowed = set(PLATFORM_ONLY[unit])
        everywhere = set.union(*copies.values()) - allowed
        for name, keys in copies.items():
            check(f"{unit}: keys missing from the {name}", sorted(everywhere - keys), [])
        # An allowlist entry nothing uses any more is a reason with no subject; drop it.
        check(f"{unit}: PLATFORM_ONLY entries that no copy carries",
              sorted(allowed - set.union(*copies.values())), [])
        # ...and one that EVERY copy carries is not platform-specific at all.
        check(f"{unit}: PLATFORM_ONLY entries that every copy carries",
              sorted(k for k in allowed if all(k in c for c in copies.values())), [])

    # 3. The three keys whose absence each cost a seat a working surface.
    for unit, key in (("daemon", "HESTIA_CURRENT_BUILD_FILE"), ("daemon", "HESTIA_WORKSPACE"),
                      ("deploy", "HESTIA_WORKSPACE")):
        for name, keys in units[unit].items():
            check(f"{unit}: {key} present in the {name}", key in keys, True)

    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), {len(templates)} plist template(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
