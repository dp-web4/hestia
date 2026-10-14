#!/usr/bin/env python3
"""A seat's EXECUTED governance surface — what its harness registration actually runs — is closure.

The shared closure is built from install DECLARATIONS. A harness executes whatever its
registration file POINTS AT, and on a seat installed by an older release that can be somewhere
no declaration names (a legacy members dir; a split layout with the gate in one dir and a hook in
another). Measured on a seat in use: the registration file was protected and the gate it pointed
at was not. Any gap between the declared and the executed surface is an unprotected gate.

So the common gate reads its own harness's registration (`registered_hooks`, the same readers as
the timeout bound, every event) and governs (`registered_surface`):
  * the running gate's own realpath and directory — ALWAYS, whatever the registration says
    (fail closed: an unreadable registration can only leave this minimum, never fewer);
  * every registered hook whose realpath lies in a hestia-owned dir (the gate's dir, the member's
    declared dest) — the reconciler's and the census's ownership rule;
  * NOT a hook another plugin registered from its own dir, even under a hestia basename.

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hestia_governance_closure as g  # noqa: E402
import hestia_single_gate as gate  # noqa: E402

ENTRY = "pre_" + "tool_use.py"
WIT = "wit" + "ness.py"
LAW = "law_" + "inject.py"
GEM = "before_" + "tool.py"


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {str(detail)[:900]}")


def _home():
    return os.path.realpath(tempfile.mkdtemp(prefix="regsurf-home-"))


def _touch(path, text="# hook\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _json_reg(path, events):
    """events: {event: [command, ...]} in Claude Code's nested shape."""
    doc = {"hooks": {ev: [{"matcher": "*", "hooks": [{"type": "command", "command": c, "timeout": 20}
                                                       for c in cmds]}]
                     for ev, cmds in events.items()}}
    _touch(path, json.dumps(doc))


HARNESS_JSON = {"event": "PreToolUse", "timeout_unit_seconds": 1, "default_timeout_seconds": 60,
                "margin_seconds": 1.5, "on_timeout": "fail-open",
                "registrations": ({"reader": "json-hook-commands", "layout": "nested",
                                   "path": "~/.claude/settings.json"},
                                  {"reader": "json-hook-commands", "layout": "nested",
                                   "path": "~/.claude/settings.local.json"})}


def _surface(harness, self_path, home, member="claude-code"):
    env = {"HOME": home, "PATH": os.environ.get("PATH", "")}
    b = gate.harness_bound(harness, self_path, 0.0, env=env)
    prof = gate.GateProfile(member_id=member, identity_path=None, gate_path=self_path)
    return gate.registered_surface(b, prof, env=env), b


def _write(target, c, cwd="/"):
    return g.classify("Write", {"file_path": target, "content": "x"}, cwd=cwd, closure=c)


def test_legacy_members_dir_is_governed():
    """The layout measured on a seat in use: the registration points the gate and the witness at
    a legacy members dir no declaration names. RED on the declared closure alone."""
    home = _home()
    legacy = os.path.join(home, ".hestia", "members", "claude-code")
    gate_file, wit = _touch(os.path.join(legacy, ENTRY)), _touch(os.path.join(legacy, WIT))
    _json_reg(os.path.join(home, ".claude", "settings.json"),
              {"PreToolUse": [f"python3 {gate_file}"], "PostToolUse": [f"python3 {wit}"]})
    static = g.default_closure()
    check("control-declared-closure-misses-it", _write(gate_file, static).classification != "write",
          _write(gate_file, static))
    s, _b = _surface(HARNESS_JSON, gate_file, home)
    check("own-dir", legacy in s.own_dirs, s)
    check("targets", gate_file in s.targets and wit in s.targets, s)
    check("entry", gate_file in s.entries, s)
    c = s.closure()
    for t in (gate_file, wit, os.path.join(legacy, "dropped_beside.py")):
        v = _write(t, c)
        check(f"governed-{os.path.basename(t)}", v.classification == "write", v)
    # shell forms reach it too
    v = g.classify("Bash", {"command": f"cd {legacy} && echo x > {ENTRY}"}, cwd="/", closure=c)
    check("governed-shell", v.classification == "write", v)


