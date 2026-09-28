#!/usr/bin/env python3
"""The operator surfaces are checked against ONE spec: docs/operator-surfaces/spec.json.

dp, 2026-09-28: "there needs to be a canonical ground-truth UI and functionality spec, that
evolves, and then dashboard and app versions can be checked against it."

Why this exists: the same night, #1132 put gate ratification in the desktop app only, and the
operator -- who uses the daemon's web dashboard, and has no app build -- could not find it. An
audit then found the two surfaces had drifted in both directions (the dashboard carries ~40
capabilities, the app 14) and that four of the daemon's widest-reach routes had no surface at all.
Nothing failed, because nothing said what either surface was supposed to hold.

What this checks, against the daemon's router (core/src/server/http.rs `.route(`):
  1. every route is accounted for: in a capability, or in `unsurfaced` with a reason;
  2. every route the spec names still exists (a stale spec is a false spec);
  3. each surface calls every route of each capability it is `required` to carry --
     unless the pair is in `known_gaps` (the ratchet: that list may only shrink, and a gap
     that has been closed must be removed from it, or this fails);
  4. no surface calls a route the spec does not know (an undocumented feature is drift too).
Semantics (reason rules, 409 handling, UNKNOWN rendering) are stated in the spec's `rules`
and referenced per capability; they are reviewed, not pattern-matched.

Run: python3 tools/operator_surfaces_spec_test.py            (bare; exit 1 on failure)
     python3 tools/operator_surfaces_spec_test.py --discover  (print what each surface calls)
     python3 tools/operator_surfaces_spec_test.py --matrix    (print the capability matrix, markdown)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "docs" / "operator-surfaces" / "spec.json"
ROUTER = REPO / "core" / "src" / "server" / "http.rs"
DASHBOARD = REPO / "core" / "src" / "server" / "dashboard" / "index.html"
APP_SRC = REPO / "app" / "src-tauri" / "src"
METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")

# THE RATCHET, BOUND IN CODE (GPT reviews of #1138). `known_gaps` may only shrink.
#  - Each spec `version` has a frozen gap set here, and the spec's `known_gaps` must EQUAL the set of
#    the version it declares -- no slack. (A subset rule let a gap closed on v1 be quietly reopened:
#    remove the surface, restore the exception, version unchanged, PASS.)
#  - The spec must declare the LATEST version here, so rolling `version` back to reuse an older,
#    larger set fails.
#  - Each version's set must be a subset of the previous version's: gaps shrink across versions.
#    Growing them is a migration that must be named in GAP_GROWTH_MIGRATIONS with a reason.
# Closing a gap: remove it from spec.json, bump `version`, add the smaller set here.
KNOWN_GAPS_BASELINE = {
    1: frozenset({("gates-verify", "dashboard"), ("gates-ratify", "dashboard")}),
    2: frozenset(),   # #1137 closed both dashboard gates gaps
}
GAP_GROWTH_MIGRATIONS: dict[int, str] = {}   # {version: why this version may ADD gaps}
FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- the daemon's routes ---------
def router_routes(src: str) -> set[tuple[str, str]]:
    """{(METHOD, path)} from every `.route("path", get(..).post(..))` in the router."""
    out = set()
    for m in re.finditer(r'\.route\(\s*"([^"]+)"\s*,\s*((?:[^()]|\([^()]*\))*)\)', src):
        for meth in re.findall(r'\b(get|post|put|delete|patch)\s*\(', m.group(2)):
            out.add((meth.upper(), m.group(1)))
    return out


def route_regex(path: str) -> re.Pattern:
    parts = [("[^/]+" if seg.startswith(":") else re.escape(seg)) for seg in path.split("/")]
    return re.compile("^" + "/".join(parts) + "$")


# ---------------------------------------------------------------- what a surface calls --------
def _normalize(lit: str) -> str:
    """A call's path with its interpolations as `:p` and no query string."""
    lit = re.sub(r"\$\{[^}]*\}", ":p", lit)          # JS template
    lit = re.sub(r"\{[^}]*\}", ":p", lit)             # Rust format!
    return lit.split("?", 1)[0]


