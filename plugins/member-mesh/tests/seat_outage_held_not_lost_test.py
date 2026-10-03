#!/usr/bin/env python3
"""A seat that cannot run a wake must HOLD its mail, say so ONCE, and say so again when back.

THE INCIDENT (CBP, 2026-10-03). The claude-code seat was out of usage credits for ~11 h
(146-byte fire logs from 01:17 to 12:38 PDT). cbp-being sent 11 `coordination` notices
into that window. Each was drained, fired into a CLI that printed "You're out of usage
credits" and exited 1, retained -- and then retired by the hourly discharge sweep as
`.discharged`, because `primer_spent` reads absence from `i_owe` and a `coordination` is
never in `i_owe` (only `review_request`/`reply` are counted). The being got one cryptic
`#undelivered:` bounce per notice per fire and kept re-asking into silence.

Drives the REAL `hestia-watch-member.sh` against an in-process stub daemon and a stub
fire command whose behaviour (seat down / seat up) the test flips mid-run. No live
daemon: the stub binds an ephemeral 127.0.0.1 port, and HESTIA_MESH_STATE is a temp dir.

  A  CLASSIFY   the one table, extracted from the real script: each vendor's seat-down
                spelling (verbatim captures), the terminal-window guard against prose,
                and the rc carve-outs.
  B  HELD       a seat-down fire leaves the primer live with a `.unrun` sidecar; the
                discharge sweep (forced to run every second, fold says "owes nothing")
                does NOT retire it; no attempt is charged.  B0 is the sabotage arm:
                set WATCH_SCRIPT to origin/main's watcher and B must FAIL.
  C  TOLD ONCE  three seat-down fires, two senders: exactly one `forum-note` per sender,
                `#seat-unavailable:` fragment, no `in_reply_to`, within the 512-byte MTU,
                naming the held ids; no per-notice `#undelivered:` bounce; a durable
                seat-status record and one `down` history row.  A watcher RESTART inside
                the outage does not re-notify.
  D  RECOVERY   the first fire that provably runs sends one `#seat-back:` per sender,
                closes the record (history `up`, `.last.json`), coalesces the held
                primers into one, and fires that one with every held id in it.
  E  PROBE      with no new mail, a held list is re-fired on OUTAGE_PROBE_SECS while
                the seat is out, never charging `.attempts`, and the probe that succeeds
                is the recovery.
  F  HOOKS      optional per-member and operator hooks run once per event.

Usage: ./seat_outage_held_not_lost_test.py      (runtime ~60s, deliberate waits)
"""
import glob
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.environ.get("WATCH_SCRIPT") or os.path.abspath(
    os.path.join(HERE, "..", "hestia-watch-member.sh"))
PLUGIN = "dest-member"
CREDITS = ("You're out of usage credits. Switch to another model, or manage usage credits "
           "at claude.ai/settings/usage?from=cc_cli_limit_message, to continue.")

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


# ---------------------------------------------------------------------------------------
# A. the table, extracted (same posture as classify_evidence_window_test.py)
# ---------------------------------------------------------------------------------------
def extract(name):
    src = open(WATCHER, encoding="utf-8").read()
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", src, re.S | re.M)
    return m.group(0) if m else ""


def classify(text, rc="1", mode=""):
    func = extract("classify_fire_failure")
    with tempfile.TemporaryDirectory() as state:
        os.makedirs(os.path.join(state, "logs"))
        with open(os.path.join(state, "logs", "stub-20260101-000000.log"), "w") as f:
            f.write(text)
        script = (f'set -euo pipefail\nSTATE="{state}"\nFIRE="/x/fire-stub.sh"\n{func}\n'
                  f"classify_fire_failure {rc} {mode}\n")
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or f"<rc={r.returncode}: {r.stderr.strip()[:200]}>"


def unavailable(cls, rc):
    func = extract("fire_class_unavailable")
    r = subprocess.run(["bash", "-c", f"{func}\nfire_class_unavailable {cls} {rc}"], timeout=10)
    return r.returncode == 0


