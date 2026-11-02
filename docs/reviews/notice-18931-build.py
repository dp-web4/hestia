#!/usr/bin/env python3
"""Build #1247's next held delta in memory: 29ae13a6 + Codex 18931's escaped-bracket P2 fix.

Never writes a governed path: sources are reconstructed in memory over 18f91db, tested in
memory, the GT tree is rebuilt in memory, and the only file written is the digest-named patch.
argv: <hestia worktree> <base-tree dir (18f91db extracted)> <out dir for the patch>"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

WT, BASE, OUT = (Path(a) for a in sys.argv[1:4])
OLD = "29ae13a63a5d29824ef610a562af05044a6636af81e005528375208c67154655"
sys.dont_write_bytecode = True
GATE = "plugins/_shared/hestia_single_gate.py"
TEST = "plugins/_shared/registered_surface_test.py"


def blob(path):
    return subprocess.check_output(["git", "show", "18f91db:" + path], cwd=WT)


def reconstructed():
    patch = (WT / "held" / (OLD + ".patch")).read_bytes()
    assert hashlib.sha256(patch).hexdigest() == OLD
    result = {}
    for section in patch.decode().split("diff --git ")[1:]:
        path = section.splitlines()[0].split(" b/", 1)[1]
        old = blob(path).decode().splitlines(keepends=True)
        out, pos, active = [], 0, False
        for line in section.splitlines(keepends=True)[1:]:
            if line.startswith("@@ "):
                start = int(re.match(r"@@ -(\d+)", line).group(1)) - 1
                out.extend(old[pos:start])
                pos, active = start, True
            elif active and line[:1] in " +-":
                if line[0] in " -":
                    assert old[pos] == line[1:], (path, pos)
                    pos += 1
                if line[0] in " +":
                    out.append(line[1:])
        out.extend(old[pos:])
        result[path] = "".join(out)
    return result


def sub1(text, old, new):
    assert text.count(old) == 1, old[:60]
    return text.replace(old, new)


def fix_gate(src):
    src = sub1(src, """    negated, ranged, POSIX class, whatever its locale reading — stands for ANY one character;
    `*` and `?` may cross `/`; a backslash is optional before what it escapes; and a `[` with no
    close Bash would accept makes the rest of the pattern match anything. Each choice can only
    widen the set.\"\"\"""",
                """    negated, ranged, POSIX class, whatever its locale reading — stands for ANY one character;
    `*` and `?` may cross `/`; a backslash is optional before the ordinary character it escapes,
    and consumes it; a backslash before `*`, `?` or `[` makes the rest of the pattern match
    anything; and a `[` with no close Bash would accept does the same. Each choice can only
    widen the set.

    The escaped wildcard falls back rather than reading `\\\\[` as a literal `[` (Codex review of
    held 29ae13a6, notice 18931, P2): the backslash used not to consume what it escaped, so the
    `[` of `x\\\\[ab]y*` opened a bracket and `[ab]` shrank to one character, missing the
    `x[ab]yes` Bash expands it onto. A literal reading would fix that pattern, but whether this
    backslash still escapes depends on quoting the producer may already have removed (a quoted
    backslash before a live `[`), and the safe answer to an uncertain reading is the wider one.\"\"\"""")
    src = sub1(src, """        elif c == "\\\\":
            out.append(r"\\\\?")
""", """        elif c == "\\\\":
            if i + 1 < n and pattern[i + 1] in _GLOB_CHARS:
                out.append(r"\\\\?.*")
                break
            out.append(r"\\\\?")
            if i + 1 < n:
                i += 1
                out.append(re.escape(pattern[i]))
""")
    src = sub1(src, """            end = _bracket_end(pattern, i)
            if end is None:
                out.append(".*")
                break
""", """            end = _bracket_end(pattern, i)
            if end is None or "[" in pattern[i + 1:end]:
                out.append(".*")
                break
""")
    src = sub1(src, """    backslash before a live `[`), and the safe answer to an uncertain reading is the wider one.\"\"\"""",
               """    backslash before a live `[`), and the safe answer to an uncertain reading is the wider one.

    A bracket holding a `[` falls back too. Bash's own reading forks there: 5.2 expands
    `[[=b=]]*` onto `bx` AND onto `[b]x` and `[=]x`, reading the first `[` as a literal and
    `[=b=]` as the bracket. That fork surfaced when notice 18931's literal-bracket names joined
    the differential corpus; one character for the whole bracket missed it.\"\"\"""")
    return src


