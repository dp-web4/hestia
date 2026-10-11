#!/usr/bin/env python3
"""Prove every *registered* candidate gate can retain the deploy escape hatch.

``hestia-deploy`` used to exercise only the Claude Code adapter before replacing
all member hooks.  That made its green preflight a statement about one harness,
not the set the installer was about to change.  This runner keeps the harness
details in each plugin's ``expects.json`` and tests only gates whose registration
is present on this host -- since 2026-10-06, the registration the install WILL
write (the candidate's own ``deploy/register-members.py`` renders and reconciles
it in memory), not the one on disk, which the install is about to rewrite.

It deliberately proves availability, not entitlement: a member may have an empty
standing scope and still retain its temp-root read and deploy-hold escape hatch.
The candidate must allow both acts while its normal enforce posture is active.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable

# The projection rewrite is shared with hestia-deploy.sh's claude-code arm, which shells out
# to the same module: one literal-safe implementation, tested once (sed's replacement side
# expands `&` to the whole match — a deploy root like `build&review` corrupted the line it was
# meant to re-point, GPT review of #1176).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seat_projection_repoint import repoint as _repoint_projection  # noqa: E402


def _commands_from_registration(path: Path, reader: str) -> list[str]:
    """Return declared hook commands, or raise for an unreadable declaration.

    This mirrors the installer's deliberately small readers.  An unknown or
    malformed registration is not evidence that a gate is absent.
    """
    if reader == "json-hook-commands":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"registration is not readable JSON: {type(exc).__name__}") from exc

        commands: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "command" and isinstance(child, str):
                        commands.append(child)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(document)
        return commands

    if reader == "toml-hook-commands":
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"registration is unreadable: {type(exc).__name__}") from exc
        return [match.group(2) for line in lines
                if (match := re.match(r'''\s*command\s*=\s*(['"])(.*)\1\s*$''', line))]

    raise ValueError(f"unknown install.registration.reader: {reader!r}")


# The one environment variable a seat cannot derive: its bootstrap locator. A candidate that
# consumes the vault projection refuses to act without it, so the preflight must probe under
# what the SEAT's launcher supplies, not under what the deploy unit happens to carry.
BOOTSTRAP_LOCATOR = "HESTIA_HOME"
#: How long the preflight lets one candidate probe run (its subprocess timeout), declared to the
#: candidate as HESTIA_HOOK_TIMEOUT_S so the candidate decides inside it.
PROBE_TIMEOUT_S = 12


def _launcher_env(commands: Iterable[str], entry: str) -> dict[str, str]:
    """The `KEY=value` assignments the registered hook line supplies to exactly this gate.

    A hook command is `ENV=v ENV2=v2 python3 /abs/path/gate.py`; the launcher's supply is
    the assignments before the interpreter. Values are read as the shell would read a
    double-quoted assignment on that line: `$HOME`-style references expand, and a
    `${X:-default}` default is honoured as the launcher's own choice (the launcher is the one
    place a default for the locator is permitted -- it is the launcher supplying it).
    """
    import shlex
    wanted = Path(entry).name
    for command in commands:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if not any(token.startswith("/") and Path(token).name == wanted for token in tokens):
            continue
        supplied: dict[str, str] = {}
        for token in tokens:
            if "=" not in token or token.startswith(("/", "-")):
                break
            key, value = token.split("=", 1)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                break
            # `${X:-default}` -> default when X is not in the launcher's own environment
            m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-(.*)\}", value)
            if m:
                value = os.environ.get(m.group(1)) or m.group(2)
            supplied[key] = os.path.expandvars(value)
        return supplied
    return {}


def _load_registrar(repo: Path):
    """The CANDIDATE tree's deploy/register-members.py, loaded as a module: the one renderer and
    reconciler install-members.sh will run after this preflight. Shared, never re-implemented here,
    so the line the probe judges is byte-for-byte the line the install writes (dp 2026-10-06).
    None when the candidate predates the reconciler (then the registered line is what will run)."""
    path = repo / "deploy" / "register-members.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("hestia_register_members_candidate", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module if hasattr(module, "reconciled_commands") else None


def _registered(commands: Iterable[str], entry: str) -> bool:
    """Whether a registration invokes exactly this gate entrypoint basename."""
    wanted = Path(entry).name
    for command in commands:
        for token in command.split():
            if token.startswith("/") and Path(token).name == wanted:
                return True
    return False


def _render(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [_render(child, replacements) for child in value]
    if isinstance(value, dict):
        return {key: _render(child, replacements) for key, child in value.items()}
    return value


def _payload_denies(stdout: str) -> bool:
    """A harness may encode a policy denial in JSON while exiting zero."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return False
    return isinstance(value, dict) and (
        value.get("permissionDecision") == "deny" or value.get("decision") == "deny"
    )