def section_a():
    print("=== A. CLASSIFY ===")
    if not extract("fire_class_unavailable"):
        check("A0: the seat-down helpers exist in the watcher", False,
              "fire_class_unavailable() not found — this is the pre-fix script")
        return
    cases = [  # (name, log text, rc, mode, expected) — vendor strings verbatim from CBP logs
        ("claude credits (claude-20261003-123831)", CREDITS + "\n", "1", "terminal", "out-of-credits"),
        ("claude weekly", "You've hit your weekly limit · resets 11pm (America/Los_Angeles)\n",
         "1", "terminal", "out-of-credits"),
        ("kimi weekly 403", "error: failed to run prompt: provider.auth_error: 403 You've reached "
         "your weekly (7-day) usage limit. Your quota will reset when the current 7-day window "
         "ends. To continue now, purchase extra usage or upgrade your plan: https://x\n"
         "See log: /home/dp/.kimi-code/logs/kimi-code.log\n", "1", "terminal", "out-of-credits"),
        ("codex workspace", "hook: SessionStart Completed\nERROR: Your workspace is out of credits. "
         "Add credits to continue.\n", "1", "terminal", "out-of-credits"),
        ("codex 401 (codex-20260901-213954)", "ERROR: Reconnecting... 5/5\nERROR: unexpected status "
         "401 Unauthorized: Missing bearer or basic authentication in header, url: "
         "https://api.openai.com/v1/responses\n", "1", "terminal", "auth-failed"),
        ("claude not logged in (claude-20260925-124914)", "Not logged in · Please run /login\n",
         "1", "terminal", "auth-failed"),
        ("kimi launch", "timeout: failed to run command ‘kimi’: No such file or directory\n",
         "1", "terminal", "launch-failed"),
        ("codex config (codex-20260903-202613)", "Error loading config.toml:\n"
         "/home/dp/.codex/config.toml:106:11: duplicate key\n    |\n"
         '106 | [projects."/home/dp/ai-workspace"]\n    |           ^^^^^^^^^^^^\n',
         "1", "terminal", "launch-failed"),
        ("rc 127", "", "127", "terminal", "launch-failed"),
        # Prose ABOUT an outage in a wake that ran: the vendor string is far above the end.
        ("prose: limits discussed, run ended normally",
         "the codex seat hit your usage limit earlier today\n" + "work line\n" * 30
         + "Committed and pushed abc123.\n", "1", "terminal", "unknown"),
        ("prose: 'command not found' in a sentence",
         "The watcher printed `command not found` on every fire for three days.\n",
         "1", "terminal", "unknown"),
    ]
    for name, text, rc, mode, want in cases:
        got = classify(text, rc, mode)
        check(f"A: {name} -> {want}", got == want, f"got {got!r}")
    check("A: the wide why= window still finds a vendor sentence far above the end",
          classify(CREDITS + "\n" + "x\n" * 30) == "out-of-credits")
    # Topic words in a wake's closing prose (32 logs on CBP: "codex remains out of
    # credits") no longer classify at all: the row is vendor-shaped now.
    check("A: topic prose about a peer's credits is not a billing verdict, in either window",
          classify("codex remains out of credits; quota exceeded on the vault run\n") == "unknown"
          and classify("codex remains out of credits\n", mode="terminal") == "unknown")
    check("A: out-of-credits/auth-failed/launch-failed are seat-down",
          all(unavailable(c, "1") for c in ("out-of-credits", "auth-failed", "launch-failed")))
    check("A: timeout/egress/unknown are NOT seat-down",
          not any(unavailable(c, "1") for c in ("timeout", "egress-blocked", "unknown")))
    check("A: a template/lock refusal rc (70, 75) is never seat-down, whatever the old log says",
          not unavailable("out-of-credits", "70") and not unavailable("out-of-credits", "75"))


