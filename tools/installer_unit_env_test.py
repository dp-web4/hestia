#!/usr/bin/env python3
"""The unit the installer WRITES must carry every Environment the template DECLARES.

WHY THIS EXISTS, measured rather than imagined. On 2026-08-24, answering "what are the
obstacles to deployment", the systemd unit turned out to have two definitions:

  deploy/templates/hestia.service   4 Environment lines   <- a template
  deploy/fleet/install.sh heredoc   3 Environment lines   <- what actually installs

The one missing from the installer was `HESTIA_CURRENT_BUILD_FILE`, and
`dashboard.rs::deployment_health` reads exactly that variable with NO fallback: unset means
`deployment_health_from_path(None)` -> state "unknown".

So running the fleet installer would have rewritten the live unit without it and taken the
deployment badge from "stale" (a signal) to "unknown" (no signal). The tool you reach for
to deploy would have silently disabled the instrument that tells you whether the deploy
landed — and the live unit on CBP still had the variable, so nothing would have surfaced
the loss until someone next asked the badge a question.

THE INVARIANT IS DIRECTIONAL, and that is the point. The template is the declaration; the
heredoc is the producer. A producer missing a declared variable is a silent capability
loss. The reverse — the installer setting something the template does not mention — is
allowed here, because the installer legitimately substitutes host-derived values.

Same class as `merged != deployed` and `registration != reachability`: two spellings of one
fact, and the one nobody reads drifts.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "templates" / "hestia.service"
INSTALLER = ROOT / "deploy" / "fleet" / "install.sh"

# The gauge's only input. Named explicitly as well as covered by the set comparison below,
# so a future edit that drops BOTH files' copy still fails on something that says why.
GAUGE_VAR = "HESTIA_CURRENT_BUILD_FILE"


def env_names(text):
    """Environment variable NAMES, ignoring values — the installer substitutes host paths."""
    return {m.group(1) for m in re.finditer(r"^Environment=([A-Z0-9_]+)=", text, re.M)}


def installer_unit_body(text):
    """The heredoc the installer writes to ~/.config/systemd/user/hestia.service."""
    m = re.search(r'cat > "\$unit" <<UNIT\n(.*?)\n^UNIT$', text, re.S | re.M)
    assert m, (
        "could not find the unit heredoc in deploy/fleet/install.sh. If the installer "
        "stopped writing the unit inline, this guard is measuring nothing — point it at "
        "whatever writes the unit now."
    )
    return m.group(1)


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    unit = installer_unit_body(installer)

    declared = env_names(template)
    installed = env_names(unit)

    assert declared, "the template declares no Environment lines — this guard is inert"
    assert installed, "the installer heredoc sets no Environment lines — this guard is inert"

    missing = declared - installed
    assert not missing, (
        f"deploy/fleet/install.sh writes the unit WITHOUT {sorted(missing)}, which "
        f"deploy/templates/hestia.service declares. The heredoc is what actually installs, "
        f"so running the installer would strip these from the live unit. This is how "
        f"{GAUGE_VAR} went missing on 2026-08-24: the template had it, the installer did "
        f"not, and the deployment gauge has no fallback — unset reads as 'unknown'."
    )

    assert GAUGE_VAR in installed, (
        f"{GAUGE_VAR} is absent from the unit the installer writes. dashboard.rs reads it "
        f"with no fallback; without it the deployment gauge reports 'unknown' and the fleet "
        f"loses its only signal about whether a deploy landed."
    )

    print(f"ok: installer sets all {len(declared)} declared Environment vars {sorted(declared)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
