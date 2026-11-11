#!/usr/bin/env python3
"""Build the held patch for hestia #1494 / #1314 over the worktree's HEAD, in memory, writing no governed path.

Re-runnable at apply time: every edit is an exact-once anchor in HEAD's gate core, so a moved main costs a
re-run, not a review cycle (the #1327 v3 lesson).

  1. Gate 1a matches the env-file token as a file name (`forbidden_hit`), at both text-sweep sites.
  2. `_CMD_SPECS` gains gh (`--jq`/`-q` values are strings) and jq (filter first; `-f` program file).
  3. A program FILE option (`-f`, `--file=`, `-fFILE`, clustered `-rf`) means the first operand is not the pattern.
  4. tools/gate_false_deny_test.py (new).
The hooks-gt copy and the manifests are emitted by HEAD's own tools/hooks_gt.emit_patch with the core read
served from the patched copy. The patch is named by its sha256 and verified: applied in memory to HEAD's
blobs it must reproduce the patched core, the new test and hooks_gt.build()'s tree exactly.

argv: <hestia worktree at the base> <out dir>
Writes: <out>/core_rev.py (neutral name) and <out>/<sha256>.patch.
No forbidden token is spelled in this source: the env token is read from HEAD's FORBIDDEN_DEFAULT.
"""
import difflib
import hashlib
import pathlib
import re
import subprocess
import sys

WT, OUT = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
CORE = "plugins/_shared/hestia_gate_core.py"
TEST = "tools/gate_false_deny_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "HEAD:" + path], cwd=WT).decode()


def once(text, old, new):
    assert text.count(old) == 1, ("anchor not exactly once", old[:80], text.count(old))
    return text.replace(old, new)


def patch_core(src):
    tok = re.search(r'FORBIDDEN_DEFAULT = \(([^)]*)\)', src).group(1)
    env = next(t.strip().strip('"') for t in tok.split(",") if t.strip().strip('"').endswith("env"))
    esc = re.escape(env)

    # 1. the matcher, defined beside forbidden_tokens, used at both gate 1a text sweeps
    src = once(src, '''def forbidden_tokens(profile: HarnessProfile) -> tuple:
    extra = os.environ.get(profile.forbidden_extra_env, "")
    return FORBIDDEN_DEFAULT + tuple(t.strip() for t in extra.split(",") if t.strip())
''', f'''def forbidden_tokens(profile: HarnessProfile) -> tuple:
    extra = os.environ.get(profile.forbidden_extra_env, "")
    return FORBIDDEN_DEFAULT + tuple(t.strip() for t in extra.split(",") if t.strip())


#: The env-file token is matched as a FILE NAME, not a substring (#1494, #639). It is a hit unless it is
#: glued inside one identifier on BOTH sides: `os.environ`, `venv.EnvBuilder` and `environ` are not the
#: file, while `{env}`, `./{env}.local`, `{env}rc`, `prod{env}`, `app{env}.bak` and a `\\{env}` regex still are.
#: `process{env}.X` stays a hit too: a word before and a dot after is also how a named env file reads.
#: Measured on McNugget, 2026-11-03..10: 3 of the 4 egress.secret false denies were the glued shape.
#: Every other token keeps the substring match.
_ENV_FILE = re.compile(r"(?<![a-z0-9_]){esc}|{esc}(?![a-z0-9_])")


def forbidden_hit(token: str, low: str) -> bool:
    """Gate 1a's match of one forbidden token against LOWERED text."""
    if token == "{env}":
        return _ENV_FILE.search(low) is not None
    return token in low
''')
    sweep = '''        for f in forbidden:
            if f in low:
'''
    assert src.count(sweep) == 2, src.count(sweep)
    src = src.replace(sweep, '''        for f in forbidden:
            if forbidden_hit(f, low):
''')

    # 2. gh's jq option and jq's filter are expressions, not paths (#1314)
    src = once(src, '''    "git": {"string_opts": {"-m", "--message", "--grep", "--author", "--format", "--pretty", "-S", "-G"}},
}
''', '''    "git": {"string_opts": {"-m", "--message", "--grep", "--author", "--format", "--pretty", "-S", "-G"}},
    # gh's `-q`/`--jq` takes a jq expression in every subcommand that has it: 55 of 55 in `gh help
    # reference` (gh 2.x, McNugget, 2026-11-10). `--template` and `-t` are NOT listed: under `repo
    # edit` and `auth status` they are booleans, so the next word would be swallowed (#1314).
    "gh": {"string_opts": {"--jq", "-q"}},
    # jq's first operand is its FILTER, unless `-f`/`--from-file` supplies the program (then every
    # operand is a file). `-L` and its jq 1.8 long form `--library-path` name a library directory
    # and are judged (legion-claude on #1550: without the long form its DIR became the filter).
    "jq": {"pattern_first": True, "file_opts": {"-f", "--from-file"},
           "value_opts": {"--indent", "-L", "--library-path"}},
}
''')

    # 3. a program FILE option means the first operand is a file, not the pattern
    src = once(src, '''            if opt in spec.get("code_opts", ()):
                code(w)
                continue
            if (opt in spec.get("delim_opts", ())''', '''            if opt in spec.get("code_opts", ()):
                code(w)
                continue
            if opt in spec.get("file_opts", ()):
                # The program came from a file (`grep -f P`, `sed -f S`, `jq -f F`): every operand
                # is a file. Before this the first one was taken as the pattern and never judged.
                state["pattern_given"] = True
            if (opt in spec.get("delim_opts", ())''')
    src = once(src, '''                if name in spec.get("pattern_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (name in spec.get("delim_opts", ())''', '''                if name in spec.get("pattern_opts", ()) or name in spec.get("file_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (name in spec.get("delim_opts", ())''')
    src = once(src, '''                if w[:2] in spec.get("pattern_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (w[:2] in spec.get("delim_opts", ())''', '''                if w[:2] in spec.get("pattern_opts", ()) or w[:2] in spec.get("file_opts", ()):
                    state["pattern_given"] = True
                if uglob or not (w[:2] in spec.get("delim_opts", ())''')
    src = once(src, '''            m = _ATTACHED_OPT.match(w)
            if m:
''', '''            run = re.match(r"-[A-Za-z0-9]+", w) if not w.startswith("--") and len(w) > 2 else None
            valued = spec.get("file_opts", set()) | spec.get("value_opts", set())
            fat = next((k for k in range(1, run.end()) if "-" + w[k] in valued), None) if run else None
            if fat is not None and head == "sed" and "i" in w[1:fat]:
                fat = None          # GNU `sed -if S`: `-i` takes the rest as its backup suffix
            if fat is not None:
                # A clustered option that takes a value (`grep -rf P`, `grep -nfP`, `jq -rf F`,
                # `jq -nL DIR`): getopt reads the letters before it as flags and hands it the rest of
                # the word, or the next word, which is judged as that option's value always is. A
                # program-file option also means every operand is a file. A letter before it that
                # itself takes a value only makes this judge more, never less.
                if "-" + w[fat] in spec.get("file_opts", ()):
                    state["pattern_given"] = True
                if fat == len(w) - 1:
                    state["pending"] = "-" + w[fat]
                else:
                    emit(w[fat + 1:], uglob)
                continue
            m = _ATTACHED_OPT.match(w)
            if m:
''')
    return src


