"""Private scratch workspace for the historical #1314 tooling (Unix only).

This is an accident-prevention guard, not isolation from a hostile same-UID process.
"""
import os
from pathlib import Path
import stat
import sys
import tempfile


MARKER = ".hestia-1314-scratch"
CONTENTS = "hestia-1314-scratch-v1\n"


def require_scratch():
    raw = os.environ.get("HESTIA_1314_SCRATCH")
    if not raw or not hasattr(os, "geteuid"):
        raise RuntimeError("a Unix private HESTIA_1314_SCRATCH is required")
    path = Path(raw)
    if not path.is_absolute() or path != path.resolve():
        raise RuntimeError("scratch must be an absolute, non-symlinked path")
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise RuntimeError("scratch must be an owner-only directory")
    marker = path / MARKER
    st = marker.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077
            or st.st_size != len(CONTENTS)):
        raise RuntimeError("scratch marker must be an owner-only regular file")
    if marker.read_text() != CONTENTS:
        raise RuntimeError("invalid scratch marker")
    return path


def create_scratch(parent=None):
    if not hasattr(os, "geteuid"):
        raise RuntimeError("scratch creation is supported only on Unix")
    parent = Path(parent or tempfile.gettempdir()).resolve(strict=True)
    path = Path(tempfile.mkdtemp(prefix="hestia-1314-", dir=parent))
    marker = path / MARKER
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(CONTENTS)
    return path


if __name__ == "__main__":
    if sys.argv[1:] == ["--create"]:
        print(create_scratch())
    elif sys.argv[1:] == ["--check"]:
        print(require_scratch())
    else:
        raise SystemExit("usage: scratch.py --create|--check")
