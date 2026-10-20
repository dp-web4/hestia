#!/usr/bin/env python3
"""A write is a write wherever the verb hides its output (#1348).

The closure's Bash write-position model knew redirects and a set of writer verbs (cp, mv,
tee, dd, sed -i, rm, ...). Every other verb's file arguments were READ positions, so a verb
that writes through an OPTION (`sort -o F`, `git diff --output=F`, `find -fprint F`), an
OUTPUT OPERAND (`uniq IN OUT`, `split IN PREFIX`), its own SCRIPT (`sed 'w F'`, awk's
`print > F`), or by REPLACING its input (`gzip F`) wrote a gate file and was witnessed as a
read: no gate.self_access refusal, no escalation. Measured on main ee7f00d8 for the first six.

Every row is a pair: the write form must classify `write`, and the same verb used to READ
the gate file must not. The read arm is what keeps the fix from becoming a false-deny
machine; the write arm is the hole.

Run: python3 tools/closure_output_writes_test.py
"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))
import hestia_governance_closure as g  # noqa: E402

T = "/w/hestia/plugins/_shared/hestia_gate_core.py"   # a governed file
D = "/w/hestia/plugins/_shared"                       # a governed directory
NEUTRAL_CWD = tempfile.mkdtemp(prefix="hgc-out-")

# (name, write form, read form of the same verb). The read form names the gate file only
# as INPUT, with any output going to /tmp.
PAIRS = [
    # output options
    ("sort -o", f"sort -o {T} /tmp/in", f"sort {T}"),
    ("sort -oFILE", f"sort -o{T} /tmp/in", f"sort -o /tmp/out {T}"),
    ("sort --output=", f"sort --output={T} /tmp/in", f"sort --output=/tmp/out {T}"),
    ("sort -ro cluster", f"sort -ro {T} /tmp/in", f"sort -r {T}"),
    ("git diff --output=", f"git diff --output={T}", f"git diff -- {T}"),
    ("git diff --output F", f"git diff --output {T}", f"git log -p {T}"),
    ("git format-patch -o", f"git format-patch -o {D} HEAD~1", "git format-patch -o /tmp/p HEAD~1"),
    ("git archive -o", f"git archive -o {T} HEAD", "git archive -o /tmp/a.tar HEAD"),
    ("find -fprint", f"find /tmp -fprint {T}", f"find {D} -name '*.py'"),
    ("find -fprintf", f"find /tmp -fprintf {T} '%p'", f"find {D} -printf '%p'"),
    ("find -fls", f"find /tmp -fls {T}", f"find {D} -ls"),
    ("find -delete", f"find {D} -name '*.py' -delete", f"find {D} -name '*.py' -print"),
    ("curl -o", f"curl -o {T} https://example.invalid/x", "curl -o /tmp/x https://example.invalid/x"),
    ("curl --output", f"curl --output {T} https://example.invalid/x", "curl -s https://example.invalid/x"),
    ("wget -O", f"wget -O {T} https://example.invalid/x", "wget -O /tmp/x https://example.invalid/x"),
    ("tar -cf", f"tar -cf {T} /tmp/in", f"tar -cf /tmp/a.tar {T}"),
    ("tar czf", f"tar czf {T} /tmp/in", f"tar tzf /tmp/a.tgz {T}"),
    ("csplit -f", f"csplit -f {D}/x /tmp/in 3", f"csplit -f /tmp/x {T} 3"),
    # output operands
    ("uniq IN OUT", f"uniq /tmp/in {T}", f"uniq {T}"),
    ("uniq -c IN OUT", f"uniq -c /tmp/in {T}", f"uniq -c {T} /tmp/out"),
    ("split IN PREFIX", f"split /tmp/in {D}/x", f"split {T} /tmp/x"),
    ("mkdir", f"mkdir {D}/new", f"ls {D}"),
    ("mkfifo", f"mkfifo {D}/fifo", f"stat {D}"),
    # scripts that write
    ("sed w", f"sed -n 'w {T}' /tmp/in", f"sed -n 1p {T}"),
    ("sed s///w", f"sed -n 's/a/b/w {T}' /tmp/in", f"sed -n 's/a/b/p' {T}"),
    ("sed -e w", f"sed -n -e 'w {T}' /tmp/in", f"sed -n -e 1p {T}"),
    ("awk print >", f"awk '{{print > \"{T}\"}}' /tmp/in", f"awk '{{print}}' {T}"),
    ("awk print >>", f"awk '{{print >> \"{T}\"}}' /tmp/in", f"awk 'NR==1' {T}"),
    ("perl -i", f"perl -i -pe 's/a/b/' {T}", f"perl -ne 'print' {T}"),
    ("perl -pi cluster", f"perl -pi -e 's/a/b/' {T}", f"perl -pe 's/a/b/' {T}"),
    # verbs that replace or remove their input
    ("gzip", f"gzip {T}", f"gzip -c {T}"),
    ("gunzip", f"gunzip {T}.gz", f"gunzip -c /tmp/x.gz"),
    ("xz", f"xz {T}", f"xz -l /tmp/x.xz"),
    ("bzip2", f"bzip2 {T}", f"bzip2 -c {T}"),
    ("zstd --rm", f"zstd --rm {T}", f"zstd -c {T}"),
    # Codex REQUEST CHANGES on #1349, round 2: other spellings of the same options
    ("sed -e attached", f"sed -n -e'w {T}' /tmp/in", f"sed -n -e'1p' {T}"),
    ("sed -ne cluster", f"sed -ne 'w {T}' /tmp/in", f"sed -ne 1p {T}"),
    ("sed --expression S", f"sed -n --expression 'w {T}' /tmp/in", f"sed -n --expression 1p {T}"),
    ("sed -f attached", f"sed -f/tmp/script {T}", f"sed -n 2p {T}"),
    ("awk -f attached", f"awk -f/tmp/script {T}", f"awk '{{print $2}}' {T}"),
    ("awk --file", f"awk --file /tmp/script {T}", f"awk -F: '{{print $1}}' {T}"),
    ("gawk -i inplace", f"gawk -i inplace '{{print}}' {T}", f"gawk '{{print}}' {T}"),
    ("tar -v -cf", f"tar -v -cf {T} /tmp/in", f"tar -v -tf /tmp/a.tar"),
    ("tar -c -f", f"tar -c -f {T} /tmp/in", f"tar -c -f /tmp/a.tar {T}"),
    ("tar --create --file", f"tar --create --file {T} /tmp/in", f"tar --create --file /tmp/a.tar {T}"),
    ("tar cvf old-style", f"tar cvf {T} /tmp/in", f"tar cvf /tmp/a.tar {T}"),
    ("split --lines N", f"split --lines 2 /tmp/in {D}/x", f"split --lines 2 {T} /tmp/x"),
    ("split -l N", f"split -l 2 /tmp/in {D}/x", f"split -l 2 {T} /tmp/x"),
    ("gzip -k", f"gzip -k {T}", f"gzip -kc {T}"),
    ("zstd -o", f"zstd -o {T} /tmp/in", f"zstd -c {T}"),
    ("xz --keep", f"xz --keep {T}", f"xz --stdout {T}"),
    # Codex REQUEST CHANGES on #1349, round 3 (28144): more spellings -> option TABLES now
    ("curl -D", f"curl -D {T} https://example.invalid/x", "curl -D /tmp/h https://example.invalid/x"),
    ("curl -c", f"curl -c {T} https://example.invalid/x", "curl -b /tmp/c https://example.invalid/x"),
    ("curl -O (cwd)", f"cd {D} && curl -O https://example.invalid/x", "cd /tmp && curl -O https://example.invalid/x"),
    ("wget -a", f"wget -a {T} -O /tmp/x https://example.invalid/x", "wget -a /tmp/log -O /tmp/x https://example.invalid/x"),
    ("gzip -S attached", f"gzip -S.txt {T}", f"gzip -c -S.txt {T}"),
    ("uniq --group", f"uniq --group=prepend /tmp/in {T}", f"uniq --group=prepend {T}"),
    ("split --numeric-suffixes=", f"split --numeric-suffixes=1 /tmp/in {D}/x", f"split --numeric-suffixes=1 {T} /tmp/x"),
    ("sort --out= abbrev", f"sort --out={T} /tmp/in", f"sort --out=/tmp/o {T}"),
    ("git diff --out= abbrev", f"git diff --out={T}", f"git diff --stat -- {T}"),
    ("sort --compress-program", f"sort --compress-program=sh {T}", f"sort -n {T}"),
    ("unknown option", f"sort --some-future-flag {T}", f"sort -u {T}"),
    ("tar -g snapshot", f"tar -g {T} -cf /tmp/a.tar /tmp/in", f"tar -tf /tmp/a.tar"),
    ("awk -d dump", f"cd {D} && awk -d '{{print}}' /tmp/in", f"awk -v x=1 '{{print x}}' {T}"),
    ("find unknown primary", f"find {D} -name x -somefutureaction", f"find {D} -type f -name '*.py'"),
    # Codex REQUEST CHANGES on #1349, round 4 (6279484423 / dissent 28169): effects of KNOWN options
    ("curl -w %output{}", f"curl -w '%output{{{T}}}changed' file:///tmp/in",
     "curl -w '%{http_code}' -s https://example.invalid/x"),
    ("curl -w %output{>>}", f"curl --write-out '%output{{>>{T}}}x' https://example.invalid/x",
     "curl --write-out '%{size_download}' https://example.invalid/x"),
    ("curl -w @file", f"curl -w @/tmp/fmt -o /tmp/x https://example.invalid/{T}",
     "curl -w '\\n' -o /tmp/x https://example.invalid/x"),
    ("wget -e logfile=", f"wget -e logfile={T} -O /tmp/out http://example.invalid/x",
     "wget -q -O /tmp/out http://example.invalid/x"),
    ("wget --execute", f"wget --execute output_document={T} http://example.invalid/x",
     "wget --spider http://example.invalid/x"),
    ("find -exec rg --pre", f"find {D} -exec rg --pre touch x {{}} +", f"find {D} -exec grep -l x {{}} +"),
    ("xargs rg --pre", f"ls {D} | xargs rg --pre touch x", f"ls {D} | xargs grep -l x"),
    ("find -exec \\; then -fprint", f"find /tmp -exec grep -l x {{}} \\; -fprint {T}",
     f"find {D} -exec grep -l x {{}} \\; -print"),
    ("find -exec \\; then -delete", f"find {D} -exec grep -q x {{}} \\; -delete",
     f"find {D} -exec grep -q x {{}} \\; -print"),
    # Codex: bare optional-argument forms (round 2's originals), not only =VALUE
    ("uniq --group bare", f"uniq --group /tmp/in {T}", f"uniq --group {T}"),
    ("split --numeric-suffixes bare", f"split --numeric-suffixes /tmp/in {D}/x",
     f"split --numeric-suffixes {T} /tmp/x"),
    # Codex dissent 28240 (round 5): a bare output option's cwd default is per option
    ("gawk -d bare + -p file", f"cd {D} && gawk -d -p/tmp/profile 'BEGIN {{print 1}}'",
     f"cd /tmp && gawk -d -p/tmp/profile 'BEGIN {{print 1}}'"),
    ("gawk -p bare + -d file", f"cd {D} && gawk -p -d/tmp/vars 'BEGIN {{print 1}}'",
     f"cd /tmp && gawk -p -d/tmp/vars 'BEGIN {{print 1}}'"),
    ("gawk --profile bare + --dump-variables=", f"cd {D} && gawk --profile --dump-variables=/tmp/v 'BEGIN {{}}'",
     f"gawk --profile=/tmp/p --dump-variables=/tmp/v '{{print}}' {T}"),
    # Codex round 6 (28252): the same optional output option repeated, with and without a file
    ("gawk -p file then -p bare", f"cd {D} && gawk -p/tmp/profile -p 'BEGIN{{print 1}}'",
     f"cd /tmp && gawk -p/tmp/profile -p 'BEGIN{{print 1}}'"),
    ("gawk -p bare then -p file", f"cd {D} && gawk -p -p/tmp/profile 'BEGIN{{print 1}}'",
     f"cd /tmp && gawk -p -p/tmp/profile 'BEGIN{{print 1}}'"),
    ("gawk --profile= then --profile", f"cd {D} && gawk --profile=/tmp/p --profile 'BEGIN{{}}'",
     f"gawk --profile=/tmp/p --profile=/tmp/q '{{print}}' {T}"),
    ("gawk -o file then -o bare", f"cd {D} && gawk -o/tmp/pp -o 'BEGIN{{}}'",
     f"gawk -o/tmp/pp -o/tmp/qq '{{print}}' {T}"),
    # Codex round 7 (28256): an EMPTY --dump-variables= writes the default file in the cwd
    ("gawk --dump-variables= empty", f"cd {D} && gawk --dump-variables= 'BEGIN {{print 1}}'",
     "cd /tmp && gawk --dump-variables= 'BEGIN {print 1}'"),
    # a verb that runs another verb
    ("xargs rm", f"echo {T} | xargs rm", f"grep -l deny {T}"),
    ("find -exec", f"find {D} -name '*.py' -exec rm {{}} +", f"find {D} -name '*.py'"),
]


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def cls(cmd):
    return g.classify("Bash", {"command": cmd}, cwd=NEUTRAL_CWD)


def test_every_hidden_output_is_a_write():
    missed = []
    for name, write, _ in PAIRS:
        v = cls(write)
        if v.classification != "write":
            missed.append(f"{name}: {write!r} -> {v.classification}")
    check("hidden_outputs_are_writes", not missed, "\n  " + "\n  ".join(missed))


def test_the_same_verb_reading_the_gate_is_not_a_write():
    over = []
    for name, _, read in PAIRS:
        v = cls(read)
        if v.classification == "write":
            over.append(f"{name}: {read!r} -> write ({v.marker})")
    check("reads_stay_reads", not over, "\n  " + "\n  ".join(over))


def test_the_known_writers_still_write():
    # Controls: what the model already knew must not regress.
    for cmd in (f"tee {T}", f"cp /tmp/x {T}", f"echo x > {T}", f"sed -i s/a/b/ {T}",
                f"rm {T}", f"mv {T} /tmp/aside"):
        v = cls(cmd)
        check(f"known:{cmd.split()[0]}", v.classification == "write", str(v))


def test_an_early_out_of_grammar_command_does_not_hide_a_later_opaque_writer():
    # Transcript replay, 2026-10-19: `tar -x` (now out of grammar) ahead of a `git apply` of an
    # unreadable patch resolved to the conditional out-of-grammar posture and classified
    # `none`, where main's unconditional opaque-writer refusal had classified `write`.
    cmd = ("git archive HEAD x.py | tar -x -C /tmp/t && "
           "git apply --include=x.py /nonexistent/unreadable.patch")
    v = cls(cmd)
    check("opaque_writer_still_decides", v.classification == "write", str(v))
    # And xargs / find -exec running a verb that only reads stay reads.
    for read in (f"grep -l deny {D}/*.py | xargs grep -n gate",
                 f"find {D} -name '*.py' -exec sha256sum {{}} \\;",
                 f"awk 'NR>5 && c>=3 {{print $1}}' {T}"):
        v = cls(read)
        check(f"passive:{read[:30]}", v.classification != "write", str(v))


ALL = [
    test_an_early_out_of_grammar_command_does_not_hide_a_later_opaque_writer,
    test_every_hidden_output_is_a_write,
    test_the_same_verb_reading_the_gate_is_not_a_write,
    test_the_known_writers_still_write,
]

if __name__ == "__main__":
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests, {len(PAIRS)} write/read pairs")
