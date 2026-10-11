#!/usr/bin/env python3
"""Non-executing literal-rule regressions for PR #1232 / notice 20536.

Same CLI and isolated-stub limits as scope-1232-shell-regressions.py.
The two *options-disqualify cases assert the documented rule exclusion;
other rejected cases assert a potentially out-of-scope reach is refused.
No represented shell command is executed.
"""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
path = Path(__file__).with_name("scope-1232-shell-regressions.py")
spec = importlib.util.spec_from_file_location("scope_regressions", path)
regressions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regressions)
regressions.CASES = [
    ('substitution-use-before-assignment', 'echo "$(cat $S/hostname)"; S=/tmp/review-probe', False),
    ('literal-field-splitting', 'S="/tmp/review-probe /etc"; cat $S/hostname', False),
    ('attached-printf-variable', 'S=/tmp/review-probe; printf -vS %s /etc; cat $S/hostname', False),
    ('attached-read-array', 'S=/tmp/review-probe; read -aS <<< /etc; cat $S/hostname', False),
    ('arithmetic-rebinding', 'S=/tmp; : $((S=0)); cat /$S/etc/hostname', False),
    ('combined-shell-code', "S=/tmp/review-probe; sh -ec 'cat /etc/hostname'; cat $S/x", False),
    ('shell-options-disqualify', 'S=/tmp/review-probe; bash --noprofile -c true; cat $S/x', False),
    ('combined-shell-options-disqualify', 'S=/tmp/review-probe; bash -lc true; cat $S/x', False),
    ('prefix-assignment', 'S=/tmp/review-probe cat $S/x', False),
    ('pipeline-left', 'S=/tmp/review-probe | true; cat $S/x', False),
    ('pipeline-right', 'true | S=/tmp/review-probe; cat $S/x', False),
    ('subshell-binding', '(S=/tmp/review-probe); cat $S/x', False),
    ('eval-rebinding', 'S=/tmp/review-probe; eval S=/tmp/other; cat $S/x', False),
    ('plain-shell-disqualify', 'S=/tmp/review-probe; sh -c true; cat $S/x', False),
    ('nameref-target', 'S=/tmp/review-probe; declare -n R=S; R=/tmp/other; cat $S/x', False),
    ('array-element', 'S=/tmp/review-probe; S[0]=/tmp/other; cat $S/x', False),
    ('array-compound', 'S=(/tmp/review-probe); cat $S/x', False),
    ('plain-use-before', 'cat $S/x; S=/tmp/review-probe', False),
    ('spaced-printf-variable', 'S=/tmp/review-probe; printf -v S %s /etc; cat $S/hostname', False),
    ('spaced-read-array', 'S=/tmp/review-probe; read -a S <<< /etc; cat $S/hostname', False),
    ('direct-forbidden', 'S=/etc; cat $S/hostname', False),
    ('simple-allow', 'S=/tmp/review-probe; cat $S/x', True),
    ('and-allow', 'S=/tmp/review-probe && cat "${S}/x"', True),
    ('newline-allow', 'S=/tmp/review-probe\ncat $S/x', True),
    ('later-substitution-allow', 'S=/tmp/review-probe; echo "$(cat $S/x)"', True),
    ('quoted-whitespace-allow', 'S="/tmp/review-probe /etc"; cat "$S/hostname"', True),
]

if __name__ == "__main__":
    sys.exit(regressions.main())
