#!/usr/bin/env python3
"""A classification of identity fields is enforceable only if something else decides it.

The proposal on `supervisor-role-2026-07-31` is to hash the *core* of
`identity.json` and let the *meta* churn, with the split stated as a rule rather
than a list:

    core is instructive (this is what is allowed).
    meta is informative (this is what happened).

The rule is right and the list would have been wrong -- a list is one more copy
to drift, and it cannot classify a field nobody has invented yet. But a rule
still has to be APPLIED by somebody, and the proposal's own stated requirement
is that the application be TOTAL: every key declared one way or the other, with
unknown keys failing closed as core, because a field that lands outside the hash
by default is the exact drift the hash exists to catch, reintroduced at the
hash's own boundary.

This is that requirement, executable -- plus the three questions the requirement
implies once you try to run it.

THE INVARIANT (four parts, each its own property)

  A  TOTAL        Every key present in any identity artifact this repo ships is
                  declared core or meta. UNACCOUNTED must be 0.

  B  ENFORCED     Every field declared CORE is read by something that decides.
                  "Instructive" is a claim about consequence: if no gate reads
                  the field, it does not constrain anything, and it is prose
                  pretending to be policy. That is not hypothetical -- the
                  thread found `out_of_scope_note` in two members' identities
                  denying a repo that `in_scope` in the same object grants,
                  a contradiction that survived because nothing reads either
                  sentence.

  C  NOT SILENTLY CORE
                  No field declared META is read by something that decides. The
                  proposal notes this about `t3`: it is a cache of a chain
                  derivation, so meta -- but "if anyone ever reads the stored
                  copy to decide rather than re-deriving, it silently becomes
                  core and the classification is wrong." An annotation next to
                  the field cannot notice the new reader. A check can.

  D  UNIFORM PROVENANCE
                  For each CORE field, the members whose writer DERIVES it must
                  be all of them or none of them. A field derived from a live
                  source on one member and frozen at seed on another is not one
                  field with one meaning; it is two fields with one name, and a
                  hash over it compares objects with different producers.

WHY D IS NOT AN AESTHETIC POINT

The divergence that killed the supervisor proposal -- one member missing 24
scope entries -- arrived through no write at all. Its cause is property D
failing: `plugins/codex/hooks/hydrate.sh` recomputes `mrh.in_scope` from the
repo registry at every session end; the corresponding gemini hook copies the
seed once and returns, with a comment saying the rewrite is "kept minimal here
pending a live-run verification."

So the two members' `mrh.in_scope` are different KINDS of object. On one it is
a derivation output, refreshed each session against a source of truth; on the
other it is a literal that has not moved since the seed was written. Both files
are internally consistent, and a hash taken over either one, by its own writer,
at its own write time, matches. The under-derived member is the one that never
writes -- so it never submits a hash either, and an absent record reads as an
agreeing one.

That is why this checks the WRITERS and not just the files. A hash whose
referent is the file as written can only catch mutation of that copy after the
fact. The comparison that catches the case the thread actually measured is
core-versus-derivation, and its precondition is that a derivation exists.

HOW THE READERS AND WRITERS ARE FOUND

Not by grep. A regex for a field name matches the field name in a docstring,
in a JSON fixture, in an unrelated dict, and in the very prose explaining the
check -- the failure mode this repo has already paid for: a gauge that cries
wolf gets muted, and a muted gauge is worse than none.

So field access is resolved by a taint walk over the AST. The identity object is
seeded from `json.load(open(P))` where P names an identity file (string
constants are propagated, including through `sys.argv` for the python embedded
in a hook's shell heredoc -- that is how `hydrate.sh` receives its path). From
there, `.get("k")` / `["k"]` / `.setdefault("k", ...)` extend the path, an
assignment propagates the taint to the target name, a Subscript assignment into
a tainted path is a WRITE, and `.append`/`.update` on one is a write too.

Consequence, stated so it can be argued with: a field read through a name this
walk cannot resolve is invisible here and will be reported as unread. The walk
under-reports; it does not over-report. For property B (core must have a reader)
under-reporting is a false ALARM, which is the safe direction only because the
count is small enough to check by hand -- and it was checked. For property C
(meta must have no reader) under-reporting is a false PASS, so C is the weaker
of the two and says so in its output.

A DECIDER is a hook that can refuse: its code emits the verdict value `deny` or
exits 2. Writers are excluded from the reader set, because `hydrate.sh` reads
`session_count` to increment it, and counting that as enforcement makes property
C fire on the bookkeeping it was written to permit. The scope is hooks: the
gates are what read an identity to decide. `entity` was additionally checked
against the whole tree by hand -- no reader anywhere, decider or not.

DISCOVERY, not a list -- for the same reason `ci_discovery` discovers: a check
that hard-codes the set of identity files cannot see the one somebody adds.
Artifacts and hooks both come from `git ls-files`.

Usage:  python3 tools/identity_classification_test.py [--report]
Exit 0 = every property holds. Exit 1 = at least one does not.
"""

