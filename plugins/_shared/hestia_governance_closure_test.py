#!/usr/bin/env python3
"""Contract tests for the shared governance-closure classifier.

The load-bearing assertions are the THREE measured false-positive classes (this program's
regression cases — each denied a member for TEXT-MENTIONING the closure without writing it):
  * a read-only find/grep/wc pipeline naming a hook file was denied;
  * a chained benign rm was denied because an EARLIER read named the closure;
  * an Edit was denied where the identical Write passed (payload text scanned as destination).
Plus the fail directions: write-classification errors fail CLOSED, read-classification errors
stay READ, registry failure falls back to the FLOOR (never open).

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
Run: python3 -m pytest <thisdir> -q   or   python3 hestia_governance_closure_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_governance_closure as g  # noqa: E402

FLOOR = g.LITERAL_FLOOR
_REAL_WRITE_TARGETS = g._write_position_targets
_REAL_READ_MENTIONS = g._read_position_mentions


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


_NEUTRAL_CWD = tempfile.mkdtemp(prefix="hgc-neutral-")


def cls(tool, tool_input, cwd=_NEUTRAL_CWD, closure=FLOOR):
    # cwd is PINNED to a neutral dir by default: classification is cwd-sensitive BY DESIGN
    # (a relative write executed while standing inside a closure dir genuinely lands in the
    # closure — plugins/_shared is itself a dir marker), so a test that inherits the runner's
    # cwd asserts the runner's location, not the module. Tests that exercise cwd semantics
    # pass their own cwd explicitly.
    return g.classify(tool, tool_input, cwd=cwd, closure=closure)


# ---- the three measured FP classes (named regression tests) ----
def test_readonly_find_naming_hook_is_read():
    v = cls("Bash", {"command":
                     'find plugins -name "pre_tool_use.py" -maxdepth 4 | wc -l'})
    check("find_is_read", v.classification == "read", str(v))
    v2 = cls("Bash", {"command": "grep -rn _touches_self plugins/kimi/hooks/ | head -5"})
    check("grep_is_read", v2.classification == "read", str(v2))


def test_chained_benign_rm_not_write_unless_target_in_closure():
    # The chained-rm FP: an earlier READ names the closure; the rm's own target does not.
    v = cls("Bash", {"command":
                     "grep -c deny plugins/kimi/hooks/pre_tool_use.py && rm -f /tmp/scratch.txt"})
    check("chained_rm_is_read", v.classification == "read", str(v))
    # Control (positive): the SAME shape with the rm target IN the closure IS a write.
    v2 = cls("Bash", {"command":
                      "echo done && rm -f plugins/kimi/hooks/pre_tool_use.py"})
    check("rm_of_gate_is_write", v2.classification == "write", str(v2))
    check("rm_rule", v2.rule == g.RULE_WRITE, str(v2))


def test_edit_write_parity():
    # Same destination -> identical classification for Edit and Write.
    dest = "/mnt/repo/plugins/claude-code/hooks/pre_tool_use.py"
    vw = cls("Write", {"file_path": dest, "content": "x = 1"})
    ve = cls("Edit", {"file_path": dest, "old_string": "x = 1", "new_string": "x = 2"})
    check("both_write", vw.classification == "write" and ve.classification == "write",
          f"{vw} vs {ve}")
    check("same_marker", vw.marker == ve.marker, f"{vw.marker} vs {ve.marker}")
    # The Edit-denied-where-Write-passed FP: payload text naming the gate is NOT a
    # destination. Both must be "none" for a benign target regardless of payload.
    # (Reproduced LIVE while drafting this very file, 2026-08-13: the installed gate
    # refused an Edit whose new_string contained a hook filename, destination scratchpad.)
    benign = "/tmp/notes.md"
    vw2 = cls("Write", {"file_path": benign,
                        "content": "docs about plugins/kimi/hooks/pre_tool_use.py"})
    ve2 = cls("Edit", {"file_path": benign, "old_string": "a",
                       "new_string": "see plugins/kimi/hooks/pre_tool_use.py"})
    check("payload_not_destination",
          vw2.classification == ve2.classification == "none", f"{vw2} vs {ve2}")


# ---- Bash write positions ----
def test_bash_redirect_into_hooks_is_write():
    v = cls("Bash", {"command": "echo hacked > plugins/kimi/hooks/pre_tool_use.py"})
    check("redirect_write", v.classification == "write" and v.rule == g.RULE_WRITE, str(v))
    v2 = cls("Bash", {"command": "date >> plugins/codex/hooks/witness.py"})
    check("append_write", v2.classification == "write", str(v2))


def test_cp_dest_into_shared_is_write():
    v = cls("Bash", {"command": "cp /tmp/patched.py plugins/_shared/hestia_gate_core.py"})
    check("cp_dest_write", v.classification == "write", str(v))
    # Either element may report the hit: the dir marker (plugins/_shared) has precedence over
    # the filename rule since the dir itself joined the floor - both are the same refusal.
    check("cp_marker", v.marker in ("hestia_gate_core.py", "plugins/_shared"), str(v))


def test_cp_source_from_hooks_is_read():
    v = cls("Bash", {"command": "cp plugins/kimi/hooks/pre_tool_use.py /tmp/backup.py"})
    check("cp_source_read", v.classification == "read", str(v))


def test_mv_source_from_hooks_is_write():
    # cp copies its source; mv DESTROYS it — moving a gate file aside disarms the gate,
    # so mv operands are write positions on BOTH sides.
    v = cls("Bash", {"command": "mv plugins/kimi/hooks/pre_tool_use.py /tmp/aside.py"})
    check("mv_source_write", v.classification == "write", str(v))


def test_tee_into_hooks_is_write():
    v = cls("Bash", {"command": "cat /tmp/x.py | tee plugins/gemini/hooks/pre_tool_use.py"})
    check("tee_write", v.classification == "write", str(v))


def test_sed_in_place_on_gate_is_write_without_i_is_read():
    v = cls("Bash", {"command": "sed -i 's/deny/allow/' plugins/kimi/hooks/pre_tool_use.py"})
    check("sed_i_write", v.classification == "write", str(v))
    v2 = cls("Bash", {"command": "sed -n '1,40p' plugins/kimi/hooks/pre_tool_use.py"})
    check("sed_plain_read", v2.classification == "read", str(v2))


def test_git_checkout_pathspec_into_hooks_is_write():
    v = cls("Bash", {"command": "git checkout HEAD~3 -- plugins/kimi/hooks/pre_tool_use.py"})
    check("checkout_pathspec_write", v.classification == "write", str(v))
    v2 = cls("Bash", {"command": "git restore plugins/claude-code/hooks/witness.py"})
    check("restore_write", v2.classification == "write", str(v2))
    # A branch switch names no closure pathspec — not a targeted closure write.
    v3 = cls("Bash", {"command": "git checkout feature-branch"})
    check("branch_switch_none", v3.classification == "none", str(v3))


def test_chmod_truncate_ln_targets_are_write():
    v = cls("Bash", {"command": "chmod 777 plugins/kimi/hooks/pre_tool_use.py"})
    check("chmod_write", v.classification == "write", str(v))
    v2 = cls("Bash", {"command": "truncate -s 0 plugins/_shared/hestia_gate_mechanism.py"})
    check("truncate_write", v2.classification == "write", str(v2))
    v3 = cls("Bash", {"command": "ln -sf /tmp/evil.py plugins/kimi/hooks/pre_tool_use.py"})
    check("ln_write", v3.classification == "write", str(v3))


def test_fd_dup_is_not_a_file_target():
    v = cls("Bash", {"command": "python3 run.py > /tmp/out.log 2>&1"})
    check("fd_dup_none", v.classification == "none", str(v))


def test_heredoc_body_naming_gate_is_read_not_write():
    v = cls("Bash", {"command":
                     "cat <<EOF > /tmp/notes.md\nsee plugins/kimi/hooks/pre_tool_use.py\nEOF"})
    check("heredoc_not_write", v.classification == "read", str(v))


def test_substring_sibling_dir_does_not_match():
    # Segment matching, not substring: hooks-backup is NOT hooks.
    v = cls("Bash", {"command": "echo x > plugins/kimi/hooks-backup/pre_tool.txt"})
    check("sibling_none", v.classification == "none", str(v))
    v2 = cls("Write", {"file_path": "/x/plugins/kimi/hooks-backup/scratch.py", "content": "x"})
    check("sibling_write_tool_none", v2.classification == "none", str(v2))


def test_member_a_writing_member_b_gate_is_write():
    # Accessor-agnostic: the closure is the UNION over plugins — whose gate it is never
    # enters the predicate (self-access is delegable; governance-access is not).
    v = cls("Write", {"file_path": "/w/plugins/claude-code/hooks/pre_tool_use.py",
                      "content": "pass"}, cwd="/w/plugins/kimi")
    check("cross_member_write", v.classification == "write", str(v))


def test_registration_config_write_is_write():
    v = cls("Write", {"file_path": os.path.expanduser("~/.claude/settings.json"),
                      "content": "{}"})
    check("settings_write", v.classification == "write", str(v))
    v2 = cls("Bash", {"command": "echo '' > ~/.codex/config.toml"})
    check("codex_reg_write", v2.classification == "write", str(v2))
    v3 = cls("Bash", {"command": "cp x deploy/install-members.sh"})
    check("installer_write", v3.classification == "write", str(v3))


def test_symlink_and_dotdot_resolve_before_match():
    with tempfile.TemporaryDirectory() as td:
        hooks = os.path.join(td, "plugins", "foo", "hooks")
        os.makedirs(hooks)
        target = os.path.join(hooks, "gate.py")
        open(target, "w").write("x")
        alias = os.path.join(td, "alias")
        os.symlink(hooks, alias)
        v = cls("Write", {"file_path": os.path.join(alias, "gate.py"), "content": "y"})
        check("symlink_resolves", v.classification == "write", str(v))
        dotdot = os.path.join(td, "plugins", "foo", "docs", "..", "hooks", "gate.py")
        v2 = cls("Write", {"file_path": dotdot, "content": "y"})
        check("dotdot_resolves", v2.classification == "write", str(v2))


def test_unparseable_command_naming_closure_fails_closed():
    v = cls("Bash", {"command": "echo 'unbalanced > plugins/kimi/hooks/pre_tool_use.py"})
    check("unparseable_write", v.classification == "write", str(v))
    check("unparseable_rule", v.rule == g.RULE_WRITE_UNPARSEABLE, str(v))
    v2 = cls("Bash", {"command": "echo 'unbalanced quote in a benign command"})
    check("unparseable_benign_none", v2.classification == "none", str(v2))


# ---- registry / floor ----
def test_registry_unreadable_falls_back_to_floor_not_open():
    def broken_reader():
        raise OSError("vault offline")
    c = g.load_closure(manifest_reader=broken_reader)
    check("floor_source", c.source == "floor", c.source)
    # The floor still refuses a hooks write — unreadable registry is NEVER an open closure.
    v = g.classify("Write", {"file_path": "/x/plugins/kimi/hooks/pre_tool_use.py",
                             "content": "x"}, closure=c)
    check("floor_still_denies", v.classification == "write", str(v))
    check("floor_not_empty", c.dir_markers and c.files_anywhere, str(c))


def test_new_plugin_manifest_extends_union_without_core_edit():
    def reader():
        return {"newplugin": {"closure": {
            "dirs": ["tools/newplugin/guard"],
            "files": ["newplugin_gate.py"],
            "paths": [".newplugin/registration.json"],
        }}}
    c = g.load_closure(manifest_reader=reader)
    check("registry_source", c.source == "registry+floor", c.source)
    v = g.classify("Write", {"file_path": "/w/tools/newplugin/guard/rules.py",
                             "content": "x"}, closure=c)
    check("new_dir_write", v.classification == "write", str(v))
    v2 = g.classify("Write", {"file_path": "/anywhere/newplugin_gate.py",
                              "content": "x"}, closure=c)
    check("new_file_write", v2.classification == "write", str(v2))
    # Tighten-only: the floor's own entries all survive the union.
    for pat in FLOOR.dir_markers:
        check("floor_dirs_kept", pat in c.dir_markers, str(pat))
    for f in FLOOR.files_anywhere:
        check("floor_files_kept", f in c.files_anywhere, f)
    v3 = g.classify("Write", {"file_path": "/x/plugins/kimi/hooks/pre_tool_use.py",
                              "content": "x"}, closure=c)
    check("floor_still_active", v3.classification == "write", str(v3))


# ---- fail directions (the documented asymmetry) ----
def test_internal_error_on_write_path_fails_closed():
    def boom(tool, ti):
        raise RuntimeError("classifier bug")
    g._write_position_targets = boom
    try:
        v = cls("Write", {"file_path": "/tmp/anything.txt", "content": "x"})
        check("write_error_closed", v.classification == "write", str(v))
        check("write_error_rule", v.rule == g.RULE_INTERNAL, str(v))
    finally:
        g._write_position_targets = _REAL_WRITE_TARGETS


def test_internal_error_on_read_path_stays_read():
    def boom(tool, ti):
        raise RuntimeError("read scanner bug")
    g._read_position_mentions = boom
    try:
        v = cls("Bash", {"command": "echo hello"})
        check("read_error_stays_read", v.classification == "read", str(v))
        check("read_error_not_write", v.classification != "write", str(v))
        check("read_error_rule", v.rule == g.RULE_READ_INTERNAL, str(v))
    finally:
        g._read_position_mentions = _REAL_READ_MENTIONS


def test_classify_never_raises_on_garbage_input():
    for ti in (None, 42, "string", [], {"command": 7}, {"file_path": ["x"]},
               {"command": None}, {}):
        v = g.classify("Bash", ti, closure=FLOOR)
        check("no_raise", v.classification in ("none", "read", "write"), repr(ti))
    v = g.classify("Weird.Tool", {"file_path": "/x/plugins/kimi/hooks/a.py"}, closure=FLOOR)
    check("unknown_tool_conservative_write", v.classification == "write", str(v))


# ---- attestation seam ----
def test_attest_ok_miswired_unknown():
    import hashlib
    with tempfile.TemporaryDirectory() as td:
        good = os.path.join(td, "shim_good.py")
        bad = os.path.join(td, "shim_bad.py")
        open(good, "w").write("good shim")
        open(bad, "w").write("tampered shim")
        expected = {
            good: hashlib.sha256(b"good shim").hexdigest(),
            bad: hashlib.sha256(b"the reviewed content").hexdigest(),
            os.path.join(td, "gone.py"): "0" * 64,  # expected but absent -> miswired
        }
        r = g.attest_shims(expected, shim_paths=[os.path.join(td, "unlisted.py")])
        check("ok", r[good]["status"] == "ok", str(r[good]))
        check("miswired", r[bad]["status"] == "miswired", str(r[bad]))
        check("absent_miswired",
              r[os.path.join(td, "gone.py")]["status"] == "miswired", str(r))
        check("unlisted_unknown",
              r[os.path.join(td, "unlisted.py")]["status"] == "unknown", str(r))


def test_attest_vault_reader_failure_reports_unknown_never_ok():
    def broken():
        raise OSError("vault offline")
    r = g.attest_shims(vault_reader=broken, shim_paths=["/tmp/some_shim.py"])
    check("all_unknown", all(v["status"] == "unknown" for v in r.values()), str(r))
    check("nothing_ok", not any(v["status"] == "ok" for v in r.values()), str(r))


def test_new_file_into_shared_dir_is_write():
    # Measured 2026-08-13: the pre-consolidation gate allowed cp'ing a brand-new module into
    # plugins/_shared because it protected known FILENAMES, not the governance directory. A new
    # file beside the core is a closure write regardless of its (never-seen-before) name.
    v = cls("Write", {"file_path": "/tmp/wt-x/plugins/_shared/evil_new_module.py"})
    check("new_file_write", v.classification == "write", str(v))
    v2 = cls("Bash", {"command": "cp /tmp/draft.py /tmp/wt-x/plugins/_shared/evil_new_module.py"})
    check("cp_dest_shared_write", v2.classification == "write", str(v2))
    v3 = cls("Bash", {"command": "ls /tmp/wt-x/plugins/_shared/"})
    check("ls_shared_not_write", v3.classification != "write", str(v3))



def test_hub_deploy_closure_is_write():
    # PR #415 / web4 #709 hand-off: the hub deploy closure joins the floor. Refusing the
    # WRITE is the R7c limb; #708's STALE detection after the fact is not the same control.
    for tgt in ("/etc/systemd/system/web4-hub.service",
                "/mnt/c/exe/projects/ai-agents/web4/ratified-build.json",
                "/mnt/c/exe/projects/ai-agents/web4/tools/ratify-build.sh",
                "/mnt/c/exe/projects/ai-agents/web4/hub/target/release/hub"):
        v = cls("Write", {"file_path": tgt})
        check(f"hub_write:{tgt}", v.classification == "write", str(v))
    # Segment discipline: a bare "hub" elsewhere must NOT match the executable entry.
    v2 = cls("Write", {"file_path": "/tmp/notes/hub"})
    check("bare_hub_not_matched", v2.classification != "write", str(v2))
    v3 = cls("Bash", {"command": "systemctl status web4-hub.service"})
    check("service_read_is_read", v3.classification == "read", str(v3))

# Explicit list — NOT a globals() comprehension — so every test name is a static reference
# (tools/ci_selfexec_test.py rejects test functions whose execution cannot be established
# statically; a dynamic sweep leaves each name un-referenced and reads as inert).
ALL = [
    test_readonly_find_naming_hook_is_read,
    test_chained_benign_rm_not_write_unless_target_in_closure,
    test_edit_write_parity,
    test_bash_redirect_into_hooks_is_write,
    test_cp_dest_into_shared_is_write,
    test_cp_source_from_hooks_is_read,
    test_mv_source_from_hooks_is_write,
    test_tee_into_hooks_is_write,
    test_sed_in_place_on_gate_is_write_without_i_is_read,
    test_git_checkout_pathspec_into_hooks_is_write,
    test_chmod_truncate_ln_targets_are_write,
    test_fd_dup_is_not_a_file_target,
    test_heredoc_body_naming_gate_is_read_not_write,
    test_substring_sibling_dir_does_not_match,
    test_member_a_writing_member_b_gate_is_write,
    test_registration_config_write_is_write,
    test_symlink_and_dotdot_resolve_before_match,
    test_unparseable_command_naming_closure_fails_closed,
    test_registry_unreadable_falls_back_to_floor_not_open,
    test_new_plugin_manifest_extends_union_without_core_edit,
    test_internal_error_on_write_path_fails_closed,
    test_internal_error_on_read_path_stays_read,
    test_classify_never_raises_on_garbage_input,
    test_attest_ok_miswired_unknown,
    test_attest_vault_reader_failure_reports_unknown_never_ok,
    test_new_file_into_shared_dir_is_write,
    test_hub_deploy_closure_is_write,
]

if __name__ == "__main__":
    print("governance-closure classifier — write-position keying + fail-direction contract")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
