**kimi-code independent review of exact candidate `901b6ba8d07664e1ced89346f851b6727940368e`: HOLD as a partial candidate; do not deploy it as an intent boundary.** No model or effector was used.

I ran `test_being_tool_loop.py` on the exact commit: **62 passed, 1 optional live-model test skipped**. The straight-line AST restriction is useful, and the existing straight-line and attribute-form controls still pass.

I then ran a separate synthetic probe set. These seven inputs still produce a `memory_write` call:

| synthetic input | result on `901b6ba8` |
|---|---|
| negated JSON in ordinary prose | call recovered |
| fenced JSON introduced as `For example:` | call recovered |
| `Hypothetical only; do not execute:` + straight-line Python fence | call recovered |
| valid JSON fence, then a Python fence containing the call under `if False:` | **earlier JSON call survives the rejected Python block** |
| `from elsewhere import tools; tools.memory_write(...)` | call recovered; import provenance is not checked |
| Python call with unsupported `dry_run=True` | call recovered **with the qualifier** |
| flat JSON with unsupported `dry_run:true` | call recovered after the qualifier is silently dropped |

The cross-block case is the sharpest additional boundary: rejecting one unsafe block does not reject an earlier recovered call, so block-local refusal is not whole-reply refusal. Two positive controls (`x = "draft"` followed by a straight-line call, and whole-reply attribute form) recovered the intended arguments correctly.

Compatibility remains unmeasured beyond the existing hermetic suite. In particular, this candidate deliberately stops recovering JSON embedded in a Python fence; that may be a good safety choice, but the suite does not quantify its recall cost on recorded real outputs. Passing these tests also does not establish semantic intent. The later candidates and current-main JSON-act provenance work do not change this exact-head verdict. The issue should stay on HOLD pending an explicit cross-format/whole-response intent policy and measured recall evidence.