def test_split_layout_both_dirs_are_governed():
    """Gate and witness in a legacy plugin dir, another hook at the declared dest."""
    home = _home()
    legacy = os.path.join(home, ".claude", "plugins", "hestia", "hooks")
    dest = os.path.join(home, ".claude", "hooks", "hestia")
    gate_file, wit = _touch(os.path.join(legacy, ENTRY)), _touch(os.path.join(legacy, WIT))
    law = _touch(os.path.join(dest, LAW))
    _json_reg(os.path.join(home, ".claude", "settings.json"),
              {"PreToolUse": [f"python3 {gate_file}"], "PostToolUse": [f"python3 {wit}"],
               "UserPromptSubmit": [f"python3 {law}"]})
    s, _b = _surface(HARNESS_JSON, gate_file, home)
    check("both-own-dirs", legacy in s.own_dirs and dest in s.own_dirs, s)
    check("all-targets", {gate_file, wit, law} <= set(s.targets), s)
    c = s.closure()
    for t in (gate_file, wit, law, os.path.join(legacy, "x.py"), os.path.join(dest, "y.py")):
        check(f"governed-{t[len(home):]}", _write(t, c).classification == "write", _write(t, c))


def test_an_unreadable_registration_fails_closed():
    """A source that exists but cannot be parsed: the gate's own realpath and dir stay governed
    (the minimum), and the source is reported as unreadable."""
    home = _home()
    legacy = os.path.join(home, ".hestia", "members", "claude-code")
    gate_file = _touch(os.path.join(legacy, ENTRY))
    _touch(os.path.join(home, ".claude", "settings.json"), "{ not json")
    s, _b = _surface(HARNESS_JSON, gate_file, home)
    check("reported-unreadable", any("settings.json" in u for u in s.unreadable), s)
    c = s.closure()
    for t in (gate_file, os.path.join(legacy, "anything.py")):
        check(f"minimum-{os.path.basename(t)}", _write(t, c).classification == "write", _write(t, c))
    # And with no registration at all, the same minimum.
    home2 = _home()
    g2 = _touch(os.path.join(home2, ".hestia", "members", "claude-code", ENTRY))
    s2, _ = _surface(HARNESS_JSON, g2, home2)
    check("no-registration-minimum", _write(g2, s2.closure()).classification == "write", s2)


def test_a_foreign_hook_is_not_governed_by_being_registered():
    """Another plugin's hooks in the same registration file — one under a hestia basename — are
    not hestia's: they stay ordinary work."""
    home = _home()
    legacy = os.path.join(home, ".hestia", "members", "claude-code")
    gate_file = _touch(os.path.join(legacy, ENTRY))
    foreign_same_name = _touch(os.path.join(home, "vendor", "hardbound", "bin", ENTRY))
    foreign_other = _touch(os.path.join(home, "tools", "lint.sh"))
    _json_reg(os.path.join(home, ".claude", "settings.json"),
              {"PreToolUse": [f"python3 {gate_file}", f"python3 {foreign_same_name}"],
               "PostToolUse": [f"bash {foreign_other}"]})
    s, _b = _surface(HARNESS_JSON, gate_file, home)
    check("foreign-not-owned", foreign_same_name not in s.targets and foreign_other not in s.targets, s)
    c = s.closure()
    for t in (foreign_same_name, foreign_other):
        check(f"foreign-ordinary-{os.path.basename(t)}", _write(t, c).classification != "write",
              _write(t, c))
    check("own-still-governed", _write(gate_file, c).classification == "write", _write(gate_file, c))


def test_toml_registrations_are_read_too():
    """Both readers: a nested TOML (codex shape) and a flat one (kimi shape), every event."""
    home = _home()
    for layout, member, text in (
        ("nested", "codex",
         '[[hooks.PreToolUse]]\nmatcher = "*"\n[[hooks.PreToolUse.hooks]]\ntype = "command"\n'
         'command = "python3 {g}"\ntimeout = 20\n'
         '[[hooks.PostToolUse]]\nmatcher = "*"\n[[hooks.PostToolUse.hooks]]\ntype = "command"\n'
         'command = "python3 {w}"\ntimeout = 20\n'),
        ("flat", "kimi-code",
         '[[hooks]]\nevent = "PreToolUse"\ncommand = "python3 {g}"\ntimeout = 20\n'
         '[[hooks]]\nevent = "PostToolUse"\ncommand = "python3 {w}"\ntimeout = 20\n'),
    ):
        legacy = os.path.join(home, ".hestia", "members", member)
        gate_file, wit = _touch(os.path.join(legacy, ENTRY)), _touch(os.path.join(legacy, WIT))
        cfg = os.path.join(home, f".{member}-cfg", "config.toml")
        _touch(cfg, text.format(g=gate_file, w=wit))
        harness = dict(HARNESS_JSON, registrations=({"reader": "toml-hook-commands", "layout": layout,
                                                     "path": cfg},))
        s, _b = _surface(harness, gate_file, home, member=member)
        check(f"{layout}-targets", {gate_file, wit} <= set(s.targets), s)
        check(f"{layout}-witness-governed", _write(wit, s.closure()).classification == "write", s)


