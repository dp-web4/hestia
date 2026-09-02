#!/usr/bin/env python3
"""Which tool arguments carry a path that NO gate is scoping?

Every gate decides reach by first extracting "the paths this call touches" from the tool
input. That extraction is a hard-coded list of argument KEY NAMES -- `path_targets` in three
seats, six separate literal re-spellings of the same tuple inside claude-code's gate. A path
that arrives under a key the list does not name is not denied; it is not seen. The scope
check runs, finds nothing to check, and the call is ALLOWED.

That is a fail-OPEN, and it is invisible to every instrument we have: the meter counts
duplicated code, the differential compares predicates on inputs someone thought to write
down, and neither can notice a key nobody enumerated. This probe measures it from the wild
instead -- real tool calls in the local transcripts -- and asks one question per call:

  Does this call carry a filesystem-path-looking value under a key its own seat's gate does
  not enumerate?

A non-zero answer is not a hypothetical. It is a list of calls whose reach was never checked.

## What counts as a path-looking value

Deliberately CONSERVATIVE, because the interesting number is a floor. A value counts only if
it is a string that starts with `/`, `~/`, or `./`, or contains a `/` and resolves to
something that exists on this box. A bare `foo.py`, a URL, and a regex do not count. That
undercounts -- a relative path that no longer exists is a real unscoped reach and is dropped
here -- and undercounting is the right direction for a claim that something is unguarded.

## What counts as enumerated

The key lists are read from the gate SOURCES, not restated here: every string constant in
each seat's `path_targets` (or, for claude-code, every tuple of key names literally spelled
beside a `tool_input.get`). Restating them would let this probe drift from the gates it is
about, which is the same defect it exists to find. `--show-keys` prints what it read.

Exit 0 always. This reports a population; it does not gate.
"""

import argparse
import ast
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_collapse_meter import discover_gates, repo_root  # noqa: E402

# Keys whose values are paths but which are NOT reach: the gate reads them for other
# reasons, or they name a location the harness itself chose rather than one the member
# asked for. Listed rather than silently skipped so the exclusion can be argued with.
NOT_REACH = {
    "cwd",          # the harness's own working directory, not a target the member named
    "gate_path",    # the gate naming itself in its own witness payload
    # SCOPED BY A DIFFERENT DOOR, not unscoped. Every gate routes `command` through command
    # scoping (`command_in_scope`) rather than path scoping, so a path inside a Bash command
    # is checked -- by other code, with its own defects, measured elsewhere. Counting it here
    # would inflate this number with calls that are in fact guarded, and the point of the
    # number is that the calls it counts are NOT.
    "command",
    # CONTENT, not reach. `old_string`/`new_string`/`content` are the bytes being written,
    # and a source file legitimately contains path-looking lines (`/* -- Mobile -- */`, a
    # doc comment naming a directory). The gate reads them for content matching. Scoring
    # them as unscoped reach put 22 calls in the first run of this probe that were nothing
    # of the kind.
    "old_string", "new_string", "content",
}

# Characters that appear in code, regexes and prose but not in a filesystem path a member
# would name. A value carrying any of them is not counted, which drops real paths embedded in
# sentences too -- the number is a floor and this keeps it one.
_NOT_IN_A_PATH = set(" \t|\\$`<>\"'")

_PATHISH = re.compile(r"^(/|~/|\./|\.\./)")


def is_pathish(v) -> bool:
    if not isinstance(v, str) or not v.strip() or len(v) > 4096:
        return False
    if _NOT_IN_A_PATH & set(v):
        return False
    if _PATHISH.match(v):
        # Two segments minimum. A lone `/i` (the tail of a regex literal) or `./` is not a
        # reach anyone could act on, and counting it would put regex flags in a security
        # finding -- which the first run of this probe did.
        return len([s for s in v.split("/") if s]) >= 2
    # A bare relative path counts only if it actually exists -- see the docstring: this is a
    # floor, and "looks like it could be a path" is how a probe starts inventing findings.
    return "/" in v and not v.startswith(("http://", "https://")) and os.path.exists(v)


