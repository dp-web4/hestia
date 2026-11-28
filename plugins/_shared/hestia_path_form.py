"""One spelling per path, on POSIX and on Windows (hestia #1743, step 1).

The Python mirror of ``core/src/path_form.rs``. The daemon records a scope grant and this gate
enforces it, so the two must agree on what "the same file" means. Both answer to the case table
in ``fixtures/path-form/cases.json``; read the Rust module's doc for the design.

Nothing here touches the filesystem. Junctions, symlinks and 8.3 short names are ``realpath``'s;
this conversion runs first, so ``realpath`` always receives a drive-rooted path. On Windows,
``os.path.realpath("/c/Users/x")`` would otherwise resolve against the CURRENT drive and name
``<drive>:\\c\\Users\\x``, a different file.

NOT WIRED yet: step 2 of #1743 routes the gate's grant matching through it.
"""
from __future__ import annotations

import os

POSIX = "posix"
WINDOWS = "windows"
GITBASH = "gitbash"
DIALECTS = (POSIX, WINDOWS, GITBASH)

_REASONS = {
    "empty": "the path is empty",
    "nul_byte": "the path contains a NUL byte",
    "relative": (
        "the path is relative; its meaning depends on a working directory the daemon and the "
        "gate may not share. Name it from the root (C:/... on Windows, /... elsewhere)"
    ),
    "tilde": "the path starts with ~; expand the home directory before naming the path",
    "drive_relative": "C:x and C: are relative to that drive's current directory; write C:/x",
    "current_drive": (
        "a path rooted without a drive letter means the current drive, which differs by "
        "process; name the drive (C:/...)"
    ),
    "gitbash_mount": (
        "a Git Bash mount (/tmp, /usr, /mnt/..., /) points wherever that Git install puts it; "
        "resolve it with `cygpath -w` and name the Windows path"
    ),
    "stream": (
        "a ':' after the drive names an NTFS stream, another name for the same file; name the "
        "file itself"
    ),
    "invalid_char": (
        "the path contains a character no Windows file name can hold (< > \" | ? * or a "
        "control character); a glob is not a path"
    ),
    "unc": "network (UNC) paths are not supported yet; name a local drive path (hestia #1743)",
    "device_namespace": (
        "device-namespace paths (\\\\.\\, \\\\?\\ without a drive) are not file paths the gate "
        "can scope"
    ),
    "verbatim_trailing": (
        "under \\\\?\\ a trailing '.' or space is part of the name, so it names a different file "
        "from the one without it; remove it or drop the \\\\?\\ prefix"
    ),
}

REFUSAL_CODES = tuple(_REASONS)

_INVALID = set('<>"|?*')


class PathRefused(ValueError):
    """A spelling with no canonical form. ``code`` matches the Rust ``Refusal::code``."""

    def __init__(self, code: str):
        self.code = code
        self.reason = _REASONS[code]
        super().__init__(f"{code}: {self.reason}")


def host_dialect() -> str:
    """``windows`` on Windows, ``posix`` elsewhere. Never ``gitbash``: only a caller that knows an
    act came through Git Bash may say so."""
    return WINDOWS if os.name == "nt" else POSIX


def canonical(raw: str, dialect: str) -> str:
    """The one absolute spelling of ``raw`` under ``dialect``; raises ``PathRefused`` otherwise.

    A grant suffix such as ``/**`` is the caller's to strip first."""
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}")
    if "\0" in raw:
        raise PathRefused("nul_byte")
    raw = _rust_trim(raw)
    if not raw:
        raise PathRefused("empty")
    if dialect == POSIX:
        return _canonical_posix(raw)
    return _canonical_windows(raw, dialect)


def _rust_trim(s: str) -> str:
    # Rust's str::trim strips Unicode White_Space; Python's str.strip() also strips the
    # separator controls \x1c-\x1f, which Rust keeps. Strip only what Rust strips.
    return s.strip("".join(c for c in _UNICODE_WHITE_SPACE))


_UNICODE_WHITE_SPACE = (
    "\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)


def _canonical_posix(raw: str) -> str:
    if raw.startswith("~"):
        raise PathRefused("tilde")
    if not raw.startswith("/"):
        raise PathRefused("relative")
    out: list[str] = []
    for seg in raw[1:].split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/" + "/".join(out)


def _strip_prefix_either(s: str, backslashed: str):
    if s.startswith(backslashed):
        return s[len(backslashed):]
    forward = backslashed.replace("\\", "/")
    if s.startswith(forward):
        return s[len(forward):]
    return None


def _starts_with_drive(s: str) -> bool:
    return len(s) >= 2 and s[0].isascii() and s[0].isalpha() and s[1] == ":"


def _canonical_windows(raw: str, dialect: str) -> str:
    verbatim = False
    s = raw
    rest = _strip_prefix_either(s, "\\\\?\\")
    if rest is not None:
        if rest[:3].upper() == "UNC" and rest[3:4] in ("\\", "/"):
            raise PathRefused("unc")
        if not _starts_with_drive(rest):
            raise PathRefused("device_namespace")
        verbatim = True
        s = rest
    elif _strip_prefix_either(s, "\\\\.\\") is not None:
        raise PathRefused("device_namespace")

    rooted_by_backslash = s.startswith("\\")
    s = s.replace("\\", "/")
    if s.startswith("//"):
        raise PathRefused("unc")
    if s.startswith("~"):
        raise PathRefused("tilde")

    if _starts_with_drive(s):
        if len(s) == 2 or s[2] != "/":
            raise PathRefused("drive_relative")
        drive, rest = s[0].upper(), s[3:]
    elif s.startswith("/"):
        if rooted_by_backslash or dialect == WINDOWS:
            raise PathRefused("current_drive")
        first, _, remainder = s[1:].partition("/")
        if len(first) == 1 and first.isascii() and first.isalpha():
            drive, rest = first.upper(), remainder
        else:
            raise PathRefused("gitbash_mount")
    else:
        raise PathRefused("relative")

    out: list[str] = []
    for seg in rest.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        if ":" in seg:
            raise PathRefused("stream")
        if any(c in _INVALID or ord(c) < 0x20 for c in seg):
            raise PathRefused("invalid_char")
        trimmed = seg.rstrip(". ")
        if len(trimmed) != len(seg):
            if verbatim:
                raise PathRefused("verbatim_trailing")
            if not trimmed:
                continue
        out.append(trimmed)
    return f"{drive}:/" + "/".join(out)


def match_key(canonical_path: str, dialect: str) -> str:
    """The key canonical paths compare by: exact on POSIX; on Windows each Basic Multilingual
    Plane character maps to its simple (single-character) upper case, as NTFS's upcase table
    does, and every other character is kept."""
    if dialect == POSIX:
        return canonical_path
    out = []
    for c in canonical_path:
        if ord(c) > 0xFFFF:
            out.append(c)
            continue
        up = c.upper()
        out.append(up if len(up) == 1 and ord(up) <= 0xFFFF else c)
    return "".join(out)


def is_within(root: str, candidate: str, dialect: str) -> bool:
    """Whether ``candidate`` is ``root`` or beneath it, both already canonical. Tested at a
    separator; a root ending in ``/`` (``C:/``, ``/``) contains everything on it."""
    r = match_key(root, dialect)
    c = match_key(candidate, dialect)
    if c == r:
        return True
    if r.endswith("/"):
        return c.startswith(r)
    return len(c) > len(r) and c.startswith(r) and c[len(r)] == "/"
