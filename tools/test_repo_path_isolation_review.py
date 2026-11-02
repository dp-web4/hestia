"""Synthetic regression: local path reach must not imply foreign remote reach."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
