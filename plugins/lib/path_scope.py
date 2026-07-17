"""
path_scope — realpath containment for the MRH scope gate (Gate-1b).

Hardens the naive string-prefix scope check (`WORKSPACE in p`, `seg in scopes`)
that ships in the orchestrator hooks today. That prefix logic is defeated by
three escapes this library closes:

  1. `../` traversal   — `/root/allowed/../../etc/passwd`
  2. symlink escape    — a symlink inside an allowed root pointing outside it
  3. absolute escape   — `/mnt/...`, `~`, any absolute path outside the roots

Design invariant — **fail-closed-on-doubt**: the Claude-Code-lineage hook
engines (Kimi/Codex/Cursor) fail OPEN on hook error (timeout / crash / non-2
exit all ALLOW). So the containment predicate must DENY on any doubt —
unresolvable path, missing ancestor, permission error, empty roots — or the
boundary is theater. Every code path here that cannot affirmatively prove
containment returns a deny.

This library owns ONLY Gate-1b (is this path inside the granted MRH). The
egress/secret innate check (Gate-1a: `.ssh`/`.env`/credentials) and the
society-safety daemon (Gate-2: write/exec) are separate and stay in the hook.

Shared by every orchestrator hook (claude-code, kimi, codex, cursor, openclaw)
so there is one implementation and no drift — the "one impl" win without a
daemon round-trip (which would reintroduce a fail-open timeout surface on the
hottest predicate). stdlib-only; safe to import from a freshly-spawned hook.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class ScopeResult:
    """Outcome of a containment check. `allowed=False` => the hook must deny."""
    allowed: bool
    reason: str                       # steering explanation (stderr on deny)
    resolved: Optional[str] = None    # the realpath actually tested
    matched_root: Optional[str] = None  # the granted root that contained it

    def __bool__(self) -> bool:
        return self.allowed


_MAX_ANCESTOR_WALK = 256  # runaway guard for nearest-existing-parent search


def _resolve_roots(allowed_roots: Iterable[str]) -> list[tuple[str, str]]:
    """
    Map each granted root to (original, realpath). A root that can't be
    resolved to an existing directory is dropped — it cannot contain any real
    path, so dropping it is safe and never widens scope. Returns [] if none
    resolve (=> everything denies, fail-closed).
    """
    out: list[tuple[str, str]] = []
    for r in allowed_roots:
        if not r:
            continue
        try:
            rp = os.path.realpath(r)
        except OSError:
            continue
        if os.path.isdir(rp):
            out.append((r, rp))
    return out


def _contained(child_real: str, root_real: str) -> bool:
    """
    True iff child_real is root_real or a descendant, compared on path
    COMPONENTS (not string prefix). `/a/bc` is NOT inside `/a/b`.
    """
    try:
        return os.path.commonpath([root_real, child_real]) == root_real
    except ValueError:
        # different drives (Windows) or mixed absolute/relative — not comparable
        return False


def _resolve_target(path: str, cwd: str) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve `path` to the realpath to test for containment.

    Existing path      -> os.path.realpath (resolves symlinks).
    Non-existent path  -> lexically normalize (collapses `..` BEFORE we trust
                          anything), find the nearest existing ancestor,
                          realpath THAT (symlink resolution on the real
                          portion; the non-existent tail has no symlinks), then
                          rejoin the tail. This is the new-file-write case:
                          a Write to a not-yet-existing path has no realpath of
                          its own, so we test where it WOULD land.

    Returns (resolved, None) on success, (None, reason) on any failure —
    caller treats a reason as a DENY (fail-closed-on-doubt).
    """
    if not path:
        return None, "empty path"
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    # Lexical collapse first: turns `/root/a/../../etc` into `/etc` so a `..`
    # escape is decided by containment below, never smuggled past it.
    norm = os.path.normpath(path)

    if os.path.exists(norm):
        try:
            return os.path.realpath(norm), None
        except OSError as e:
            return None, f"cannot resolve path ({type(e).__name__})"

    # Non-existent: walk up to the nearest existing ancestor.
    parent = os.path.dirname(norm)
    walked = 0
    while parent and not os.path.exists(parent):
        nxt = os.path.dirname(parent)
        if nxt == parent:            # reached filesystem root without existing
            break
        parent = nxt
        walked += 1
        if walked > _MAX_ANCESTOR_WALK:
            return None, "path nesting too deep to resolve"
    if not parent or not os.path.exists(parent):
        return None, "no existing ancestor to resolve against"

    try:
        parent_real = os.path.realpath(parent)
    except OSError as e:
        return None, f"cannot resolve parent ({type(e).__name__})"

    # Tail from the (existing, realpath'd) parent to the intended target.
    # `norm` is already lexically collapsed and `parent` is a true ancestor of
    # it, so the tail is forward-only; join + normpath keeps it inside.
    tail = os.path.relpath(norm, parent)
    intended = os.path.normpath(os.path.join(parent_real, tail))
    return intended, None


def check_path(
    path: str,
    allowed_roots: Iterable[str],
    cwd: str,
    *,
    for_write: bool = False,
) -> ScopeResult:
    """
    Is `path` inside one of `allowed_roots` (the granted MRH)?

    `allowed_roots` are the resolved roots the launcher froze at grant time
    (cwd + public repos + shared-context) — this library never reads the
    manifest itself (that would be a hook-time trust input the enforced party
    could edit; scope is fixed at grant time, per the launcher contract).

    Fail-closed: unresolvable target, no existing ancestor, empty/again-
    unresolvable roots => allowed=False. `for_write` is carried for the deny
    reason and future policy; containment logic is identical for read/write
    (both use nearest-existing-ancestor when the path doesn't exist).
    """
    roots = _resolve_roots(allowed_roots)
    if not roots:
        return ScopeResult(False, "no granted roots resolve — nothing is in scope (deny)")

    resolved, err = _resolve_target(path, cwd)
    if err:
        verb = "write" if for_write else "access"
        return ScopeResult(False, f"cannot {verb} '{path}': {err} — denied (fail-closed)")

    for original, root_real in roots:
        if _contained(resolved, root_real):
            return ScopeResult(True, "in scope", resolved=resolved, matched_root=original)

    root_names = ", ".join(o for o, _ in roots)
    return ScopeResult(
        False,
        (f"path '{path}' resolves to '{resolved}', outside your granted scope. "
         f"Your roots: {root_names}. "
         f"Parent-traversal (../), symlink escape, and absolute host paths (/mnt, ~) "
         f"are denied for scoped roles. If you genuinely need this, it is out of your "
         f"MRH — ask the launching human to widen the role; do not route around the gate."),
        resolved=resolved,
    )


def check_paths(
    paths: Iterable[str],
    allowed_roots: Iterable[str],
    cwd: str,
    *,
    for_write: bool = False,
) -> ScopeResult:
    """
    Deny if ANY path is out of scope (a tool touching multiple paths is only in
    scope if all of them are). Returns the first failing ScopeResult, else the
    last success. Empty input denies (nothing to affirmatively allow).
    """
    last: Optional[ScopeResult] = None
    any_path = False
    for p in paths:
        any_path = True
        r = check_path(p, allowed_roots, cwd, for_write=for_write)
        if not r.allowed:
            return r
        last = r
    if not any_path or last is None:
        return ScopeResult(False, "no paths to check — denied (fail-closed)")
    return last
