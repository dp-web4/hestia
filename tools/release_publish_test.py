#!/usr/bin/env python3
"""tools/release_publish.py against a mocked `gh`: nothing short of the full manifest publishes.

The regression is Codex's HOLD on hestia#1283: assemble succeeded, the artifact download failed,
the fresh draft was empty, and the old inline shell compared two empty lists as equal and
published an EMPTY release. Each case below runs the real script as a subprocess with a fake `gh`
first on PATH; the fake keeps the release in a JSON state file and logs every call, so "did it
reach the publish PATCH" is read from the log, not inferred from an exit code.

Cases:
  1. assemble ok + download failed (no dist/) + empty draft  -> exit 1, NO publish PATCH
  2. assemble ok + empty dist/                               -> exit 1, NO publish PATCH
  3. full manifest, vX.Y.Z                                   -> published, prerelease=false, latest
  4. full manifest, vX.Y.Z-rc.N                              -> published, prerelease=true, NOT latest
  5. one asset missing locally                               -> NO publish
  6. one extra file locally                                  -> NO publish
  7. a stale extra asset already on the draft                -> NO publish
  8. assemble failed, full dist/                             -> assets attached, NO publish
  9. one upload fails                                        -> NO publish
 10. the release is already published                        -> refused, nothing uploaded
 11. re-run onto a draft that already holds the assets       -> replaced (delete+upload), published
 12. check-dir: exact manifest passes; missing / extra fail
 13. published release is bound to its tag (the publish PATCH names it; by-tag lookup verifies)
 14. GitHub ignores tag_name -> one re-bind, then a loud failure, never a silent untagged release

Run: python3 tools/release_publish_test.py   (bare; exit 1 on failure)
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "release_publish.py"
REPO = "dp-web4/hestia"
RID = "4242"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["MOCK_GH_STATE"]
st = json.load(open(state_path))
args = sys.argv[1:]
st["calls"].append(args)
def save():
    json.dump(st, open(state_path, "w"))
if not args or args[0] != "api":
    save(); print("mock gh: only `api` is supported", file=sys.stderr); sys.exit(2)
method, endpoint, fields, inp, i = "GET", None, {}, None, 1
while i < len(args):
    a = args[i]
    if a == "-X": method = args[i + 1]; i += 2
    elif a in ("-F", "-f"):
        k, v = args[i + 1].split("=", 1)
        if a == "-F" and v.startswith("@"): v = open(v[1:]).read()
        elif a == "-F" and v in ("true", "false"): v = (v == "true")
        fields[k] = v; i += 2
    elif a == "-H": i += 2
    elif a == "--input": inp = args[i + 1]; i += 2
    else: endpoint = a; i += 1
rel = st["release"]
base = f"repos/{st['repo']}/releases/{rel['id']}"
if method == "GET" and endpoint == base:
    save(); print(json.dumps(rel)); sys.exit(0)
if method == "GET" and endpoint == f"repos/{st['repo']}/releases/tags/" + rel["tag_name"] and not rel["draft"]:
    save(); print(json.dumps(rel)); sys.exit(0)
if method == "GET" and endpoint.startswith(f"repos/{st['repo']}/releases/tags/"):
    save(); print("HTTP 404: Not Found", file=sys.stderr); sys.exit(1)
if method == "PATCH" and endpoint == base:
    # GitHub's behaviour, measured on v0.3.0-rc.1: publishing a draft without naming its tag
    # leaves the release under an `untagged-<hex>` placeholder.
    if os.environ.get("MOCK_GH_IGNORES_TAG"):
        fields = {k: v for k, v in fields.items() if k != "tag_name"}
    if fields.get("draft") is False and rel["draft"] and "tag_name" not in fields:
        rel["tag_name"] = "untagged-d4c9c308d31f0db84ef6"
    rel.update(fields); save(); print("{}"); sys.exit(0)
if method == "DELETE" and endpoint.startswith(f"repos/{st['repo']}/releases/assets/"):
    aid = int(endpoint.rsplit("/", 1)[1])
    rel["assets"] = [x for x in rel["assets"] if x["id"] != aid]; save(); sys.exit(0)
up = f"https://uploads.github.com/{base}/assets?name="
if method == "POST" and endpoint.startswith(up):
    name = endpoint[len(up):]
    if name in os.environ.get("MOCK_GH_FAIL_UPLOAD", "").split(","):
        save(); print("mock upload failure", file=sys.stderr); sys.exit(1)
    if any(x["name"] == name for x in rel["assets"]):
        save(); print("already_exists", file=sys.stderr); sys.exit(1)
    open(inp, "rb").read()
    st["next_id"] += 1
    rel["assets"].append({"id": st["next_id"], "name": name}); save(); print("{}"); sys.exit(0)
save(); print(f"mock gh: unhandled {method} {endpoint}", file=sys.stderr); sys.exit(2)
'''

sys.path.insert(0, str(HERE))
import release_publish as RP  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILS.append(name + (f"\n    {detail}" if detail else ""))


def run_case(tmp: pathlib.Path, tag: str, *, dist: str = "full", assemble: str = "success",
             draft: bool = True, remote: list[str] | None = None, kind: str | None = None,
             fail_upload: str = "", extra_local: str | None = None, drop_local: str | None = None,
             extra_env: dict | None = None):
    """Returns (exit code, final release state, calls, stdout)."""
    case = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    bindir = case / "bin"
    bindir.mkdir()
    fake = bindir / "gh"
    fake.write_text(FAKE_GH)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    d = case / "dist"
    if dist in ("full", "empty"):
        d.mkdir()
    if dist == "full":
        for n in RP.manifest(tag):
            (d / n).write_bytes(f"bytes of {n}".encode())
    if drop_local:
        (d / drop_local).unlink()
    if extra_local:
        (d / extra_local).write_text("stray")

    remote = remote or []
    state = {
        "repo": REPO, "calls": [], "next_id": 100,
        "release": {"id": int(RID), "tag_name": tag, "draft": draft, "prerelease": False,
                    "assets": [{"id": i + 1, "name": n} for i, n in enumerate(remote)]},
    }
    sp = case / "state.json"
    sp.write_text(json.dumps(state))
    notes = case / "notes.md"
    notes.write_text(f"notes for {tag}")

    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
               MOCK_GH_STATE=str(sp), GH_REPO=REPO, MOCK_GH_FAIL_UPLOAD=fail_upload,
               **(extra_env or {}))
    kind = kind or ("prerelease" if "-rc." in tag else "release")
    r = subprocess.run([sys.executable, str(SCRIPT), "publish", "--tag", tag, "--release-id", RID,
                        "--dist", str(d), "--assemble", assemble, "--notes", str(notes),
                        "--kind", kind], capture_output=True, text=True, env=env)
    final = json.loads(sp.read_text())
    return r.returncode, final["release"], final["calls"], r.stdout + r.stderr


def publish_patches(calls) -> list:
    return [c for c in calls if "-X" in c and "PATCH" in c and "draft=false" in c]


def names(rel) -> list[str]:
    return sorted(a["name"] for a in rel["assets"])


def main() -> int:
    V = "v0.3.0"
    RC = "v0.3.0-rc.1"
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)

        # 1. THE REGRESSION: assemble ok, download failed, fresh empty draft.
        rc, rel, calls, out = run_case(tmp, V, dist="none")
        check("1 download failure exits non-zero", rc != 0, out)
        check("1 download failure never reaches the publish PATCH", not publish_patches(calls), calls)
        check("1 release is still a draft", rel["draft"] is True)

        # 2. dist/ exists but is empty.
        rc, rel, calls, out = run_case(tmp, V, dist="empty")
        check("2 empty dist exits non-zero", rc != 0, out)
        check("2 empty dist never publishes", not publish_patches(calls) and rel["draft"] is True)

        # 3. full manifest, plain tag -> latest release.
        rc, rel, calls, out = run_case(tmp, V)
        check("3 full manifest publishes", rc == 0 and rel["draft"] is False, out)
        check("3 attached set is exactly the manifest", names(rel) == RP.manifest(V), names(rel))
        check("3 plain tag is not a prerelease", rel.get("prerelease") is False)
        check("3 plain tag is marked latest", rel.get("make_latest") == "true")
        check("3 manifest has 17 names (8 assets, 8 .sha256, SHA256SUMS)", len(RP.manifest(V)) == 17)

        # 4. full manifest, rc tag -> pre-release, never latest.
        rc, rel, calls, out = run_case(tmp, RC)
        check("4 rc publishes", rc == 0 and rel["draft"] is False, out)
        check("4 rc is a prerelease", rel.get("prerelease") is True)
        check("4 rc is never latest", rel.get("make_latest") == "false")
        check("4 rc asset names carry the full tag",
              all(RC in n for n in names(rel) if n != "SHA256SUMS"), names(rel))

        # 13. the published release is reachable BY ITS TAG (v0.3.0-rc.1 shipped as untagged-<hex>).
        for tag in (V, RC):
            rc, rel, calls, out = run_case(tmp, tag)
            check(f"13 {tag} publish PATCH names the tag",
                  any(f"tag_name={tag}" in c for c in publish_patches(calls)), calls)
            check(f"13 {tag} published release keeps its tag", rel["tag_name"] == tag, rel["tag_name"])
            check(f"13 {tag} verified by the by-tag lookup",
                  any(c[-1].endswith(f"/releases/tags/{tag}") for c in calls), calls)
        # 14. GitHub drops tag_name from every PATCH -> re-bind once -> still unbound -> loud failure.
        rc, rel, calls, out = run_case(tmp, V, extra_env={"MOCK_GH_IGNORES_TAG": "1"})
        check("14 an unbindable publish fails loudly", rc != 0 and "NOT bound to its tag" in out, out)

        # 5-7. missing / extra / stale assets block.
        rc, rel, calls, out = run_case(tmp, V, drop_local=f"hestia-app-{V}-android-universal.apk")
        check("5 a missing asset blocks publish", rc != 0 and not publish_patches(calls), out)
        rc, rel, calls, out = run_case(tmp, V, extra_local="hestia-app-v0.3.0-x86_64-linux.rpm")
        check("6 an extra local file blocks publish", rc != 0 and not publish_patches(calls), out)
        rc, rel, calls, out = run_case(tmp, V, remote=["hestia-v0.2.9-x86_64-unknown-linux-gnu.tar.gz"])
        check("7 a stale asset on the draft blocks publish", rc != 0 and not publish_patches(calls), out)

        # 8. assemble failed: attach for inspection, never publish.
        rc, rel, calls, out = run_case(tmp, V, assemble="failure")
        check("8 assemble failure exits non-zero", rc != 0, out)
        check("8 assemble failure never publishes", not publish_patches(calls) and rel["draft"] is True)
        check("8 assets were still attached to the draft", names(rel) == RP.manifest(V), names(rel))

        # 9. an upload fails.
        rc, rel, calls, out = run_case(tmp, V, fail_upload=f"hestia-app-{V}-x86_64-linux.deb")
        check("9 a failed upload blocks publish", rc != 0 and not publish_patches(calls), out)

        # 10. already published: refuse, touch nothing.
        rc, rel, calls, out = run_case(tmp, V, draft=False)
        check("10 a published release is refused", rc != 0, out)
        check("10 nothing was patched or uploaded",
              not any("PATCH" in c or "POST" in c for c in calls), calls)

        # 11. re-run onto a draft holding every asset: replace, then publish.
        rc, rel, calls, out = run_case(tmp, V, remote=RP.manifest(V))
        check("11 re-run replaces and publishes", rc == 0 and rel["draft"] is False, out)
        check("11 re-run deleted each old asset first",
              sum(1 for c in calls if "DELETE" in c) == 17, calls)
        check("11 attached set is exactly the manifest", names(rel) == RP.manifest(V), names(rel))

        # 12. check-dir.
        d = tmp / "cd"
        d.mkdir()
        for n in RP.manifest(V):
            (d / n).write_text("x")
        check("12 check-dir passes the exact manifest", RP.cmd_check_dir(d, V) == 0)
        (d / "extra.txt").write_text("x")
        check("12 check-dir fails an extra file", RP.cmd_check_dir(d, V) == 1)
        (d / "extra.txt").unlink()
        (d / "SHA256SUMS").unlink()
        check("12 check-dir fails a missing SHA256SUMS", RP.cmd_check_dir(d, V) == 1)
        check("12 check-dir fails a missing dir", RP.cmd_check_dir(tmp / "nope", V) == 1)

    for f in FAILS:
        print("FAIL", f)
    print(f"release_publish: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
