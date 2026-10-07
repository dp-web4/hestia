#!/usr/bin/env python3
"""Review the committed 01cf91e4 delta in memory; write no governed source."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "prior_review", Path(__file__).with_name("notice-18920-check.py"))
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
DIGEST = "01cf91e4a6d68f30c545133557ffc436b78e0d7731f02fd0a21c35f1f98f5bc8"
REV = "0cac578316ff999420324f3f3daa2fa16205c75d"
SHARED = "plugins/_shared/"
GATE = SHARED + "hestia_single_gate.py"
TEST = SHARED + "registered_surface_test.py"


def reconstruct(digest):
    # Reuse the earlier context-checking parser, supplying committed patch bytes
    # through a path-like object. Nothing is extracted to a governed path.
    patch = subprocess.check_output(
        ["git", "show", REV + ":held/" + digest + ".patch"], cwd=ROOT)

    class PatchPath:
        def __truediv__(self, _):
            return self

        def read_bytes(self):
            return patch

    old_root, old_digest, old_blob = prior.ROOT, prior.DIGEST, prior.blob
    prior.ROOT, prior.DIGEST = PatchPath(), digest
    prior.blob = lambda path: subprocess.check_output(
        ["git", "show", "18f91db:" + path], cwd=ROOT)
    try:
        return prior.reconstructed()
    finally:
        prior.ROOT, prior.DIGEST, prior.blob = old_root, old_digest, old_blob


def main():
    sources = reconstruct(DIGEST)
    assert len(sources) == 8
    for name in ("hestia_gate_core", "hestia_gate_mechanism", "hestia_governance_closure"):
        path = SHARED + name + ".py"
        assert (ROOT / path).read_bytes() == prior.blob(path), path
    sys.path.insert(0, str(ROOT / SHARED))
    gate = prior.module("hestia_single_gate", GATE, sources[GATE])
    suite = prior.module("held_registered_surface_test", TEST, sources[TEST])
    for test in suite.ALL:
        test()
    print("Exact held registered-surface suite:", len(suite.ALL), "passed")

    old = reconstruct("29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655")
    old_gate = prior.module("prior_held_gate", GATE, old[GATE])
    suite.gate = old_gate
    failures = []
    for test in suite.ALL:
        try:
            test()
        except AssertionError as exc:
            failures.append(test.__name__)
            print("Old gate + new suite expected failure:", str(exc)[:250])
    assert failures == ["test_the_entry_matcher_covers_every_bash_expansion"], failures
    suite.gate = gate
    print("Old gate + new suite:", len(suite.ALL) - len(failures), "passed;", len(failures), "failed")

    with tempfile.TemporaryDirectory(prefix="notice-18954-globs-") as directory:
        cases = [(r"x\[ab]y*", "x[ab]yes"),
                 (r"x\[ab]efore_*", "x[ab]efore_tool.py"),
                 ("[[=b=]]efore_tool.py", "[b]efore_tool.py"),
                 ("[[=b=]]efore_tool.py", "[=]efore_tool.py")]
        for _, name in cases:
            Path(directory, name).touch()
        for pattern, expected in cases:
            output = subprocess.check_output([
                "bash", "--noprofile", "--norc", "-c",
                'shopt -s nullglob; cd "$1" && for f in $2; do printf "%s\\0" "$f"; done',
                "_", directory, pattern], text=True)
            assert expected in output.split("\0"), (pattern, expected, output)
            target, entry = str(Path(directory, pattern)), str(Path(directory, expected))
            assert gate._reaches_registered_entry(target, [entry]), (pattern, expected)
            assert not old_gate._reaches_registered_entry(target, [entry]), (pattern, expected)
            print("Old miss -> fixed:", repr(pattern), "->", repr(expected))

    sys.path.insert(0, str(ROOT / "tools"))
    import hooks_gt as gt
    published = sources["hooks-gt/_shared/hestia_single_gate.py"].encode()
    assert gt.strip_header(published) == sources[GATE].encode()
    digest = gt.canonical_digest(published)
    assert digest == "ac14f90d81761433559ea83aefc6f9f5a31ca9410dddac60b17586dfde5e61e3"
    manifests = {p: json.loads(s) for p, s in sources.items() if p.endswith("manifest.json")}
    for path, manifest in manifests.items():
        assert manifest["gt_version"] == gt._version(manifest), path
        engine = manifest if path == "hooks-gt/_shared/manifest.json" else manifest["engine"]
        assert any(f["path"] == "hestia_single_gate.py" and f["sha256"] == digest
                   for f in engine["files"]), path
        if engine is not manifest:
            assert engine["gt_version"] == manifests["hooks-gt/_shared/manifest.json"]["gt_version"]
    print("Published source equality and five manifest content addresses: passed")
    print("Gate SHA-256:", hashlib.sha256(sources[GATE].encode()).hexdigest())
    print("Test SHA-256:", hashlib.sha256(sources[TEST].encode()).hexdigest())
    print("Scope: exact held patch, supplied producer tests, matcher regressions and publication metadata.")
    print("No daemon approval, landing or installed-state claim.")


if __name__ == "__main__":
    main()
