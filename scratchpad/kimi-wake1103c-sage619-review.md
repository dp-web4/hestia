**Independent candidate-chain verification — kimi-code. CONCUR on the four requested slices and the final narrow integration.**

I ran the exact candidates locally with synthetic homes:

| Candidate | Focus | Result |
|---|---|---|
| `e3e8304ec` | partial-effect recovery | 167 passed across retirement, settled state and dispatcher |
| `cf0eff3a2` | question+answer topic selector | 13 passed |
| `b98430a4d` | broad-retirement confirmation | 25 passed |
| `40bfd0c45` | integrated confirmation + recovery | 32 passed |
| final PR head `b948045ca` | narrow integration after owner recut | 19 passed |

The recovery candidate preserves evidence and reports uncertain/partial effects rather than claiming a clean no-op. The selector stops shared evidence citations from selecting unrelated conclusions. The broad confirmation is rebound under the home lock to the observed source, and the integrated recovery fixtures actually pass through preview confirmation before reaching their injected failures. The final owner recut carries those three #619-specific repairs without the separate fleet-wide home-I/O hardening.

The merged PR's hosted checks are green; merge commit is `1f0ff3510b7af1f065df57cf592a84bcf208c2f8`. My verdict covers these requested slices, not a new audit of every shared home writer. The disclosed process-local confirmation, preview visibility, archive privacy, noncooperating-writer and crash-consistency limits remain outside this GO. No live home or runtime was touched.
