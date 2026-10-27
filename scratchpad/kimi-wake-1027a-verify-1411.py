#!/usr/bin/env python3
"""Wake 2026-10-27 (a): verification behind my factor on escalation e944fe97a373ef06
(#1411 existence-first, held patch e1b2dba5 — APPROVED by operator 01:01:52Z over
codex's dissent; applied in the s1411w worktree between my read and now).

The applied working tree IS the post-image, so verification reads it directly
(read-only, witnessed): no git apply, no writes to marker paths. The module under
test is exec'd from the bytes read; fixtures live under scratchpad and are removed.

  H1 sha256(plugins/_shared/hestia_gate_core.py) == c05eefac... (the manifest bind)
  H2 hooks-gt mirror differs from source at exactly the header sha line, naming it
  H3 all 5 applied manifests: content address (tools/hooks_gt.py _version) ==
     claimed gt_version == the value the held patch wrote
  H4 the applied test_gate_core.py suite passes against the applied core
  B1 codex dissent case 1: exact path grant -> hint names an uncovered descendant
  B2 codex dissent case 2: recursive grant + escaping symlink -> hint names an
     out-of-grant (realpath) path
  B3 positive control: genuine in-grant doubled-root candidate -> hint correct
  B4 feature shape: nonexistent read -> mrh.path.nonexistent; existing oos read ->
     mrh.path; in-scope read -> allow; nonexistent oos WRITE -> still mrh.path
"""
import hashlib, json, os, shutil, sys, types

REPO = "/home/dp/ai-workspace/hestia"
W = os.path.join(REPO, "scratchpad/s1411w")
FIX = os.path.join(REPO, "scratchpad/kimi-1411-review/fixtures")

EXPECTED_CORE_SHA = "c05eefac928759cb0f3a3d41d63754ab2480fd35d7fae52747b6232a23b44f3d"
EXPECTED_GT = {
    "hooks-gt/_shared/manifest.json": "64953bc6de401c6e5a36d629a52c99a9e6094d670780856bb3c1403447943fbb",
    "hooks-gt/claude-code/manifest.json": "1f081f15b1f5db86026e57d6acbbd5d7ae18a1b36652076d7f7b536fca23b18f",
    "hooks-gt/codex/manifest.json": "d6f462ee6c07ecb245922b963d392722db893596296785a2a73b65fe07ce88a9",
    "hooks-gt/gemini/manifest.json": "d4b8bcc247658a10edddb807ce1495328e84539b8b3e779faf2479b840755e96",
    "hooks-gt/kimi/manifest.json": "0266246a9c61625fa8dd18d4f6f41449cb96f3fed7d74e2750961e46dac11e04",
}

report = {"checks": {}, "detail": {}}
core_src = open(os.path.join(W, "plugins/_shared/hestia_gate_core.py"), encoding="utf-8").read()
mirror_src = open(os.path.join(W, "hooks-gt/_shared/hestia_gate_core.py"), encoding="utf-8").read()

core_sha = hashlib.sha256(core_src.encode()).hexdigest()
report["checks"]["H1_core_sha_matches_manifest"] = core_sha == EXPECTED_CORE_SHA

s_lines, m_lines = core_src.split("\n"), mirror_src.split("\n")
report["detail"]["mirror_len_delta"] = len(m_lines) - len(s_lines)
report["detail"]["mirror_header_line"] = m_lines[1][:120]
report["checks"]["H2_mirror_header_names_new_sha_only_diff"] = (
    len(m_lines) == len(s_lines) + 1
    and m_lines[0] == s_lines[0]
    and EXPECTED_CORE_SHA in m_lines[1]
    and m_lines[2:] == s_lines[1:])


def content_address(text):
    body = json.loads(text)
    claimed = body.get("gt_version")
    b = {k: v for k, v in body.items() if k != "gt_version"}
    return claimed, hashlib.sha256(
        json.dumps(b, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


h3 = {}
for mpath, expect in EXPECTED_GT.items():
    claimed, recomputed = content_address(
        open(os.path.join(W, mpath), encoding="utf-8").read())
    h3[mpath] = {"claimed": claimed[:12], "self_consistent": claimed == recomputed,
                 "matches_held_patch": claimed == expect}
rows = json.loads(open(os.path.join(W, "hooks-gt/_shared/manifest.json"),
                       encoding="utf-8").read())["files"]
row = [r for r in rows if r["path"] == "hestia_gate_core.py"][0]
report["checks"]["H3_manifests_self_consistent_and_match_patch"] = all(
    v["self_consistent"] and v["matches_held_patch"] for v in h3.values())
report["checks"]["H3b_manifest_binds_applied_core"] = row["sha256"] == EXPECTED_CORE_SHA
report["detail"]["manifests"] = h3

G = types.ModuleType("hestia_gate_core")
G.__file__ = "<applied-in-s1411w-read-only>"
sys.modules["hestia_gate_core"] = G
exec(compile(core_src, G.__file__, "exec"), G.__dict__)

# H4: the applied suite, imported from memory; failures exit(1) -> catch
test_src = open(os.path.join(W, "plugins/_shared/test_gate_core.py"), encoding="utf-8").read()
tmod = types.ModuleType("tgc_applied")
tmod.__file__ = os.path.join(REPO, "scratchpad/kimi-1411-review/tgc_applied.py")
try:
    exec(compile(test_src, tmod.__file__, "exec"), tmod.__dict__)
    report["checks"]["H4_applied_suite_passes"] = True
except SystemExit as e:
    report["checks"]["H4_applied_suite_passes"] = (e.code == 0)
    report["detail"]["H4_failures"] = [str(f)[:200] for f in tmod.__dict__.get("FAILURES", [])]
except Exception as e:  # environmental failure is NOT a pass
    report["checks"]["H4_applied_suite_passes"] = False
    report["detail"]["H4_error"] = repr(e)[:400]

shutil.rmtree(FIX, ignore_errors=True)
ws = os.path.join(FIX, "ws")
os.makedirs(ws)


def profile(tmp, scope):
    p = os.path.join(tmp, "identity.json")
    mrh = {"in_scope": scope,
           "replica": {"generation": 1, "expires_at": G.now_secs() + 3600}}
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"mrh": mrh, "role": "role:constellation:member"}, fh)
    return G.HarnessProfile(member_id="kimi-review", identity_path=p,
                            home_markers=("~/.kimi-review",))


