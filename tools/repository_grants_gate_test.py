#!/usr/bin/env python3
"""Typed repository grants through the production snapshot, resolver and normalizer."""

import copy
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import grant_modes_gate_test as g
import hestia_single_gate as single


class RepositoryGrants(unittest.TestCase):
    def setUp(self):
        self.context = g._Workspace()
        self.ws = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        g.m._POLICY_SNAPSHOT_CACHE.clear()
        self.addCleanup(g.m._POLICY_SNAPSHOT_CACHE.clear)
        self.now = int(time.time())
        self.row = {
            "repo": "owner/project",
            "entry": "repo:owner/project",
            "modes": "r",
            "expires_at": None,
            "granted_by": "operator",
        }
        self.fake = g.mt._std_stub(self.ws, generation=7, horizon=self.now + 60)
        self.scope = self.fake.extra["hestia_scope_status"]
        self.scope["repository_grants"] = [self.row]
        g.m._discover_endpoint = lambda: "http://fake/mcp"
        g.m._McpHttp = lambda ep, dl: self.fake

    def policy(self, cached=False):
        snap = g.m.fetch_policy_snapshot("cbp-being", use_cache=cached)
        self.assertIsNotNone(snap)
        return g._policy(snap)

    def verdict(self, tool="mcp__github__fetch_pr", repo="owner/project", policy=None):
        prof, pol = policy or self.policy()
        ev = single.normalized_event(
            single.GateEvent(
                tool=tool, tool_input={"repository_full_name": repo}, cwd=self.ws
            )
        )
        return g.core.evaluate(ev, prof, self.ws, policy=pol)

    def test_read_owner_and_mode(self):
        self.assertFalse(self.verdict().blocks)
        for repo in ["other/project", "owner/other", "project"]:
            with self.subTest(repo=repo):
                self.assertTrue(self.verdict(repo=repo).blocks)
        for tool in [
            "mcp__github__create_pull_request",
            "mcp__github__delete_file",
            "mcp__github__run_workflow",
            "mcp__other__fetch_pr",
            "mcp__github__get_unknown",
        ]:
            with self.subTest(tool=tool):
                self.assertTrue(self.verdict(tool=tool).blocks)
        self.row["modes"] = "w"
        self.assertTrue(self.verdict().blocks)

    def test_full_and_narrowed_modes(self):
        for modes in ["r", "rw", "re", "rd", "rwe", "rwed"]:
            self.row["modes"] = modes
            with self.subTest(modes=modes):
                self.assertFalse(self.verdict().blocks)
                self.assertEqual(
                    self.verdict(tool="mcp__github__unknown_mutation").blocks,
                    modes != "rwed",
                )
        self.assertTrue(self.verdict(repo="other/project").blocks)

    def test_malformed_rows_grant_nothing(self):
        cases = [None, [], "repo:owner/project", {}, {"repo": "owner/project"}]
        for key, values in {
            "repo": ["owner/project\n", "../project", "owner/*", "owner/project/more"],
            "entry": ["repo:other/project", "path:/tmp/project", "*"],
            "modes": ["", "rx", None, True],
            "expires_at": [True, "future", self.now - 1],
        }.items():
            for value in values:
                row = copy.deepcopy(self.row)
                row[key] = value
                cases.append(row)
        for row in cases:
            with self.subTest(row=row):
                self.scope["repository_grants"] = [row]
                self.assertTrue(self.verdict().blocks)

    def test_repository_authority_never_enters_path_scope(self):
        for modes in ["r", "rwed"]:
            self.row["modes"] = modes
            prof, pol = self.policy()
            self.assertEqual(pol.mode_scope, ())
            self.assertNotIn("owner/project", pol.scope)
            ev = g.core.NormalizedEvent(
                tool="Read", paths=[self.ws + "/owner/project/private"]
            )
            self.assertTrue(g.core.evaluate(ev, prof, self.ws, policy=pol).blocks)

    def test_certification_and_expiry(self):
        for key, values in {
            "generation": [None, True, "7"],
            "snapshot_expires_at": [None, True, "later", self.now],
        }.items():
            original = self.scope[key]
            for value in values:
                self.scope[key] = value
                with self.subTest(key=key, value=value):
                    self.assertTrue(self.verdict().blocks)
            self.scope[key] = original
        pol = self.policy()
        with patch.object(g.core, "now_secs", return_value=self.now + 60):
            self.assertTrue(self.verdict(policy=pol).blocks)

    def test_row_expiry_is_checked_even_if_snapshot_horizon_is_later(self):
        self.row["expires_at"] = self.now + 10
        pol = self.policy()
        self.assertFalse(self.verdict(policy=pol).blocks)
        with patch.object(g.core, "now_secs", return_value=self.now + 10):
            self.assertTrue(self.verdict(policy=pol).blocks)

    def test_revocation_refetch_and_bounded_cache(self):
        cached = self.policy(cached=True)
        self.assertFalse(self.verdict(policy=cached).blocks)
        self.scope["repository_grants"] = []
        self.scope["generation"] = 8
        # Existing invocation remains certified until its horizon, not instantaneous revoke.
        self.assertFalse(self.verdict(policy=self.policy(cached=True)).blocks)
        refreshed = self.policy(cached=False)
        self.assertEqual(refreshed[1].generation, 8)
        self.assertTrue(self.verdict(policy=refreshed).blocks)
        with patch.object(g.core, "now_secs", return_value=self.now + 60):
            self.assertTrue(self.verdict(policy=cached).blocks)
        g.m._POLICY_SNAPSHOT_CACHE.clear()
        self.assertTrue(self.verdict(policy=self.policy(cached=True)).blocks)

    def test_legacy_explicit_grant_compatibility(self):
        self.scope["repository_grants"] = []
        self.fake.extra["hestia_operating_law"]["operator_grant"] = {
            "in_scope": ["repo:owner/project"]
        }
        # Compatibility tested directly at policy boundary; typed channel stays empty.
        prof = g.core.HarnessProfile(
            member_id="cbp-being", identity_path="/nonexistent/identity.json"
        )
        pol = g.core.resolve_agent_policy(
            prof, vault_reader=lambda _: {"in_scope": ["repo:owner/project"]}
        )
        self.assertFalse(self.verdict(policy=(prof, pol)).blocks)
        self.assertTrue(self.verdict(repo="other/project", policy=(prof, pol)).blocks)

    def test_normalizer_identity_shapes(self):
        prof, pol = self.policy()
        for key in ("repository_full_name", "repo_full_name", "repository", "repo"):
            for repo, blocks in (("owner/project", False), ("other/project", True)):
                with self.subTest(key=key, repo=repo):
                    ev = single.normalized_event(
                        single.GateEvent(
                            tool="mcp__github__fetch_pr",
                            tool_input={key: repo},
                            cwd=self.ws,
                        )
                    )
                    self.assertEqual(
                        g.core.evaluate(ev, prof, self.ws, policy=pol).blocks, blocks
                    )
        # Separate owner/repo and URLs are not currently supported identity shapes.
        # They must refuse rather than inferring qualified authority from a bare name.
        for data in (
            {"owner": "owner", "repo": "project"},
            {"repository": "https://github.com/owner/project"},
        ):
            ev = single.normalized_event(
                single.GateEvent(
                    tool="mcp__github__fetch_pr", tool_input=data, cwd=self.ws
                )
            )
            self.assertTrue(g.core.evaluate(ev, prof, self.ws, policy=pol).blocks)

    def test_uncached_fetch_replaces_existing_cache(self):
        original = self.policy(cached=True)
        self.assertFalse(self.verdict(policy=original).blocks)
        self.scope["repository_grants"] = []
        self.scope["generation"] = 8
        self.assertTrue(self.verdict(policy=self.policy(cached=False)).blocks)
        reused = self.policy(cached=True)
        self.assertEqual(reused[1].generation, 8)
        self.assertTrue(self.verdict(policy=reused).blocks)
        with patch.object(g.core, "now_secs", return_value=self.now + 60):
            self.assertTrue(self.verdict(policy=self.policy(cached=True)).blocks)

    def test_failed_refresh_preserves_only_bounded_prior_authority(self):
        original = self.policy(cached=True)
        with patch.object(g.m, "_fetch_policy_snapshot_uncached", return_value=None):
            with patch.object(g.m, "SNAPSHOT_RETRY_PAUSE_S", 0):
                self.assertIsNone(
                    g.m.fetch_policy_snapshot("cbp-being", use_cache=False)
                )
        reused = self.policy(cached=True)
        self.assertEqual(reused[1].generation, 7)
        self.assertFalse(self.verdict(policy=reused).blocks)
        with patch.object(g.core, "now_secs", return_value=self.now + 60):
            self.assertTrue(self.verdict(policy=reused).blocks)
            self.assertTrue(self.verdict(policy=original).blocks)

    def test_fresh_revocation_does_not_mutate_previously_resolved_policy(self):
        original = self.policy(cached=True)
        self.scope["repository_grants"] = []
        self.scope["generation"] = 8
        refreshed = self.policy(cached=False)
        self.assertTrue(self.verdict(policy=refreshed).blocks)
        self.assertFalse(self.verdict(policy=original).blocks)
        with patch.object(g.core, "now_secs", return_value=self.now + 60):
            self.assertTrue(self.verdict(policy=original).blocks)


if __name__ == "__main__":
    unittest.main()