import ast
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)


# --------------------------------------------------------------------------
# THE CLASSIFICATION. One table, and the only one.
#
# Every entry carries the evidence it was classified ON, because the proposal's
# own method is that a mechanism must be traceable to a pain. An entry whose
# `why` is "looks like it" is an entry somebody guessed, and the totality check
# below exists precisely so that guessing is not required: an undeclared field
# shows up as a RED with its name in it, which is a question addressed to whoever
# owns the field, not a default silently applied on their behalf.
#
# UNDECLARED IS NOT META. It is unaccounted, and it fails this check. A hasher
# built on this table must treat unaccounted as core (fail closed); a CHECK must
# treat it as unfinished, because a hasher that silently absorbs new fields is
# how the classification never gets finished.
# --------------------------------------------------------------------------

CORE = {
    "mrh.in_scope": "it is what the gate permits",
    "role":         "instructive",
    "entity":       "the subject the rest is about",
}

META = {
    "session_count": "record of what happened",
    "last_session":  "record of what happened",
    "sessions":      "record of what happened",
    "phases":        "history",
    "milestones":    "history",
    "relationships": "history",
    "t3":            "a cache of a chain derivation -- see property C",
}

# Keys beginning with `_` are prose the JSON format has no other home for
# (`_comment`, `_note`, `_paths_note`). They are excluded from the totality
# count rather than declared meta: declaring them meta would state that they
# record what happened, and they do not record anything -- they explain. The
# distinction matters at exactly one place, and it is not hypothetical: if a
# `_`-key ever states a constraint, it is instructive prose with no enforcer,
# which is property B's failure, and calling it meta would hide that.
PROSE_PREFIX = "_"


def tracked(pattern: str):
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=REPO,
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO / p for p in out]


def identity_artifacts():
    """Every identity-shaped JSON this repo ships, discovered."""
    found = {}
    for p in tracked("*.json"):
        name = p.name
        if not (name == "identity.json" or name.endswith("identity.seed.json")):
            continue
        try:
            found[p.relative_to(REPO).as_posix()] = json.loads(p.read_text())
        except Exception as e:                       # a file we cannot read is
            found[p.relative_to(REPO).as_posix()] = e  # a finding, not a skip
    return found


# --------------------------------------------------------------------------
# The taint walk.
# --------------------------------------------------------------------------

HEREDOC = re.compile(r"<<-?'?(PY|EOF)'?[^\n]*\n(.*?)\n\1\b", re.S)
PY_INVOKE = re.compile(r"python3?\s+-\s+([^\n<]*)<<")


def embedded_python(shell_src: str):
    """(source, argv) for each python heredoc in a shell file.

    argv matters: hydrate receives the identity path as `sys.argv[1]`, so
    without it the load that seeds the whole walk is unrecognisable.
    """
    for m in HEREDOC.finditer(shell_src):
        body = m.group(2)
        head = shell_src[:m.start()].rsplit("\n", 1)[-1]
        inv = PY_INVOKE.search(head + "<<")
        argv = re.findall(r'"([^"]*)"|\'([^\']*)\'', inv.group(1)) if inv else []
        argv = [a or b for a, b in argv]
        yield body, ["-"] + argv


