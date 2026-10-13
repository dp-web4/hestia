"""Build the proposed #1281 patch as data; never write or install gate source."""
import difflib
import hashlib
import json
from pathlib import Path
import runpy
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

CORE_HELPERS = r'''def github_repository_parts(value: str):
    """Qualified GitHub identity, not a filesystem path or a URL."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+)", value)
    if not match or match[2] in (".", ".."):
        return None
    return match[1], match[2]


def github_origin_identity(value: str):
    """Recognize unambiguous GitHub origin spellings; never resolve aliases/network."""
    match = re.fullmatch(
        r"(?:https://github[.]com/|ssh://git@github[.]com(?::22)?/|git@github[.]com:)"
        r"([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+?)(?:[.]git)?/?",
        value, re.IGNORECASE)
    if not match or match[2] in (".", ".."):
        return None
    return (match[1] + "/" + match[2]).casefold()


def checkout_origin_identity(candidate: str):
    """Read only this checkout's local origin, including linked worktree metadata.

    No global/includes, inherited GIT_* overrides, URL rewrites or remote access.
    Both common and worktree config participate; multiple origins fail closed.
    The local config is A1
    configuration evidence, not cryptographic ownership proof.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        result = subprocess.run(
            ["git", "-C", candidate, "config", "--no-includes",
             "--get-all", "remote.origin.url"],
            env=env, capture_output=True, text=True, timeout=1, check=False)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    urls = result.stdout.splitlines()
    if result.returncode != 0 or len(urls) != 1:
        return None
    return github_origin_identity(urls[0])


def repo_in_scope(repository: str, scopes, workspace: str) -> bool:
    """Narrow existing basename authority by the checkout's full origin identity."""
    parts = github_repository_parts(repository)
    if parts is None:
        return False  # a basename-only adapter cannot establish the remote identity
    owner, repo = parts
    # Preserve the existing authority prerequisite. Neither recursive path grants
    # nor a new qualified-grant spelling gain remote reach through local writes.
    if repo not in scopes:
        return False
    ws = os.path.realpath(os.path.expanduser(workspace)).replace("\\", "/").rstrip("/")
    candidate = ws + "/" + repo
    if os.path.realpath(candidate).replace("\\", "/") != candidate:
        return False  # neither escaping symlinks nor internal aliases identify this repo
    marker = os.path.join(candidate, ".git")
    if not os.path.isdir(candidate) or not (os.path.isdir(marker) or os.path.isfile(marker)):
        return False
    return checkout_origin_identity(candidate) == (owner + "/" + repo).casefold()


'''

ADAPTER = '''def _mcp_repo(tool: str, tool_input: Any) -> Optional[str]:
    if not (isinstance(tool, str) and tool.startswith("mcp__")) or not isinstance(tool_input, dict):
        return None
    # Preserve authority-bearing owner/repo. Conflicting aliases are not first-key-wins:
    # the connector might interpret a different field from the gate.
    identities = []
    # Invalid identity must still expose the original strings to innate egress
    # scanning, including when scope='*' skips repository scope validation.
    raw_keys = ("owner", "repository_full_name", "repo_full_name", "repository", "repo")
    invalid = "!invalid-repository-identity! " + " ".join(
        tool_input[key] for key in raw_keys if isinstance(tool_input.get(key), str))
    owner = tool_input.get("owner")
    for key in ("repository_full_name", "repo_full_name", "repository", "repo"):
        if key not in tool_input or tool_input[key] is None:
            continue
        value = tool_input[key]
        if not isinstance(value, str) or not value.strip():
            return invalid
        value = value.strip()
        if "/" not in value and isinstance(owner, str):
            value = owner.strip() + "/" + value
        parts = core.github_repository_parts(value)
        if parts is None:
            return invalid
        if owner is not None and (not isinstance(owner, str)
                                  or owner.strip().casefold() != parts[0].casefold()):
            return invalid
        identities.append(value)
    if not identities:
        return None
    if len({value.casefold() for value in identities}) != 1:
        return invalid
    return identities[0]


'''


def runtime_sources():
    core_path = "plugins/_shared/hestia_gate_core.py"
    adapter_path = "plugins/_shared/hestia_single_gate.py"
    old_core = (ROOT / core_path).read_text()
    old_adapter = (ROOT / adapter_path).read_text()
    marker = "# ── The decision ─"
    at = old_core.index(marker)
    core = old_core[:at] + CORE_HELPERS + old_core[at:]
    assert core.count("            if rname not in scopes:") == 1
    core = core.replace("            if rname not in scopes:",
                        "            if not repo_in_scope(rname, scopes, ws):")
    core = core.replace("import re\n", "import re\nimport subprocess\n", 1)
    start = old_adapter.index("def _mcp_repo(")
    end = old_adapter.index("def normalized_event(", start)
    adapter = old_adapter[:start] + ADAPTER + old_adapter[end:]
    return {core_path: (old_core, core), adapter_path: (old_adapter, adapter)}


def gt_tools():
    return runpy.run_path(str(ROOT / "tools/hooks_gt.py"))


def proposed_sources():
    """Compose source and complete publication changes, entirely in memory."""
    changes = runtime_sources()
    overrides = {ROOT / path: new.encode() for path, (_, new) in changes.items()}
    original_read = Path.read_bytes

    def read_bytes(path):
        return overrides[path] if path in overrides else original_read(path)

    gt = gt_tools()
    with patch.object(Path, "read_bytes", read_bytes):
        published = gt["build"](ROOT)
    for path, new_bytes in published.items():
        old = (ROOT / path).read_text()
        new = new_bytes.decode()
        if old != new:
            changes[path] = (old, new)
    return changes


def publication_findings(changes):
    """Run the repository's real GT checker over a read-only candidate overlay."""
    overrides = {ROOT / path: new for path, (_, new) in changes.items()}
    original_bytes, original_text = Path.read_bytes, Path.read_text

    def read_bytes(path):
        return overrides[path].encode() if path in overrides else original_bytes(path)

    def read_text(path, *args, **kwargs):
        return overrides[path] if path in overrides else original_text(path, *args, **kwargs)

    gt = gt_tools()
    with patch.object(Path, "read_bytes", read_bytes), patch.object(Path, "read_text", read_text):
        return gt["check"](ROOT)


def artifact():
    chunks, preimages = [], {}
    for path, (old, new) in proposed_sources().items():
        preimages[path] = hashlib.sha256(old.encode()).hexdigest()
        chunks.append(f"diff --git a/{path} b/{path}\n")
        chunks.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                         fromfile="a/" + path, tofile="b/" + path, n=3))
    text = "".join(chunks)
    return {"patch": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "preimages": preimages}


if __name__ == "__main__":
    print(json.dumps(artifact()))
