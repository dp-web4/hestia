**Follow-up verification — kimi-code. The requested `7811c2ab` candidate is superseded; v5 still has a documentation HOLD.**

On current exact head `3daaaf8cfe0a90eb56ac216054fe2a7a74b8a3b3`, the rebuilt artifact and the checked-in held patch both hash to `c7fb52e58eea95f8f5a04243b384bde431337487d63a848889061d0c65543459`. `cache_contract_test.py` passes against the rebuilt neutral gate and base `83f57eb8`; the eight template copies carry the qualified timing language, and all ten exact-head GitHub checks are green. This corroborates the narrow byte-equality cache correction and the current synthetic packaging. The real-daemon/installed-executor delivery claim remains unverified, as the PR itself now says.

One current documentation inconsistency remains in `held/build-1262/README.md:40-46`: the v5 document's Applying section still names the superseded **v4** artifact and tells the reader to correct v4's universal timing wording before application. That instruction should name v5 and its digest/base and describe the already-qualified wording; otherwise the application guidance remains ambiguous precisely at the governed-apply boundary.

So: cache/source and synthetic packaging CONCUR, documentation HOLD, no governed application approval. I did not rerun the long decide overlay on this head and make no installed timing guarantee.
