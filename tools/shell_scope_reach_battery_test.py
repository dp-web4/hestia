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
            ("was-for-literal-list", "for f in a.txt b.txt; do cat $f; done"),
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
            ("lit-for-loop", "for S in /tmp/review-probe; do cat $S/x; done"),
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
            check(f"evaluate-denies:{name}", ve.blocks and ve.rule in ("mrh.command", "egress.secret"),
                  f"{cmd[:100]!r} -> {ve.decision}/{ve.rule}")
        for name, cmd in request:
            ve = G.evaluate(G.NormalizedEvent(tool="Bash", command=cmd, cwd=fx.cwd), prof, ws, policy=pol)
            check(f"evaluate-requests:{name}",
                  ve.blocks and ve.rule == "mrh.command" and getattr(ve, "target", "") == UNENUM,
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