def test_a_registered_entry_no_declaration_covers_escalates_under_the_entry_marker():
    """Pricing: a write to a registered gate entry the declared closure does not cover carries the
    registered-entry marker, which the daemon prices like a declared entry. A write to another
    file in the same dir carries the directory, not the marker."""
    home = _home()
    legacy = os.path.join(home, ".hestia", "members", "gemini")
    gate_file = _touch(os.path.join(legacy, GEM))
    _json_reg(os.path.join(home, ".gemini", "settings.json"), {"BeforeTool": [f"python3 {gate_file}"]})
    harness = dict(HARNESS_JSON, event="BeforeTool",
                   registrations=({"reader": "json-hook-commands", "layout": "nested",
                                   "path": "~/.gemini/settings.json"},))
    s, _b = _surface(harness, gate_file, home, member="gemini")

    class Inv:
        registered = s

        def __init__(self, ev):
            self.event = ev

    def verdict(target):
        ev = gate.GateEvent(tool="write_file", tool_input={"file_path": target, "content": "x"},
                            cwd="/", session_id="s", raw={})
        return gate._closure_verdict(Inv(ev))

    v = verdict(gate_file)
    check("entry-write", v.classification == "write" and v.marker == gate.REGISTERED_ENTRY_MARKER, v)
    v = verdict(os.path.join(legacy, "other.py"))
    check("dir-write-not-entry-marker", v.classification == "write"
          and v.marker != gate.REGISTERED_ENTRY_MARKER, v)

    # A WILDCARD that can expand onto the entry carries the marker too (Codex review of #1247
    # at 18f91db, P1): the daemon knows only declared locations, so evidence the gate drops here
    # is unrecoverable there. One that cannot reach the entry is the negative control.
    def bash(command):
        ev = gate.GateEvent(tool="Bash", tool_input={"command": command}, cwd="/",
                            session_id="s", raw={})
        return ev, gate._closure_verdict(Inv(ev))

    # `[^z]` and `[[:alpha:]]` are the Codex re-review's (notice 18830, P1): fnmatch missed both.
    for pattern in ("before_*", "before_too?.py", "[ab]efore_tool.py", "[^z]efore_tool.py",
                    "[!z]efore_tool.py", "[[:alpha:]]efore_tool.py", "[]b]efore_tool.py",
                    # Escapes (Codex review of held 29ae13a6, notice 18931): whatever the
                    # producer's quote/escape normalization makes of these, they still mark.
                    "b\\efore_*", "\\before_tool.py", "before\\_tool.py"):
        ev, v = bash("touch " + os.path.join(legacy, pattern))
        check(f"glob-entry-marker:{pattern}", v.classification == "write"
              and v.marker == gate.REGISTERED_ENTRY_MARKER, v)
        targets, _complete = gate._closure_write_set(ev, s.closure())
        check(f"glob-entry-reaches:{pattern}",
              any(gate._reaches_registered_entry(t, s.entries) for t in targets), targets)
    ev, v = bash("touch " + os.path.join(legacy, "after_*"))
    check("glob-not-entry", v.classification == "write"
          and v.marker != gate.REGISTERED_ENTRY_MARKER, v)
    targets, _complete = gate._closure_write_set(ev, s.closure())
    check("glob-not-entry-reaches", not any(gate._reaches_registered_entry(t, s.entries)
                                            for t in targets), targets)


