# ADR-0001: Name — Hestia

**Date:** 2026-05-15
**Status:** Accepted
**Authors:** dp + CBP-Claude (Opus 4.7)

## Context

The Web4 local toolkit (this project) needed a name. dp's brief: "governance-related, somewhat successful mythology would be good. hermeticism? they don't really have mythology. greek? worked until didn't. i dunno. invent something. or just call it 4-something."

Candidates evaluated:
- Hestia (Greek goddess of hearth, home, state)
- Forseti (Norse god of justice)
- Numina (Latin: divine presences)
- Vesta (Roman counterpart of Hestia)
- Atrios (coined; plural-feel of atria)
- Themis (Greek goddess of divine law)
- Janus (Roman god of beginnings, gates, dualities)

## Decision

**Hestia.**

## Rationale

- Greek goddess of hearth, home, family — *and the state*. Every Greek polis had a public hearth dedicated to her. Governance is directly within her purview.
- Most honored of the Olympians; received the first portion of every sacrifice. Conceptually load-bearing in the mythology she comes from.
- The hearth metaphor scaffolds the entire product narrative:
  - Local-first by default (a hearth is the most local thing)
  - Persistence through care (the fire is tended; the trust state is maintained)
  - Hospitality (Greek *xenia*) gives us the user-agent relationship model for free
  - Federation = carrying embers to light a new colony's hearth — the Greek colonial ritual
- "Greek worked until didn't" applies to Athens-the-city, not to the household goddess. Hestia was the continuity layer underneath.
- Pronounceable, warm, non-technical-friendly (HESS-tee-ah).
- Doesn't sound like security software or dev tooling — sounds like a place you'd want to be.

## Trade-offs accepted

- **Namespace collision with Hestia Control Panel** (HestiaCP, 4.3K GitHub stars, MIT-licensed web hosting control panel). Different category (web hosting vs AI agent trust infrastructure); confusion risk is low. Search-engine confusion will be transient. Trade-dress separation is real.
- **Package names will use `hestia-` prefix.** `hestia` on PyPI and npm is taken by unrelated projects. We ship as `hestia-sdk` (Python), `hestia-core` (Rust), `@hestia/plugin-sdk` (npm scope). Same pattern we navigated for `web4 → web4-sdk` on 2026-05-15.
- **Trademark filing deferred.** Phase 2 task after v1 launch validates the name is sticking.

## Alternatives rejected

- **Forseti / Numina / Vesta / Themis** — namespace collisions on PyPI, npm, crates.io, GitHub stars-worth-of-projects. Significant prior art.
- **Atrios (coined)** — clean namespace but zero semantic load. Coined names require building the brand from scratch; we wanted the mythology to do narrative work for us.
- **Janus** — perfect conceptual fit (two-faced god of thresholds), but heavily used in security software and occasionally negative connotation ("two-faced" → duplicitous).
- **4-something** (dp's joke suggestion) — clever wordplay but loses the metaphor scaffold.

## Consequences

- Repository: `dp-web4/hestia` (created 2026-05-15).
- Public name: **Hestia** (capital H).
- Tagline candidates: *"Tend your hearth. Your agents are guests."* / *"Web4 begins at home."* / *"Local-first trust for the agents you've chosen."*
- Domain: `hestia.dev` (subject to availability — pending check); `hestia.web4.foundation` as redundant.
- All package names use `hestia-` prefix.
