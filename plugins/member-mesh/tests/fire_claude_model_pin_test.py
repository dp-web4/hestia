#!/usr/bin/env python3
"""fire-claude.sh pins the fired session's model, and names the machine it runs on.

WHY (sprout, 2026-10-14). Two lines in the template were written for the one seat that
ran it:

  1. `claude -p` passed no --model, so a wake ran on whatever the interactive Claude Code
     default was that day. hub-watch.sh had the identical gap and dead-lettered its
     notices `quota-paused` when that default ran out of credits. dp: "it should be pinned
     to fleet-defined model, currently opus-5-5".
  2. The prompt said "You are Claude (claude-code) on CBP". Enabling the watcher on sprout
     would have told every sprout wake it was on CBP, and a fired session signs its git
     acts <machine>-<model> from what it is told (fleet rule 2026-09-02).

Behavioural, against the real script with a stubbed `claude` that records its argv —
the same harness shape as fire_sender_allowlist_test.py.

  M1. Unset HESTIA_FIRE_CLAUDE_MODEL -> `--model claude-opus-5-5`.
  M2. Set to a model id -> `--model <that id>`.
  M3. Set to empty -> no --model at all (the CLI default; the old behaviour, on purpose).
  M4. The prompt is still the LAST argument (every template's contract) in all three.
  H1. The prompt names this host's short name by default.
  H2. HESTIA_FIRE_HOST overrides it, and "on CBP" is gone unless the host IS CBP.

Usage: ./fire_claude_model_pin_test.py     (runtime ~2s)
"""
import json
import os
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def fire(tmp, **env_overrides):
    """Run the real fire-claude.sh on one fireworthy notice; return (rc, argv list)."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    argfile = os.path.join(tmp, "argv.json")
    stub = os.path.join(bindir, "claude")
    with open(stub, "w") as f:
        f.write('#!/usr/bin/env python3\nimport json, sys\n'
                f'json.dump(sys.argv[1:], open({argfile!r}, "w"))\n')
    os.chmod(stub, 0o755)
    src = os.path.join(tmp, "notice-test.json")
    with open(src, "w") as f:
        json.dump({"notices": [{"id": 1, "kind": "reply", "from_plugin": "kimi-code",
                                "to_plugin": "claude-code", "pointer_uri": "shared-context/x.md",
                                "queued_at": "2026-10-14T00:00:00Z"}],
                   "unanswered": {}}, f)
    env = {k: v for k, v in os.environ.items()
           if k not in ("HESTIA_FIRE_CLAUDE_MODEL", "HESTIA_FIRE_HOST")}
    env["HOME"] = tmp
    env["HESTIA_MESH_LOCK_DIR"] = os.path.join(tmp, "locks")
    env["HESTIA_FIRE_LOCK_WAIT"] = "10"
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    env.update(env_overrides)
    r = subprocess.run([os.path.join(MESH, "fire-claude.sh"), src], env=env,
                       capture_output=True, text=True)
    argv = json.load(open(argfile)) if os.path.exists(argfile) else None
    return r, argv


def model_of(argv):
    if not argv or "--model" not in argv:
        return None
    i = argv.index("--model")
    return argv[i + 1] if i + 1 < len(argv) else ""


cases = (
    ("M1. unset -> the fleet model", {}, "claude-opus-5-5"),
    ("M2. set -> that model", {"HESTIA_FIRE_CLAUDE_MODEL": "claude-sonnet-5-5"}, "claude-sonnet-5-5"),
    ("M3. empty -> no --model (CLI default)", {"HESTIA_FIRE_CLAUDE_MODEL": ""}, None),
)
for label, env, want in cases:
    with tempfile.TemporaryDirectory() as tmp:
        r, argv = fire(tmp, **env)
        check(f"{label}: the CLI was fired", argv is not None,
              f"rc={r.returncode} stderr={r.stderr[-600:]!r}")
        check(f"{label}: --model is {want!r}", model_of(argv) == want, f"argv={argv!r}")
        check(f"{label}: --model appears at most once",
              (argv or []).count("--model") <= 1, f"argv={argv!r}")
        check(f"M4. {label}: the prompt is still the last argument",
              bool(argv) and argv[-1].startswith("You are Claude (claude-code) on "),
              f"last={(argv or [''])[-1][:120]!r}")

host = socket.gethostname().split(".")[0]
with tempfile.TemporaryDirectory() as tmp:
    r, argv = fire(tmp)
    prompt = (argv or [""])[-1]
    check("H1. the prompt names this host by default",
          prompt.startswith(f"You are Claude (claude-code) on {host}, woken"),
          f"host={host!r} prompt={prompt[:120]!r}")
with tempfile.TemporaryDirectory() as tmp:
    r, argv = fire(tmp, HESTIA_FIRE_HOST="sprout")
    prompt = (argv or [""])[-1]
    check("H2. HESTIA_FIRE_HOST overrides the host name",
          prompt.startswith("You are Claude (claude-code) on sprout, woken"),
          f"prompt={prompt[:120]!r}")
    check("H2. a sprout wake is not told it is on CBP", " on CBP," not in prompt,
          f"prompt={prompt[:120]!r}")

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