def identity_field_access(src: str, argv=None):
    """(reads, writes) as dotted field paths off the identity object."""
    tree = ast.parse(src)
    argv = argv or []
    consts = {}            # name -> string value, for path resolution
    tainted = {}           # name -> path tuple into the identity object

    def const_str(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        if isinstance(node, ast.JoinedStr):          # f"{d}/identity.json"
            return "".join(const_str(v) or "" for v in node.values)
        if isinstance(node, ast.FormattedValue):
            return ""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            l, r = const_str(node.left), const_str(node.right)
            return (l or "") + (r or "") if (l or r) else None
        if isinstance(node, ast.Subscript):          # sys.argv[1]
            base = node.value
            if (isinstance(base, ast.Attribute) and base.attr == "argv"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, int)
                    and node.slice.value < len(argv)):
                return argv[node.slice.value]
        if isinstance(node, ast.Call):               # os.path.join(a, b, ...)
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("join", "expanduser",
                                                           "abspath", "get"):
                parts = [const_str(a) for a in node.args]
                parts = [p for p in parts if p]
                return "/".join(parts) if parts else None
        return None

    # pass 1: string constants (two passes so a later-defined name still binds)
    for _ in range(2):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name):
                    v = const_str(node.value)
                    if v:
                        consts[t.id] = v
            elif isinstance(node, ast.Tuple):
                pass
        # tuple unpack: a, b, c = sys.argv[1], sys.argv[2], sys.argv[3]
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Tuple)
                    and isinstance(node.value, ast.Tuple)):
                for t, v in zip(node.targets[0].elts, node.value.elts):
                    if isinstance(t, ast.Name):
                        s = const_str(v)
                        if s:
                            consts[t.id] = s

    def names_an_identity(node):
        for sub in ast.walk(node):
            s = const_str(sub)
            if s and "identity" in s.lower() and s.lower().endswith(".json"):
                return True
        return False

    def is_identity_load(node):
        if not isinstance(node, ast.Call):
            return False
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in ("load", "loads")):
            return False
        return names_an_identity(node)

    def resolve(node):
        """path tuple if node evaluates to (a subtree of) the identity object"""
        if is_identity_load(node):
            return ()
        if isinstance(node, ast.Name):
            return tainted.get(node.id)
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("get", "setdefault") and node.args:
                base = resolve(f.value)
                k = node.args[0]
                if base is not None and isinstance(k, ast.Constant) and isinstance(k.value, str):
                    return base + (k.value,)
        if isinstance(node, ast.Subscript):
            base = resolve(node.value)
            k = node.slice
            if base is not None and isinstance(k, ast.Constant) and isinstance(k.value, str):
                return base + (k.value,)
        if isinstance(node, ast.BoolOp):              # (ident.get("mrh") or {})
            for v in node.values:
                r = resolve(v)
                if r is not None:
                    return r
        return None

    reads, writes = set(), set()
    for _ in range(2):                                # taint needs a second pass too
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Subscript):
                        p = resolve(t)
                        if p:
                            writes.add(".".join(p))
                r = resolve(node.value)
                if r is not None:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            tainted[t.id] = r
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in ("append", "update", "extend", "pop", "setdefault")):
                p = resolve(node.func.value)
                if p:
                    writes.add(".".join(p))
            else:
                p = resolve(node)
                if p:
                    reads.add(".".join(p))
    return reads, writes


