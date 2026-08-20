#!/usr/bin/env python3
"""hestia_governance_closure — ONE governance-access classifier for every harness shim.

PRD gate-consolidation §5 / §6.B / §7.3(8): the effective governance CLOSURE — the files that
decide policy, the shared modules they import, the installers that put them in force, and the
registration configs that select which shim runs — must be protected from writes BY ANY MEMBER,
uniformly, from every adopting harness. Today each gate carries its own hand-copy of that
predicate (claude-code: _SELF_MARKERS/_GOVERNANCE_FILES/_touches_self; kimi: Gate 1c, restored
as a raw text-match; codex: nothing at all). This module is the single replacement.

GOVERNANCE-ACCESS, NOT SELF-ACCESS (dp, ratified — PR #370 line)
----------------------------------------------------------------
The check is ACCESSOR-AGNOSTIC. "Self" is the wrong key: self-access is delegable (member A
asks member B to edit A's gate, and B's "it isn't MY gate" makes the write ordinary). What is
protected is the UNION of all registered plugins' governance closures, against a write from
ANY member. Member A editing member B's gate is exactly the attack this catches.

KEYED ON WRITE POSITION, NEVER TEXT MENTION (dp, ratified)
----------------------------------------------------------
A tool call is a governance write only if a WRITE-POSITION argument resolves into the closure:
  * Write/Edit/NotebookEdit (and unknown tools, conservatively): file_path / path /
    notebook_path.
  * Bash: parsed write positions only — redirect targets (>, >>, &>, >|), tee arguments,
    cp/install/rsync DESTINATION (mv: EVERY operand — the source is destroyed too), sed -i
    file args, chmod/chown/chgrp/truncate/ln -sf targets, rm/unlink/rmdir/shred targets,
    dd of=, touch targets, git checkout -- / git restore / git clean pathspecs.
A command that merely NAMES a closure file in a read position (grep pattern, find -name, cat
source, cp SOURCE, ls) is classified "read" — allowed, witnessed by the caller. Payload text
(Write `content`, Edit `old_string`/`new_string`, heredoc bodies) is NEVER a haystack: a
document ABOUT the gate is not a write TO the gate. This kills the three measured
false-positive classes (a read-only find denied; a chained benign rm denied; an Edit denied
where the same Write passed) — each is a named regression test in the test file.

MATCHING IS SEGMENT-BASED, RESOLVE-FIRST. Candidates are matched raw AND cwd-joined AND
realpath'd (symlink aliases and `..` resolve before any segment is consulted), then compared
as whole path segments — never substrings — so `plugins/kimi/hooks-backup` does not match
`plugins/*/hooks` (the substring-boundary bug class the core documents as fixed).

Read matching is deliberately BROADER than write matching: a common hook filename
(pre_tool_use.py etc.) counts as a write target only under a hooks/ segment (a stray
witness.py in a vendor tree is not the gate — denying it would be a fresh FP), but a bare
mention of it anywhere classifies as "read" so reconnaissance stays visible as a witnessed
pattern. Over-witnessing a read costs nothing; over-denying a write manufactures bypasses.

CRITERIA LIVE IN THE VAULT; THE FLOOR LIVES HERE (fail-safe literal)
--------------------------------------------------------------------
The closure registry is the union of per-plugin closure manifests (each plugin's expects.json
may declare a `closure` key: dirs / files / hooks_only_files / paths). A new plugin extends
the union by declaring its own closure in its own manifest — no core edit, no peer edit (this
kills the cross-plugin coupling where adding a plugin meant editing other plugins' marker
tuples). If the registry is unreadable the module falls back to LITERAL_FLOOR, a hardcoded
minimal closure — fail-SAFE: the registry can only TIGHTEN the floor (union semantics), never
loosen it. An unreadable vault yields the floor, never an empty (open) closure. This is the
same reasoning as the core's "mirrored, not imported" note: a load failure must not disarm
the check.

FAIL-CLOSED CONTRACT — WITH A DELIBERATE, LOAD-BEARING ASYMMETRY
----------------------------------------------------------------
classify() NEVER raises to the caller and this module never calls sys.exit (it returns a
ClosureVerdict; a shim cannot mistake "the classifier crashed" for "allowed"). But the two
phases fail in OPPOSITE directions, on purpose:

  * An internal error while determining WRITE positions fails CLOSED: classification "write",
    rule "governance-closure-internal-error". A crash on the write path must not let a
    governance write through.
  * An internal error while scanning READ mentions fails OPEN-as-read: classification "read"
    (rule "governance-closure-read-internal-error", for diagnostics). Reads cannot mutate the
    closure, and a read that fails closed would recreate the exact false-positive → bypass →
    friction loop this module exists to end. The write phase has ALREADY returned by the time
    the read phase runs, so nothing write-shaped can hide behind this.

An UNPARSEABLE Bash command (tokenizer failure, e.g. unbalanced quotes) is a narrower case:
write positions are undecidable, so if any raw token matches the closure the command is
classified "write" with rule "governance-closure-unparseable-command" (fail-closed on
ambiguity), and "none" when nothing in it touches the closure vocabulary.

This module is LAW-adjacent classification, not mechanism: transport-free (no sockets, no
daemon), no sys.exit, stdlib only. Witnessing the read, escalating the write, and rendering
the refusal stay in the caller (the shim / hestia_gate_mechanism).

DISCLOSED LIMITS (each is a daemon-preset-backed residual, not a silent hole):
  * Indirection (`bash helper.sh` where helper.sh writes the gate) is not chased — the write
    happens in a child process this classifier never sees; the daemon's destructive preset
    and the witness chain remain behind it. Chasing command text was the FP factory.
  * Wrapper stripping (sudo/env/timeout/...) is best-effort; a confusingly wrapped write may
    classify as none. Same residual backstop.
  * `ln` with a single operand (link lands in cwd) is not resolved.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "ClosureVerdict",
    "Closure",
    "LITERAL_FLOOR",
    "RULE_WRITE",
    "RULE_WRITE_UNPARSEABLE",
    "RULE_OUT_OF_GRAMMAR",
    "RULE_OPAQUE_WRITER",
    "RULE_INTERNAL",
    "RULE_READ_INTERNAL",
    "classify",
    "load_closure",
    "default_closure",
    "attest_shims",
]

# ── Rule ids (returned to the shim; the shim's refusal/witness names the RULE and the ACT) ──
RULE_WRITE = "governance-closure-write"
RULE_WRITE_UNPARSEABLE = "governance-closure-unparseable-command"
# REPAIR 2 (GPT fleet-review blocker 1): a Bash command OUTSIDE the supported shell grammar —
# a substitution/variable in a write position, a shell block/conditional, `bash -c`/`sh -c`/
# `eval`, or a `git apply`/`patch` invocation — whose write set the classifier therefore
# CANNOT resolve. Fail-closed as a write ONLY when closure vocabulary appears anywhere in the
# command (a benign out-of-grammar command that names nothing closure-ish must stay "none",
# or we recreate the friction→bypass loop). See the SUPPORTED GRAMMAR block below.
RULE_OUT_OF_GRAMMAR = "governance-closure-out-of-grammar"
# An opaque patch writer (patch / git apply / git am) whose patch CONTENT could not be
# read: the write set is unknowable, so the act is refused UNCONDITIONALLY — no
# vocabulary condition (GPT second pass: a patch file named /tmp/x.patch carries no
# closure vocabulary on the argv while its content writes the closure). When the patch
# IS readable, its +++/---/rename targets are extracted and classified precisely.
RULE_OPAQUE_WRITER = "governance-closure-opaque-writer"
RULE_INTERNAL = "governance-closure-internal-error"
RULE_READ_INTERNAL = "governance-closure-read-internal-error"


@dataclass(frozen=True)
class ClosureVerdict:
    """What the shim acts on. classification is the ONLY control field:

    "none"  -> not a governance-closure act; proceed to ordinary gates.
    "read"  -> touches/mentions the closure in a non-write position; ALLOWED — the shim
               emits its gate_self_read witness and proceeds.
    "write" -> a write-position argument resolves into the closure; the shim refuses,
               witnesses gate_self_access, and runs its escalation/claim flow.
    `marker` is the matched closure element (the REASON); `resource` is the concrete
    argument that matched (the ACT — a human's basis for approving an escalation).
    `source` says which closure decided: "registry+floor" or "floor".
    """
    classification: str            # "none" | "read" | "write"
    rule: Optional[str] = None     # rule id on "write" (and diagnostics on read-internal)
    marker: Optional[str] = None   # matched closure element
    resource: Optional[str] = None  # the argument that resolved into the closure
    source: str = "floor"


# ── The closure — segment-pattern matchers, tighten-only union ──────────────────────────────
def _segments(path: str) -> tuple:
    p = path.replace("\\", "/").rstrip("/")
    return tuple(s for s in p.split("/") if s not in ("", "."))


def _seg_patterns(items: Iterable[str]) -> tuple:
    out = []
    for it in items:
        if isinstance(it, str):
            segs = _segments(it)
            if segs:
                out.append(segs)
    return tuple(out)


def _contains_run(segs: tuple, pat: tuple) -> bool:
    """True if `pat` appears as a CONSECUTIVE run of whole segments in `segs`.
    "*" matches exactly one segment. Whole-segment equality — never substring — so
    `.../hooks-backup/...` does not satisfy a `hooks` segment."""
    n = len(pat)
    if n == 0 or n > len(segs):
        return False
    for i in range(len(segs) - n + 1):
        if all(p == "*" or p == segs[i + j] for j, p in enumerate(pat)):
            return True
    return False


@dataclass(frozen=True)
class Closure:
    """A set of matchers. Immutable; grown only by union() — tighten-only by construction."""
    dir_markers: tuple = ()        # segment patterns; target in/under the dir is a write
    files_anywhere: tuple = ()     # distinctive basenames — govern wherever they live
    files_hooks_only: tuple = ()   # common basenames — write-match only under a hooks/ segment
    exact_paths: tuple = ()        # segment-suffix patterns (registration configs, installer)
    source: str = "floor"

    def union(self, other: "Closure", source: Optional[str] = None) -> "Closure":
        def u(a, b):
            return a + tuple(x for x in b if x not in a)
        return Closure(
            dir_markers=u(self.dir_markers, other.dir_markers),
            files_anywhere=u(self.files_anywhere, other.files_anywhere),
            files_hooks_only=u(self.files_hooks_only, other.files_hooks_only),
            exact_paths=u(self.exact_paths, other.exact_paths),
            source=source or self.source,
        )

    def _match_segments(self, segs: tuple, position: str) -> Optional[str]:
        if not segs:
            return None
        for pat in self.dir_markers:
            if _contains_run(segs, pat):
                return "/".join(pat)
        for pat in self.exact_paths:
            if len(pat) <= len(segs) and segs[-len(pat):] == pat:
                return "/".join(pat)
        base = segs[-1]
        if base in self.files_anywhere:
            return base
        if base in self.files_hooks_only:
            # WRITE needs the hooks/ context (a stray witness.py elsewhere is not the gate);
            # READ matches the bare name so reconnaissance is still witnessed.
            if position == "read" or "hooks" in segs:
                return base
        return None

    def match(self, target: str, *, cwd: Optional[str] = None,
              position: str = "write") -> Optional[str]:
        """The matched closure element, or None. Candidates: raw, cwd-joined (when relative),
        and realpath'd forms — resolve BEFORE segment comparison (symlink/.. aliasing)."""
        if not isinstance(target, str) or not target:
            return None
        cands = [target]
        norm = target.replace("\\", "/")
        rel = not os.path.isabs(norm) and not norm.startswith("~")
        if cwd and isinstance(cwd, str) and rel:
            cands.append(os.path.join(cwd, norm))
        for c in list(cands):
            # realpath ONLY forms whose base is already pinned (absolute, ~, or joined onto the
            # caller's cwd). realpath on a bare relative resolves against the PROCESS cwd —
            # which is the classifying process's location, not the classified command's, and
            # made classification depend on where the gate happened to run (measured: the test
            # suite flipped verdicts based on the runner's cwd).
            if rel and c is target:
                continue
            try:
                rp = os.path.realpath(os.path.expanduser(c))
                if rp not in cands:
                    cands.append(rp)
            except (OSError, ValueError):
                pass
        for c in cands:
            hit = self._match_segments(_segments(c), position)
            if hit:
                return hit
        return None


# ── LITERAL_FLOOR — the fail-safe minimal closure, hardcoded HERE on purpose ────────────────
# If the registry/vault cannot be read, THIS is what still holds. The registry may only ADD.
# Mirrors (and must stay a superset in spirit of) hestia_gate_core.GOVERNANCE_FILES — kept as
# a literal, not an import, for the same reason the core documents: a failed import must not
# disarm the check on fail-open engines.
LITERAL_FLOOR = Closure(
    dir_markers=(
        ("plugins", "*", "hooks"),   # every registered plugin's hooks dir, accessor-agnostic
        ("plugins", "_shared"),      # the shared governance dir ITSELF: a NEW file dropped
                                     # beside the core is a closure write (measured 2026-08-13:
                                     # the pre-consolidation gate allowed exactly that, because
                                     # it protected known filenames, not the directory)
        ("hestia", "hooks"),
    ),
    files_anywhere=(
        "hestia_gate_core.py",
        "hestia_gate_mechanism.py",
        "hestia_governance_closure.py",   # this module is itself closure
        "gate_self_protection_test.py",
        # web4-hub DEPLOY closure (#415 / web4 #709, R7c limb): these decide WHICH hub
        # binary executes — a write redirecting which binary runs is equivalent to a
        # write to it, and that binary enforces its society's law. Distinctive names,
        # governed wherever they live.
        "web4-hub.service",
        "ratified-build.json",
        "ratify-build.sh",
    ),
    files_hooks_only=(
        "pre_tool_use.py",
        "society_pre_tool_use.py",
        "post_tool_use.py",
        "witness.py",
        "law_inject.py",
    ),
    exact_paths=(
        # The hub's STAGED EXECUTABLE (#415): deliberately a segment path, not a
        # basename — bare "hub" would match a third of the workspace.
        ("hub", "target", "release", "hub"),
        ("deploy", "install-members.sh"),
        (".claude", "settings.json"),
        (".claude", "settings.local.json"),
        (".codex", "config.toml"),
        (".kimi-code", "config.toml"),
        (".kimi", "config.toml"),
    ),
    source="floor",
)


def _closure_from_manifest(manifest: dict) -> Optional[Closure]:
    """Parse one plugin manifest's `closure` key. Returns None when absent/unusable —
    a malformed manifest contributes nothing (the floor still holds), never subtracts."""
    if not isinstance(manifest, dict):
        return None
    c = manifest.get("closure")
    if not isinstance(c, dict):
        return None
    try:
        return Closure(
            dir_markers=_seg_patterns(c.get("dirs") or ()),
            files_anywhere=tuple(f for f in (c.get("files") or ()) if isinstance(f, str)),
            files_hooks_only=tuple(f for f in (c.get("hooks_only_files") or ())
                                   if isinstance(f, str)),
            exact_paths=_seg_patterns(c.get("paths") or ()),
        )
    except Exception:
        return None


def _read_manifests_fs(plugins_root: str) -> dict:
    out = {}
    for name in sorted(os.listdir(plugins_root)):
        mp = os.path.join(plugins_root, name, "expects.json")
        try:
            with open(mp, "r", encoding="utf-8") as fh:
                out[name] = json.load(fh)
        except (OSError, ValueError):
            continue  # a plugin with no/broken manifest contributes nothing
    return out


def load_closure(plugins_root: Optional[str] = None,
                 manifest_reader: Optional[Callable[[], dict]] = None) -> Closure:
    """Assemble the closure: LITERAL_FLOOR ∪ every plugin manifest's declared closure.

    `manifest_reader` (tests, vault-backed readers) returns {plugin_name: manifest_dict}.
    Default reads plugins/*/expects.json beside this module. NEVER raises; total failure
    returns the floor (fail-safe), never an empty closure (fail-open)."""
    try:
        if manifest_reader is not None:
            manifests = manifest_reader()
        else:
            root = plugins_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            manifests = _read_manifests_fs(root)
        if not isinstance(manifests, dict):
            return LITERAL_FLOOR
        result = LITERAL_FLOOR
        for _name, manifest in sorted(manifests.items()):
            extra = _closure_from_manifest(manifest)
            if extra is not None:
                result = result.union(extra)
        return Closure(result.dir_markers, result.files_anywhere, result.files_hooks_only,
                       result.exact_paths, source="registry+floor")
    except Exception:
        return LITERAL_FLOOR


_DEFAULT_CLOSURE: Optional[Closure] = None


def default_closure() -> Closure:
    global _DEFAULT_CLOSURE
    if _DEFAULT_CLOSURE is None:
        _DEFAULT_CLOSURE = load_closure()
    return _DEFAULT_CLOSURE


# ── Bash write-position parsing ─────────────────────────────────────────────────────────────
#
# SUPPORTED GRAMMAR (REPAIR 2 — GPT fleet-review blocker 1). The classifier resolves write
# positions for exactly ONE shape: SIMPLE COMMANDS with recognized verbs and LITERAL
# (non-substitution) arguments, joined by the sequencing operators `;` `&&` `||` `|` `&`. A
# leading `cd <literal dir>` adjusts the effective cwd for relative write targets that FOLLOW
# it on the same command line (so `cd plugins/<m>/hooks && echo x > GATE` resolves into the
# closure). Everything else is OUT OF GRAMMAR and its write set is undecidable:
#   * a substitution/variable in a WRITE position (`> $VAR`, `> $(cmd)`, `cp x $DEST`);
#   * a shell block / conditional governing the command (`if`/`while`/`for`/`case`/`{ }`/
#     subshell) — control flow can hide or gate a write;
#   * `bash -c` / `sh -c` / `eval` — the write happens inside an opaque string;
#   * `git apply` / `git am` / `patch` — the write set lives inside patch CONTENT the
#     classifier never sees.
# An out-of-grammar command is classified "write" (rule RULE_OUT_OF_GRAMMAR) IFF closure
# vocabulary appears ANYWHERE in it (including inside a `-c`/`eval` string, which is
# re-tokenized for the scan); otherwise it stays "none". This is the deliberate fail-closed
# stance for indirection: we cannot see the write, so any closure mention denies — but a
# benign out-of-grammar command that names nothing closure-ish is NOT refused (no new FP).
# Reads are unaffected: a `>` inside a QUOTED argument or a heredoc body is never a write
# position, so it never creates a write target (it may still classify "read", which is allowed).
_PUNCT = "();<>|&"
# The alphabet `_tokenize` actually hands shlex — "\n" is in it (#463). `_is_punct` keys on
# THIS, not on `_PUNCT`: a token shlex assembled out of this alphabet must never read back as
# an ordinary word, or it is appended to the running simple command as an argument.
_PUNCT_CHARS = _PUNCT + "\n"
# BASH'S OPERATOR TABLE, and why it has to exist here (#496, GPT not-same review of the
# first #463 fix). shlex's `punctuation_chars` mode FUSES adjacent punctuation into one
# token — `\n\n`, `;\n`, `\n;`, `\n&&`, `\n>`, `);`, `()` are each a SINGLE token. That
# fusion is a shlex artifact, not a bash rule: bash emits maximal operators from exactly
# this table and nothing else. Every fused spelling was absent from `_SEPARATORS` and, not
# being a separator, was appended to the current simple command — so the boundary vanished
# and the write behind it went unseen again, one token wider than #463:
#
#     printf hi\ncp /tmp/evil <closure>    -> DENY   (#463, closed by the newline token)
#     printf hi\n\ncp /tmp/evil <closure>  -> ALLOW  (#496: one blank line and it is back)
#
# RE-SPLITTING, NOT A WIDER `_SEPARATORS`. A set of fused spellings is a list the next
# fusion outgrows — `\n\n\n` and `\n>` are already outside the four the review named. The
# operator table is CLOSED: bash has no other operators, so restoring bash's own token
# boundaries settles the class instead of enumerating it. It also keeps shlex the SOLE
# quote model (#485's hazard, which the caller's docstring warns of in those words): we
# re-split tokens shlex has ALREADY resolved to unquoted punctuation and never look at raw
# text. And because everything routes back through the EXISTING separator arm, no second
# arm exists to fall out of state parity with it — the fused `);` that carried a `< file`
# preimage past a boundary now hits the one arm that already resets `stdin_src`.
#
# Longest-first, because these are maximal munch: `>>` must not become `>` `>`, and `>&`
# must not become `>` `&` — that would split an fd-dup off its fd and lose `2>&1`.
_OPERATORS = tuple(sorted(
    {";;", "<<<", "&>>", "<<", ">>", "<&", ">&", "<>", ">|", "&>", "&&", "||", "|&",
     ";", "&", "|", "<", ">", "(", ")", "\n"},
    key=len, reverse=True))
# "\n" IS A SEPARATOR AND IT IS EMITTED AS ONE (#463). It was listed here before and
# matched NOTHING, because the tokenizer let shlex treat a newline as whitespace and shlex
# never emits whitespace as a token. Every line after the first therefore arrived as
# ARGUMENTS to line one's head, so a benign head hid every write behind it:
#
#     cp /tmp/evil <closure>/x.py            -> DENY   (positive control)
#     printf hi\ncp /tmp/evil <closure>/x.py -> ALLOW  (#463: same write, invisible)
#
# A silent write to the code that decides writes is the one class worse than a false
# refusal. `_tokenize` now removes "\n" from shlex's whitespace set and adds it to the
# punctuation set, so it arrives here as its own token and this entry finally matches.
# Each entry is one bash operator, and `_tokenize` guarantees they arrive that way: it
# re-splits shlex's fused punctuation runs, so `;\n` reaches here as `;` then `\n` and both
# match. Without that guarantee this set would need every fused spelling, which is not a
# finite thing to maintain (#496).
_SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", ";;", "\n"})
_WRAPPERS = frozenset({"sudo", "doas", "env", "command", "exec", "nohup", "nice", "time",
                       "stdbuf"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Shell-block / control-flow keywords: a simple command headed by one of these means the line
# is a compound construct the write-position parser does not model — out of grammar.
_SHELL_BLOCK_KEYWORDS = frozenset({
    "if", "then", "elif", "else", "fi", "while", "until", "for", "do", "done",
    "case", "esac", "function", "select", "{", "}", "((", "[[",
})
# Interpreters whose `-c` operand is an opaque program string (out of grammar when `-c` given).
_SUBSHELL_CMDS = frozenset({"bash", "sh", "dash", "zsh", "ksh", "mksh", "busybox"})


class _OpaqueWriter(Exception):
    """A patch-applying command whose patch content cannot be read — write set unknowable."""
    def __init__(self, source: str = "stdin"):
        self.source = source


def _patch_write_targets(src_path: str) -> list:
    """Extract write targets from a readable diff/mbox: `+++ `/`--- ` headers (a/ b/
    prefixes stripped, /dev/null skipped) plus git `rename to`/`copy to`. Raises
    _OpaqueWriter when the file cannot be read — the caller fails closed."""
    try:
        with open(os.path.expanduser(src_path), "r", encoding="utf-8",
                  errors="replace") as fh:
            text = fh.read(1_048_576)
    except OSError:
        raise _OpaqueWriter(src_path)
    out = []
    for ln in text.splitlines():
        if ln.startswith(("+++ ", "--- ")):
            p = ln[4:].split("\t")[0].strip()
            if not p or p == "/dev/null":
                continue
            if p.startswith(("a/", "b/")):
                p = p[2:]
            out.append(p)
        elif ln.startswith(("rename to ", "copy to ")):
            out.append(ln.split(" to ", 1)[1].strip())
    return out


class _OutOfGrammar(Exception):
    """Internal signal: this Bash command is outside the supported grammar, so its write set
    cannot be resolved. The caller (_write_position_targets) turns it into the
    RULE_OUT_OF_GRAMMAR posture — a write iff closure vocabulary appears anywhere."""


def _is_punct(tok: str) -> bool:
    return bool(tok) and all(ch in _PUNCT_CHARS for ch in tok)


def _split_operator_run(tok: str) -> list:
    """Split one fused punctuation run into the bash operators it actually is.

    shlex hands back `');'` where bash emits `)` then `;`. Maximal munch against
    `_OPERATORS`, longest first.

    The `raise` is unreachable by construction: every single character of `_PUNCT_CHARS` is
    itself a 1-character operator, so the scan always makes progress. That closure is the
    load-bearing part and it is PINNED as a test rather than assumed here, because a set
    whose producer can emit a value it does not cover is exactly the defect that produced
    #463. If the closure is ever broken, this raises, the caller turns a tokenizer failure
    into the fail-closed unparseable posture, and no unsplit run is ever passed through as
    if it were a word.
    """
    out, i, n = [], 0, len(tok)
    while i < n:
        for op in _OPERATORS:
            if tok.startswith(op, i):
                out.append(op)
                i += len(op)
                break
        else:
            raise ValueError("operator run %r has no operator at offset %d" % (tok, i))
    return out


def _has_subst(tok: str) -> bool:
    """A token carrying a shell substitution/variable — `$VAR`, `${...}`, `$(...)`, or a
    backtick. In a WRITE position this makes the destination unresolvable (out of grammar)."""
    return isinstance(tok, str) and ("$" in tok or "`" in tok)


def _join_eff(eff: str, target: str) -> str:
    """Resolve a relative write target against the cd-tracked effective cwd. Absolute/`~`
    targets are returned unchanged; an empty accumulator leaves the target untouched (the
    caller's real cwd still applies in Closure.match)."""
    if not isinstance(target, str) or not target:
        return target
    if not eff or os.path.isabs(target) or target.startswith("~"):
        return target
    return os.path.normpath(os.path.join(eff, target))


def _vocab_tokens(command: str) -> list:
    """Every token to scan for closure vocabulary on the out-of-grammar path — the outer
    tokens PLUS the re-tokenized contents of any `-c`/`eval` string operand, so a bare
    closure filename named inside an opaque string is still visible to the scan."""
    try:
        toks = _tokenize(command)
    except Exception:
        return command.split()
    out = [t for t in toks if not _is_punct(t)]
    for i, t in enumerate(toks):
        base = os.path.basename(t) if isinstance(t, str) else ""
        if base in _SUBSHELL_CMDS or base == "eval":
            for s in toks[i + 1:]:
                if isinstance(s, str) and s.startswith("-"):
                    continue
                if isinstance(s, str) and s:
                    try:
                        out.extend(_tokenize(s))
                    except Exception:
                        out.append(s)
                break
    return out


def _tokenize(cmd: str) -> list:
    """Tokenize a command, with NEWLINES and COMMENT MARKERS visible to the caller.

    TWO HOLES, ONE CAUSE, CLOSED HERE (#463, measured 2026-08-18):

      `printf hi\ncp /tmp/evil <closure>/x.py`   was permitted — shlex counts a newline as
      whitespace, so the second line became arguments to `printf` and the `cp` was never a
      head. The 2026-08-10 fix for this lived in the caller's own text splitter; the
      2026-08-13 consolidation moved classification here and left the splitter behind, so
      the hole reopened in the module that replaced it.

      `echo a#b; cp /tmp/evil <closure>/x.py`    was permitted — shlex's `commenters` eats
      from `#` to end of LINE, and the `;` sits on that line, so the comment swallowed the
      separator and the write with it. No newline was needed for that one.

    ONE QUOTE MODEL, DELIBERATELY. The obvious repair is to pre-split the raw text on
    unquoted newlines, and the caller's `_command_lines` does exactly that — correctly, with
    its own hand-written quote walk. Porting that walk here would put TWO quote models in one
    classifier, and the day they disagree about where a quote ends is the day the disagreement
    is a bypass (that is #485's class, and the caller's own docstring warns of it in those
    words). So the newline is handed to shlex instead: removed from `whitespace`, added to
    `punctuation_chars`. shlex keeps deciding what is quoted, and a QUOTED newline stays data
    inside its token exactly as before — verified, not assumed.

    COMMENTS ARE NOT STRIPPED, and that is a considered fail-closed trade. Dropping tokens
    from a `#` to the next newline would be the faithful bash rule, but after tokenization a
    token beginning with `#` cannot be distinguished from a QUOTED one (`echo "#x"`), and
    dropping on that guess would make everything after a quoted `#` invisible — trading a
    false refusal for a silent write, which is the wrong direction for this module. Left in,
    a comment's words become an ordinary simple command whose head is `#`: harmless, and the
    following line is still seen. The residual cost is a comment containing a redirect
    (`# write with > here`) raising a phantom write target and refusing a benign command.
    That is a false POSITIVE, it fails closed, and it is the direction this module prefers.
    `a#b` is unaffected: shlex keeps a mid-word `#` attached, so it never opens anything.
    """
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT_CHARS)
    lex.whitespace_split = True
    # Newline must not be whitespace, or it is consumed before it can be punctuation.
    lex.whitespace = " \t\r\f\v"
    # shlex's comment rule eats the separator with the comment; see the docstring.
    lex.commenters = ""
    out = []
    for tok in lex:
        # Only runs shlex ITSELF resolved to unquoted punctuation are re-split, so shlex
        # remains the sole quote model: a quoted word is never re-examined here.
        out.extend(_split_operator_run(tok) if _is_punct(tok) else [tok])
    return out


def _strip_wrappers(words: list) -> list:
    words = list(words)
    for _ in range(8):  # bounded; wrappers nest shallowly
        while words and _ASSIGN_RE.match(words[0]):
            words.pop(0)
        if not words:
            return words
        head = os.path.basename(words[0])
        if head in _WRAPPERS:
            words.pop(0)
            while words and words[0].startswith("-"):
                opt = words.pop(0)
                if head == "sudo" and opt in ("-u", "-g") and words:
                    words.pop(0)
            continue
        if head == "timeout":
            words.pop(0)
            while words and words[0].startswith("-"):
                opt = words.pop(0)
                if opt in ("-k", "--kill-after", "-s", "--signal") and words:
                    words.pop(0)
            if words and re.match(r"^\d", words[0]):
                words.pop(0)
            continue
        return words
    return words


def _positionals(args: list, opts_with_value: tuple = ()) -> list:
    out, i, literal = [], 0, False
    while i < len(args):
        a = args[i]
        if not literal and a == "--":
            literal = True
            i += 1
            continue
        if not literal and a.startswith("-") and a != "-":
            if a in opts_with_value:
                i += 2
                continue
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _opt_value(args: list, *names: str) -> Optional[str]:
    for i, a in enumerate(args):
        if a in names and i + 1 < len(args):
            return args[i + 1]
        for n in names:
            if n.startswith("--") and a.startswith(n + "="):
                return a[len(n) + 1:]
    return None


def _command_write_targets(words: list, stdin_src=None) -> list:
    """Write-position arguments of ONE simple command. Unknown commands contribute NONE —
    their file args are read positions by default (the anti-FP stance; the daemon's
    destructive preset stays behind anything exotic)."""
    words = _strip_wrappers(words)
    if not words:
        return []
    name = os.path.basename(words[0])
    args = words[1:]

    if name in ("cp", "mv", "install", "rsync"):
        ovals = ("-t", "--target-directory", "-S", "--suffix", "-m", "-o", "-g",
                 "--mode", "--owner", "--group", "--backup")
        tdir = _opt_value(args, "-t", "--target-directory")
        pos = _positionals(args, opts_with_value=ovals)
        if name == "mv":
            # mv is rm+cp: the SOURCE is destroyed too, so every operand is a write
            # position (mv <gatefile> /tmp/ disarms the gate as surely as rm does).
            return pos + ([tdir] if tdir else [])
        if tdir:
            return [tdir]
        return [pos[-1]] if len(pos) >= 2 else []
    if name == "tee":
        return _positionals(args)
    if name == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if name == "patch":
        # The write set lives inside the patch CONTENT. Resolve it: read the named input
        # (-i/--input or the `<` stdin source threaded by the caller) and extract its
        # targets. No readable input -> _OpaqueWriter -> unconditional fail-close.
        pin = _opt_value(args, "-i", "--input") or stdin_src
        if not pin:
            raise _OpaqueWriter()
        return _patch_write_targets(pin)
    if name == "sed":
        # In-place: `--in-place[=SUFFIX]`, `-i`, `-i.bak`, AND bundled short clusters that
        # contain `i` (`-Ei`, `-nEi`, ...). A short cluster is `-<letters>` (not `--`); the
        # regex fires when an `i` appears anywhere in that letter run before an attached suffix.
        in_place = any(
            a == "--in-place" or a.startswith("--in-place=")
            or (a.startswith("-") and not a.startswith("--")
                and re.match(r"^-[A-Za-z]*i", a) is not None)
            for a in args)
        if not in_place:
            return []
        script_flag = any(a in ("-e", "-f") or a.startswith(("--expression", "--file"))
                          for a in args)
        pos = _positionals(args, opts_with_value=("-e", "-f"))
        return pos if script_flag else pos[1:]
    if name in ("chmod", "chown", "chgrp"):
        pos = _positionals(args, opts_with_value=("--reference",))
        return pos[1:]
    if name == "truncate":
        return _positionals(args, opts_with_value=("-s", "--size", "-r", "--reference"))
    if name == "ln":
        pos = _positionals(args, opts_with_value=("-t", "--target-directory", "-S", "--suffix"))
        tdir = _opt_value(args, "-t", "--target-directory")
        if tdir:
            return [tdir]
        return [pos[-1]] if len(pos) >= 2 else []
    if name in ("rm", "unlink", "rmdir", "shred"):
        return _positionals(args)
    if name == "touch":
        return _positionals(args, opts_with_value=("-d", "-t", "-r", "--date", "--reference"))
    if name == "git":
        # Skip global options to find the subcommand.
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            break
        if i >= len(args):
            return []
        sub, rest = args[i], args[i + 1:]
        if sub in ("apply", "am"):
            # The write set lives inside the named patch/mbox files (or stdin). Resolve by
            # reading them; unreadable/unknowable -> _OpaqueWriter -> unconditional fail-close.
            pfiles = [a for a in rest if not a.startswith("-")]
            if not pfiles and stdin_src:
                pfiles = [stdin_src]
            if not pfiles:
                raise _OpaqueWriter()
            out, resolved = [], False
            for pf in pfiles:
                try:
                    out.extend(_patch_write_targets(pf))
                except _OpaqueWriter:
                    # A BARE DIGIT THAT CANNOT BE OPENED IS A FILE DESCRIPTOR, not a patch
                    # file. `_tokenize` runs shlex with `punctuation_chars`, which splits
                    # `2>&1` into `2`, `>&`, `1` and keeps NO adjacency — so the fd lands in
                    # the simple command's word list exactly like an argument, and this
                    # branch collected it as a second patch file. `_patch_write_targets`
                    # then failed to open it and raised _OpaqueWriter("2"): an UNCONDITIONAL
                    # fail-close naming a file descriptor as the governance resource, on a
                    # command whose real patch had already been read and named nothing in
                    # the closure. Measured on CBP 2026-08-18 and appealed (a3534df3),
                    # upheld cross-vendor by kimi-code, which reproduced it byte-exact.
                    #
                    # The skip is deliberately conditioned on the READ FAILING, not on the
                    # shape alone: a patch file that really is named `2` still opens, still
                    # parses, and still contributes its targets. Dropping every bare digit
                    # unread would have opened a hole exactly the width of `git apply 2`.
                    #
                    # The `>&` branch in `_bash_write_targets` already skips the RIGHT side
                    # of the same operator (`nxt.isdigit()` after a punct containing `&`).
                    # It ran one token too late to catch the left side; this is that shape,
                    # caught where the damage was.
                    if pf.isdigit():
                        continue
                    raise
                resolved = True
            if not resolved:
                # Every operand was an fd, so no patch source was named at all — the content
                # is arriving on a pipe this classifier cannot read. Same posture as the
                # `not pfiles` case above, and the same reason.
                raise _OpaqueWriter()
            return out
        if sub == "checkout":
            # Only explicit pathspec overwrite (`checkout [-|tree-ish] -- paths`); a branch
            # switch is not a targeted closure write.
            if "--" in rest:
                return rest[rest.index("--") + 1:]
            return []
        if sub == "restore":
            return _positionals(rest, opts_with_value=("-s", "--source"))
        if sub == "clean":
            return _positionals(rest)
        return []
    return []


def _flush_simple_command(words: list, eff: str, targets: list, stdin_src=None) -> str:
    """Resolve ONE simple command: detect out-of-grammar heads (shell block, `bash -c`,
    `eval`, `git apply`/`patch` — the last two via _command_write_targets), track `cd` into
    the effective cwd, else append this command's cd-resolved write targets. Returns the
    (possibly updated) effective cwd. Raises _OutOfGrammar on an out-of-grammar construct."""
    stripped = _strip_wrappers(words)
    if not stripped:
        return eff
    head = stripped[0]
    base = os.path.basename(head) if isinstance(head, str) else ""
    # Shell block / control-flow keyword governing this command -> out of grammar.
    if head in _SHELL_BLOCK_KEYWORDS or base in _SHELL_BLOCK_KEYWORDS:
        raise _OutOfGrammar()
    # `bash -c` / `sh -c` / `eval` -> opaque program string -> out of grammar.
    if base == "eval":
        raise _OutOfGrammar()
    if base in _SUBSHELL_CMDS and any(a == "-c" for a in stripped[1:]):
        raise _OutOfGrammar()
    # `cd <literal dir>` -> adjust the effective cwd for subsequent relative write targets.
    if base == "cd":
        rest = [a for a in stripped[1:] if not a.startswith("-")]
        if rest:
            d = rest[0]
            if _has_subst(d):
                return eff  # a computed cd cannot be tracked; leave eff unchanged
            eff = d if (os.path.isabs(d) or d.startswith("~")) \
                else os.path.normpath(os.path.join(eff or ".", d))
        return eff
    for tg in _command_write_targets(words, stdin_src):  # may raise (git apply/am, patch)
        if _has_subst(tg):
            raise _OutOfGrammar()  # substitution in a write position
        targets.append(_join_eff(eff, tg))
    return eff



_HEREDOC_OP = re.compile(r"<<-?(?!<)\s*([\'\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _strip_heredoc_bodies(command: str) -> str:
    """Remove heredoc BODIES (a line-delimited construct) before tokenizing, keeping the
    operator line itself -- bash executes the rest of that line. Terminator match is
    deliberately loose (stripped compare): terminating early retains body lines as code
    (a false positive), never drops executable code (a bypass)."""
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        delims = [m.group(2) for m in _HEREDOC_OP.finditer(line)]
        i += 1
        for d in delims:
            while i < len(lines) and lines[i].strip() != d:
                i += 1
            if i < len(lines):
                i += 1  # consume the terminator line
    return "\n".join(out)


def _bash_write_targets(command: str) -> list:
    """All write-position arguments across a compound command: redirect targets plus each
    simple command's write positions, each resolved against the cd-tracked effective cwd.
    Raises on tokenizer failure (caller -> unparseable posture) and raises _OutOfGrammar on
    any out-of-grammar construct (caller -> out-of-grammar posture)."""
    toks = _tokenize(_strip_heredoc_bodies(command))
    targets, cur = [], []
    stdin_src = None  # `< file` source for the current simple command (patch input)
    eff = ""  # relative cwd accumulator; cd within this command line adjusts it
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _SEPARATORS:
            if cur:
                eff = _flush_simple_command(cur, eff, targets, stdin_src)
                cur = []
            stdin_src = None
            i += 1
            continue
        if _is_punct(t):
            if (">" in t or "<" in t) and cur and cur[-1].isdigit():
                cur.pop()  # leading fd number belongs to the redirect, not to argv
            if ">" in t:
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and "&" in t and nxt.isdigit():
                    i += 2  # fd dup (2>&1) — not a file
                    continue
                if nxt is not None and nxt not in _SEPARATORS and not _is_punct(nxt):
                    if _has_subst(nxt):
                        raise _OutOfGrammar()  # substitution in a redirect (write) position
                    targets.append(_join_eff(eff, nxt))
                    i += 2
                    continue
                i += 1
                continue
            if t in ("<", "<<", "<<<", "<<-"):
                if t == "<" and i + 1 < len(toks) and not _is_punct(toks[i + 1]):
                    stdin_src = toks[i + 1]  # patch/git-apply may consume this as input
                i += 2  # read redirect / heredoc delimiter — source side, skip operand
                continue
            i += 1
            continue
        cur.append(t)
        i += 1
    if cur:
        eff = _flush_simple_command(cur, eff, targets, stdin_src)
    return targets


# ── Classification ──────────────────────────────────────────────────────────────────────────
_PATH_KEYS = ("file_path", "path", "notebook_path")
_BASH_TOOLS = frozenset({"Bash", "Shell"})
# Tools whose path argument is a READ position. Anything not listed here and not Bash is
# treated conservatively: its path keys are write positions (an unknown tool might mutate).
_READ_PATH_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite",
                              "TodoList", "WebFetch", "WebSearch", "GetGoal"})


def _write_position_targets(tool_name: str, tool_input: Any) -> tuple:
    """(targets, note). note is None or "unparseable" (Bash tokenizer failure: write
    positions undecidable, every raw token becomes a conservative candidate)."""
    if not isinstance(tool_input, dict):
        return [], None
    if tool_name in _READ_PATH_TOOLS:
        return [], None
    if tool_name in _BASH_TOOLS:
        cmd = tool_input.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return [], None
        try:
            return _bash_write_targets(cmd), None
        except _OpaqueWriter as ow:
            # Patch content unreadable: the write set is unknowable and NO vocabulary
            # condition applies — classify() refuses unconditionally.
            return [ow.source], "opaque-writer"
        except _OutOfGrammar:
            # Undecidable write set: hand the FULL vocabulary token list up, so classify()
            # can fail closed iff closure vocabulary appears anywhere in the command.
            return _vocab_tokens(cmd), "out-of-grammar"
        except Exception:
            return cmd.split(), "unparseable"
    # Write / Edit / NotebookEdit / unknown tools: the stated destination keys, and ONLY
    # those. content / old_string / new_string are payload, never destination (FP8 class;
    # this is also what makes Edit and Write classify identically).
    return [v for k in _PATH_KEYS
            if isinstance((v := tool_input.get(k)), str) and v], None


def _read_position_mentions(tool_name: str, tool_input: Any) -> list:
    """Everything the call NAMES in a non-write position. Only used to classify "read"
    (allowed + witnessed) — never to deny. Write positions were already checked; a token
    reappearing here cannot upgrade anything."""
    if not isinstance(tool_input, dict):
        return []
    out = []
    if tool_name in _BASH_TOOLS:
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            try:
                out.extend(t for t in _tokenize(cmd) if not _is_punct(t))
            except Exception:
                out.extend(cmd.split())
    for k in _PATH_KEYS:
        v = tool_input.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    return out


def classify(tool_name: str, tool_input: Any, *, cwd: Optional[str] = None,
             closure: Optional[Closure] = None) -> ClosureVerdict:
    """Classify one tool call against the governance closure. NEVER raises.

    Returns classification "write" (refuse + escalate), "read" (allow + witness), or "none".
    See the module docstring for the fail-direction asymmetry between the two phases."""
    try:
        if closure is None:
            closure = default_closure()
        src = closure.source
    except Exception:
        closure, src = LITERAL_FLOOR, LITERAL_FLOOR.source

    # Phase 1 — WRITE positions. Internal errors here fail CLOSED.
    try:
        targets, note = _write_position_targets(tool_name, tool_input)
        # OUT OF GRAMMAR (REPAIR 2): `targets` is the command's full vocabulary token list,
        # not resolved write positions; match with the BROADER read-position semantics (a
        # bare closure basename anywhere counts as vocabulary) and fail closed as a write if
        # ANY token is closure vocabulary. If none is, fall through to Phase 2 -> "none".
        if note == "opaque-writer":
            # GPT second pass: the literal "any closure write" invariant. An opaque patch
            # whose content cannot be read is refused regardless of argv vocabulary.
            return ClosureVerdict("write", RULE_OPAQUE_WRITER, None,
                                  targets[0] if targets else "stdin", src)
        position = "read" if note == "out-of-grammar" else "write"
        for t in targets:
            marker = closure.match(t, cwd=cwd, position=position)
            if marker:
                if note == "out-of-grammar":
                    rule = RULE_OUT_OF_GRAMMAR
                elif note == "unparseable":
                    rule = RULE_WRITE_UNPARSEABLE
                else:
                    rule = RULE_WRITE
                return ClosureVerdict("write", rule, marker, t, src)
    except Exception as e:  # noqa: BLE001 — fail-closed: a broken write classifier must not admit
        return ClosureVerdict("write", RULE_INTERNAL, None,
                              f"internal:{type(e).__name__}", src)

    # Phase 2 — READ mentions. Internal errors here must NOT block (reads cannot mutate the
    # closure; failing closed here is the FP loop). Nothing write-shaped can reach this phase.
    try:
        for t in _read_position_mentions(tool_name, tool_input):
            marker = closure.match(t, cwd=cwd, position="read")
            if marker:
                return ClosureVerdict("read", None, marker, t, src)
    except Exception:  # noqa: BLE001 — deliberate: read-side failure stays "read", never "write"
        return ClosureVerdict("read", RULE_READ_INTERNAL, None, None, src)

    return ClosureVerdict("none", None, None, None, src)


# ── Attestation seam (consumed by the dashboard; §7.2 rides the #231 manifest family) ───────
def attest_shims(expected: Optional[dict] = None, *,
                 vault_reader: Optional[Callable[[], dict]] = None,
                 shim_paths: Iterable[str] = ()) -> dict:
    """Per-shim wiring report: {path: {status, actual, expected}} with status in
    {"ok", "miswired", "unknown"}.

    `expected` (or `vault_reader()`) maps shim path -> expected sha256 hex. Semantics:
      ok       — file hashes to the vault-stored expectation;
      miswired — an expectation exists and the file mismatches OR is unreadable/absent;
      unknown  — no expectation available (vault unreadable, or shim not listed): NEVER
                 reported as healthy — unknown is the #231 posture, not a quiet ok.
    NEVER raises. Hashing is of the file on disk; the loaded-module self-attestation
    (§7.2's sharpening) layers on top of this seam later."""
    report: dict = {}
    exp: dict = {}
    vault_ok = False
    try:
        if expected is not None:
            exp, vault_ok = dict(expected), True
        elif vault_reader is not None:
            got = vault_reader()
            if isinstance(got, dict):
                exp, vault_ok = dict(got), True
    except Exception:
        exp, vault_ok = {}, False
    try:
        paths = set(exp) | set(shim_paths)
    except Exception:
        paths = set(exp)
    for p in paths:
        actual = None
        try:
            with open(p, "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
        except Exception:
            actual = None
        want = exp.get(p) if vault_ok else None
        if want is None:
            status = "unknown"
        elif actual == want:
            status = "ok"
        else:
            status = "miswired"
        report[p] = {"status": status, "actual": actual, "expected": want}
    return report
