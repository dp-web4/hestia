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
  expired: view(projectEscalations([asType(approvedOpen, 'gate_escalation_expired', {chain_position: 99})], none)),
  hostileDetail: escapeHtml(hostileView.detail),
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
        check("an open not in the pending set is not mislabeled pending",
              got["offRecord"][0]["detail"].endswith("no longer on record"))
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
        check("a hostile marker is escaped on the rendered path",
              "<" not in got["hostileDetail"] and "&lt;img" in got["hostileDetail"], got["hostileDetail"])
        check("non-escalation rows pass through unchanged", got["untouched"] == [{
            "chain_position": 30, "event_type": "outcome", "plugin_id": "kimi-code", "hash": "o",
        }])

if failures:
    raise SystemExit("dashboard escalation feed contract failed: " + ", ".join(failures))
print("dashboard escalation feed contract: PASS")
