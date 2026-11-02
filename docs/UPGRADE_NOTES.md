# Operator upgrade notes

## Standing-scope authority digest: recursive grants

**Release status:** This note describes the change proposed in
[Hestia #1478](https://github.com/dp-web4/hestia/pull/1478). It applies only when a release
actually contains that change; it does not say that a release or upgrade has occurred.

The authority digest now includes whether each standing grant is recursive. For an otherwise
unchanged standing-scope record containing one or more recursive grants, its digest calculated
by the new format will differ from the digest calculated by the old format. Rows for exact
grants retain their previous digest spelling, and the society-floor digest is not changed by
this patch. The patch changes audit calculations; it does not create, revoke, widen or narrow
grants or change gate enforcement.

For an upgrade review:

1. Preserve the pre-upgrade record and digest, along with the version that produced them.
2. Compare the actual standing-scope records and their recursive flags, not just hashes
   produced by different versions. Calculate both sides with the same format when checking
   a runtime projection against its durable record.
3. Record the format transition with the new digest. A changed hash alone is not evidence of
   a newly granted path; nor is a format transition a reason to dismiss a mismatch in the
   underlying records or any other unexplained change. Investigate those independently.

The separately tracked [standing-refusal audit gap](https://github.com/dp-web4/hestia/issues/1476)
is not fixed by this change. A matching authority digest is not evidence that refusals match.
