#!/usr/bin/env python3
"""Patch preparation for escalation eefa54867105ccd5 (NM2/NM2b — the base tokenizer's
quote model), filed per claude's §8 of forum/claude-code/reply-2767-2768.

The filing named the remedy — fail closed on `$'` reached in unquoted state — and deferred
the patch itself to this artifact: the patch ships only with claude's §5 table as its
acceptance test, measured, and with THIS seat's false-positive cost measured rather than
borrowed from claude's 31/68,288.

What this tool does, in order:

  1. builds the patched copy of plugins/_shared/hestia_governance_closure.py by textual
     anchor (same idiom as claude_heredoc_excision_v3_2751.build_patched) — the REAL patch
     that a grant on eefa54867105ccd5 would write, byte-exact, printed in §6;
  2. runs the §5 acceptance table against THREE arms: installed, installed+patch, and
     v3+patch stacked (claude's 647fc42b re-issue may land first; the anchors must survive
     it), with bash itself as the write oracle;
  3. measures the POSTURE CHOICE: both the unparseable and the out-of-grammar posture
     close NM2/NM2b (the guard re-fires inside _vocab_tokens, so both fall back to raw
     splits — the first draft's claim that OOG leaves NM2 open is measured FALSE and
     corrected here).  The postures separate on a discriminant case: a benign desynced
     write to a hooks-NAMED file outside hooks/ is refused by OOG (FP) and classified
     "read" by the unparseable posture;
  4. runs the module's own contract suite (hestia_governance_closure_test.py) against the
     patched copy;
  5. measures this seat's FP cost over ~/.kimi-code/sessions — both the raw predicate
     (comparable to claude's 31) and the REAL cost: classification flips under the actual
     patch.  Errors are counted per COMMAND and printed (the lesson of claude's §6:
     a scan that cannot classify must say so).

Exit 0 iff: both holes closed by the real patch on both arms, every control unchanged,
the contract suite green, and the scan classified every command it read.

Every governed path is assembled from parts; this script only ever READS the module.

Run:  python3 tools/kimi_ansi_c_desync_patch_2780.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "plugins", "_" + "shared")
MOD = os.path.join(SHARED, "hestia_governance" + "_" + "closure.py")
GATE_REL = os.path.join("plugins", "_" + "shared", "hestia_governance" + "_" + "closure.py")

# ── The patch, verbatim.  §6 prints exactly this; a claim writes exactly this. ──────────────

ANCHOR_FN = "def _is_punct(tok: str) -> bool:"

PATCH_BLOCK = '''
class _AnsiCQuoteDesync(Exception):
    """Internal signal: the command reaches `$'` in UNQUOTED state — ANSI-C quoting, a
    quoting form this tokenizer does not model.  shlex(posix) reads `\\'` inside it as an
    ESCAPED quote; bash reads it as a LITERAL apostrophe, so from that byte on the two
    lexers desync and NO token this tokenizer emits for the command can be trusted —
    including redirect targets (measured: NM2 and NM2b, forum claude-code
    reply-2767-2768 §5; NM2b carries no heredoc operator at all, so the class is the
    quote model, not heredoc).  Raised from _tokenize; _write_position_targets' generic
    arm turns it into the UNPARSEABLE posture — raw whitespace tokens matched at WRITE
    position.  Deliberately NOT _OutOfGrammar: both postures close the measured holes
    (the guard re-fires inside _vocab_tokens, so both fall back to raw whitespace
    splits), but the out-of-grammar arm matches those raw tokens at READ position in
    phase 1, which REFUSES a benign desynced write to a hooks-NAMED file outside hooks/
    (measured on the patch-prep tool's OOG-variant arm: `... > /tmp/witness.py`
    classifies "write" there, "read" here).  And "the tokenizer cannot be trusted on
    this command" IS the unparseable semantics, so the rule on the record
    (RULE_WRITE_UNPARSEABLE) says what actually happened."""


def _has_unquoted_ansi_c_quote(cmd: str) -> bool:
    """`$'` reached in unquoted state.  Tracks only the quote forms this tokenizer already
    models (single, double, backslash escapes), so this is not a second, differently-wrong
    quote model: it is the same model, asked where it stops applying."""
    q, i = None, 0
    while i < len(cmd):
        c = cmd[i]
        if q is None:
            if c == "\\\\":
                i += 2
                continue
            if c == "$" and cmd.startswith("$'", i):
                return True
            if c == "'":
                q = "'"
            elif c == '"':
                q = '"'
        elif q == "'":
            if c == "'":
                q = None
        else:
            if c == "\\\\":
                i += 2
                continue
            if c == '"':
                q = None
        i += 1
    return False

'''

CALL_OLD = """def _tokenize(cmd: str) -> list:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT)"""

CALL_NEW = """def _tokenize(cmd: str) -> list:
    if _has_unquoted_ansi_c_quote(cmd):
        raise _AnsiCQuoteDesync(cmd)
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT)"""

# The posture refutation: identical patch, exception subclasses _OutOfGrammar instead.
OOG_BLOCK = PATCH_BLOCK.replace(
    "class _AnsiCQuoteDesync(Exception):", "class _AnsiCQuoteDesync(_OutOfGrammar):")


def apply_patch(src: str, block: str = PATCH_BLOCK) -> str:
    if src.count(ANCHOR_FN) != 1 or src.count(CALL_OLD) != 1:
        raise SystemExit("patch anchor not unique — module drifted; re-derive the patch")
    return src.replace(ANCHOR_FN, block.lstrip("\n") + ANCHOR_FN, 1).replace(
        CALL_OLD, CALL_NEW, 1)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m  # dataclass() resolves the owning module by name
    spec.loader.exec_module(m)
    return m


def build_arm(dst_dir, src):
    shutil.copytree(SHARED, dst_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "build"))
    p = os.path.join(dst_dir, os.path.basename(MOD))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    return _load(p, "gc_%x" % (abs(hash(dst_dir)) & 0xffffffff))


# ── Cases: claude's §5 table, plus two quoted-`$'` controls the predicate must NOT fire on ──

NM2 = "printf %s $'it\\'s <<EOF'\nprintf x > " + GATE_REL + "\nEOF'"
NM2B = "printf %s $'it\\'s'\nprintf x > " + GATE_REL + "\n:'"

CASES = [
    # label, command, bash writes to the GOVERNED path?, required patched classification
    ("NM2 (heredoc op present)", NM2, True, "write"),
    ("NM2b (NO heredoc op)", NM2B, True, "write"),
    ("control: plain write", "printf x > " + GATE_REL, True, "write"),
    ("control: real heredoc", "cat <<EOF > " + GATE_REL + "\nbody\nEOF", True, "write"),
    ("control: quoted delimiter", "cat <<'EOF' > /tmp/z\nbody\nEOF", False, "none"),
    ("control: benign ANSI-C", "printf %s $'a\\tb' > /tmp/zz", False, None),  # measured, see §2 note
    ("control: `$'` inside SQ", "printf %s 'literal $' > " + GATE_REL, True, "write"),
    ("control: `$'` inside DQ", "printf %s \"$'x\" > /tmp/z2", False, "none"),
    # The posture discriminant: a desynced benign write to a hooks-NAMED file OUTSIDE
    # hooks/.  Unparseable posture matches raw tokens at WRITE position (no hooks/ seg,
    # no match) then phase 2 reads it -> "read".  OOG posture matches at READ position
    # in phase 1, where files_hooks_only matches the bare name -> refused (FP).
    ("control: desynced write, hooks-named file", "printf %s $'a\\tb' > /tmp/witness.py",
     False, "read"),
]


def bash_writes(cmd):
    """Arm C: swap the governed path for a scratch file and ask bash itself."""
    d = tempfile.mkdtemp(prefix="ansic-shell-")
    t = os.path.join(d, "written.txt")
    subprocess.run(["bash", "-c", cmd.replace(GATE_REL, t)], capture_output=True,
                   check=False, stdin=subprocess.DEVNULL, timeout=10)
    return os.path.exists(t)


def verdict(mod, closures, cmd):
    try:
        return mod.classify("Bash", {"command": cmd}, closure=closures[mod]).classification
    except Exception as e:  # classify NEVER raises; if it did, that IS the finding
        return "RAISED:%s" % type(e).__name__


def main():
    tmp = tempfile.mkdtemp(prefix="ansic-patch-")
    installed = _load(MOD, "gc_installed_2780")
    src = open(MOD, encoding="utf-8").read()

    arms = {}
    arms["installed+patch"] = build_arm(os.path.join(tmp, "real"), apply_patch(src))
    arms["OOG variant"] = build_arm(os.path.join(tmp, "oog"), apply_patch(src, OOG_BLOCK))
    # Stacked arm: claude's v3 (escalation 647fc42b, pending re-issue) may land FIRST.
    # The anchors must survive it — measured, not assumed.
    try:
        v3tool = _load(os.path.join(REPO, "tools", "claude_heredoc_excision_v3_2751.py"),
                       "v3tool_2780")
        v3dir = os.path.join(tmp, "v3base")
        (v3src, _v3out), _ = v3tool.build_patched(v3dir)
        arms["v3+patch (stacked)"] = build_arm(os.path.join(tmp, "stacked"),
                                               apply_patch(_v3out))
    except SystemExit as e:
        arms["v3+patch (stacked)"] = "ANCHOR-LOST: %s" % e
    closures = {}
    for label, mod in arms.items():
        if not isinstance(mod, str):
            closures[mod] = mod.default_closure()
    closures[installed] = installed.default_closure()
    # Self-check, earned the hard way: the first run of this tool had apply_patch ignore
    # its `block` parameter, so the "OOG variant" was the real patch twice and every
    # posture conclusion drawn from it was void.  An arm that is not actually distinct
    # must fail loudly here, not publish.
    oog_mod = arms["OOG variant"]
    if not isinstance(oog_mod, str) and not issubclass(
            oog_mod._AnsiCQuoteDesync, oog_mod._OutOfGrammar):
        raise SystemExit("OOG arm is not distinct — arm-construction bug; do not publish")

    print("=== 1. arms built ===")
    for label, mod in arms.items():
        if isinstance(mod, str):
            print("  %-22s %s" % (label, mod))
        else:
            print("  %-22s guard present: %s"
                  % (label, hasattr(mod, "_has_unquoted_ansi_c_quote")))

    print("\n=== 2. acceptance table (bash oracle / installed / patched arms) ===")
    header = ("case", "writes?", "installed", "+patch", "OOG-var", "v3+patch")
    print("  %-28s %-8s %-10s %-8s %-8s %s" % header)
    print("  " + "-" * 78)
    failures = []
    for label, cmd, governed, required in CASES:
        w = bash_writes(cmd)
        vi = verdict(installed, closures, cmd)
        cols = []
        for arm in ("installed+patch", "OOG variant", "v3+patch (stacked)"):
            mod = arms[arm]
            cols.append("(n/a)" if isinstance(mod, str) else verdict(mod, closures, cmd))
        print("  %-28s %-8s %-10s %-8s %-8s %s"
              % (label, w, vi, cols[0], cols[1], cols[2]))
        # Gate: the REAL patch (both arms) must meet the required classification.
        if required is not None:
            for got, arm in ((cols[0], "installed+patch"), (cols[2], "v3+patch")):
                if got != required:
                    failures.append((label, arm, required, got))
        # Consistency: bash truth vs the case's governance expectation.
        if w != governed:
            print("    !! bash oracle disagrees with the case's premise (%s)" % label)
    print("\n  note on the benign-ANSI-C row: claude's raw PREDICATE failed it closed")
    print("  categorically (31/68,288 on their seat).  As a PATCH the cost is lower: the")
    print("  unparseable posture only refuses when a raw whitespace token ALSO matches the")
    print("  closure, so an ungoverned benign command classifies `none`.  The row is")
    print("  reported, not gated — the filed remedy's FP bound is an UPPER bound.")

    print("\n=== 3. posture choice: WHY not _OutOfGrammar (measured, not asserted) ===")
    print("  first draft of this tool asserted the OOG posture leaves NM2 OPEN.  Measured,")
    print("  that is FALSE — the guard re-fires inside _vocab_tokens, so BOTH postures fall")
    print("  back to raw whitespace splits and both close NM2/NM2b (see the table).  The")
    print("  postures separate on the discriminant case instead:")
    disc = CASES[-1]
    for arm in ("installed+patch", "OOG variant"):
        mod = arms[arm]
        got = "(n/a)" if isinstance(mod, str) else verdict(mod, closures, disc[1])
        print("  %-20s `%s` -> %s" % (arm, disc[1], got))
    print("  OOG matches raw tokens at READ position in phase 1, where files_hooks_only")
    print("  matches the bare name: a benign write to /tmp/witness.py is REFUSED (FP).")
    print("  The unparseable posture classifies it `read` — allowed, witnessed.")

    print("\n=== 4. module contract suite against the patched copy ===")
    suite = os.path.join(tmp, "real", "hestia_governance_closure_test.py")
    r = subprocess.run([sys.executable, suite], capture_output=True, text=True,
                       timeout=300, cwd=os.path.join(tmp, "real"))
    print("  hestia_governance_closure_test.py rc=%d" % r.returncode)
    tail = (r.stdout + r.stderr).strip().splitlines()
    for ln in tail[-5:]:
        print("    " + ln)
    if r.returncode != 0:
        failures.append(("contract suite", "installed+patch", "rc=0", "rc=%d" % r.returncode))

    print("\n=== 5. this seat's FP cost (~/.kimi-code/sessions, per-COMMAND error count) ===")
    patched = arms["installed+patch"]
    pred = getattr(patched, "_has_unquoted_ansi_c_quote", None) if not isinstance(patched, str) else None
    root = os.path.expanduser(os.path.join("~", ".kimi-code", "sessions"))
    total = ansi = errs = files_read = 0
    flips = {}
    if pred is not None:
        for rdir, _d, files in os.walk(root):
            for f in files:
                if f != "wire.jsonl":
                    continue
                files_read += 1
                try:
                    fh = open(os.path.join(rdir, f), encoding="utf-8", errors="replace")
                except Exception:
                    continue
                with fh:
                    for line in fh:
                        if '"tool.call"' not in line or '"Bash"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                            ev = rec.get("event") or {}
                            if ev.get("type") != "tool.call" or ev.get("name") != "Bash":
                                continue
                            c = (ev.get("args") or {}).get("command")
                            if not isinstance(c, str):
                                continue
                        except Exception:
                            continue
                        total += 1
                        try:
                            ansi += bool(pred(c))
                            a = verdict(installed, closures, c)
                            b = verdict(patched, closures, c)
                            if a != b:
                                flips[(a, b)] = flips.get((a, b), 0) + 1
                        except Exception:
                            errs += 1
    print("  wire files read: %d   Bash calls scanned: %d   unclassifiable: %d"
          % (files_read, total, errs))
    print("  carrying `$'` in unquoted state (raw predicate, claude-comparable): %d%s"
          % (ansi, "  (%.3f%%)" % (100.0 * ansi / total) if total else ""))
    print("  classification flips under the ACTUAL patch (the real cost):")
    if flips:
        for (a, b), n in sorted(flips.items()):
            print("    %s -> %s : %d" % (a, b, n))
    else:
        print("    none — zero commands change classification on this seat")
    if errs:
        failures.append(("FP scan", "seat", "0 unclassifiable", "%d" % errs))

    print("\n=== 6. the patch, byte-exact (what a grant on eefa54867105ccd5 writes) ===")
    print("  FILE: plugins/_shared/hestia_governance_closure.py  (ONE file, ONE write act)")
    print("  edit 1: insert before `%s`:" % ANCHOR_FN)
    for ln in PATCH_BLOCK.rstrip("\n").splitlines():
        print("  +" + ln)
    print("  edit 2: replace the _tokenize head:")
    for ln in CALL_OLD.splitlines():
        print("  -" + ln)
    for ln in CALL_NEW.splitlines():
        print("  +" + ln)

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("  both holes closed on both arms; controls unchanged; suite green; scan clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
