import hashlib
import os
import re
import subprocess
from scratch import require_scratch
from apply_lib import split, apply


def checked_patch(scratch, digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("an exact lowercase SHA-256 is required")
    data = (scratch / (digest + ".patch")).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("patch bytes do not match the requested digest")
    return data.decode("utf-8")


def main():
    scratch = require_scratch()
    files = split(checked_patch(scratch, os.environ["HESTIA_1314_PATCH_SHA"]))
    want = {"plugins/_shared/hestia_gate_core.py": "core_rev.py",
            "tools/shell_scope_reach_battery_test.py": "battery_rev.py",
            "tools/one_gate_decide_contract_test.py": "contract_held.py"}
    if not set(want).issubset(files):
        raise ValueError("patch omits a required core, battery or contract file")
    for name, lines in files.items():
        base = subprocess.run(["git", "-C", os.environ["HESTIA_1314_REPO"], "show",
                               f"2d79644f:{name}"], capture_output=True, text=True,
                              check=True).stdout
        got = apply(base, lines)
        if name in want:
            if got != (scratch / want[name]).read_text():
                raise ValueError(f"reconstructed bytes differ: {name}")
        elif name.endswith("hestia_gate_core.py"):
            core = (scratch / "core_rev.py").read_text()
            pieces = core.split("\n", 5)
            if len(pieces) != 6 or not pieces[-1] or pieces[-1] not in got:
                raise ValueError(f"mirror does not contain core: {name}")
        print(name, "checked" if name in want else "applies; mirror checked where applicable")


if __name__ == "__main__":
    main()
