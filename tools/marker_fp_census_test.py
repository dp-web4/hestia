#!/usr/bin/env python3
"""Pins for `marker_fp_census.py`. Every case here is a bug that shipped a WRONG NUMBER
rather than an error -- which is the only failure mode this corpus actually has."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from marker_fp_census import (tmp_only, disposition, reescalations, censored,
                              fisher_2x2, _acttext)

FAILS = []
def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r} want {want!r}")

def rec(reason, marker="plugins/_shared", tool="Bash", **kw):
    d = dict(id="x", at="2026-08-20T00:00:00+00:00", tool=tool, seat="s", marker=marker,
             reason=reason, digest="d", status="approved", decided=True, claimed=False)
    d.update(kw); return d

# 1. The act-text prefix is "Bash: cmd" WITH A COLON. Stripping "^\w+\s+" leaves a bare
#    ":" as the first token, which parses as the shell no-op builtin and silently turned
#    real writes into no-op segments. Cost: the /tmp class read 0 decidable rows.
check("colon prefix stripped", _acttext(rec("Bash: cat /tmp/plugins/_shared/f")),
      "cat /tmp/plugins/_shared/f")
check("no-colon prefix still stripped", _acttext(rec("Bash cat /tmp/plugins/_shared/f")),
      "cat /tmp/plugins/_shared/f")

# 2. `_segments()` returns SEGMENT STRINGS, not token lists. `for t in seg` iterates
#    CHARACTERS, so no token ever matched a multi-character marker and the class was
#    empty. An empty class printed as "0/0 = n/a", not as an error.
check("tmp class sees tokens, not chars",
      tmp_only(rec("Bash: cat /tmp/plugins/_shared/f")), True)
check("non-tmp marker token excludes",
      tmp_only(rec("Bash: cat /home/dp/plugins/_shared/f")), False)
check("mixed tmp and non-tmp is NOT in class",
      tmp_only(rec("Bash: cp /tmp/plugins/_shared/a /home/dp/plugins/_shared/b")), False)

# 3. Censored act text is NOT decidable. Scoring it either way is a guess, and the two
#    censors are seat-disjoint, so guessing biases the class BY SEAT.
check("redacted is undecidable", tmp_only(rec("Bash: [REDACTED - 800 chars withheld]")), None)
check("truncated is undecidable", tmp_only(rec("Bash: cat /tmp/x …[truncated]")), None)
check("redacted detected", censored("Bash: [REDACTED - x]"), "redacted")
check("truncated detected", censored("Bash: x …[truncated]"), "truncated")
check("intact detected", censored("Bash: cat /tmp/x"), None)

# 4. A marker that matches no tokenisable token is undecidable, NOT out-of-class --
#    otherwise the denominator silently absorbs every parse failure as a negative.
check("no marker hit is undecidable", tmp_only(rec("Bash: echo hello", marker="zzz")), None)

# 5. Re-escalation requires a DIFFERENT act_digest. An identical digest is a retry of
#    the same act, not a respelling, and counting it inflates the headline rate.
LONG = ("Bash: chmod +x /a/plugins/_shared/hestia_governance_closure.py && "
        "python3 -c 'import sys; print(sys.version)' && ls -la /a/plugins/_shared")
same = [rec(LONG, id="1", digest="D", at="2026-08-20T00:00:00+00:00"),
        rec(LONG, id="2", digest="D", at="2026-08-20T00:00:10+00:00")]
_, hits = reescalations(same, gap=1800, sim=0.9)
check("identical digest is not a respelling", len(hits), 0)
diff = [dict(same[0]), dict(same[1], digest="E",
             reason=LONG.replace("Bash: ", "Bash: sleep 80; "))]
_, hits = reescalations(diff, gap=1800, sim=0.9)
check("different digest at high similarity IS a respelling", len(hits), 1)

# 6. Records with NO digest are excluded from the DENOMINATOR, not scored negative --
#    act_digest is a vintage cutover (absent before 2026-08-25), so scoring its absence
#    as "did not re-escalate" mixes a recording change into a behaviour rate.
nodig = [rec("Bash: chmod +x /a/plugins/_shared/f", id="1", digest=None)]
scored, _ = reescalations(nodig, gap=1800, sim=0.9)
check("digestless row is not scorable", len(scored), 0)

# 7. Fisher against a known 2x2 (R fisher.test: 6/51 vs 31/43 -> ~1e-9).
p = fisher_2x2(6, 45, 31, 12)
check("fisher is in the right decade", p < 1e-8 and p > 1e-11, True)
check("fisher of a null table is 1.0", round(fisher_2x2(5, 5, 5, 5), 6), 1.0)

if FAILS:
    print("\n".join("FAIL " + f for f in FAILS)); sys.exit(1)
print("ok - 17 pins")
