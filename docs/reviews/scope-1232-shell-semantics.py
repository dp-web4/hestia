"""Harmless shell semantics checks: prints arguments, never reads target paths."""
import json
import os
import subprocess
import tempfile

cases = {
    'quoted-word': '"S=/tmp/review"; printf "<%s>\\n" "$S/etc/hostname"',
    'quoted-name': '"S"=/tmp/review; printf "<%s>\\n" "$S/etc/hostname"',
    'escaped-name': '\\S=/tmp/review; printf "<%s>\\n" "$S/etc/hostname"',
    'quoted-equals': 'S"="/tmp/review; printf "<%s>\\n" "$S/etc/hostname"',
    'stdin-option': "bash -s ignored <<< 'printf \"<%s>\\n\" /etc/hostname'",
    'stdin-option-script-looking': "bash -s /tmp/ignored <<< 'printf \"<%s>\\n\" /etc/hostname'",
    'stdin-pipe-option': "printf '%s' 'printf \"<%s>\\n\" /etc/hostname' | bash -s ignored",
    'heredoc-overridden': "bash <<'EOF' <<< 'printf \"<%s>\\n\" /etc/hostname'\ntrue\nEOF",
    'find-clustered-shell': "find . -maxdepth 0 -exec sh -ec 'printf \"<%s>\\n\" /etc/hostname' \\;",
}
with tempfile.TemporaryDirectory(prefix='scope-semantics-') as root:
    # Minimal environment: no user startup, functions, or bindings inherited.
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
    for label, script in cases.items():
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script],
            cwd=root, env=env, text=True, capture_output=True, timeout=5)
        ok = result.returncode == 0 and result.stdout == '</etc/hostname>\n'
        print(json.dumps({'case': label, 'exit': result.returncode,
                          'printed': result.stdout.strip(), 'passed': ok}), flush=True)
        assert ok, result
