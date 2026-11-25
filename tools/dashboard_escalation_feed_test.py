#!/usr/bin/env python3
"""Escalations render once, with current disposition and the terminal ruling hash (#869).

The rows come from `dashboard_escalation_feed_fixture.json`, which is the `/api/dashboard`
snapshot the daemon serves after real opens, peer rulings, a self-withdrawal and one open
left pending. `handler::tests::the_dashboard_feed_fixture_matches_what_the_daemon_writes`
holds that file to the real writers, so a key the page reads but no writer records (the
first version read `granted` on rulings and `escalation_id` on pending items) fails here.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

ui = Path("core/src/server/dashboard/index.html").read_text(encoding="utf-8")
fixture = Path("tools/dashboard_escalation_feed_fixture.json").read_text(encoding="utf-8")
failures = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def function_source(name):
    match = re.search(rf"function {name}\([^)]*\) \{{.*?\n  \}}\n", ui, re.S)
    check(f"{name} is defined", match is not None)
    return match.group(0) if match else ""


check("the feed projects through the snapshot's live pending set",
      "projectEscalations(source, livePendingIds(lastData))" in ui)
# Snapshot consistency (NOVA 11-22): the pending set the projection reads must come from the
# SAME `/api/dashboard` response as the rows it projects. `renderFeed` reads pending from
# `lastData`, so every caller must pass that snapshot's own `recent`, and `lastData` must be
# assigned before the render that uses it.
feed_calls = re.findall(r"renderFeed\(([^)]*)\);", ui)
check("every renderFeed call passes the current snapshot's own recent rows",
      feed_calls and all(a in ("data.recent", "lastData.recent") for a in feed_calls), feed_calls)
check("lastData is the snapshot being rendered (assigned before rerender)",
      re.search(r"lastData = data;\s*\n\s*rerender\(data\);", ui) is not None)
check("the renderer consumes the escalation view", "if (escView)" in ui)
check("the event label says escalation", "escView ? 'escalation' : e.event_type" in ui)
check("the feed detail is rendered only through escapeHtml",
      'title="${escapeHtml(hover || detail)}"' in ui and "${escapeHtml(detail)}" in ui)

node = shutil.which("node")
check("node is available to execute the projection", node is not None)
if node:
    js = (function_source("escalationView") + function_source("livePendingIds")
          + function_source("projectEscalations") + function_source("escapeHtml")
          + "const fx = " + fixture + ";\n" + r"""