def diff(path, old, new):
    a = old.splitlines(True) if old is not None else []
    b = new.splitlines(True)
    hdr = f"diff --git a/{path} b/{path}\n" + ("new file mode 100755\n" if old is None else "")
    return hdr + "".join(difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{path}", f"b/{path}"))


def hunks(section):
    out, cur = [], None
    for line in section.splitlines(keepends=True)[1:]:
        if line.startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))?", line)
            cur = {"start": int(m.group(1)) - 1, "old": [], "new": []}
            out.append(cur)
        elif cur is not None and line[:1] in " +-" and not line.startswith(("--- ", "+++ ")):
            if line[0] in " -":
                cur["old"].append(line[1:])
            if line[0] in " +":
                cur["new"].append(line[1:])
    return out


def strict_apply(old_text, section):
    lines = old_text.splitlines(keepends=True) if old_text is not None else []
    out, pos = [], 0
    for h in hunks(section):
        start = max(h["start"] if h["old"] else h["start"] + 1, 0) if old_text is not None else 0
        out.extend(lines[pos:start])
        assert lines[start:start + len(h["old"])] == h["old"], ("strict", start)
        out.extend(h["new"])
        pos = start + len(h["old"])
    out.extend(lines[pos:])
    return "".join(out)


def sections(text):
    return {sec.splitlines()[0].split(" b/", 1)[1]: sec for sec in text.split("diff --git ")[1:]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    core_new = patch_core(blob(CORE))
    test_new = (HERE / "gate_false_deny_rows.py").read_text(encoding="utf-8")
    (OUT / "core_rev.py").write_text(core_new, encoding="utf-8")

    sys.path.insert(0, str(WT / "tools"))
    import hooks_gt
    assert hooks_gt.check(WT) == [], hooks_gt.check(WT)
    core_abs = WT / CORE
    real_read = pathlib.Path.read_bytes

    def served(self):
        return core_new.encode() if self.resolve() == core_abs else real_read(self)

    pathlib.Path.read_bytes = served
    try:
        gt_out = OUT / "gt.part"
        n = hooks_gt.emit_patch(WT, gt_out)
        tree = hooks_gt.build(WT)
    finally:
        pathlib.Path.read_bytes = real_read
    print(f"hooks_gt emitted {n} files")

    body = diff(CORE, blob(CORE), core_new) + gt_out.read_text(encoding="utf-8") + diff(TEST, None, test_new)
    gt_out.unlink()
    sha = hashlib.sha256(body.encode()).hexdigest()
    for old in OUT.glob("*.patch"):
        old.rename(OUT / (old.name + ".prev"))
    (OUT / f"{sha}.patch").write_text(body, encoding="utf-8")

    for path, sec in sections(body).items():
        old = None if path == TEST else blob(path)
        got = strict_apply(old, sec)
        want = core_new if path == CORE else test_new if path == TEST else tree[path].decode()
        assert got == want, f"verify: {path}"
        print(f"  ok  {path}")
    assert hooks_gt.strip_header(tree["hooks-gt/_shared/hestia_gate_core.py"]) == core_new.encode()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT).decode().strip()
    print(f"base {head}\npatch {OUT / (sha + '.patch')}\nsha256 {sha}")


main()
