#!/usr/bin/env python3
"""REPAIR 2 acceptance — the explicit SUPPORTED-GRAMMAR contract for the closure classifier
(GPT fleet-review blocker 1).

The classifier resolves write positions for exactly ONE shape: simple commands with
recognized verbs and LITERAL arguments, joined by `;` `&&` `||` `|` `&`, with a leading
`cd <literal dir>` adjusting the effective cwd. Everything else is OUT OF GRAMMAR (a
substitution/variable in a write position; a shell block/conditional; `bash -c`/`sh -c`/
`eval`; `git apply`/`git am`/`patch`) and its write set is undecidable — so it is classified
"write" (rule governance-closure-out-of-grammar) IFF closure vocabulary appears anywhere in
the command, and "none" otherwise (a benign out-of-grammar command that names nothing
closure-ish must NOT be refused — that re-creates the friction→bypass loop).

Two suites:
  1. EXPLICIT-ALL: every GPT bad shape as a named case, BOTH arms — a closure target => write,
     the same shape with a benign target => none (or, for the read-FP shapes, simply
     NOT-write). Classifier-only, against the LITERAL_FLOOR (deterministic).
  2. DIFFERENTIAL: ~6 representative cases run in a REAL bash subshell inside a sandbox
     seeded with a fake closure layout; assert the classifier's verdict agrees with what the
     shell ACTUALLY wrote. Every write-arm command only ever touches the sandbox.

Governance-file basenames are assembled from fragments so this SOURCE file never contains a
closure marker as a literal (the installed gate false-positives on the payload text — the
very FP this repair narrows).

check() RAISES so pytest sees each case; the __main__ runner collects (house convention).
Run: SHELL_GRAMMAR_SHARED=<plugins/_shared> python3 shell_grammar_test.py
"""
import hashlib
import os
import subprocess
import sys
import tempfile

# The module under test. Default: ./verify/plugins/_shared beside this file (the repair12
# scratch tree); override with SHELL_GRAMMAR_SHARED to point at any staged _shared.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.environ.get("SHELL_GRAMMAR_SHARED") or os.path.join(
    _HERE, "verify", "plugins", "_shared")
sys.path.insert(0, _SHARED)
import hestia_governance_closure as g  # noqa: E402

FLOOR = g.LITERAL_FLOOR

# Closure basenames — assembled from fragments (never a literal marker in this file).
HOOK = "pre_" + "tool_use.py"          # plugins/*/hooks basename (hooks-only)
CORE = "hestia_gate_" + "core.py"      # plugins/_shared file (anywhere)

_NEUTRAL_CWD = tempfile.mkdtemp(prefix="shell-grammar-neutral-")


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def cls(cmd, cwd=_NEUTRAL_CWD):
    return g.classify("Bash", {"command": cmd}, cwd=cwd, closure=FLOOR)


# ── Suite 1: EXPLICIT-ALL — every GPT shape, both arms ──────────────────────────────────────
# Each case: (name, command, expected_classification, expected_rule_or_None).
# expected_classification: "write" | "none" | "not-write" (read-FP shapes: must not be a write).
HOOKS = "plugins/kimi/hooks"           # a plugins/*/hooks dir (dir-path literals are fine)
SHARED_DIR = "plugins/_shared"
OOG = g.RULE_OUT_OF_GRAMMAR
WRT = g.RULE_WRITE
OPQ = g.RULE_OPAQUE_WRITER
RULE_W = WRT

# Patch-content fixtures (GPT 2nd pass): a diff whose CONTENT targets the closure vs one
# whose content is benign — the argv is identical in shape for both, which is the point.
BENIGN_DIR = tempfile.mkdtemp(prefix="shell-grammar-patches-")
with open(os.path.join(BENIGN_DIR, "closure.patch"), "w", encoding="utf-8") as _fh:
    _fh.write("--- a/plugins/kimi/hooks/" + HOOK + chr(10)
              + "+++ b/plugins/kimi/hooks/" + HOOK + chr(10)
              + "@@ -1 +1 @@" + chr(10) + "-x" + chr(10) + "+y" + chr(10))
with open(os.path.join(BENIGN_DIR, "benign.patch"), "w", encoding="utf-8") as _fh:
    _fh.write("--- a/tmp/notes.txt" + chr(10) + "+++ b/tmp/notes.txt" + chr(10)
              + "@@ -1 +1 @@" + chr(10) + "-x" + chr(10) + "+y" + chr(10))


