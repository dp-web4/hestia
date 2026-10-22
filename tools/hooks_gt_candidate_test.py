"""Hermetic certification-preflight checks; no installed hooks or vault access."""
import importlib.util
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
                "hooks": {"BeforeEvent": [{"command": "python3 ${ROOT}/hooks/worker.py"}]}}))
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
