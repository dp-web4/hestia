#!/usr/bin/env python3
"""Compile the reviewed pricing functions verbatim in a temporary Rust harness.

No daemon is contacted. Only serde derives on the copied Bar enum are omitted.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
s = (root / "core/src/server/gate_escalation.rs").read_text()
bar = s[s.index("pub enum Bar {"):s.index("// The DECLARATION ORDER")]
functions = s[s.index("pub fn bar_for(marker:"):s.index("/// The longest resolved target recorded")]
harness = r'''
fn main() {
    let marker = "plugins/_shared";
    for (label, act, targets) in [
        ("unknown-variable", "Bash: touch /w/plugins/_shared/$TARGET", vec!["/w/plugins/_shared/$TARGET".to_string()]),
        ("alias", "Bash: touch /w/alias.txt", vec!["/w/alias.txt".to_string()]),
        ("glob-star-act", "Bash: rm /w/plugins/_shared/*.py", vec![]),
        ("glob-class-act", "Bash: rm /w/plugins/_shared/[pq]re_tool_use.py", vec![]),
        ("glob-class-target", "Edit -> act", vec!["/w/plugins/_shared/[pq]re_tool_use.py".to_string()]),
        ("unknown-sentinel-control", "Edit -> act", vec!["hestia:unpriceable:unenumerated".to_string()]),
        ("alias-destination-control", "Edit -> act", vec!["/w/plugins/_shared/hestia_single_gate.py".to_string()]),
    ] {
        let (bar, markers) = price(marker, Some(act), &targets);
        println!("{label}: {bar:?} {markers:?}");
    }
}
'''
with tempfile.TemporaryDirectory(prefix="codex-18784-price-") as tmp:
    source = Path(tmp) / "probe.rs"
    binary = Path(tmp) / "probe"
    source.write_text("#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]\n" + bar + functions + harness)
    subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
