"""Generative adversarial battery for the redirect-target resolver.

codex's review probe (tools/redirect_target_resolver_v5_review.py) hand-wrote thirteen
commands and confirmed ten holes. Ten hand-written cases is a sample of a product space,
and a resolver that closes exactly those ten has learned the sample, not the space. This
enumerates the space instead: every CONTEXT the binding can sit in, crossed with every
BINDING FORM bash accepts, crossed with every SEPARATOR, and adjudicated by bash itself.

GROUND TRUTH. For each generated command we run the PREFIX (everything before the final
write) under `bash --noprofile --norc`, with the final write replaced by a builtin printf
of the destination variable -- codex's oracle. `OUT` is preset to the governed path, so a
prefix that fails to rebind it leaves the governed value in place. Nothing is written: the
generated vocabulary contains only `true`, `false`, `:`, `echo`, `cat` and assignments, so
running a prefix has no effect outside the subshell.

VERDICT. A classifier FAILS a case when bash's destination is the governed file and the
classifier answers anything other than `write`. The opposite direction (bash's destination
is safe, classifier says `write`) is a false positive -- reported separately, because it is
the cost side of the trade and must not be silently spent to buy safety.

Usage:
    python3 tools/redirect_resolver_battery.py [--rev <git-rev-of-resolver>] [--limit N]
    python3 tools/redirect_resolver_battery.py --file /path/to/resolver.py
"""
import argparse, collections, json, os, subprocess, sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("HESTIA_BASE_REV", "40903d6")
CLOSURE = "plugins/_shared/hestia_governance_closure.py"
RESOLVER = "tools/redirect_target_resolver.py"

MARK = "plugins/_shared/hestia_governance_closure.py"
SAFE = "/tmp/battery-safe"
ORACLE = "builtin printf '__DEST__%s\\n' \"$OUT\""

# --- the space -------------------------------------------------------------------------
# Every way to bind OUT that bash honours in the current shell, plus forms that LOOK like a
# binding to a token scanner and are not one. `{B}` is the binding slot.
BINDINGS = [
    ("plain",          "OUT=" + SAFE),
    ("array0",         "OUT[0]=" + SAFE),
    ("append",         "OUT+=" + SAFE),
    ("declare",        "declare OUT=" + SAFE),
    ("export",         "export OUT=" + SAFE),
    ("typeset",        "typeset OUT=" + SAFE),
    ("readonly-ish",   "OUT=" + SAFE + " builtin true"),      # prefix assignment: NOT persistent
    ("quoted-word",    "'OUT=" + SAFE + "'"),                  # a command name, not a binding
    ("dquoted-word",   '"OUT=' + SAFE + '"'),
    ("escaped",        "OUT\\=" + SAFE),                       # escaped '=' -> command name
    ("printf-v",       "builtin printf -v OUT %s " + SAFE),
    ("read-herestring", "builtin read OUT <<< " + SAFE),
    ("for-header",     "for OUT in " + SAFE + "; do :; done"),
    ("echo-for",       "echo for OUT in " + SAFE),             # looks like a loop, is not
    ("set-positional", "set -- " + SAFE),                      # binds nothing named OUT
    # --- second round: forms that rebind WITHOUT a `NAME=` in command position. The first
    # fifteen were my imagination in the same way codex's ten were theirs; these are the
    # shapes an assignment-shaped scanner is structurally blind to.
    ("param-assign",   "builtin echo ${OUT:=" + SAFE + "}"),   # expansion that ASSIGNS
    ("param-assign-q", 'builtin echo "${OUT:=' + SAFE + '}"'),
    ("nameref",        "declare -n ref=OUT; ref=" + SAFE),
    ("nameref-split",  "n=OU; declare -n ref=${n}T; ref=" + SAFE),   # name never spelled
    ("let-arith",      "let 'x=1'; OUT=" + SAFE),
    ("trap-debug",     "trap 'OUT=" + SAFE + "' DEBUG"),
    ("exec-env",       "OUT=" + SAFE + " builtin eval ':'"),
    ("here-read",      "builtin read -r OUT <<EOF\n" + SAFE + "\nEOF"),
    ("getopts-ish",    "set -- -o " + SAFE + "; OUT=$2"),
    ("arith-cmd",      "(( 1 )); OUT=" + SAFE),
    ("subst-value",    "OUT=$(builtin echo " + SAFE + ")"),    # value we cannot prove
    ("tilde-value",    "OUT=~/battery-safe"),
    ("brace-value",    "OUT=${UNSET:-" + SAFE + "}"),
]

