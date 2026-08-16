#!/usr/bin/env python3
"""Escalation 1010b3182bc7ae78 — the proposed governance-closure repair, as an
inspectable, runnable artifact OUTSIDE the closure it proposes to change.

The write to plugins/_shared/hestia_governance_closure.py is refused (gate-self). This
script does not attempt that write. It:
  1. builds a patched COPY in a scratch dir,
  2. runs the repository's own closure test suite against the copy (no regressions),
  3. runs the false-positive battery against BOTH copies (before/after),
  4. runs a sabotage control proving the battery can fail,
  5. emits the unified diff a decider would approve.

Run:  python3 tools/claude_heredoc_excision_proposal_1010b318.py [--emit-diff]
"""
import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "plugins", "_shared")
MOD = os.path.join(SHARED, "hestia_governance_closure.py")

ANCHOR = '''def _tokenize(cmd: str) -> list:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT)
    lex.whitespace_split = True
    return list(lex)
'''

ADDITION = '''

# `<<EOF` / `<<-EOF` / `<<'EOF'` / `<<"EOF"` / `<<\\\\EOF`. Deliberately does NOT match the
# here-STRING `<<<word` (its operand is one word, already handled as a read position).
_HEREDOC_RE = re.compile(
    r"<<-?[ \\t]*(?P<q>['\\"]?)(?P<bs>\\\\?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=q)")


def _heredoc_body_is_inert(body: str, literal: bool) -> bool:
    """A body is inert iff nothing in it can become a command.

    A QUOTED (or backslashed) delimiter suppresses all expansion, so the body is literal
    text -- always inert. An UNQUOTED delimiter expands the body, so `$(...)`, backticks
    and `${...}` inside it CAN execute: those stay in the haystack (fail closed). A body
    with neither `$` nor a backtick cannot expand into anything, so it is inert anyway."""
    return literal or ("$" not in body and "`" not in body)


def _excise_heredoc_bodies(cmd: str) -> str:
    """Remove inert heredoc BODIES before write-position analysis, keeping the operator
    and terminator lines so redirect/operand parsing is unchanged.

    The module contract says payload is never a write-position haystack, but a heredoc
    body reaches the tokenizer as ordinary trailing words. Two measured false-positive
    shapes come from that, and this closes both:
      * an ODD number of quote characters in body prose (`author's`) breaks the lexer and
        the unparseable fallback hands the WHOLE command up as write candidates -- so a
        governance path merely CITED in a commit message is reported as the write target;
      * a redirect operator in body prose (`stdout > path`) parses fine and puts the cited
        path in a genuine write position -- a deny indistinguishable from a real write.

    An UNTERMINATED heredoc is left intact: a malformed command stays fail-closed."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        pending = [(m.group("delim"), bool(m.group("q") or m.group("bs")))
                   for m in _HEREDOC_RE.finditer(line)]
        for delim, literal in pending:
            body, j = [], i
            while j < len(lines) and lines[j].strip() != delim:
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                break  # unterminated: leave the remainder untouched (fail closed)
            if _heredoc_body_is_inert("\\n".join(body), literal):
                out.append("")  # body excised; terminator still follows
            else:
                out.extend(body)
            out.append(lines[j])
            i = j + 1
    return "\\n".join(out)
'''

# The call site: the excised command is what gets tokenized AND what the unparseable
# fallback splits, so both false-positive shapes are closed by one substitution.
CALL_OLD = '''        try:
            return _bash_write_targets(cmd), None
'''
CALL_NEW = '''        cmd = _excise_heredoc_bodies(cmd)
        try:
            return _bash_write_targets(cmd), None
'''

CITE = "plugins/_shared/hestia_governance_closure.py"


def _hd(body, delim="MSG", quoted=True):
    d = "'%s'" % delim if quoted else delim
    return "git commit-tree e74cc02 -p a4e8fb8 -F /dev/stdin <<%s\n%s\n%s" % (d, body, delim)


# (label, command, expected_after, must_be_unchanged_by_fix)
BATTERY = [
    ("FP1 odd apostrophe in body prose + cite",
     _hd("the author's note on %s" % CITE), "read", False),
    ("FP1b odd double-quote in body prose + cite",
     _hd('the "payload rule on %s' % CITE), "read", False),
    ("FP1c three apostrophes (odd) + cite",
     _hd("author's editor's reader's note on %s" % CITE), "read", False),
    ("FP2 redirect operator in body prose + cite",
     _hd("we route stdout > %s in the example" % CITE), "read", False),
    ("FP2b append operator in body prose + cite",
     _hd("we route stdout >> %s in the example" % CITE), "read", False),
    # --- must NOT change: real writes stay denied ---
    ("TP1 real redirect into the closure",
     "echo x > %s" % CITE, "write", True),
    ("TP2 real redirect into closure AFTER a heredoc",
     _hd("harmless prose") + "\necho x > %s" % CITE, "write", True),
    ("TP3 UNQUOTED heredoc whose body carries a command substitution",
     _hd("prose $(echo x > %s) more" % CITE, quoted=False), "write", True),
    ("TP4 unterminated heredoc with odd quote + cite (stays fail-closed)",
     "git commit-tree e74cc02 -F /dev/stdin <<'MSG'\nauthor's note on %s" % CITE,
     "write", True),
    ("TP5 here-string is not a heredoc",
     "cat <<< notes > %s" % CITE, "write", True),
    ("N1 no governance path anywhere",
     _hd("the author's note on tools/unrelated.py"), "none", True),
]


