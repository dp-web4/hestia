"""Offline #1281 origin-binding regression; --held compiles the held bytes in memory.

Baseline deliberately fails before repair. --core-suite also runs existing offline
core tests, relocating only their fixture cache. No live gate or remote is used.
"""
import argparse
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch
from recursive_repo_scope_candidate import artifact, proposed_sources

ROOT = Path(__file__).resolve().parents[2]
HELD = ROOT / "held/c7ed5f759edad539f1aed9fcce58ae25b13a92f6b41db193668354d1b5bb7a4e.patch"


def load_module(name, path, source):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TEMPLATE_DIR="")
    return subprocess.run(["git", "-C", str(path), *args], env=env, capture_output=True,
                          text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--held", action="store_true")
    ap.add_argument("--core-suite", action="store_true")
    ap.add_argument("--contract-suite", action="store_true")
    args = ap.parse_args()
    changes = proposed_sources()
    if args.held:
        a = artifact()
        assert HELD.read_text() == a["patch"], "held artifact differs from tested candidate"
        assert hashlib.sha256(HELD.read_bytes()).hexdigest() == HELD.stem
    sys.path.insert(0, str(ROOT / "plugins/_shared"))
    baseline_core = load_module("hestia_gate_core", ROOT / "plugins/_shared/hestia_gate_core.py",
                               changes["plugins/_shared/hestia_gate_core.py"][0])
    baseline_adapter = load_module("hestia_single_gate", ROOT / "plugins/_shared/hestia_single_gate.py",
                                  changes["plugins/_shared/hestia_single_gate.py"][0])
    g = load_module("hestia_gate_core", ROOT / "plugins/_shared/hestia_gate_core.py",
                    changes["plugins/_shared/hestia_gate_core.py"][int(args.held)])
    adapter = load_module("hestia_single_gate", ROOT / "plugins/_shared/hestia_single_gate.py",
                          changes["plugins/_shared/hestia_single_gate.py"][int(args.held)])
    failed, total = [], 0
    compared = []

    def check(label, observed, expected):
        nonlocal total
        total += 1
        okay = observed == expected
        print(f"{'PASS' if okay else 'FAIL'} {label}: {observed!r}")
        if not okay:
            failed.append(label)

    with tempfile.TemporaryDirectory(prefix="repo-scope-regression-") as tmp:
        ws = Path(tmp) / "workspace"
        ws.mkdir()

        def checkout(name, origin=None):
            path = ws / name
            path.mkdir()
            git(path, "init", "-q")
            if origin:
                git(path, "config", "remote.origin.url", origin)
            return path

        repo = checkout("sample", "https://github.com/example/sample.git")
        checkout("missing-origin")
        checkout("blocked-private", "https://github.com/example/blocked-private.git")
        (ws / "plain-directory").mkdir()
        (ws / "alias").symlink_to(repo, target_is_directory=True)
        outside = Path(tmp) / "outside"
        outside.mkdir()
        git(outside, "init", "-q")
        git(outside, "config", "remote.origin.url", "https://github.com/example/escaped.git")
        (ws / "escaped").symlink_to(outside, target_is_directory=True)
        common = checkout("common", "https://github.com/example/worktree.git")
        git(common, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture")
        git(common, "worktree", "add", "--detach", "-q", str(ws / "worktree"))
        profile = g.HarnessProfile(member_id="codex", identity_path="unused",
                                   launch_cwd_env="TEST_SCOPE_LAUNCH")

        def verdict(scopes, identity="example/sample", paths=None, fields=None, with_rule=False):
            pol = g.AgentPolicy(member_id="codex", scope=tuple(scopes), source="synthetic-vault")
            event = adapter.normalized_event(adapter.GateEvent(
                tool="mcp__fixture__github", tool_input=fields if fields is not None else
                {"repository_full_name": identity}))
            event.paths.extend(paths or [])
            result = g.evaluate(event, profile, str(ws), pol)
            decision = result.decision
            if args.held:
                baseline_event = baseline_adapter.normalized_event(baseline_adapter.GateEvent(
                    tool="mcp__fixture__github", tool_input=fields if fields is not None else
                    {"repository_full_name": identity}))
                baseline_event.paths.extend(paths or [])
                baseline = baseline_core.evaluate(baseline_event, profile, str(ws), pol).decision
                compared.append((baseline, decision))
                assert decision != "allow" or baseline == "allow", (scopes, identity, baseline, decision)
            return (decision, result.rule) if with_rule else decision

        with patch.dict(os.environ, {"TEST_SCOPE_LAUNCH": str(Path(tmp) / "elsewhere"),
                                     "HESTIA_FORBIDDEN_EXTRA": "blocked-private"}):
            broad = [f"path:{ws}/**"]
            check("local file already covered", g._within_path_grant(str(repo / "README.md"), broad, str(ws)), True)
            check("adapter preserves owner", adapter._mcp_repo("mcp__fixture", {"repository_full_name": "example/sample"}), "example/sample")
            check("recursive workspace adds no remote authority", verdict(broad), "deny")
            check("recursive repository path adds no remote authority", verdict([f"path:{repo}/**"]), "deny")
            check("explicit basename grant permits matching origin", verdict(["sample"]), "allow")
            check("foreign owner denied with recursive grant", verdict(broad, "foreign/sample"), "deny")
            check("foreign owner denied with explicit grant", verdict(["sample"], "foreign/sample"), "deny")
            check("basename alone denied", verdict(["sample"], "sample"), "deny")
            check("owner and repo fields combine", verdict(["sample"], fields={"owner": "example", "repo": "sample"}), "allow")
            check("conflicting aliases denied", verdict(["sample"], fields={"repository_full_name": "example/sample", "repo": "foreign/sample"}), "deny")
            check("conflicting owner denied", verdict(["sample"], fields={"repository_full_name": "example/sample", "owner": "foreign"}), "deny")
            check("no grants", verdict([]), "deny")
            check("qualified grant spelling adds no new authority", verdict(["example/sample"]), "deny")
            check("exact workspace stays exact", verdict([f"path:{ws}"]), "deny")
            check("exact repo stays exact", verdict([f"path:{repo}"]), "deny")
            check("file grant cannot front for repo", verdict([f"path:{repo}/README.md"]), "deny")
            check("recursive child cannot front for repo", verdict([f"path:{repo}/src/**"]), "deny")
            check("sibling prefix is not containment", verdict([f"path:{ws}-other/**"]), "deny")
            check("missing checkout", verdict(broad, "example/missing"), "deny")
            check("explicit grant cannot invent checkout", verdict(["missing"], "example/missing"), "deny")
            check("ordinary directory", verdict(broad, "example/plain-directory"), "deny")
            check("missing origin under recursive grant", verdict(broad, "example/missing-origin"), "deny")
            check("missing origin under explicit grant", verdict(["missing-origin"], "example/missing-origin"), "deny")
            check("real linked worktree with explicit grant", verdict(["worktree"], "example/worktree"), "allow")
            check("worktree foreign owner", verdict(["worktree"], "foreign/worktree"), "deny")
            git(common, "config", "extensions.worktreeConfig", "true")
            git(ws / "worktree", "config", "--worktree", "remote.origin.url", "https://github.com/foreign/worktree.git")
            check("worktree override makes common origin ambiguous", verdict(["worktree"], "example/worktree"), "deny")
            check("worktree override cannot select foreign origin", verdict(["worktree"], "foreign/worktree"), "deny")
            check("symlink escape", verdict(broad, "example/escaped"), "deny")
            check("internal alias", verdict(broad, "example/alias"), "deny")
            check("forbidden name dominates", verdict(broad, "example/blocked-private"), "deny")
            check("relative secret remains forbidden", verdict(broad, paths=[".env"]), "deny")
            # Notice 20670: invalid identity previously erased egress evidence.
            # Vary alias, malformed/conflicting shape, policy, and degraded mode.
            token = g.FORBIDDEN_DEFAULT[-1]
            egress_fields = []
            for key in ("repository_full_name", "repo_full_name", "repository", "repo"):
                for shape, value in (("bare", token),
                                     ("URL", "https://github.com/o/" + token),
                                     ("qualified", "o/" + token)):
                    egress_fields.append((key + " " + shape, {key: value}))
            egress_fields.extend([
                ("owner plus bare", {"owner": "o", "repo": token}),
                ("conflicting aliases", {"repo": "o/" + token, "repository": "o/sample"}),
                ("conflicting owner", {"owner": token, "repo": "o/sample"}),
                ("nonstring preceding raw alias", {"repository_full_name": 42, "repo": token}),
                ("empty preceding raw alias", {"repository_full_name": "", "repo": token}),
            ])
            for label, fields in egress_fields:
                for scope in (["*"], ["sample"], broad, []):
                    check("innate egress " + label + " scope=" + str(scope),
                          verdict(scope, fields=fields, with_rule=True), ("deny", "egress.secret"))
                event = adapter.normalized_event(adapter.GateEvent(
                    tool="mcp__fixture__github", tool_input=fields))
                degraded = g.degraded_verdict(event, profile)
                check("degraded egress " + label,
                      (degraded.decision, degraded.rule), ("deny", "egress.secret"))
            check("unscoped benign bare remains allowed",
                  verdict(["*"], fields={"repo": "sample"}), "allow")
            check("scoped benign bare remains denied",
                  verdict(["sample"], fields={"repo": "sample"}, with_rule=True), ("deny", "mrh.repo"))
            for identity in ["example/..", "example/.", "../sample", "example/sample/child", "example/sample\\child", "example/sample%2fchild", "/sample", ""]:
                check(f"malformed identity {identity!r}", verdict(["sample"], identity), "deny")
            for remote in ["https://github.com/example/sample", "git@github.com:example/sample.git",
                           "ssh://git@github.com/example/sample.git", "ssh://git@github.com:22/example/sample.git",
                           "https://github.com/EXAMPLE/SAMPLE.git/"]:
                git(repo, "config", "remote.origin.url", remote)
                check(f"origin spelling {remote}", verdict(["sample"]), "allow")
            for remote in ["https://github.com/foreign/sample.git", "https://elsewhere.invalid/example/sample.git",
                           "git@alias:example/sample.git", "https://github.com/example/sample.git?x=1",
                           "https://github.com@example.invalid/example/sample.git", "file:///example/sample.git"]:
                git(repo, "config", "remote.origin.url", remote)
                check(f"reject origin {remote}", verdict(["sample"]), "deny")
            git(repo, "config", "remote.origin.url", "https://github.com/example/sample.git")
            git(repo, "config", "--add", "remote.origin.url", "https://github.com/foreign/sample.git")
            check("multiple origin URLs are ambiguous", verdict(["sample"]), "deny")
            git(repo, "config", "--replace-all", "remote.origin.url", "https://github.com/example/sample.git")
            with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.url",
                                         "GIT_CONFIG_VALUE_0": "https://github.com/foreign/sample.git",
                                         "GIT_DIR": str(outside / ".git")}):
                check("environment cannot rebind origin", verdict(["sample"], "foreign/sample"), "deny")
                check("environment does not hide actual origin", verdict(["sample"]), "allow")
            git(repo, "config", "--unset-all", "remote.origin.url")
            includes = Path(tmp) / "extra-config"
            includes.write_text('[remote "origin"]\n url = https://github.com/example/sample.git\n')
            git(repo, "config", "include.path", str(includes))
            check("included origin cannot supply identity", verdict(["sample"]), "deny")
            # Notice 20654: hold policy fixed while exercising member-writable
            # evidence. A new checkout, a new origin, and an origin rewrite must
            # each leave the recursive path grant's remote authority unchanged.
            minted = ws / "minted"
            check("before checkout mint", verdict(broad, "victim/minted"), "deny")
            metadata = minted / ".git"
            (metadata / "objects").mkdir(parents=True)
            (metadata / "refs").mkdir()
            (metadata / "HEAD").write_text("ref: refs/heads/main\n")
            config = metadata / "config"
            config.write_text('[core]\n repositoryformatversion = 0\n bare = false\n')
            check("mint writes covered by existing path grant",
                  g._within_path_grant(str(config), broad, str(ws)), True)
            check("after checkout mint without origin", verdict(broad, "victim/minted"), "deny")
            config.write_text(config.read_text() +
                              '[remote "origin"]\n url = https://github.com/victim/minted.git\n')
            check("after matching origin mint", verdict(broad, "victim/minted"), "deny")
            config.write_text(config.read_text().replace("victim/minted", "other/minted"))
            check("after origin retarget", verdict(broad, "other/minted"), "deny")
            # Explicit basename authority already admitted all owners on main.
            # Record the remaining A1 limit without claiming grant-time binding.
            git(repo, "config", "remote.origin.url", "https://github.com/example/sample.git")
            check("explicit grant before origin retarget", verdict(["sample"], "victim/sample"), "deny")
            config = repo / ".git/config"
            config.write_text(config.read_text().replace("example/sample", "victim/sample"))
            check("explicit grant after origin retarget (existing baseline reach)",
                  verdict(["sample"], "victim/sample"), "allow")
            expired = g.resolve_agent_policy(profile, vault_reader=lambda _: {
                "in_scope": broad, "generation": 1, "snapshot_expires_at": 1, "expires_at": 1})
            check("expired snapshot has no reach", expired.scope, ())
    print(f"{total - len(failed)}/{total} passed; mode={'held in memory' if args.held else 'main'}")
    if args.held:
        print(f"No baseline-deny to candidate-allow transitions in {len(compared)} repository evaluations")
    if args.core_suite:
        scratch = ROOT / "scratchpad"
        scratch.mkdir(exist_ok=True)
        expand = os.path.expanduser
        with tempfile.TemporaryDirectory(prefix="repo-core-suite-", dir=scratch) as fixture:
            with patch("os.path.expanduser", lambda p: fixture if p == "~/.cache/hestia-gate-core-tests" else expand(p)):
                try:
                    runpy.run_path(str(ROOT / "plugins/_shared/test_gate_core.py"), run_name="__main__")
                except SystemExit as done:
                    if done.code:
                        raise
    if args.contract_suite:
        with patch.object(sys, "argv", ["one_gate_decide_contract_test.py", "--only", "contract"]):
            try:
                runpy.run_path(str(ROOT / "tools/one_gate_decide_contract_test.py"), run_name="__main__")
            except SystemExit as done:
                if done.code:
                    raise
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
