"""Synthetic regression: local path reach must not imply foreign remote reach."""
import unittest
from unittest.mock import patch

import grant_modes_gate_test as g
import hestia_single_gate as single


class RepoIsolation(unittest.TestCase):
    def test_recursive_path_does_not_grant_foreign_remote(self):
        with g._Workspace() as ws:
            for standing, should_block in (
                ([], True),
                ([{"path": ws + "/project", "recursive": True}], True),
            ):
                snap = g._snapshot(ws, standing=standing)
                prof, pol = g._policy(snap)
                for tool in ("mcp__github__fetch_pr", "mcp__github__delete_file"):
                    ev = single.normalized_event(single.GateEvent(
                        tool=tool, tool_input={"repository_full_name": "foreign/project"}, cwd=ws))
                    verdict = g.core.evaluate(ev, prof, ws, policy=pol)
                    with self.subTest(standing=standing, tool=tool):
                        self.assertEqual(verdict.blocks, should_block,
                                         f"{verdict}; scope={pol.scope}")

    def test_simulated_typed_path_projection_preserves_local_and_legacy_behavior(self):
        # A test-process-only hypothesis, not a modified or installed gate.
        def path_only(path, recursive=False):
            return "path:" + path.strip().rstrip("/") + ("/**" if recursive else "")

        with g._Workspace() as ws, patch.object(g.m, "_scope_entry_for_grant", path_only):
            snap = g._snapshot(ws, standing=[{"path": ws + "/project", "recursive": True}])
            prof, pol = g._policy(snap)
            local = g.core.NormalizedEvent(tool="Read", paths=[ws + "/project/file"])
            self.assertFalse(g.core.evaluate(local, prof, ws, policy=pol).blocks)
            for tool in ("mcp__github__fetch_pr", "mcp__github__delete_file"):
                ev = single.normalized_event(single.GateEvent(
                    tool=tool, tool_input={"repository_full_name": "foreign/project"}, cwd=ws))
                self.assertTrue(g.core.evaluate(ev, prof, ws, policy=pol).blocks)

            narrowed = g._snapshot(ws, by_mode=[g._grant(ws + "/project", "r")])
            narrow_prof, narrow_pol = g._policy(narrowed)
            for tool, blocked in (("Read", False), ("Write", True)):
                event = g.core.NormalizedEvent(tool=tool, paths=[ws + "/project/file"])
                self.assertEqual(g.core.evaluate(event, narrow_prof, ws, policy=narrow_pol).blocks,
                                 blocked, f"{tool}: {narrow_pol}")
            self.assertTrue(any(root.endswith("/project") and recursive and modes == "r"
                                for root, recursive, modes in g.core.scope_roots_with_modes(narrow_pol, ws)))

            # Separately granted legacy and qualified repository entries retain their old meaning.
            for entry, repo, blocked in (("project", "foreign/project", False),
                                          ("repo:owner/project", "owner/project", False),
                                          ("repo:owner/project", "foreign/project", True)):
                legacy = g.core.resolve_agent_policy(prof, vault_reader=lambda _, e=entry: {"in_scope": [e]})
                ev = single.normalized_event(single.GateEvent(
                    tool="mcp__github__fetch_pr", tool_input={"repository_full_name": repo}, cwd=ws))
                with self.subTest(entry=entry, repo=repo):
                    self.assertEqual(g.core.evaluate(ev, prof, ws, policy=legacy).blocks, blocked)

    def test_existing_mode_contracts_under_simulated_projection(self):
        def path_only(path, recursive=False):
            return "path:" + path.strip().rstrip("/") + ("/**" if recursive else "")
        with patch.object(g.m, "_scope_entry_for_grant", path_only):
            for name in sorted(n for n in vars(g) if n.startswith("test_") and callable(getattr(g, n))):
                with self.subTest(contract=name):
                    getattr(g, name)()


if __name__ == "__main__":
    unittest.main()
