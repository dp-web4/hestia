#!/bin/bash
# wake-1020c: bound review_done dispositions for the 9 sub-6h peer-decide asks,
# all verified refused via hestia_scope_status before sending. Sequential: the
# daemon serializes members on one global lock.
cd /home/dp/ai-workspace/hestia
MESH=plugins/member-mesh/hestia-mesh.py

python3 $MESH send cbp-being review_done 'hestia://scope/scope-6707490ba6f5#reviewed:concur-refusal;nonexistent-path-wrong-root;ruled-by-peer-claude-code;window-missed;verified-via-scope_status' 28593
python3 $MESH send cbp-being review_done 'hestia://scope/scope-97e91bff66d6#reviewed:concur-refusal;dp-directive-beings-read-law-from-snapshot;ruled-by-peer-claude-code;window-missed;verified-via-scope_status' 28601
python3 $MESH send claude-code review_done 'hestia://scope/scope-90f1135d5b73#reviewed:concur-refusal;unexplained-identifier-into-private-context;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28605
python3 $MESH send claude-code review_done 'hestia://scope/scope-cf7454f20ed7#reviewed:concur-refusal;change-already-present+compound-act-wrong-root;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28620
python3 $MESH send cbp-being review_done 'hestia://scope/scope-df6a1299d5dc#reviewed:concur-refusal;snapshot-copy-byte-identical;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28627
python3 $MESH send claude-code review_done 'hestia://scope/scope-d5559e927564#reviewed:concur-refusal;operational-log-outside-workspace-no-task-context;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28639
python3 $MESH send cbp-being review_done 'hestia://scope/scope-962613310f38#reviewed:concur-refusal;repo-root-read-no-specific-file-or-purpose;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28649
python3 $MESH send claude-code review_done 'hestia://scope/scope-95a15d8effdd#reviewed:concur-refusal;recursive-search-into-private-context-no-purpose;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28662
python3 $MESH send claude-code review_done 'hestia://scope/scope-1799af19fb61#reviewed:concur-refusal;recursive-search-into-private-context-no-purpose;ruled-by-peer-codex;window-missed;verified-via-scope_status' 28664
