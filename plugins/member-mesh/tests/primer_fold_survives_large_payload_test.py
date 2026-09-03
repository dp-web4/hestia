#!/usr/bin/env python3
"""The primer's debt fold must survive a fold larger than one environment string.

WHAT WAS WRONG. `hestia-watch-member.sh` composed the primer by handing the whole
`hestia_member_unanswered` result to an interpreter through a single environment
variable. A single environment string is capped by the kernel at MAX_ARG_STRLEN --
32 pages, 131,072 bytes on a 4KiB-page host. Measured on CBP 2026-09-03 the live fold
for `claude-code` was 362,244 bytes, 2.76x the cap, so `execve` failed E2BIG and the
composition interpreter NEVER STARTED. The shell fell through to
`|| echo "$OUT" > "$PRIMER"` and wrote the raw drain response.

WHY IT MATTERED MORE THAN A MISSING FOLD. That interpreter is the only writer of
THREE keys: `unanswered`, `open_petitions` and `for_plugin`. `for_plugin` was added
by 3fc5088 to fix seven primers nobody could attribute, and its own comment says it is
stamped OUTSIDE the fold "on purpose... an owner that only survives the happy path
re-creates exactly them". Source order is no protection when the failure is at exec:
the remedy re-created exactly those primers, 319 times on the claude seat alone.
A member in this state is told nothing about its debt, and a missing block renders as
NO DEBT -- it does not fail loud, which is why it ran for 15 days unnoticed.

WHY A CAP IS NOT THE FIX. The payload is 84% `owed_to_me`, and 691 of 780 such rows
had never been drained -- invitations to roster ids that never drain (#541). Every
escalation mints more, and the list has no shrink path. The quantity is monotonic, so
any byte cap is a date, not a fix. The channel is the fix.

WHAT THIS TEST PINS. Not that the source line exists -- an existence pin over a
constant certifies nothing, and is exactly what would have passed green for 15 days
here. This runs the real composition step from the real script against a fold that is
DELIBERATELY over the cap, and asserts the composed primer actually carries the keys.
The sabotage arm re-introduces the environment channel and must go RED.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "hestia-watch-member.sh")
LIMIT = 131072  # MAX_ARG_STRLEN


def _fold(nbytes):
    """A syntactically real unanswered fold padded past `nbytes`."""
    rows, i = [], 0
    while len(json.dumps({"i_owe": [], "owed_to_me": rows})) < nbytes:
        rows.append({
            "id": 9000 + i,
            "kind": "review_request",
            "from_plugin": "claude-code",
            "to_plugin": "a-completely-different-impostor",
            "drained_at": None,
            "queued_at": "2026-09-02T18:51:48.200691044Z",
            "pointer_uri": "hestia://escalation/%016x#corroborate-or-dissent" % (i * 2654435761),
        })
        i += 1
    return {"i_owe": [], "owed_to_me": rows}


def _composition_source():
    """Lift the python composition body out of the shell script verbatim."""
    src = open(SCRIPT, encoding="utf-8").read()
    # Channel-AGNOSTIC on purpose. If this only matched the fixed spelling, an
    # unpatched script would fail with "anchor missing" -- red under the wrong
    # check's name, which reads as a broken test rather than a live defect. Match
    # either channel so the delivery assertions below are what actually goes red.
    m = re.search(r"printf '%s' \"\$OUT\" \| UN(?:_FILE)?=[^\n]*python3 -c '\n(.*?)\n'\s*>",
                  src, re.S)
    if not m:
        raise AssertionError(
            "composition block not found -- if it was refactored, RE-ANCHOR this test "
            "rather than deleting it; the defect it pins is a delivery failure, not a line"
        )
    return m.group(1)


class PrimerFoldSurvivesLargePayload(unittest.TestCase):

    def setUp(self):
        self.body = _composition_source()
        self.fold = _fold(int(LIMIT * 1.5))
        self.blob = json.dumps(self.fold)
        self.assertGreater(len(self.blob), LIMIT,
                           "test fold must exceed MAX_ARG_STRLEN or it pins nothing")
        self.drain = json.dumps({"evicted": 0, "notices": [{"id": 1}], "peeked": 0, "total": 1})

    def _run(self, env):
        """Run the lifted body, feeding whichever channel that body actually reads.

        An UNPATCHED script therefore gets a 196KB `UN` in its environment and fails
        exactly the way production fails -- OSError E2BIG at exec -- rather than
        failing because a fixture was not wired. The assertion that goes red is a
        DELIVERY assertion either way.
        """
        env = dict(env)
        if "UN_FILE" not in self.body:
            env["UN"] = self.blob
        env.setdefault("PATH", os.getenv("PATH", "/usr/bin:/bin"))
        env.setdefault("FOR_PLUGIN", "claude-code")
        env.setdefault("PET", '{"asked":true,"mine":[]}')
        try:
            return subprocess.run([sys.executable, "-c", self.body], input=self.drain,
                                  capture_output=True, text=True, env=env)
        except OSError as exc:
            return exc

    def test_oversized_fold_is_delivered_and_the_primer_keeps_its_owner(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(self.blob)
            path = fh.name
        try:
            got = self._run({"UN_FILE": path})
            self.assertNotIsInstance(got, OSError,
                                     "composition could not even be exec'd with the fold on disk")
            self.assertEqual(got.returncode, 0, got.stderr)
            primer = json.loads(got.stdout)
            self.assertEqual(primer.get("for_plugin"), "claude-code",
                             "primer lost its owner -- this is the unattributable-primer defect")
            self.assertIn("open_petitions", primer)
            self.assertEqual(len(primer["unanswered"]["owed_to_me"]),
                             len(self.fold["owed_to_me"]),
                             "fold was truncated in transit")
        finally:
            os.unlink(path)

    def test_sabotage_the_environment_channel_is_red(self):
        """Re-introducing the env channel must fail -- the arm that was green for 15 days."""
        env_body = self.body.replace(
            'json.load(open(os.' + 'environ.get("UN_FILE") or "/dev/null"))',
            'json.loads(os.' + 'environ.get("UN") or "{}")')
        self.assertNotEqual(env_body, self.body,
                            "sabotage did not apply -- the arm is inert, fix the anchor")
        try:
            got = subprocess.run([sys.executable, "-c", env_body], input=self.drain,
                                 capture_output=True, text=True,
                                 env={"PATH": os.getenv("PATH", "/usr/bin:/bin"),
                                      "UN": self.blob, "FOR_PLUGIN": "claude-code",
                                      "PET": '{"asked":true,"mine":[]}'})
            self.assertNotEqual(got.returncode, 0,
                                "an oversized fold went through the environment -- "
                                "either the cap moved or the sabotage missed")
        except OSError as exc:
            self.assertEqual(exc.errno, 7, "expected E2BIG from the environment channel")

    def test_a_non_dict_fold_degrades_instead_of_killing_composition(self):
        """`null` parses fine and then dies on .get -- an exit-0 failure the shell cannot see."""
        for bad in ("null", "[]", '"x"', "0"):
            with self.subTest(fold=bad):
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                    fh.write(bad)
                    path = fh.name
                try:
                    got = self._run({"UN_FILE": path})
                    self.assertEqual(got.returncode, 0,
                                     "a %s fold took the whole composition down" % bad)
                    primer = json.loads(got.stdout)
                    self.assertEqual(primer.get("for_plugin"), "claude-code")
                    self.assertEqual(primer["unanswered"], {"i_owe": [], "owed_to_me": []})
                finally:
                    os.unlink(path)


if __name__ == "__main__":
    unittest.main()
