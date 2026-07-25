#!/usr/bin/env python3
"""Shared Gate-1 enforcement core for hestia foreign-member adapters.

Sibling of `path_scope.py`. `path_scope` is the one implementation of Gate-1b
(realpath containment); this module is the one implementation of everything else
Gate-1 does — classification, the Gate-1a secret sweep, command-scope, and the
Claude-lineage translation — so that a fix lands once instead of once per adapter.

WHY THIS EXISTS (CBP review, thread `harness-lane-split`, 2026-07-24):
adapters #4 and #5 re-implemented `_strings`, `dedupe`, `command_in_scope`,
`path_in_scope`, `to_claude_lineage` and the Gate-1a body by copy, and drifted
three ways in a single commit. Two of the holes found on adapter #4 were holes
already closed on adapter #3. The per-adapter part that genuinely differs is the
engine's *vocabulary*; the enforcement logic is not per-engine and should not be
per-file. Adapters now supply a `Vocabulary` and call `plan()`.

THE LOAD-BEARING RULE — UNKNOWN IS MAXIMALLY DANGEROUS.
The root cause of most of that review: a tool in no known class, whose args use no
recognized key, was swept by *nothing*. Gate-1a iterated `paths + egress + cmd`,
all three empty, so the loop body never ran and the call passed Gate-1 having been
examined for nothing. These adapters are documented-tier against moving upstreams,
so vocabulary drift is the EXPECTED case, not the exotic one. An unrecognized tool
now gets the STRICTEST treatment (every string leaf swept, command-scoped, Gate-2
required), not the weakest. The failure mode of drift becomes over-block, which is
the direction we can afford.
"""
import os
import re

# Classes. UNKNOWN is deliberately the strictest, not the loosest.
READ, WRITE, EXEC, EGRESS, MCP, UNKNOWN = "read", "write", "exec", "egress", "mcp", "unknown"

FORBIDDEN_DEFAULT = ("/.ssh", ".env", "credentials", "id_rsa", "id_ed25519",
                     "/.git/config", "secrets")

# A search *term* is not an exfil channel: `grep credentials` inside your own repo is
# a member auditing their own tree. Exempt from the Gate-1a innate sweep ONLY for
# read-class tools and ONLY when the term is not path-shaped. An egress tool's
# `query` is never exempt — that IS the channel (a web_search naming id_rsa).
SEARCH_TERM_KEYS = ("pattern", "regex", "query_pattern")

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def strings(v, depth=0, _max=4):
    """Every string leaf of an arbitrarily-shaped value (bounded depth)."""
    if isinstance(v, str):
        return [v]
    if depth > _max:
        return []
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in strings(x, depth + 1, _max)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in strings(x, depth + 1, _max)]
    return []


