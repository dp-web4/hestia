use hestia::policy::{GatedResource, PolicyAction, PolicyEngine, ResourceMode};
use serde_json::json;

fn engine() -> PolicyEngine {
    let resource: GatedResource = serde_json::from_value(json!({
        "id": "cargo",
        "description": "serialize cargo and protect scratch",
        "mode": ResourceMode::Enforce,
        "consumers": [{
            "tools": ["Bash"],
            "target_patterns_scope": "executable_positions",
            "target_patterns_are_regex": true,
            "target_patterns": ["^cargo(-serial)?\\s+(build|test|check)\\b"]
        }],
        "floors": [{
            "id": "scratch",
            "probe": {"kind": "disk_free", "path": "/"},
            "min": 60000
        }],
        "runner": {"usage": "cargo-serial <cargo args>", "pattern": "^cargo-serial$"},
        "on_unknown": "refuse"
    }))
    .unwrap();
    let mut config = hestia::policy::get_preset("safety").unwrap().config;
    config.resources = vec![resource];
    PolicyEngine::new(config)
}

fn routed(cmd: &str) -> Option<Option<bool>> {
    let action = PolicyAction {
        tool_name: "Bash",
        category: "command",
        target: Some(cmd),
        full_command: Some(cmd),
    };
    engine()
        .matching_resources(&action)
        .first()
        .map(|(_, routed)| *routed)
}

#[test]
fn env_unset_option_does_not_hide_the_cargo_consumer() {
    assert_eq!(routed("env -u CARGO_TERM_COLOR cargo build"), Some(Some(false)));
}

#[test]
fn timeout_signal_option_does_not_hide_the_cargo_consumer() {
    assert_eq!(routed("timeout -s KILL 30 cargo test"), Some(Some(false)));
}

#[test]
fn sudo_user_option_does_not_hide_the_cargo_consumer() {
    assert_eq!(routed("sudo -u dp cargo check"), Some(Some(false)));
}

#[test]
fn shell_escape_in_the_executable_does_not_hide_the_cargo_consumer() {
    assert_eq!(routed(r"c\argo build"), Some(Some(false)));
}

#[test]
fn shell_negation_does_not_hide_the_cargo_consumer() {
    assert_eq!(routed("! cargo test"), Some(Some(false)));
}