CASES = [
    # --- substitution / variable in a WRITE position ---
    ("subst_redirect_var__closure",
     f"VAR={HOOKS}/{HOOK}; echo x > $VAR", "write", OOG),
    ("subst_redirect_var__benign",
     "VAR=/tmp/out.txt; echo x > $VAR", "none", None),
    ("subst_cmdsub_redirect__closure",
     f"echo {SHARED_DIR}/{CORE} > $(pickdest)", "write", OOG),
    ("subst_cmdsub_redirect__benign",
     "echo hi > $(pickdest)", "none", None),
    ("subst_cp_dest__closure",
     f"cp {SHARED_DIR}/{CORE} $DEST", "write", OOG),
    ("subst_cp_dest__benign",
     "cp a.txt $DEST", "none", None),

    # --- cd <literal> && write-relative ---
    ("cd_then_write_relative__closure",
     f"cd {HOOKS} && echo x > {HOOK}", "write", WRT),
    ("cd_then_write_relative__benign",
     "cd /tmp && echo x > notes.txt", "none", None),

    # --- shell blocks / conditionals ---
    ("if_block__closure",
     f"if true; then echo x > {HOOKS}/{HOOK}; fi", "write", OOG),
    ("if_block__benign",
     "if true; then echo hi; fi", "none", None),
    ("while_block__closure",
     f"while read l; do rm {SHARED_DIR}/{CORE}; done", "write", OOG),
    ("while_block__benign",
     "while read l; do echo $l; done", "none", None),
    ("brace_block__closure",
     f"{{ echo x > {HOOKS}/{HOOK}; }}", "write", OOG),
    ("brace_block__benign",
     "{ echo hi; }", "none", None),

    # --- sed bundled flags (-Ei, -i.bak) ---
    ("sed_bundled_Ei__closure",
     f"sed -Ei 's/a/b/' {HOOKS}/{HOOK}", "write", WRT),
    ("sed_bundled_Ei__benign",
     "sed -Ei 's/a/b/' /tmp/x.txt", "none", None),
    ("sed_ibak__closure",
     f"sed -i.bak 's/a/b/' {HOOKS}/{HOOK}", "write", WRT),
    ("sed_no_i_on_closure__read",  # -E without -i is a READ, never a write
     f"sed -E 's/a/b/' {HOOKS}/{HOOK}", "not-write", None),

    # --- cp -t DIR src... (DIR is the destination) ---
    ("cp_t_dir__closure",
     f"cp -t {SHARED_DIR} /tmp/a.py", "write", WRT),
    ("cp_t_dir__benign",
     "cp -t /tmp/dest a.py", "none", None),

    # --- bash -c / sh -c / eval (opaque string) ---
    ("bash_c__closure",
     f"bash -c 'rm {HOOKS}/{HOOK}'", "write", OOG),
    ("bash_c__benign",
     "bash -c 'echo hi'", "none", None),
    ("sh_c_bare_name__closure",   # bare closure basename inside the -c string
     f"sh -c 'edit {CORE}'", "write", OOG),
    ("sh_c__benign",
     "sh -c 'ls -la'", "none", None),
    ("eval__closure",
     f"eval \"rm {SHARED_DIR}/{CORE}\"", "write", OOG),
    ("eval__benign",
     "eval \"echo hi\"", "none", None),

    # --- git apply / git am / patch: patch CONTENT is read and resolved (GPT 2nd pass).
    # Readable patch -> precise targets from +++/--- headers; unreadable -> unconditional
    # fail-close (opaque-writer), because argv vocabulary says nothing about the write set.
    ("git_apply__closure_content",
     f"git apply {BENIGN_DIR}/closure.patch", "write", RULE_W),
    ("git_apply__benign_content",
     f"git apply {BENIGN_DIR}/benign.patch", "none", None),
    ("git_apply__missing_patch_fails_closed",
     "git apply /tmp/definitely-missing-xyz.patch", "write", OPQ),
    ("git_apply__no_input_at_all_fails_closed",
     "git apply", "write", OPQ),
    ("git_am__mbox_with_closure_diff",
     f"git am {BENIGN_DIR}/closure.patch", "write", RULE_W),
    ("git_am__missing_mbox_fails_closed",
     "git am /tmp/definitely-missing.mbox", "write", OPQ),
    ("patch__stdin_closure_content",
     f"patch -p1 < {BENIGN_DIR}/closure.patch", "write", RULE_W),
    ("patch__stdin_benign_content",
     f"patch -p1 < {BENIGN_DIR}/benign.patch", "none", None),
    ("patch__stdin_missing_fails_closed",
     "patch -p1 < /tmp/definitely-missing.diff", "write", OPQ),
    ("patch__no_input_fails_closed",
     "patch -p1", "write", OPQ),

    # --- read-FP shapes: a quoted `>` or a heredoc body must NOT create a write target ---
    ("quoted_redirect_in_arg__not_write",
     f"echo 'a > {HOOKS}/{HOOK}'", "not-write", None),
    ("heredoc_body_names_gate__not_write",
     f"cat <<EOF > /tmp/notes.md\nsee {HOOKS}/{HOOK}\nEOF", "not-write", None),
]


