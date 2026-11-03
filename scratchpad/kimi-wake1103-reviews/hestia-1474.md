**kimi-code independent reproduction on current main `83f57eb8dc3da6b3e44220b8e527207d488344dd`: CONFIRMED.** I wrote a fresh synthetic harness through the production snapshot mapper, policy resolver, `normalized_event`, and `evaluate`; I did not use the earlier test commits. No remote repository, live grant, or governed file was touched.

Key results:

| policy / act | result |
|---|---|
| no grant, `foreign-owner/project` read or delete | deny `mrh.repo` |
| recursive local `<ws>/project`, same foreign read or delete | **ALLOW** |
| exact local `<ws>/project`, same foreign read or delete | deny `mrh.repo` |
| no grant, local file read | deny `mrh.path` |
| recursive local grant, file inside / sibling | allow / deny |
| explicit qualified `me/project`, own / foreign read | allow / deny |

The provenance collision is direct: `_scope_entry_for_grant` turns the daemon-derived recursive local path into bare `project`, and `evaluate` accepts that bare spelling as the legacy owner-agnostic repository grant. The denial text saying a path grant never reaches a remote repository is therefore false for this common shape.

I also tested the proposed provenance-preserving direction by monkeypatching only the mapper in the synthetic process to emit `path:<ws>/project/**`. With that spelling, foreign remote read and delete deny, the local inside read still allows, and the sibling still denies. An explicitly supplied legacy bare `project` remains owner-agnostic, while the qualified grant remains owner-bound. This supports separating **path-derived entries** from **explicit legacy repository entries** rather than silently deleting legacy authority.

This is not approval of a deployable patch. The existing serialization-contract change, downstream consumers, mode/expiry/revocation, symlink behavior, full current-base artifact, exact-head CI, independent review, and governed operator decision still need to be addressed. Harness: `scratchpad/kimi-wake1103-hestia1474-repro.py` on the review branch.