def keys_from_path_targets(path: Path):
    """Every string constant inside a top-level `path_targets`, if the module has one."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "path_targets":
            return {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return None


def keys_from_get_literals(path: Path, anchor):
    """Fallback for a gate with no `path_targets`: the key TUPLES it walks for a path.

    claude-code has no such function -- it re-spells the same three-key tuple in six places
    and also keeps a `_PATH_KEYS` constant that most of those six do not use. Reading the
    tuples is how this probe reports what that gate ACTUALLY enumerates rather than what its
    constant claims.

    Only GROUPED spellings count: a tuple iterated over `tool_input`, an `or`-chain of
    `tool_input.get(...)`, or a `*PATH_KEYS*` constant. A lone `tool_input.get("command")`
    does NOT -- the gate reads `command`, `content`, `old_string` and `new_string` for
    content matching, not for reach, and folding those in would report a path vocabulary
    four keys wider than the one the scope check actually uses. Being wrong in the
    flattering direction is the failure mode this whole line of work exists to catch.

    A group is kept only if it contains at least one ANCHOR key -- a key every gate that
    declares a real `path_targets` agrees is a path. That rule is derived from the other
    gates' own declarations rather than written down here, so this probe cannot drift from
    them independently. It mis-reads exactly one shape: a group that MIXES an anchor key
    with a non-path key. Those are printed, not silently folded in.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    keys = set()
    mixed = []

    def literals(seq):
        return {e.value for e in seq
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}

    def keep(group, lineno):
        if not group or not (group & anchor):
            return
        if group - anchor - keys:
            mixed.append((lineno, sorted(group)))
        keys.update(group)

    for node in ast.walk(tree):
        # for k in ("a", "b"): ... tool_input.get(k)  /  [x[k] for k in (...)]
        if isinstance(node, (ast.For, ast.comprehension)):
            it = node.iter
            if isinstance(it, (ast.Tuple, ast.List)) and "tool_input" in ast.dump(node):
                keep(literals(it.elts), getattr(it, "lineno", 0))
        # tool_input.get("a") or tool_input.get("b") or ...
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            got = set()
            for v in node.values:
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) \
                        and v.func.attr == "get" and v.args \
                        and isinstance(v.args[0], ast.Constant) \
                        and isinstance(v.func.value, ast.Name) \
                        and v.func.value.id == "tool_input":
                    got |= literals(v.args[:1])
            if len(got) > 1:
                keep(got, getattr(node, "lineno", 0))
        # _PATH_KEYS = ("a", "b", ...)
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List)):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any("PATH_KEYS" in n.upper() for n in names):
                keep(literals(node.value.elts), getattr(node, "lineno", 0))
    return keys, mixed


