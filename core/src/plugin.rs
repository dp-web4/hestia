//! Plugin seam — re-exported from the shared public `hub-plugin` crate.
//!
//! Hestia and the hub use the **same** generic seam: core owns authn + gating +
//! sealing, plugins own the handler, dispatched `gate → handle → scope`. This
//! used to be a hand-maintained copy of `hub-plugin`'s interface; now that
//! `hub-plugin` is a public open-core crate, we consume it directly so a plugin
//! crate can `impl ToolPlugin` **once** and load on either side — which this
//! module's prior copy only aspired to.
//!
//! The seam is scale-agnostic: `PluginCtx::signer_lct()` / `signer_pubkey_hex()`
//! return the **society** LCT in a hub and the **owner** LCT in a person-scale
//! Hestia node (the fractal). `crate::plugin::*` and `crate::PluginRegistry`
//! keep their existing paths via this re-export — no call-site churn.

pub use hub_plugin::*;
