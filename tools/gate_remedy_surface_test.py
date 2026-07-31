#!/usr/bin/env python3
"""A refusal that names a remedy is making a promise about a surface nobody compares.

WHAT HAPPENED (CBP, 2026-07-31, thread supervisor-role-2026-07-31). The gate refused a
write, and told the session how to appeal it: run `hestia gate approve <id> --reason ...`.
The shipped binary answers `error: unrecognized subcommand 'gate'`. Four escalations were
open against that seat and none could be closed by the command the refusal named. The
session could not appeal, and the law it had been given forbids the only other move
(rephrasing to reach the same resource) — so the rule that punishes rephrasing had left
rephrasing as the only available act.

WHY NO EXISTING CHECK REACHES IT. Every other divergence found in that thread was a file
against a file: repo vs bundle (plugins/codex/tests/marketplace_parity_test.py), repo vs
deployment (plugins/member-mesh/tests/install_drift_test.py). This one is a SENTENCE
against a SUBCOMMAND TABLE. Both halves are in this repo and neither has ever been
compared to the other, because they are not two copies of anything — they are a claim and
the surface it is a claim about. Copying files more carefully would not have caught it.

It is also the worst-timed defect shape available: the string only speaks at the moment
someone is already blocked, which is the moment they are least able to work around being
told a lie. An advertisement that ships inside an error path is read exactly once, under
duress, by someone with no way to check it.

VERIFIED AT SOURCE, not from a binary's behaviour (2026-07-31, legion). `core/src/cli.rs`
declares `enum Command` with twelve variants and no `Gate` among them, and there is no
`GateCmd` anywhere in the file. So this was never a stale-binary problem and no upgrade
fixes it: the subcommand has not existed at any point the string has. The remedy itself is
real, but it lives on the OTHER surface — `core/src/server/handler.rs` dispatches
`hestia_gate_escalation_*` and `hestia_gate_arbitrate_escalation` as MCP tools. So the
deny does not advertise a capability the fleet lacks; it advertises a real capability at
an address it has never had. An agent that follows the instruction literally concludes the
remedy is missing.

WHAT THIS COMPARES. Advertised remedies extracted from the gate surfaces, resolved against
the two surfaces that actually exist:

    `hestia <sub>`     ->  variants of `enum Command` in core/src/cli.rs
    `hestia_<tool>`    ->  dispatch arms in core/src/server/handler.rs

Properties asserted:

  A. THE EXTRACTOR FINDS SOMETHING. Zero advertisements extracted is a broken reader, not
     a clean bill — the gate demonstrably makes these promises. Asserted separately so a
     regex that stops matching cannot present itself as a pass. This is the same
     fail-soft that plugins/codex/tests/marketplace_parity_test.py had to design around:
     an absent construct must read as FAIL, never as an empty set of problems.
  B. BOTH SURFACES PARSE, and are non-empty. A reader that cannot find `enum Command`
     returns None and fails here, rather than returning an empty set and failing every
     advertisement in C for the wrong reason. Which of "the promise is broken" and "the
     reader broke" is true has to stay distinguishable, or the first fix attempted will be
     to the wrong file.
  C. EVERY ADVERTISED CLI INVOCATION RESOLVES.  <-- RED TODAY: `hestia gate`.
  D. EVERY ADVERTISED MCP TOOL RESOLVES. Green today, and it is the half that shows the
     check is not merely spelling `gate` — the law's `hestia_appeal` is extracted by the
     same rule and does resolve.
  E. THIS FILE NAMES NO GOVERNANCE FILE. Enforced here, against the list read out of the
     gate at runtime, because of how the finding was reported: the same gate refuses a
     WRITE whose content merely mentions one of those filenames near the token `hooks/`
     — deliberately, per its own comment, judging by mention rather than by executable
     position. CBP could not write the document describing this without redacting the
     filenames out of it. A checker that listed its targets could therefore not be
     authored on a machine where the gate it checks is live. So the targets are
     DISCOVERED, for a second independent reason on top of the one ci_discovery.py
     already established.

ON SCANNING TEST FILES TOO. plugins/claude-code/hooks/test_gate_escalation.py carries the
same invocation in a fixture. It is deliberately not exempt: the fixture asserts today's
string, so it is a second place the promise is written down, and a fix that changed only
the gate would leave a test pinning the broken text. Naming both is the point.

WHAT THIS DOES NOT DO. It does not check ARGUMENTS or flags — `--reason` is unverified
even where the subcommand resolves. Nor does it run the binary: the comparison is
source-to-source so it holds on a CI runner with no hestia installed, which is also the
only way it could be hermetic. On the machine that found this, `hestia` is not on PATH at
all, so a live `--help` probe would have had nothing to ask.

Run: python3 tools/gate_remedy_surface_test.py
"""

