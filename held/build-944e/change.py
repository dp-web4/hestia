"""hestia #944 (endpoint half): the three side paths that still guessed the daemon's port.

`emit_attestation`, `gate_self_call` and `scope_call` read `HESTIA_ENDPOINT` and fell back to the
literal `http://127.0.0.1:7711/mcp`. The decision path (`check_with_society`) and the snapshot fetch
already use `_discover_endpoint()` and refuse with no endpoint. This makes the three side paths do
the same: `_discover_endpoint()` (env, then `$HESTIA_HOME/endpoint`), and None -> nothing is sent.

`apply(text) -> text` edits the mechanism source; each old block must occur exactly once.
"""

LITERAL = 'os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")'

EDITS = [
    # emit_attestation: best effort, returns None on every no-send path already.
    (
        '    endpoint = endpoint or ' + LITERAL + '\n',
        '    # #944: the endpoint is configuration. With none projected, attest nothing; never a\n'
        '    # guessed port (2026-10-06: a fallback to :7711 reached the live daemon from a CI\n'
        '    # harness and opened four real escalations under other members\' names, #1246).\n'
        '    endpoint = endpoint or _discover_endpoint()\n'
        '    if endpoint is None:\n'
        '        return None\n',
    ),
    # gate_self_call: "Callers treat None as refusal (writes) or best-effort loss (witnesses)."
    (
        '    but never runs past it, and no step starts after it (that is a None: refusal or loss)."""\n'
        '    endpoint = ' + LITERAL + '\n',
        '    but never runs past it, and no step starts after it (that is a None: refusal or loss).\n'
        '\n'
        '    No endpoint discovered (#944) is a None too: nothing is sent to a guessed port."""\n'
        '    endpoint = _discover_endpoint()\n'
        '    if endpoint is None:\n'
        '        return None\n',
    ),
    # scope_call: "Returns ... None when nothing was sent".
    (
        '    the daemon may have applied it. Never raises."""\n'
        '    endpoint = ' + LITERAL + '\n',
        '    the daemon may have applied it. Never raises.\n'
        '\n'
        '    No endpoint discovered (#944) is None: nothing was sent, to any port."""\n'
        '    endpoint = _discover_endpoint()\n'
        '    if endpoint is None:\n'
        '        return None\n',
    ),
]


def apply(text):
    for old, new in EDITS:
        n = text.count(old)
        assert n == 1, (old[:80], n)
        text = text.replace(old, new)
    assert LITERAL not in text, "a guessed-port fallback survived"
    return text
