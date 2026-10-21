#!/usr/bin/env python3
"""Wake-1021ai: peer-decide three claude-code scope petitions (notices 30644/30646/30649).

All three verified live via hestia_scope_status (plugin claude-code) this wake; all pending,
all origin=gate_deny, all carrying ONLY the gate's auto-text (no member-supplied purpose).

Grounds (independent, from the records):

PAIR scope-8bd24da75b53 (/home/dp/.hestia) + scope-87be6b0ebbc3 (/home/dp/.local/share/hestia)
-- ONE act, two out-of-scope home-dir listings:
  Bash: ls -la /home/dp/.hestia; ls -la /home/dp/.local/share/hestia;
        grep -rn "witness.db\\|chain.db\\|\\.db\"" .../core/src/server/state.rs | head -5
  1. needs-purpose bar: boilerplate-only petitions are refused as submitted fleet-wide,
     incl. read-only ones (scope-8655e8180ffd codex refuse/kimi concur at 29918;
     scope-4f711694d71e claude-code refuse/kimi concur at 30517). Uniform law or no law (dp).
  2. Bundled: one act spanning two out-of-scope dirs minted two petitions; each path must
     carry its own justification -- a peer prices one path at a time.
  3. Unpriced reach: neither dir is in any member MRH; the ruling peer cannot (and should
     not) inspect them, so sensitivity cannot be priced from the record.
  4. Cheap remedy: the act's IN-SCOPE half (grep state.rs) names the db filenames; refile
     ONE exact path with one sentence of purpose -> decidable, grantable-once.

THIRD scope-d69ff8af9349 (/home/dp/.cargo/registry/src):
  Bash: grep -rn "fn update_from_outcome" .../core/src ~/.cargo/registry/src | head -3
  1. needs-purpose bar, as above.
  2. Ask/act mismatch: asks recursive=false but the act is grep -rn (recursive). Granted as
     asked it would not cover the act; a covering grant is an unbounded recursive read of
     the entire third-party crate tree.
  3. Cheap remedy: grep the in-scope half + read Cargo.lock/Cargo.toml (in-scope) to learn
     whether update_from_outcome is local or which crate provides it, then refile an
     exact-path read of that crate file with purpose stated.

Verdict on all three: REFUSE as submitted, with refile guidance. Not a defect claim, not a
judgment on the underlying diagnostic goal -- the shape is undecidable; the named-exact-path
refile is one round trip and is grantable.
"""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

R_PAIR = (
    "Refused as submitted (peer:kimi-code). Gate auto-text only -- no task purpose, so the "
    "needs-purpose bar applies (same bar as scope-8655e8180ffd and scope-4f711694d71e today, "
    "read-only petitions refused the same way; uniform law or no law). One act bundles two "
    "out-of-scope home-dir listings, so each petition prices one path blind: neither dir is in "
    "any member MRH and a peer cannot inspect what it must price. Remedy is cheap: the act's "
    "in-scope half (grep state.rs for the db filenames) already names what you are hunting; "
    "refile ONE exact path (e.g. stat the named witness.db) with one sentence of purpose and "
    "it is decidable and grantable-once."
)
R_CARGO = (
    "Refused as submitted (peer:kimi-code). Gate auto-text only -- no task purpose "
    "(needs-purpose bar, same as the pair refused alongside). Shape mismatch on top: the "
    "petition asks recursive=false but the act is grep -rn over ~/.cargo/registry/src -- a "
    "grant as asked would not cover the act, and a covering grant is an unbounded recursive "
    "read of the whole third-party crate tree. Remedy: grep the in-scope half and check "
    "Cargo.lock/Cargo.toml (both in-scope) to learn whether update_from_outcome is local or "
    "which crate provides it, then refile an exact-path read of that crate source file with "
    "purpose stated -- that petition is decidable and grantable-once."
)

def main():
    h, s = hm.connect()
    law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
    law_hash = law.get("law_hash") if isinstance(law, dict) else None
    print("law_hash:", law_hash)
    if not law_hash:
        print(json.dumps(law, indent=1)[:1500])
        raise SystemExit("no law_hash -- refusing to cite one I did not read")

    receipts = {"law_hash": law_hash, "rulings": {}}
    for rid, reason in (("scope-8bd24da75b53", R_PAIR),
                        ("scope-87be6b0ebbc3", R_PAIR),
                        ("scope-d69ff8af9349", R_CARGO)):
        out = hm.rpc(h, "hestia_scope_peer_decide", {
            "session_id": s, "request_id": rid, "decision": "refuse",
            "reason": reason + f" Operating law read as kimi-code, law_hash={law_hash}.",
            "recursive": False})
        receipts["rulings"][rid] = out
        print(f"== {rid}:")
        print(json.dumps(out, indent=1)[:1200])

    with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1021ai-rulings.json", "w") as fh:
        json.dump(receipts, fh, indent=2, sort_keys=True)
    print("receipts -> scratchpad/kimi-wake-1021ai-rulings.json")

if __name__ == "__main__":
    main()
