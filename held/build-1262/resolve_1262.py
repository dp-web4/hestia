#!/usr/bin/env python3
"""Resolve the four conflicts in the neutral copies (writes <name>.resolved).

hooks.json x3: #1262's _timeout_contract (the canonical-or-MISWIRED text) plus main's new keys
(_disposition_reader, _member_mesh); main's older _timeout_contract wording is dropped.
gate: main's (path, reader, mtime, size) cache around #1262's three-value loader."""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
BLOCK = re.compile(r"<<<<<<< kimi\n(.*?)=======\n(.*?)>>>>>>> main\n", re.S)


def hooks(name):
    text = (HERE / f"{name}.merged").read_text(encoding="utf-8")

    def pick(m):
        theirs = [l for l in m.group(2).splitlines(True) if not l.lstrip().startswith('"_timeout_contract"')]
        return m.group(1) + "".join(theirs)
    out = BLOCK.sub(pick, text)
    json.loads(out)
    assert "<<<<<<<" not in out
    (HERE / f"{name}.resolved").write_text(out, encoding="utf-8")


GATE_LOADER = '''    """(parsed document, None, dupes) or (None, why, {}). `dupes` maps id(marked object) to
    (the marked object, {repeated key: [occurrences in order]}), for the JSON reader only:
    json.loads is last-wins — as the harness's own parser is — so a duplicated key is no
    measured deadline overrun, but it IS ambiguous wiring, MISWIRED evidence under the
    protocol's duplicate rule (#1262 re-review P2). TOML rejects a duplicate key at parse, so
    the tomllib path never marks anything. A TOML config without tomllib is (None, "scan", {}).
    The mark carries its object: holding it keeps the id from being recycled once an overwritten
    object is freed, and the lookup re-checks identity — a bare id() can be handed to a later
    allocation, which would hang a stranger's repeated key on a clean registration (#1262
    re-review B1). Occurrences are kept so an ENCLOSING key whose copies agree (deep-equal) can
    be told from one the harness's last-wins parser silently chooses between (#1262 re-review
    P2 round 2).
    Cached on (path, reader, mtime, size): the timeout bound and the registered-surface read
    parse each registration once per process, and a changed file is re-read. The cached
    document is what keeps every marked object alive, so a mark's identity holds across hits."""
    st = os.stat(path)
    key = (path, reader, st.st_mtime_ns, st.st_size)
    hit = _CONFIG_CACHE.get(key)
    if hit is not None:
        return hit
    out = _load_config_uncached(path, reader)
    _CONFIG_CACHE[key] = out
    return out


def _load_config_uncached(path: str, reader: str):
'''


def gate():
    text = (HERE / "sg.merged").read_text(encoding="utf-8")
    blocks = BLOCK.findall(text)
    assert len(blocks) == 1, len(blocks)
    out = BLOCK.sub(lambda m: GATE_LOADER, text)
    # main's registered-surface reader unpacks the loader's old two values
    old = "            doc, how = _load_config(path, reader)\n"
    assert out.count(old) == 1, out.count(old)
    out = out.replace(old, "            doc, how, _dupes = _load_config(path, reader)\n")
    assert "<<<<<<<" not in out and "doc, how = _load_config" not in out
    compile(out, "sg.resolved", "exec")
    (HERE / "sg.resolved").write_text(out, encoding="utf-8")


for n in ("cc_hooks", "cx_hooks", "km_hooks"):
    hooks(n)
for n in ("gm_hooks", "km_pre", "gm_chan_test", "decide_test"):
    (HERE / f"{n}.resolved").write_bytes((HERE / f"{n}.merged").read_bytes())
gate()
print("resolved")