def build_patched(dst_dir):
    src = open(MOD, encoding="utf-8").read()
    if ANCHOR not in src:
        raise SystemExit("anchor not found — module drifted; re-derive the patch")
    if CALL_OLD not in src:
        raise SystemExit("call site not found — module drifted; re-derive the patch")
    out = src.replace(ANCHOR, ANCHOR + ADDITION, 1).replace(CALL_OLD, CALL_NEW, 1)
    shutil.copytree(SHARED, dst_dir, dirs_exist_ok=True)
    with open(os.path.join(dst_dir, "hestia_governance_closure.py"), "w",
              encoding="utf-8") as fh:
        fh.write(out)
    return src, out


def load(dirpath):
    import importlib.util
    p = os.path.join(dirpath, "hestia_governance_closure.py")
    name = "gc_%x" % (abs(hash(dirpath)) & 0xffffffff)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m  # dataclass() resolves the owning module by name
    spec.loader.exec_module(m)
    return m


def run_battery(mod, label):
    print("\n--- battery: %s ---" % label)
    res = {}
    for name, cmd, expected, _pin in BATTERY:
        v = mod.classify("Bash", {"command": cmd})
        res[name] = v.classification
        print("  %-52s %-5s (want %s)" % (name[:52], v.classification, expected))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-diff", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="closure-proposal-")
    patched_dir = os.path.join(tmp, "patched")
    src, out = build_patched(patched_dir)

    if args.emit_diff:
        sys.stdout.writelines(difflib.unified_diff(
            src.splitlines(True), out.splitlines(True),
            fromfile="a/plugins/_shared/hestia_governance_closure.py",
            tofile="b/plugins/_shared/hestia_governance_closure.py"))
        return 0

    before = load(SHARED)
    after = load(patched_dir)
    rb = run_battery(before, "BEFORE (installed)")
    ra = run_battery(after, "AFTER (proposed)")

    print("\n--- verdict per case ---")
    ok = True
    for name, _cmd, expected, pinned in BATTERY:
        good = ra[name] == expected
        moved = rb[name] != ra[name]
        if pinned and moved:
            good = False
            note = "REGRESSION: fix moved a case that must not move"
        else:
            note = "fixed" if moved else "unchanged"
        ok &= good
        print("  %-52s %-5s -> %-5s  %s  %s" % (
            name[:52], rb[name], ra[name], "OK " if good else "BAD", note))

    print("\n--- repository closure suite against the PATCHED copy ---")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q",
                        os.path.join(patched_dir, "hestia_governance_closure_test.py")],
                       capture_output=True, text=True, cwd=patched_dir)
    print((r.stdout or r.returncode) and r.stdout.strip().splitlines()[-1] or r.stderr[-400:])
    suite_ok = r.returncode == 0

    print("\n--- sabotage control (battery must FAIL when the fix is defanged) ---")
    sab_dir = os.path.join(tmp, "sabotage")
    shutil.copytree(SHARED, sab_dir, dirs_exist_ok=True)
    sab = open(os.path.join(patched_dir, "hestia_governance_closure.py"),
               encoding="utf-8").read().replace(
        '    if "<<" not in cmd:\n        return cmd\n',
        '    if "<<" not in cmd:\n        return cmd\n    return cmd  # SABOTAGE\n', 1)
    with open(os.path.join(sab_dir, "hestia_governance_closure.py"), "w",
              encoding="utf-8") as fh:
        fh.write(sab)
    rs = run_battery(load(sab_dir), "SABOTAGED (excision disabled)")
    sab_caught = any(rs[n] != e for n, _c, e, _p in BATTERY)
    print("  sabotage detected by the battery: %s%s" % (
        sab_caught, "" if sab_caught else "   <-- battery is INERT, do not trust it"))

    print("\nRESULT: battery=%s suite=%s sabotage-control=%s" % (ok, suite_ok, sab_caught))
    return 0 if (ok and suite_ok and sab_caught) else 1


if __name__ == "__main__":
    raise SystemExit(main())
