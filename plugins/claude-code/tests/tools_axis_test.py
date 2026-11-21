#!/usr/bin/env python3
"""#760 stage 1: independent TOOLS/FILES axes, with TOOLS in shadow mode."""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SHARED = HERE.parents[1] / "_shared" if len(HERE.parents) > 1 else HERE
sys.path.insert(0, str(SHARED))
import hestia_gate_core as gate  # noqa: E402


class ToolsAxisTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = os.path.realpath(self.tmp.name)
        self.home = os.path.join(self.workspace, "hestia-home")
        os.makedirs(self.home)
        self.environ = mock.patch.dict(os.environ, {"HESTIA_HOME": self.home})
        self.environ.start()
        self.profile = gate.HarnessProfile(member_id="acx", identity_path="")

    def tearDown(self):
        self.environ.stop()
        self.tmp.cleanup()

    def verdict(self, command, scope, tool="Bash", paths=None, tools_configured=False):
        event = gate.NormalizedEvent(
            tool=tool, command=command, cwd=self.workspace, paths=paths or [])
        policy = gate.AgentPolicy(member_id="acx", scope=tuple(scope),
                                  tools_configured=tools_configured)
        return gate.evaluate(event, self.profile, self.workspace, policy)

    def resolve_with_stale_replica(self, files, tools):
        identity = os.path.join(self.workspace, "identity.json")
        with open(identity, "w", encoding="utf-8") as fh:
            json.dump({"mrh": {
                "in_scope": ["repo:retired"],
                "replica": {"generation": 1, "expires_at": gate.now_secs() + 3600},
            }}, fh)
        self.profile = gate.HarnessProfile(member_id="acx", identity_path=identity)
        return gate.resolve_agent_policy(self.profile, lambda _member: {
            "in_scope": files,
            "generation": 2,
            "expires_at": gate.now_secs() + 3600,
            "allowlist": {"tools": tools},
        })

    def read_verdict(self, repo, policy):
        os.makedirs(os.path.join(self.workspace, repo), exist_ok=True)
        path = os.path.join(self.workspace, repo, "file.txt")
        with open(path, "a", encoding="utf-8"):
            pass
        event = gate.NormalizedEvent(tool="Read", cwd=self.workspace, paths=[path])
        with mock.patch.object(gate, "_under_temp_root", return_value=False):
            return gate.evaluate(event, self.profile, self.workspace, policy)

    def shadow_rows(self):
        path = os.path.join(self.home, gate.ALLOWLIST_SHADOW_RELPATH)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    def assert_shadow(self, command, scope, target=None, tool="Bash", paths=None):
        verdict = self.verdict(command, scope, tool=tool, paths=paths)
        self.assertEqual(verdict.decision, "allow")
        rows = self.shadow_rows()
        self.assertTrue(rows)
        row = rows[-1]
        self.assertEqual(row["mode"], "shadow")
        self.assertEqual(row["would_deny"], target is not None)
        if target is not None:
            self.assertEqual(row["rule"], "mrh.tool")
            self.assertEqual(row["target"], target)
        return row

    def test_legacy_policy_without_tool_entries_is_unchanged(self):
        self.assertEqual(self.verdict("git status", []).decision, "allow")
        self.assertEqual(self.verdict("python3 -c 'print(1)'", []).decision, "allow")
        self.assertEqual(self.shadow_rows(), [])

    def test_explicit_empty_tools_axis_is_distinct_from_legacy_absence(self):
        legacy = gate.resolve_agent_policy(self.profile, lambda _member: {"in_scope": []})
        self.assertFalse(legacy.tools_configured)
        policy = gate.resolve_agent_policy(
            self.profile,
            lambda _member: {"in_scope": [], "allowlist": {"tools": []}})
        self.assertTrue(policy.tools_configured)
        event = gate.NormalizedEvent(
            tool="Bash", command="git status", cwd=self.workspace, paths=[])
        self.assertEqual(gate.evaluate(event, self.profile, self.workspace, policy).decision,
                         "allow")
        rows = self.shadow_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["grants"], [])
        self.assertTrue(rows[0]["would_deny"])
        self.assertEqual(rows[0]["target"], "git")

    def test_nonempty_allowlist_tools_feed_effective_grants(self):
        for entries in (["python3"], [{"value": "python3"}]):
            with self.subTest(entries=entries):
                policy = gate.resolve_agent_policy(
                    self.profile,
                    lambda _member: {"in_scope": [], "allowlist": {"tools": entries}})
                self.assertTrue(policy.tools_configured)
                self.assertEqual(gate._tool_grants(policy.scope), frozenset({"python3"}))
                for command, would_deny, target in (
                        ("python3 -V", False, ""), ("git status", True, "git")):
                    event = gate.NormalizedEvent(
                        tool="Bash", command=command, cwd=self.workspace, paths=[])
                    verdict = gate.evaluate(event, self.profile, self.workspace, policy)
                    self.assertEqual(verdict.decision, "allow")
                    row = self.shadow_rows()[-1]
                    self.assertEqual(row["grants"], ["python3"])
                    self.assertEqual(row["would_deny"], would_deny)
                    self.assertEqual(row["target"], target)

    def test_malformed_tools_preserve_current_files_and_block_stale_widening(self):
        for tools in (["git status"], [""], [{}], [[]], [None], "python3"):
            with self.subTest(tools=tools):
                policy = self.resolve_with_stale_replica(["repo:current"], tools)
                self.assertEqual(policy.source, "vault")
                self.assertEqual(policy.generation, 2)
                self.assertIn("current", policy.scope)
                self.assertNotIn("retired", policy.scope)
                self.assertEqual(self.read_verdict("current", policy).decision, "allow")
                revoked = self.read_verdict("retired", policy)
                self.assertEqual(revoked.decision, "deny")
                self.assertEqual(revoked.rule, "mrh.path")

    def test_tools_parser_exception_cannot_discard_vault_files(self):
        with mock.patch.object(gate, "_parse_allowlist_tools", side_effect=ValueError("bad")):
            policy = self.resolve_with_stale_replica(["repo:current"], [])
        self.assertEqual(policy.source, "vault")
        self.assertEqual(policy.scope, ("current",))
        self.assertEqual(policy.generation, 2)
        self.assertEqual(self.read_verdict("current", policy).decision, "allow")
        revoked = self.read_verdict("retired", policy)
        self.assertEqual(revoked.decision, "deny")
        self.assertEqual(revoked.rule, "mrh.path")

    def test_scope_parser_preserves_tool_entries(self):
        self.assertEqual(gate._parse_scope_entries(["tool:python3"]), ("tool:python3",))

    def test_command_head_grant_shadows_only_that_head(self):
        scope = ["tool:python3"]
        self.assert_shadow("python3 -c 'print(1)'", scope)
        self.assert_shadow("git status", scope, "git")

    def test_tool_entry_is_not_a_filesystem_grant(self):
        with tempfile.NamedTemporaryFile(dir=self.workspace) as ordinary, \
                mock.patch.object(gate, "_under_temp_root", return_value=False):
            denied = self.verdict(None, ["tool:Read"], tool="Read", paths=[ordinary.name])
            self.assertEqual(denied.rule, "mrh.path")
            allowed = self.verdict(None, ["tool:Read", f"path:{self.workspace}/**"],
                                   tool="Read", paths=[ordinary.name])
            self.assertEqual(allowed.decision, "allow")

    def test_every_executable_position_is_measured(self):
        scope = ["tool:python3", "tool:git"]
        self.assert_shadow("python3 -c 'print(1)' && git status", scope)
        self.assert_shadow("python3 -c 'print(1)' && rg --files", scope, "rg")

    def test_harness_tool_and_shell_head_are_distinct(self):
        self.assert_shadow("python3 -c 'print(1)'", ["tool:python3"])
        self.assert_shadow("git status", ["tool:python3"], "git")
        self.assert_shadow("git status", ["tool:Bash"])

    def test_file_grant_does_not_authorize_a_different_verb(self):
        with tempfile.NamedTemporaryFile(dir=self.workspace) as ordinary:
            read = self.verdict(None, ["tool:Read", f"path:{self.workspace}/**"],
                                tool="Read", paths=[ordinary.name])
            self.assertEqual(read.decision, "allow")
            self.assert_shadow("git status", ["tool:python3", f"path:{self.workspace}/**"], "git")

    def test_quoted_data_is_not_an_executable_position(self):
        self.assert_shadow("echo 'ci python test step'", ["tool:echo"])
        self.assert_shadow("git status", ["tool:echo"], "git")

    def test_substitutions_reveal_their_command_heads(self):
        for command in ("echo $(python3 -V)", "echo `python3 -V`"):
            with self.subTest(command=command):
                self.assertEqual(gate._command_heads(command), (["echo", "python3"], None))
                self.assert_shadow(command, ["tool:echo"], "python3")

    def test_newlines_and_shell_keywords_are_not_command_heads(self):
        commands = (
            ("ls\npython3 -V", ["tool:ls", "tool:python3"]),
            ("if python3 -V; then echo ok; fi", ["tool:python3", "tool:echo"]),
            ("{ python3 -V; }", ["tool:python3"]),
            ("! python3 -V", ["tool:python3"]),
            ("f() { python3 -V; }", ["tool:python3"]),
        )
        for command, scope in commands:
            with self.subTest(command=command):
                self.assert_shadow(command, scope)

    def test_env_and_timeout_find_the_wrapped_executable(self):
        for command in ("env X=1 python3 -V", "env X+=1 python3 -V",
                        "timeout -s TERM 5 python3 -V", "timeout -- 5 python3 -V"):
            with self.subTest(command=command):
                self.assertEqual(gate._command_heads(command), (["python3"], None))
                self.assert_shadow(command, ["tool:python3"])

    def test_redirections_and_heredoc_delimiters_are_not_command_heads(self):
        cases = (
            ("> /dev/null python3 -V", "python3"),
            ("<in python3 -V", "python3"),
            ("cat <<EOF\nplain text\nEOF", "cat"),
            ("python3 <<'PY'\nprint('ok')\nPY", "python3"),
        )
        for command, head in cases:
            with self.subTest(command=command):
                self.assertEqual(gate._command_heads(command), ([head], None))
                self.assert_shadow(command, ["*", f"tool:{head}"])

    def test_nested_shell_and_eval_payloads_are_uncertainty(self):
        for command in ("sh -c 'python3 -V'", "bash -c 'python3 -V'",
                        "eval 'python3 -V'"):
            with self.subTest(command=command):
                heads, uncertainty = gate._command_heads(command)
                self.assertIsNotNone(uncertainty)
                self.assertIn("not modelled", uncertainty)
                self.assert_shadow(command, ["tool:sh", "tool:bash", "tool:eval"],
                                   gate._TOOL_OPAQUE)

    def test_arithmetic_is_uncertainty_not_an_executable_name(self):
        command = "x=1; ((x++)); python3 -V"
        heads, uncertainty = gate._command_heads(command)
        self.assertEqual(heads, [])
        self.assertIn("arithmetic", uncertainty)
        self.assert_shadow(command, ["tool:python3"], gate._TOOL_OPAQUE)

    def test_unmodelled_shell_is_explicit_uncertainty(self):
        for command in (
                "for x in a b; do echo $x; done",
                "sudo -u root python3 -V",
                "sh -c 'python3 -V'",
                "bash -c 'python3 -V'",
                "eval 'python3 -V'",
                "$PROGRAM -V",
                "echo 'unterminated"):
            with self.subTest(command=command):
                baseline = self.verdict(command, [])
                shadowed = self.verdict(
                    command, ["tool:echo", "tool:sh", "tool:bash", "tool:eval"])
                self.assertEqual(shadowed.decision, baseline.decision)
                self.assertEqual(shadowed.rule, baseline.rule)
                row = self.shadow_rows()[-1]
                self.assertTrue(row["would_deny"])
                self.assertEqual(row["target"], gate._TOOL_OPAQUE)

    def test_non_bash_tool_denial_is_shadow_only(self):
        with tempfile.NamedTemporaryFile(dir=self.workspace) as ordinary:
            self.assert_shadow(None, ["tool:Read", f"path:{self.workspace}/**"],
                               "Edit", tool="Edit", paths=[ordinary.name])

    def test_telemetry_failure_cannot_change_the_verdict(self):
        with mock.patch.object(gate, "record_allowlist_shadow", return_value=False):
            self.assertEqual(self.verdict("git status", ["tool:python3"]).decision, "allow")
        with mock.patch.object(gate, "_tool_shadow_verdict", side_effect=RuntimeError):
            self.assertEqual(self.verdict("git status", ["tool:python3"]).decision, "allow")
            self.assertEqual(self.shadow_rows()[-1]["target"], gate._TOOL_OPAQUE)
        self.assertFalse(gate.record_allowlist_shadow(
            "acx", "Bash", frozenset({"python3"}), None,
            home="/proc/nonexistent/cannot/write"))


if __name__ == "__main__":
    unittest.main()
