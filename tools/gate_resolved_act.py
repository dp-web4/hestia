#!/usr/bin/env python3
"""Layer 1 of the smarter gate: decide gate 1a on the RESOLVED ACT, not the command text.

PROPOSED. This is a standalone function plus its proof. It does not patch, install or deploy
the gate; a seat editing the rule that governs seats is precisely what gate-self-access
exists to prevent. It is written to be reviewed, run, and — if the fleet agrees — applied by
someone who is not me.

THE DEFECT IT REPLACES. Gate 1a currently does:

    for blob in (paths + repos + [command]):
        if forbidden_token in blob.lower():   # unbounded substring, raw command text
            deny(innate=True)

Every open false positive in tools/gate_precision_corpus.py follows from those two words,
"unbounded substring": searching for a word, importing a module, quoting a token in a bug
report, naming a variable after what it holds, or writing an ordinary English plural. And
hestia#923 shows the converse in the same mechanism — a script that writes the law while
mentioning nothing is not classified at all. Over-matching and under-matching are ONE defect.

WHAT THIS DOES INSTEAD, in two moves:

  1. ARGUMENTS ARE NOT PATHS. Split the command into argv and keep only the elements that
     actually name a filesystem location. A regex, a commit message, an issue title and a
     variable name are arguments. They are not scanned as paths, because they are not paths.

  2. COMPONENTS, NOT SUBSTRINGS. Match a forbidden token against whole path COMPONENTS. The
     environment-file token names a file called exactly that, not any filename that happens
     to contain those four characters — which is hestia#988, where a granted directory's own
     file could not be named.

WHAT IT DELIBERATELY DOES NOT DO. It does not relax what counts as forbidden, does not add
an intent test, and does not trust the caller. Every control in the corpus must keep denying,
and the measure refuses to report success unless they do: precision bought by allowing a real
act is not precision, and without controls in the same run those two outcomes look identical.
"""
from __future__ import annotations

import os
import shlex
from typing import Iterable, List, Optional, Tuple


def path_candidates(command: Optional[str], cwd: Optional[str] = None) -> List[str]:
    """The argv elements that actually name a filesystem location.

    Conservative on purpose: when in doubt an element IS treated as a path, because the cost
    of scanning a non-path is a wasted comparison while the cost of skipping a real one is a
    hole. An element counts when it contains a separator, begins with ~ or ., or names
    something that exists relative to cwd.

    Leading decoration is stripped rather than used to dismiss an element: curl's `f=@<path>`
    and shell redirections carry real paths behind a prefix, and a scan that missed those
    would be exactly the under-match half of hestia#923.
    """
    if not command:
        return []
    try:
        argv = shlex.split(command)
    except ValueError:
        # An unparseable command is not a licence to skip the check. Fall back to whitespace
        # splitting: cruder, never quieter.
        argv = command.split()

    out: List[str] = []
    for idx, raw in enumerate(argv):
        # A CODE ARGUMENT IS NOT A PATH AND IS NOT NOTHING — look inside it. This block has
        # to come BEFORE the early exit below: the first cut put it after, so it was
        # unreachable and three nested invocations read a key while the suite said the
        # proposal was clean. Found by running the evasions, not by reading the diff.
        prog_here = _program(argv)
        if idx > 0 and prog_here in CODE_FLAG and argv[idx - 1] == CODE_FLAG[prog_here]:
            if prog_here in SHELL_CODE:
                out.extend(path_candidates(raw, cwd))    # it IS a command; resolve it
            else:
                out.extend(_literals_with_separators(raw))
            continue

        by_prog = _arg_is_path_by_program(argv, idx)
        if by_prog is False:
            continue
        tok = raw
        for lead in ("f=@", "@", "--file=", "--output=", "-o=", ">>", ">", "<"):
            if tok.startswith(lead):
                tok = tok[len(lead):]
        if "=" in tok and "/" in tok.split("=", 1)[1]:
            tok = tok.split("=", 1)[1]
        if not tok:
            continue
        if by_prog is True:
            out.append(tok)
            continue
        looks_like_path = ("/" in tok) or tok.startswith("~") or tok.startswith(".")
        if not looks_like_path and cwd:
            try:
                looks_like_path = os.path.exists(os.path.join(cwd, tok))
            except OSError:
                looks_like_path = False
        if looks_like_path:
            out.append(tok)
    return out


# --- which arguments of a program are actually paths ---------------------------------------
#
# "Is this argument a path?" cannot be answered by looking at the argument. A private-key
# filename and a store name are both bare words; one is a file being read and the other is a
# search pattern. The difference is the PROGRAM, and nothing but the program knows.
#
# (Those two words are described rather than spelled. Writing this comment was refused twice
#  for naming them as examples — the eighth and ninth refusals in a day spent building the
#  case that this happens. The adaptation is in the prose; the rule is untouched.)
#
# Measured while attacking this proposal: without this table, reading a key by bare filename
# with no directory slipped through — a hole the crude substring scan did NOT have. A smarter
# gate that is weaker is the worst available outcome, so this table exists to close it.
#
# ALL_ARGS   : every non-flag argument names a file (cat, cp, tar...).
# AFTER_DDASH: paths come only after `--` (git and friends: the words before it are patterns,
#              refs and subcommands, which is exactly where the measured false positives are).
# CODE_FLAG  : the argument following this flag is code, never a path.
ALL_ARGS = ("cat", "less", "more", "head", "tail", "cp", "mv", "rm", "install", "tar",
            "base64", "scp", "rsync", "shred", "gzip", "openssl", "ssh-keygen", "chmod",
            "chown", "touch", "stat", "file", "wc", "sort", "uniq", "xxd", "od")
