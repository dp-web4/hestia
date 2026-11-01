#!/usr/bin/env node
// Runs the dashboard's real renderDeployment and update-button click handler against fake
// /api/dashboard snapshots, with the browser's clock ahead of or behind the daemon's.
//
// /api/dashboard serves the last snapshot while the next one builds, so the poll right after
// a click can predate it. The page holds an accepted click ("updating…" / "checking…") until
// a snapshot shows it. An update is matched by its request_id; a check by the server's own
// stamp on the check changing. The browser's clock is never compared with the daemon's: on
// another machine they differ (#1434 review). Usage: node tools/dashboard_deployment_pending_test.mjs
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../core/src/server/dashboard/index.html', import.meta.url), 'utf8');
const slice = (from, to) => {
  const a = html.indexOf(from);
  const b = html.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`dashboard_deployment_pending_test: cannot find ${JSON.stringify(from)}`);
  return html.slice(a, b);
};
const code = slice('  let deploymentPending = null;', '  // Scheduled auto-update')
  + slice('  (function wireDeploymentUpdate()', '  async function fetchFailures()');

const DAEMON_T0 = Date.parse('2026-10-28T12:00:00Z');
const iso = (ms) => new Date(Math.floor(ms / 1000) * 1000).toISOString(); // whole seconds, as the daemon writes

function harness(skewMs) {
  let daemonNow = DAEMON_T0;
  const clock = { now: () => daemonNow + skewMs, parse: Date.parse };
  const els = {};
  const $ = (id) => (els[id] ||= {
    hidden: false, disabled: false, dataset: {}, textContent: '', title: '', className: '',
    classList: { toggle() {}, remove() {}, add() {} },
    addEventListener(type, fn) { this.handler = fn; },
  });
  let snapshot = null;
  let postReply = { ok: true, status: 202, body: {} };
  let hold = null; // when set, the POST waits until the test calls release()
  const apiFetch = async () => {
    if (hold) await hold.promise;
    return { ok: postReply.ok, status: postReply.status, json: async () => postReply.body };
  };
  const api = new Function('$', 'fmt', 'renderAutoUpdate', 'apiFetch', 'tick', 'Date', `${code}
    return { render: renderDeployment, pending: () => deploymentPending };`)(
    $, { stamp: (s) => s }, () => {}, apiFetch, async () => api.render(snapshot), clock);
  const btn = $('deployment-update');
  return {
    btn, api,
    advance(ms) { daemonNow += ms; },
    stampNow: () => iso(daemonNow),
    show(s) { snapshot = s; api.render(s); },
    reply(r) { postReply = r; },
    click: () => btn.handler(),
    holdPost() { let release; hold = { promise: new Promise((r) => { release = r; }) }; hold.release = release; },
    releasePost() { const h = hold; hold = null; h.release(); },
  };
}