const rows = id => fx.recent.filter(e => e.escalation_id === id);
const only = (id, type) => rows(id).filter(e => e.event_type === type);
const view = list => list.map(e => ({hash: e.hash, plugin_id: e.plugin_id, ...e.escalation_view}));
const none = new Set();
const live = livePendingIds(fx);
// Expiry and claim rows are not driven by the fixture test (a lapse needs the clock, a claim
// needs the gated write re-issued); these carry an open row's keys under the writer's type.
const asType = (e, event_type, extra) => ({...e, event_type, ...extra});
const approvedOpen = only('a0a0a0a0approved', 'gate_escalation_opened')[0];
const hostile = {...approvedOpen, marker: '<img src=x onerror=alert(1)>'};
const hostileView = projectEscalations([hostile], none)[0].escalation_view;
console.log(JSON.stringify({
  livePending: [...live],
  all: view(projectEscalations(fx.recent, live)),
  allOldestFirst: view(projectEscalations([...fx.recent].reverse(), live)),
  approved: view(projectEscalations(rows('a0a0a0a0approved'), none)),
  denied: view(projectEscalations(rows('d0d0d0d0denied00'), none)),
  withdrawn: view(projectEscalations(rows('w0w0w0w0withdrwn'), none)),
  pending: view(projectEscalations(rows('p0p0p0p0pending0'), live)),
  offRecord: view(projectEscalations(rows('p0p0p0p0pending0'), none)),
  rulingOnly: view(projectEscalations(only('a0a0a0a0approved', 'gate_escalation_decided'), none)),
  rulingOnlyForAsker: projectEscalations(only('d0d0d0d0denied00', 'gate_escalation_decided'), none)
    .filter(e => e.plugin_id === 'claude-code').length,
  claimOnly: view(projectEscalations([asType(approvedOpen, 'gate_escalation_claimed', {chain_position: 99})], none)),
  claimAfterRuling: view(projectEscalations(
    [asType(approvedOpen, 'gate_escalation_claimed', {chain_position: 99, hash: 'claim'}),
     ...rows('a0a0a0a0approved')], none)),
  expired: view(projectEscalations([asType(approvedOpen, 'gate_escalation_expired', {chain_position: 99, lapse_kind: 'undecided'})], none)),
  expiredNoKind: view(projectEscalations([asType(approvedOpen, 'gate_escalation_expired', {chain_position: 99})], none)),
  hostileDetail: escapeHtml(hostileView.detail),
  // NOVA 11-22: more than one eligible terminal event, in BOTH array orders. A later ruling
  // (a re-decide after appeal, or a lapse recorded after a ruling) is the current status.
  twoRulings: [false, true].map(rev => {
    const later = {...only('a0a0a0a0approved', 'gate_escalation_decided')[0],
      chain_position: 50, hash: 'later-ruling', status: 'denied', decided_by: 'dp',
      decided_via: 'operator_session'};
    const list = [later, ...rows('a0a0a0a0approved')];
    return view(projectEscalations(rev ? list.reverse() : list, none));
  }),
  rulingThenExpiry: [false, true].map(rev => {
    const list = [asType(approvedOpen, 'gate_escalation_expired', {chain_position: 51, hash: 'expiry', lapse_kind: 'approved_unclaimed'}),
      ...rows('a0a0a0a0approved')];
    return view(projectEscalations(rev ? list.reverse() : list, none));
  }),
  twoClaims: [false, true].map(rev => {
    const list = [asType(approvedOpen, 'gate_escalation_claimed', {chain_position: 60, hash: 'claim-new'}),
      asType(approvedOpen, 'gate_escalation_claimed', {chain_position: 55, hash: 'claim-old'})];
    return view(projectEscalations(rev ? list.reverse() : list, none));
  }),
  // A feed crossing a page/window boundary: the newer page holds the ruling and a claim, the
  // older page the open. Every way the pages can be joined must pick the same row.
  acrossPages: (() => {
    const claim = asType(approvedOpen, 'gate_escalation_claimed', {chain_position: 70, hash: 'claim'});
    const newer = [claim, ...only('a0a0a0a0approved', 'gate_escalation_decided')];
    const older = only('a0a0a0a0approved', 'gate_escalation_opened');
    return [[...newer, ...older], [...older, ...newer], [...older, ...[...newer].reverse()],
            newer].map(list => view(projectEscalations(list, none)));
  })(),
  // The pending set is read at fold time, the feed may be an earlier read: an id the pending
  // set still names never overrides a settlement the feed already holds.
  pendingButRuled: view(projectEscalations(rows('a0a0a0a0approved'), new Set(['a0a0a0a0approved']))),
  // Every ruler/marker field the new display path interpolates, hostile at once.
  hostileAll: (() => {
    const ruling = {...only('a0a0a0a0approved', 'gate_escalation_decided')[0],
      marker: '<script>alert(1)</script>', decided_by: '"><img src=x onerror=alert(2)>',
      decided_via: "'><svg onload=alert(3)>", bar: '<b>bar</b>&'};
    const v = projectEscalations([ruling], none)[0].escalation_view;
    return {detail: escapeHtml(v.detail), hover: escapeHtml(`gate_escalation_decided\n${v.detail}`),
            raw: v.detail};
  })(),
  // Per-being filter on a terminal-only slice: the row stays under the OPENING actor, not
  // under the ruler, even when the ruler is a different member.
  rulingOnlyByMember: (() => {
    const slice = projectEscalations(only('a0a0a0a0approved', 'gate_escalation_decided'), none);
    return {asker: slice.filter(e => e.plugin_id === 'claude-code').length,
            ruler: slice.filter(e => e.plugin_id === 'codex').length};
  })(),
  auditEvents: (() => {
    const events = [
      asType(approvedOpen, 'gate_escalation_arbiter_refused', {chain_position: 80, hash: 'refusal'}),
      asType(approvedOpen, 'gate_escalation_payload_drift', {chain_position: 81, hash: 'drift'}),
      asType(approvedOpen, 'gate_escalation_payload_assertion_mismatch', {chain_position: 82, hash: 'mismatch'}),
      ...rows('a0a0a0a0approved'),
    ];
    return projectEscalations(events, none)
      .map(e => ({event_type: e.event_type, hash: e.hash, folded: !!e.escalation_view}));
  })(),
  untouched: projectEscalations([{chain_position: 30, event_type: 'outcome', plugin_id: 'kimi-code', hash: 'o'}], none),
}));
""")
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    check("projection executes", result.returncode == 0, result.stderr.strip()[:500])
    if result.returncode == 0:
        got = json.loads(result.stdout)
        check("a pending item in the snapshot is live (read by `id`)",
              got["livePending"] == ["p0p0p0p0pending0"], got["livePending"])
        check("each escalation collapses to one row", len(got["all"]) == 4, got["all"])
        by_status = {r["status"]: r for r in got["all"]}
        check("the served feed shows approved, denied, withdrawn and pending",
              sorted(by_status) == ["approved", "denied", "pending", "withdrawn"], sorted(by_status))
        check("array order does not change any disposition or source row",
              sorted(got["all"], key=lambda r: r["hash"])
              == sorted(got["allOldestFirst"], key=lambda r: r["hash"]))
        approved = got["approved"]
        check("open and ruling collapse to the ruling row",
              len(approved) == 1 and approved[0]["hash"] == "hash-2", approved)
        check("approval names ruler, channel, and met bar",
              approved[0]["status"] == "approved" and approved[0]["statusClass"] == "ok"
              and approved[0]["detail"]
              == "a0a0a0a0 policy.json -> approved by codex (peer_member, bar single_approver met)",
              approved[0])
        denied = got["denied"][0]
        check("a peer denial renders denied", denied["status"] == "denied"
              and denied["statusClass"] == "deny" and "-> denied by codex (peer_member" in denied["detail"],
              denied)
        check("self-withdrawal is not mislabeled as a merits denial",
              got["withdrawn"][0]["status"] == "withdrawn"
              and "withdrawn by claude-code" in got["withdrawn"][0]["detail"], got["withdrawn"])
        check("a live pending open renders pending", got["pending"][0]["status"] == "pending")
        off = got["offRecord"][0]
        check("an open not in the pending set is not mislabeled pending",
              off["status"] != "pending" and off["detail"].endswith("not pending; outcome not in this feed"),
              off)
        check("not-pending is not rendered as denied or expired",
              off["status"] not in ("denied", "expired") and off["statusClass"] == "info"
              and "denied" not in off["detail"] and "expired" not in off["detail"], off)
        check("the later of two rulings is the current status, in either array order",
              all(len(v) == 1 and v[0]["hash"] == "later-ruling" and v[0]["status"] == "denied"
                  and "-> denied by dp (operator_session" in v[0]["detail"] for v in got["twoRulings"]),
              got["twoRulings"])
        check("a lapse recorded after a ruling is the newest settlement, in either array order",
              all(len(v) == 1 and v[0]["hash"] == "expiry" and v[0]["status"] == "expired"
                  for v in got["rulingThenExpiry"]), got["rulingThenExpiry"])
        check("an approval that lapsed unclaimed is not called unruled",
              all(v[0]["detail"].endswith("approved, expired unclaimed") and "unruled" not in v[0]["detail"]
                  for v in got["rulingThenExpiry"]), got["rulingThenExpiry"])
        check("of two claims the newer is the row, in either array order",
              all(len(v) == 1 and v[0]["hash"] == "claim-new" for v in got["twoClaims"]), got["twoClaims"])
        check("a feed crossing a page boundary picks the ruling however the pages are joined",
              all(len(v) == 1 and v[0]["hash"] == "hash-2" and v[0]["status"] == "approved"
                  and v[0]["plugin_id"] == "claude-code" for v in got["acrossPages"]), got["acrossPages"])
        check("a pending id never overrides a settlement already in the feed",
              got["pendingButRuled"][0]["status"] == "approved", got["pendingButRuled"])
        hostile_all = got["hostileAll"]
        check("hostile marker, ruler, channel and bar are all escaped on detail and hover",
              all("<" not in hostile_all[k] and ">" not in hostile_all[k] and '"' not in hostile_all[k]
                  and "'" not in hostile_all[k] for k in ("detail", "hover"))
              and "&lt;script&gt;" in hostile_all["detail"] and "&lt;img" in hostile_all["detail"]
              and "&lt;svg" in hostile_all["detail"], hostile_all)
        check("the hostile values reached the display path unaltered before escaping",
              "<script>alert(1)</script>" in hostile_all["raw"]
              and '"><img src=x onerror=alert(2)>' in hostile_all["raw"], hostile_all["raw"])
        check("a terminal-only slice stays under the opening actor, not the ruler",
              got["rulingOnlyByMember"] == {"asker": 1, "ruler": 0}, got["rulingOnlyByMember"])
        check("a window that cut the open still shows the ruling and its asker",
              got["rulingOnly"][0]["status"] == "approved"
              and got["rulingOnly"][0]["plugin_id"] == "claude-code", got["rulingOnly"])
        check("per-being filtering keeps a ruling-only slice under its asker",
              got["rulingOnlyForAsker"] == 1)
        check("a claim without its ruling says the ruling is outside the window",
              got["claimOnly"][0]["detail"].endswith("claimed (ruling outside this window)"))
        check("a later claim does not displace the ruling",
              got["claimAfterRuling"][0]["hash"] == "hash-2"
              and got["claimAfterRuling"][0]["status"] == "approved", got["claimAfterRuling"])
        check("expiry is explicit and unruled", got["expired"][0]["detail"].endswith("expired unruled"))
        check("an expiry row with no lapse_kind claims neither ruled nor unruled",
              got["expiredNoKind"][0]["detail"].endswith("-> expired"), got["expiredNoKind"])
        check("a hostile marker is escaped on the rendered path",
              "<" not in got["hostileDetail"] and "&lt;img" in got["hostileDetail"], got["hostileDetail"])
        audit = got["auditEvents"]
        check("refused arbiters and payload drift stay separate from the lifecycle summary",
              len(audit) == 4
              and all(r["folded"] == (r["event_type"] == "gate_escalation_decided") for r in audit),
              audit)
        check("audit events keep their own event types and chain hashes",
              {r["event_type"]: r["hash"] for r in audit if r["event_type"] != "gate_escalation_decided"}
              == {"gate_escalation_arbiter_refused": "refusal",
                  "gate_escalation_payload_drift": "drift",
                  "gate_escalation_payload_assertion_mismatch": "mismatch"}, audit)
        check("non-escalation rows pass through unchanged", got["untouched"] == [{
            "chain_position": 30, "event_type": "outcome", "plugin_id": "kimi-code", "hash": "o",
        }])

if failures:
    raise SystemExit("dashboard escalation feed contract failed: " + ", ".join(failures))
print("dashboard escalation feed contract: PASS")
