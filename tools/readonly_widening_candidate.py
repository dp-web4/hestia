#!/usr/bin/env python3
"""The measured widening: four classes, each with its own control, on real traffic.

WHAT THIS REPLACES
------------------
A first pass (`readonly_wrapper_reduction.py`) widened brace groups, subshells,
arithmetic and command substitution. It passed its bypass control 24/24 and fixed 6 of 7
minimal pairs -- and moved real traffic by **3 refusals out of 3219 (0.1%)**. The
hypothesis that exotic shell syntax drives the false-refusal load is REFUTED on this
seat's corpus. That result is kept, not buried: it is why this file exists.

Blame attribution over the same 3219 refusals pointed somewhere far more boring, and
each class below was then confirmed first-hand against the INSTALLED classifier rather
than inferred from the histogram. (One histogram entry -- `#` at 18% -- was an artifact
of the attributor's own crude segment splitter, NOT a defect: all four comment spellings
classify correctly. It is named here because an unretracted 18% would have been the
headline finding.)

THE FOUR CLASSES
----------------
  A. EXEC-WRAPPERS   `timeout N C`, `env [V=x] C`, `nice C`, `nohup C`, `stdbuf -oL C`
     Compositional: the wrapper adds no ability to write, so the call is read-only iff
     C is. Reduced to C and handed to the real classifier -- same move as `( C )`.

  B. NON-WRITING HEADS   `sleep`, `ps`, `pgrep`, `free`, `uptime`, ...
     The criterion the gate itself used to admit `cd`: "there is no flag, no argument
     and no spelling of it that modifies a file." Each name below was checked against
     its own man page for a writing form; ones that HAVE a writing form (`date -s`,
     `hostname X`, `nvidia-smi -r`) are deliberately excluded, exactly as the gate
     excluded `date` and `hostname`.

  C. GIT READ SUBCOMMANDS   the largest addressable bucket (git blames 748 refusals)
     Split the way the gate already splits git: bare-admitted where no writing form
     exists (`shortlog`, `count-objects`, `rev-list`), GUARDED where a writing form
     shares the subcommand (`config`, `branch`, `remote`, `worktree`, `reflog`, `tag`,
     `stash`). Guards are default-deny: the read form must be positively recognised.

  D. QUOTED HEREDOC UNDER A READ HEAD   `cat <<'EOF' ... EOF`
     A quoted delimiter suppresses all expansion, so the body is inert data. An
     UNQUOTED delimiter does not, and stays refused -- that distinction is the whole
     control, and it is the same one an arbiter upheld on 2026-08-26 for the
     destructive preset (appeal 324f51f4: quoting the token as data is not executing
     it). The two rules disagreeing about the same construct is the finding here.

MECHANISM HONESTY
-----------------
A and D are REDUCTIONS: the text is rewritten into something the unmodified installed
classifier already judges, so every allow still comes from the real gate. B and C are
ADMISSIONS: a claim by this file that a name cannot write. Admissions are strictly
weaker evidence than reductions, they are counted separately in the output, and each
one is answerable to the bypass corpus. Do not read a B/C benefit as if it were an A/D
benefit.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

DEFAULT_HOOK = Path.home() / ".claude" / "hooks" / "hestia" / "pre_tool_use.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# --- A. exec-wrappers ------------------------------------------------------
# `xargs` is NOT here and must not be: it builds a command line from stdin, so the thing
# it runs is not visible in the text at all. That is the same reason the gate refuses it.
_WRAPPERS = {
    "timeout": lambda a: _drop_flags(a, valued={"-s", "--signal", "-k", "--kill-after"}, positional=1),
    "nice": lambda a: _drop_flags(a, valued={"-n", "--adjustment"}, positional=0),
    "nohup": lambda a: a,
    "ionice": lambda a: _drop_flags(a, valued={"-c", "-n", "-p"}, positional=0),
    "stdbuf": lambda a: _drop_flags(a, valued={"-i", "-o", "-e"}, positional=0),
    "env": lambda a: _drop_env_assignments(a),
}


def _drop_flags(args: list[str], valued: set[str], positional: int) -> list[str] | None:
    """Strip the wrapper's own options, then `positional` of its own operands."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in valued:
            i += 2
            continue
        if a.startswith("-") and "=" in a:
            i += 1
            continue
        if a.startswith("-") and a != "--":
            i += 1
            continue
        if a == "--":
            i += 1
            break
        break
    i += positional
    rest = args[i:]
    return rest or None