# Every call style the dashboard uses: apiFetch(path, opts), hubFetch(path, opts),
# polSend('METHOD', path, body), and wireOperatorAct({ endpoint: path }) -- which always POSTs.
# No comment stripping: a `/*` inside a string (a glob) swallowed everything to the next `*/` and
# hid real calls. Instead a literal counts only in a CODE position -- after ( , : = + ? [ -- which a
# path mentioned in a comment's prose never is.
# Dashboard helpers that take no method argument and always send one. Asserted against the
# dashboard itself in main(), so a renamed or changed helper fails here instead of being read as GET.
FIXED_METHOD_HELPERS = {"hubAct": "POST"}
_DASH_LIT = re.compile(r"([(,:=+?\[])\s*([`'\"])(/api/[^`'\"]*)\2")


def dashboard_calls(html: str) -> set[tuple[str, str]]:
    js = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S))
    out = set()
    for m in _DASH_LIT.finditer(js):
        path = m.group(3)
        tail = js[m.end():m.end() + 160]
        # '/api/vault/' + encodeURIComponent(name) [+ '/retire']
        cat = re.match(r"\s*\+\s*[^,)]+?(?:\s*\+\s*(['\"`])(/[^'\"`]*)\1)?(?=\s*[,)])", tail)
        if path.endswith("/") and cat:
            path += ":p" + (cat.group(2) or "")
        before = js[max(0, m.start() - 60):m.start() + 1]
        # any helper called as fn('METHOD', path): polSend, aliasAct, ...
        named = re.search(r"\w+\(\s*'(GET|POST|PUT|DELETE|PATCH)'\s*,\s*$", before)
        fixed = re.search(r"\b(\w+)\(\s*$", before)
        if named:
            meth = named.group(1)
        elif re.search(r"endpoint\s*:$", before):
            meth = "POST"                                  # wireOperatorAct always POSTs
        elif fixed and fixed.group(1) in FIXED_METHOD_HELPERS:
            meth = FIXED_METHOD_HELPERS[fixed.group(1)]
        else:
            window = js[m.end():m.end() + 400]
            close = window.find(");")
            opts = window[: close if close != -1 else 400]
            mm = re.search(r"method\s*:\s*['\"](POST|PUT|DELETE|PATCH)['\"]", opts)
            meth = mm.group(1) if mm else "GET"
        out.add((meth, _normalize(path)))
    return out


def app_calls(src: str) -> set[tuple[str, str]]:
    """Three styles in app/src-tauri/src: daemon::get/send(&state, [Method::X,] "/api/.."),
    reqwest `.post(format!("{daemon_url}/api/.."))` (sign-in, remote fleet), and a path built
    with format! into a variable that the NEXT daemon:: call sends."""
    out = set()
    for m in re.finditer(r'"(?:\{[^}"]*\})?(/api/[^"]*)"', src):
        before = src[max(0, m.start() - 220):m.start()]
        after = src[m.end():m.end() + 600]
        after = after[: after.find("\n}") if "\n}" in after else len(after)]   # this fn only
        verb = re.search(r"\.(get|post|put|delete|patch)\(\s*&?(?:format!\()?\s*$", before)
        if verb:
            meth = verb.group(1).upper()
        elif re.search(r"reqwest::get\(\s*&?(?:format!\()?\s*$", before):
            meth = "GET"
        else:
            # the daemon:: call this literal is an argument of, or -- for a path built first --
            # the next one after it
            opens = list(re.finditer(r"daemon::(get|send_checked|send)\b", before[before.rfind(";") + 1:]))
            call = None
            if opens:
                call = (opens[-1].group(1), before[before.rfind(";") + 1:][opens[-1].start():])
            else:
                nxt = re.search(r"daemon::(get|send_checked|send)\b[^;]*", after)
                if nxt:
                    call = (nxt.group(1), nxt.group(0))
            if call is None:
                continue
            mm = re.search(r"Method::(POST|PUT|DELETE|PATCH)", call[1])
            meth = "GET" if call[0] == "get" else (mm.group(1) if mm else "POST")
        out.add((meth, _normalize(m.group(1))))
    return out


