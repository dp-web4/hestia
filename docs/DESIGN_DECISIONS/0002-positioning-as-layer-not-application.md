# ADR-0002: Hestia is a layer, not a replacement application

**Date:** 2026-05-15
**Status:** Accepted
**Authors:** dp + CBP-Claude (Opus 4.7)

## Context

The initial framing of the Web4 local toolkit was ambiguous: it could be read as a "multi-client dashboard" (a place users live, alongside or instead of Claude Code / Cursor / etc.), or as a transparent layer that augments those agents in place. The two framings produce different products.

dp clarified: *"we are not replacing anyone's agent. we're making their agent-of-choice web4 compliant (via plugin), and layering web4 identity/trust functionality on top of what they already do."*

## Decision

Hestia is **infrastructure, not an application.** Specifically:

- Users **never live in Hestia's UI.** They live in Claude Code, Cursor, OpenClaw, Cline, ChatGPT desktop, or whatever agent they already chose.
- Hestia runs alongside, exposes credentials and society state to those agents via MCP, observes their tool calls through plugins, and surfaces an inspection UI when (and only when) the user wants to look at what's been happening.
- Hestia does NOT compete with Claude Code, Cursor, Cline, OpenClaw, Conductor, Claude Code Agent View, or any agent or agent-dashboard. Every one of them is a target plugin — they become more capable by plugging into Hestia.

The analogue: Hestia is to agent ecosystems what TLS is to HTTP, what DNSSEC is to DNS, what password managers are to login forms — a transparent layer that makes the thing the user actually cares about (their agent of choice) more trustworthy, without changing what they touch.

## Rationale

- **Adoption friction.** Asking users to switch tools is the largest friction point in any product. By being purely additive, Hestia removes that ask entirely.
- **Ecosystem alignment.** We're not in a zero-sum game with agents we want to integrate with. Their success feeds us.
- **Differentiation.** Microsoft's Agent Governance Toolkit (the closest competitor) is enterprise-imposed governance over agents Microsoft controls. We're user-sovereign governance over agents the user chose. Same Ed25519 + DIDs + trust scoring; different question about *who's in charge*.
- **Plugin model is load-bearing.** Three working Web4 governance plugins already exist (for Claude Code, OpenClaw, ruflo). They demonstrate the pattern; the work is unifying them under one SDK + central trust state.

## Test for design calls

When a design question comes up, ask: *"Is this adding to what users already love, or is this trying to replace it?"* If the answer is "replace," redesign.

## Specific consequences

- The Tauri app's primary surface is **NOT** a dashboard for active agent sessions. The inspection UI exists for occasional review (like checking a password manager's audit log), default state closed.
- The Plugin Authoring Kit is a **load-bearing** deliverable — without great plugins for the agents users already chose, Hestia has no product.
- Marketing assets must show *the user's existing agent UI* (e.g. Claude Code with a Hestia indicator), not Hestia's UI. The visible primary surface is always the user's agent.
- Onboarding flow: "we found Claude Code on this machine — want to make it Web4-compliant? [install plugin]" rather than "welcome to your new dashboard."

## What this does NOT mean

- We still ship a UI (the inspection surface). Just not as the primary user-facing thing.
- We still have opinions about how plugins should be structured (the PAK contract). Just not opinions about what agent users should use.
- We still build a real product (vault, society state, witness chain, federation). Just delivered as a layer those products are reached through, not as a destination.

## References

- Original positioning ambiguity: see [strategy doc](https://github.com/dp-web4/private-context) prior to 2026-05-15
- The framing fix: dp's directive on 2026-05-15