def is_decider(src: str) -> bool:
    """Something that DECIDES is something that can refuse.

    Not a filename list and not a grep. A hook is a decider if its code emits
    the verdict value `deny` or exits 2 -- the two ways this repo's hooks block
    a call. Docstrings are skipped, which is not a nicety: every gate in this
    repo explains the deny protocol at length in prose, and the file you are
    reading names it too. A textual count says 1-4 for the gates and 0 for the
    writers, so the crude version happens to separate them here -- but only
    until somebody documents a hook, which is the sort of accident that gets a
    check muted later.

    The separation matters for exactly one reason: `hydrate.sh` reads
    `session_count`, `last_session` and `sessions` to increment them. Counting
    the writer as a decider makes three declared-meta fields look like they are
    being read to decide, and property C fires on its own bookkeeping.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value == "deny" and id(node) not in docstrings):
            return True
        if (isinstance(node, ast.Call) and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 2):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "exit":
                return True
    return False


def hook_sources():
    """Every hook this repo ships, as (relpath, member, python_source, argv)."""
    out = []
    for p in tracked("plugins/*/hooks/*") + tracked("plugins/*/*/*/*/hooks/*"):
        rel = p.relative_to(REPO).as_posix()
        member = rel.split("/")[1]
        if rel.startswith("plugins/codex/marketplace/"):
            member = "codex(marketplace)"
        try:
            src = p.read_text(errors="replace")
        except Exception:
            continue
        if p.suffix == ".py":
            out.append((rel, member, src, None, is_decider(src)))
        elif p.suffix in (".sh", "") and src.startswith("#!"):
            bodies = list(embedded_python(src))
            for body, argv in bodies:
                out.append((rel, member, body, argv, is_decider(body)))
            if "identity" in src and not bodies:
                out.append((rel, member, "", None, False))  # writer, no derivation
    return out


def access_map():
    """member -> {'reads', 'writes'}, and per-file detail.

    `reads` counts ONLY reads performed by a decider. A writer's read of its own
    bookkeeping field is not an enforcement of it.
    """
    per_member, per_file = {}, {}
    for rel, member, src, argv, decides in hook_sources():
        try:
            reads, writes = identity_field_access(src, argv) if src else (set(), set())
        except SyntaxError:
            continue
        per_file[rel] = (reads, writes, decides)
        m = per_member.setdefault(member, {"reads": set(), "writes": set(), "files": []})
        if decides:
            m["reads"] |= reads
        m["writes"] |= writes
        m["files"].append(rel)
    return per_member, per_file


# --------------------------------------------------------------------------
# properties
# --------------------------------------------------------------------------

def keypaths(obj, prefix=""):
    """Top-level keys, plus one level into `mrh` -- the only nested object the
    classification currently reaches into, because it is the only one whose
    subkeys were individually argued."""
    for k, v in obj.items():
        if k.startswith(PROSE_PREFIX):
            continue
        path = f"{prefix}{k}"
        if k == "mrh" and isinstance(v, dict):
            for sk in v:
                if not sk.startswith(PROSE_PREFIX):
                    yield f"mrh.{sk}"
        else:
            yield path


def prop_a_total(artifacts):
    seen = {}
    for rel, obj in artifacts.items():
        if isinstance(obj, Exception):
            continue
        for kp in keypaths(obj):
            seen.setdefault(kp, set()).add(rel)
    unaccounted = {k: v for k, v in seen.items() if k not in CORE and k not in META}
    return seen, unaccounted


def prop_b_enforced(per_member):
    all_reads = set().union(*(m["reads"] for m in per_member.values())) if per_member else set()
    return {f: sorted(k for k, m in per_member.items() if f in m["reads"])
            for f in CORE}, all_reads


def prop_c_silent_core(per_member):
    return {f: sorted(k for k, m in per_member.items() if f in m["reads"])
            for f in META if any(f in m["reads"] for m in per_member.values())}


def prop_d_provenance(per_member, artifacts):
    """A core field is 'carried' by a member if that member ships an identity
    artifact containing it. Among carriers, who DERIVES it?"""
    carriers = {}
    for rel, obj in artifacts.items():
        if isinstance(obj, Exception):
            continue
        member = rel.split("/")[1] if rel.startswith("plugins/") else rel
        if rel.startswith("plugins/codex/marketplace/"):
            member = "codex(marketplace)"
        for kp in keypaths(obj):
            carriers.setdefault(kp, set()).add(member)
    split = {}
    for f in CORE:
        holds = carriers.get(f, set())
        if not holds:
            continue
        derives = {m for m in holds if f in per_member.get(m, {}).get("writes", set())}
        frozen = holds - derives
        if derives and frozen:
            split[f] = (sorted(derives), sorted(frozen))
    return split


def main():
    report = "--report" in sys.argv
    artifacts = identity_artifacts()
    per_member, per_file = access_map()

    seen, unaccounted = prop_a_total(artifacts)
    readers, all_reads = prop_b_enforced(per_member)
    silent = prop_c_silent_core(per_member)
    split = prop_d_provenance(per_member, artifacts)

    print(f"discovered {len(artifacts)} identity artifacts, "
          f"{len(per_file)} hook sources, {len(per_member)} members\n")

    if report:
        for rel, (r, w, d) in sorted(per_file.items()):
            if r or w:
                print(f"  {rel}   [{'decider' if d else 'writer'}]"
                      f"\n      reads  {sorted(r)}\n      writes {sorted(w)}")
        print()

    fails = []

    # A
    if unaccounted:
        fails.append("A")
        print(f"FAIL  A TOTAL: {len(unaccounted)} of {len(seen)} keys are declared "
              f"neither core nor meta")
        for k, where in sorted(unaccounted.items()):
            short = sorted({w.split('/')[1] for w in where if w.startswith('plugins/')})
            print(f"        {k:22s} in {', '.join(short) or 'shipped artifacts'}")
        print("      Not a formatting nit: a hash built on this table covers "
              f"{len(seen) - len(unaccounted)} of {len(seen)} keys,\n"
              "      and the ones outside it are outside by default -- which is the "
              "drift the hash is for.")
    else:
        print(f"PASS  A TOTAL: all {len(seen)} shipped keys declared")

    # B
    unread = [f for f, who in readers.items() if not who]
    if unread:
        fails.append("B")
        print(f"\nFAIL  B ENFORCED: {len(unread)} of {len(CORE)} core fields are read "
              f"by no decider")
        for f in unread:
            print(f"        {f:22s} declared core -- '{CORE[f]}' -- and nothing reads it")
        for f, who in readers.items():
            if who:
                print(f"        {f:22s} read by {', '.join(who)}")
        print("      A field nothing reads constrains nothing. Either a reader is "
              "missing,\n      or the field is informative and the classification "
              "says otherwise.")
    else:
        print(f"\nPASS  B ENFORCED: all {len(CORE)} core fields have a reader")

    # C
    if silent:
        fails.append("C")
        print(f"\nFAIL  C NOT SILENTLY CORE: {len(silent)} meta field(s) are read by "
              f"a decider")
        for f, who in silent.items():
            print(f"        {f:22s} declared meta, read by {', '.join(who)}")
    else:
        print(f"\nPASS  C NOT SILENTLY CORE: no meta field is read by a decider")
        print("      (the weaker direction: the walk under-reports reads, so this "
              "can pass\n       on a reader it could not resolve)")

    # D
    if split:
        fails.append("D")
        print(f"\nFAIL  D UNIFORM PROVENANCE: {len(split)} core field(s) are derived "
              f"on some members and frozen on others")
        for f, (derives, frozen) in split.items():
            print(f"        {f}\n"
                  f"            derived by {', '.join(derives)}\n"
                  f"            frozen at seed on {', '.join(frozen)} "
                  f"(writer performs no derivation)")
        print("      Both shapes produce a self-consistent file, so a hash taken by "
              "each writer\n      over its own output matches on both -- and the "
              "frozen one never writes, so it\n      never submits a hash at all. "
              "An absent record is not a disagreeing one.")
    else:
        print(f"\nPASS  D UNIFORM PROVENANCE: every core field has one producer shape")

    if fails:
        print(f"\nRED  properties {', '.join(fails)}")
        return 1
    print("\nGREEN  A, B, C, D")
    return 0


if __name__ == "__main__":
    sys.exit(main())