def resolve(calls: set[tuple[str, str]], routes: set[tuple[str, str]]) -> tuple[set, set]:
    """-> (matched routes, calls that match no route)."""
    matched, stray = set(), set()
    for meth, path in calls:
        hits = {(rm, rp) for rm, rp in routes if rm == meth and
                (route_regex(rp).match(path) or route_regex(path.replace(":p", ":x")).match(rp))}
        if hits:
            matched |= hits
        else:
            stray.add((meth, path))
    return matched, stray


def surface_calls() -> dict[str, set[tuple[str, str]]]:
    app_src = "\n".join(p.read_text() for p in sorted(APP_SRC.rglob("*.rs")))
    return {"dashboard": dashboard_calls(DASHBOARD.read_text()), "app": app_calls(app_src)}


def parse_route(s: str) -> tuple[str, str]:
    meth, path = s.split(" ", 1)
    return meth.upper(), path.strip()


# ---------------------------------------------------------------- the checks ------------------
def main(argv: list[str]) -> int:
    routes = router_routes(ROUTER.read_text())
    calls = surface_calls()
    resolved = {s: resolve(c, routes) for s, c in calls.items()}

    if "--discover" in argv:
        for s, (matched, stray) in resolved.items():
            print(f"## {s}: {len(matched)} route(s) called")
            for r in sorted(matched, key=lambda x: (x[1], x[0])):
                print(f"   {r[0]:6} {r[1]}")
            for r in sorted(stray):
                print(f"   ?? {r[0]:6} {r[1]}   (matches no route)")
        return 0

    html = DASHBOARD.read_text()
    for helper, meth in FIXED_METHOD_HELPERS.items():
        body = re.search(r"function " + helper + r"\(.*?\n  \}", html, flags=re.S)
        check(f"dashboard helper {helper}() still exists and still sends {meth} "
              f"(FIXED_METHOD_HELPERS in this file)",
              body is not None and f"method: '{meth}'" in body.group(0))

    spec = json.loads(SPEC.read_text())
    caps = spec["capabilities"]
    surfaces = spec["surfaces"]
    rules = {r["id"] for r in spec["rules"]}
    spec_routes: dict[tuple[str, str], str] = {}
    for c in caps:
        for r in c["routes"]:
            pr = parse_route(r)
            # one route, one capability: a dict would silently let the later capability win
            check(f"route {r} is named by two capabilities: {spec_routes.get(pr)} and {c['id']}",
                  pr not in spec_routes)
            spec_routes.setdefault(pr, c["id"])
    unsurfaced = {}
    for u in spec.get("unsurfaced", []):
        check(f"unsurfaced {u.get('route')} states why (the README promises it)",
              isinstance(u.get("why"), str) and u["why"].strip() != "")
        check(f"unsurfaced route {u.get('route')} is listed twice", parse_route(u["route"]) not in unsurfaced)
        unsurfaced[parse_route(u["route"])] = u
    gaps = {(g["capability"], g["surface"]) for g in spec.get("known_gaps", [])}
    version = spec.get("version")
    latest = max(KNOWN_GAPS_BASELINE)
    check(f"spec version {version} is the latest in KNOWN_GAPS_BASELINE ({latest}): an older "
          f"version's gap set cannot be reused", version == latest)
    baseline = KNOWN_GAPS_BASELINE.get(version, frozenset())
    for g in sorted(gaps - baseline):
        check(f"known_gaps adds {g[0]}/{g[1]}, which version {version}'s baseline does not hold: the "
              f"list only shrinks -- a new gap is a migration (new version + GAP_GROWTH_MIGRATIONS)", False)
    for g in sorted(baseline - gaps):
        check(f"version {version}'s baseline still holds {g[0]}/{g[1]}, which spec.json no longer lists: "
              f"record the closure (bump version, add the smaller set) so it cannot be reopened", False)
    versions = sorted(KNOWN_GAPS_BASELINE)
    for prev, cur in zip(versions, versions[1:]):
        grown = KNOWN_GAPS_BASELINE[cur] - KNOWN_GAPS_BASELINE[prev]
        check(f"version {cur} adds gaps {sorted(grown)} over version {prev} without a named "
              f"migration in GAP_GROWTH_MIGRATIONS", not grown or cur in GAP_GROWTH_MIGRATIONS)

    if "--matrix" in argv:
        print("| capability | kind | risk | " + " | ".join(surfaces) + " | routes |")
        print("|---|---|---|" + "---|" * len(surfaces) + "---|")
        for c in caps:
            cells = []
            for s in surfaces:
                st = c["surfaces"][s]["status"]
                cells.append(st + (" (gap)" if (c["id"], s) in gaps else ""))
            print(f"| {c['id']} | {c['kind']} | {c['risk']} | " + " | ".join(cells)
                  + " | " + "<br>".join(c["routes"]) + " |")
        return 0

    # 0. the spec is well-formed
    ids = [c["id"] for c in caps]
    check("capability ids are unique", len(ids) == len(set(ids)))
    for c in caps:
        for k in ("id", "title", "kind", "risk", "routes", "surfaces"):
            check(f"{c.get('id')}: has '{k}'", k in c)
        check(f"{c['id']}: kind is read|write", c.get("kind") in ("read", "write"))
        check(f"{c['id']}: risk is low|medium|high|critical", c.get("risk") in ("low", "medium", "high", "critical"))
        for r in c.get("rules", []):
            check(f"{c['id']}: rule '{r}' is defined in rules[]", r in rules)
        for s in surfaces:
            e = c["surfaces"].get(s)
            check(f"{c['id']}: states an obligation for surface '{s}'", e is not None)
            if e is None:
                continue
            check(f"{c['id']}/{s}: status is required|planned|excluded",
                  e.get("status") in ("required", "planned", "excluded"))
            if e.get("status") in ("planned", "excluded"):
                check(f"{c['id']}/{s}: a {e.get('status')} surface says why", bool(e.get("why")))

    # 1. every route is accounted for
    for r in sorted(routes, key=lambda x: (x[1], x[0])):
        check(f"route {r[0]} {r[1]} is in the spec: add it to a capability, or to `unsurfaced` "
              f"with a reason", r in spec_routes or r in unsurfaced)
    # 2. the spec names only routes that exist
    for r, cid in spec_routes.items():
        check(f"{cid}: route {r[0]} {r[1]} does not exist in the router (stale spec)", r in routes)
    for r in unsurfaced:
        check(f"unsurfaced route {r[0]} {r[1]} does not exist in the router", r in routes)
        check(f"route {r[0]} {r[1]} is both unsurfaced AND in a capability", r not in spec_routes)
    # 3. each surface carries what it is required to, gaps excepted -- and the ratchet
    for c in caps:
        for s in surfaces:
            e = c["surfaces"].get(s) or {}
            have = resolved[s][0]
            present = all(parse_route(r) in have for r in c["routes"])
            if e.get("status") == "required":
                if (c["id"], s) in gaps:
                    check(f"{c['id']} is now present on {s}: remove it from known_gaps "
                          f"(the list only shrinks)", not present)
                else:
                    missing = [r for r in c["routes"] if parse_route(r) not in have]
                    check(f"{c['id']} is REQUIRED on {s} and {s} does not call: {', '.join(missing)}",
                          present)
            elif e.get("status") == "excluded":
                called = [r for r in c["routes"] if parse_route(r) in have]
                check(f"{c['id']} is EXCLUDED from {s} ({e.get('why')}) but {s} calls: "
                      f"{', '.join(called)}", not called)
    for cid, s in gaps:
        cap = next((c for c in caps if c["id"] == cid), None)
        check(f"known_gaps names an unknown capability '{cid}'", cap is not None)
        if cap:
            check(f"known_gaps lists {cid}/{s} but it is not `required` there",
                  (cap["surfaces"].get(s) or {}).get("status") == "required")
    # 4. no surface calls what the spec does not know
    for s, (matched, stray) in resolved.items():
        for r in sorted(matched):
            check(f"{s} calls {r[0]} {r[1]}, which no capability names (undocumented feature)",
                  r in spec_routes)
        for r in sorted(stray):
            check(f"{s} calls {r[0]} {r[1]}, which matches no daemon route", False)

    for f in FAILS:
        print("FAIL", f)
    n_gaps = len(spec.get("known_gaps", []))
    print(f"operator surfaces spec: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s)); "
          f"{len(caps)} capabilities, {len(routes)} routes, {n_gaps} known gap(s) on the ratchet")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
