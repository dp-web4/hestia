//! Plugin seam — a generic `ToolPlugin` / `PluginCtx` registry.
//!
//! Lets tools register into Hestia's MCP/channel surface: core owns authn +
//! gating + sealing, plugins own the handler. The interface mirrors the hub's
//! generic seam so a plugin crate can implement `ToolPlugin` once and load on
//! either side.
//!
//! The interface is deliberately identical to `hub-plugin` so a plugin crate
//! can implement `ToolPlugin` once and be loaded on either side.

use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use uuid::Uuid;

pub type LctId = Uuid;

#[derive(Clone, Debug)]
pub struct Caller {
    pub lct: LctId,
    pub role: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ToolScope {
    Bounded,
    Unbounded,
}

#[derive(Debug)]
pub enum PluginError {
    Denied(String),
    BadRequest(String),
    Unavailable(String),
    Internal(String),
}

impl std::fmt::Display for PluginError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PluginError::Denied(m) => write!(f, "denied: {m}"),
            PluginError::BadRequest(m) => write!(f, "bad request: {m}"),
            PluginError::Unavailable(m) => write!(f, "unavailable: {m}"),
            PluginError::Internal(m) => write!(f, "internal: {m}"),
        }
    }
}
impl std::error::Error for PluginError {}

#[async_trait]
pub trait PluginCtx: Send + Sync {
    fn caller(&self) -> &Caller;
    fn owner_lct(&self) -> LctId;
    fn sign(&self, bytes: &[u8]) -> Result<Vec<u8>, PluginError>;
    fn owner_pubkey_hex(&self) -> String;
    fn state(&self) -> &Value;
    async fn send_to_peer(&self, peer: LctId, payload: &[u8]) -> Result<Vec<u8>, PluginError>;
}

#[async_trait]
pub trait ToolPlugin: Send + Sync {
    fn name(&self) -> &str;
    fn policy_action(&self) -> String {
        format!("read:{}", self.name())
    }
    fn scope(&self) -> ToolScope {
        ToolScope::Bounded
    }
    async fn handle(&self, ctx: &dyn PluginCtx, args: &Value) -> Result<Value, PluginError>;
}

pub trait PolicyGate: Send + Sync {
    fn allow(&self, role: &str, action: &str) -> bool;
}

pub trait Scoper: Send + Sync {
    fn bound(&self, role: &str, result: Value) -> Value;
}

#[derive(Default)]
pub struct PluginRegistry {
    tools: HashMap<String, Arc<dyn ToolPlugin>>,
}

impl PluginRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self, plugin: Arc<dyn ToolPlugin>) {
        self.tools.insert(plugin.name().to_string(), plugin);
    }

    pub fn names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.tools.keys().cloned().collect();
        v.sort();
        v
    }

    pub async fn dispatch(
        &self,
        ctx: &dyn PluginCtx,
        tool: &str,
        args: &Value,
        gate: &dyn PolicyGate,
        scoper: &dyn Scoper,
    ) -> Result<Value, PluginError> {
        let plugin = self
            .tools
            .get(tool)
            .ok_or_else(|| PluginError::BadRequest(format!("unknown tool: {tool}")))?;
        let role = ctx.caller().role.clone();
        let action = plugin.policy_action();
        if !gate.allow(&role, &action) {
            return Err(PluginError::Denied(format!("{action} denied for role {role}")));
        }
        let result = plugin.handle(ctx, args).await?;
        Ok(match plugin.scope() {
            ToolScope::Bounded => scoper.bound(&role, result),
            ToolScope::Unbounded => result,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct EchoPlugin;

    #[async_trait]
    impl ToolPlugin for EchoPlugin {
        fn name(&self) -> &str { "echo" }
        fn scope(&self) -> ToolScope { ToolScope::Unbounded }
        async fn handle(&self, _ctx: &dyn PluginCtx, args: &Value) -> Result<Value, PluginError> {
            Ok(args.clone())
        }
    }

    struct AllowAll;
    impl PolicyGate for AllowAll {
        fn allow(&self, _role: &str, _action: &str) -> bool { true }
    }

    struct NoScope;
    impl Scoper for NoScope {
        fn bound(&self, _role: &str, result: Value) -> Value { result }
    }

    struct StaticCtx {
        caller: Caller,
    }

    #[async_trait]
    impl PluginCtx for StaticCtx {
        fn caller(&self) -> &Caller { &self.caller }
        fn owner_lct(&self) -> LctId { Uuid::nil() }
        fn sign(&self, _bytes: &[u8]) -> Result<Vec<u8>, PluginError> { Ok(vec![0; 64]) }
        fn owner_pubkey_hex(&self) -> String { "00".repeat(32) }
        fn state(&self) -> &Value { &Value::Null }
        async fn send_to_peer(&self, _peer: LctId, _payload: &[u8]) -> Result<Vec<u8>, PluginError> {
            Err(PluginError::Unavailable("no peers".into()))
        }
    }

    #[tokio::test]
    async fn test_registry_dispatch() {
        let mut reg = PluginRegistry::new();
        reg.register(Arc::new(EchoPlugin));

        let ctx = StaticCtx { caller: Caller { lct: Uuid::nil(), role: "citizen".into() } };
        let args = serde_json::json!({"hello": "world"});
        let result = reg.dispatch(&ctx, "echo", &args, &AllowAll, &NoScope).await.unwrap();
        assert_eq!(result, args);
    }

    #[tokio::test]
    async fn test_registry_unknown_tool() {
        let reg = PluginRegistry::new();
        let ctx = StaticCtx { caller: Caller { lct: Uuid::nil(), role: "citizen".into() } };
        let result = reg.dispatch(&ctx, "nonexistent", &Value::Null, &AllowAll, &NoScope).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_registry_denied() {
        let mut reg = PluginRegistry::new();
        reg.register(Arc::new(EchoPlugin));

        struct DenyAll;
        impl PolicyGate for DenyAll {
            fn allow(&self, _: &str, _: &str) -> bool { false }
        }

        let ctx = StaticCtx { caller: Caller { lct: Uuid::nil(), role: "external".into() } };
        let result = reg.dispatch(&ctx, "echo", &Value::Null, &DenyAll, &NoScope).await;
        assert!(matches!(result, Err(PluginError::Denied(_))));
    }
}
