#!/usr/bin/env python3
"""The identifier exception reaches every Web/MCP egress leaf (#1275).

These are text-classifier tests, not evidence of OS read confinement. A filename
can also look like an identifier; this matcher does not distinguish the two.
"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "_shared"))
import hestia_single_gate as gate


def events(text):
    for tool in ("WebSearch", "WebFetch", "web_fetch", "google_web_search"):
        for key in ("url", "urls", "prompt", "query"):
            yield gate.GateEvent(tool, {key: [text] if key == "urls" else text})
    for key in ("command", "args", "url", "cwd"):
        value = [text] if key == "args" else text
        yield gate.GateEvent("mcp__example__read", {"_hestia_mcp_context": {key: value}})


class EgressIdentifierTests(unittest.TestCase):
    def setUp(self):
        self.profile = gate.GateProfile("codex", None).core_profile()
        self.env = patch.dict(os.environ, {self.profile.forbidden_extra_env: ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def assert_egress(self, text, denied):
        for event in events(text):
            with self.subTest(text=text, tool=event.tool, payload=event.tool_input):
                result = gate._egress_precheck(SimpleNamespace(event=event), self.profile)
                if denied:
                    self.assertIsNotNone(result)
                    self.assertTrue(result.blocks)
                    self.assertEqual(result.rule, "egress.secret")
                    self.assertTrue(result.innate)
                else:
                    self.assertIsNone(result)

    def test_identifiers_are_not_egress_denials(self):
        for text in ("os.environ", "vllm.envs", "OS.ENVIRON", "os.environ and vllm.envs"):
            self.assert_egress(text, False)

    def test_path_spellings_still_deny(self):
        for text in (".env", "./.env", "a/.env", ".env.local", ".envrc",
                     "prod.env", "config.env", "https://example.invalid/.env"):
            self.assert_egress(text, True)

    def test_identifier_does_not_hide_another_occurrence(self):
        for text in ("os.environ .env", ".env os.environ", "os.environ prod.env",
                     "os.environ vllm.envs .env.local"):
            self.assert_egress(text, True)

    def test_separate_leaves_remain_independently_checked(self):
        for tool, payload in (
            ("WebSearch", {"query": "os.environ", "prompt": ".env"}),
            ("WebFetch", {"urls": ["os.environ", ".env"]}),
            ("mcp__example__read", {"_hestia_mcp_context": {"args": ["os.environ", ".env"]}}),
        ):
            with self.subTest(tool=tool):
                event = gate.GateEvent(tool, payload)
                result = gate._egress_precheck(SimpleNamespace(event=event), self.profile)
                self.assertIsNotNone(result)
                self.assertEqual(result.rule, "egress.secret")

    def test_non_dot_tokens_and_escaped_pattern_remain_denials(self):
        for text in ("credentials", "secrets", "a/.ssh/id_ed25519", r"\.env"):
            self.assert_egress(text, True)

    def test_operator_extra_tokens_keep_the_same_semantics(self):
        with patch.dict(os.environ, {self.profile.forbidden_extra_env: ".custom,privateword"}):
            self.assert_egress("pkg.customize", False)
            for text in (".custom", "prod.custom", "pkg.customize .custom", "aprivatewordb"):
                self.assert_egress(text, True)


if __name__ == "__main__":
    unittest.main()
