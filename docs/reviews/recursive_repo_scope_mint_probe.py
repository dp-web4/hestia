"""Reproduce the held patch's authority expansion, entirely offline.

Only synthetic directories are changed. The digest-checked candidate executes in
memory; no enforcing source, grants, or remote repositories are modified.
"""
import os
from pathlib import Path
import tempfile
import types
import sys
from unittest.mock import patch

from recursive_repo_scope_probe import SOURCE, candidate


def run(source, expected):
    core = types.ModuleType("mint_probe_core")
    sys.modules[core.__name__] = core
    exec(compile(source, str(SOURCE), "exec"), core.__dict__)
    with tempfile.TemporaryDirectory(prefix="repo-mint-review-") as tmp:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        profile = core.HarnessProfile(member_id="codex", identity_path="unused",
                                      launch_cwd_env="MINT_PROBE_CWD")
        policy = core.AgentPolicy(member_id="codex",
                                  scope=(f"path:{workspace}/**",), source="fixture")
        event = core.NormalizedEvent(tool="mcp__fixture__github", repos=["invented-repo"])
        repo = workspace / "invented-repo"

        def decision():
            return core.evaluate(event, profile, str(workspace), policy).decision

        with patch.dict(os.environ, {"MINT_PROBE_CWD": str(Path(tmp) / "elsewhere"),
                                     "HESTIA_FORBIDDEN_EXTRA": ""}):
            before = decision()
            repo.mkdir()
            ordinary_directory = decision()
            # This local write is within the pre-existing recursive path grant.
            assert core._within_path_grant(str(repo / ".git"), policy.scope, str(workspace))
            (repo / ".git").write_text("x")
            after_marker = decision()
        observed = (before, ordinary_directory, after_marker)
        assert observed == expected, (observed, expected)
        return observed


if __name__ == "__main__":
    original = SOURCE.read_text()
    print("baseline:", run(original, ("deny", "deny", "deny")))
    print("held candidate:", run(candidate(original), ("deny", "deny", "allow")))
    print("Reproduced: unchanged path authority gains remote reach after a marker write.")
