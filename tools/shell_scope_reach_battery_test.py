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

NARROWED (dp's ruling, 2026-10-10: "narrow and land"). Four Codex rounds found false-allows in the
attempt to MODEL what a substitution or variable expands to (name-keyed output tables: "head prints
lines, date never prints paths"), and the class is unsound: `date +/x`, `seq -f`, `shuf -e`,
`expr`, `wc`/`sha256sum` operand echo, `grep`/`sort`/`head FILE` all print paths. So nothing an
expansion produces is modelled any more. A command substitution, a process substitution, a
variable (quoted or not), brace expansion, argv built from stdin (`xargs`), or an expansion used as
the program, wherever its value would be judged as a path, is UNENUMERATED. The act is refused
with the `hestia:unpriceable:unenumerated` target (#1274's sentinel), which the gate turns into a
scope REQUEST that only a one-time approval of that exact act can lift. `request` rows below pin
exactly that: refused, AND refused as the sentinel (never a silent allow, never a dead end).
`--classify` prints every row's verdict under the given core (battery-first evidence).

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
    deny, allow, request = [], [], []
    os.environ["SCOPE_BATTERY_ENV_SET"] = "1"
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
            ("here-string-subst", f"cat <<< \"$(cat {o}/secret.txt)\""),
            # Codex re-review of #1232 (P1-3, default-judge): quoting does not exempt a path,
            # options are keyed to their command, quoting is per character.
            ("grep-r-quoted-root", 'grep -r x "/"'),
            ("grep-rn-single-quoted-root", "grep -rn x '/'"),
            ("ls-s-root", "ls -s /"),
            ("ls-s-dashdash-root", "ls -s -- /"),
            ("echo-quoted-root-unquoted-star", 'echo "/"*'),
            ("printf-quoted-root-unquoted-star", 'printf "%s\\n" "/"*'),
            ("cut-delim-then-file", f"cut -d / -f1 {o}/secret.txt"),
            ("awk-fs-then-file", f"awk -F / '{{print $1}}' {o}/secret.txt"),
            ("grep-e-then-file", f"grep -e x {o}/secret.txt"),
            ("grep-pattern-is-path-shaped-then-file", f"grep /x/ {o}/secret.txt"),
            ("for-loop-glob", f"for f in {o}/*; do echo $f; done"),
            ("bash-c-string", f"bash -c 'cat {o}/secret.txt'"),
            ("python-c-literal", f"python3 -c \"print(open('{o}/secret.txt').read())\""),
            ("assigned-var", f"D={o}; cat $D/secret.txt"),
            ("braced-var", f"D={o}; cat ${{D}}/secret.txt"),
            # Codex re-review P1-2: the WHOLE unquoted heredoc body, line boundaries intact.
            ("heredoc-multiline-subst", f"cat <<EOF\n$(\ncat {o}/secret.txt\n)\nEOF"),
            ("heredoc-continued-subst", f"cat <<EOF\n$(cat \\\n{o}/secret.txt)\nEOF"),
            ("heredoc-subst-in-quotes-still-expands", f"cat <<EOF\n'$(cat {o}/secret.txt)'\nEOF"),
            ("quoted-heredoc-marker-is-text", f"echo \"x<<EOF\"\ncat {o}/secret.txt"),
            # Unmodelled shell is INCOMPLETE, refused — never skipped.
            ("unknown-var-in-path", "cat $SCOPE_BATTERY_UNSET_VAR/secret.txt"),
            ("substitution-output-as-path", "cp -r $(dirname $f)/. $d/"),
            ("unbalanced-quote", f"cat '{o}/secret.txt"),
            ("unclosed-substitution", f"echo $(cat {o}/secret.txt"),
            ("unknown-heredoc-form", "cat <<$TERMINATOR\nx\n$TERMINATOR"),
            ("for-list-outside", f"for f in {o}/secret.txt; do cat $f; done"),
            # Codex review 17029 of patch 3f81192064560a33 — seven probes that ALLOWED:
            ("17029a-loop-item-past-cap",
             "for f in " + " ".join(f"/tmp/review-probe-{i}" for i in range(40)) + f" {o}/secret.txt; do cat $f; done"),
            ("17029b-empty-var-default", f"D=;cat ${{D:-{o}/secret.txt}}"),
            ("17029c-tr-glob-expands", f"tr {o}/* x"),
            ("17029c-grep-pattern-glob-expands", f"grep {o}/*"),
            ("17029d-heredoc-arith-subst", f"cat <<EOF\n$(( $(cat {o}/secret.txt) ))\nEOF"),
            ("17029e-date-then-echo-subst", f"cat \"$(date >/dev/null;echo {o}/secret.txt)\""),
            ("17029f-python-c-dir-literal", f"python3 -c \"import os; os.listdir('{o}/')\""),
            # variants
            ("arith-subst-inline", f"echo $(( $(cat {o}/secret.txt) + 1 ))"),
            ("while-read-from-outside-find", f"find {o} -name secret.txt | while read f; do cat \"$f\"; done"),
            ("lister-pipeline-outside", f"cat $(find {o} -name secret.txt 2>/dev/null | head -1)"),
            ("rewriting-pipeline-is-unmodelled", "cat $(ls | sed s/a/b/)"),
            ("grep-o-pipeline-is-unmodelled", "cat $(find . -name x | grep -o 'y.*')"),
            ("redirect-to-file-pipeline-is-unmodelled", "cat $(find . 2>err.log | head -1)"),
            ("while-read-from-cat-is-unknown", "cat list.txt | while read f; do cat \"$f\"; done"),
            ("printf-glob-expands", f"printf '%s' {o}/*"),
            ("echo-glob-quoted-dir-unquoted-star", f"echo \"{o}\"/*"),
            ("unquoted-heredoc-inside-subst",
             f"x=\"$(cat <<EOF\n$(cat {o}/secret.txt)\nEOF\n)\""),
            ("lister-subst-outside", f"cat $(find {o} -name secret.txt)"),
            ("default-param-outside", f"cat ${{SCOPE_BATTERY_UNSET_VAR:-{o}/secret.txt}}"),
            ("echo-subst-path", f"cat \"$(echo {o}/secret.txt)\""),
            ("dirname-subst", f"ls $(dirname {o}/secret.txt)"),
            ("arbitrary-output-as-path", "cat $(cat list.txt)"),
            ("positional-param-path", "cat $1/x"),
            ("while-read-var", "while read f; do cat $f/x; done < list.txt"),
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
            # Codex review of #1232, P1-4: an unquoted root glob expands for EVERY command, and a
            # literal root is a path argument except in true delimiter/string positions.
            ("cat-root-glob", "cat /*"),
            ("echo-root-glob-expands", "echo /*"),
            ("head-root-glob", "head -n1 /*"),
            ("grep-under-root", "grep -r x /"),
            ("cat-root-literal", "cat /"),
            ("redirect-into-root-glob", "cat < /*"),
            # Codex review of #1232, P1-2: an UNQUOTED heredoc body is expanded before its
            # consumer runs, so its substitutions are executed commands.
            ("unquoted-heredoc-subst", f"cat <<EOF\n$(cat {o}/secret.txt)\nEOF"),
            ("unquoted-heredoc-backtick", f"cat <<EOF\n`cat {o}/secret.txt`\nEOF"),
            ("unquoted-heredoc-nested", f"cat <<EOF\n${{X:-$(echo $(cat {o}/secret.txt))}}\nEOF"),
            ("unquoted-heredoc-tabstrip", f"cat <<-EOF\n\t$(cat {o}/secret.txt)\n\tEOF"),
            ("unquoted-python-heredoc-subst", f"python3 - <<EOF\nprint('$(cat {o}/secret.txt)')\nEOF"),
            ("quoted-subst-nested", f'echo "$(cat "$(echo {o}/secret.txt)")"'),
            # Codex review of #1232, P1-3: past the judging budget the command is refused, never
            # allowed — repeated spellings count once, distinct ones fail closed.
            ("budget-repeat-then-outside", "cat " + " ".join(["/tmp/review-probe"] * 70 + [f"{o}/secret.txt"])),
            ("budget-distinct-overflow", "cat " + " ".join(f"/tmp/review-probe-{i}" for i in range(140))),
            ("find-root-after-newline", "echo start\nfind / -maxdepth 1"),
            # Codex review 17054 (notice 17068), P1-quote-context: a dequoted apostrophe must not
            # hide a live substitution from the body lifter.
            # A resolved literal is judged like the literal it is (dp, 2026-10-11).
            ("lit-resolves-to-outside", f"S={o}/secret.txt; cat \"$S\""),
            ("lit-resolves-under-outside-dir", f"S={o}; cat $S/secret.txt"),
            ("lit-empty-value-then-root-path", "S=; cat $S/etc/hostname"),
            ("17054-printf-apostrophe-subst", f"printf '%s\\n' \"'$(cat {o}/secret.txt)'\""),
            ("17054-echo-apostrophe-subst", f"echo \"'$(cat {o}/secret.txt)'\""),
            # Codex review 17054, P1-output-model, and the class the author's probes widened it to
            # (notice-17068-response.md): an output model keyed on the command NAME is unsound.
            ("17054-date-format-path", f"cat \"$(date +{o}/secret.txt)\""),
            ("17054-find-printf-path", f"cat \"$(find . -maxdepth 0 -printf {o}/secret.txt)\""),
            ("17054-head-file-operand", "cat \"$(find . -maxdepth 0 | head -n1 paths.txt)\""),
            ("class-seq-f", f"cat \"$(seq -f '{o}/secret%g.txt' 1 1)\""),
            ("class-shuf-e", f"cat $(shuf -e {o}/secret.txt)"),
            ("class-expr", f"cat $(expr {o}/secret.txt)"),
            ("class-sha256sum-operand", "cat $(sha256sum paths.txt | cut -d' ' -f3)"),
            ("class-wc-operand", "cat $(wc -l paths.txt)"),
            ("class-grep-file", "cat $(grep -h . paths.txt)"),
            ("class-sort-file", "cat $(sort paths.txt)"),
            ("class-head-file", "cat \"$(head -n1 paths.txt)\""),
            ("class-date-plain-format", "cat /tmp/run-$(date +%s)/../../..$HOME/notes.txt"),
            # kimi-code adversarial review of #1232 (F2): expansion-time structure and heredoc heads.
            ("kimi-A01-unset-var-prefix", "cat $SCOPE_BATTERY_UNSET_VAR/etc/hostname"),
            ("kimi-A02-ifs-glue-in-subst", "echo $(cat${IFS}/etc/hostname)"),
            ("kimi-A03-ifs-glue", "cat$IFS/etc/hostname"),
            ("kimi-A04-sudo-u-bash-heredoc", f"sudo -u root bash <<EOF\ncat {o}/secret.txt\nEOF"),
            ("kimi-A06-chroot-bash-heredoc", f"chroot / bash <<EOF\ncat {o}/secret.txt\nEOF"),
            ("kimi-A08-default-dir", "cat ${SCOPE_BATTERY_UNSET_VAR:-/etc}/hostname"),
            # Found writing this battery (2026-10-10), in 01e68a1c as well as main: a relative path
            # after a directory change, shell code in a string argument, a reassigned HOME, brace
            # expansion and a glob followed by `..`, and argv built from stdin.
            ("cd-temp-then-dotdot", f"cd {fx.tmp} && cat {os.path.relpath(o + '/secret.txt', fx.tmp)}"),
            ("git-C-temp-then-dotdot",
             f"git -C {fx.tmp} diff --no-index {os.path.relpath(o + '/secret.txt', fx.tmp)} x"),
            ("eval-string", f"eval \"cat {o}/secret.txt\""),
            ("find-exec-sh-c", f"find . -exec sh -c 'cat {o}/secret.txt' \\;"),
            ("su-c-string", f"su -c 'cat {o}/secret.txt'"),
            ("home-reassigned-then-tilde", f"HOME={o}; cat ~/secret.txt"),
            ("brace-dotdot", f"cat /tmp/{{..,x}}{o}/secret.txt"),
            ("glob-then-dotdot", f"cat /tmp/*/../..{o}/secret.txt"),
            ("xargs-from-echo", f"echo {o}/secret.txt | xargs cat"),
            ("procsub-reads-outside", f"diff <(cat {o}/secret.txt) a.txt"),
        ]
        # REQUESTS: refused AS the unenumerated sentinel. The gate opens a scope request that a
        # one-time approval of this exact act lifts. The first block ALLOWED on 01e68a1c.
        request += [
            ("17054-date-format-path", f"cat \"$(date +{o}/secret.txt)\""),
            ("17054-find-printf-path", f"cat \"$(find . -maxdepth 0 -printf {o}/secret.txt)\""),
            ("17054-head-file-operand", "cat \"$(find . -maxdepth 0 | head -n1 paths.txt)\""),
            ("class-seq-f", "cat \"$(seq -f '/tmp/review-probe%g' 1 1)\""),
            ("class-shuf-e", "cat $(shuf -e /tmp/review-probe)"),
            ("class-expr", "cat $(expr /tmp/review-probe)"),
            ("class-wc-operand", "cat $(wc -l paths.txt)"),
            ("class-grep-file", "cat $(grep -h . paths.txt)"),
            ("class-sort-file", "cat $(sort paths.txt)"),
            ("class-head-file", "cat \"$(head -n1 paths.txt)\""),
            ("kimi-A01-unset-var-prefix", "cat $SCOPE_BATTERY_UNSET_VAR/etc/hostname"),
            ("kimi-A03-ifs-glue", "cat$IFS/etc/hostname"),
            ("kimi-A08-default-dir", "cat ${SCOPE_BATTERY_UNSET_VAR:-/etc}/hostname"),
            ("home-reassigned-then-tilde", "HOME=/tmp/review-probe; cat ~/x"),
            ("brace-dotdot", "cat /tmp/{..,x}/etc/hostname"),
            ("glob-then-dotdot", "cat /tmp/*/../../etc/hostname"),
            ("xargs-from-echo", "echo /tmp/review-probe | xargs cat"),
            ("procsub-as-path", "diff <(sort a.txt) a.txt"),
            ("expansion-as-program", "$(command -v cat) a.txt"),
            ("quoted-var", "cat \"$SCOPE_BATTERY_UNSET_VAR/x\""),
            ("subshell-assignment-leak", "D=/tmp/review-probe-a; (D=/tmp/review-probe-b); cat $D/x"),
            ("prefix-assignment-not-in-scope-of-expansion", "D=/tmp cat $D/hostname"),
            ("cd-unknown-then-relative", "cd \"$SCOPE_BATTERY_UNSET_VAR\" && cat ../x/y"),
            # formerly MODELLED (allowed on 01e68a1c): now unenumerated, and priced honestly
            ("was-for-relative-glob", "for f in *.txt; do cat $f; done"),
            ("was-lister-subst-relative", "cat $(find . -name '*.txt')"),
            ("was-date-in-temp-path", "x=$(date +%s); cat /tmp/review-probe-$x"),
            ("was-default-param-under-temp", "cat ${SCOPE_BATTERY_UNSET_VAR:-/tmp/review-probe}"),
            ("was-while-read-from-relative-find",
             "find . -name '*.txt' | while read f; do cat \"$f\"; done"),
            ("was-while-read-from-ls", "ls | while read -r f; do wc -l \"$f\"; done"),
            ("was-lister-pipeline-head", "cat $(find . -name '*.txt' 2>/dev/null | head -1)"),
            ("was-lister-pipeline-sort-grep", "cat $(ls | sort | grep txt | tail -1)"),
            ("was-lister-pipeline-sed-n-line", "f=$(ls -t *.txt | sed -n 2p); cat \"$f\""),
            ("was-pwd-subst", "cat \"$(pwd)/a.txt\""),
            # dp, 2026-10-11: the single-literal-assignment rule is scoped exactly this tightly.
            # Each row is an exclusion that must stay UNENUMERATED (a scope request).
            # The literal-list loop rule's exclusions that stay UNENUMERATED (scope requests).
            ("litfor-glob-list", "for f in *.txt; do cat $f; done"),
            ("litfor-dotdot-item", "for d in a ..; do ls $d/x; done"),
            ("litfor-rebound-in-body", "for r in a b; do r=$(pwd); cat $r/x; done"),
            ("litfor-read-rebinds", "for r in a b; do read r; cat $r/x; done"),
            ("litfor-eval-body", "for r in a b; do eval \"cat $r\"; done"),
            ("litfor-quoted-item", "for r in 'a b' c; do cat $r/x; done"),
            ("litfor-var-item", "for r in a $SCOPE_BATTERY_UNSET_VAR; do cat $r/x; done"),
            ("litfor-subst-item", "for r in a $(pwd); do cat $r/x; done"),
            ("litfor-ifs-var", "for IFS in a b; do cat $IFS/x; done"),
            ("litfor-piped-out", "for r in a b; do cat $r/x; done | sort"),
            ("litfor-over-budget", "for r in " + " ".join(f"i{k}" for k in range(40)) + "; do cat $r/x; done"),
            # Codex HOLD 23938: a body whose state persists into the next iteration, or that holds a
            # second loop keyword, is judged as before (V unenumerated), not per iteration.
            ("litfor-body-cd", "for f in a.txt b.txt; do cat $f; cd sub; done"),
            ("litfor-body-command-cd", "for f in a.txt b.txt; do cat $f; command cd sub; done"),
            ("litfor-body-pushd", "for f in a.txt b.txt; do pushd sub; cat $f; done"),
            ("litfor-body-assigns", "for f in a.txt b.txt; do cat $f; Z=sub; done"),
            ("litfor-body-default-assign", "for f in a.txt b.txt; do cat ${Z:=sub}/$f; done"),
            ("litfor-body-printf-v", "for f in a.txt b.txt; do printf -v Z %s sub; cat $Z/$f; done"),
            ("litfor-body-function-def", "for f in a.txt b.txt; do g(){ cat $f; }; g; done"),
            ("litfor-body-dot-source", "for f in a.txt b.txt; do . ./x; cat $f; done"),
            ("litfor-body-done-word", "for f in a.txt b.txt; do cat $f; echo done; done"),
            ("litfor-body-comment", "for f in a.txt b.txt; do cat $f # ; done\ndone"),
            ("litfor-trailing-semicolon", "for f in a.txt b.txt; do cat $f; done;"),
            ("litfor-done-without-separator", "for f in a.txt b.txt; do cat $f &done"),
            ("lit-use-before-assignment", "cat $S/x; S=/tmp/review-probe"),
            ("lit-assignment-is-a-pipeline-stage", "S=/tmp/review-probe | cat $S/x"),
            ("lit-assignment-entered-from-a-pipe", "true | S=/tmp/review-probe; cat $S/x"),
            ("lit-prefix-assignment-does-not-bind", "S=/tmp/review-probe cat $S/x"),
            ("lit-reassigned", "S=/tmp/review-probe; S=/tmp/review-probe-2; cat $S/x"),
            ("lit-conditional-and", "true && S=/tmp/review-probe; cat $S/x"),
            ("lit-conditional-or", "S=/tmp/review-probe || S=/tmp/review-probe-2; cat $S/x"),
            ("lit-default-expansion", "S=/tmp/review-probe; cat ${S:-/tmp/x}/y"),
            ("lit-assigned-in-subshell", "(S=/tmp/review-probe); cat $S/x"),
            ("lit-used-in-its-subshell", "(S=/tmp/review-probe; cat $S/x)"),
            ("lit-assigned-in-brace-group", "{ S=/tmp/review-probe; }; cat $S/x"),
            ("lit-assigned-in-function", "f() { S=/tmp/review-probe; }; f; cat $S/x"),
            ("lit-assigned-in-substitution", "x=$(S=/tmp/review-probe); cat $S/x"),
            ("lit-substitution-to-substitution", "a=$(S=/tmp/review-probe; true); b=$(cat $S/x)"),
            ("lit-value-is-a-substitution", "S=$(echo /tmp/review-probe); cat $S/x"),
            ("lit-value-has-a-dollar", "S=/tmp/$SCOPE_BATTERY_UNSET_VAR; cat $S/x"),
            ("lit-value-has-a-quoted-dollar", "S='/tmp/$x'; cat $S/y"),
            ("lit-value-has-a-glob", "S=/tmp/*; cat $S/x"),
            ("lit-value-has-dotdot", "S=/tmp/../tmp; cat $S/x"),
            ("lit-value-has-a-brace", "S=/tmp/{a,b}; cat $S/x"),
            ("lit-HOME", "HOME=/tmp/review-probe; cat $HOME/x"),
            ("lit-PWD", "PWD=/tmp/review-probe; cat $PWD/x"),
            ("lit-OLDPWD", "OLDPWD=/tmp/review-probe; cat $OLDPWD/x"),
            ("lit-IFS", "IFS=/tmp/review-probe; cat $IFS/x"),
            ("lit-PATH", "PATH=/tmp/review-probe; cat $PATH/x"),
            ("lit-name-in-the-environment", "SCOPE_BATTERY_ENV_SET=/tmp/review-probe; cat $SCOPE_BATTERY_ENV_SET/x"),
            ("lit-read", "read S; cat $S/x"),
            ("lit-read-after", "S=/tmp/review-probe; read S; cat $S/x"),
            ("lit-unset", "S=/tmp/review-probe; unset S; cat $S/x"),
            ("lit-exported-elsewhere", "export S; S=/tmp/review-probe; cat $S/x"),
            ("lit-export-assignment", "export S=/tmp/review-probe; cat $S/x"),
            ("lit-declare", "declare S=/tmp/review-probe; cat $S/x"),
            ("lit-local", "local S=/tmp/review-probe; cat $S/x"),
            ("lit-eval-reassigns", "S=/tmp/review-probe; eval S=/tmp/review-probe-2; cat $S/x"),
            ("lit-sh-c-reassigns", "S=/tmp/review-probe; sh -c 'S=/tmp/review-probe-2'; cat $S/x"),
            ("lit-source", "S=/tmp/review-probe; source ./f.sh; cat $S/x"),
            ("lit-nameref", "S=/tmp/review-probe; declare -n R=S; R=/tmp/review-probe-2; cat $S/x"),
            ("lit-array-element", "S=/tmp/review-probe; S[0]=/tmp/review-probe-2; cat $S/x"),
            ("lit-array-assignment", "S=(/tmp/review-probe); cat $S/x"),
            ("lit-append", "S=/tmp/review-probe; S+=/../../etc; cat $S/hostname"),
            ("lit-printf-v", "S=/tmp/review-probe; printf -v S %s /tmp/review-probe-2; cat $S/x"),
            ("lit-mapfile", "S=/tmp/review-probe; mapfile S < f; cat $S/x"),
            ("lit-let", "S=/tmp/review-probe; let S=1; cat $S/x"),
            ("lit-background", "S=/tmp/review-probe & cat $S/x"),
            # An interpreter anywhere disqualifies every name (Codex 20536, P1-4); also pins that
            # a code literal before the binding does not crash the scan (a 2026-10-11 regression).
            ("lit-after-a-python-c-literal",
             "python3 -c \"print(open('/tmp/review-probe').read())\"; S=/tmp/review-probe; cat $S/x"),
        ]
        # #1287 part 1 (2026-10-13): a value that cannot bind is unenumerated only where its use
        # is judged as a PATH. Message / pattern / string positions (and the prose options) are
        # data; an UNQUOTED glob-valued name there is still a pathname expansion.
        deny += [
            ('1287-prose-flag-does-not-hide-a-file', 'R="x * y"; hestia gate deny X --reason "$R" /etc/hostname'),
            ('1287-prose-flag-does-not-hide-a-glob', 'hestia gate deny X --reason /etc/*'),
            # Codex HOLD 21639: prose is per (command, subcommand), never generic. These options are
            # value-less FLAGS on these commands; the next word is a file and stays judged.
            ('1287-grep-text-is-a-flag', 'grep needle --text /etc/hostname'),
            ('1287-rg-text-is-a-flag', 'rg needle --text /etc/hostname'),
            ('1287-diff-text-is-a-flag', 'diff --text /etc/hostname /dev/null'),
            ('1287-readelf-notes-is-a-flag', 'readelf --notes /etc/hostname'),
            ('1287-git-diff-summary-is-a-flag', 'git diff --no-index /dev/null --summary /etc/hostname'),
            ('1287-gh-pr-review-c-is-a-flag', 'gh pr review 1 -c /etc/hostname'),
            ('1287-gh-prose-needs-its-subcommand', 'gh pr view 1 --body /etc/hostname'),
        ]
        request += [
            ('1287-path-glob-var', 'F="a*"; cat $F'),
            ('1287-path-glob-var-quoted', 'F="a*"; cat "$F"'),
            ('1287-unquoted-glob-var-in-echo', 'R="/tmp/review-probe/*"; echo $R'),
            ('1287-unquoted-glob-var-in-reason', 'R="/tmp/review-probe/*"; hestia gate deny X --reason $R'),
            ('1287-prose-var-also-used-as-a-path', 'R="a* b"; hestia gate deny X --reason "$R" $R'),
            ('1287-dash-m-is-not-prose-for-python', 'R="a* b"; python3 -m "$R"'),
            ('1287-dash-m-is-not-prose-for-mkdir', 'R="a* b"; mkdir -m "$R" x'),
            ('1287-dash-m-is-not-prose-for-hestia', 'R="x * y"; hestia mesh send peer -m "$R"'),
            ('1287-grep-text-var-is-a-file', 'grep needle --text "$SCOPE_BATTERY_UNSET_VAR"'),
            # Codex HOLD 21675: an UNQUOTED value that field splitting breaks apart inserts more
            # arguments, a file among them. Its six shapes, then main's own positions that had it.
            ('1289-split-pr-title-body-file', 'R="hello --body-file /etc/hostname"; gh pr create --title $R'),
            ('1289-split-pr-title-eq-body-file', 'R="hello --body-file /etc/hostname"; gh pr create --title=$R'),
            ('1289-split-issue-title-body-file', 'R="hello --body-file /etc/hostname"; gh issue create --title $R'),
            ('1289-split-release-title-asset', 'R="hello /etc/hostname"; gh release create v2 --title $R'),
            ('1289-split-release-notes-asset', 'R="hello /etc/hostname"; gh release create v2 --notes $R'),
            ('1289-split-release-notes-eq-asset', 'R="hello /etc/hostname"; gh release create v2 --notes=$R'),
            ('1289-split-grep-pattern', 'R="x /etc/hostname"; grep $R'),
            ('1289-split-grep-e', 'R="x /etc/hostname"; grep -e $R'),
            ('1289-split-sed-script', 'R="p /etc/hostname"; sed -n $R'),
            ('1289-split-awk-program', 'R="1 /etc/hostname"; awk $R'),
            ('1289-split-git-m', 'R="x /etc/hostname"; git commit -m $R'),
            ('1289-split-unknown-unquoted-reason', 'hestia gate deny X --reason $SCOPE_BATTERY_UNSET_VAR'),
            ('1289-split-cmdsub-unquoted-pattern', 'grep $(cat a.txt) a.txt'),
            ('1289-split-cmdsub-unquoted-git-m', 'git commit -m $(cat a.txt)'),
            ('1289-split-backtick-unquoted-reason', 'hestia gate deny X --reason `cat a.txt`'),
            # Codex HOLD 21718: quoted, `${A[@]}` is still one argument PER ELEMENT. Its six
            # shapes, then the supplementary ones and main's own positions.
            ('1289-array-pr-title-body-file', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; gh pr create --title "${A[@]}"'),
            ('1289-array-pr-title-eq-body-file', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; gh pr create --title="${A[@]}"'),
            ('1289-array-issue-title-body-file', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; gh issue create --title "${A[@]}"'),
            ('1289-array-release-title-asset', 'A[0]=hello; A[1]=/etc/hostname; gh release create v2 --title "${A[@]}"'),
            ('1289-array-release-notes-asset', 'A[0]=hello; A[1]=/etc/hostname; gh release create v2 --notes "${A[@]}"'),
            ('1289-array-slice-notes-eq-asset', 'A[0]=unused; A[1]=hello; A[2]=/etc/hostname; gh release create v2 --notes="${A[@]:1}"'),
            ('1289-array-positional-slice-reason', 'hestia gate deny X --reason "${@:1}"'),
            ('1289-array-keys-notes', 'A[0]=x; gh release create v2 --notes "${!A[@]}"'),
            ('1289-array-prefix-names-notes', 'gh release create v2 --notes "${!SCOPE_BATTERY@}"'),
            ('1289-array-grep-pattern', 'A[0]=x; A[1]=/etc/hostname; grep "${A[@]}"'),
            ('1289-array-git-m', 'A[0]=x; A[1]=/etc/hostname; git commit -m "${A[@]}"'),
            ('1289-positional-all-reason', 'hestia gate deny X --reason "$@"'),
            # Codex HOLD 21790: the same, nested in a default / alternate word. Its six shapes,
            # then deeper nesting, nested quotes, positionals, and indirection (R='A[@]').
            ('1289-nested-pr-title-default', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; R=; gh pr create --title "${R:-${A[@]}}"'),
            ('1289-nested-pr-title-eq-default', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; R=; gh pr create --title="${R:-${A[@]}}"'),
            ('1289-nested-issue-title-alternate', 'A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; R=yes; gh issue create --title "${R:+${A[@]}}"'),
            ('1289-nested-release-title-default', 'A[0]=hello; A[1]=/etc/hostname; R=; gh release create v2 --title "${R:-${A[@]}}"'),
            ('1289-nested-release-notes-alternate', 'A[0]=hello; A[1]=/etc/hostname; R=yes; gh release create v2 --notes "${R+${A[@]}}"'),
            ('1289-nested-release-notes-eq-default', 'A[0]=hello; A[1]=/etc/hostname; R=; gh release create v2 --notes="${R:-${A[@]}}"'),
            ('1289-nested-twice', 'A[0]=hello; A[1]=/etc/hostname; R=; gh release create v2 --notes "${R:-${X:-${A[@]}}}"'),
            ('1289-nested-inner-quotes', 'A[0]=hello; A[1]=/etc/hostname; R=; gh release create v2 --notes "${R:-"${A[@]}"}"'),
            ('1289-nested-positional', 'R=; gh release create v2 --notes "${R:-$@}"'),
            ('1289-nested-positional-slice', 'R=; gh release create v2 --notes "${R:-${@:1}}"'),
            ('1289-indirect-array', 'A[0]=hello; A[1]=/etc/hostname; R="A[@]"; gh release create v2 --notes "${!R}"'),
            ('1289-indirect-with-default', 'A[0]=hello; A[1]=/etc/hostname; R=A[@]; gh release create v2 --notes "${!R:-x}"'),
            # Codex HOLD 21861: the indirection target from a positional. Its six shapes, then the
            # other special-parameter targets and a nested one.
            ('1289-posind-pr-title', "A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; set -- 'A[@]'; gh pr create --title \"${!1}\""),
            ('1289-posind-pr-title-eq', "A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; set -- 'A[@]'; gh pr create --title=\"${!1}\""),
            ('1289-posind-issue-title', "A[0]=hello; A[1]=--body-file; A[2]=/etc/hostname; set -- 'A[@]'; gh issue create --title \"${!1}\""),
            ('1289-posind-release-title', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; gh release create v2 --title \"${!1}\""),
            ('1289-posind-release-notes', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; gh release create v2 --notes \"${!1}\""),
            ('1289-posind-release-notes-eq', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; gh release create v2 --notes=\"${!1}\""),
            ('1289-posind-multi-digit', "A[0]=hello; A[1]=/etc/hostname; set -- 1 2 3 4 5 6 7 8 9 'A[@]'; gh release create v2 --notes \"${!10}\""),
            ('1289-posind-count', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; gh release create v2 --notes \"${!#}\""),
            ('1289-posind-with-default', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; gh release create v2 --notes \"${!1:-x}\""),
            ('1289-posind-nested', "A[0]=hello; A[1]=/etc/hostname; set -- 'A[@]'; R=; gh release create v2 --notes \"${R:-${!1}}\""),
            ('1289-array-spaced-index', 'A[0]=hello; A[1]=/etc/hostname; gh release create v2 --notes "${A[ @ ]}"'),
        ]
        allow += [
            ('1287-prose-1287-exact-shape', 'cd ~/ws/granted; R="Refused: no seat asked for this. The act is the deploy preflight\'s advisory hold probe (deploy/from-main/hestia-deploy.sh ~L605, plugins/*/expects.json \'evaluate deploy hold\'), fired for ever …"; hestia gate deny 0123abcd --as claude-code --reason "$R"'),
            ('1287-prose-reason-eq', 'R="see plugins/*/x \'q\'"; hestia gate deny 1 --as claude-code --reason="$R"'),
            ('1287-prose-gh-body', 'R="see plugins/*/expects.json \'q\'"; gh pr comment 1 --body "$R"'),
            ('1287-prose-git-m', 'R="fix: plugins/*/x \'b\'"; git commit -m "$R"'),
            ('1287-prose-argument', 'R="plugins/*/x \'y\'"; hestia gate corroborate X --stance dissent --argument "$R"'),
            ('1287-prose-title-body', 'T="a * b"; D="c/* \'d\'"; gh pr create --title "$T" --body "$D"'),
            ('1287-prose-gh-close-comment', 'R="see plugins/*/x"; gh pr close 7 -c "$R"'),
            ('1287-prose-gh-merge-subject', 'R="land plugins/*"; gh pr merge 7 --squash --subject "$R"'),
            ('1287-prose-echo-quoted', 'R="a/* b"; echo "$R"'),
            ('1287-prose-printf-quoted', 'R="a/* b"; printf \'%s\\n\' "$R"'),
            ('1287-prose-grep-pattern-quoted', 'R="a.*b"; grep -n "$R" a.txt'),
            ('1287-prose-unknown-var-quoted-in-reason', 'hestia gate deny X --as claude-code --reason "$SCOPE_BATTERY_UNSET_VAR"'),
            # Codex HOLD 21675 controls: quoted is one argument; an unquoted value is data where it
            # is provably one field; an echo / printf operand split is only more strings.
            ('1289-quoted-title-control', 'R="hello --body-file /etc/hostname"; gh pr create --title "$R"'),
            ('1289-quoted-notes-eq-control', 'R="hello /etc/hostname"; gh release create v2 --notes="$R"'),
            ('1289-quoted-grep-control', 'R="x /etc/hostname"; grep "$R" a.txt'),
            ('1289-unquoted-echo-split-is-strings', 'R="x /etc/hostname"; echo $R'),
            ('1289-one-field-unquoted-reason', 'R=abc; hestia gate deny X --reason $R'),
            ('1289-one-field-unquoted-pattern', 'P=needle; grep $P a.txt'),
            ('1289-arithmetic-unquoted-pattern', 'grep $((1+2)) a.txt'),
            ('1289-status-unquoted-pattern', 'grep $? a.txt'),
            ('1289-quoted-cmdsub-git-m', 'git commit -m "$(cat a.txt)"'),
            ('1289-quoted-backtick-reason', 'hestia gate deny X --reason "`cat a.txt`"'),
            ('1289-quoted-cmdsub-inside-prose', 'gh pr comment 1 --body "ran at $(date), see a.txt"'),
            ('1289-ansi-c-pattern-is-one-word', "grep -v -c $'\\tpass\\t' a.txt"),
            ('1289-loop-var-quoted-in-sed-program', 'for r in 1,2 3,4; do sed -n "${r}p" a.txt; done'),
            # Codex HOLD 21718 controls: these quoted forms are ONE word.
            ('1289-array-star-joins-one-word', 'A[0]=hello; A[1]=/etc/hostname; gh release create v2 --notes "${A[*]}"'),
            ('1289-array-element-is-one-word', 'A[0]=hello; gh release create v2 --notes "${A[0]}"'),
            ('1289-array-count-is-one-word', 'A[0]=hello; gh release create v2 --notes "${#A[@]}"'),
            ('1289-default-with-at-is-one-word', 'gh pr comment 1 --body "${SCOPE_BATTERY_UNSET_VAR:-ping a@b}"'),
            ('1289-array-in-echo-is-strings', 'A[0]=x; A[1]=/etc/hostname; echo "${A[@]}"'),
            # Codex HOLD 21790 controls: nested scalars and joined arrays are ONE word.
            ('1289-nested-star-joins-one-word', 'A[0]=hello; A[1]=/etc/hostname; R=; gh release create v2 --notes "${R:-${A[*]}}"'),
            ('1289-nested-element-is-one-word', 'A[0]=hello; R=; gh release create v2 --notes "${R:-${A[0]}}"'),
            ('1289-nested-scalar-braced-is-one-word', 'X=hi; R=; gh release create v2 --notes "${R:-${X}}"'),
            ('1289-nested-scalar-is-one-word', 'X=hi; R=; gh release create v2 --notes "${R:-$X}"'),
            ('1289-escaped-brace-is-one-word', 'R=; gh release create v2 --notes "${R:-x\\}y}"'),
            ('1289-last-pid-is-one-word', 'gh release create v2 --notes "${!}"'),
            ('1289-indirect-keys-joined-is-one-word', 'A[0]=x; gh release create v2 --notes "${!A[*]}"'),
            # Codex HOLD 21861 controls: the allowlist's one-word heads.
            ('1289-positional-is-one-word', "set -- hi; gh release create v2 --notes \"${1}\""),
            ('1289-positional-default-is-one-word', "gh release create v2 --notes \"${1:-none}\""),
            ('1289-star-is-one-word', 'gh release create v2 --notes "${*}"'),
            ('1289-count-is-one-word', 'A[0]=x; gh release create v2 --notes "${#A[@]}"'),
            ('1289-transform-is-one-word', 'X=hi; gh release create v2 --notes "${X@Q}"'),
            ('1289-element-expr-is-one-word', 'A[0]=x; gh release create v2 --notes "${A[0]:-y}"'),
            ('1289-prefix-joined-is-one-word', 'gh release create v2 --notes "${!HESTIA*}"'),
        ]
        # Codex's quote runner (docs/reviews/scope-1232-quote-regressions.py, notice 20554,
        # 33bddc1c) and the marker / IFS rows that generalise it (2026-10-12).
        deny += [
            ('codex-quote-custom-ifs-splits-literal', 'IFS=:; S=/tmp:/etc; cat $S/hostname'),
            ('codex-quote-raw-quote-marker', 'S="/tmp/x /etc"; cat \x04$S/hostname'),
            ('codex-quote-single-quoted-marker', 'S="/tmp/x /etc"; cat \'\x04\'$S/hostname'),
            ('codex-quote-whitespace-unquoted-control', 'S="/tmp/x /etc"; cat $S/hostname'),
            ('codex-quote-mixed-quoted-unquoted-control', 'S="/tmp/x /etc"; cat "$S"$S/hostname'),
            ('codex-quote-newline-unquoted-control', 'S="/tmp/x\n/etc"; cat $S/hostname'),
            ('quote-marker-byte-00', 'S=/tmp/x; cat \x00$S/hostname'),
            ('quote-marker-byte-01', 'S=/tmp/x; cat \x01$S/hostname'),
            ('quote-marker-byte-02', 'S=/tmp/x; cat \x02$S/hostname'),
            ('quote-marker-byte-03', 'S=/tmp/x; cat \x03$S/hostname'),
            ('quote-marker-byte-04', 'S=/tmp/x; cat \x04$S/hostname'),
            ('quote-marker-byte-05', 'S=/tmp/x; cat \x05$S/hostname'),
            ('quote-marker-byte-in-single-quotes', "S=/tmp/x; cat '\x00'$S/hostname"),
            ('quote-ifs-prefix-assignment', 'S=/tmp:/etc; IFS=: cat $S/hostname'),
            ('quote-ifs-append', 'IFS+=:; S=/tmp:/etc; cat $S/hostname'),
            ('quote-ifs-after-binding', 'S=/tmp:/etc; IFS=:; cat $S/hostname'),
        ]
        # Codex's IFS runner (docs/reviews/scope-1232-ifs-regressions.py, notice 20972, f9e94b40)
        # and every other spelling that names IFS (2026-10-12).
        deny += [
            ('codex-ifs-loop-binding', 'S=/tmp:/etc; for IFS in :; do cat $S/hostname; done'),
            ('codex-ifs-ordinary-ifs-assignment-control', 'IFS=:; S=/tmp:/etc; cat $S/hostname'),
            ('quote-ifs-for-positional', 'S=/tmp:/etc; for IFS; do cat $S/hostname; done'),
            ('quote-ifs-select', 'S=/tmp:/etc; select IFS in :; do cat $S/hostname; break; done'),
            ('quote-ifs-exec-fd-name', 'S=/tmp1/etc; exec {IFS}>/dev/null; cat $S/hostname'),
            ('quote-ifs-coproc', 'S=/tmp1/etc; coproc IFS { :; }; cat $S/hostname'),
            ('quote-ifs-wait-p', 'S=/tmp1/etc; sleep 0 & wait -n -p IFS; cat $S/hostname'),
            ('quote-ifs-case-branch', 'S=/tmp:/etc; case : in *) IFS=: ;; esac; cat $S/hostname'),
            ('quote-ifs-continuation-assign', 'S=/tmp:/etc; I\\\nFS=:; cat $S/hostname'),
            ('quote-ifs-continuation-for', 'S=/tmp:/etc; for I\\\nFS in :; do cat $S/hostname; done'),
            ('quote-ifs-continuation-fd-name', 'S=/tmp1/etc; exec {I\\\nFS}>/dev/null; cat $S/hostname'),
            ('quote-ifs-array-element', 'IFS[0]=:; S=/tmp:/etc; cat $S/hostname'),
        ]
        allow += [
            ('codex-ifs-loop-quoted-control', 'S=/tmp:/etc; for IFS in :; do cat "$S/hostname"; done'),
            ('codex-ifs-array-quoted-control', 'IFS[0]=:; S=/tmp:/etc; cat "$S/hostname"'),
            ('codex-ifs-default-ifs-control', 'S=/tmp:/etc; cat $S/hostname'),
        ]
        allow += [
            ('codex-quote-custom-ifs-quoted-control', 'IFS=:; S=/tmp:/etc; cat "$S/hostname"'),
            ('codex-quote-whitespace-quoted-control', 'S="/tmp/x /etc"; cat "$S/hostname"'),
            ('codex-quote-simple-literal-control', 'S=/tmp/x; cat $S/hostname'),
        ]
        # Codex's two #1232 regression runners (docs/reviews/scope-1232-shell-regressions.py and
        # scope-1232-literal-regressions.py, notice 20536, bc1ea92b) as INVARIANTS: every
        # refusal case is refused (a path or a scope request), every positive control allowed.
        deny += [
            ('codex-shell-direct', 'cat /etc/hestia-scope-review-nonexistent'),
            ('codex-shell-standalone-c', "bash -c 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-long-option-c', "bash --noprofile -c 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-combined-lc', "bash -lc 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-combined-ec', "sh -ec 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-exec-combined', "exec bash -lc 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-sudo-combined', "sudo bash -lc 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-builtin-eval', "builtin eval 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-command-eval', "command eval 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-ansi-c-quote', "cat $'/etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-shell-here-string', "bash <<< 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-shell-pipe', "printf 'cat /etc/hestia-scope-review-nonexistent' | bash"),
            ('codex-shell-shell-descriptor', "bash /dev/fd/3 3<<< 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-lit-substitution-use-before-assignment', 'echo "$(cat $S/hostname)"; S=/tmp/review-probe'),
            ('codex-lit-literal-field-splitting', 'S="/tmp/review-probe /etc"; cat $S/hostname'),
            ('codex-lit-attached-printf-variable', 'S=/tmp/review-probe; printf -vS %s /etc; cat $S/hostname'),
            ('codex-lit-attached-read-array', 'S=/tmp/review-probe; read -aS <<< /etc; cat $S/hostname'),
            ('codex-lit-arithmetic-rebinding', 'S=/tmp; : $((S=0)); cat /$S/etc/hostname'),
            ('codex-lit-combined-shell-code', "S=/tmp/review-probe; sh -ec 'cat /etc/hostname'; cat $S/x"),
            ('codex-lit-shell-options-disqualify', 'S=/tmp/review-probe; bash --noprofile -c true; cat $S/x'),
            ('codex-lit-combined-shell-options-disqualify', 'S=/tmp/review-probe; bash -lc true; cat $S/x'),
            ('codex-lit-prefix-assignment', 'S=/tmp/review-probe cat $S/x'),
            ('codex-lit-pipeline-left', 'S=/tmp/review-probe | true; cat $S/x'),
            ('codex-lit-pipeline-right', 'true | S=/tmp/review-probe; cat $S/x'),
            ('codex-lit-subshell-binding', '(S=/tmp/review-probe); cat $S/x'),
            ('codex-lit-eval-rebinding', 'S=/tmp/review-probe; eval S=/tmp/other; cat $S/x'),
            ('codex-lit-plain-shell-disqualify', 'S=/tmp/review-probe; sh -c true; cat $S/x'),
            ('codex-lit-nameref-target', 'S=/tmp/review-probe; declare -n R=S; R=/tmp/other; cat $S/x'),
            ('codex-lit-array-element', 'S=/tmp/review-probe; S[0]=/tmp/other; cat $S/x'),
            ('codex-lit-array-compound', 'S=(/tmp/review-probe); cat $S/x'),
            ('codex-lit-plain-use-before', 'cat $S/x; S=/tmp/review-probe'),
            ('codex-lit-spaced-printf-variable', 'S=/tmp/review-probe; printf -v S %s /etc; cat $S/hostname'),
            ('codex-lit-spaced-read-array', 'S=/tmp/review-probe; read -a S <<< /etc; cat $S/hostname'),
            ('codex-lit-direct-forbidden', 'S=/etc; cat $S/hostname'),
            # The literal-list loop rule's exclusions: each must still refuse.
            ('litfor-outside-item', f"for r in granted {o}; do ls $r; done"),
            ('litfor-outside-in-body', f"for r in a b; do cat {o}/secret.txt; done"),
            ('litfor-then-outside', f"for f in a.txt; do cat $f; done; cat {o}/secret.txt"),
            ('litfor-and-then-outside', f"for f in a.txt; do cat $f; done && cat {o}/secret.txt"),
            ('litfor-item-builds-outside', f"for r in secret.txt; do cat {o}/$r; done"),
            ('litfor-nested-outside', f"for r in a; do for s in {o}; do ls $s; done; done"),
            ('litfor-ungranted-repo-item', f"for r in granted notgranted; do ls {ws}/$r; done"),
        ]
        allow += [
            ('codex-shell-allowed-temp-path', 'cat /tmp/hestia-scope-review-nonexistent'),
            ('codex-shell-inert-here-string', "cat <<< 'cat /etc/hestia-scope-review-nonexistent'"),
            ('codex-shell-inert-pipe', "printf 'cat /etc/hestia-scope-review-nonexistent' | cat"),
            ('codex-lit-simple-allow', 'S=/tmp/review-probe; cat $S/x'),
            ('codex-lit-and-allow', 'S=/tmp/review-probe && cat "${S}/x"'),
            ('codex-lit-newline-allow', 'S=/tmp/review-probe\ncat $S/x'),
            ('codex-lit-later-substitution-allow', 'S=/tmp/review-probe; echo "$(cat $S/x)"'),
            ('codex-lit-quoted-whitespace-allow', 'S="/tmp/review-probe /etc"; cat "$S/hostname"'),
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
            ("echo-literal-root", "echo /"),
            ("cut-delim-separate", "cut -d / -f1 a.txt"),
            ("awk-fs-separate", "awk -F / '{print $1}' a.txt"),
            ("quoted-heredoc-subst-is-data", f"cat <<'EOF'\n$(cat {o}/secret.txt)\nEOF"),
            ("dquoted-heredoc-subst-is-data", f"cat <<\"EOF\"\n$(cat {o}/secret.txt)\nEOF"),
            ("backslash-heredoc-subst-is-data", f"cat <<\\EOF\n$(cat {o}/secret.txt)\nEOF"),
            ("budget-repeats-count-once", "cat " + " ".join(["/tmp/review-probe"] * 200)),
            ("tr-quoted-slash", "echo a/b | tr '/' '_'"),
            ("cut-delim", "echo a/b | cut -d/ -f2"),
            ("awk-fs", "awk -F/ '{print $1}' a.txt"),
            ("ifs-slash", "IFS=/ read -r x y <<< a/b"),
            ("c-comment-in-python", "python3 -c 'x = 1  # /* not a glob */'"),
            ("python-heredoc-code-noise",
             "python3 - <<'EOF'\nimport re\nt = re.search(r'<table.*?</table>', h)\n"
             "parts = p.split('/')\nif s.startswith('//'): pass\nx = 'a' + \"/\" + 'b'\nEOF"),
            ("here-string-literal-is-data", f"cat <<< {o}/secret.txt"),
            # an expansion whose value is never judged as a path stays allowed (its body is
            # still judged as a command)
            ("value-subst-assigned", "n=$(grep -c x a.txt); echo $n"),
            ("exit-status", "echo done-$?"),
            ("count-pipeline", "n=$(cat a.txt | wc -l); echo $n"),
            ("special-param-in-temp-path", "cat /tmp/review-probe-$$"),
            ("arith-in-temp-path", "cat /tmp/review-probe-$((1+2))"),
            ("subst-body-in-echo-is-judged-not-modelled", "echo \"$(cat a.txt)\""),
            ("for-loop-var-in-echo", "for f in a b; do echo $f; done"),
            ("brace-in-quotes-is-literal", "echo '{a,b}'"),
            ("cd-temp-then-relative-inside", f"cd {fx.tmp} && ls sub/x"),
            ("eval-of-inscope", "eval \"cat a.txt\""),
            ("sh-c-in-find-exec-inscope", "find . -exec sh -c 'cat a.txt' \\;"),
            # dp, 2026-10-11: a variable assigned exactly ONE literal earlier in the same command,
            # at top level, never otherwise bound, resolves to that literal (then judged like any
            # literal path). Formerly `was-assigned-var-under-temp`, a request.
            ("lit-assigned-var-under-temp", "D=/tmp/review-probe; cat $D/x"),
            ("lit-and-then", "S=/tmp/review-probe && cat \"${S}/x\""),
            ("lit-newline", "S=/tmp/review-probe\ncat $S/x"),
            ("lit-relative-in-repo", "S=a.txt; cat $S"),
            ("lit-used-inside-a-later-substitution", "S=/tmp/review-probe; echo \"$(cat $S/x)\""),
            # THE LITERAL-LIST LOOP RULE (proposal, cbp-claude 2026-10-14; #1205 L-b): a whole
            # command that is one `for V in <literals>; do BODY; done` is judged as `V=item; BODY`
            # per item, and allowed only if every iteration is. Formerly `was-for-literal-list`,
            # a request.
            ("litfor-literal-list", "for f in a.txt b.txt; do cat $f; done"),
            ("litfor-quoted-use", "for f in a.txt b.txt; do wc -l \"$f\"; done"),
            ("litfor-newline-form", "for f in a.txt b.txt\ndo\n  cat \"$f\"\ndone"),
            ("litfor-temp-items", "for n in 1 2 3; do cat /tmp/review-probe-$n; done"),
            # Formerly request `lit-for-loop` (dp's 2026-10-11 ruling listed `for` among the
            # binders that stay unenumerated; this proposal admits only a LITERAL list).
            ("litfor-was-lit-for-loop", "for S in /tmp/review-probe; do cat $S/x; done"),
            # Formerly request `1289-split-loop-var-in-sed-program` (Codex HOLD 21675: an unquoted
            # value can split into extra arguments). A literal item has no whitespace and no glob
            # character, so it is one field; the IFS-touched case stays refused by `_literal_names`.
            ("litfor-was-1289-split-sed-program", "for r in 1,2 3,4; do sed -n ${r}p a.txt; done"),
            ("commit-message-heredoc-apostrophe",
             "git commit -m \"$(cat <<'EOF'\nit's fine (really\nEOF\n)\""),
            ("comment-is-not-run", f"ls  # {o}/secret.txt"),
            ("arithmetic-shift", "echo $(( 1 << 2 ))"),
            ("grep-pattern-path-shaped-only", "grep -rn '/etc/' a.txt"),
            ("sed-script-path-shaped", "sed 's|/usr/|/opt/|' a.txt"),
            ("find-name-pattern", "find . -name '*/x/*'"),
            ("git-message-path", f"git commit -m '{o}/secret.txt was refused'"),
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
            # An over-budget command is refused as INCOMPLETE (no single path to name).
            check(f"deny-names-a-path:{name}",
                  bool(resolved) or str(tok).startswith("<incomplete"),
                  f"{cmd[:120]!r} -> {(ok, tok, resolved)}")
        for name, cmd in allow:
            ok, tok, resolved = fx.reach(cmd)
            check(f"allow:{name}", ok is True, f"{cmd!r} -> {(ok, tok, resolved)}")
        UNENUM = getattr(G, "UNENUMERATED_TARGET", "hestia:unpriceable:unenumerated")
        for name, cmd in request:
            ok, tok, resolved = fx.reach(cmd)
            check(f"request:{name}", ok is False and resolved == UNENUM,
                  f"{cmd!r} -> {(ok, tok, resolved)}")
            # Lifted by a one-time approval of the act (the sentinel in this act's trial scope),
            # after which only a concrete path the act also names can still refuse it.
            lifted = fx.reach(cmd, scopes=("granted", "path:" + UNENUM))
            check(f"request-lifted-by-once:{name}", lifted[0] is True or lifted[2] not in (None, UNENUM),
                  f"{cmd!r} lifted -> {lifted}")

        # #1296 (live case scope-55faf36cae2d, 2026-10-13): a variable the single-literal rule
        # resolves is judged by its VALUE's shape, as its literal spelling would be. Run from a
        # cwd OUTSIDE the workspace, where judging it as a relative path is a false deny.
        # The issue's repro needs the fleet's grant shape and an EXISTING cwd outside it.
        out_cwd = f"{o}/sub"
        ws_tree = (f"path:{ws}/**",)
        for name, cmd in (
            ("1296-header-value", 'S=aa0fd2f4; curl -s -X POST http://127.0.0.1:8010/mcp -H "mcp-session-id: $S"'),
            ("1296-header-braced-suffix", 'S=abc; curl -s http://h/mcp -H "id: ${S}x"'),
            ("1296-bare-token", "S=abc; echo x | grep -c $S"),
        ):
            r = fx.reach(cmd, scopes=ws_tree, cwd=out_cwd)
            check(f"allow-outside-cwd:{name}", r[0] is True, f"{cmd!r} -> {r}")
        # The literal-list loop under the fleet's real grant shape (`path:<ws>/**`; #1205 L-b).
        # Under a repo-NAME grant, pass 1 reads `<ws>/$r` lexically, as it does for the
        # single-literal rule; that stricter residual is unchanged here.
        ws_tree = (f"path:{ws}/**",)
        for name, cmd in (
            ("litfor-abs-under-path-grant", f"for r in granted notgranted; do ls {ws}/$r; done"),
            ("litfor-git-C-under-path-grant", f"for r in granted; do git -C {ws}/$r status --short; done"),
        ):
            r = fx.reach(cmd, scopes=ws_tree)
            check(f"allow-path-grant:{name}", r[0] is True, f"{cmd!r} -> {r}")
        r = fx.reach(f"for r in granted {o}; do ls $r; done", scopes=ws_tree)
        check("deny-path-grant:litfor-outside-item", r[0] is False, r)
        for name, cmd in (
            ("1296-control-literal-path-value", f"S={o}/secret.txt; cat $S"),
            ("1296-control-slash-built", "S=etc; cat /$S/hostname"),
            ("1296-control-relative-escape", "S=../secret.txt; cat $S"),
            ("1296-control-relative-dotted", "S=./deep.txt; cat $S"),
        ):
            r = fx.reach(cmd, scopes=ws_tree, cwd=out_cwd)
            check(f"deny-outside-cwd:{name}", r[0] is False, f"{cmd!r} -> {r}")
        # Codex HOLD 23938 (P1 a): a `done` that ends a FILENAME after an already-closed loop is
        # not the loop's end. Stripping it judged `<o>/granted-` (granted) for `<o>/granted-done`.
        gd = pathlib.Path(o) / "granted-done"
        gd.write_text("ungranted\n")
        (pathlib.Path(o) / "granted-").write_text("granted\n")
        r = fx.reach(f"for f in a; do :; done; cat {gd}", scopes=("granted", f"path:{o}/granted-"))
        check("deny-1312-done-suffix-is-a-filename", r[0] is False and r[2] == str(gd), r)
        # (P1 b): `cd` persists across iterations; judged one iteration at a time, the third pass
        # of `cd sub` through a `sub/sub -> <o>` link was never examined.
        cdl = pathlib.Path(ws) / "cdloop"
        (cdl / "sub").mkdir(parents=True)
        (cdl / "sub" / "sub").symlink_to(o, target_is_directory=True)
        r = fx.reach("for f in secret.txt secret.txt secret.txt; do cat $f; cd sub; done",
                     scopes=ws_tree, cwd=str(cdl))
        check("refuse-1312-cd-persists-across-iterations", r[0] is False, r)
        # Codex HOLD 23996: bash forms the command word AFTER quote removal and expansion, so a
        # raw-text `cd` match misses `c''d`, `c\\d`, a line continuation, `pu''shd`, an item that
        # is `cd`, `c$f`, `$(echo c)d`, `$'\\x63d'` and a glob that could match `cd`. Each must be
        # refused AND must not take the loop rule (a refusal for another reason would hide it).
        lfi = getattr(G, "_literal_for_iterations", lambda _c: None)
        l3 = "for f in secret.txt secret.txt secret.txt; do cat $f; "
        for name, cmd in (
            ("empty-single", l3 + "c''d sub; done"), ("empty-double", l3 + 'c""d sub; done'),
            ("inner-double", l3 + 'c"d" sub; done'), ("backslash", l3 + "c\\d sub; done"),
            ("continuation", l3 + "c\\\nd sub; done"), ("pushd-split", l3 + "pu''shd sub; done"),
            ("ansi-c-hex", l3 + "$'\\x63d' sub; done"), ("subst-joined", l3 + "$(echo c)d sub; done"),
            ("glob-q", l3 + "c? sub; done"), ("glob-class", l3 + "c[d] sub; done"),
            ("glob-star", l3 + "c* sub; done"), ("dot-escaped", l3 + "\\. sub/x; done"),
            ("item-is-cd", "for f in cd cd cd; do cat secret.txt; $f sub; done"),
            ("item-braced-cd", "for f in cd cd cd; do cat secret.txt; ${f} sub; done"),
            ("item-completes-cd", "for f in d d d; do cat secret.txt; c$f sub; done"),
            ("item-sliced", "for f in cdx cdx cdx; do cat secret.txt; ${f:0:2} sub; done"),
            ("item-is-dot", "for f in . . .; do $f sub/x; done"),
            ("other-var-head", "for f in a a a; do cat secret.txt; $Z sub; done"),
        ):
            r = fx.reach(cmd, scopes=ws_tree, cwd=str(cdl))
            check(f"refuse-1312-stateful-spelling:{name}", r[0] is False and lfi(cmd) is None,
                  f"{cmd!r} -> {r}, rule={lfi(cmd) is not None}")
        # ...and quoting or globbing an ARGUMENT keeps the rule.
        for name, cmd in (
            ("quoted-arg", "for f in a.txt b.txt; do grep -n 'foo bar' $f; done"),
            ("quoted-var", 'for f in a.txt b.txt; do wc -l "$f"; done'),
            ("glob-arg", "for f in a.txt b.txt; do ls *.txt; cat ${f}; done"),
        ):
            check(f"allow-1312-quoted-or-globbed-argument:{name}",
                  fx.reach(cmd, scopes=ws_tree, cwd=str(cdl))[0] is True, cmd)
        # Codex review 24029: fnmatch has no POSIX classes or `[^x]`, so `c[[:alpha:]]` beside a
        # file named `cd` runs `cd` while fnmatch says it cannot (an end-to-end false allow on
        # 28148979); and `.` (source) is a command after `!`, `if`, `time` or a redirection, not
        # only after a separator (refused there by the ordinary judge, but not by the rule).
        (cdl / "cd").write_text("")
        (cdl / "move").write_text("cd sub\n")
        for name, cmd in (
            ("posix-class", l3 + "c[[:alpha:]] sub; done"), ("posix-head", l3 + "[[:lower:]]d sub; done"),
            ("posix-alnum", l3 + "c[[:alnum:]] sub; done"), ("caret-negation", l3 + "c[^x] sub; done"),
            ("posix-pushd", l3 + "pu[[:alpha:]]hd sub; done"),
            ("extglob", l3 + "@(c?) sub; done"),
            ("dot-after-bang", l3 + "! . ./move; done"), ("dot-after-if", l3 + "if . ./move; then :; fi; done"),
            ("dot-after-time", l3 + "time . ./move; done"), ("dot-after-redirect", l3 + ">/dev/null . ./move; done"),
            ("dot-after-then", l3 + "if true; then . ./move; fi; done"),
            ("dot-after-else", l3 + "if false; then :; else . ./move; fi; done"),
        ):
            check(f"refuse-1312-stateful-spelling:{name}", lfi(cmd) is None
                  and fx.reach(cmd, scopes=ws_tree, cwd=str(cdl))[0] is False,
                  f"{cmd!r}, rule={lfi(cmd) is not None}")
        # ...and the test words `[`/`[[` keep the rule. (A `.` argument never had it: the
        # single-literal rule does not resolve V in a statement holding a bare `.` word.)
        for name, cmd in (
            ("test-bracket", "for f in a.txt b.txt; do [ -f $f ] && cat $f; done"),
            ("test-double-bracket", "for f in a.txt b.txt; do [[ -f $f ]] && cat $f; done"),
        ):
            r = fx.reach(cmd, scopes=ws_tree, cwd=str(cdl))
            check(f"allow-1312-test-word:{name}", lfi(cmd) is not None and r[0] is True,
                  f"{cmd!r} -> {r}")

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

        # HOME, three states (Codex notice 17009): a set-but-EMPTY HOME expands `~/x` to `/x`
        # as the shell does (no passwd fallback); an UNSET HOME falls back to the account's
        # passwd entry; a populated HOME is used as given.
        os.environ["HOME"] = ""
        r = fx.reach("cat ~/etc/hostname")
        check("home-empty-expands-to-root-relative", r[0] is False and r[2] == "/etc/hostname", r)
        os.environ.pop("HOME", None)
        import pwd
        pw_home = pwd.getpwuid(os.getuid()).pw_dir
        r = fx.reach("cat ~/.bashrc")
        check("home-unset-falls-back-to-passwd", r[0] is False and (r[2] or "").startswith(pw_home), r)
        os.environ["HOME"] = fx.base
        r = fx.reach("cat ~/notes.txt")
        check("home-populated-is-used", r[0] is False and r[2] == f"{fx.base}/notes.txt", r)

        # A WORKSPACE SPELLED WITH `..` (found by the staged contract run, 2026-10-10): pass 1
        # normalised the candidate but not the workspace, so an inside path looked like a
        # traversal OUT and was judged by the outside rule; under a temp-root workspace that
        # admitted the workspace's own ungranted repo. Main refused it; so must this.
        dotted = f"{fx.ws}/granted/.."
        tws = fx.tmp + "/tws"
        os.makedirs(tws + "/granted", exist_ok=True)
        os.makedirs(tws + "/notgranted", exist_ok=True)
        for w, label in ((dotted, "dotted"), (tws + "/granted/..", "temp-dotted")):
            r = G.command_scope_reach(f"cat {w}/notgranted/b.txt", ["granted"], w, fx.cwd,
                                      home_markers=(fx.marker,))
            check(f"workspace-spelled-with-dotdot-{label}", r[0] is False, r)
        r = G.command_scope_reach(f"cat {tws}/notgranted/b.txt", ["granted"], tws + "/granted/..",
                                  tws + "/granted", home_markers=(fx.marker,))
        check("workspace-dotted-normalised-path-refused", r[0] is False, r)

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
        # Codex review 17029 measured through core.evaluate, so every deny row is also checked
        # there — the verdict a seat acts on, not only the helper.
        for name, cmd in deny:
            ve = G.evaluate(G.NormalizedEvent(tool="Bash", command=cmd, cwd=fx.cwd), prof, ws, policy=pol)
            check(f"evaluate-denies:{name}", ve.blocks and ve.rule in (
                      "mrh.command", "mrh.command.unenumerated", "egress.secret"),
                  f"{cmd[:100]!r} -> {ve.decision}/{ve.rule}")
        # hestia#1313 (dp, 2026-10-14): an unenumerable reach is refused under its own rule, which
        # does not escalate (no scope request is opened). The target still names the sentinel.
        unenum_rule = "mrh.command.unenumerated" if "mrh.command.unenumerated" in G.REMEDIES else "mrh.command"
        for name, cmd in request:
            ve = G.evaluate(G.NormalizedEvent(tool="Bash", command=cmd, cwd=fx.cwd), prof, ws, policy=pol)
            check(f"evaluate-requests:{name}",
                  ve.blocks and ve.rule == unenum_rule and getattr(ve, "target", "") == UNENUM,
                  f"{cmd[:100]!r} -> {ve.decision}/{ve.rule}/{getattr(ve, 'target', None)}")
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
    return {"deny": deny, "allow": allow, "request": request}


def against_main(fx: Fixture) -> int:
    """How many DENY rows the given core lets through — on main, the size of the gap."""
    rows = run(fx)
    leaked = [n for n, c in rows["deny"] if fx.reach(c)[0] is True]
    print(f"deny rows the core ALLOWS: {len(leaked)}/{len(rows['deny'])}: {', '.join(leaked)}")
    return 0


def classify(fx: Fixture) -> int:
    """Each row's verdict under the given core: ALLOW, REFUSE (a path), REQUEST (the sentinel)."""
    rows = run(fx)
    home = fx.base
    unenum = getattr(G, "UNENUMERATED_TARGET", "hestia:unpriceable:unenumerated")
    saved = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        for group in ("deny", "request", "allow"):
            for name, cmd in rows[group]:
                ok, tok, resolved = fx.reach(cmd)
                v = "ALLOW" if ok else ("REQUEST" if resolved == unenum else
                                        "INCOMPLETE" if not resolved else "REFUSE")
                print(f"{group:8} {v:10} {name}")
    finally:
        if saved is not None:
            os.environ["HOME"] = saved
    return 0


def main() -> int:
    fx = Fixture()
    if "--against-main" in sys.argv:
        return against_main(fx)
    if "--classify" in sys.argv:
        return classify(fx)
    run(fx)
    print(f"shell-scope battery: {PASSES} passed, {len(FAILS)} failed (core: {CORE_PATH})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
