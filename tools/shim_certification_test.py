"""Falsifiers for tools/shim_certification.py. Run directly by CI."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("shim_certification", HERE / "shim_certification.py")
assert SPEC and SPEC.loader
sc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sc)

SEATS = sc.REPO_SHIMS
RUNTIME = ("hestia_single_gate.py", "hestia_gate_core.py")


def fixture():
    td = tempfile.TemporaryDirectory()
    root = Path(td.name) / "repo"
    home = Path(td.name) / "home"
    shared = root / "plugins" / "_shared"
    deployed = home / "shared"
    shared.mkdir(parents=True)
    deployed.mkdir(parents=True)
    (shared / "RUNTIME_MANIFEST.txt").write_text("\n".join(RUNTIME) + "\n", encoding="utf-8")
    # The tool reads its three certification scalars out of the canonical template rather
    # than redeclaring them, so a fixture repo needs one. Deliberately NOT the production
    # values: a test that reuses them would pass even if the binding were removed.
    template = root / "plugins" / "_template" / "shim_template.py"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        'SHIM_CERTIFICATION_SCHEMA = "fixture-schema/v9"\n'
        'CERTIFICATION_CRITERIA = "FIXTURE_CRITERIA.md@1970-01-01"\n'
        'REQUIRED_GATE_API = "fixture/0"\n'
        'PERMITTED_FUNCTIONS = ("main",)\n', encoding="utf-8")
    # The criteria document the label names. Its BYTES are in the preimage, so the fixture
    # needs a real one -- the label alone is not what the digest commits to.
    criteria = root / "docs" / "FIXTURE_CRITERIA.md"
    criteria.parent.mkdir(parents=True, exist_ok=True)
    criteria.write_text("# fixture criteria\nrule one\n", encoding="utf-8")
    for name in RUNTIME:
        payload = f"# {name}\nVALUE = 1\n"
        (shared / name).write_text(payload, encoding="utf-8")
        (deployed / name).write_text(payload, encoding="utf-8")
    for seat, parts in SEATS.items():
        repo_shim = root / "plugins" / Path(*parts)
        repo_shim.parent.mkdir(parents=True, exist_ok=True)
        repo_shim.write_text(f"# {seat}\nPROFILE = {{}}\n", encoding="utf-8")
        dep_parts = sc.DEPLOYED_SHIMS[seat]
        # Rebase the declared ~/. paths under the fixture home.
        rel = Path(*dep_parts[1:])
        dep_shim = home.parent / rel if dep_parts[0] != "~" else Path(td.name) / "user" / rel
        # The module uses expanduser, so HOME must point at this user dir.
        user = Path(td.name) / "user"
        dep_shim = user / rel
        dep_shim.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_shim, dep_shim)
    return td, root, home, Path(td.name) / "user"


def with_fixture(fn):
    td, root, home, user = fixture()
    old = dict(os.environ)
    try:
        os.environ["HESTIA_REPO_ROOT"] = str(root)
        os.environ["HESTIA_HOME"] = str(home)
        os.environ["HOME"] = str(user)
        fn(root, home, user)
    finally:
        os.environ.clear(); os.environ.update(old)
        td.cleanup()


def test_identical_repo_and_deployed_subject_match():
    def run(_root, _home, _user):
        for seat in SEATS:
            assert sc.certification(seat, False)["certification_sha256"] == \
                   sc.certification(seat, True)["certification_sha256"]
    with_fixture(run)


def test_runtime_mutation_invalidates_every_seat_without_changing_shim():
    def run(_root, home, _user):
        before = {s: sc.certification(s, True) for s in SEATS}
        (home / "shared" / RUNTIME[0]).write_text("VALUE = 2\n", encoding="utf-8")
        after = {s: sc.certification(s, True) for s in SEATS}
        for seat in SEATS:
            assert before[seat]["shim_sha256_raw"] == after[seat]["shim_sha256_raw"]
            assert before[seat]["certification_sha256"] != after[seat]["certification_sha256"]
    with_fixture(run)


def test_missing_runtime_is_unknown_not_a_shorter_hash():
    def run(_root, home, _user):
        (home / "shared" / RUNTIME[1]).unlink()
        try:
            sc.certification("codex", True)
        except sc.Unknown:
            return
        raise AssertionError("missing runtime must not produce a certification")
    with_fixture(run)


def test_unset_home_is_unknown_not_a_guessed_root():
    """The verifier must never invent an installation root. It used to default to
    `~/.hestia`, which lets it report MATCHED about a tree the caller never named — the
    #944 class, and worse here than in a seat, because this tool's entire product is the
    claim that a SPECIFIC installation is the certified one."""
    def run(_root, _home, _user):
        os.environ.pop("HESTIA_HOME", None)
        sc._HOME_OVERRIDE = None
        try:
            sc.certification("codex", True)
        except sc.Unknown as exc:
            assert "no default" in str(exc), exc
            return
        raise AssertionError("unset HESTIA_HOME produced a certification instead of UNKNOWN")
    with_fixture(run)


def test_home_override_is_used_when_the_environment_is_unset():
    def run(_root, home, _user):
        os.environ.pop("HESTIA_HOME", None)
        sc._HOME_OVERRIDE = str(home)
        try:
            assert sc.certification("codex", True)["runtime_dir"] == str(home / "shared")
        finally:
            sc._HOME_OVERRIDE = None
    with_fixture(run)


def test_scalars_come_from_the_template_not_a_second_copy():
    """Binding, not duplication: change the template's scalars and the subject must move.
    If the tool re-declared them, this assertion could not fail."""
    def run(root, _home, _user):
        assert sc.canonical_scalars()["SCHEMA"] == "fixture-schema/v9"
        before = sc.certification("codex", False)["certification_sha256"]
        tmpl = root / "plugins" / "_template" / "shim_template.py"
        tmpl.write_text(tmpl.read_text(encoding="utf-8")
                        .replace("fixture-schema/v9", "fixture-schema/v10"), encoding="utf-8")
        after = sc.certification("codex", False)
        assert after["schema"] == "fixture-schema/v10"
        assert after["certification_sha256"] != before, \
            "the certification subject ignored a change to the canonical schema"
    with_fixture(run)


def test_prd_enumeration_matches_the_permitted_tuple():
    """The PRD says 'the tuple decides' and then enumerates the tuple in prose. It has
    drifted twice: once before harvest (its own note) and once at harvest, where it still
    named _shared_runtime_dir, _load_shared_module, _emergency_refuse and
    _read_harness_input. Prose cannot be kept in step by intention, so it is pinned here."""
    import ast
    import re
    repo = Path(__file__).resolve().parents[1]
    tmpl = repo / "plugins" / "_template" / "shim_template.py"
    permitted = set()
    for node in ast.parse(tmpl.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "PERMITTED_FUNCTIONS" for t in node.targets):
            permitted = {e.value for e in ast.walk(node)
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    assert permitted, "template declares no PERMITTED_FUNCTIONS"

    prd = (repo / "docs" / "PRD_SHIM_CERTIFICATION.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*\d+\s*\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|", prd, re.M)
    assert rows, "PRD has no numbered function table to check"
    assert set(rows) == permitted, (
        f"PRD table and PERMITTED_FUNCTIONS disagree: "
        f"only in PRD={sorted(set(rows) - permitted)}, "
        f"only in template={sorted(permitted - set(rows))}")


def test_changing_only_the_criteria_moves_the_certification():
    """The hole this closes: the preimage used to carry the criteria LABEL and nothing
    else, so the normative document could be rewritten while every certification digest
    stayed byte-for-byte identical. It demonstrably did -- the criteria changed four times
    on 2026-09-22 under a label reading `@2026-09-04`, and no digest moved.

    Certification means review against *this version of these criteria*. If the criteria
    can change without the subject changing, the digest certifies against a name, not a
    standard."""
    def run(root, _home, _user):
        before = {s: sc.certification(s, False)["certification_sha256"] for s in SEATS}
        doc = root / "docs" / "FIXTURE_CRITERIA.md"
        doc.write_text(doc.read_text(encoding="utf-8") + "rule two\n", encoding="utf-8")
        after = {s: sc.certification(s, False) for s in SEATS}
        for seat in SEATS:
            assert after[seat]["certification_sha256"] != before[seat], (
                f"{seat}: the criteria document changed and the certification did not")
        # The label did NOT change, which is exactly the case that used to slip through.
        assert after["codex"]["criteria"] == "FIXTURE_CRITERIA.md@1970-01-01"
    with_fixture(run)


def test_missing_criteria_document_is_unknown():
    """A label naming a document that is not there must not certify. Silence here would
    reintroduce the same hole by a different route."""
    def run(root, _home, _user):
        (root / "docs" / "FIXTURE_CRITERIA.md").unlink()
        try:
            sc.certification("codex", False)
        except sc.Unknown:
            return
        raise AssertionError("a missing criteria document still produced a certification")
    with_fixture(run)


def _template_tuples():
    import ast
    repo = Path(__file__).resolve().parents[1]
    tmpl = repo / "plugins" / "_template" / "shim_template.py"
    out = {}
    for node in ast.parse(tmpl.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, "id", None)
            if name in ("PERMITTED_FUNCTIONS", "BYTE_IDENTICAL_FUNCTIONS",
                        "ADAPTER_FUNCTIONS"):
                out[name] = {e.value for e in ast.walk(node)
                             if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out, repo


def test_prd_kinds_match_the_byte_identical_tuple():
    """The names drifted, and the KIND column drifted a step longer — correcting the names
    alone left `_emergency_block` and `main` marked per-seat, which inverts C4's split from
    5/3 to 3/5. C4 is the normative certification rule, so the classification is pinned as
    hard as the enumeration."""
    import re
    tup, repo = _template_tuples()
    identical, adapters = tup["BYTE_IDENTICAL_FUNCTIONS"], tup["ADAPTER_FUNCTIONS"]
    assert identical | adapters == tup["PERMITTED_FUNCTIONS"], \
        "the template's own two tuples do not partition PERMITTED_FUNCTIONS"
    assert not (identical & adapters), "a function is declared both byte-identical and adapter"

    prd = (repo / "docs" / "PRD_SHIM_CERTIFICATION.md").read_text(encoding="utf-8")
    claimed = {}
    for name, kind in re.findall(
            r"^\|\s*\d+\s*\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|([^|]*)\|", prd, re.M):
        claimed[name] = "byte-identical" in kind
    for fn in sorted(identical):
        assert claimed.get(fn) is True, \
            f"PRD calls {fn} per-seat; the template declares it byte-identical"
    for fn in sorted(adapters):
        assert claimed.get(fn) is False, \
            f"PRD calls {fn} byte-identical; the template declares it an adapter"


def test_c4_counts_match_the_template():
    """C4 states the split in words ('Five of them ... The other three'). Words and tuples
    are two copies of one fact, so they are checked against each other."""
    import re
    tup, repo = _template_tuples()
    prd = (repo / "docs" / "PRD_SHIM_CERTIFICATION.md").read_text(encoding="utf-8")
    section = prd.split("### C4")[1].split("###")[0]
    words = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}

    m = re.search(r"\*\*(\w+)\*\* of them", section) or re.search(r"(\w+) of them", section)
    assert m, "C4 no longer states how many functions are byte-identical"
    assert words.get(m.group(1).lower()) == len(tup["BYTE_IDENTICAL_FUNCTIONS"]), (
        f"C4 says {m.group(1)!r} byte-identical; the template declares "
        f"{len(tup['BYTE_IDENTICAL_FUNCTIONS'])}")

    m = re.search(r"other \*\*(\w+)\*\*", section) or re.search(r"other (\w+)", section)
    assert m, "C4 no longer states how many functions are adapters"
    assert words.get(m.group(1).lower()) == len(tup["ADAPTER_FUNCTIONS"]), (
        f"C4 says {m.group(1)!r} adapters; the template declares "
        f"{len(tup['ADAPTER_FUNCTIONS'])}")

    for fn in tup["BYTE_IDENTICAL_FUNCTIONS"]:
        assert f"`{fn}`" in section, f"C4 does not name {fn} among the byte-identical set"
    # GPT's cleanup on #1104: the first version of this arm checked the five identical
    # names and left the three adapter names unchecked -- half the split unpinned, which is
    # the same half-a-fix shape as the kind column.
    for fn in tup["ADAPTER_FUNCTIONS"]:
        assert f"`{fn}`" in section, f"C4 does not name {fn} among the adapters"


TESTS = [
    test_identical_repo_and_deployed_subject_match,
    test_runtime_mutation_invalidates_every_seat_without_changing_shim,
    test_missing_runtime_is_unknown_not_a_shorter_hash,
    test_unset_home_is_unknown_not_a_guessed_root,
    test_home_override_is_used_when_the_environment_is_unset,
    test_scalars_come_from_the_template_not_a_second_copy,
    test_prd_enumeration_matches_the_permitted_tuple,
    test_prd_kinds_match_the_byte_identical_tuple,
    test_c4_counts_match_the_template,
    test_changing_only_the_criteria_moves_the_certification,
    test_missing_criteria_document_is_unknown,
]

if __name__ == "__main__":
    declared = {n for n, v in globals().items() if n.startswith("test_") and callable(v)}
    listed = {fn.__name__ for fn in TESTS}
    assert declared == listed, f"TESTS drift: declared={declared} listed={listed}"
    for test in TESTS:
        test()
    print(f"OK - {len(TESTS)} shim certification tests")