def _drop_env_assignments(args: list[str]) -> list[str] | None:
    """`env [-i] [NAME=VALUE]... COMMAND`. Bare `env` (no command) prints and is a read."""
    i = 0
    while i < len(args) and (args[i].startswith("-") or re.match(r"^[A-Za-z_]\w*=", args[i])):
        if args[i] in {"-u", "--unset"}:
            i += 2
            continue
        i += 1
    rest = args[i:]
    return rest if rest else ["true"]  # bare `env` prints the environment: a read


def _unwrap_execs(cmd: str) -> str:
    """Rewrite each segment `WRAPPER ... CMD ...` to `CMD ...`, repeatedly."""
    import shlex

    out = []
    for seg in re.split(r"(\|\||&&|[;|\n])", cmd):
        if seg in {"||", "&&", ";", "|", "\n"} or not seg.strip():
            out.append(seg)
            continue
        cur = seg
        for _ in range(4):  # `timeout 5 nice env FOO=1 cat x` -- bounded, not while-True
            try:
                parts = shlex.split(cur, posix=False)
            except ValueError:
                break
            if not parts:
                break
            head = Path(parts[0].strip("'\"")).name
            if head not in _WRAPPERS:
                break
            inner = _WRAPPERS[head](parts[1:])
            if not inner:
                break
            cur = " ".join(inner)
        out.append(cur)
    return "".join(out)


# --- B. heads with no writing form ----------------------------------------
# Checked individually. EXCLUDED on purpose, each because a writing form exists:
#   date (-s sets the clock)   hostname (X sets it)   nvidia-smi (-r resets the GPU)
#   stty (sets terminal modes) sysctl (-w writes)     ip/ifconfig (configure)
_NON_WRITING_HEADS = {
    "sleep", "ps", "pgrep", "pidof", "free", "uptime", "nproc", "printenv",
    "groups", "arch", "tty", "logname", "locale", "getconf", "lsb_release",
    "ulimit", "times", "jobs", "dirs", "read", "let", "expr", "sha1sum",
    "b2sum", "sha512sum", "nl", "fold", "fmt", "paste", "join", "look",
    "strings", "xxd", "od", "base64", "base32", "cmp", "yes", "tac",
}