# ---------------------------------------------------------------------------------------
# Stub daemon
# ---------------------------------------------------------------------------------------
class Stub:
    def __init__(self):
        self.queue, self.notify, self.lock = [], [], threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, hdrs=None):
                self.send_response(code)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                m = req.get("method")
                if m == "initialize":
                    return self._send(200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
                                      {"mcp-session-id": "stub-sid"})
                if m == "notifications/initialized":
                    return self._send(202, b"")
                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                with outer.lock:
                    if tool == "hestia_connect":
                        p = {"sessionId": "stub-session"}
                    elif tool == "hestia_member_inbox":
                        p = {"total": len(outer.queue), "notices": outer.queue}
                        outer.queue = []
                    elif tool == "hestia_member_unanswered":
                        # "owes nothing" at floor 0: exactly the fold that retired the
                        # being's coordination notices. The judge must not believe it
                        # for a list no session ever saw.
                        p = {"i_owe": [], "owed_to_me": [], "older_than_secs": 0,
                             "kinds_counted": ["review_request", "reply"]}
                    elif tool == "hestia_member_notify":
                        outer.notify.append(args)
                        p = {"queued_id": 9000 + len(outer.notify), "recipient_liveness": "live"}
                    else:
                        p = {}
                rpc = {"jsonrpc": "2.0", "id": req.get("id", 9),
                       "result": {"content": [{"type": "text", "text": json.dumps(p)}]}}
                return self._send(200, f"data: {json.dumps(rpc)}\n\n".encode(),
                                  {"Content-Type": "text/event-stream"})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def push(self, *notices):
        with self.lock:
            self.queue.extend(notices)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def notice(nid, frm="cbp-being", kind="coordination"):
    return {"id": nid, "kind": kind, "from_plugin": frm,
            "pointer_uri": f"sage://conversation/cbp-claude#seq={nid}",
            "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


class Rig:
    """A temp state dir, a fire stub the test can flip between down and up, a watcher."""

    def __init__(self, probe_secs="3600", hooks=False):
        self.tmp = tempfile.mkdtemp(prefix="seat-outage-test-")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(self.state, "logs"))
        self.mode = os.path.join(self.tmp, "mode")
        self.fired = os.path.join(self.tmp, "fired.jsonl")
        self.set_mode("down")
        self.fire = os.path.join(self.tmp, "fire-stub.sh")
        with open(self.fire, "w") as f:
            f.write(f"""#!/usr/bin/env bash
LOG="{self.state}/logs/stub-$(date +%Y%m%d-%H%M%S)-$$.log"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(sorted(n["id"] for n in d.get("notices",[]))))' "$1" >> "{self.fired}"
if [ "$(cat "{self.mode}")" = down ]; then
  printf '%s\\n' "{CREDITS}" > "$LOG"; exit 1
fi
echo "wake ran; replied to everything" > "$LOG"; exit 0
""")
        os.chmod(self.fire, 0o755)
        self.hooklog = os.path.join(self.tmp, "hooks.log")
        if hooks:
            hd = os.path.join(self.state, "seat-status", "hooks")
            os.makedirs(hd)
            for name in ("cbp-being", "_operator"):
                p = os.path.join(hd, name)
                with open(p, "w") as f:
                    f.write(f'#!/usr/bin/env bash\necho "{name} $SEAT_EVENT $SEAT $SEAT_MEMBER | '
                            f'$SEAT_MESSAGE" >> "{self.hooklog}"\n')
                os.chmod(p, 0o755)
        self.stub = Stub()
        self.probe = probe_secs
        self.proc = None
        self.out = ""

    def set_mode(self, m):
        with open(self.mode, "w") as f:
            f.write(m)

    def start(self):
        env = dict(os.environ)
        env.update({"HESTIA_ENDPOINT": f"http://127.0.0.1:{self.stub.port}/mcp",
                    "HESTIA_MESH_STATE": self.state, "WATCH_INTERVAL": "1",
                    "UNANSWERED_EVERY": "3600", "DISCHARGE_SWEEP_EVERY": "1",
                    "OUTAGE_PROBE_SECS": self.probe})
        self.proc = subprocess.Popen(["bash", WATCHER, PLUGIN, "dest-agent", self.fire], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     start_new_session=True)

    def stopw(self):
        if self.proc:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.out += self.proc.communicate(timeout=20)[0] or ""
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.out += self.proc.communicate()[0] or ""
            self.proc = None

    def wait(self, pred, secs=20):
        end = time.time() + secs          # bounded: every wait in this file has a deadline
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.25)
        return pred()

    def fires(self):
        try:
            return [json.loads(l) for l in open(self.fired) if l.strip()]
        except FileNotFoundError:
            return []

    def primers(self, suffix=".json"):
        return sorted(glob.glob(os.path.join(self.state, "primers", PLUGIN, "notice-*" + suffix)))

    def sidecars(self, ext):
        return glob.glob(os.path.join(self.state, "primers", PLUGIN, "notice-*.json" + ext))

    def notes(self, marker, to=None):
        return [a for a in self.stub.notify if marker in a.get("pointer_uri", "")
                and (to is None or a.get("to_plugin_id") == to)]

    def history(self):
        try:
            return [json.loads(l) for l in open(os.path.join(self.state, "seat-status", "history.jsonl"))]
        except FileNotFoundError:
            return []

    def close(self):
        self.stopw()
        self.stub.stop()


