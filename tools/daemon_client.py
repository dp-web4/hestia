#!/usr/bin/env python3
"""Call any hestia MCP tool through the tracked member-mesh transport (#603).

Usage:
  python3 tools/daemon_client.py <tool_name> [json_arguments]

Environment: HESTIA_MESH_PLUGIN (required member identity), HESTIA_ENDPOINT,
HESTIA_MESH_HOST_AGENT, HESTIA_ROLE, HESTIA_MESH_TIMEOUT. This is a thin client,
not a second transport or an MCP registration. Exit codes: 0 ok, 1 unreachable,
2 usage, 3 daemon refusal, 4 undetermined outcome.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

_SPEC = importlib.util.spec_from_file_location(
    "hestia_member_mesh",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "plugins", "member-mesh", "hestia-mesh.py"),
)
_mesh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mesh)


def call(tool_name: str, arguments: dict):
    """Call one tool with a connected, attributed session; never hide a refusal."""
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name must be a non-empty string")
    if not isinstance(arguments, dict):
        raise TypeError("arguments must be a JSON object")
    h, session_id = _mesh.connect()
    out = _mesh.rpc(h, tool_name, dict(arguments, session_id=session_id))
    if _mesh.failed(out):
        raise _mesh.DaemonRefusal(out)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or len(argv) > 2:
        print(json.dumps({"_hestia_error": {"code": "usage",
                                            "message": "usage: daemon_client.py <tool_name> [json_arguments]"}}))
        return 2
    try:
        arguments = json.loads(argv[1]) if len(argv) == 2 else {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
    except (ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"_hestia_error": {"code": "usage", "message": str(e)}}))
        return 2
    try:
        print(json.dumps(call(argv[0], arguments)))
        return 0
    except _mesh.Unreachable as e:
        print(json.dumps({"_hestia_error": {"code": "unreachable", "message": str(e)}}))
        return 1
    except _mesh.Undetermined as e:
        print(json.dumps({"_hestia_error": {"code": "undetermined", "message": str(e)}}))
        return 4
    except _mesh.DaemonRefusal as e:
        print(json.dumps(e.payload))
        return 3


if __name__ == "__main__":
    sys.exit(main())
