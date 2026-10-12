// Compile the production AppState implementation without Tauri's desktop dependencies.
// Vault/signing are stubs; authentication uses production code. No real credentials
// or daemon are used.
fn main() {
    let file = "../../../app/src-tauri/src/lib.rs";
    let text = std::fs::read_to_string(file).unwrap();
    let start = text.find("use std::path::PathBuf;").unwrap();
    let end = text.find("fn config_path(").unwrap();
    let state = text[start..end].replace("use tauri::Manager;", "");
    let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::write(output.join("state.rs"), state).unwrap();
    println!("cargo:rerun-if-changed={file}");
}
