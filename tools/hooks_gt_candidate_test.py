"""Hermetic certification-preflight checks; no installed hooks or vault access."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load("hooks_gt_candidate")
st = load("hooks_gt_store")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.home = Path(self.tmp.name) / "store-parent"
        for name in ("alpha", "beta"):
            base = self.repo / "plugins" / name
            (base / "hooks").mkdir(parents=True)
            spec = {"install": {"member": f"{name}-member", "files": ["hooks/worker.py"]}}
            if name == "beta":
                spec["install"]["requires"] = ["alpha/hooks/worker.py"]
            (base / "expects.json").write_text(json.dumps(spec))
            (base / "hooks/worker.py").write_text(f"print('{name}')\n")
            (base / "hooks/hooks.json").write_text(json.dumps({
                "hooks": {"BeforeEvent": [{"command":
                    f"python3 @HESTIA_PLUGIN_ROOT@/{name}/hooks/worker.py"}]}}))
        shared = self.repo / "plugins/_shared"
        shared.mkdir()
        (shared / "RUNTIME_MANIFEST.txt").write_text("engine.py\n")
        (shared / "engine.py").write_text("RULES = 1\n")
        self.publish()
        self.root = st.store_root(self.home)
        self.version = self.current("beta")

    def publish(self):
        for rel, data in st.hooks_gt.build(self.repo).items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        st.ingest(self.repo, self.home)

    def current(self, name):
        return json.loads((self.repo / f"hooks-gt/{name}/manifest.json").read_text())["gt_version"]

    def get(self, **kw):
        return c.candidate(self.root, **dict(
            {"name": "beta", "version": self.version, "member": "beta-member"}, **kw))

    def closure(self):
        return self.root / "closures/beta" / f"{self.version}.json"

    def blob(self, path="hooks/worker.py"):
        m = json.loads(self.closure().read_text())["manifest"]
        sha = next(r["sha256"] for r in m["files"] if r["path"] == path)
        return st.blob_path(self.root, sha)

    def rewrite(self, change):
        rec = json.loads(self.closure().read_text())
        change(rec["manifest"])
        m = rec["manifest"]
        m["gt_version"] = st.hooks_gt._version(m)
        self.version = m["gt_version"]
        self.closure().write_text(json.dumps(rec))

    def test_candidate_binds_registration_engine_dependency_and_exact_bytes(self):
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        result = self.get()
        self.assertEqual(result, self.get())
        self.assertEqual(result["status"], "uncertified")
        self.assertEqual({r["path"] for r in result["files"]}, {
            "beta/hooks/worker.py", "beta/hooks/hooks.json", "_shared/engine.py", "alpha/hooks/worker.py"})
        self.assertEqual(result["registration"]["path"], "beta/hooks/hooks.json")
        self.assertNotIn("certified", result)
        after = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_new_engine_does_not_change_old_candidate(self):
        original = self.get()
        (self.repo / "plugins/_shared/engine.py").write_text("RULES = 2\n")
        self.publish()
        self.assertNotEqual(self.current("beta"), self.version)
        self.assertEqual(original, self.get())
        self.assertNotEqual(original["candidate_sha256"],
                            self.get(version=self.current("beta"))["candidate_sha256"])

    def test_missing_registration_refuses(self):
        self.rewrite(lambda m: m.update(registration=None))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_wrong_member_and_global_engine_refuse(self):
        for kw in ({"member": "other"}, {"name": "_shared"}):
            with self.subTest(kw=kw), self.assertRaises(c.CandidateError):
                self.get(**kw)

    def test_paths_and_versions_are_not_globs_or_traversals(self):
        for kw in ({"name": "../beta"}, {"version": "../latest"}, {"version": "current"},
                   {"name": "/beta"}, {"version": "A" * 64}, {"member": ""}):
            with self.subTest(kw=kw), self.assertRaises(c.CandidateError):
                self.get(**kw)

    def test_manifest_tamper_without_version_change_refuses(self):
        p = self.closure()
        p.chmod(0o644)
        rec = json.loads(p.read_text())
        rec["manifest"]["member"] = "other"
        p.write_text(json.dumps(rec))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_duplicate_json_key_refuses(self):
        p = self.closure()
        p.chmod(0o644)
        p.write_text(p.read_text().replace('"manifest":', '"note": "shadow", "manifest":', 1))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_duplicate_manifest_path_refuses_even_with_new_valid_version(self):
        self.rewrite(lambda m: m["files"].append(dict(m["files"][0])))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_traversal_manifest_path_refuses_even_with_valid_version(self):
        self.rewrite(lambda m: m["files"][0].update(path="../escape"))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_engine_digest_disagreement_refuses(self):
        self.rewrite(lambda m: m["engine"]["files"][0].update(sha256="0" * 64))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_dependency_overlap_refuses(self):
        self.rewrite(lambda m: m["requires"].append({
            "unit": "beta", "path": m["files"][0]["path"], "sha256": m["files"][0]["sha256"]}))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_dependency_cannot_extend_reserved_namespaces(self):
        for name in ("beta", "_shared"):
            with self.subTest(unit=name):
                self.rewrite(lambda m: m.update(requires=[{
                    "unit": name, "path": "extra.py", "sha256": m["files"][0]["sha256"]}]))
                with self.assertRaisesRegex(c.CandidateError, "reserved namespace"):
                    self.get()

    def test_unverified_dependency_identity_is_explicit_and_digest_bound(self):
        original = self.get()
        for name in ("alpha", "nosuchunit"):
            self.rewrite(lambda m: m.update(requires=[{
                "unit": name, "path": "forged.py", "sha256": m["engine"]["files"][0]["sha256"]}]))
            result = self.get()
            labels = result["unverified_dependency_labels"]
            self.assertEqual(labels[0]["unit"], name)
            self.assertEqual(labels[0]["path"], "forged.py")
            self.assertNotEqual(original["candidate_sha256"], result["candidate_sha256"])
            claimed = result.pop("candidate_sha256")
            self.assertEqual(claimed, c.hashlib.sha256(json.dumps(
                result, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def set_registration(self, registration):
        sha, _ = st.put_blob(self.root, json.dumps(registration).encode())

        def change(m):
            for row in m["files"]:
                if row["path"] == m["registration"]:
                    row["sha256"] = sha

        self.rewrite(change)

    def test_unresolved_command_targets_refuse_with_diagnostics(self):
        target = "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"
        for command in (
            "python3 @HESTIA_PLUGIN_ROOT@/beta/hooks/ghost.py",
            "python3 ${ROOT}/hooks/worker.py", "python3 /outside/worker.py",
            "bash -c 'python3 " + target + "'", "python3 " + target + "; /outside/worker.py",
            "python3 " + target + " $(outside)", "python3 " + target + " `outside`",
            "env python3 " + target, "python3 " + target + " --extra=/outside/file",
            "python3 @HESTIA_PLUGIN_ROOT@/beta/hooks/*.py", None,
        ):
            with self.subTest(command=command):
                self.set_registration({"hooks": {"Event": [{"command": command}]}})
                with self.assertRaises(c.CandidateError) as caught:
                    self.get()
                self.assertEqual(caught.exception.unresolved_targets, [command])
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = c.main(["--store", str(self.root), "--unit", "beta",
                                 "--member", "beta-member", "--version", self.version])
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(json.loads(err.getvalue())["unresolved_targets"], [command])

    def test_member_mesh_lines_resolve_only_to_a_required_runtime_file(self):
        """#1373: a mesh line names <member>/hooks/<file>; it resolves to the required member-mesh/<file> and
        nothing looser. The pin must be a literal id."""
        wanted = {"beta/hooks/worker.py": "0" * 64, "member-mesh/session-mesh-inbox.sh": "1" * 64}
        ok = 'HESTIA_MESH_PLUGIN=beta-x HESTIA_ROLE="${HESTIA_ROLE:-@HESTIA_DEFAULT_ROLE@}" ' \
             "@HESTIA_PLUGIN_ROOT@/beta/hooks/session-mesh-inbox.sh"
        self.assertEqual(c.command_targets({"hooks": {"SessionStart": [{"command": ok}]}}, wanted),
                         ["member-mesh/session-mesh-inbox.sh"])
        for command in (
            # not required by this member
            "HESTIA_MESH_PLUGIN=beta-x @HESTIA_PLUGIN_ROOT@/beta/hooks/prompt-disposition-watch.sh",
            # a substitution or a placeholder instead of a literal pin
            "HESTIA_MESH_PLUGIN=$(id) @HESTIA_PLUGIN_ROOT@/beta/hooks/session-mesh-inbox.sh",
            "HESTIA_MESH_PLUGIN=@HESTIA_MESH@ @HESTIA_PLUGIN_ROOT@/beta/hooks/session-mesh-inbox.sh",
            # not directly in hooks/
            "HESTIA_MESH_PLUGIN=beta-x @HESTIA_PLUGIN_ROOT@/beta/hooks/sub/session-mesh-inbox.sh",
            "HESTIA_MESH_PLUGIN=beta-x @HESTIA_PLUGIN_ROOT@/beta/session-mesh-inbox.sh",
        ):
            with self.subTest(command=command):
                with self.assertRaises(c.CandidateError) as caught:
                    c.command_targets({"hooks": {"SessionStart": [{"command": command}]}}, wanted)
                self.assertEqual(caught.exception.unresolved_targets, [command])

    def test_all_nested_command_targets_are_checked(self):
        self.set_registration({"hooks": {"Event": [{"hooks": [
            {"type": "command", "command": "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"},
            {"type": "command", "command": "@HESTIA_PLUGIN_ROOT@/alpha/hooks/worker.py"}]}]}})
        result = self.get()
        self.assertEqual(result["command_targets"], ["alpha/hooks/worker.py", "beta/hooks/worker.py"])
        self.assertEqual(result["unresolved_targets"], [])
        self.set_registration({"hooks": {"Event": [{"hooks": [
            {"command": "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"},
            {"command": "@HESTIA_PLUGIN_ROOT@/alpha/hooks/missing.py"}]}]}})
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_empty_or_noncommand_hooks_refuse(self):
        for hooks in ({"Event": []}, {"Event": [{"type": "prompt", "prompt": "do it"}]}):
            self.set_registration({"hooks": hooks})
            with self.assertRaises(c.CandidateError):
                self.get()

    def test_unknown_command_fields_refuse_even_with_a_known_target(self):
        target = "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"
        for extra in ({"args": ["--other"]}, {"env": {"PYTHONPATH": "/elsewhere"}},
                      {"commands": ["echo other"]}, {"futureField": False}):
            with self.subTest(extra=extra):
                self.set_registration({"hooks": {"Event": [{
                    "type": "command", "command": target, **extra}]}})
                with self.assertRaises(c.CandidateError):
                    self.get()
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = c.main(["--store", str(self.root), "--unit", "beta",
                                 "--member", "beta-member", "--version", self.version])
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), "")

    def test_known_command_metadata_passes_without_becoming_a_target(self):
        self.set_registration({"hooks": {"Event": [{"hooks": [{
            "type": "command", "command": "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py",
            "timeout": 15, "statusMessage": "Checking the request"}]}]}})
        self.assertEqual(self.get()["command_targets"], ["beta/hooks/worker.py"])

    def test_command_metadata_must_not_hide_structures_or_coerce_types(self):
        for extra in ({"timeout": True}, {"timeout": 0}, {"timeout": "15"},
                      {"timeout": {"command": "echo hidden"}},
                      {"statusMessage": {"command": "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"}}):
            with self.subTest(extra=extra):
                self.set_registration({"hooks": {"Event": [{
                    "command": "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py", **extra}]}})
                with self.assertRaises(c.CandidateError):
                    self.get()

    def test_quoted_target_resolves_but_traversal_refuses(self):
        self.set_registration({"hooks": {"Event": [{"command":
            'python3 "@HESTIA_PLUGIN_ROOT@/beta/hooks/worker.py"'}]}})
        self.assertEqual(self.get()["command_targets"], ["beta/hooks/worker.py"])
        self.set_registration({"hooks": {"Event": [{"command":
            "python3 @HESTIA_PLUGIN_ROOT@/beta/hooks/../hooks/worker.py"}]}})
        with self.assertRaises(c.CandidateError) as caught:
            self.get()
        self.assertEqual(caught.exception.unresolved_targets,
                         ["python3 @HESTIA_PLUGIN_ROOT@/beta/hooks/../hooks/worker.py"])

    def test_nonregistration_json_cannot_hide_digest_header(self):
        # Derive a recognized header from a published non-JSON blob.
        header = next(line for line in self.blob().read_bytes().splitlines()
                      if st.hooks_gt._HEADER_RE.match(line.decode()))
        data = header + b'\n{}\n'
        sha, _ = st.put_blob(self.root, data)
        self.rewrite(lambda m: m["files"].append({
            "path": "extra.json", "source": "plugins/beta/extra.json", "sha256": sha}))
        with self.assertRaisesRegex(c.CandidateError, "JSON blob contains"):
            self.get()

    def test_duplicate_dependency_refuses(self):
        self.rewrite(lambda m: m["requires"].append(dict(m["requires"][0])))
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_missing_dependency_blob_refuses(self):
        rec = json.loads(self.closure().read_text())["manifest"]
        st.blob_path(self.root, rec["requires"][0]["sha256"]).unlink()
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_modified_blob_refuses(self):
        p = self.blob()
        p.chmod(0o644)
        p.write_bytes(p.read_bytes() + b"# changed\n")
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_header_only_tamper_refuses_despite_same_canonical_digest(self):
        p = self.blob()
        data = p.read_bytes()
        changed = data.replace(st.hooks_gt.header_value(data).encode(), b"0" * 64, 1)
        self.assertEqual(st.hooks_gt.canonical_digest(data), st.hooks_gt.canonical_digest(changed))
        p.chmod(0o644)
        p.write_bytes(changed)
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_symlink_blob_refuses(self):
        p = self.blob()
        outside = Path(self.tmp.name) / "outside"
        outside.write_bytes(p.read_bytes())
        p.unlink()
        p.symlink_to(outside)
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_symlink_directory_refuses(self):
        p = self.root / "closures/beta"
        moved = self.root / "closures/renamed"
        p.rename(moved)
        p.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_symlink_store_root_refuses(self):
        alias = Path(self.tmp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(c.CandidateError):
            c.candidate(alias, name="beta", version=self.version, member="beta-member")

    def test_fifo_refuses_without_waiting_for_writer(self):
        p = self.blob()
        p.unlink()
        os.mkfifo(p)
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_file_and_aggregate_budgets(self):
        with patch.object(c, "MAX_TOTAL", 1), self.assertRaises(c.CandidateError):
            self.get()
        reader = c.Reader(self.root)
        try:
            p = self.blob()
            with self.assertRaises(c.CandidateError):
                reader.read(str(p.relative_to(self.root)), limit=1)
        finally:
            reader.close()

    def test_published_members_resolve_from_a_throwaway_store(self):
        # Copy public repository artifacts into a disposable store, never live state.
        home = Path(self.tmp.name) / "public-store"
        st.ingest(HERE.parent, home)
        members = 0
        for path in sorted((HERE.parent / "hooks-gt").glob("*/manifest.json")):
            m = json.loads(path.read_text())
            if m["member"] is None or m["registration"] is None:
                continue
            with self.subTest(unit=m["unit"]):
                got = c.candidate(st.store_root(home), name=m["unit"],
                                  version=m["gt_version"], member=m["member"])
                self.assertEqual(got["status"], "uncertified")
                self.assertEqual(got["gt_version"], m["gt_version"])
            members += 1
        self.assertGreater(members, 0)

    def test_registration_json_is_verified_not_just_hashed(self):
        data = b'{"hooks": {}, "hooks": {"BeforeEvent": []}}'
        sha, _ = st.put_blob(self.root, data)

        def change(m):
            for row in m["files"]:
                if row["path"] == m["registration"]:
                    row["sha256"] = sha

        self.rewrite(change)
        with self.assertRaises(c.CandidateError):
            self.get()

    def test_file_count_budget(self):
        with patch.object(c, "MAX_FILES", 3), self.assertRaises(c.CandidateError):
            self.get()


if __name__ == "__main__":
    unittest.main()
