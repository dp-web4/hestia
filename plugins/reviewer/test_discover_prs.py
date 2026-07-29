#!/usr/bin/env python3
"""Tests for the attribution probe. Network-free: `python3 -m unittest` from this directory.

WHY THIS FILE EXISTS. Two guards in `discover_prs.py` have now been found never to have
fired — `^claude\\s` against a capture that stops at the space, and then the exact-match set
against `GPT-5`. Both were written, both read correctly to a reviewer, and neither was ever
executed against the string shapes it claimed to handle. A third round of "it looks right"
is not a fix; a case table that runs is. Each case below is a shape the record can actually
produce, not a shape the guard's author had in mind.
"""
import unittest

import discover_prs as d


class ModelNotMember(unittest.TestCase):
    """A model name carries no attribution. A member id does."""

    def test_bare_family_names_are_models(self):
        for token in ("Claude", "claude", "Kimi", "opus", "gemini", "noreply", "anthropic"):
            with self.subTest(token=token):
                self.assertTrue(d._is_model_not_member(token))

    def test_versioned_model_names_are_models(self):
        # The residual kimi-code caught on 426de31: these matched nothing in the set, so
        # the guard PASSED them and the caller attributed a PR to a member named "GPT-5".
        for token in ("GPT-5", "gpt-4o", "gemini-2.5", "claude-opus-5", "Claude-Opus-5",
                      "claude-4.5-sonnet", "claude-v3"):
            with self.subTest(token=token):
                self.assertTrue(d._is_model_not_member(token))

    def test_a_bare_version_is_not_an_id(self):
        self.assertTrue(d._is_model_not_member("5"))

    def test_member_ids_survive(self):
        # `claude-code` shares its first token with a model and MUST still resolve; that is
        # the whole reason the rule is per-token rather than substring.
        for token in ("claude-code", "kimi-code", "codex-cli", "agent-inventory", "thor",
                      "opus-agent"):
            with self.subTest(token=token):
                self.assertFalse(d._is_model_not_member(token))


class AuthorMember(unittest.TestCase):
    """The predicate is only half of it — these run the caller, with the network stubbed."""

    def setUp(self):
        self._gh = d.gh
        d.gh = lambda *a, **k: ""  # commit path empty, so the body path is what is exercised

    def tearDown(self):
        d.gh = self._gh

    def test_model_trailers_are_discarded_not_attributed(self):
        for body in ("Co-Authored-By: GPT-5 <noreply@openai.com>",
                     "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"):
            with self.subTest(body=body):
                self.assertEqual(d.author_member("hestia", 1, body), (None, "undetermined"))

    def test_web4_member_trailer_in_the_body(self):
        # kimi-code's B2: `Web4-Member:` lands in the PR body as often as in a commit.
        self.assertEqual(
            d.author_member("hestia", 1, "Web4-Member: kimi-code"), ("kimi-code", "body-trailer")
        )

    def test_signature_is_the_weakest_basis_and_is_labelled_as_such(self):
        self.assertEqual(
            d.author_member("hestia", 1, "text\n\n— claude-code\n"),
            ("claude-code", "body-signature"),
        )

    def test_no_attribution_reports_undetermined(self):
        self.assertEqual(d.author_member("hestia", 1, "nothing here"), (None, "undetermined"))


if __name__ == "__main__":
    unittest.main()
