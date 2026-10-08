#!/usr/bin/env python3
"""Compile the reviewed pricing functions verbatim in a temporary Rust harness.

No daemon is contacted. Only serde derives on the copied Bar enum are omitted.
The first two rows intentionally model the OLD producer wire as negative controls;
the sentinel and destination rows model the repaired producer output.
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
    for (label, act, targets, expected) in [
        ("unknown-variable", "Bash: touch /w/plugins/_shared/$TARGET", vec!["/w/plugins/_shared/$TARGET".to_string()], Bar::SingleApprover),
        ("alias", "Bash: touch /w/alias.txt", vec!["/w/alias.txt".to_string()], Bar::SingleApprover),
        ("glob-star-act", "Bash: rm /w/plugins/_shared/*.py", vec![], Bar::SovereignPlusPeer),
        ("glob-class-act", "Bash: rm /w/plugins/_shared/[pq]re_tool_use.py", vec![], Bar::SovereignPlusPeer),
        ("glob-class-target", "Edit -> act", vec!["/w/plugins/_shared/[pq]re_tool_use.py".to_string()], Bar::SovereignPlusPeer),
        ("unknown-sentinel-control", "Edit -> act", vec!["hestia:unpriceable:unenumerated".to_string()], Bar::SovereignPlusPeer),
        ("alias-destination-control", "Edit -> act", vec!["/w/plugins/_shared/hestia_single_gate.py".to_string()], Bar::SovereignPlusPeer),
        ("bracketed-literal", "Bash: ls [/w/hooks/pre_tool_use.py]", vec![], Bar::SovereignPlusPeer),
        ("unmatched-class", "Bash: rm /w/hooks/[xy]re_tool_use.py", vec![], Bar::SingleApprover),
    ] {
        let (bar, markers) = price(marker, Some(act), &targets);
        assert_eq!(bar, expected, "{label}");
        println!("{label}: {bar:?} {markers:?}");
    }
}
'''
with tempfile.TemporaryDirectory(prefix="codex-19509-price-") as tmp:
    source = Path(tmp) / "probe.rs"
    binary = Path(tmp) / "probe"
    source.write_text("#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]\n" + bar + functions + harness)
    subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