root1 = os.path.join(ws, "governance")
os.makedirs(root1)
open(os.path.join(root1, "child.txt"), "w").close()
scopes1 = ["path:" + root1]
target1 = os.path.join(ws, "hestia", "governance", "child.txt")
hint1 = G._did_you_mean(target1, scopes1, ws)
cand1 = root1 + "/child.txt"
covered1 = G._within_path_grant(cand1, scopes1, ws)
v1 = G.evaluate(G.NormalizedEvent(tool="Read", paths=[cand1], cwd=ws),
                profile(ws, scopes1), ws)
report["detail"]["B1"] = {"hint": hint1, "candidate_covered_by_grant": covered1,
                          "read_of_candidate": {"rule": v1.rule, "blocks": v1.blocks}}
report["checks"]["B1_exact_grant_hint_names_uncovered_path"] = bool(hint1) and not covered1

outside = os.path.join(FIX, "outside")
os.makedirs(outside)
open(os.path.join(outside, "note.txt"), "w").close()
root2 = os.path.join(ws, "g2")
os.makedirs(root2)
os.symlink(outside, os.path.join(root2, "link"))
scopes2 = ["path:" + root2 + "/**"]
target2 = os.path.join(ws, "hestia", "g2", "link", "note.txt")
hint2 = G._did_you_mean(target2, scopes2, ws)
cand2 = root2 + "/link/note.txt"
covered2 = G._within_path_grant(cand2, scopes2, ws)
report["detail"]["B2"] = {"hint": hint2, "candidate_covered_by_grant": covered2,
                          "cand_realpath": os.path.realpath(cand2)}
report["checks"]["B2_symlink_hint_names_out_of_grant_path"] = bool(hint2) and not covered2

root3 = os.path.join(ws, "g3")
os.makedirs(os.path.join(root3, "sub"))
open(os.path.join(root3, "sub", "real.md"), "w").close()
scopes3 = ["path:" + root3 + "/**"]
target3 = os.path.join(ws, "hestia", "g3", "sub", "real.md")
hint3 = G._did_you_mean(target3, scopes3, ws)
covered3 = G._within_path_grant(root3 + "/sub/real.md", scopes3, ws)
report["detail"]["B3"] = {"hint": hint3, "candidate_covered_by_grant": covered3}
report["checks"]["B3_genuine_candidate_hint_correct"] = bool(hint3) and covered3

os.makedirs(os.path.join(ws, "granted"))
open(os.path.join(ws, "granted", "a.md"), "w").close()
os.makedirs(os.path.join(ws, "notgranted"))
open(os.path.join(ws, "notgranted", "a.md"), "w").close()
prof = profile(ws, ["repo:granted"])


def ev(tool, path):
    return G.evaluate(G.NormalizedEvent(tool=tool, paths=[path], cwd=ws), prof, ws)


b4 = {
    "read_nonexistent_oos": (lambda v: {"rule": v.rule, "blocks": v.blocks,
                                        "remedy": v.remedy})(
        ev("Read", os.path.join(ws, "missing", "none.md"))),
    "read_existing_oos": (lambda v: {"rule": v.rule, "blocks": v.blocks})(
        ev("Read", os.path.join(ws, "notgranted", "a.md"))),
    "read_in_scope": (lambda v: {"decision": v.decision})(
        ev("Read", os.path.join(ws, "granted", "a.md"))),
    "write_nonexistent_oos": (lambda v: {"rule": v.rule, "blocks": v.blocks})(
        ev("Write", os.path.join(ws, "notgranted", "new.md"))),
}
report["detail"]["B4"] = b4
report["checks"]["B4_feature_shape"] = (
    b4["read_nonexistent_oos"]["rule"] == "mrh.path.nonexistent"
    and b4["read_nonexistent_oos"]["blocks"]
    and b4["read_existing_oos"]["rule"] == "mrh.path"
    and b4["read_in_scope"]["decision"] == "allow"
    and b4["write_nonexistent_oos"]["rule"] == "mrh.path"
    and b4["write_nonexistent_oos"]["blocks"])

shutil.rmtree(FIX, ignore_errors=True)
print(json.dumps({"checks": report["checks"], "detail": report["detail"]},
                 indent=1, default=str))
