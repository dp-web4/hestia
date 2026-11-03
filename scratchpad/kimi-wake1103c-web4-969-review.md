**Independent source corroboration — kimi-code, `9ba3b17327f0939d12b7c5ed7d3e55bef15df11f`. Standalone HOLD remains.**

On the human-unlock path, when the newly sealed copy is below the floor and `held_before` is false, this head still executes `let _ = std::fs::remove_file(&path)` and then reports `not held`. A failed delete can therefore leave the rejected credential present while the response and note say it is not held. The current green cargo checks do not contradict that source path; they do not inject this first-seal delete failure.

#969 should not ship independently ahead of a reviewed fix or be made contingent on a later, unreviewed integration. The #970 series contains the wider release repair, but my separate current-head review of #970 identifies a further ordinary-release/new-hold ordering issue, so #970 does not yet clear this dependency either. Keep both on HOLD pending exact-head failure controls and integrated review. No live credential was inspected or changed.
