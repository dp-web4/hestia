#!/usr/bin/env python3
"""Adversarial battery for the shell-scope gap (dp, 2026-10-05: "yes on gate gap, let's fix it").

THE GAP. `command_scope_reach` judged only shell tokens UNDER the workspace, so `cat /abs/outside`
passed on every seat while a Read of the same path was refused `mrh.path`. Measured live
2026-10-05: a session listed and read a mail client's profile directory on a Windows mount through
the shell, and the core returned (True, None, None) for it.

THE RULE UNDER TEST. A shell path that lands OUTSIDE the workspace is judged exactly like a Read
path: temp roots, the member's home markers, `path:` grants (exact, or `/**` recursive) by realpath.
The POSIX device sinks (`/dev/null`, `/dev/std*`, `/dev/fd/*`, ...) are always reachable. Data
heredoc bodies are not reach; interpreter heredoc bodies are.

Written BEFORE the fix (write-the-adversarial-battery-first): every DENY row below passed on main.
`--against-main` prints how many of them main let through.

    python3 tools/shell_scope_reach_battery_test.py
    HESTIA_SCOPE_BATTERY_CORE=/path/to/core.py python3 tools/shell_scope_reach_battery_test.py

Fixtures live under ~/.cache (never /tmp: /tmp is unconditionally in scope, and a fixture there
passes every assertion for the wrong reason).
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = os.getenv("HESTIA_SCOPE_BATTERY_CORE") or str(REPO / "plugins" / "_shared" / "hestia_gate_core.py")

_spec = importlib.util.spec_from_file_location("hestia_gate_core", CORE_PATH)
G = importlib.util.module_from_spec(_spec)
sys.modules["hestia_gate_core"] = G
_spec.loader.exec_module(G)

FAILS: list = []
PASSES = 0


def check(name: str, cond: bool, detail="") -> None:
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(name)
        print(f"FAIL {name}: {detail}")


class Fixture:
    """base/            (HOME for the run; outside the workspace; not under /tmp)
         ws/granted/a.txt  ws/notgranted/b.txt
         outside/secret.txt outside/sub/deep.txt outside/bin/python outside/script.py
         marker/own.txt     (the member's home marker)
       plus a temp dir (under TMPDIR) holding a symlink to outside/."""

    def __init__(self):
        root = os.path.expanduser("~/.cache/hestia-shell-scope-battery")
        os.makedirs(root, exist_ok=True)
        self.base = tempfile.mkdtemp(dir=root)
        assert not self.base.startswith(("/tmp/", "/var/tmp/")), self.base
        b = self.base
        self.ws = f"{b}/ws"
        self.out = f"{b}/outside"
        self.marker = f"{b}/marker"
        for d in (f"{self.ws}/granted", f"{self.ws}/notgranted", f"{self.out}/sub", f"{self.out}/bin",
                  self.marker):
            os.makedirs(d, exist_ok=True)
        for f in (f"{self.ws}/granted/a.txt", f"{self.ws}/notgranted/b.txt", f"{self.out}/secret.txt",
                  f"{self.out}/sub/deep.txt", f"{self.out}/bin/python", f"{self.out}/script.py",
                  f"{self.marker}/own.txt", f"{b}/notes.txt"):
            pathlib.Path(f).write_text("x\n")
        # A link INSIDE a granted repo whose target is outside (the #953 venv shape).
        os.symlink(f"{self.out}/bin/python", f"{self.ws}/granted/venvpy")
        # A link under a TEMP root whose target is outside: lexically temp, really not.
        self.tmp = tempfile.mkdtemp()
        os.symlink(self.out, f"{self.tmp}/link")
        self.cwd = f"{self.ws}/granted"

    def reach(self, cmd, scopes=("granted",), markers=None, cwd=None):
        try:
            return G.command_scope_reach(cmd, list(scopes), self.ws, cwd or self.cwd,
                                         home_markers=(self.marker,) if markers is None else markers)
        except TypeError:   # a pre-fix core (no home_markers) — `--against-main` measures it
            return G.command_scope_reach(cmd, list(scopes), self.ws, cwd or self.cwd)

    def profile(self, scopes):
        return G.HarnessProfile(member_id="battery", identity_path="/nonexistent/identity.json",
                                home_markers=(self.marker,))

    def policy(self, scopes):
        return G.AgentPolicy(member_id="battery", scope=tuple(scopes), source="vault")


def run(fx: Fixture) -> dict:
    o, ws = fx.out, fx.ws
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = fx.base
    deny, allow = [], []
    try:
        deny += [
            # plain, quoted, and the Read-parity target
            ("plain-abs", f"cat {o}/secret.txt"),
            ("double-quoted", f'cat "{o}/secret.txt"'),
            ("single-quoted", f"cat '{o}/secret.txt'"),
            ("ls-dir", f"ls -la {o}"),
            # home spellings
            ("tilde", "cat ~/notes.txt"),
            ("dollar-HOME", "cat $HOME/notes.txt"),
            ("braced-HOME", "cat ${HOME}/notes.txt"),
            ("tilde-into-ungranted-repo", "cat ~/ws/notgranted/b.txt"),
            ("bare-home", "ls ~"),
            # relative escapes
            ("dotdot-escape", "cat ../../outside/secret.txt"),
            ("ws-traversal-out", f"cat {ws}/../outside/secret.txt"),
            # symlinks (the in-repo link is judged by its target under a `path:` grant; see the
            # residual pinned below for a repo-NAME grant, which Read shares)
            ("temp-link-to-outside", f"cat {fx.tmp}/link/secret.txt"),
            ("ln-to-outside", f"ln -s {o}/secret.txt {ws}/granted/l"),
            # globs
            ("glob", f"cat {o}/*.txt"),
            ("glob-dir", f"ls {o}/sub/*"),
            # redirections
            ("redirect-out", f"echo x > {o}/new.txt"),
            ("redirect-append", f"echo x >>{o}/new.txt"),
            ("redirect-stderr", f"make 2>{o}/err.log"),
            ("redirect-both", f"make &>{o}/all.log"),
            ("redirect-in", f"wc -l < {o}/secret.txt"),
            # pipes and lists
            ("pipe-tee", f"cat {ws}/granted/a.txt | tee {o}/copy.txt"),
            ("and-list", f"true && cat {o}/secret.txt"),
            ("semicolon", f"echo hi; cat {o}/secret.txt"),
            # substitutions, quoted or not
            ("cmd-subst-quoted", f'echo "$(cat {o}/secret.txt)"'),
            ("cmd-subst-bare", f"echo $(cat {o}/secret.txt)"),
            ("backticks", f"echo `cat {o}/secret.txt`"),
            # here-strings and interpreter heredocs
            ("here-string", f"cat <<< {o}/secret.txt"),
            ("python-heredoc", f"python3 - <<'EOF'\nprint(open('{o}/secret.txt').read())\nEOF"),
            ("bash-heredoc", f"bash <<EOF\ncat {o}/secret.txt\nEOF"),
            ("sudo-sh-heredoc", f"sudo sh <<EOF\ncat {o}/secret.txt\nEOF"),
            # directory-changing options
            ("git-C", f"git -C {o} status"),
            ("make-directory-eq", f"make --directory={o}"),
            ("tar-C-attached", f"tar -C{o} -xf x.tar"),
            ("cd-then-act", f"cd {o} && ls"),
            # interpreters with file args
            ("python-file", f"python3 {o}/script.py"),
            ("bash-file", f"bash {o}/script.py"),
            # assignments and option values
            ("env-assign", f"CFG={o}/secret.txt run"),
            ("opt-eq", f"tool --config={o}/secret.txt"),
            # network pseudo-device and the root
            ("dev-tcp", "cat < /dev/tcp/127.0.0.1/9"),
            ("find-root", "find / -name x"),
            ("du-root-glob", "du -sh /* 2>/dev/null"),
            ("find-root-after-newline", "echo start\nfind / -maxdepth 1"),
        ]
        allow += [
            # device sinks stay reachable
            ("dev-null", "ls 2>/dev/null"),
            ("dev-null-both", "make &>/dev/null"),
            ("dev-stderr", "echo x >/dev/stderr"),
            ("dev-stdout", "echo x >/dev/stdout"),
            ("dev-stdin", "cat /dev/stdin"),
            ("dev-fd", "exec 3>/dev/fd/3"),
            ("dev-urandom", "head -c 8 /dev/urandom"),
            # temp roots, home markers, the workspace rule
            ("tmp", "cat /tmp/anything"),
            ("tmp-under-TMPDIR", f"ls {fx.tmp}"),
            ("home-marker", f"cat {fx.marker}/own.txt"),
            ("granted-repo", f"cat {ws}/granted/a.txt"),
            ("granted-via-tilde", "cat ~/ws/granted/a.txt"),
            ("relative-in-repo", "cat a.txt"),
            # not paths
            ("sed-address", "sed '/^#/d' a.txt"),
            ("regex-alternation", "grep -E '/(foo|bar)/' a.txt"),
            ("url", "curl -s https://example.com/a/b/c"),
            ("scp-remote", "scp host:/etc/passwd ."),
            ("path-list", "PATH=$HOME/.local/bin:$PATH ls"),
            # a word of slashes alone is a delimiter unless a walker takes it as its argument
            ("tr-slash", "echo a/b | tr / _"),
            ("tr-quoted-slash", "echo a/b | tr '/' '_'"),
            ("cut-delim", "echo a/b | cut -d/ -f2"),
            ("awk-fs", "awk -F/ '{print $1}' a.txt"),
            ("ifs-slash", "IFS=/ read -r x y <<< a/b"),
            ("c-comment-in-python", "python3 -c 'x = 1  # /* not a glob */'"),
            ("python-heredoc-code-noise",
             "python3 - <<'EOF'\nimport re\nt = re.search(r'<table.*?</table>', h)\n"
             "parts = p.split('/')\nif s.startswith('//'): pass\nx = 'a' + \"/\" + 'b'\nEOF"),
            ("subst-dot-suffix", "cp -r $(dirname $f)/. $d/"),
            ("grep-slash-pattern", "grep -v '//' a.txt"),
            # data heredoc bodies are data
            ("data-heredoc", f"cat > {fx.tmp}/note.md <<'EOF'\nsee {o}/secret.txt\nEOF"),
            ("commit-message-heredoc",
             f"git commit -m \"$(cat <<'EOF'\nfix: refused {o}/secret.txt\nEOF\n)\""),
            # a quoted sentence is one word, not a path
            ("quoted-sentence", f"git commit -m 'gate refused {o}/secret.txt as outside'"),
            # the gate's own refusal hints, quoted back
            ("hint-spelling", f"echo 'path:{o}/**'"),
            ("hint-recursive-word", f"echo path:{o}/sub/**"),
        ]
        for name, cmd in deny:
            ok, tok, resolved = fx.reach(cmd)
            check(f"deny:{name}", ok is False, f"{cmd!r} -> {(ok, tok, resolved)}")
            check(f"deny-names-a-path:{name}", bool(resolved), f"{cmd!r} -> {(ok, tok, resolved)}")
        for name, cmd in allow:
            ok, tok, resolved = fx.reach(cmd)
            check(f"allow:{name}", ok is True, f"{cmd!r} -> {(ok, tok, resolved)}")

        # GRANTS: the existing forms reach, at exactly their breadth.
        exact = ("granted", f"path:{o}/secret.txt")
        rec = ("granted", f"path:{o}/**")
        sub_rec = ("granted", f"path:{o}/sub/**")
        check("grant-exact-allows-exact", fx.reach(f"cat {o}/secret.txt", exact)[0] is True)
        check("grant-exact-not-sibling", fx.reach(f"cat {o}/sub/deep.txt", exact)[0] is False)
        check("grant-exact-not-glob", fx.reach(f"cat {o}/*.txt", exact)[0] is False)
        check("grant-recursive-allows-subtree", fx.reach(f"cat {o}/sub/deep.txt", rec)[0] is True)
        check("grant-recursive-allows-glob", fx.reach(f"cat {o}/*.txt", rec)[0] is True)
        check("grant-sub-recursive-not-parent", fx.reach(f"cat {o}/secret.txt", sub_rec)[0] is False)
        check("grant-reached-through-traversal", fx.reach(f"cat {ws}/../outside/secret.txt", exact)[0] is True)
        check("grant-reached-through-dotdot", fx.reach("cat ../../outside/secret.txt", exact)[0] is True)
        # A PRE-EXISTING link inside a granted tree whose target is outside (the #953 venv
        # interpreter) keeps its allowance under a `path:` grant — refusing it would re-open #953
        # on every seat holding `path:<ws>/**`. MAKING such a link names its target, and that
        # naming IS judged (deny row `ln-to-outside` above). Pinned both ways.
        ws_rec = (f"path:{ws}/granted/**",)
        check("residual-preexisting-link-under-path-grant-admitted",
              fx.reach(f"{ws}/granted/venvpy -V", ws_rec)[0] is True)
        check("making-the-link-is-judged",
              fx.reach(f"ln -s {o}/secret.txt {ws}/granted/l2", ws_rec)[0] is False)
        # RESIDUAL, pinned (shared with Read): under a repo-NAME grant the workspace rule is
        # lexical, so a link inside the repo is admitted by its spelling, for Read and shell
        # alike. Closing it is a Read-and-shell change together, not this one.
        check("residual-repo-name-link-admitted-like-read",
              fx.reach(f"{ws}/granted/venvpy -V")[0] is True
              and not G.evaluate(G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/venvpy"], cwd=fx.cwd),
                                 fx.profile(("granted",)), ws, policy=fx.policy(("granted",))).blocks)
        check("grant-reached-through-temp-link", fx.reach(f"cat {fx.tmp}/link/secret.txt", rec)[0] is True)
        check("grant-tilde-spelling", fx.reach("cat ~/notes.txt", ("granted", f"path:{fx.base}/notes.txt"))[0] is True)

        # HOME MARKERS come from the caller: a caller passing none gets none (narrow direction).
        check("no-markers-no-home-allowance", fx.reach(f"cat {fx.marker}/own.txt", markers=())[0] is False)

        # EGRESS still dominates: a temp link whose target names a forbidden token.
        os.makedirs(f"{o}/.ssh", exist_ok=True)
        pathlib.Path(f"{o}/.ssh/id").write_text("x\n")
        os.symlink(f"{o}/.ssh/id", f"{fx.tmp}/innocent")
        r = fx.reach(f"cat {fx.tmp}/innocent", rec)
        check("egress-through-temp-link", r[0] is False and ".ssh" in (r[1] or ""), r)

        # evaluate(): the refusal is mrh.command, names the outside path, carries it as data,
        # and a Read of the same path is refused too (parity is the whole point).
        prof = fx.profile(("granted",))
        pol = fx.policy(("granted",))
        v = G.evaluate(G.NormalizedEvent(tool="Bash", command=f"cat {o}/secret.txt", cwd=fx.cwd),
                       prof, ws, policy=pol)
        check("evaluate-denies-mrh-command", v.blocks and v.rule == "mrh.command", v)
        check("evaluate-says-outside", "outside the workspace" in v.reason, v.reason)
        check("evaluate-carries-target", getattr(v, "target", "") == f"{o}/secret.txt", getattr(v, "target", None))
        check("remedy-names-scope-status", "hestia_scope_status" in v.remedy, v.remedy)
        vr = G.evaluate(G.NormalizedEvent(tool="Read", paths=[f"{o}/secret.txt"], cwd=fx.cwd),
                        prof, ws, policy=pol)
        check("read-parity-denies", vr.blocks and vr.rule == "mrh.path", vr)
        check("read-carries-target", getattr(vr, "target", "") == f"{o}/secret.txt", getattr(vr, "target", None))
        v2 = G.evaluate(G.NormalizedEvent(tool="Bash", command=f"cat {fx.marker}/own.txt", cwd=fx.cwd),
                        prof, ws, policy=pol)
        check("evaluate-passes-home-markers", v2.decision == "allow", v2)
        # Parity on the deny side: every absolute deny target is also refused to Read.
        for name, cmd in deny:
            ok, tok, resolved = fx.reach(cmd)
            if resolved and resolved.startswith("/") and not resolved.endswith("/*") and resolved != "/":
                vr = G.evaluate(G.NormalizedEvent(tool="Read", paths=[resolved], cwd=fx.cwd), prof, ws,
                                policy=pol)
                check(f"read-parity:{name}", vr.blocks, f"{resolved} -> {vr}")
        # An unscoped member is still unscoped (the gap closes MRH, it does not touch `*`).
        vu = G.evaluate(G.NormalizedEvent(tool="Bash", command=f"cat {o}/secret.txt", cwd=fx.cwd),
                        prof, ws, policy=G.AgentPolicy(member_id="battery", scope=("*",), source="vault"))
        check("unscoped-unchanged", vu.decision == "allow", vu)
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
    return {"deny": deny, "allow": allow}


def against_main(fx: Fixture) -> int:
    """How many DENY rows the given core lets through — on main, the size of the gap."""
    rows = run(fx)
    leaked = [n for n, c in rows["deny"] if fx.reach(c)[0] is True]
    print(f"deny rows the core ALLOWS: {len(leaked)}/{len(rows['deny'])}: {', '.join(leaked)}")
    return 0


def main() -> int:
    fx = Fixture()
    if "--against-main" in sys.argv:
        return against_main(fx)
    run(fx)
    print(f"shell-scope battery: {PASSES} passed, {len(FAILS)} failed (core: {CORE_PATH})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