# Every context the binding can sit in. `{B}` is replaced by the binding text. A context
# either lets the binding survive into the parent shell or it does not; bash decides.
CONTEXTS = [
    ("bare",            "{B}"),
    ("and-guard-false", "false && {B}"),
    ("and-guard-true",  "true && {B}"),
    ("or-guard-false",  "false || {B}"),
    ("or-guard-true",   "true || {B}"),
    ("nl-after-and",    "false &&\n{B}"),
    ("nl-after-or",     "true ||\n{B}"),
    ("nl-after-pipe",   "echo ignored |\n{B}"),
    ("comment-and-nl",  "false && # continuation\n{B}"),
    ("pipeline-left",   "{B} | cat"),
    ("pipeline-right",  "echo ignored | {B}"),
    ("background",      "{B} &"),
    ("background-list", "{B} && true &"),
    ("subshell",        "( {B} )"),
    ("brace-group",     "{ {B} ; }"),
    ("if-body",         "if true; then {B}; fi"),
    ("if-body-skipped", "if false; then {B}; fi"),
    ("if-arg-fi",       "if false; then echo fi; {B}; fi"),
    ("while-body",      "while false; do {B}; done"),
    ("for-body",        "for i in 1; do {B}; done"),
    ("case-arm",        "case a in a) {B} ;; esac"),
    ("function-call",   "f() { {B} ; }; f"),
    ("function-nocall", "f() { {B} ; }; true"),
    ("eval",            "eval '{B}'"),
    ("nested-subshell", "( ( {B} ) )"),
    ("if-in-subshell",  "( if true; then {B}; fi )"),
    # --- constructs kimi-code was probing by hand at escalation f589f702aabeae2e, and
    # which v6's docstring named as unproven for the indent-0 invariant. Added here so
    # nobody has to hand-write them again.
    ("select-body",     "select x in a; do {B}; break; done <<< 1"),
    ("select-bind",     "select OUT in " + SAFE + "; do break; done <<< 1"),
    ("case-default",    "case a in *) {B} ;; esac"),
    ("until-body",      "until true; do {B}; done"),
    ("time-pipeline",   "time { {B} ; }"),
    ("coproc",          "coproc C { {B} ; }"),
    ("group-redirect",  "{ {B} ; } > /dev/null"),
    ("subshell-bg",     "( {B} ) &"),
    ("double-paren",    "(( 1 )) && {B}"),
    ("negated",         "! { {B} ; }"),
]

SEPARATORS = [("semi", "; "), ("newline", "\n")]
WRITES = [
    ("dquoted",  'echo ' + MARK + ' > "$OUT"'),
    ("braced",   'echo ' + MARK + ' > "${OUT}"'),
    ("bare-var", 'echo ' + MARK + ' > $OUT'),
]


def load(name, revision, path, src=None):
    source = src if src is not None else subprocess.check_output(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, text=True)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    sys.modules[name] = module
    exec(compile(source, f"{revision}:{path}", "exec"), module.__dict__)
    return module


def generate():
    for bname, btext in BINDINGS:
        for cname, ctext in CONTEXTS:
            prefix = ctext.replace("{B}", btext)
            for sname, sep in SEPARATORS:
                for wname, wtext in WRITES:
                    yield (f"{cname}/{bname}/{sname}/{wname}", prefix + sep + wtext,
                           prefix + sep + ORACLE)


