#!/usr/bin/env python3
"""The unknown-member grant refusal (#1067) is not a dead end, and its way out is deliberate.

The daemon now refuses (409, nothing written) an operator-originated grant to a plugin_id that
has never connected, because the warning it used to return was rendered inside the success
element and read as success: three typo'd grants on one seat in forty minutes, while the seat
that needed them stayed denied.

Granting ahead of a member's first connect is still legitimate, and a registry that is empty or
unreadable would otherwise block every grant from the dashboard. So the dashboard offers the
deliberate path on exactly that refusal. What has to stay true of that offer:

  * it appears ONLY on a 409 that says `member_known: false`;
  * the first send never carries `register_new_member` -- the flag is not a default;
  * pressing the offered button re-sends the SAME form once, with the flag;
  * the flag is one-shot: the next ordinary grant does not carry it -- INCLUDING when the
    press itself never reached the daemon (the form failed its own path check).

Behavioural: the real `wireScopeGrants` block is lifted out of the dashboard and run under node
against a stub DOM and a scripted daemon, so these are assertions about what the page DOES.

Run: python3 tools/grant_refusal_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
FAILS: list[str] = []

HARNESS = r"""
const els = {};
function el(id) {
  return els[id] || (els[id] = { id, value: '', hidden: true, disabled: false, innerHTML: '', textContent: '',
    classList: { toggle() {} }, handlers: {},
    addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); },
    async fire(t, ev) { for (const f of (this.handlers[t] || [])) await f(ev || { target: this }); },
    click() { return this.fire('click'); } });
}
const $ = id => el(id);
const escapeHtml = s => String(s);
const lastData = {}; const renderScopeGrants = () => {}; const tick = async () => {};
const sent = []; const replies = JSON.parse(process.argv[1]);
const apiFetch = async (url, opts) => {
  sent.push({ url, body: JSON.parse(opts.body) });
  const r = replies[Math.min(sent.length - 1, replies.length - 1)];
  return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
};
el('govern-grants');
BLOCK
(async () => {
  const log = [];
  const fill = () => { el('sg-plugin').value = 'Claude-code'; el('sg-path').value = '/w/repos'; el('sg-reason').value = 'r'; };
  fill();
  await el('sg-grant-btn').click();
  log.push({ step: 'first send', sent: sent.length, flag: sent[0].body.register_new_member,
             offered: el('sg-err').innerHTML.includes('sg-ahead-btn'), errShown: !el('sg-err').hidden });
  const script = JSON.parse(process.argv[2]);
  if (script === 'press') {
    await el('sg-err').fire('click', { target: { id: 'sg-ahead-btn' } });
    log.push({ step: 'pressed', sent: sent.length, flag: sent[1] && sent[1].body.register_new_member,
               same: sent[1] && sent[1].body.plugin_id === 'Claude-code' && sent[1].body.path === '/w/repos' });
    fill();
    await el('sg-grant-btn').click();
    log.push({ step: 'next ordinary grant', sent: sent.length, flag: sent[2] && sent[2].body.register_new_member });
  } else if (script === 'stray-click') {
    await el('sg-err').fire('click', { target: { id: 'something-else' } });
    log.push({ step: 'stray click in the error box', sent: sent.length });
  } else if (script === 'spent-by-a-failed-press') {
    // The press that does NOT reach the daemon: the form now fails its own path check. The flag
    // must be spent by that click anyway, or it rides along on the next ordinary grant.
    el('sg-path').value = 'relative/path';
    await el('sg-err').fire('click', { target: { id: 'sg-ahead-btn' } });
    log.push({ step: 'press with a bad path', sent: sent.length });
    fill();
    await el('sg-grant-btn').click();
    log.push({ step: 'the ordinary grant after it', sent: sent.length, flag: sent[1] && sent[1].body.register_new_member });
  }
  process.stdout.write(JSON.stringify(log));
})();
"""


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def block() -> str:
    a = UI.index("  (function wireScopeGrants() {")
    return UI[a:UI.index("\n  })();", a)] + "\n  })();"


def run(replies, script) -> list:
    prog = HARNESS.replace("BLOCK", block())
    r = subprocess.run(["node", "-e", prog, json.dumps(replies), json.dumps(script)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not r.stdout:
        FAILS.append(f"node failed ({script}): {r.stderr.strip()[-300:]}")
        return []
    return json.loads(r.stdout)


REFUSED = {"status": 409, "body": {"error": "no member 'Claude-code' has ever connected", "member_known": False,
                                    "nearest": ["claude-code"]}}
GRANTED = {"status": 200, "body": {"ok": True, "member_known": False, "plugin_id": "Claude-code", "path": "/w/repos"}}


def source_contract() -> None:
    blk = block()
    check("the flag is written in exactly one place, under the one-shot",
          blk.count("register_new_member"), 2)   # the assignment + the comment naming it
    check("...and that place is guarded by `ahead`", "if (ahead) body.register_new_member = true;" in blk)
    check("the offer warns what a typo granted this way becomes", "shows up as a phantom agent" in blk)


def behaviour() -> None:
    log = run([REFUSED, GRANTED, GRANTED], "press")
    step = {s["step"]: s for s in log}
    check("first send: no flag, ever", step.get("first send", {}).get("flag"), None)
    check("first send: the refusal is shown, with the deliberate path offered",
          (step.get("first send", {}).get("errShown"), step.get("first send", {}).get("offered")), (True, True))
    check("pressing it re-sends the SAME form, once, with the flag",
          (step.get("pressed", {}).get("sent"), step.get("pressed", {}).get("flag"), step.get("pressed", {}).get("same")),
          (2, True, True))
    check("ONE-SHOT: the next ordinary grant does not carry it",
          (step.get("next ordinary grant", {}).get("sent"), step.get("next ordinary grant", {}).get("flag")), (3, None))

    # Offered ONLY on the unknown-member refusal -- not on any other failure, and not on a 409
    # that does not say member_known:false.
    for label, reply in (("a 500", {"status": 500, "body": {"error": "vault"}}),
                         ("a 400", {"status": 400, "body": {"error": "reason is required", "member_known": False}}),
                         ("a 409 about something else", {"status": 409, "body": {"error": "busy"}})):
        first = (run([reply], "none") or [{}])[0]
        check(f"not offered on {label}", (first.get("errShown"), first.get("offered")), (True, False))

    log = run([REFUSED], "stray-click")
    check("a click elsewhere in the error box sends nothing", (log or [{}])[-1].get("sent"), 1)
    log = run([REFUSED, GRANTED, GRANTED], "spent-by-a-failed-press")
    step = {s["step"]: s for s in log}
    check("a press that fails the form's own path check reaches no daemon",
          step.get("press with a bad path", {}).get("sent"), 1)
    check("...and is SPENT anyway: the next ordinary grant carries no flag",
          (step.get("the ordinary grant after it", {}).get("sent"), step.get("the ordinary grant after it", {}).get("flag")),
          (2, None))


def test_grant_refusal_contract() -> None:
    """pytest's entry: the same checks, and a failure it can see."""
    FAILS.clear()
    source_contract()
    if shutil.which("node"):
        behaviour()
    assert not FAILS, "\n".join(FAILS)


def main() -> int:
    # One body for both invocations (tools/ci_selfexec_test.py); the assert is pytest's channel
    # and is caught here so every failure is printed, not only the fact of one.
    try:
        test_grant_refusal_contract()
    except AssertionError:
        pass
    if not shutil.which("node"):
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"grant refusal contract: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