# --- C. git ---------------------------------------------------------------
_GIT_READ_EXTRA = {
    "shortlog", "count-objects", "rev-list", "merge-base", "name-rev",
    "check-ignore", "check-attr", "whatchanged", "verify-pack", "var",
    "ls-remote", "for-each-ref", "diff-tree", "diff-index", "cherry",
    "get-tar-commit-id", "patch-id", "range-diff", "annotate",
    # `hash-object` was here and the bypass corpus caught it: `-w` writes the object to
    # the database, so it HAS a writing form and never belonged in a bare set. Moved to
    # the guards below. This is the failure mode the gate's own `date`/`hostname` comment
    # warns about -- a read-looking NAME carrying a mutating FLAG -- reproduced by me in
    # the act of fixing it.
}
# Subcommand -> predicate over its args returning True only for a RECOGNISED read form.
# Default-deny: anything unrecognised is a write, so a new git verb cannot leak in.
_GIT_GUARDED_READ = {
    "config": lambda a: bool(a) and all(
        x in {"--get", "--get-all", "--get-regexp", "--list", "-l", "--global",
              "--local", "--system", "--show-origin", "--show-scope", "--worktree"}
        or not x.startswith("-") and any(
            f in a for f in ("--get", "--get-all", "--get-regexp"))
        for x in a),
    "branch": lambda a: bool(a) and all(
        x in {"--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv",
              "--verbose", "--show-current", "--contains", "--merged", "--no-merged",
              "--format", "--sort"} or not x.startswith("-") and (
            "--list" in a or "-l" in a) for x in a),
    "remote": lambda a: bool(a) and a[0] in {"-v", "--verbose", "show", "get-url"},
    "worktree": lambda a: bool(a) and a[0] == "list",
    "reflog": lambda a: not a or a[0] in {"show", "--all"} or a[0].startswith("-"),
    "tag": lambda a: bool(a) and (a[0] in {"-l", "--list"} or "--list" in a or "-l" in a),
    "stash": lambda a: bool(a) and a[0] in {"list", "show"},
    "notes": lambda a: bool(a) and a[0] in {"list", "show"},
    "submodule": lambda a: bool(a) and a[0] in {"status", "summary"},
    "bisect": lambda a: bool(a) and a[0] in {"log", "view"},
    "hash-object": lambda a: "-w" not in a and "--stdin-paths" not in a,
}


# An output redirect writes a file no matter how harmless its head is. `_admitted` walks
# HEADS, so without this check `ps aux > /tmp/f` is admitted on `ps` and the redirect is
# never seen -- caught by the bypass corpus, not by review. Only `/dev/null` and
# `/dev/stderr` targets are tolerated, because those provably store nothing.
_INERT_TARGETS = {"/dev/null", "/dev/stderr", "/dev/stdout", "/dev/fd/1", "/dev/fd/2"}


