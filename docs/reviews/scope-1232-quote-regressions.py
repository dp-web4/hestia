"""Additional non-executing scope probes; reuse the independently published runner."""
import importlib.util
import sys
from pathlib import Path
sys.dont_write_bytecode = True
path = Path(__file__).with_name('scope-1232-shell-regressions.py')
spec = importlib.util.spec_from_file_location('review_runner', path)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
r.CASES = [
    ('dq-control', 'S="/tmp/review /etc"; cat "$S/hostname"', True),
    ('dq-brace-control', 'S="/tmp/review /etc"; cat "${S}/hostname"', True),
    ('empty-quote-before', 'S="/tmp/review /etc"; cat ""$S/hostname', False),
    ('mixed-refs', 'S="/tmp/review /etc"; cat "$S"$S/hostname', False),
    ('mixed-refs-reverse', 'S="/tmp/review /etc"; cat $S"$S/hostname"', False),
    ('substitution-unquoted', 'S="/tmp/review /etc"; echo "$(cat $S/hostname)"', False),
    ('substitution-quoted', 'S="/tmp/review /etc"; echo "$(cat "$S/hostname")"', True),
    ('substitution-before-quoted', 'echo "$(cat "$S/hostname")"; S="/tmp/review /etc"', False),
    ('quoted-assignment-word', '"S=/tmp/review"; cat "$S/etc/hostname"', False),
    ('quoted-assignment-name', '"S"=/tmp/review; cat "$S/etc/hostname"', False),
    ('escaped-assignment-name', '\\S=/tmp/review; cat "$S/etc/hostname"', False),
    ('quoted-assignment-equals', 'S"="/tmp/review; cat "$S/etc/hostname"', False),
    ('quoted-assignment-value-control', 'S="/tmp/review"; cat "$S/hostname"', True),
    ('shell-stdin-option', "bash -s ignored <<< 'cat /etc/hostname'", False),
    ('shell-stdin-input-option', "printf 'cat /etc/hostname' | bash -s ignored", False),
    ('shell-stdin-script-option', "bash -s /tmp/ignored <<< 'cat /etc/hostname'", False),
    ('shell-nonstdin-control', "bash /tmp/review-script <<< 'cat /etc/hostname'", True),
    ('shell-heredoc-override', "bash <<'EOF' <<< 'cat /etc/hostname'\ntrue\nEOF", False),
    ('find-clustered-shell', "find . -exec sh -ec 'cat /etc/hostname' \\;", False),
]
if __name__ == '__main__':
    sys.exit(r.main())
