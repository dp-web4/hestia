"""Build and validate the held #1275 completion without writing governed files.

Run from the PR checkout: python3 docs/reviews/build-1275.py
The only write is held/<sha256>.patch. Candidate gate code executes in memory
for offline tests; the installed gate and checkout sources are never changed.
"""
import ast
import difflib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
GATE = "plugins/_shared/hestia_single_gate.py"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hooks_gt as gt


def main():
    old = (ROOT / GATE).read_bytes()
    before = b"            if token in low:\n"
    after = b"            if core.names_forbidden_token(low, token):\n"
    assert old.count(before) == 1, "expected the unmodified precheck"
    new = old.replace(before, after)
    sources = {GATE: new}
    declarations = gt.units(ROOT)
    tree = {}
    for unit, declaration in declarations.items():
        for rel, source in declaration["files"].items():
            data = sources.get(source, (ROOT / source).read_bytes())
            tree[f"hooks-gt/{unit}/{rel}"] = gt.with_header(data, rel)
    manifests = gt._compose(ROOT, lambda unit, rel: gt.canonical_digest(tree[f"hooks-gt/{unit}/{rel}"]))
    for unit, manifest in manifests.items():
        tree[f"hooks-gt/{unit}/manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    proposed = dict(sources)
    proposed.update({rel: data for rel, data in tree.items() if data != (ROOT / rel).read_bytes()})
    assert set(proposed) == {GATE, "hooks-gt/_shared/hestia_gate_core.py",
                            "hooks-gt/_shared/hestia_single_gate.py"} | {
        f"hooks-gt/{unit}/manifest.json" for unit in ("_shared", "claude-code", "codex", "gemini", "kimi")}

    # Exercise the actual GT checker against a read-only, in-memory projection.
    real_bytes = Path.read_bytes
    def projected_bytes(path):
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            return real_bytes(path)
        return proposed[rel] if rel in proposed else real_bytes(path)
    def projected_text(path, encoding=None, errors=None):
        return projected_bytes(path).decode(encoding or "utf-8", errors or "strict")
    with patch.object(Path, "read_bytes", projected_bytes), patch.object(Path, "read_text", projected_text):
        assert gt.check(ROOT) == [], "candidate GT is incoherent"
    print("Projected GT: zero findings")

    spec = importlib.util.spec_from_file_location("egress_identifier_tests", ROOT / "tools/egress_identifier_test.py")
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    for source, label, expected_ok in ((old, "before", False), (new, "held", True)):
        module = types.ModuleType("hestia_single_gate_candidate")
        module.__file__ = str(ROOT / GATE)
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        tests.gate = module
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
        print(f"{label}: {result.testsRun} tests, {len(result.failures)} subcase failures, {len(result.errors)} errors")
        if result.wasSuccessful() != expected_ok or result.errors:
            raise AssertionError(stream.getvalue())
        if not expected_ok:
            assert all(t.test_case._testMethodName in {"test_identifiers_are_not_egress_denials",
                                            "test_operator_extra_tokens_keep_the_same_semantics"}
                       for t, _ in result.failures), stream.getvalue()

    chunks = []
    for rel, data in sorted(proposed.items()):
        chunks.append(f"diff --git a/{rel} b/{rel}\n" + "".join(difflib.unified_diff(
            (ROOT / rel).read_text().splitlines(True), data.decode().splitlines(True), f"a/{rel}", f"b/{rel}")))
    body = "".join(chunks).encode()
    digest = hashlib.sha256(body).hexdigest()
    out = ROOT / "held" / (digest + ".patch")
    out.write_bytes(body)
    assert (ROOT / GATE).read_bytes() == old
    print(f"Held patch: {digest} ({len(proposed)} files)")

    if "--full" in sys.argv:
        # Keep the core's non-/tmp scope discrimination, but use a writable
        # checkout fixture instead of its default external cache directory.
        path = ROOT / "plugins/_shared/test_gate_core.py"
        source = path.read_text()
        with tempfile.TemporaryDirectory(prefix="core-1275-", dir=ROOT) as fixture:
            parsed = ast.parse(source)
            class FixtureRoot(ast.NodeTransformer):
                def visit_Call(self, node):
                    if (isinstance(node.func, ast.Attribute) and node.func.attr == "expanduser"
                            and node.args and isinstance(node.args[0], ast.Constant)
                            and str(node.args[0].value).endswith("/hestia-gate-core-tests")):
                        return ast.copy_location(ast.Constant(fixture), node)
                    return self.generic_visit(node)
            parsed = ast.fix_missing_locations(FixtureRoot().visit(parsed))
            try:
                exec(compile(parsed, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})
            except SystemExit as exc:
                assert exc.code in (None, 0), f"core suite exited {exc.code}"

        # Existing decide() contracts use a test daemon only. Load the candidate
        # in memory under the canonical import name so the suite exercises it.
        name = "hestia_single_gate"
        module = types.ModuleType(name)
        module.__file__ = str(ROOT / GATE)
        sys.modules[name] = module
        exec(compile(new, module.__file__, "exec"), module.__dict__)
        import one_gate_decide_contract_test as contracts
        assert contracts.main(["--only", "contract"]) == 0


if __name__ == "__main__":
    main()