def section_bcd():
    print("\n=== B/C/D. HELD, TOLD ONCE, RECOVERY ===")
    r = Rig()
    try:
        r.start()
        r.stub.push(notice(16342))
        r.wait(lambda: len(r.fires()) >= 1)
        r.stub.push(notice(16344))
        r.wait(lambda: len(r.fires()) >= 2)
        r.stub.push(notice(16346), notice(7001, frm="kimi-code", kind="review_done"))
        r.wait(lambda: len(r.fires()) >= 3)
        time.sleep(4)                       # several forced discharge sweeps (every 1s)
        live = r.primers()
        discharged = r.primers(".json.discharged")
        check("B: every seat-down primer is still LIVE after repeated discharge sweeps",
              len(live) == 3 and not discharged,
              f"live={len(live)} discharged={discharged}\n{r.out}")
        check("B: each held primer carries a .unrun sidecar", len(r.sidecars(".unrun")) == 3,
              f"unrun={r.sidecars('.unrun')}")
        check("B: no attempt was charged for the seat's outage", not r.sidecars(".attempts"),
              f"attempts={r.sidecars('.attempts')}")

        being = r.notes("#seat-unavailable:", "cbp-being")
        kimi = r.notes("#seat-unavailable:", "kimi-code")
        check("C: exactly ONE seat-unavailable note to cbp-being across 3 fires", len(being) == 1,
              json.dumps(r.stub.notify, indent=1))
        check("C: exactly ONE to the second sender (kimi-code)", len(kimi) == 1,
              json.dumps(r.stub.notify, indent=1))
        if being:
            a = being[0]
            p = a["pointer_uri"]
            check("C: the note is a forum-note with NO in_reply_to (it answers nothing)",
                  a.get("kind") == "forum-note" and "in_reply_to" not in a, json.dumps(a))
            check("C: within the 512-byte MTU", len(p.encode()) <= 512, f"{len(p.encode())} bytes")
            check("C: names why, since, the held id and the observer",
                  ";why=out-of-credits;" in p and "since=" in p and "held=16342" in p
                  and "via=watch-dest-member" in p, p)
            check("C: carries a readable sentence for a reader that renders pointers",
                  "HELD, not lost" in p and "seat-back" in p, p)
        check("C: no per-notice #undelivered bounce for a seat-down fire",
              not r.notes("#undelivered"), json.dumps(r.notes("#undelivered")))
        status = os.path.join(r.state, "seat-status", f"{PLUGIN}.json")
        st = json.load(open(status)) if os.path.exists(status) else {}
        check("C: a durable seat-status record names the outage and the held ids",
              st.get("why") == "out-of-credits" and sorted(st.get("held", {}).get("cbp-being", []))
              == [16342, 16344, 16346] and st.get("fires") == 3, json.dumps(st))
        check("C: one `down` history row", [h["event"] for h in r.history()] == ["down"],
              json.dumps(r.history()))

        # Restart inside the outage: the record persists, nobody is told twice.
        r.stopw()
        r.start()
        r.stub.push(notice(16348))
        r.wait(lambda: len(r.fires()) >= 4)
        time.sleep(1)
        check("C: a watcher restart inside the outage does not re-notify",
              len(r.notes("#seat-unavailable:", "cbp-being")) == 1,
              json.dumps(r.notes("#seat-unavailable:"), indent=1))

        # D: the seat comes back. A fresh notice fires and runs.
        r.set_mode("up")
        r.stub.push(notice(16350))
        r.wait(lambda: len(r.notes("#seat-back:")) >= 2)
        back_b = r.notes("#seat-back:", "cbp-being")
        back_k = r.notes("#seat-back:", "kimi-code")
        check("D: one seat-back note to each sender told", len(back_b) == 1 and len(back_k) == 1,
              json.dumps(r.stub.notify, indent=1))
        if back_b:
            check("D: seat-back is a forum-note, no in_reply_to, names the held ids, <=512 B",
                  back_b[0]["kind"] == "forum-note" and "in_reply_to" not in back_b[0]
                  and "16342" in back_b[0]["pointer_uri"]
                  and len(back_b[0]["pointer_uri"].encode()) <= 512, json.dumps(back_b[0]))
        check("D: the outage record is closed (state gone, .last.json kept, history down+up)",
              not os.path.exists(status)
              and os.path.exists(os.path.join(r.state, "seat-status", f"{PLUGIN}.last.json"))
              and [h["event"] for h in r.history()] == ["down", "up"],
              json.dumps(r.history()))
        held_ids = [16342, 16344, 16346, 16348, 7001]
        r.wait(lambda: any(set(held_ids) <= set(f) for f in r.fires()), secs=25)
        check("D: the held primers are COALESCED and fired as ONE wake carrying every held id",
              any(set(held_ids) <= set(f) for f in r.fires()),
              f"fires={r.fires()}\n{r.out}")
        r.wait(lambda: not r.primers(), secs=10)
        check("D: nothing is left live once the coalesced wake ran", not r.primers(),
              f"live={r.primers()}")
        check("D: the folded originals are set aside, not deleted",
              len(r.primers(".json.coalesced")) >= 3, f"{r.primers('.json.coalesced')}")
        check("D: no seat-unavailable note was sent after recovery",
              len(r.notes("#seat-unavailable:")) == 2, json.dumps(r.notes("#seat-unavailable:")))
    finally:
        r.close()


