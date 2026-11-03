import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.environ["HESTIA_REVIEW_ROOT"]
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "plugins", "_shared"))

import grant_modes_gate_test as g
import hestia_single_gate as single


class PathRemoteProvenanceProbe(unittest.TestCase):
    def remote(self, ws, full, tool="mcp__github__fetch_pr"):
        return single.normalized_event(single.GateEvent(
            tool=tool, tool_input={"repository_full_name": full}, cwd=ws))

    def test_current_projection_crosses_path_and_remote_domains(self):
        with g._Workspace() as ws:
            rows = []
            for standing in ([], [{"path": ws + "/project", "recursive": True}]):
                snap = g._snapshot(ws, standing=standing)
                prof, pol = g._policy(snap)
                rows.append((standing, list(pol.scope)))
                for full in ("owner/project", "foreign/project"):
                    for tool in ("mcp__github__fetch_pr", "mcp__github__delete_file"):
                        verdict = g.core.evaluate(self.remote(ws, full, tool), prof, ws, policy=pol)
                        rows.append((bool(standing), full, tool, verdict.decision, verdict.rule))
                        self.assertEqual(verdict.blocks, not standing,
                                         f"{full} {tool}: {verdict}; scope={pol.scope}")
            print("CURRENT_PROJECTION_ROWS", rows)

    def test_literal_path_and_explicit_repository_controls(self):
        with g._Workspace() as ws:
            prof, _ = g._policy(g._snapshot(ws, standing=[]))
            path_pol = g.core.resolve_agent_policy(
                prof, vault_reader=lambda _member: {"in_scope": ["path:" + ws + "/project/**"]})
            for full in ("owner/project", "foreign/project"):
                verdict = g.core.evaluate(self.remote(ws, full), prof, ws, policy=path_pol)
                self.assertTrue(verdict.blocks)
                self.assertEqual(verdict.rule, "mrh.repo")

            for entry, full, blocked in (
                ("repo:owner/project", "owner/project", False),
                ("repo:owner/project", "foreign/project", True),
                ("project", "foreign/project", False),
            ):
                pol = g.core.resolve_agent_policy(
                    prof, vault_reader=lambda _member, entry=entry: {"in_scope": [entry]})
                verdict = g.core.evaluate(self.remote(ws, full), prof, ws, policy=pol)
                self.assertEqual(verdict.blocks, blocked, f"{entry} {full}: {verdict}")

    def test_path_only_hypothesis_preserves_local_boundary(self):
        def path_only(path, recursive=False):
            return "path:" + path.strip().rstrip("/") + ("/**" if recursive else "")

        with g._Workspace() as ws, patch.object(g.m, "_scope_entry_for_grant", path_only):
            inside = ws + "/project/file"
            outside = ws + "/other/file"
            g._materialize(inside)
            g._materialize(outside)
            prof, empty_pol = g._policy(g._snapshot(ws, standing=[]))
            empty = g._verdict(prof, empty_pol, ws, "Read", inside)
            self.assertTrue(empty.blocks)
            self.assertEqual(empty.rule, "mrh.path")

            snap = g._snapshot(ws, standing=[{"path": ws + "/project", "recursive": True}])
            prof, pol = g._policy(snap)
            self.assertEqual(list(pol.scope), ["path:" + ws + "/project/**"])
            self.assertFalse(g._verdict(prof, pol, ws, "Read", inside).blocks)
            self.assertTrue(g._verdict(prof, pol, ws, "Read", outside).blocks)
            for tool in ("mcp__github__fetch_pr", "mcp__github__delete_file"):
                verdict = g.core.evaluate(self.remote(ws, "foreign/project", tool), prof, ws, policy=pol)
                self.assertTrue(verdict.blocks)
                self.assertEqual(verdict.rule, "mrh.repo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