def leaf_pairs(obj, depth=0, _max=4, _key=None):
    """(top-level-key, string-leaf) pairs. Key-awareness is what lets the search-term
    exemption be precise: we exempt the value *because of where it came from*, never
    by matching the value itself (which would exempt the same string in a `body`)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            top = _key if _key is not None else k
            if isinstance(v, str):
                out.append((top, v))
            elif depth < _max:
                out.extend(leaf_pairs(v, depth + 1, _max, top))
    elif isinstance(obj, (list, tuple)) and depth < _max:
        for x in obj:
            if isinstance(x, str):
                out.append((_key, x))
            else:
                out.extend(leaf_pairs(x, depth + 1, _max, _key))
    elif isinstance(obj, str):
        out.append((_key, obj))
    return out


def dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def is_remote_url(s):
    """A network endpoint (http/https/git/ssh://...). `file://` is NOT remote."""
    return bool(_URL_RE.match(s)) and not s.startswith("file://")


def is_path_shaped(s):
    return "/" in s or s.startswith("~")


def as_local_path(s):
    """Local filesystem path this string denotes, or None if it denotes no local path.
    Handles `file://` URIs — the LSP/MCP-resource arg shape, which string-prefix path
    logic never saw (CBP CRUSH-4: `lsp_rename` on an out-of-scope file via `uri`)."""
    if not isinstance(s, str) or not s:
        return None
    if s.startswith("file://"):
        rest = s[len("file://"):]
        if rest.startswith("localhost/"):
            rest = rest[len("localhost"):]
        try:
            from urllib.parse import unquote
            rest = unquote(rest)
        except Exception:
            pass
        return rest or None
    if is_remote_url(s):
        return None
    return s if is_path_shaped(s) else None


class Vocabulary(object):
    """The per-engine part — data, not logic. Everything an adapter must state about
    its engine's tool namespace and argument shapes."""

    def __init__(self, read=(), write=(), exec_=(), egress=(), mcp_tools=(),
                 mcp_prefixes=("mcp",), path_keys=(), list_path_keys=(),
                 uri_keys=("uri", "resource_uri"), cmd_keys=("command",),
                 lineage_tool=None, lineage_arg=None, extra_roots=()):
        self.read = {t.lower() for t in read}
        self.write = {t.lower() for t in write}
        self.exec_ = {t.lower() for t in exec_}
        self.egress = {t.lower() for t in egress}
        self.mcp_tools = {t.lower() for t in mcp_tools}
        self.mcp_prefixes = tuple(p.lower() for p in mcp_prefixes)
        self.path_keys = tuple(path_keys)
        self.list_path_keys = tuple(list_path_keys)
        self.uri_keys = tuple(uri_keys)
        self.cmd_keys = tuple(cmd_keys)
        self.lineage_tool = dict(lineage_tool or {})
        self.lineage_arg = dict(lineage_arg or {})
        self.extra_roots = tuple(extra_roots)

    def is_mcp(self, t):
        """MCP-family detection must not be a bare name prefix. Upstream Crush also
        registers `read_mcp_resource` / `list_mcp_resources` — MCP tools whose names
        start with `read_`/`list_` (CBP CRUSH-2)."""
        return (t.startswith(self.mcp_prefixes) or t in self.mcp_tools
                or "_mcp_" in t or t.endswith("_mcp"))

    def classify(self, tool):
        t = (tool or "").lower()
        if self.is_mcp(t):
            return MCP
        for table, klass in ((self.read, READ), (self.egress, EGRESS),
                             (self.write, WRITE), (self.exec_, EXEC)):
            if t in table:
                return klass
        return UNKNOWN


class Plan(object):
    """What Gate-1 must examine for one call."""

    def __init__(self, klass, gate1a, paths, cmd_scope, needs_gate2, for_write):
        self.klass = klass
        self.gate1a = gate1a          # blobs swept for forbidden tokens (innate)
        self.paths = paths            # local paths for realpath containment (Gate-1b)
        self.cmd_scope = cmd_scope    # blobs checked against out-of-scope repo names
        self.needs_gate2 = needs_gate2
        self.for_write = for_write


def plan(tool, tool_input, vocab):
    """Decide what to examine. The whole point: there is no path through this function
    that examines nothing."""
    klass = vocab.classify(tool)
    ti = tool_input if isinstance(tool_input, dict) else {}
    pairs = leaf_pairs(ti)

    # Declared path args (explicit keys + list forms + multiedit's [{file_path}]).
    declared = []
    for k in vocab.path_keys:
        v = ti.get(k)
        if isinstance(v, str):
            declared.append(v)
    for k in vocab.list_path_keys:
        v = ti.get(k)
        if isinstance(v, str):
            declared.append(v)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    declared.append(x)
                elif isinstance(x, dict):
                    fp = x.get("file_path") or x.get("path")
                    if isinstance(fp, str):
                        declared.append(fp)
    for k in vocab.uri_keys:
        v = ti.get(k)
        if isinstance(v, str):
            declared.append(v)

    cmd = None
    for k in vocab.cmd_keys:
        c = ti.get(k)
        if isinstance(c, str):
            cmd = c
            break
        if isinstance(c, list):
            cmd = " ".join(str(x) for x in c)
            break

    # A search term that names no path is not a channel — but only for a reader.
    def exempt(key, s):
        return klass == READ and key in SEARCH_TERM_KEYS and not is_path_shaped(s)

    if klass in (MCP, UNKNOWN, EGRESS):
        # The argument schema is the server's / the engine's / nobody's — not ours.
        # Sweep every leaf rather than a guessed key list. This is the gemini lesson
        # (the URL that only ever appeared inside `prompt`) applied permanently, and
        # it removes the schema-guess dependency that produced KIRO-4 and CRUSH-1.
        gate1a = [s for k, s in pairs if not exempt(k, s)]
        # ...but a network endpoint is not a local repo path: command-scoping a URL
        # only ever false-denies (deliberate asymmetry carried from gemini `4213fec`).
        cmd_scope = [s for k, s in pairs if not is_remote_url(s)]
    else:
        # A known read/write/exec tool: its declared args ARE its channels.
        known = set(declared) | ({cmd} if cmd is not None else set())
        gate1a = [s for k, s in pairs if s in known and not exempt(k, s)]
        cmd_scope = [cmd] if cmd is not None else []

    # Realpath containment applies only to things that denote a local path.
    paths = dedupe([p for p in (as_local_path(s) for s in declared) if p])

    return Plan(
        klass=klass,
        gate1a=dedupe(gate1a),
        paths=paths,
        cmd_scope=dedupe(cmd_scope),
        # Read-class is the ONLY class that may skip the governor.
        needs_gate2=(klass != READ),
        # Unknown/MCP are treated as writers: stricter containment, safe direction.
        for_write=(klass in (WRITE, EXEC, UNKNOWN, MCP)),
    )


def forbidden_hit(blob, forbidden):
    low = blob.lower()
    for f in forbidden:
        if f and f in low:
            return f
    return None


def all_repos(workspace):
    """Sibling repos of the workspace, or None if the workspace cannot be enumerated.

    None is NOT the same as []. An unenumerable workspace is doubt, and `path_scope`'s
    own rule is fail-closed-on-doubt: with a dead HESTIA_WORKSPACE the old code found
    no repo "out of scope" and `command_in_scope` therefore passed everything (CBP
    non-blocking, lane-wide). An empty-but-readable workspace is a real, benign state
    and stays permissive."""
    try:
        return [d for d in os.listdir(workspace)
                if os.path.isdir(os.path.join(workspace, d)) and not d.startswith(".")]
    except Exception:
        return None


def command_in_scope(cmd, scopes, workspace, repos=None):
    """False if the blob names an out-of-scope sibling repo or reaches into the
    workspace outside the granted scopes."""
    if repos is None:
        repos = all_repos(workspace)
    if repos is None:
        return False  # unenumerable workspace: fail closed rather than disarm
    for repo in (r for r in repos if r not in scopes):
        if re.search(rf"""(^|[\s/=:"'(]){re.escape(repo)}(/|[\s"')]|$)""", cmd):
            return False
    if workspace in cmd:
        after = cmd.split(workspace, 1)[1]
        if not any(after.lstrip("/").startswith(s) for s in scopes):
            return False
    return True


def event_name(event, keys=("hook_event_name", "event")):
    """The engines disagree on this field name — Crush uses `event`, the Claude lineage
    uses `hook_event_name` — and getting it wrong exits 0 on EVERY call, which is the
    quietest possible way to disarm a gate (CBP KIRO-3). Accept either."""
    for k in keys:
        v = event.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def should_gate(event, want="PreToolUse"):
    """True if this event must be gated.

    If NO recognized event key is present but a `tool_name` is, gate it anyway. Exiting
    0 on an unrecognized envelope is the same class of fail-open as exiting 0 on an
    unrecognized tool, and these adapters' stdin contracts are documented-tier."""
    name = event_name(event)
    if name is None:
        return isinstance(event.get("tool_name"), str) and bool(event.get("tool_name"))
    return name == want


def normalize_mcp_name(tool):
    """Crush builds MCP tool names as `mcp_<server>_<tool>` (single underscore,
    `mcp-tools.go:59`), but the society governor dispatches on the Claude convention
    `mcp__<server>__<tool>` (CBP CRUSH-3). Translate at the boundary.

    Ambiguous when a server name itself contains `_`; we split at the first separator,
    which is the common case. A wrong split yields a governor tool name that matches no
    rule — the call still had to pass Gate-1 and still reaches the governor, so the
    failure mode is a less specific rule, never a skipped gate."""
    t = tool or ""
    if t.startswith("mcp__"):
        return t
    if t.startswith("mcp_"):
        rest = t[len("mcp_"):]
        if "_" in rest:
            server, name = rest.split("_", 1)
            return f"mcp__{server}__{name}"
        return f"mcp__{rest}"
    return t


def to_claude_lineage(event, tool, tinput, vocab, lineage_name="foreign"):
    """Re-shape a foreign PreToolUse event into the Claude-lineage shape the governor
    understands, lossless (original fields ride under `source_event`).

    The governor extracts its target from file_path/path/url/notebook_path and only
    reads `command` when tool_name is in {Bash, Shell} — an untranslated handoff gives
    it target=None for every command, which is a gate that is consulted but blind."""
    out = dict(event)
    klass = vocab.classify(tool)
    if klass == MCP:
        out["tool_name"] = normalize_mcp_name(tool)
    else:
        out["tool_name"] = vocab.lineage_tool.get((tool or "").lower(), tool)
    if isinstance(tinput, dict):
        ti = {vocab.lineage_arg.get(k, k): v for k, v in tinput.items()}
        if "url" not in ti:
            # Lift an endpoint out of free text so an egress call meets the governor
            # with a real target instead of None (the gemini `web_fetch` prompt lesson).
            for s in strings(tinput):
                if is_remote_url(s):
                    ti["url"] = s
                    break
            else:
                m = re.search(r"https?://[^\s\"'<>)]+", " ".join(strings(tinput)))
                if m:
                    ti["url"] = m.group(0)
        out["tool_input"] = ti
    out["source_event"] = {"lineage": lineage_name, "tool_name": tool,
                           "tool_input": tinput, "class": klass}
    return out