def test_an_unresolved_destination_leaves_the_write_set_incomplete():
    """`complete` is about the whole write set, not the targets that matched (Codex review of
    #1247 at 18f91db, P1 inherited from #1239). A `$VAR` destination — in the protected dir or
    beside a known target — and a relative destination with no cwd to pin it are unenumerated,
    so the daemon prices the highest bar. A literal, located write set stays complete."""
    home = _home()
    hooks = os.path.join(home, "plugins", "m", "hooks")

    def write_set(command, cwd="/"):
        ev = gate.GateEvent(tool="Bash", tool_input={"command": command}, cwd=cwd,
                            session_id="s", raw={})
        return gate._closure_write_set(ev)

    for label, command, cwd in (
        ("var-in-protected-dir", f"touch {hooks}/$TARGET", "/"),
        ("var-after-known", f'touch {hooks}/ordinary.txt; touch "$TARGET"', "/"),
        ("relative-no-cwd", "touch plugins/m/hooks/ordinary.txt", None),
    ):
        targets, complete = write_set(command, cwd)
        check(f"incomplete:{label}", targets and not complete, (targets, complete))
    for label, command, cwd in (
        ("literal-absolute", f"touch {hooks}/ordinary.txt {hooks}/{ENTRY}", "/"),
        ("relative-with-cwd", "touch plugins/m/hooks/ordinary.txt", home),
        ("glob-in-protected-dir", f"touch {hooks}/*.py", "/"),
    ):
        targets, complete = write_set(command, cwd)
        check(f"complete:{label}", targets and complete, (targets, complete))


def test_the_degenerate_anchor_is_not_widened():
    """A gate run from a home or the root does not govern the whole home: only the file itself."""
    home = _home()
    gate_file = _touch(os.path.join(home, ENTRY))
    s, _b = _surface(HARNESS_JSON, gate_file, home)
    check("no-home-dir-marker", home not in s.own_dirs, s)
    check("file-itself-governed", _write(gate_file, s.closure()).classification == "write", s)
    check("home-neighbour-ordinary",
          _write(os.path.join(home, "notes.md"), s.closure()).classification != "write", s)


def test_the_entry_matcher_covers_every_bash_expansion():
    """Differential against Bash itself (Codex re-review of #1247, notice 18830): for each
    pattern, every name Bash's pathname expansion produces in a directory of candidate names
    must satisfy `_reaches_registered_entry`. Over-matching is allowed (it prices higher);
    missing one is the P1."""
    import subprocess
    d = tempfile.mkdtemp(prefix="glob-diff-")
    # Literal-bracket and literal-wildcard names are Codex's notice-18931 P2: an escaped `\\[`
    # is a literal `[`, and the earlier corpus had no name it could expand onto.
    names = [GEM, "after_tool.py", "Before_tool.py", "]efore_tool.py", "zefore_tool.py",
             "b.py", "before_tool.pyc", "x[ab]yes", "x[ab]efore_tool.py", "[b]efore_tool.py",
             "*efore_tool.py", "?efore_tool.py", "[=]efore_tool.py", "[:]efore_tool.py"]
    for name in names:
        _touch(os.path.join(d, name))
    patterns = ["before_*", "[^z]efore_tool.py", "[!z]efore_tool.py", "[^b]efore_tool.py",
                "[[:alpha:]]efore_tool.py", "[[:upper:]]efore_tool.py", "[]b]efore_tool.py",
                "[!]]efore_tool.py", "[a-c]efore_tool.py", "[[=b=]]efore_tool.py",
                "[\\b]efore_tool.py", "?efore_*", "*[[:punct:]]py", "[b", "[!a-z]*",
                "x\\[ab]y*", "x\\[ab]efore_*", "\\[b]*", "\\[b\\]efore_tool.py", "\\**",
                "\\?efore*", "b\\efore_*", "\\before_tool.py", "x\\[a*", "*\\]*",
                "[[=b=]]*", "[[=e=]]*", "[[.b.]]*", "[[:punct:]]*", "[![:alpha:]]*", "[[]*"]
    for pattern in patterns:
        out = subprocess.run(["bash", "-c", 'shopt -s nullglob; cd "$1" && for f in $2; '
                              'do printf "%s\\0" "$f"; done', "_", d, pattern],
                             capture_output=True, text=True, check=True).stdout
        for got in filter(None, out.split("\0")):
            full = os.path.join(d, got)
            check(f"bash-expansion-covered:{pattern}->{got}",
                  gate._reaches_registered_entry(os.path.join(d, pattern), [full]),
                  (pattern, got))


ALL = [
    test_legacy_members_dir_is_governed,
    test_split_layout_both_dirs_are_governed,
    test_an_unreadable_registration_fails_closed,
    test_a_foreign_hook_is_not_governed_by_being_registered,
    test_toml_registrations_are_read_too,
    test_a_registered_entry_no_declaration_covers_escalates_under_the_entry_marker,
    test_an_unresolved_destination_leaves_the_write_set_incomplete,
    test_the_degenerate_anchor_is_not_widened,
    test_the_entry_matcher_covers_every_bash_expansion,
]

if __name__ == "__main__":
    print("registered surface — what a seat's harness registration actually runs is closure")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
