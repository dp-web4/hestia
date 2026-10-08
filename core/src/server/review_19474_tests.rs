// Review-only recovery regressions ported from review 19153.
// Assertions specify correct recovery; both fail on PR #1272 bbf05a94.
    // Review 19153 first established these recovery failures on f4c6629.
    fn review_entity_file(state: &super::super::state::ServerState, member: &str) -> std::path::PathBuf {
        use sha2::{Digest, Sha256};
        let key = state.trust_entity_key(member, crate::reputation::DEFAULT_CONSTELLATION_ROLE);
        let hash = format!("{:x}", Sha256::digest(key.as_bytes()));
        state.home.join("trust").join(format!("{}.json", &hash[..16]))
    }

    #[tokio::test]
    #[ignore = "known inherited recovery regression; run explicitly for review 19474"]
    async fn review_19474_a_lost_entity_under_a_surviving_checkpoint_is_replayed() {
        use crate::storage::durability::durable_scope;
        let (dir, state) = state_with_safety().await;
        let mut args = witness_args("gemini", "deny");
        args["action_id"] = json!(Uuid::new_v4().to_string());
        let (out, durable) = durable_scope(tool_witness_decision(&state, &args)).await;
        durable.unwrap();
        assert_eq!(out.unwrap()["charged"], true);
        let path = {
            let s = state.lock().await;
            s.trust_store.persister().flush_blocking();
            review_entity_file(&s, "gemini")
        };
        assert_eq!(grain_actions(&state, "gemini").await, 1);
        drop(state);
        // Model an independently lost unsynced cache file with projection.json surviving.
        // No chain rows are changed; the acknowledged decision remains durable.
        assert!(dir.path().join("trust/projection.json").exists());
        std::fs::remove_file(path).unwrap();
        let reopened = reopen_with_safety(&dir).await;
        assert_eq!(grain_actions(&reopened, "gemini").await, 1, "the checkpoint's manifest no longer verifies: replay from the epoch");
        let retry = tool_witness_decision(&reopened, &args).await.unwrap();
        assert_eq!(retry["charged"], false, "the charge is on the chain once");
        assert_eq!(grain_actions(&reopened, "gemini").await, 1);
    }

    #[tokio::test]
    #[ignore = "known inherited recovery regression; run explicitly for review 19474"]
    async fn review_19474_a_partial_first_batch_is_not_mistaken_for_legacy() {
        use crate::storage::durability::durable_scope;
        let (dir, state) = state_with_safety().await;
        let persister = { state.lock().await.trust_store.persister().clone() };
        let hold = persister.hold_for_test();
        for member in ["gemini", "codex"] {
            let mut args = witness_args(member, "deny");
            args["action_id"] = json!(Uuid::new_v4().to_string());
            let (out, durable) = durable_scope(tool_witness_decision(&state, &args)).await;
            durable.unwrap();
            assert_eq!(out.unwrap()["charged"], true);
        }
        let (keep, lose) = {
            let s = state.lock().await;
            (review_entity_file(&s, "gemini"), review_entity_file(&s, "codex"))
        };
        drop(hold);
        persister.flush_blocking();
        drop(persister);
        drop(state);
        // Exact cache shape of a process crash part-way through the FIRST batch: one v2
        // entity rename completed; the other entity and last-written manifest did not.
        assert!(keep.exists());
        std::fs::remove_file(lose).unwrap();
        std::fs::remove_file(dir.path().join("trust/projection.json")).unwrap();
        let reopened = reopen_with_safety(&dir).await;
        assert_eq!(grain_actions(&reopened, "gemini").await, 1);
        assert_eq!(grain_actions(&reopened, "codex").await, 1, "a v2 cache is replayed, not adopted at the head");
        let s = reopened.lock().await;
        assert_eq!(s.trust_store.projection_since(), Some(0), "the fresh epoch stays 0");
    }