def engine_reach_keys(root: Path):
    """The engine's declared (tool, key) reach table, flattened to key names (slice 5).

    Read from the AST of the shipped core, never hardcoded here: a probe that carried its
    own copy of the table would be the drift it measures. Returns None when the core does
    not declare the table (a pre-slice-5 tree)."""
    core = root / "plugins" / "_shared" / "hestia_gate_core.py"
    try:
        tree = ast.parse(core.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List)):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = {e.value for e in node.value.elts
                                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    if "PATH_KEYS" not in consts or "PATTERN_REACH_TOOLS" not in consts:
        return None
    keys = set()
    for name in ("PATH_KEYS", "PATH_LIST_KEYS", "GLOB_KEYS"):
        keys |= consts.get(name, set())
    return keys | {"pattern"}


def _is_engine_path_targets_call(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "path_targets"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "_core")


def live_site_delegates(path: Path) -> bool:
    """Does the seat's LIVE scope-extraction site consume the engine table?

    Not "does the source mention `_core.path_targets(` somewhere" -- GPT's review of #830
    falsified that in one move: a seat-local 3-key extractor on the real path plus one dead
    engine call elsewhere read as fully delegated. The proof is structural, at the site
    that feeds scope: the value bound to the paths the scope check judges must BE the engine
    call, every seat-local `path_targets`/`_path_targets` definition is gone, and no other
    binding of that name on the live path comes from anywhere else.

    Live sites, by seat shape:
      - a `NormalizedEvent(... paths=<expr> ...)` keyword (claude-code)
      - an assignment `paths = <expr>` inside main() (codex, kimi, gemini)

    Every such binding must CONTAIN the engine call, and every other callee in it must be a
    pure harness-shape translator: a local function that names NO path key (codex's
    apply_patch_targets parses file targets out of a diff body -- event shape a shim may
    translate -- and is composed with the engine call at the site). A callee that spells a
    key name is a second domain and reads as a re-fork, whatever it is called."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    local_fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if any(n in local_fns for n in ("path_targets", "_path_targets")):
        return False
    # path is plugins/<seat>/hooks/<file>; the repo root is three levels up. A fixture
    # outside any tree keeps the classic three names, which is enough to catch a re-fork.
    parents = path.resolve().parents
    root_keys = engine_reach_keys(parents[3]) if len(parents) > 3 else None
    key_names = set(root_keys or set()) | {"file_path", "path", "notebook_path"}
    bindings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "NormalizedEvent":
            for kw in node.keywords:
                if kw.arg == "paths":
                    bindings.append(kw.value)
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id in ("paths", "_paths") for t in node.targets):
                bindings.append(node.value)
    if not bindings:
        return False
    for expr in bindings:
        calls = [c for c in ast.walk(expr) if isinstance(c, ast.Call)]
        if not any(_is_engine_path_targets_call(c) for c in calls):
            return False                       # a binding with no engine call: re-fork
        for c in calls:
            if _is_engine_path_targets_call(c):
                continue
            name = getattr(c.func, "id", None)
            fn = local_fns.get(name)
            if fn is None:
                return False                   # an unknown callee cannot be proven a translator
            spelled = {k.value for k in ast.walk(fn)
                       if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if spelled & key_names:
                return False                   # the callee spells a path key: a second domain
    return True


def gate_key_vocabularies(root: Path):
    gates, unclassified = discover_gates(root)
    if unclassified:
        raise SystemExit(f"UNCLASSIFIED hook module(s): {unclassified}")
    vocab = {}
    declared = {}
    engine_keys = engine_reach_keys(root)
    for seat, path in gates:
        # A seat whose LIVE extraction site is the engine call consumes the engine table by
        # construction (slice 5): its vocabulary IS the table. Proven at the site, not by a
        # substring (see live_site_delegates). The flat key census below is a trend, not the
        # contract: the typed (tool, key) behaviour is pinned by
        # tools/reach_domain_contract_test.py, which can turn red where this cannot.
        if engine_keys is not None and live_site_delegates(path):
            declared[seat] = engine_keys
            vocab[seat] = {"keys": {k for k in engine_keys if k not in NOT_REACH},
                           "source": "engine reach table (delegated)", "path": path, "mixed": []}
            continue
        keys = keys_from_path_targets(path)
        if keys is not None:
            declared[seat] = keys
            vocab[seat] = {"keys": {k for k in keys if k not in NOT_REACH},
                           "source": "path_targets", "path": path, "mixed": []}
    if not declared:
        raise SystemExit("no gate declares path_targets -- the anchor cannot be derived")
    # The anchor is what every DECLARING gate agrees is a path key. Derived, never written.
    anchor = set.intersection(*declared.values())
    for seat, path in gates:
        if seat in vocab:
            continue
        keys, mixed = keys_from_get_literals(path, anchor)
        vocab[seat] = {"keys": {k for k in keys if k not in NOT_REACH},
                       "source": f"grouped tool_input reads anchored on {sorted(anchor)}",
                       "path": path, "mixed": mixed}
    return vocab


def iter_tool_uses(transcripts):
    for t in transcripts:
        try:
            with open(t, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    msg = rec.get("message") or {}
                    for block in (msg.get("content") or []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            yield t, block.get("name"), block.get("input")
        except OSError:
            # An unreadable transcript is one fewer sample, not a failure of the claim --
            # and the claim is a floor, so dropping samples can only shrink it.
            continue


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcripts", default=str(Path.home() / ".claude" / "projects"),
                    help="directory of harness transcripts to read")
    ap.add_argument("--seat", default="claude-code",
                    help="which gate's key vocabulary to score these calls against")
    ap.add_argument("--limit-files", type=int, default=0,
                    help="read at most N transcript files (0 = all)")
    ap.add_argument("--show-keys", action="store_true",
                    help="print every gate's key vocabulary and exit")
    ap.add_argument("--examples", type=int, default=3,
                    help="example values printed per unenumerated key")
    args = ap.parse_args()

    root = repo_root(Path(__file__).resolve())
    vocab = gate_key_vocabularies(root)

    print("KEY VOCABULARIES, read from the gate sources:")
    for seat in sorted(vocab):
        v = vocab[seat]
        print(f"  {seat:12} ({v['source']})")
        print(f"      {' '.join(sorted(v['keys'])) or '(none)'}")
        for lineno, group in v.get("mixed", []):
            print(f"      line {lineno}: group mixes a path key with others -- "
                  f"{' '.join(group)}")
    union = set().union(*(v["keys"] for v in vocab.values()))
    common = set.intersection(*(v["keys"] for v in vocab.values()))
    print(f"  union {len(union)}  common-to-all {len(common)}: {' '.join(sorted(common))}")
    for seat in sorted(vocab):
        missing = union - vocab[seat]["keys"]
        if missing:
            print(f"  {seat} does NOT enumerate: {' '.join(sorted(missing))}")
    if args.show_keys:
        return 0

    if args.seat not in vocab:
        raise SystemExit(f"unknown seat {args.seat}; have {sorted(vocab)}")
    enumerated = vocab[args.seat]["keys"]

    files = sorted(Path(args.transcripts).rglob("*.jsonl"))
    if args.limit_files:
        files = files[:args.limit_files]
    print(f"\nreading {len(files)} transcript(s) against the {args.seat} vocabulary\n")

    # SPLIT BY WHETHER THE TOOL IS GATED AT ALL. `Glob` and `Grep` are in the core's
    # READ_CLASS: the seat does not scope them by design, so a path in `pattern` is not an
    # unguarded reach, it is a read the policy declares free. Pooling those with a screenshot
    # WRITE to an ungranted directory would inflate the finding roughly fourfold. The two
    # populations are counted and printed apart; only the gated one is a hole.
    sys.path.insert(0, str(root / "plugins" / "_shared"))
    import hestia_gate_core as core  # noqa: E402

    calls = 0
    with_path = 0
    unseen_calls = 0
    gated_calls = 0
    per_key = collections.Counter()
    per_key_gated = collections.Counter()
    per_key_tools = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    for _t, tool, ti in iter_tool_uses(files):
        calls += 1
        if not isinstance(ti, dict):
            continue
        hit_enum = False
        hit_unseen = []
        for k, v in ti.items():
            if k in NOT_REACH:
                continue
            vals = v if isinstance(v, list) else [v]
            if not any(is_pathish(x) for x in vals):
                continue
            if k in enumerated:
                hit_enum = True
            else:
                hit_unseen.append((k, next(x for x in vals if is_pathish(x))))
        if hit_enum or hit_unseen:
            with_path += 1
        if hit_unseen:
            unseen_calls += 1
            gated = bool(tool) and core.needs_society_gate(tool) and tool not in core.READ_CLASS
            if gated:
                gated_calls += 1
            for k, sample in hit_unseen:
                per_key[k] += 1
                if gated:
                    per_key_gated[k] += 1
                per_key_tools[k][tool] += 1
                if len(examples[k]) < args.examples:
                    examples[k].append((tool, sample, gated))

    print(f"tool calls read                 {calls}")
    print(f"  carrying a path-looking value {with_path}")
    print(f"  with a path under a key the {args.seat} gate does NOT enumerate: "
          f"{unseen_calls}")
    if with_path:
        print(f"  = {100.0 * unseen_calls / with_path:.1f}% of path-carrying calls")
    print(f"  of those, on a tool the policy DOES gate (not READ_CLASS): {gated_calls}")
    print("  -- that last line is the hole. The rest are declared-free reads.")
    print()
    if not per_key:
        print("No unenumerated path-bearing keys in this corpus. That is a MEASURED zero "
              "for this seat and this transcript set -- not for the tool surface.")
        return 0
    print(f"{'key':24} {'calls':>6} {'gated':>6}  tools")
    print("-" * 78)
    for k, n in per_key.most_common():
        tools = ", ".join(f"{t}:{c}" for t, c in per_key_tools[k].most_common(4))
        print(f"{k:24} {n:6} {per_key_gated[k]:6}  {tools}")
    print()
    for k, n in per_key.most_common():
        print(f"{k}:")
        for tool, sample, gated in examples[k]:
            print(f"   {'GATED' if gated else 'read '} {tool:38} {sample[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