def _throwaway_seat_home(member: str, environment: dict[str, str], parent: Path) -> Path | None:
    """A seat home whose projection names the CANDIDATE engine, or None if unconfigured.

    The candidate gate loads its seat projection at import and exports every projected key
    OVER the probe environment (#944: the vault is the authority, a hook line is not). That
    silently replaces the HESTIA_SHARED_DIR pin below with the INSTALLED engine path, so the
    probe pairs the new gate with the old engine and every deploy that adds an engine function
    the gate uses fails preflight forever (#1171: #1149's correlation_key refused on CBP and
    Legion identically; nothing repaired it).

    The pairing that exists after install is gate + the tree being installed, so probe under a
    throwaway home whose projection is the seat's own, re-pointed by the shared
    seat_projection_repoint module. A seat with no rendered projection keeps the probe env
    unchanged: its candidate refuses config.unbacked either way, which is the truth of that
    seat.
    """
    launcher_home = environment.get(BOOTSTRAP_LOCATOR)
    if not launcher_home:
        return None
    real_projection = Path(launcher_home) / "seats" / f"{member}.env"
    if not real_projection.is_file():
        return None
    return _repoint_projection(member, real_projection, parent / member,
                               environment["HESTIA_SHARED_DIR"])


def run_probes(
    repo: Path,
    home: Path,
    endpoint: str,
    scratch: str,
    hold: str,
    excluded: set[str] | None = None,
    workspace: Path | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Run candidate probes and return public-safe status rows plus success."""
    excluded = excluded or set()
    rows: list[dict[str, Any]] = []
    good = True
    workspace_text = str((workspace or repo.parent).resolve())
    # One temp root for every throwaway seat home this run builds; the probes are
    # synchronous, so the homes can leave with the run.
    registrar = _load_registrar(repo)
    with tempfile.TemporaryDirectory(prefix="gate-preflight-homes-") as homes_raw:
        homes = Path(homes_raw)
        rows, good = _run_probes(repo, home, endpoint, scratch, hold, excluded, workspace_text, homes,
                                 registrar)
    return rows, good


def _run_probes(
    repo: Path,
    home: Path,
    endpoint: str,
    scratch: str,
    hold: str,
    excluded: set[str],
    workspace_text: str,
    homes: Path,
    registrar: Any = None,
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    good = True

    for expects_path in sorted((repo / "plugins").glob("*/expects.json")):
        member = expects_path.parent.name
        if member in excluded:
            continue
        try:
            spec = json.loads(expects_path.read_text(encoding="utf-8"))
            install = spec.get("install") or {}
            registration = install.get("registration") or {}
            probe = install.get("gate_probe")
            if not isinstance(probe, dict):
                raise ValueError("missing install.gate_probe")
            segments = registration.get("path") or []
            reader = registration.get("reader")
            entry = probe.get("entry")
            events = probe.get("events")
            if (not isinstance(segments, list) or not all(isinstance(x, str) for x in segments)
                    or not isinstance(reader, str) or not isinstance(entry, str)
                    or not isinstance(events, list) or not events):
                raise ValueError("invalid install.gate_probe or registration declaration")
        except (OSError, ValueError, TypeError) as exc:
            rows.append({"member": member, "status": "unmeasured", "reason": str(exc)})
            good = False
            continue

        # PROBE THE REGISTRATION THE INSTALL WILL WRITE (dp 2026-10-06, #1237 #1242). Since the
        # registrar became a reconciler, hestia's own hook lines are rewritten to the rendered
        # template on every deploy -- so the line on disk now is NOT the line the candidate will run
        # under. Probing the current line refused forever on every host whose line predated a
        # template change (stage C's HESTIA_HOME): the install that would have fixed the line was
        # the install the preflight blocked. For a member that ships a template, the commands come
        # from the candidate's own register-members.py (render + reconcile, in memory, every planned
        # file assumed installed). A member without one is never touched by the install, so its
        # registered line is still the truth.
        template = expects_path.parent / "hooks" / "hooks.json"
        if registrar is not None and template.is_file() and install.get("dest"):
            status, commands, why = registrar.reconciled_commands(str(expects_path.parent), str(home),
                                                                  os.environ)
            if status == "absent":
                rows.append({"member": member, "status": "not-registered"})
                continue
            if status != "ok":
                rows.append({"member": member, "status": "unmeasured",
                             "reason": f"the install would not register this member: {why}"[:300]})
                good = False
                continue
        else:
            registration_path = home.joinpath(*segments)
            if not registration_path.exists():
                rows.append({"member": member, "status": "not-registered"})
                continue
            try:
                commands = _commands_from_registration(registration_path, reader)
            except ValueError as exc:
                rows.append({"member": member, "status": "unmeasured", "reason": str(exc)})
                good = False
                continue
        if not _registered(commands, entry):
            rows.append({"member": member, "status": "not-registered"})
            continue

        candidate = expects_path.parent / entry
        if not candidate.is_file():
            rows.append({"member": member, "status": "unmeasured", "reason": "candidate missing"})
            good = False
            continue

        declared_env = probe.get("environment") or {}
        if not isinstance(declared_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in declared_env.items()
        ):
            rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe environment"})
            good = False
            continue
        # THE PROBE RUNS UNDER THE LAUNCHER'S ENVIRONMENT, NOT THE DEPLOY UNIT'S. The unit that
        # runs this deploy carries HESTIA_HOME (it needs it for its own daemon), and until
        # 2026-09-05 that value leaked into the probe. The first candidate that CONSUMES the
        # vault projection (#959) therefore answered the preflight on a box whose interactive
        # launcher and watcher units supplied no locator at all, and would have been installed
        # into seats that could then not act -- fail-closed by design, an outage in fact
        # (CBP; the timer was stopped by hand, #944). The preflight's question is "after this
        # install, can this seat still stop this timer?", and the seat runs under what its
        # LAUNCHER supplies: the assignments on its registered hook line. So: the deploy's
        # locator is stripped, the launcher's assignments are applied, and a candidate that
        # cannot act under them is refused -- with the candidate's own reason on the row.
        # (Since 2026-10-06 "the registered hook line" is the RENDERED one, above: the deploy
        # unit's HESTIA_HOME reaches the probe only by being rendered onto that line, which is
        # exactly how it reaches the seat.)
        environment = {k: v for k, v in os.environ.items() if k != BOOTSTRAP_LOCATOR}
        environment.update(_launcher_env(commands, entry))
        environment.update(declared_env)
        environment.update({"HESTIA_ENDPOINT": endpoint, "HESTIA_WORKSPACE": workspace_text})
        # THE PROBE DECLARES THE TIMEOUT IT ENFORCES (one-gate stage C). A candidate gate bounds
        # its decision by the timeout its harness REALLY enforces, read from the registration —
        # and this probe is not the harness: it runs the candidate from the tree, under its own
        # subprocess timeout below. A non-harness invoker declares that bound; when the candidate
        # also finds a registration of itself, the smaller wins, so this can only shorten it.
        environment["HESTIA_HOOK_TIMEOUT_S"] = str(PROBE_TIMEOUT_S)
        # THE CANDIDATE GATE IS PROBED AGAINST THE CANDIDATE ENGINE, not the installed one.
        # Since #742/#747 a seat loads shared law only from HESTIA_SHARED_DIR or the installed
        # $HESTIA_HOME/shared, with no fallback. The first cycle after #747 merged (CBP,
        # 2026-09-01T16:10Z) probed the new gate against the still-installed 3-module engine,
        # the gate correctly refused `no-shared-authority`, and the preflight read that as
        # "gate refuses a benign read" and blocked the very install that ships the module
        # the gate needed. Gate + stale engine is a pairing that never exists after install;
        # gate + the reviewed tree about to be installed is the one that will. This is the
        # explicit dev/test selection the loader allows, naming the exact tree under test.
        environment["HESTIA_SHARED_DIR"] = str(repo / "plugins" / "_shared")
        # ...and for a candidate that CONSUMES the vault projection the pin above is not
        # enough: the projection overrides it at import. Probe under a throwaway seat home
        # whose projection names the candidate engine (#1171). The projection is keyed by the
        # SEAT id the gate loads (`install.member`: kimi's plugin dir is `kimi`, its seat and
        # projection are `kimi-code`), not by the plugin directory. Keyed by the directory, the
        # kimi lookup missed, the probe kept the real home, and the candidate was paired with the
        # INSTALLED engine -- the #1171 failure again, for the one member whose names differ.
        seat = install.get("member") if isinstance(install.get("member"), str) else member
        throwaway = _throwaway_seat_home(seat, environment, homes)
        if throwaway is not None:
            environment[BOOTSTRAP_LOCATOR] = str(throwaway)

        for declared in events:
            if not isinstance(declared, dict):
                rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe event"})
                good = False
                break
            label = declared.get("label")
            event = declared.get("event")
            if not isinstance(label, str) or not isinstance(event, dict):
                rows.append({"member": member, "status": "unmeasured", "reason": "invalid probe event"})
                good = False
                break
            rendered = _render(event, {"{scratch}": scratch, "{hold}": hold})
            try:
                completed = subprocess.run(
                    [sys.executable, str(candidate)],
                    input=json.dumps(rendered),
                    text=True,
                    capture_output=True,
                    cwd=repo,
                    env=environment,
                    timeout=PROBE_TIMEOUT_S,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                rows.append({"member": member, "probe": label, "status": "refused", "reason": "timeout"})
                good = False
                continue
            if completed.returncode != 0 or _payload_denies(completed.stdout):
                reason = (
                    f"candidate exited {completed.returncode}"
                    if completed.returncode != 0
                    else "candidate returned denial payload"
                )
                # THE CANDIDATE'S OWN WORDS, on the row. "candidate exited 2" tells an operator
                # nothing about which of the gate's refusals fired -- and since #959 one of them
                # is "your launcher does not supply the locator", which the operator repairs in a
                # different place than a law refusal. Last stderr line, bounded.
                said = [line.strip() for line in (completed.stderr or "").splitlines() if line.strip()]
                if said:
                    reason += ": " + said[-1][:200]
                # ADVISORY (#767): a probe may be declared advisory when it asserts a right the
                # law has not granted. The deploy-hold probe is one: no seat's scope admits a
                # write to $HESTIA_HOME/deploy.hold, so from #729's first cycle every member
                # gate refused it and the members' install was blocked fleet-wide, on a probe
                # nobody had run against the gate before shipping it. An advisory refusal is
                # still a row in deploy.log every cycle, so the observation is kept; it no
                # longer decides whether hooks install. Whether members SHOULD hold the deploy
                # is a ruling for the law, and when it lands the flag comes off.
                if declared.get("advisory") is True:
                    rows.append({"member": member, "probe": label,
                                 "status": "advisory-refused", "reason": reason})
                    continue
                rows.append({"member": member, "probe": label, "status": "refused", "reason": reason})
                good = False
            else:
                rows.append({"member": member, "probe": label, "status": "ok"})

    return rows, good


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--workspace", type=Path,
                        help="workspace that contains the hestia checkout (defaults to repo parent)")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--hold", required=True)
    parser.add_argument("--exclude-member", action="append", default=[])
    args = parser.parse_args(argv)

    rows, good = run_probes(
        args.repo.resolve(), args.home.expanduser(), args.endpoint, args.scratch, args.hold,
        set(args.exclude_member), args.workspace,
    )
    for row in rows:
        # This enters deploy.log. Keep it useful without leaking local paths or hook stderr.
        detail = f" ({row['reason']})" if row.get("reason") else ""
        probe = f" {row['probe']}" if row.get("probe") else ""
        print(f"gate-preflight {row['status']} {row['member']}{probe}{detail}")
    return 0 if good else 4


if __name__ == "__main__":
    raise SystemExit(main())