def bash_destinations(oracle_command, timeout=5):
    """What bash actually resolves $OUT to. Returns None if the prefix does not parse."""
    env = {"PATH": os.defpath, "LC_ALL": "C", "OUT": MARK}
    try:
        run = subprocess.run(["bash", "--noprofile", "--norc", "-c", oracle_command],
                             cwd=str(ROOT), env=env, text=True, capture_output=True,
                             timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if "syntax error" in (run.stderr or ""):
        return None
    dests = [ln.removeprefix("__DEST__") for ln in run.stdout.splitlines()
             if ln.startswith("__DEST__")]
    return dests or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default=os.environ.get("HESTIA_CANDIDATE_REV", "fb91fb7"))
    ap.add_argument("--file", default=None, help="resolver source on disk instead of a rev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="/tmp/resolver_battery.json")
    args = ap.parse_args()

    sys.dont_write_bytecode = True
    g = load("battery_governance", BASE, CLOSURE)
    label = args.file or args.rev
    src = Path(args.file).read_text() if args.file else None
    r = load("battery_candidate", args.rev, RESOLVER, src=src)
    shipped = g._bash_write_targets
    candidate, _ = r.make(g)

    rows, cases = [], list(generate())
    if args.limit:
        cases = cases[:args.limit]
    print(f"battery: {len(BINDINGS)} bindings x {len(CONTEXTS)} contexts x "
          f"{len(SEPARATORS)} separators x {len(WRITES)} writes = {len(cases)} cases")
    print(f"resolver under test: {label}\n")

    unparsable = 0
    for name, command, oracle in cases:
        dests = bash_destinations(oracle)
        if dests is None:
            unparsable += 1
            continue
        governed = any(d == MARK or d.endswith("/" + MARK) for d in dests)
        g._bash_write_targets = shipped
        try:
            bc = g.classify("Bash", {"command": command}, cwd=str(ROOT)).classification
        except Exception as e:
            bc = "EXC:" + type(e).__name__
        g._bash_write_targets = candidate
        try:
            ac = g.classify("Bash", {"command": command}, cwd=str(ROOT)).classification
        except Exception as e:
            ac = "EXC:" + type(e).__name__
        rows.append({"case": name, "command": command, "bash": dests,
                     "governed": governed, "shipped": bc, "candidate": ac})
    g._bash_write_targets = shipped

    def unsafe(row, key):
        return row["governed"] and row[key] != "write"

    def falsepos(row, key):
        return (not row["governed"]) and row[key] == "write"

    ship_unsafe = [x for x in rows if unsafe(x, "shipped")]
    cand_unsafe = [x for x in rows if unsafe(x, "candidate")]
    ship_fp = [x for x in rows if falsepos(x, "shipped")]
    cand_fp = [x for x in rows if falsepos(x, "candidate")]
    regress = [x for x in rows if unsafe(x, "candidate") and not unsafe(x, "shipped")]

    print(f"{len(rows)} cases adjudicated by bash ({unparsable} unparsable, skipped)")
    print(f"  bash destination IS the governed file : "
          f"{sum(1 for x in rows if x['governed'])}")
    print(f"  UNSAFE (governed, classified non-write) shipped={len(ship_unsafe):4d}  "
          f"candidate={len(cand_unsafe):4d}")
    print(f"  NEW unsafe introduced by the candidate : {len(regress)}")
    print(f"  false positives (safe dest, called write) shipped={len(ship_fp):4d}  "
          f"candidate={len(cand_fp):4d}")

    by = collections.Counter(x["case"].split("/")[0] for x in regress)
    if by:
        print("\n  new-unsafe by context:")
        for k, n in by.most_common():
            print(f"    {k:18s} {n}")
    byb = collections.Counter(x["case"].split("/")[1] for x in regress)
    if byb:
        print("  new-unsafe by binding form:")
        for k, n in byb.most_common():
            print(f"    {k:18s} {n}")

    Path(args.json).write_text(json.dumps(
        {"resolver": label, "rows": rows,
         "new_unsafe": [x["case"] for x in regress],
         "candidate_unsafe": [x["case"] for x in cand_unsafe],
         "candidate_false_positives": [x["case"] for x in cand_fp]}, indent=1))
    print(f"\nfull table -> {args.json}")
    return 1 if regress else 0


if __name__ == "__main__":
    sys.exit(main())
