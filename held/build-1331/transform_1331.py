"""Cut hestia #1331 (gaps a/b): Gate 1a sweeps a link's resolved TARGET as well as its name. Reads the gate
core from git HEAD (never the working file), writes the revised copy under a NEUTRAL name, and emits
`source-1331.diff` beside this file. argv: <hestia worktree> <out dir>"""
import difflib, pathlib, subprocess, sys

wt, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()

old = '''    return (list(event.paths) + list(event.repos)
            + (egress_items(getattr(event, "egress", None)) or [])
            + ([event.command] if event.command else []))
'''
new = '''    return (list(event.paths) + list(event.repos)
            + (egress_items(getattr(event, "egress", None)) or [])
            + ([event.command] if event.command else [])
            + link_targets(event))


def link_targets(event: "NormalizedEvent") -> list:
    """The resolved targets of the paths an act names, where a link makes them DIFFER from the name
    (hestia #1331, gaps a/b). Measured on main f9f29a23 in-process (a fixture, no credential): inside a
    granted repo, a link to a secret-NAMED file passed Gate 1a by a relative shell read and by `Read`
    (absolute or relative), because the innate sweep judged the path AS NAMED. Absolute shell paths in
    the workspace already had their target checked (the scope pass); this gives the one rule no grant
    relaxes the same view, for every path argument and every shell word that names an existing path
    (relative ones joined onto the event's cwd). A path that is not a link contributes nothing, so
    an ordinary act's verdict cannot change. Never raises: an unreadable path adds nothing."""
    words = list(event.paths)
    if event.command:
        try:
            words += shlex.split(event.command)
        except ValueError:
            words += event.command.split()
    cwd = getattr(event, "cwd", None)
    out = []
    for w in words:
        if not isinstance(w, str) or not w:
            continue
        # a flag names a path only through its `=value` (`--input=notes.txt`); a bare flag names none
        if w.startswith("-"):
            if "=" not in w:
                continue
            cands = {w.split("=", 1)[1]}
        else:
            cands = {w, w.split("=", 1)[1]} if "=" in w else {w}
        for cand in cands:
            try:
                base = os.path.expanduser(cand)
                if not os.path.isabs(base):
                    if not cwd:
                        continue
                    base = os.path.join(cwd, base)
                if not os.path.lexists(base):
                    continue
                real = os.path.realpath(base)
                if real != os.path.normpath(base):
                    out.append(real)
            except (OSError, ValueError):
                continue
    return out
'''
assert src.count(old) == 1
rev = src.replace(old, new)
(out / "core_rev.py").write_text(rev)
diff = "".join(difflib.unified_diff(src.splitlines(True), rev.splitlines(True), f"a/{rel}", f"b/{rel}"))
here = pathlib.Path(__file__).resolve().parent
(here / "source-1331.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("ok", len(diff.splitlines()), "diff lines")
