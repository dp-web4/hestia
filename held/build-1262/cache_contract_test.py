#!/usr/bin/env python3
"""Exercise a neutral built candidate with synthetic files only, never the live gate.

Usage: python3 cache_contract_test.py <base-worktree> <neutral-gate.py>
"""
import importlib.util
import builtins
import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

base = pathlib.Path(sys.argv[1]).resolve()
candidate = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(base / "plugins" / "_shared"))
spec = importlib.util.spec_from_file_location("timeout_cache_candidate", candidate)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="hestia-cache-test-") as tmp:
    config = pathlib.Path(tmp) / "registration.json"
    config.write_bytes(b'{"timeout":7}')
    st = config.stat()
    a = module._load_config(str(config), "json-hook-commands")
    assert a[0]["timeout"] == 7
    assert module._load_config(str(config), "json-hook-commands") is a, "unchanged bytes hit cache"
    config.write_bytes(b'{"timeout":3}')
    os.utime(config, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert config.stat().st_size == st.st_size and config.stat().st_mtime_ns == st.st_mtime_ns
    b = module._load_config(str(config), "json-hook-commands")
    assert b[0]["timeout"] == 3, "same-size, same-mtime changed bytes must not hit cache"
    config.write_bytes(b'{"timeout":x}')
    os.utime(config, ns=(st.st_atime_ns, st.st_mtime_ns))
    try:
        module._load_config(str(config), "json-hook-commands")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed changed bytes must not be hidden by a cached parse")
    config.write_bytes(b'{"timeout":3}')
    assert module._load_config(str(config), "json-hook-commands")[0]["timeout"] == 3
    config.write_bytes(b'{"timeout":1,"timeout":2}')
    original_open = builtins.open
    reads = []
    def counted_open(path, mode="r", *args, **kwargs):
        if str(path) == str(config) and mode == "rb":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)
    with patch("builtins.open", side_effect=counted_open):
        c = module._load_config(str(config), "json-hook-commands")
    assert len(reads) == 1, "comparison and parsing must use the same single read"
    assert c[0]["timeout"] == 2 and c[2], "duplicate-key evidence survives parsing"
    assert module._load_config(str(config), "json-hook-commands") is c, "duplicate evidence survives a hit"
    try:
        module._load_config(str(config), "toml")
    except ValueError:
        pass
    else:
        raise AssertionError("a JSON cache hit must not be returned to a different reader")
print("cache contract: PASS")
