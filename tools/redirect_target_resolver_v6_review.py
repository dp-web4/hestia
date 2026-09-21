"""Reproduce notice 13422's v6 dissent without executing any governed write.

Run from any cwd: python3 tools/redirect_target_resolver_v6_review.py
The assertions pin the rejected candidate's behavior, not desired production behavior.
"""
import pathlib
import shlex
import tempfile

import redirect_resolver_battery as battery
import redirect_target_resolver_v6 as resolver


def main():
    g = battery.load("v6_review_governance", battery.BASE, battery.CLOSURE)
    shipped = g._bash_write_targets
    candidate, _ = resolver.make(g)

    def classify(command, impl):
        g._bash_write_targets = impl
        return g.classify("Bash", {"command": command},
                          cwd=str(battery.ROOT)).classification

    cases = [(name, prefix) for name, prefix in battery.BINDINGS
             if name.startswith("rebind-")]
    assert len(cases) == 8
    for name, prefix in cases:
        # A semicolon keeps the read case separate from the pre-existing newline
        # here-string bug. The final write only reaches the classifier.
        command = prefix + "; " + battery.WRITES[0][1]
        destinations = battery.bash_destinations(prefix + "; " + battery.ORACLE)
        assert destinations == [battery.MARK], (name, destinations)
        before, after = classify(command, shipped), classify(command, candidate)
        assert (before, after) == ("write", "read"), (name, before, after)
        print(f"CONFIRMED {name}: bash=governed shipped={before} v6={after}")

    # Plain command position is a control for the wrapper/quoting failure.
    direct = ('OUT=' + battery.SAFE + '; n=OU; printf -v "${n}T" %s '
              + battery.MARK + '; ' + battery.WRITES[0][1])
    assert classify(direct, candidate) == "write"
    safe = 'OUT=' + battery.SAFE + '; ' + battery.WRITES[0][1]
    assert classify(safe, candidate) == "read"

    # Existing defect: the heredoc scanner starts at the SECOND '<' in '<<<',
    # then drops the real command on the next line. Confirm against both versions.
    read_prefix = dict(cases)["rebind-read-builtin"]
    newline = read_prefix + "\n" + battery.WRITES[0][1]
    assert battery.bash_destinations(read_prefix + "\n" + battery.ORACLE) == [battery.MARK]
    assert classify(newline, shipped) == classify(newline, candidate) == "read"
    print("CONFIRMED pre-existing here-string/newline defect in both classifiers")

    # Only the pretty-printer sees these sources. A write to a disposable sentinel
    # would show that parse-only processing executed supplied shell text.
    with tempfile.TemporaryDirectory(prefix="v6-noexec-") as directory:
        sentinel = pathlib.Path(directory) / "sentinel"
        write = ": > " + shlex.quote(str(sentinel))
        sources = {
            "simple": write,
            "command-substitution": "x=$(" + write + ")",
            "process-substitution": "cat <(" + write + ")",
            "arithmetic-index": "a[$(" + write + "; echo 0)]=x",
            "heredoc": "cat <<EOF\n$(" + write + ")\nEOF",
            "coproc": "coproc { " + write + "; }",
            "trap": "trap '" + write + "' EXIT",
            "function": "f() { " + write + "; }; f",
        }
        for name, source in sources.items():
            assert resolver.pretty(source) is not None, (name, "parse failed")
            assert not sentinel.exists(), (name, "executed")
    print("PASS 2 classification controls and 8 parse-only execution sentinels")
    print("Sentinels are finite evidence, not a proof of non-execution.")


if __name__ == "__main__":
    main()
