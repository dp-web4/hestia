//! Hestia plugin SDK error types.

use serde_json::Value;
use thiserror::Error;

/// Error type for all Hestia SDK operations.
#[derive(Debug, Error)]
pub enum HestiaError {
    #[error("hestia: plugin must call connect() before invoking other methods")]
    NotConnected,

    #[error("hestia: session expired; call connect() again to renew")]
    SessionExpired,

    #[error("hestia: action denied by policy: {reason}")]
    PolicyDenied {
        reason: String,
        policy_id: Option<String>,
    },

    #[error("hestia: user declined credential request{}", suffix(.reason.as_deref()))]
    VaultDenied { reason: Option<String> },

    #[error("hestia: credential '{name}' not found in vault")]
    VaultNotFound { name: String },

    #[error("hestia: credential '{name}' not allowed under scope {scope:?} for this plugin")]
    VaultScopeMismatch { name: String, scope: Vec<String> },

    #[error("hestia: action {action_id} not found (begin_action required first)")]
    ActionNotFound { action_id: String },

    #[error("hestia: role '{role}' is not available to plugins")]
    InvalidRole { role: String },

    #[error("hestia: invalid response from server: {0}")]
    InvalidResponse(String),

    #[error("hestia: unknown tool: {tool}")]
    UnknownTool { tool: String },

    #[error("hestia: protocol or transport error: {0}")]
    Transport(String),

    #[error("hestia: unknown error code '{code}': {message}")]
    Unknown {
        code: String,
        message: String,
        data: Option<Value>,
    },
}

fn suffix(reason: Option<&str>) -> String {
    match reason {
        Some(r) => format!(": {}", r),
        None => String::new(),
    }
}

impl HestiaError {
    /// Map a Hestia error envelope `{code, message, data}` to a typed error.
    pub fn from_envelope(code: &str, message: &str, data: Option<&Value>) -> Self {
        let data_obj = data.and_then(|v| v.as_object());
        let field = |key: &str| -> Option<String> {
            data_obj
                .and_then(|m| m.get(key))
                .and_then(|v| v.as_str())
                .map(String::from)
        };
        let str_array = |key: &str| -> Vec<String> {
            data_obj
                .and_then(|m| m.get(key))
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        };

        match code {
            "hestia.not_connected" => HestiaError::NotConnected,
            "hestia.session_expired" => HestiaError::SessionExpired,
            "hestia.policy_denied" => HestiaError::PolicyDenied {
                reason: message.to_string(),
                policy_id: field("policy_id"),
            },
            "hestia.vault_denied" => HestiaError::VaultDenied {
                reason: Some(message.to_string()),
            },
            "hestia.vault_not_found" => HestiaError::VaultNotFound {
                name: field("name").unwrap_or_else(|| "?".to_string()),
            },
            "hestia.vault_scope_mismatch" => HestiaError::VaultScopeMismatch {
                name: field("name").unwrap_or_else(|| "?".to_string()),
                scope: str_array("requested_scope"),
            },
            "hestia.action_not_found" => HestiaError::ActionNotFound {
                action_id: field("action_id").unwrap_or_else(|| "?".to_string()),
            },
            "hestia.invalid_role" => HestiaError::InvalidRole {
                role: field("role").unwrap_or_else(|| "?".to_string()),
            },
            "hestia.unknown_tool" => HestiaError::UnknownTool {
                tool: field("tool").unwrap_or_else(|| "?".to_string()),
            },
            _ => HestiaError::Unknown {
                code: code.to_string(),
                message: message.to_string(),
                data: data.cloned(),
            },
        }
    }
}

pub type Result<T> = std::result::Result<T, HestiaError>;