const base = { state: 'current', update_capable: true, check_capable: true, update_state: 'idle' };
let fails = 0;
const expect = (name, h, label, extra = true) => {
  const ok = h.btn.textContent === label && extra;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name} -> ${JSON.stringify(h.btn.textContent)}`);
  if (!ok) fails++;
};

const FIVE_MIN = 5 * 60 * 1000;
for (const [skewName, skew] of [['same clock', 0], ['browser 5 min behind', -FIVE_MIN], ['browser 5 min ahead', FIVE_MIN]]) {
  // Check: the last check was 10 s ago (daemon time) and said up to date.
  {
    const h = harness(skew);
    const before = { ...base, check: { state: 'up-to-date', at: iso(DAEMON_T0 - 10000) } };
    h.show(before);
    expect(`[${skewName}] check offered`, h, 'check for updates');
    await h.click(); // the tick after the POST serves the pre-click snapshot
    expect(`[${skewName}] check click, stale snapshot: holds checking`, h, 'checking…', h.api.pending() !== null);
    h.advance(2000);
    h.show(before);
    expect(`[${skewName}] next poll still stale: holds checking`, h, 'checking…');
    h.advance(3000);
    h.show({ ...base, check: { state: 'up-to-date', at: h.stampNow() } });
    expect(`[${skewName}] check finished: released at once`, h, 'check for updates', h.api.pending() === null);
  }
  // Check: the snapshot shows the check running, then a result.
  {
    const h = harness(skew);
    h.show({ ...base, check: { state: 'up-to-date', at: iso(DAEMON_T0 - 10000) } });
    await h.click();
    h.advance(1000);
    h.show({ ...base, check: { state: 'checking', at: h.stampNow() } });
    expect(`[${skewName}] server says checking`, h, 'checking…', h.api.pending() === null);
    h.advance(4000);
    h.show({ ...base, check: { state: 'available', at: h.stampNow(), latest: 'abc123' } });
    expect(`[${skewName}] check found an update`, h, 'update');
  }
  // Update: matched by request_id, whatever the clocks say.
  {
    const h = harness(skew);
    const before = { ...base, check: { state: 'available', at: iso(DAEMON_T0 - 10000), latest: 'abc123' } };
    h.show(before);
    expect(`[${skewName}] update offered`, h, 'update');
    h.reply({ ok: true, status: 202, body: { request_id: 'req-1' } });
    await h.click();
    expect(`[${skewName}] update click, stale snapshot: holds updating`, h, 'updating…', h.api.pending() !== null);
    h.advance(2000);
    h.show({ ...before, update_state: 'requested', update_request_id: 'req-1' });
    expect(`[${skewName}] snapshot shows the request`, h, 'updating…', h.api.pending() === null);
  }
}

// A check that FINISHES while the POST is in flight: a poll lands mid-POST with the new
// stamp. The baseline is the stamp from before the click, so the tick after the POST sees
// the change and releases at once, instead of holding "checking…" for 30 s (legion review).
{
  const h = harness(0);
  h.show({ ...base, check: { state: 'up-to-date', at: iso(DAEMON_T0 - 10000) } });
  h.holdPost();
  const clicked = h.click();
  h.advance(3000);
  h.show({ ...base, check: { state: 'up-to-date', at: h.stampNow() } }); // poll lands mid-POST
  h.releasePost();
  await clicked; // its tick re-renders the mid-POST snapshot
  expect('check finished during the POST: released at once', h, 'check for updates', h.api.pending() === null);
}

// A failed POST sets no hold: the button offers a retry straight away.
{
  const h = harness(0);
  h.show({ ...base, check: { state: 'up-to-date', at: iso(DAEMON_T0 - 10000) } });
  h.reply({ ok: false, status: 503, body: { error: 'check_unavailable' } });
  await h.click();
  expect('failed check POST: retry, no hold', h, 'retry check', h.api.pending() === null && !h.btn.disabled);
}

// A click no snapshot ever shows is released after 30 s (browser time only).
{
  const h = harness(-FIVE_MIN);
  const before = { ...base, check: { state: 'up-to-date', at: iso(DAEMON_T0 - 10000) } };
  h.show(before);
  await h.click();
  h.advance(29000);
  h.show(before);
  expect('29 s, still stale: holds', h, 'checking…');
  h.advance(2000);
  h.show(before);
  expect('31 s, still stale: released', h, 'check for updates', h.api.pending() === null);
}

// Retry after a failed update: the stale snapshot still says failed with the old id.
{
  const h = harness(0);
  const failed = { ...base, update_state: 'failed', update_request_id: 'req-0' };
  h.show(failed);
  expect('failed update offers retry', h, 'retry update');
  h.reply({ ok: true, status: 202, body: { request_id: 'req-3' } });
  await h.click();
  expect('retry, stale failed snapshot: holds updating', h, 'updating…');
}

if (fails) {
  console.error(`dashboard deployment pending: ${fails} FAILED`);
  process.exit(1);
}
console.log('dashboard deployment pending: PASS');