def _has_writing_redirect(seg: str) -> bool:
    """Quote-aware scan for an output redirect to anything that is not inert."""
    i, quote = 0, None
    while i < len(seg):
        ch = seg[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == ">":
            j = i + 1
            while j < len(seg) and seg[j] in ">|":
                j += 1
            if j < len(seg) and seg[j] == "&":     # `>&1` duplicates a descriptor
                i = j + 1
                continue
            rest = seg[j:].strip().split()
            target = rest[0].strip("'\"") if rest else ""
            if target not in _INERT_TARGETS:
                return True
            i = j + 1
            continue
        i += 1
    return False


def _git_is_read(parts: list[str]) -> bool | None:
    """None = 'no opinion, let the gate decide'. True/False = this file's claim."""
    args = [p for p in parts[1:] if not (p == "-C" or p.startswith("--git-dir"))]
    args = [a for a in args if not a.startswith("/") and not a.startswith("--work-tree")]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub in _GIT_READ_EXTRA:
        return True
    if sub in _GIT_GUARDED_READ:
        try:
            return bool(_GIT_GUARDED_READ[sub](rest))
        except Exception:
            return False
    return None


# --- D. quoted heredoc -----------------------------------------------------
_HEREDOC = re.compile(r"<<-?\s*(['\"])(\w+)\1")


def _strip_quoted_heredocs(cmd: str) -> str:
    """Delete `<<'EOF' ... EOF` bodies. A QUOTED delimiter suppresses every expansion,
    so the body is inert data and cannot execute. An UNQUOTED `<<EOF` is left alone --
    it expands `$( )` and backticks, and that difference is the control."""
    for m in _HEREDOC.finditer(cmd):
        tag = m.group(2)
        body = re.compile(r"<<-?\s*['\"]" + re.escape(tag) + r"['\"].*?^\s*" + re.escape(tag) + r"\s*$",
                          re.S | re.M)
        cmd = body.sub(" /dev/null ", cmd)
    return cmd


# --- the combined candidate ------------------------------------------------

def widened(cmd: str, gate, *, use_admissions: bool = True) -> bool:
    if gate._is_read_only("Bash", {"command": cmd}):
        return True
    text = _strip_quoted_heredocs(cmd)        # D (reduction)
    text = _unwrap_execs(text)                # A (reduction)
    if gate._is_read_only("Bash", {"command": text}):
        return True
    if not use_admissions:
        return False
    return _admitted(text, gate)              # B + C (admissions)


def _admitted(cmd: str, gate) -> bool:
    """Every segment must be read-only, either per the gate or per a stated admission."""
    import shlex

    for seg in re.split(r"\|\||&&|[;|\n]", cmd):
        seg = seg.strip()
        if not seg:
            continue
        if gate._is_read_only("Bash", {"command": seg}):
            continue
        # Before any head-based admission: a redirect writes regardless of the head.
        if _has_writing_redirect(seg):
            return False
        try:
            parts = shlex.split(seg, posix=False)
        except ValueError:
            return False
        if not parts:
            return False
        head = Path(parts[0].strip("'\"")).name
        if head in _NON_WRITING_HEADS:
            continue
        if head == "git":
            verdict = _git_is_read(parts)
            if verdict:
                continue
        return False
    return True


# --- controls --------------------------------------------------------------
# Every entry writes (or may write). Any that flips to allow refutes the class it tests.

BYPASS = [
    # A -- wrappers must not launder their payload
    ("A", "timeout 5 rm /tmp/f"),
    ("A", "timeout -s KILL 5 sed -i 's/a/b/' /tmp/f"),
    ("A", "env FOO=1 sed -i 's/a/b/' /tmp/f"),
    ("A", "env -i rm /tmp/f"),
    ("A", "nice -n 5 rm /tmp/f"),
    ("A", "nohup rm /tmp/f"),
    ("A", "stdbuf -oL tee /tmp/f"),
    ("A", "timeout 5 nice env FOO=1 rm /tmp/f"),
    ("A", "timeout 5 python3 -c 'x'"),
    # B -- a non-writing head must not free its neighbours
    ("B", "sleep 5; rm /tmp/f"),
    ("B", "sleep 5 && sed -i x /tmp/f"),
    ("B", "ps aux > /tmp/f"),
    ("B", "read x < /tmp/f; rm /tmp/f"),
    # C -- git guards are default-deny
    ("C", "git commit -m x"),
    ("C", "git config user.email x"),
    ("C", "git config --global user.name y"),
    ("C", "git branch newbranch"),
    ("C", "git branch -d old"),
    ("C", "git branch -M main"),
    ("C", "git remote add origin url"),
    ("C", "git remote set-url origin url"),
    ("C", "git worktree add /tmp/w"),
    ("C", "git worktree prune"),
    ("C", "git reflog expire --all"),
    ("C", "git reflog delete HEAD@{0}"),
    ("C", "git tag v1"),
    ("C", "git tag -d v1"),
    ("C", "git stash"),
    ("C", "git stash pop"),
    ("C", "git notes add -m x"),
    ("C", "git submodule update --init"),
    ("C", "git bisect reset"),
    ("C", "git hash-object -w /tmp/f"),
    ("C", "git pull"),
    ("C", "git fetch origin"),
    # D -- an UNQUOTED heredoc still expands, so it is still a write
    ("D", "cat <<EOF\n$(rm /tmp/f)\nEOF"),
    ("D", "cat <<EOF\n`rm /tmp/f`\nEOF"),
    ("D", "tee /tmp/f <<'EOF'\nx\nEOF"),
    ("D", "bash <<'EOF'\nrm /tmp/f\nEOF"),
    ("D", "python3 <<'EOF'\nimport os\nEOF"),
]

BENEFIT = [
    ("A", "timeout 5 cat /etc/hostname"),
    ("A", "env FOO=1 cat /etc/hostname"),
    ("A", "nice cat /etc/hostname"),
    ("A", "timeout 300 grep -c . /etc/hostname"),
    ("B", "sleep 5"),
    ("B", "sleep 5 && cat /etc/hostname"),
    ("B", "ps aux"),
    ("B", "ps aux | grep x"),
    ("B", "free -h"),
    ("B", "nproc"),
    ("C", "git shortlog -s"),
    ("C", "git count-objects -v"),
    ("C", "git worktree list"),
    ("C", "git config --get user.email"),
    ("C", "git branch --list"),
    ("C", "git remote -v"),
    ("C", "git reflog"),
    ("C", "git rev-list --count HEAD"),
    ("C", "git for-each-ref --format='%(refname)'"),
    ("D", "cat <<'EOF'\nhello\nEOF"),
    ("D", "grep x /etc/hostname <<'EOF'\ny\nEOF"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hook", type=Path, default=DEFAULT_HOOK)
    ap.add_argument("--corpus", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--limit", type=int, default=4000)
    args = ap.parse_args()

    gate = load(args.hook, "_gate_under_test")
    rgc = load(Path(__file__).parent / "readonly_grammar_coverage.py", "rgc")
    print(f"classifier under test: {args.hook}\n")

    print("CONTROL -- each of these writes; any allow refutes its class")
    leaked = [(k, c) for k, c in BYPASS
              if widened(c, gate) and not gate._is_read_only("Bash", {"command": c})]
    already = [(k, c) for k, c in BYPASS if gate._is_read_only("Bash", {"command": c})]
    if already:
        print(f"  NOTE {len(already)} allowed by the BASELINE, so they test nothing here:")
        for k, c in already:
            print(f"    ~ [{k}] {c!r}")
    if leaked:
        print(f"  FAIL {len(leaked)}/{len(BYPASS)} leaked:")
        for k, c in leaked:
            print(f"    ! [{k}] {c!r}")
    else:
        print(f"  PASS 0/{len(BYPASS)} leaked\n")

    print("BENEFIT -- each reads and writes nothing")
    missed = []
    for k, c in BENEFIT:
        base = gate._is_read_only("Bash", {"command": c})
        wide = widened(c, gate)
        if not wide:
            missed.append((k, c))
        flag = "fixed" if wide and not base else ("already" if base else "STILL REFUSED")
        print(f"  [{k}] {flag:<14} {c!r}"[:118])
    print(f"\n  {len(BENEFIT) - len(missed)}/{len(BENEFIT)} now read-only\n")

    cmds = rgc.harvest(args.corpus, args.limit)
    if not cmds:
        return 1 if leaked else 0
    base_w = [c for c in cmds if not gate._is_read_only("Bash", {"command": c})]
    red_only = [c for c in base_w if widened(c, gate, use_admissions=False)]
    full = [c for c in base_w if widened(c, gate)]
    clean = [c for c in full if rgc.plainly_read_only(c)]
    print(f"REAL CORPUS ({len(cmds)} commands this seat actually issued)")
    print(f"  refused by baseline                      {len(base_w):>6}")
    print(f"  freed by REDUCTIONS alone (A+D)          {len(red_only):>6}"
          f"  ({len(red_only)/max(len(base_w),1):5.1%} of refusals)")
    print(f"  freed by reductions + ADMISSIONS (A-D)   {len(full):>6}"
          f"  ({len(full)/max(len(base_w),1):5.1%} of refusals)")
    print(f"  of those, screen finds no write token    {len(clean):>6}"
          f"  ({len(clean)/max(len(full),1):5.0%})")
    print()
    print("  Reductions are the stronger evidence: the real gate still decides them.")
    print("  Admissions rest on this file's claim that a name cannot write, and are")
    print("  only as good as the control above.")
    dirty = [c for c in full if not rgc.plainly_read_only(c)]
    if dirty:
        print(f"\n  {len(dirty)} newly-admitted commands DO carry a write token -- audit these:")
        for c in dirty[:10]:
            print(f"    ! {' '.join(c.split())[:130]}")
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
