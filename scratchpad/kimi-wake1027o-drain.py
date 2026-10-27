#!/usr/bin/env python3
"""Wake-1027o: resolve i_owe row 29789 (escalation 2953ddfc7dc5119d) and loop-close any
further capped-render rows until the daemon's own unanswered query reads i_owe 0."""
import importlib.util, json, subprocess

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

MESH = "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py"


def read_pointer(uri):
    h, s = hm.connect()
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            r = env.get("result", env)
            txt = r["contents"][0]["text"] if "contents" in r else json.dumps(r)
            return json.loads(txt) if isinstance(txt, str) else txt
    return None


def send_reply(in_reply_to, pointer):
    r = subprocess.run(
        ["python3", MESH, "send", "cbp-being", "reply", pointer, in_reply_to],
        capture_output=True, text=True,
        env={"HESTIA_MESH_PLUGIN": "kimi-code", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    marker = [ln for ln in r.stdout.splitlines() if "hestia-mesh: sent" in ln]
    print(f"  in_reply_to={in_reply_to}: {marker[0] if marker else (r.stderr.strip() or r.stdout[-300:])}")


for _ in range(6):
    h, s = hm.connect()
    out = hm.rpc(h, "hestia_member_unanswered", {"session_id": s, "plugin_id": "kimi-code"})
    i_owe = out.get("i_owe", [])
    if not i_owe:
        print("i_owe: 0 -- clean")
        break
    print(f"i_owe: {len(i_owe)} -> {[r['id'] for r in i_owe]}")
    for row in i_owe:
        nid = row["id"]
        uri = row["pointer_uri"].split("#")[0].split(";")[0]
        frag = row["pointer_uri"].split("#", 1)[1].split(";")[0] if "#" in row["pointer_uri"] else ""
        d = read_pointer(uri)
        if d is None:
            print(f"  {nid}: UNREADABLE, skipping")
            continue
        err = d.get("_hestia_error")
        if err:
            ptr = f"{uri}#{frag};request-gone-from-live-map:unknown-not-moot;memory-only-map-eviction-is-not-a-refusal;via=kimi-code"
        elif d.get("status") == "expired":
            se = d.get("settled_entry") or {}
            ts = (se.get("timestamp") or "").replace("-", "").replace(":", "")
            ts = ts[:15].replace("T", "T") + "Z" if ts else "unknown"
            ts = ts.replace("+00:00", "")
            ed = se.get("eventData") or {}
            dissent = ed.get("factors_dissenting", "?")
            concur = ed.get("factors_concurring", "?")
            present = ed.get("factors_present", "?")
            wit = (se.get("hash") or "")[:16]
            ptr = (f"{uri}#{frag};already-terminal:lapsed-{ts};"
                   f"kimi-factored-dissenting-on-record-{present}of{present}-dissent-{concur}-concur;"
                   f"witness:{wit};via=kimi-code")
        else:
            print(f"  {nid}: status={d.get('status')} -- NOT terminal, needs real handling, skipping")
            continue
        send_reply(str(nid), ptr)
else:
    print("loop cap reached")
