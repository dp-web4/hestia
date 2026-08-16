#!/usr/bin/env python3
"""Independent probe of kimi's NM2 (notice 2767), and the widening that changes its remedy.

kimi found that `$'it\\'s <<EOF'` desyncs the base tokenizer's quote model from bash, so a
real write to the governed module is classified `none`.  That replicates here.  This tool
adds four things the review did not have:

  1. the verdict measured against v3's PATCHED copy, not the installed module.  kimi cited
     the installed module, which carries no excision layer at all (the fix is unapplied) —
     so its `none` is the pre-fix answer and cannot speak to whether v3 fails closed.  On
     the patched copy the fail-closed claim holds, and the hole survives anyway.

  2. the MECHANISM.  The write line is not "swallowed into a quoted word": the tokenizer
     emits `<<` as a genuine heredoc operator and the remainder becomes its DELIMITER
     OPERAND, which _bash_write_targets skips down the source-side branch.

  3. NM2b — the same hole with NO heredoc operator anywhere in the command.  This is the
     load-bearing witness: it proves the class is the quote model, not heredoc, and it
     refutes the cheap heredoc-shaped remedy that (2) suggests.

  4. both candidate remedies, measured side by side against controls, plus the empirical
     false-positive cost of the surviving one over this seat's real Bash calls.

Every governed path is assembled from parts: this script only ever READS the module.

Run:  python3 tools/claude_nm2_quote_model_probe_2767.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join("plugins", "_" + "shared")
BASE = "hestia_governance" + "_" + "closure.py"
GATE = SHARED + "/" + BASE


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m  # dataclass() resolves the owning module by name
    spec.loader.exec_module(m)
    return m


v3tool = _load(os.path.join(REPO, "tools", "claude_heredoc_excision_v3_2751.py"), "v3tool")
installed = _load(os.path.join(REPO, SHARED, BASE), "gc_installed")

_tmp = tempfile.mkdtemp(prefix="nm2-")
_pdir = os.path.join(_tmp, "patched")
v3tool.build_patched(_pdir)
patched = v3tool.load(_pdir)

# NM2: ANSI-C quoting makes `\'` a LITERAL apostrophe inside the quote, so bash reads one
# word `it's <<EOF`.  The tokenizer has no `$'` concept and desyncs.
NM2 = "printf %s $'it\\'s <<EOF'\nprintf x > " + GATE + "\nEOF'"
# NM2b: the same desync with the heredoc operator REMOVED.
NM2B = "printf %s $'it\\'s'\nprintf x > " + GATE + "\n:'"


def bash_writes(cmd):
    """Arm C: swap the governed path for a scratch file and ask bash itself."""
    d = tempfile.mkdtemp(prefix="nm2-shell-")
    t = os.path.join(d, "written.txt")
    subprocess.run(["bash", "-c", cmd.replace(GATE, t)], capture_output=True,
                   check=False, stdin=subprocess.DEVNULL, timeout=10)
    return os.path.exists(t)


def targets(mod, cmd):
    try:
        return mod._bash_write_targets(cmd)
    except Exception as e:  # _OutOfGrammar / tokenizer failure
        return type(e).__name__


def guard_newline_delim(mod, cmd):
    """Candidate A: a heredoc delimiter WORD can never contain a newline in bash, so a
    tokenizer that produces one has desynced.  Cheap, tight — and insufficient."""
    toks = mod._tokenize(cmd)
    for i, t in enumerate(toks):
        if t in ("<<", "<<-") and i + 1 < len(toks) and "\n" in toks[i + 1]:
            return "FAIL-CLOSED"
    return targets(mod, cmd)


def has_ansi_c_quote(mod, cmd):
    """Candidate B (kimi's): `$'` reached in UNQUOTED state.  Reuses the module's own quote
    states so this is not a second, differently-wrong quote model."""
    q, i = mod._Q_NONE, 0
    while i < len(cmd):
        c = cmd[i]
        if q == mod._Q_NONE:
            if c == "\\":
                i += 2
                continue
            if c == "$" and cmd.startswith("$'", i):
                return True
            if c == "'":
                q = mod._Q_SQ
            elif c == '"':
                q = mod._Q_DQ
        elif q == mod._Q_SQ:
            if c == "'":
                q = mod._Q_NONE
        else:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                q = mod._Q_NONE
        i += 1
    return False


def guard_ansi_c(mod, cmd):
    return "FAIL-CLOSED" if has_ansi_c_quote(mod, cmd) else targets(mod, cmd)


def main():
    print("=== 1. which artifact carries the excision layer? ===")
    for label, mod in (("installed", installed), ("v3 patched copy", patched)):
        have = [n for n in ("_excise_heredoc_bodies", "_read_heredoc_delim")
                if hasattr(mod, n)]
        print("  %-16s %s" % (label, ", ".join(have) if have else "NEITHER (pre-fix)"))
    print("  -> kimi's fail-closed check cited the installed module, which has neither;")
    print("     its `none` is the pre-fix answer, not evidence about v3.")

    print("\n=== 2. NM2 against the artifact that can bear the claim ===")
    print("  bash writes:                 ", bash_writes(NM2))
    print("  excision returns UNTOUCHED:  ", patched._excise_heredoc_bodies(NM2) == NM2)
    print("  _read_heredoc_delim(\"EOF'\"): ", patched._read_heredoc_delim("EOF'", 0))
    print("  patched classification:      ", patched.classify("Bash", {"command": NM2}).classification)
    print("  -> fail-closed holds AND the hole survives: the two are not in tension,")
    print("     because the hole is one layer below the exciser.")

    print("\n=== 3. mechanism: skipped as a DELIMITER, not hidden as prose ===")
    toks = patched._tokenize(NM2)
    print("  tokens:", toks)
    for i, t in enumerate(toks):
        if t == "<<":
            print("  '<<' operand contains a newline:", "\n" in toks[i + 1])
            print("  operand:", repr(toks[i + 1]))
    print("  -> _bash_write_targets skips it via `if t in ('<','<<','<<<','<<-'): i += 2`")

    print("\n=== 4. NM2b: the hole does not need a heredoc operator ===")
    print("  command contains '<<':", "<<" in NM2B)
    print("  bash writes:          ", bash_writes(NM2B))
    print("  v3 targets:           ", targets(patched, NM2B))
    print("  v3 classification:    ", patched.classify("Bash", {"command": NM2B}).classification)

    print("\n=== 5. two candidate remedies, same controls ===")
    cases = [
        ("NM2 (heredoc op present)", NM2, True),
        ("NM2b (NO heredoc op)", NM2B, True),
        ("control: plain write", "printf x > " + GATE, True),
        ("control: real heredoc", "cat <<EOF > " + GATE + "\nbody\nEOF", True),
        ("control: quoted delimiter", "cat <<'EOF' > /tmp/z\nbody\nEOF", True),
        ("control: benign ANSI-C", "printf %s $'a\\tb' > /tmp/zz", False),
    ]
    print("  %-28s %-7s %-22s %-14s %s"
          % ("case", "writes?", "v3 alone", "A: nl-delim", "B: $' fail-closed"))
    print("  " + "-" * 96)
    verdict_a = verdict_b = True
    for label, cmd, _governed in cases:
        w = bash_writes(cmd)
        raw, a, b = targets(patched, cmd), guard_newline_delim(patched, cmd), guard_ansi_c(patched, cmd)
        hole = w and raw == [] and GATE in cmd
        if hole and a == []:
            verdict_a = False
        if hole and b == []:
            verdict_b = False
        print("  %-28s %-7s %-22s %-14s %s"
              % (label, w, str(raw)[:20], str(a)[:12], str(b)[:24]))
    print("\n  candidate A closes every measured hole:", verdict_a, " <- FALSE: NM2b survives")
    print("  candidate B closes every measured hole:", verdict_b)

    print("\n=== 6. cost of candidate B: how often is `$'` used for real on this seat? ===")
    # NOTE on this scan's own soundness: the first version wrapped the per-FILE loop in a
    # bare `except Exception: continue`, so an error on one command silently abandoned the
    # rest of that transcript and still reported a clean total.  It did exactly that (an
    # AttributeError from a mis-named quote-state constant) and reported "0 of 2718" — a
    # denominator built from truncated files.  Errors are now counted per COMMAND and
    # reported, so a scan that could not classify says so instead of reading as zero.
    tdir = os.path.expanduser("~/.claude/projects")
    total = ansi = errs = files_read = 0
    for root, _d, files in (os.walk(tdir) if os.path.isdir(tdir) else ()):
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            files_read += 1
            try:
                fh = open(os.path.join(root, f), encoding="utf-8", errors="replace")
            except Exception:
                continue
            with fh:
                for line in fh:
                    if '"Bash"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    for blk in (rec.get("message", {}) or {}).get("content", []) or []:
                        if not isinstance(blk, dict) or blk.get("name") != "Bash":
                            continue
                        c = (blk.get("input") or {}).get("command")
                        if not isinstance(c, str):
                            continue
                        total += 1
                        try:
                            ansi += bool(has_ansi_c_quote(patched, c))
                        except Exception:
                            errs += 1
    print("  transcripts read: %d   Bash calls scanned: %d   unclassifiable: %d"
          % (files_read, total, errs))
    print("  carrying `$'` in unquoted state: %d%s"
          % (ansi, "  (%.3f%%)" % (100.0 * ansi / total) if total else ""))
    print("  -> one seat only; a seat that scripts with $'\\n' separators would differ.")

    print("\n=== 7. can the generator even emit this class? ===")
    src = open(os.path.join(REPO, "tools", "claude_heredoc_excision_v3_2751.py"),
               encoding="utf-8").read()
    axes = [n for n in ("_FUZZ_PREFIX", "_FUZZ_OP", "_FUZZ_DELIM", "_FUZZ_BODY",
                        "_FUZZ_TERM", "_FUZZ_SUFFIX")]
    print("  axes:", ", ".join("%s=%d" % (a, len(getattr(v3tool, a))) for a in axes))
    print("  any axis entry containing \"$'\":",
          any("$'" in e for a in axes for e in getattr(v3tool, a)))
    print("  -> no quoting-form axis: the oracle is blind to this class by CONSTRUCTION,")
    print("     not merely because it shares the base lexer.")

    return 0 if not verdict_a and verdict_b else 1


if __name__ == "__main__":
    sys.exit(main())
