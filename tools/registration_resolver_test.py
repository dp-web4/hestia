"""Regression tests for tools/registration_resolver.py.

Run bare by tools/ci_discovery.py and under unittest/pytest alike.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import registration_resolver as rr  # noqa: E402


class RegistrationResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.home.mkdir()
        self.repo.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def expects(self, member="claude-code", reader="json-hook-commands", path=None):
        d = self.repo / "plugins" / member
        d.mkdir(parents=True, exist_ok=True)
        p = d / "expects.json"
        reg = {}
        if reader is not None:
            reg["reader"] = reader
        if path is not None:
            reg["path"] = path
        payload = {"install": {"registration": reg}}
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def reg_json(self, rel, commands):
        p = self.home.joinpath(*rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"hooks": [{"hooks": [{"command": c} for c in commands]}]}),
            encoding="utf-8",
        )
        return p

    def touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# hook\n", encoding="utf-8")
        return p.resolve()

    def test_bare_absolute_hook_is_target(self):
        hook = self.touch("hooks/bare.py")
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [str(hook)])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "ok")
        self.assertTrue(r["complete"])
        self.assertEqual([x["path"] for x in r["targets"]], [str(hook)])

    def test_interpreter_and_env_prefix_find_script_not_interpreter(self):
        a = self.touch("hooks/a.py")
        b = self.touch("hooks/b.py")
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"python3 {a}", f"MODE=strict python3 -u {b}"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "ok")
        self.assertEqual({x["path"] for x in r["targets"]}, {str(a), str(b)})
        self.assertTrue(r["complete"])

    def test_node_value_option_is_unclassified_not_a_phantom_hook(self):
        module = self.touch("node/preload.js")
        script = self.touch("node/hook.js")
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"node --require {module} {script}"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "ok")
        self.assertFalse(r["complete"])
        self.assertEqual(r["targets"], [])
        self.assertEqual(len(r["unclassified_commands"]), 1)

    def test_unknown_python_option_is_unclassified_not_argv_guessing(self):
        value = self.touch("python/option-value")
        script = self.touch("python/hook.py")
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"python3 --future-option {value} {script}"])
        r = rr.resolve_registration(e, self.home)
        self.assertFalse(r["complete"])
        self.assertEqual(r["targets"], [])

    def test_same_basename_at_two_paths_is_not_deduplicated(self):
        a = self.touch("one/pre_tool_use.py")
        b = self.touch("two/pre_tool_use.py")
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"python3 {a}", f"python3 {b}"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(len(r["targets"]), 2)
        self.assertEqual(
            [x["basename"] for x in r["targets"]],
            ["pre_tool_use.py", "pre_tool_use.py"],
        )

    def test_missing_hook_is_preserved_as_the_finding(self):
        missing = (self.root / "hooks" / "dead.py").resolve()
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"python3 {missing}"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(
            r["targets"],
            [
                {
                    "path": str(missing),
                    "basename": "dead.py",
                    "exists": False,
                    "kind": "missing",
                }
            ],
        )

    def test_existing_directory_is_not_a_hook_target(self):
        d = self.root / "workspace"
        d.mkdir()
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [str(d.resolve())])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["targets"], [])
        self.assertEqual(len(r["discarded"]), 1)
        self.assertIn("directory", r["discarded"][0]["reason"])

    def test_absolute_option_value_on_unknown_binary_is_not_a_phantom_hook(self):
        d = self.root / "workspace"
        d.mkdir()
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, [f"hestia-agent-inventory --workspace {d.resolve()} --brief"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["targets"], [])
        self.assertFalse(r["complete"])
        self.assertEqual(len(r["unclassified_commands"]), 1)

    def test_unclassified_is_not_silently_none_registered(self):
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        self.reg_json(rel, ["custom-wrapper relative-hook.py"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "ok")
        self.assertEqual(r["commands_seen"], 1)
        self.assertFalse(r["complete"])
        self.assertEqual(r["targets"], [])

    def test_absent_registration_is_not_present_not_empty_ok(self):
        e = self.expects(path=[".claude", "missing.json"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "not_present")
        self.assertNotIn("targets", r)

    def test_unreadable_registration_is_distinct(self):
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        p = self.home.joinpath(*rel)
        p.mkdir(parents=True)
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "unreadable")

    def test_malformed_json_registration_is_unparseable(self):
        rel = [".claude", "settings.json"]
        e = self.expects(path=rel)
        p = self.home.joinpath(*rel)
        p.parent.mkdir(parents=True)
        p.write_text("{not-json", encoding="utf-8")
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "unparseable")

    def test_unknown_reader_is_loud_before_touching_host(self):
        e = self.expects(reader="invented-reader", path=["x"])
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "unknown_reader")

    def test_no_registration_contract_is_not_declared(self):
        e = self.expects(reader=None, path=None)
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "not_declared")

    def test_toml_reader_matches_interpreter_shape(self):
        hook = self.touch("hooks/codex.py")
        rel = [".codex", "config.toml"]
        e = self.expects(member="codex", reader="toml-hook-commands", path=rel)
        p = self.home.joinpath(*rel)
        p.parent.mkdir(parents=True)
        p.write_text(f'command = "python3 {hook}"\n', encoding="utf-8")
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "ok")
        self.assertEqual([x["path"] for x in r["targets"]], [str(hook)])

    def test_malformed_toml_command_assignment_is_unparseable(self):
        rel = [".codex", "config.toml"]
        e = self.expects(member="codex", reader="toml-hook-commands", path=rel)
        p = self.home.joinpath(*rel)
        p.parent.mkdir(parents=True)
        p.write_text('command = "unterminated\n', encoding="utf-8")
        r = rr.resolve_registration(e, self.home)
        self.assertEqual(r["state"], "unparseable")


if __name__ == "__main__":
    unittest.main()
