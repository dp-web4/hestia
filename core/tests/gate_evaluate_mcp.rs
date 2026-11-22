use std::path::PathBuf;
use std::process::Command;

#[test]
fn gate_evaluate_is_callable_through_real_mcp() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let out = Command::new("python3")
        .arg(root.join("tools/gate_evaluate_mcp_test.py"))
        .arg(env!("CARGO_BIN_EXE_hestia"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "real MCP gate evaluation failed\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}
