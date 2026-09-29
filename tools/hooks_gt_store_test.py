#!/usr/bin/env python3
"""tools/hooks_gt_store.py: the local GT store is deduplicated, verified on write and read,
immutable, INERT, and resolves each member version to ITS pinned engine.

Hermetic: a synthetic repo (plugins `alpha` and `beta` with ordinary file names -- never a
gate-named file) and a throwaway HESTIA_HOME."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("hooks_gt_store", HERE / "hooks_gt_store.py")
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)
gt = st.hooks_gt

FAILURES: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


def repo(tmp: Path) -> Path:
    r = tmp / "repo"
    for m in ("alpha", "beta"):
        (r / "plugins" / m / "hooks").mkdir(parents=True)
        (r / "plugins" / m / "expects.json").write_text(json.dumps(
            {"install": {"member": f"{m}-member", "files": ["hooks/gate.py", "hooks/common.sh"]}}))
        (r / "plugins" / m / "hooks" / "gate.py").write_text(f"#!/usr/bin/env python3\nprint('{m}')\n")
        # IDENTICAL content in both members: must be one blob in the store.
        (r / "plugins" / m / "hooks" / "common.sh").write_text("#!/bin/sh\nexit 0\n")
    (r / "plugins" / "_shared").mkdir(parents=True)
    (r / "plugins" / "_shared" / "RUNTIME_MANIFEST.txt").write_text("engine.py\n")
    (r / "plugins" / "_shared" / "engine.py").write_text("RULES = 1\n")
    publish(r)
    return r


def publish(r: Path) -> None:
    for rel, data in gt.build(r).items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def raises(fn):
    try:
        fn()
    except st.StoreError as e:
        return str(e)
    return None


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        r = repo(tmp)
        home = tmp / "home"
        home.mkdir()

        print("A. no default location")
        check("the store refuses to guess where it lives", raises(lambda: st.store_root(None)) is not None)

        print("B. ingest: verified, deduplicated, idempotent")
        c = st.ingest(r, home)
        check("closures written for both members and the engine", c["closures_written"] == 3, c)
        root = st.store_root(home)
        blobs = [p for p in (root / "blobs").glob("*/*")]
        common = gt.canonical_digest(gt.with_header(b"#!/bin/sh\nexit 0\n", "hooks/common.sh"))
        check("identical files across members are ONE blob",
              sum(1 for p in blobs if p.name == common) == 1 and c["blobs_reused"] >= 1, c)
        check("blobs are read-only", all((p.stat().st_mode & 0o222) == 0 for p in blobs))
        c2 = st.ingest(r, home)
        check("re-ingesting the same publication writes nothing",
              c2["blobs_written"] == 0 and c2["closures_written"] == 0, c2)

        print("C. INERT: nothing in the store selects anything")
        check("no `current` link or activation marker exists",
              not any(p.name in ("current", "active") for p in root.rglob("*")))
        rec = json.loads(next((root / "closures" / "alpha").glob("*.json")).read_text())
        check("each closure says presence is not certification", "not certification" in rec["note"])
        check("a stored closure holds only its manifest and the note", set(rec) == {"manifest", "note"}, sorted(rec))

        print("D. a member version resolves to ITS pinned engine, even when a newer engine exists")
        a1 = json.loads((r / "hooks-gt" / "alpha" / "manifest.json").read_text())["gt_version"]
        (r / "plugins" / "_shared" / "engine.py").write_text("RULES = 2\n")
        publish(r)
        st.ingest(r, home)
        a2 = json.loads((r / "hooks-gt" / "alpha" / "manifest.json").read_text())["gt_version"]
        check("the engine change produced a new member version", a1 != a2)
        old = st.resolve(home, "alpha", a1)
        new = st.resolve(home, "alpha", a2)
        check("the OLD member version resolves the OLD engine bytes",
              b"RULES = 1" in old["_shared/engine.py"], old.get("_shared/engine.py"))
        check("the new member version resolves the new engine", b"RULES = 2" in new["_shared/engine.py"])
        check("both engine versions coexist in the store",
              len(list((root / "closures" / "_shared").glob("*.json"))) == 2)
        check("the whole store verifies", st.verify(home) == [], st.verify(home))

        print("E. tampering is refused on read, and on reuse at the next ingest")
        target = st.blob_path(root, st.load_closure(root, "alpha", a1)["files"]["hooks/gate.py"])
        os.chmod(target, 0o644)
        target.write_bytes(target.read_bytes().replace(b"print('alpha')", b"print('bypassed')"))
        check("resolve refuses a tampered blob",
              "tampered or corrupt" in (raises(lambda: st.resolve(home, "alpha", a1)) or ""))
        check("verify names it", any("does not match" in x for x in st.verify(home)), st.verify(home))
        check("a re-ingest refuses to reuse the corrupt blob",
              "refusing to reuse" in (raises(lambda: st.ingest(r, home)) or ""))

        cp = root / "closures" / "beta" / f"{json.loads((r / 'hooks-gt' / 'beta' / 'manifest.json').read_text())['gt_version']}.json"
        os.chmod(cp, 0o644)
        cr = json.loads(cp.read_text())
        bver = cr["manifest"]["gt_version"]
        cr["manifest"]["member"] = "someone-else"
        cp.write_text(json.dumps(cr))
        check("a closure edited to lie about itself is refused",
              "does not match its own version" in (raises(
                  lambda: st.resolve(home, "beta", bver)) or ""))

        print("E2. a closure's operational fields cannot diverge from its verified manifest (GPT #1161)")
        # Fresh store, so E's deliberate tampering does not mask these arms.
        home3 = tmp / "home3"
        home3.mkdir()
        st.ingest(r, home3)
        root3 = st.store_root(home3)
        av = json.loads((r / "hooks-gt" / "alpha" / "manifest.json").read_text())["gt_version"]
        bv = json.loads((r / "hooks-gt" / "beta" / "manifest.json").read_text())["gt_version"]
        ap = root3 / "closures" / "alpha" / f"{av}.json"
        os.chmod(ap, 0o644)
        pristine = ap.read_text()
        beta_gate = st.load_closure(root3, "beta", bv)["files"]["hooks/gate.py"]
        alpha_gate = st.load_closure(root3, "alpha", av)["files"]["hooks/gate.py"]
        check("precondition: alpha and beta gates are different blobs", beta_gate != alpha_gate)
        # GPT's reproduction, and one arm per duplicated operational field: each adds the field
        # BESIDE an untouched manifest (the pre-fix record shape), pointing somewhere else.
        arms = {
            "files": {"hooks/gate.py": beta_gate, "hooks/common.sh":
                      st.load_closure(root3, "alpha", av)["files"]["hooks/common.sh"]},
            "engine": {"unit": "_shared", "gt_version": "0" * 64, "files": []},
            "requires": [{"unit": "beta", "path": "hooks/gate.py", "sha256": beta_gate}],
        }
        for field, value in arms.items():
            rec = json.loads(pristine)
            rec[field] = value
            ap.write_text(json.dumps(rec))
            msg = raises(lambda: st.resolve(home3, "alpha", av))
            check(f"a stored `{field}` beside the manifest is refused by resolve",
                  msg is not None and "beyond its manifest" in msg, msg)
            check(f"...and named by verify", any("beyond its manifest" in x for x in st.verify(home3)),
                  st.verify(home3))
        ap.write_text(pristine)
        got = st.resolve(home3, "alpha", av)["alpha/hooks/gate.py"]
        check("control: the untouched closure resolves ALPHA's hook", b"print('alpha')" in got, got[:80])
        check("control: the untouched store verifies clean", st.verify(home3) == [], st.verify(home3))
        # A manifest moved under another unit's directory is refused (unit identity).
        moved = root3 / "closures" / "beta" / f"{av}.json"
        moved.write_text(pristine)
        check("alpha's closure filed under beta is refused",
              "does not match its own version" in (raises(lambda: st.resolve(home3, "beta", av)) or ""))
        moved.unlink()

        print("F. a repo whose GT does not hold is refused, and nothing is written")
        home2 = tmp / "home2"
        home2.mkdir()
        g = r / "hooks-gt" / "beta" / "hooks" / "gate.py"
        g.write_bytes(g.read_bytes() + b"# drift\n")
        msg = raises(lambda: st.ingest(r, home2))
        check("ingest refuses when tools/hooks_gt.py check has findings",
              msg is not None and "does not hold" in msg, msg)
        check("...and wrote nothing at all", not (home2 / st.STORE).exists())

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