import ast
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

# Gate surfaces are DISCOVERED (property E), from git rather than the filesystem, for
# ci_discovery.py's reason: an untracked scratch file is not the repo's obligation.
GATE_GLOB = re.compile(r"^plugins/[^/]+/hooks/.*\.py$")

CLI_SRC = "core/src/cli.rs"
MCP_SRC = "core/src/server/handler.rs"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True,
    ).stdout
    return sorted(p for p in (raw.decode() for raw in out.split(b"\0") if raw))


def gate_sources() -> list[str]:
    return [p for p in tracked() if GATE_GLOB.match(p)]


# ---------------------------------------------------------------------------
# The two surfaces. Each returns None when its construct is ABSENT, and that is
# load-bearing (property B): an empty set here would silently convert "I could not
# read the CLI" into "the CLI defines nothing", which fails every advertisement in C
# and points the reader at the wrong file.
# ---------------------------------------------------------------------------

def cli_subcommands() -> set[str] | None:
    """Variant names of `enum Command` in the clap definition, kebab-cased as clap does."""
    src = (REPO / CLI_SRC).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\benum\s+Command\s*\{", src)
    if not m:
        return None
    depth, i, body = 0, m.end() - 1, []
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        else:
            body.append(src[i])
        i += 1
    else:
        return None
    # Variants are the CamelCase idents at brace-depth 1 of the enum body.
    names, d = set(), 0
    for line in "".join(body).splitlines():
        stripped = line.strip()
        if d == 0:
            v = re.match(r"([A-Z][A-Za-z0-9]*)\s*(\{|\(|,|$)", stripped)
            if v:
                names.add(re.sub(r"(?<!^)(?=[A-Z])", "-", v.group(1)).lower())
        d += line.count("{") + line.count("(") - line.count("}") - line.count(")")
    return names or None


def mcp_tools() -> set[str] | None:
    """Tool names the MCP server actually dispatches."""
    src = (REPO / MCP_SRC).read_text(encoding="utf-8", errors="replace")
    names = set(re.findall(r'"(hestia_[a-z_]+)"\s*=>', src))
    return names or None


# ---------------------------------------------------------------------------
# Advertisements.
#
# The discriminator is the repo's OWN convention for "this is a thing you invoke":
# a backtick-delimited token, or a string that IS the command line. Measured against
# every gate surface before it was chosen — the alternatives all cry wolf, and a check
# that cries wolf gets muted, which is the failure mode the gate's own comment warns
# about for its escalation event class.
#
# Dropped by the backtick/string-initial rule, correctly, all four verified by hand:
#   "## hestia law: NOT LOADED"    a markdown HEADING in the law banner
#   "...hestia security REVIEW..." prose inside a comment
#   "hestia_decision": verb        a JSON FIELD NAME in an observation record
#   hestia_plugin_sdk              a python PACKAGE named in a module docstring
# Docstrings are skipped outright: they are commentary about the system, and a
# docstring mentioning a command is not the gate telling an agent to run one.
# ---------------------------------------------------------------------------

CLI_RE = re.compile(r"hestia[ \t]+([a-z][a-z0-9-]*)")
TOOL_RE = re.compile(r"hestia_[a-z_]+")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(n, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _backticked(text: str, start: int) -> bool:
    return start > 0 and text[start - 1] == "`"


def _in_markdown_heading(text: str, start: int) -> bool:
    return text[:start].rsplit("\n", 1)[-1].lstrip().startswith("#")


def advertisements() -> list[tuple[str, int, str, str]]:
    """(path, lineno, kind, token) for every remedy the gate surfaces advertise."""
    found = []
    for path in gate_sources():
        text = (REPO / path).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:  # a gate we cannot parse is not a gate we can clear
            found.append((path, getattr(exc, "lineno", 0) or 0, "unparseable", str(exc)))
            continue
        skip = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in skip:
                continue
            v = node.value
            for m in CLI_RE.finditer(v):
                if _in_markdown_heading(v, m.start()):
                    continue
                # A CLI invocation counts if it is quoted as one, or if the whole
                # string is the command — which is how the escalation fallback is
                # written: assigned bare, then interpolated into "To allow: {how}".
                if _backticked(v, m.start()) or m.start() == 0:
                    found.append((path, node.lineno, "cli", m.group(1)))
            for m in TOOL_RE.finditer(v):
                # Backticks ONLY. String-initial would sweep in dict keys — the
                # observation record's "hestia_decision" field is not a tool call.
                if _backticked(v, m.start()):
                    found.append((path, node.lineno, "tool", m.group(0)))
    return found


def main() -> int:
    print("gate remedy surface — advertised remedies vs the surfaces that exist\n")

    sources = gate_sources()
    print(f"  discovered {len(sources)} gate surface(s):")
    for s in sources:
        print(f"    {s}")
    print()

    ads = advertisements()
    unparseable = [a for a in ads if a[2] == "unparseable"]
    for path, ln, _, detail in unparseable:
        check(f"A. {path} parses", False, detail)

    cli_ads = sorted({(a[3], a[0], a[1]) for a in ads if a[2] == "cli"})
    tool_ads = sorted({(a[3], a[0], a[1]) for a in ads if a[2] == "tool"})

    # A — the reader works at all.
    check("A. extractor found advertised remedies",
          bool(cli_ads or tool_ads),
          f"{len(cli_ads)} cli, {len(tool_ads)} tool")

    # B — both surfaces are readable.
    subs = cli_subcommands()
    tools = mcp_tools()
    check(f"B. {CLI_SRC} declares enum Command", subs is not None,
          f"{len(subs)} subcommands" if subs else "enum Command NOT FOUND — reader broke")
    check(f"B. {MCP_SRC} declares a dispatch table", tools is not None,
          f"{len(tools)} tools" if tools else "no dispatch arms found — reader broke")

    if subs is None or tools is None:
        print("\n  surfaces unreadable; C/D not run (they would fail for the wrong reason)")
    else:
        print(f"\n  cli surface: {' '.join(sorted(subs))}\n")

        # C — every advertised CLI invocation resolves.
        bad = [(t, p, ln) for t, p, ln in cli_ads if t not in subs]
        check("C. every advertised `hestia <sub>` resolves against the CLI",
              not bad,
              "; ".join(f"'hestia {t}' at {p}:{ln} — no such subcommand" for t, p, ln in bad)
              or f"{len(cli_ads)} checked")

        # D — every advertised MCP tool resolves.
        bad_t = [(t, p, ln) for t, p, ln in tool_ads if t not in tools]
        check("D. every advertised `hestia_<tool>` resolves against MCP dispatch",
              not bad_t,
              "; ".join(f"'{t}' at {p}:{ln} — not dispatched" for t, p, ln in bad_t)
              or f"{len(tool_ads)} checked")

    # E — this file names no governance file, per the list the GATE defines.
    governance = set()
    for path in sources:
        try:
            tree = ast.parse((REPO / path).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "_GOVERNANCE_FILES"):
                for elt in ast.walk(node.value):
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        governance.add(elt.value)
    self_src = pathlib.Path(__file__).read_text(encoding="utf-8", errors="replace")
    leaked = sorted(n for n in governance if n in self_src)
    check("E. this checker names no governance file (stays authorable under a live gate)",
          bool(governance) and not leaked,
          "gate defines no _GOVERNANCE_FILES — cannot verify" if not governance
          else (f"leaked: {', '.join(leaked)}" if leaked
                else f"{len(governance)} names checked, none present"))

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print(f"PASSED all {len(sources)} gate surface(s) clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
