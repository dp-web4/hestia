//! Review reproductions: assertions describe the bugs on 2b5c57f / 9a58e0c.
use hestia::storage::{durability::durable_scope_observing, trust::TrustStore};

#[tokio::test]
async fn review_cached_trust_read_acknowledges_unpersisted_value() {
    let dir = tempfile::tempdir().unwrap();
    let store = TrustStore::open(dir.path(), [42; 32]).unwrap();
    store.get("review").unwrap();
    store.persister().flush_blocking().unwrap();
    let hold = store.persister().hold_for_test();
    store.update("review", false, 0.5).unwrap();
    let (seen, durable) = tokio::time::timeout(
        std::time::Duration::from_secs(1),
        durable_scope_observing(async { store.get("review").unwrap() }),
    ).await.expect("BUG: read replies while trust persistence is held");
    durable.unwrap();
    let disk = TrustStore::open(dir.path(), [42; 32]).unwrap();
    assert_eq!(seen.action_count, 1);
    assert_eq!(disk.get("review").unwrap().action_count, 0);
    println!("acknowledged count={}, reopened count=0 with persister held", seen.action_count);
    drop(hold);
}

#[test]
fn review_concurrent_policy_evaluations_exceed_limit() {
    use hestia::policy::{PolicyAction, PolicyConfig, PolicyDecision, PolicyEngine};
    use std::sync::{Arc, Barrier};
    let config: PolicyConfig = serde_json::from_value(serde_json::json!({
        "name": "review", "version": "1", "enforce": true, "default_policy": "allow",
        "rules": [{"id": "one", "name": "one", "priority": 1,
          "match": {"tools": ["Read"], "rate_limit": {"max_count": 1, "window_ms": 60000}},
          "decision": "deny"}]
    })).unwrap();
    for round in 0..1000 {
        let engine = PolicyEngine::new(config.clone());
        let start = Arc::new(Barrier::new(16));
        let allowed: usize = std::thread::scope(|scope| {
            let jobs: Vec<_> = (0..16).map(|_| {
                let engine = engine.clone();
                let start = start.clone();
                scope.spawn(move || {
                    start.wait();
                    usize::from(engine.evaluate(&PolicyAction { tool_name: "Read", category: "file_read",
                        target: Some("/tmp/example"), full_command: None }).decision == PolicyDecision::Allow)
                })
            }).collect();
            jobs.into_iter().map(|j| j.join().unwrap()).sum()
        });
        if allowed > 1 {
            println!("round {round}: max_count=1 but allowed={allowed}");
            return;
        }
    }
    panic!("race not reproduced in 1000 rounds; this is a scheduler-dependent reproduction");
}