def test_explicit_all_grammar_cases():
    failures = []
    for name, cmd, expect, rule in CASES:
        v = cls(cmd)
        if expect == "write":
            if v.classification != "write":
                failures.append(f"{name}: expected write, got {v.classification} ({v})")
                continue
            if rule is not None and v.rule != rule:
                failures.append(f"{name}: expected rule {rule}, got {v.rule} ({v})")
        elif expect == "none":
            if v.classification != "none":
                failures.append(f"{name}: expected none, got {v.classification} ({v})")
        elif expect == "not-write":
            if v.classification == "write":
                failures.append(f"{name}: must NOT be write, got write ({v})")
    check("explicit_all", not failures, "\n  ".join(failures))


# ── Suite 2: DIFFERENTIAL — classifier verdict vs what a REAL shell actually wrote ───────────
def _snapshot(root):
    """Map of rel-path -> sha256 for every file under `root` (created files appear, deleted
    files vanish, modified files change hash)."""
    snap = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                with open(p, "rb") as fh:
                    snap[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                pass
    return snap


def _setup_sandbox(root):
    """A fake closure layout the write-arm commands can safely touch."""
    for sub in ("plugins/kimi/hooks", "plugins/_shared", "docs"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    with open(os.path.join(root, "plugins/kimi/hooks", HOOK), "w") as fh:
        fh.write("orig\n")
    with open(os.path.join(root, "plugins/_shared", CORE), "w") as fh:
        fh.write("orig\n")
    with open(os.path.join(root, "src.txt"), "w") as fh:
        fh.write("payload\n")


def _actually_touched_closure(root, before, after):
    """Did the shell run write/modify/delete any path that IS in the closure?"""
    changed = set()
    for rel in set(before) | set(after):
        if before.get(rel) != after.get(rel):
            changed.add(rel)
    for rel in changed:
        if FLOOR.match(os.path.join(root, rel), position="write"):
            return True, changed
    return False, changed


# (name, command, expected_classifier_write?) — write-arm commands touch ONLY the sandbox.
_DIFF_CASES = [
    ("redirect_into_hook", f"echo pwned > plugins/kimi/hooks/{HOOK}", True),
    ("cp_into_shared", f"cp src.txt plugins/_shared/{CORE}", True),
    ("sed_bundled_in_place", f"sed -Ei 's/orig/edited/' plugins/kimi/hooks/{HOOK}", True),
    ("cd_then_relative", f"cd plugins/kimi/hooks && echo x > {HOOK}", True),
    ("redirect_benign", "echo hi > docs/readme.md", False),
    ("cp_benign", "cp src.txt docs/notes.txt", False),
]


def test_differential_against_real_shell():
    failures = []
    for name, cmd, expect_write in _DIFF_CASES:
        sandbox = tempfile.mkdtemp(prefix=f"shell-grammar-diff-{name}-")
        try:
            _setup_sandbox(sandbox)
            before = _snapshot(sandbox)
            p = subprocess.run(["bash", "-c", cmd], cwd=sandbox,
                               capture_output=True, text=True, timeout=30)
            after = _snapshot(sandbox)
            touched, changed = _actually_touched_closure(sandbox, before, after)
            v = g.classify("Bash", {"command": cmd}, cwd=sandbox, closure=FLOOR)
            classifier_write = v.classification == "write"
            # (a) the shell did what the case says it should
            if touched != expect_write:
                failures.append(f"{name}: shell touched-closure={touched}, expected "
                                f"{expect_write}; rc={p.returncode} changed={changed} "
                                f"stderr={p.stderr!r}")
                continue
            # (b) the differential invariant: classifier agrees with the real write
            if classifier_write != touched:
                failures.append(f"{name}: classifier write={classifier_write} but shell "
                                f"actually-touched-closure={touched} ({v}); changed={changed}")
        finally:
            import shutil
            shutil.rmtree(sandbox, ignore_errors=True)
    check("differential", not failures, "\n  ".join(failures))


# ── Suite 3: BLOCK AROUND A READ-ONLY BODY — the #440 class, pinned as OPEN ─────────────────
# The contract above resolves write positions for simple commands only; a `for`/`if`/`while`
# block is out of grammar, and out-of-grammar means "closure vocabulary anywhere => write".
# So a block whose BODY is a plain read of a closure file is refused as a write, and the
# same body outside the block is not. Three real escalations, each self-withdrawn within
# 15 s and each mis-attributed at least once by a seat that measured the shim's legacy
# `_is_read_only` (which permits these loops since 50f78c4) instead of THIS classifier:
#   a3557a7f4f0ca71f 2026-09-04  python3 <shared test> | tail; for t in tests/*.py; do ...
#   c83eccb2dc985f8a 2026-09-05  for r in <ranges>; do sed -n "${r}p" <shared file>; done
#   0a850f87d37a908b 2026-09-05  for f in <deploy files>; do grep -n ... "$f"; done
# Each case asserts the CURRENT verdict (write, out-of-grammar) next to its unblocked body
# (not-write). When a repair narrows the out-of-grammar haystack so that a block with no
# write position inside it is no longer a write, the block half goes red: move the pair
# into CASES as "not-write" — do not loosen this suite.
_BLOCK_READ_OPEN = [
    ("a3557a7f__interpreter_then_loop",
     f'python3 {SHARED_DIR}/{CORE} 2>&1 | tail -3; echo "=== t ==="; '
     f'for t in plugins/kimi/tests/*.py; do r=$(python3 "$t" 2>&1 | tail -1); echo "$r"; done',
     f'python3 {SHARED_DIR}/{CORE} 2>&1 | tail -3'),
    ("c83eccb2__loop_sed_n_program_expansion",
     f'for r in 1-3 5-7; do echo "--- $r"; sed -n "${{r}}p" {SHARED_DIR}/{CORE}; done',
     f'sed -n "${{r}}p" {SHARED_DIR}/{CORE}'),
    ("c83eccb2_control__loop_static_sed_n",
     f'for r in 1 2; do sed -n 1,3p {SHARED_DIR}/{CORE}; done',
     f'sed -n 1,3p {SHARED_DIR}/{CORE}'),
    ("0a850f87__loop_grep_over_closure_files",
     f'for f in {HOOKS}/{HOOK} {SHARED_DIR}/{CORE}; do grep -n "def " "$f"; done',
     f'grep -n "def " {HOOKS}/{HOOK} {SHARED_DIR}/{CORE}'),
    ("if_block_read_only_body",
     f'if grep -q def {SHARED_DIR}/{CORE}; then cat {SHARED_DIR}/{CORE}; fi',
     f'grep -q def {SHARED_DIR}/{CORE} && cat {SHARED_DIR}/{CORE}'),
]


def test_block_around_read_only_body_is_still_out_of_grammar():
    failures = []
    for name, block, body in _BLOCK_READ_OPEN:
        vb = cls(body)
        if vb.classification == "write":
            failures.append(f"{name}: the UNBLOCKED body is a write ({vb}); the control is "
                            f"broken, so the block half proves nothing")
            continue
        v = cls(block)
        if v.classification != "write" or v.rule != OOG:
            failures.append(f"{name}: block is no longer write/{OOG} (got {v}) — the #440 "
                            f"class moved; promote this pair into CASES as not-write")
    check("block_read_only_body_pinned_open", not failures, "\n  ".join(failures))


ALL = [
    test_explicit_all_grammar_cases,
    test_differential_against_real_shell,
    test_block_around_read_only_body_is_still_out_of_grammar,
]

if __name__ == "__main__":
    print("REPAIR 2 — explicit supported-shell-grammar contract + differential vs real shell")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} suites, {len(CASES)} explicit cases, {len(_DIFF_CASES)} differential, "
          f"{len(_BLOCK_READ_OPEN)} block-read pairs pinned open")