def fix_test(src):
    src = sub1(src, """                    "[!z]efore_tool.py", "[[:alpha:]]efore_tool.py", "[]b]efore_tool.py"):""",
               """                    "[!z]efore_tool.py", "[[:alpha:]]efore_tool.py", "[]b]efore_tool.py",
                    # Escapes (Codex review of held 29ae13a6, notice 18931): whatever the
                    # producer's quote/escape normalization makes of these, they still mark.
                    "b\\\\efore_*", "\\\\before_tool.py", "before\\\\_tool.py"):""")
    src = sub1(src, """    names = [GEM, "after_tool.py", "Before_tool.py", "]efore_tool.py", "zefore_tool.py",
             "b.py", "before_tool.pyc"]""",
               """    # Literal-bracket and literal-wildcard names are Codex's notice-18931 P2: an escaped `\\\\[`
    # is a literal `[`, and the earlier corpus had no name it could expand onto.
    names = [GEM, "after_tool.py", "Before_tool.py", "]efore_tool.py", "zefore_tool.py",
             "b.py", "before_tool.pyc", "x[ab]yes", "x[ab]efore_tool.py", "[b]efore_tool.py",
             "*efore_tool.py", "?efore_tool.py", "[=]efore_tool.py", "[:]efore_tool.py"]""")
    src = sub1(src, """                "[\\\\b]efore_tool.py", "?efore_*", "*[[:punct:]]py", "[b", "[!a-z]*"]""",
               """                "[\\\\b]efore_tool.py", "?efore_*", "*[[:punct:]]py", "[b", "[!a-z]*",
                "x\\\\[ab]y*", "x\\\\[ab]efore_*", "\\\\[b]*", "\\\\[b\\\\]efore_tool.py", "\\\\**",
                "\\\\?efore*", "b\\\\efore_*", "\\\\before_tool.py", "x\\\\[a*", "*\\\\]*",
                "[[=b=]]*", "[[=e=]]*", "[[.b.]]*", "[[:punct:]]*", "[![:alpha:]]*", "[[]*"]""")
    return src


def module(name, path, source):
    loaded = types.ModuleType(name)
    loaded.__file__ = str(WT / path)
    sys.modules[name] = loaded
    exec(compile(source, loaded.__file__, "exec"), loaded.__dict__)
    return loaded


def test(sources, label):
    for name in ("hestia_gate_core", "hestia_gate_mechanism", "hestia_governance_closure"):
        path = "plugins/_shared/" + name + ".py"
        assert (WT / path).read_bytes() == blob(path), path
    if str(WT / "plugins/_shared") not in sys.path:
        sys.path.insert(0, str(WT / "plugins/_shared"))
    gate = module("hestia_single_gate", GATE, sources[GATE])
    suite = module("held_registered_surface_test", TEST, sources[TEST])
    fails = []
    for t in suite.ALL:
        try:
            t()
        except BaseException as e:  # noqa: BLE001
            fails.append(f"{t.__name__}: {str(e)[:300]}")
    print(f"[{label}] {len(suite.ALL) - len(fails)}/{len(suite.ALL)} passed")
    for f in fails:
        print("   FAIL", f)
    with tempfile.TemporaryDirectory(prefix="held-matcher-") as d:
        for pattern, expected in ((r"x\[ab]y*", "x[ab]yes"), (r"x\[ab]efore_*", "x[ab]efore_tool.py")):
            ok = gate._reaches_registered_entry(os.path.join(d, pattern), [os.path.join(d, expected)])
            print(f"[{label}] Codex 18931 case {pattern!r} -> {expected!r}: matched={ok}")
    return gate, not fails


def gt_tree(sources):
    sys.path.insert(0, str(BASE / "tools"))
    import hooks_gt as H
    decl = H.units(BASE)
    tree = {}
    for unit, u in decl.items():
        for gt_rel, src_rel in u["files"].items():
            data = sources[src_rel].encode() if src_rel in sources else (BASE / src_rel).read_bytes()
            tree[f"{H.GT_DIR}/{unit}/{gt_rel}"] = H.with_header(data, gt_rel)
    for unit, m in H._compose(BASE, lambda unit, rel: H.canonical_digest(tree[f"{H.GT_DIR}/{unit}/{rel}"])).items():
        tree[f"{H.GT_DIR}/{unit}/manifest.json"] = (json.dumps(m, indent=2) + "\n").encode()
    return H, tree


def main():
    held = reconstructed()
    test(held, "held 29ae13a6")
    new = dict(held)
    new[GATE] = fix_gate(held[GATE])
    new[TEST] = fix_test(held[TEST])
    test({**held, TEST: new[TEST]}, "held gate + new tests (must be red)")
    _, ok = test(new, "fixed")
    H, tree = gt_tree(new)
    final = {GATE: new[GATE].encode(), TEST: new[TEST].encode()}
    final.update({rel: b for rel, b in tree.items() if (BASE / rel).read_bytes() != b})
    assert set(final) == {s.split(" b/", 1)[1].splitlines()[0] for s in
                          (WT / "held" / (OLD + ".patch")).read_text().split("diff --git ")[1:]}, sorted(final)
    gt_gate = final["hooks-gt/_shared/hestia_single_gate.py"]
    assert H.strip_header(gt_gate) == final[GATE], "GT copy != source"
    chunks = []
    for rel in [GATE, TEST] + sorted(r for r in final if r.startswith("hooks-gt/")):
        a = (BASE / rel).read_text().splitlines(True)
        b = final[rel].decode().splitlines(True)
        chunks.append(f"diff --git a/{rel} b/{rel}\n" + "".join(
            difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}")))
    patch = "".join(chunks).encode()
    digest = hashlib.sha256(patch).hexdigest()
    print("GT engine canonical digest:", H.canonical_digest(gt_gate))
    print("source sha256:", {k: hashlib.sha256(final[k]).hexdigest()[:8] for k in (GATE, TEST)})
    if not ok:
        print("NOT writing patch: suite red")
        return 1
    (OUT / (digest + ".patch")).write_bytes(patch)
    print("wrote", digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
