#!/usr/bin/env python3
"""hestia #1494 / #1314: the two largest false-deny causes on McNugget's week of gate decisions
(2026-11-03..10, 89 denies, 7 false), fixed without loosening any real secret read or outside reach.

1. Gate 1a matched the env-file token as a raw SUBSTRING, so `os.environ`, `venv.EnvBuilder` and
   `gh search 'os.environ'` were refused as secret reads. It is now matched as a file name: a hit
   unless the token is glued inside one identifier on both sides.
2. `mrh.command` judged a jq expression as a relative path: gh's `--jq`/`-q` value and jq's own
   filter operand (`.state`, `.comments[-2:][]` — a glob, so a read of the cwd).
3. Found while measuring: with the program from a FILE (`grep -f`, `sed -f`, `awk -f`, `jq -f`, and
   clustered as `-rf`), the first operand was still taken as the pattern and never judged, so
   `grep -f P /outside` passed.
4. #1560 (legion-claude's #1550 v2 review): the cluster rule went on scanning past a letter whose value
   is text, so in `grep -nefoo FILE` the `f` inside `-e`'s pattern `foo` was read as `-f` and `oo`
   judged as a program file. The first text-valued letter now owns the rest of the word.

Every FALSE row below fails on main's core; every DENY row passes on both. Strings only: nothing
here opens a file it names. No forbidden token is spelled in this source (tools/marker_bar_probe.py's
discipline): the env token is built from the core's own constant.

Run: python3 tools/gate_false_deny_test.py [dir holding core_rev.py]
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
if (OUT / "core_rev.py").is_file():
    spec = importlib.util.spec_from_file_location("hestia_gate_core", OUT / "core_rev.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_core"] = mod
    sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
    spec.loader.exec_module(mod)
sys.path.insert(0, str(ROOT / "tools"))
import grant_modes_gate_test as g  # noqa: E402

core = g.core
E = next(t for t in core.FORBIDDEN_DEFAULT if t.endswith("env"))
OUTSIDE = "/etc/hosts"          # exists on every seat, outside every fixture workspace

# Commands whose only "secret" is a word that merely CONTAINS the env token.
ENV_ALLOW = [
    ("os.environ in python -c", "python3 -c 'import os; print(os.environ.get(\"HOME\"))'"),
    ("gh search for os.environ", "gh search issues --repo dp-web4/hestia --state open 'os.environ'"),
    ("rg for venv.EnvBuilder (#1494)", "rg -n 'venv.EnvBuilder|system_site_packages' {ws}/repo"),
    ("grep environ", "grep -rn environ {ws}/repo"),
]
# Every spelling of the env FILE stays refused by gate 1a, wherever it appears.
ENV_DENY = [
    ("the file", "cat {ws}/repo/" + E),
    ("dot-slash .local", "cat ./" + E + ".local"),
    ("home", "cp ~/" + E + " /tmp/x"),
    ("redirect", "python3 x.py < {ws}/repo/" + E),
    ("source", "source {ws}/repo/" + E),
    ("prefixed name", "cat {ws}/repo/prod" + E),
    ("prefixed name with suffix", "cat {ws}/repo/app" + E + ".bak"),
    ("rc file", "cat {ws}/repo/" + E + "rc"),
    ("upper case", "cat {ws}/repo/" + E.upper()),
    ("python -c open", "python3 -c 'print(open(\"" + E + "\").read())'"),
    ("jq on the file", "jq . {ws}/repo/" + E),
    ("inside a --jq value", "gh api x --jq '" + E + "'"),
    ("escaped in a regex (conservative)", "grep -rn '\\" + E + "' {ws}/repo"),
    ("member access (conservative)", "grep -rn 'process" + E + ".HOME' {ws}/repo"),
]
# A jq expression is not a path: gh's --jq / -q value, and jq's filter operand.
SCOPE_ALLOW = [
    ("gh --jq brackets", "gh pr view 1 -R o/r --json comments --jq '.comments[-2:][]|.body[:1200]'"),
    ("gh --jq bare", "gh pr view 1 -R o/r --json state --jq .state"),
    ("gh -q", "gh pr view 1 -R o/r --json state -q .state"),
    ("gh --jq=", "gh pr view 1 -R o/r --json state --jq=.state"),
    ("gh api --jq", "gh api repos/o/r/pulls/1 --jq .head.sha"),
    ("jq filter then a granted file", "jq .state {ws}/repo/a.json"),
    ("jq filter in a pipe", "gh pr list -R o/r --json number | jq '.[].number'"),
    ("jq -r filter", "jq -r '.reviews[-1].body' {ws}/repo/a.json"),
]
# Outside reaches stay refused, including through the new exemptions.
SCOPE_DENY = [
    ("jq reads an outside file", "jq .a " + OUTSIDE),
    ("jq -f, outside data", "jq -f {ws}/repo/p.jq " + OUTSIDE),
    ("jq --from-file, outside data", "jq --from-file {ws}/repo/p.jq " + OUTSIDE),
    ("jq -f outside program", "jq -f " + OUTSIDE),
    ("jq -L outside library", "jq -L /etc .a {ws}/repo/a.json"),
    ("gh --jq, then an outside read", "gh api x --jq .a && cat " + OUTSIDE),
    ("gh -q with an unquoted glob", "gh api x -q /etc/*"),
    ("gh --body-file outside", "gh pr comment 1 --body-file " + OUTSIDE),
    ("gh --template is a boolean under repo edit", "gh repo edit --template " + OUTSIDE),
    # the hole this change closes: a program file means the operands are files
    ("grep -f, outside data", "grep -f {ws}/repo/p " + OUTSIDE),
    ("grep --file=, outside data", "grep --file={ws}/repo/p " + OUTSIDE),
    ("grep -fFILE, outside data", "grep -f{ws}/repo/p " + OUTSIDE),
    ("sed -f, outside data", "sed -f {ws}/repo/p.sed " + OUTSIDE),
    ("awk -f, outside data", "awk -f {ws}/repo/p.awk " + OUTSIDE),
    ("rg -f, outside data", "rg -f {ws}/repo/p " + OUTSIDE),
    # clustered: getopt hands `f` the next word (or the rest of the word); every operand is a file
    ("jq -rf outside program", "jq -rf " + OUTSIDE + " {ws}/repo/a.json"),
    ("jq -rf, outside data", "jq -rf {ws}/repo/p.jq " + OUTSIDE),
    ("grep -rf outside patterns", "grep -rf " + OUTSIDE + " {ws}/repo"),
    ("grep -rf, outside data", "grep -rf {ws}/repo/p " + OUTSIDE),
    ("grep -nfFILE, outside data", "grep -nf{ws}/repo/p " + OUTSIDE),
    ("sed -nf, outside data", "sed -nf {ws}/repo/p.sed " + OUTSIDE),
    # jq's library directory, every spelling (legion-claude and Nova on #1550; jq 1.8 long form)
    ("jq -n --library-path outside", "jq -n --library-path /etc 'include \"x\"; .'"),
    ("jq --library-path= outside", "jq -n --library-path=/etc 'include \"x\"; .'"),
    ("jq -n -L outside", "jq -n -L /etc 'include \"x\"; .'"),
    ("jq -L/DIR attached outside", "jq -n -L/etc 'include \"x\"; .'"),
    ("jq -nL clustered outside", "jq -nL /etc 'include \"x\"; .'"),
    ("jq -nL/DIR clustered attached", "jq -nL/etc 'include \"x\"; .'"),
    # #1560: a clustered PATTERN letter owns the rest of the word; every operand is still a file
    ("grep -nefoo, outside data", "grep -nefoo " + OUTSIDE),
    ("grep -ne PAT, outside data", "grep -ne foo " + OUTSIDE),
    ("grep -nef: `f` is -e's pattern, outside data", "grep -nef " + OUTSIDE),
    ("grep -nefoo, granted then outside", "grep -nefoo {ws}/repo/a.json " + OUTSIDE),
    ("sed -ne SCRIPT, outside data", "sed -ne p " + OUTSIDE),
    # an UNQUOTED glob in the clustered value is expanded by the shell (a directory read), so it is
    # judged, as the attached `-e/x/*` already is. Main left it unjudged: a small tightening.
    ("grep -ne with an unquoted glob value", "grep -ne/etc/* {ws}/repo"),
    # string options are head-wide (git's `-m` is a boolean under checkout): a cluster ending in one
    # does not hand the next word over unjudged
    ("git checkout -fm, outside path", "git checkout -fm " + OUTSIDE),
]
# Shapes that must not be over-judged by the cluster rule.
SCOPE_ALLOW += [
    ("sed -if: `f` is -i's backup suffix", "sed -if 's/a/b/' {ws}/repo/a.json"),
    ("jq -n --library-path granted", "jq -n --library-path {ws}/repo 'include \"x\"; .'"),
    # #1560: `-e` owns `foo`; the `f` inside it is not -f (legion-claude's #1550 v2 review)
    ("grep -nefoo: `foo` is -e's pattern", "grep -nefoo {ws}/repo/a.json"),
    ("grep -inef: `f` is -e's pattern", "grep -inef {ws}/repo/a.json"),
    ("grep -nefoo/bar: a pattern, not a path", "grep -nefoo/bar {ws}/repo/a.json"),
    # the shape that is a false deny on main: the text after the misread `f` names an existing outside
    # path, so `-f`'s "program file" /etc/hosts was judged, though grep reads the pattern `f/etc/hosts`
    ("grep -nef/etc/hosts: the pattern `f/etc/hosts`", "grep -nef/etc/hosts {ws}/repo/a.json"),
    ("grep -ief/etc/hosts: the pattern `f/etc/hosts`", "grep -ief/etc/hosts {ws}/repo/a.json"),
]


def main():
    bad = []
    cwd = tempfile.mkdtemp(prefix="hestia-fdr-cwd-")   # outside the grant: _Workspace turns temp admission off
    try:
        with g._Workspace() as ws:
            os.makedirs(ws + "/repo", exist_ok=True)
            for f in ("a.json", "p", "p.jq", "p.sed", "p.awk"):
                pathlib.Path(ws, "repo", f).write_text("{}\n")
            snap = g._snapshot(ws, standing=[{"path": ws, "recursive": True}])
            prof, pol = g._policy(snap)

            def verdict(cmd):
                ev = core.NormalizedEvent(tool="Bash", paths=[], command=cmd.format(ws=ws), cwd=cwd)
                return core.evaluate(ev, prof, ws, policy=pol)

            for name, cmd in ENV_ALLOW + SCOPE_ALLOW:
                v = verdict(cmd)
                if v.blocks:
                    bad.append(f"ALLOW expected, got {v.rule}: {name}")
            for name, cmd in ENV_DENY:
                v = verdict(cmd)
                if v.rule != "egress.secret":
                    bad.append(f"egress.secret expected, got {v.decision}/{v.rule}: {name}")
            for name, cmd in SCOPE_DENY:
                v = verdict(cmd)
                if not (v.blocks and (v.rule or "").startswith("mrh.command")):
                    bad.append(f"mrh.command expected, got {v.decision}/{v.rule}: {name}")
    finally:
        os.rmdir(cwd)
    for b in bad:
        print("FAIL", b)
    n = len(ENV_ALLOW) + len(SCOPE_ALLOW) + len(ENV_DENY) + len(SCOPE_DENY)
    print(f"{'PASS' if not bad else 'FAIL'}: {n - len(bad)}/{n} rows "
          f"({len(ENV_ALLOW) + len(SCOPE_ALLOW)} false-deny, {len(ENV_DENY) + len(SCOPE_DENY)} must-deny)")
    if bad:
        raise SystemExit(1)       # raises under a runner too, never a silent pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
