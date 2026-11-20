#!/usr/bin/env python3
"""#551: real fire prompts render a measured budget, never an invented one."""

import json
import os
import shlex
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
CASES = (
    ("fire-claude.sh", "claude", "codex"),
    ("fire-codex.sh", "codex", "claude-code"),
    ("fire-kimi.sh", "kimi", "claude-code"),
)


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def fire(script, stub, peer, payload, usage_rc):
    with tempfile.TemporaryDirectory() as tmp:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        prompt = os.path.join(tmp, "prompt.txt")
        calls = os.path.join(tmp, "calls.txt")
        stub_path = os.path.join(bindir, stub)
        body = json.dumps(payload) if payload is not None else "not-json"
        with open(stub_path, "w", encoding="utf-8") as fh:
            fh.write(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = usage ]; then\n"
                f"  printf 'usage --json\\n' >> {shlex.quote(calls)}\n"
                f"  printf '%s' {shlex.quote(body)}\n"
                f"  exit {usage_rc}\n"
                "fi\n"
                "for a; do :; done\n"
                f"printf %s \"$a\" > {shlex.quote(prompt)}\n"
            )
        os.chmod(stub_path, 0o755)
        primer = os.path.join(tmp, "notice.json")
        with open(primer, "w", encoding="utf-8") as fh:
            json.dump({
                "notices": [{
                    "id": 1,
                    "kind": "review_request",
                    "from_plugin": peer,
                    "pointer_uri": "hestia://scope/scope-test#peer-decide",
                }],
                "unanswered": {},
            }, fh)
        env = dict(os.environ)
        env["HOME"] = tmp
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        env["HESTIA_MESH_LOCK_DIR"] = os.path.join(tmp, "locks")
        env["HESTIA_FIRE_LOCK_WAIT"] = "10"
        result = subprocess.run(
            [os.path.join(MESH, script), primer],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        check(f"{script}: fire succeeds", result.returncode == 0,
              f"rc={result.returncode} stdout={result.stdout} stderr={result.stderr}")
        with open(prompt, encoding="utf-8") as fh:
            rendered = fh.read()
        with open(calls, encoding="utf-8") as fh:
            probes = fh.read().splitlines()
        check(f"{script}: one quota probe per fire", probes == ["usage --json"], probes)
        return rendered


for script, stub, peer in CASES:
    prompt = fire(script, stub, peer, {"remaining_percent": 11, "window": "weekly"}, 0)
    check(f"{script}: valid quota reaches the real prompt",
          "budget: ~11% weekly remaining" in prompt, prompt[:500])
    prompt = fire(script, stub, peer, None, 1)
    check(f"{script}: unsupported quota output is absent",
          "budget: ~" not in prompt, prompt[:500])

print(f"OK — valid and absent budget rendering for {len(CASES)} vendors, one probe per fire")
