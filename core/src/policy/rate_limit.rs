//! Sliding-window rate limiter for policy rules.
//!
//! Memory-only, per-daemon-process. Same shape as `rate_limiter.py`:
//!
//! - `check(key, max, window_ms)` — would a new firing be under the limit?
//! - `record(key)` — record a firing
//! - `prune(window_ms)` — drop expired entries globally
//!
//! Time uses Unix-epoch milliseconds (`SystemTime::UNIX_EPOCH`). The
//! limiter is thread-safe via an internal `Mutex`.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RateLimitResult {
    pub allowed: bool,
    pub current: u32,
    pub limit: u32,
}

#[derive(Debug, Default)]
pub struct RateLimiter {
    windows: Mutex<HashMap<String, Vec<u64>>>,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

impl RateLimiter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Returns whether a new firing would be under the limit. Prunes
    /// expired entries as a side effect.
    pub fn check(&self, key: &str, max_count: u32, window_ms: u64) -> RateLimitResult {
        let now = now_ms();
        let cutoff = now.saturating_sub(window_ms);
        let mut guard = self.windows.lock().unwrap();
        let entry = guard.entry(key.to_string()).or_default();
        entry.retain(|t| *t > cutoff);
        let current = entry.len() as u32;
        RateLimitResult {
            allowed: current < max_count,
            current,
            limit: max_count,
        }
    }

    /// Record a new firing for the key.
    pub fn record(&self, key: &str) {
        let now = now_ms();
        let mut guard = self.windows.lock().unwrap();
        guard.entry(key.to_string()).or_default().push(now);
    }

    /// Drop expired entries across all keys. Returns the count of
    /// dropped entries.
    pub fn prune(&self, window_ms: u64) -> usize {
        let cutoff = now_ms().saturating_sub(window_ms);
        let mut guard = self.windows.lock().unwrap();
        let mut pruned = 0usize;
        let mut to_remove = Vec::new();
        for (key, ts) in guard.iter_mut() {
            let before = ts.len();
            ts.retain(|t| *t > cutoff);
            pruned += before - ts.len();
            if ts.is_empty() {
                to_remove.push(key.clone());
            }
        }
        for k in to_remove {
            guard.remove(&k);
        }
        pruned
    }

    pub fn count(&self, key: &str) -> u32 {
        let guard = self.windows.lock().unwrap();
        guard.get(key).map(|v| v.len() as u32).unwrap_or(0)
    }

    pub fn key_count(&self) -> usize {
        let guard = self.windows.lock().unwrap();
        guard.len()
    }

    /// Stable rate-limit key per rule + context. Mirrors
    /// `RateLimiter.make_key` from `rate_limiter.py`.
    pub fn make_key(rule_id: &str, tool_or_category: &str) -> String {
        format!("ratelimit:{rule_id}:{tool_or_category}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread::sleep;
    use std::time::Duration;

    #[test]
    fn allow_until_limit() {
        let l = RateLimiter::new();
        for _ in 0..5 {
            let r = l.check("k", 5, 60_000);
            assert!(r.allowed);
            l.record("k");
        }
        let r = l.check("k", 5, 60_000);
        assert!(!r.allowed);
        assert_eq!(r.current, 5);
        assert_eq!(r.limit, 5);
    }

    #[test]
    fn expired_entries_pruned() {
        let l = RateLimiter::new();
        l.record("k");
        sleep(Duration::from_millis(30));
        let r = l.check("k", 2, 10);
        assert_eq!(r.current, 0); // 30ms > 10ms window → pruned
        assert!(r.allowed);
    }

    #[test]
    fn distinct_keys_dont_interfere() {
        let l = RateLimiter::new();
        for _ in 0..5 {
            l.record("a");
        }
        let r_b = l.check("b", 5, 60_000);
        assert!(r_b.allowed);
        assert_eq!(r_b.current, 0);
    }

    #[test]
    fn prune_drops_empty_keys() {
        let l = RateLimiter::new();
        l.record("k");
        sleep(Duration::from_millis(20));
        let pruned = l.prune(5);
        assert_eq!(pruned, 1);
        assert_eq!(l.key_count(), 0);
    }

    #[test]
    fn make_key_is_stable() {
        assert_eq!(
            RateLimiter::make_key("rule-1", "tool:Bash"),
            "ratelimit:rule-1:tool:Bash"
        );
    }
}