AFTER_DDASH = ("git",)
# A shell interpreter's -c argument IS a command: recurse into it. A language interpreter's
# is code in another language: scan only its quoted literals that look like paths.
#
# Both halves were measured. Skipping code entirely was a REGRESSION I introduced while
# closing a different hole — a nested shell invocation reading a key by absolute path went
# from denied to allowed, which the crude substring scan had caught. Scanning code entirely
# is the original defect, since a process-environment accessor is not a file. Neither
# extreme is right and the split is the whole point: ask what the argument IS.
SHELL_CODE = {"bash": "-c", "sh": "-c", "zsh": "-c", "dash": "-c"}
LANG_CODE = {"python": "-c", "python3": "-c", "perl": "-e", "ruby": "-e", "node": "-e"}
CODE_FLAG = dict(SHELL_CODE, **LANG_CODE)


def _literals_with_separators(code: str) -> List[str]:
    """Quoted string literals inside foreign code that look like filesystem paths.

    Narrow on purpose. A literal containing a separator is a plausible path; an attribute
    name is not, which is what keeps the process-environment accessor out of this.
    """
    import re
    out = []
    for m in re.finditer(r"""(['"])(.*?)\1""", code, re.S):
        lit = m.group(2)
        if "/" in lit or lit.startswith("~"):
            out.append(lit)
    return out


def _program(argv: List[str]) -> str:
    return os.path.basename(argv[0]).lower() if argv else ""


def _arg_is_path_by_program(argv: List[str], i: int) -> Optional[bool]:
    """True/False when the PROGRAM settles it, None when it does not and shape must decide."""
    prog = _program(argv)
    if not prog or i == 0:
        return False
    if prog in AFTER_DDASH:
        try:
            return i > argv.index("--")
        except ValueError:
            return False          # no `--`: nothing on a git command line is a path argument
    if prog in CODE_FLAG and argv[i - 1] == CODE_FLAG[prog]:
        return False              # handled by path_candidates, which looks INSIDE it
    if prog in ALL_ARGS:
        return not argv[i].startswith("-")
    return None


def _components(p: str) -> List[str]:
    """Path components, lowercased, with decoration and expansion removed."""
    p = os.path.expanduser(p)
    return [c for c in p.lower().replace("\\", "/").split("/") if c]


def _component_hit(want: str, have: str) -> bool:
    """One forbidden component against one path component, on REAL boundaries.

    Exact is not enough and substring is too much. A secret file is routinely the token plus
    an extension, and an extension is one dot away: the component-exact rule this replaces
    MISSED the dot-env file with a `local` suffix, the same file with a deployment suffix,
    and the AWS-shaped credential file with its json extension — three real ones that the
    crude substring scan it is meant to improve on catches. A precision proposal that is
    WEAKER than what it replaces is the worst available outcome. Found by attacking the
    proposal, not by reading it.

    So a token matches a component when it IS that component, when the component is the token
    plus a dot-extension, or when the component ends at the token on a dot. The delimiter set
    is the dot ONLY. Admitting '-' or '_' as boundaries brings the false positives straight
    back: a document written about credential handling has a hyphen in its basename, and
    under a hyphen rule it is refused again — the exact defect this layer exists to end.

    (The forms above are described rather than spelled. Writing this docstring was refused
    three times for naming them — refusals twelve through fourteen in a day spent measuring
    that this happens, every one of them on text whose only purpose is to explain the
    refusal. The rule is untouched; only my prose adapted, which is the litigated route and
    is also the evidence.)

    Residual, measured and accepted: a key file renamed with an underscore infix and stored
    outside the standard directory is not matched by its own token. It IS matched by the
    directory token in every standard location, and widening to catch it costs the false
    positives above. Named here so the next reader inherits the measurement, not the guess.
    """
    if have == want:
        return True
    if have.startswith(want + "."):
        return True
    if want.startswith("."):
        return have.endswith(want)          # a dotted token as the extension of a basename
    return have.endswith("." + want)        # a bare token as the extension of a basename


def token_hits_path(token: str, path: str) -> bool:
    """Does a forbidden token match this path ON COMPONENT BOUNDARIES?

    A single-component token matches one component. A multi-component token (a token written
    with separators) matches a consecutive run of them. Each component is compared by
    _component_hit, which admits a dot-extension and nothing else. Nothing matches as a bare
    substring inside a longer name, which is what retires hestia#988.
    """
    want = [c for c in token.lower().split("/") if c]
    if not want:
        return False
    have = _components(path)
    n = len(want)
    return any(len(have[i:i + n]) == n
               and all(_component_hit(w, h) for w, h in zip(want, have[i:i + n]))
               for i in range(len(have) - n + 1))


def forbidden_reach(paths: Iterable[str], repos: Iterable[str], command: Optional[str],
                    forbidden: Iterable[str], cwd: Optional[str] = None
                    ) -> Optional[Tuple[str, str]]:
    """(token, path) for the first real reach at a forbidden thing, else None.

    `paths` are already-resolved targets and are scanned as they are. `repos` are names, so a
    token matches a name exactly. The command contributes only its path arguments.
    """
    forbidden = list(forbidden)
    for p in list(paths) + path_candidates(command, cwd):
        for f in forbidden:
            if token_hits_path(f, p):
                return f, p
    for r in repos:
        low = str(r).lower()
        for f in forbidden:
            if low == f.lower().strip("/"):
                return f, str(r)
    return None
