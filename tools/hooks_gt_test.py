#!/usr/bin/env python3
"""tools/hooks_gt.py: the digest rule, the redundancy check, and every finding it can name.

Hermetic: a synthetic repo root in a temp dir, with a plugin named `demo` whose files have ordinary
names, so the test never writes a gate-named file. The last section runs `check` on the real repo:
the published GT must hold on every commit (docs/PRD_HOOK_GROUND_TRUTH.md G2)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("hooks_gt", HERE / "hooks_gt.py")
gt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gt)

FAILURES: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def repo(tmp: Path) -> Path:
    r = tmp / "repo"
    (r / "plugins" / "demo" / "hooks").mkdir(parents=True)
    (r / "plugins" / "_shared").mkdir(parents=True)
    (r / "plugins" / "demo" / "expects.json").write_text(json.dumps(
        {"gate": ["PreToolUse"], "install": {"member": "demo-member",
                                             "files": ["hooks/gate.py", "hooks/obs.sh"]}}))
    (r / "plugins" / "demo" / "hooks" / "gate.py").write_text("#!/usr/bin/env python3\nprint('gate')\n")
    (r / "plugins" / "demo" / "hooks" / "obs.sh").write_text("#!/bin/sh\nexit 0\n")
    (r / "plugins" / "demo" / "hooks" / "hooks.json").write_text('{"hooks": {}}\n')
    (r / "plugins" / "_shared" / "RUNTIME_MANIFEST.txt").write_text("# engine\nengine.py\n")
    (r / "plugins" / "_shared" / "engine.py").write_text("X = 1\n")
    return r


def publish_into(r: Path) -> None:
    for rel, data in gt.build(r).items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def main() -> int:
    print("A. the digest rule")
    src = b"#!/usr/bin/env python3\nprint('x')\n"
    pub = gt.with_header(src, "hooks/x.py")
    check("the header goes after the shebang", pub.split(b"\n")[1].startswith(b"# hestia-gt-sha256:"))
    check("the header names the file's own canonical digest",
          gt.header_value(pub) == gt.canonical_digest(pub))
    check("stripping the header gives back the source", gt.strip_header(pub) == src)
    check("JSON carries no header", gt.with_header(b'{"a": 1}\n', "hooks/hooks.json") == b'{"a": 1}\n')
    other = pub.replace(b"print('x')", b"print('y')")
    check("changing the body changes the canonical digest",
          gt.canonical_digest(other) != gt.canonical_digest(pub))

    with tempfile.TemporaryDirectory() as d:
        r = repo(Path(d))
        print("B. a fresh publish holds")
        check("before publishing, check says nothing is published",
              any("does not exist" in f for f in gt.check(r)), gt.check(r))
        publish_into(r)
        check("after publishing, no findings", gt.check(r) == [], gt.check(r))
        m = json.loads((r / "hooks-gt" / "demo" / "manifest.json").read_text())
        check("the manifest names the member and the registration",
              m["member"] == "demo-member" and m["registration"] == "hooks/hooks.json")
        check("the registration template is ground truth too",
              any(f["path"] == "hooks/hooks.json" for f in m["files"]))
        check("the shared engine is its own unit", (r / "hooks-gt" / "_shared" / "engine.py").is_file())

        print("C. every deviation is named")
        g = r / "hooks-gt" / "demo" / "hooks" / "gate.py"
        pristine = g.read_bytes()
        g.write_bytes(pristine.replace(b"print('gate')", b"print('bypassed')"))
        f = gt.check(r)
        check("a GT file edited in place reads MISWIRED against its published sha",
              any("does not match its published sha" in x and "MISWIRED" in x for x in f), f)
        check("...and as an unpublished change against its source",
              any("UNPUBLISHED" in x for x in f), f)
        g.write_bytes(pristine)

        s = r / "plugins" / "demo" / "hooks" / "obs.sh"
        s.write_text("#!/bin/sh\nexit 1\n")
        f = gt.check(r)
        check("a source edited without re-publishing is UNPUBLISHED", f and all("UNPUBLISHED" in x for x in f), f)
        publish_into(r)
        check("re-publishing clears it", gt.check(r) == [], gt.check(r))

        hv = gt.header_value(g.read_bytes())
        g.write_bytes(g.read_bytes().replace(hv.encode(), b"f" * 64))
        f = gt.check(r)
        check("a header that disagrees with the manifest is named",
              any("header sha" in x for x in f), f)
        g.write_bytes(pristine)

        (r / "hooks-gt" / "demo" / "hooks" / "obs.sh").unlink()
        f = gt.check(r)
        check("a missing GT file is named", any("GT file is missing" in x for x in f), f)
        publish_into(r)

        exp = json.loads((r / "plugins" / "demo" / "expects.json").read_text())
        exp["install"]["files"].append("hooks/new.py")
        (r / "plugins" / "demo" / "expects.json").write_text(json.dumps(exp))
        (r / "plugins" / "demo" / "hooks" / "new.py").write_text("pass\n")
        f = gt.check(r)
        check("a newly declared file that was never published is named",
              any("not in the published manifest" in x for x in f), f)

        print("D. publish emits one patch for a tree that has none yet")
        r2 = repo(Path(d) / "fresh")
        out = Path(d) / "gt.patch"
        n = gt.emit_patch(r2, out)
        check("the patch has changes", n > 0, n)
        text = out.read_text()
        check("new executable files are marked 0755", "new file mode 100755" in text)

    print("E. the real repo: the published GT holds on this commit")
    f = gt.check()
    for x in f:
        print("     ", x)
    check("tools/hooks_gt.py check is clean on this tree", f == [], f"{len(f)} finding(s)")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