def section_e():
    print("\n=== E. PROBE ===")
    r = Rig(probe_secs="2")
    try:
        r.start()
        r.stub.push(notice(16400))
        r.wait(lambda: len(r.fires()) >= 3, secs=25)   # 1 fresh fire + >=2 probes
        check("E: a held list is re-fired as a probe while the seat is out", len(r.fires()) >= 3,
              f"fires={r.fires()}\n{r.out}")
        check("E: probes never charge .attempts", not r.sidecars(".attempts"),
              f"attempts={r.sidecars('.attempts')}")
        check("E: probes never re-notify", len(r.notes("#seat-unavailable:")) == 1,
              json.dumps(r.stub.notify))
        r.set_mode("up")
        r.wait(lambda: r.notes("#seat-back:"), secs=15)
        check("E: the probe that succeeds is the recovery (seat-back sent, list delivered)",
              len(r.notes("#seat-back:")) == 1 and not r.primers(),
              f"notify={json.dumps(r.stub.notify)} live={r.primers()}\n{r.out}")
    finally:
        r.close()


def section_f():
    print("\n=== F. HOOKS ===")
    r = Rig(hooks=True)
    try:
        r.start()
        r.stub.push(notice(16500))
        r.wait(lambda: len(r.fires()) >= 1)
        r.stub.push(notice(16501))
        r.wait(lambda: len(r.fires()) >= 2)
        time.sleep(1)
        r.set_mode("up")
        r.stub.push(notice(16502))
        r.wait(lambda: r.notes("#seat-back:"), secs=15)
        time.sleep(1)
        lines = open(r.hooklog).read().splitlines() if os.path.exists(r.hooklog) else []
        ev = [" ".join(l.split(" | ")[0].split()[:2]) for l in lines]
        check("F: member hook and operator hook each run once on down and once on up",
              sorted(ev) == sorted(["cbp-being down", "_operator down", "cbp-being up", "_operator up"]),
              f"hook calls={lines}\n{r.out}")
        check("F: the member hook receives the same sentence the mesh note carries",
              any(l.startswith("cbp-being down") and "HELD, not lost" in l for l in lines), f"{lines}")
    finally:
        r.close()


def main():
    section_a()
    if not extract("fire_class_unavailable"):
        print("\n(pre-fix watcher: running B as the sabotage arm)")
    section_bcd()
    if extract("fire_class_unavailable"):
        section_e()
        section_f()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all seat-outage properties hold")


if __name__ == "__main__":
    main()
