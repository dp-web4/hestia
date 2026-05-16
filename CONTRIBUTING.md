# Contributing to Hestia

This project is in **Phase 0** — foundations being laid. The API surface, repository structure, and module boundaries are not yet stable. If you're considering contributing, the following will help.

## What we welcome right now

1. **Plugin authors.** If you maintain or work on an AI agent client (Claude Code, OpenClaw, Cursor, Cline, ruflo, Continue, Aider, Codex, Ollama-frontend, LM Studio, Jan, Msty, anything that accepts plugins or speaks MCP) — talk to us. We want to make your tool Web4-compliant via a plugin. See [docs/PLUGIN_AUTHORING_GUIDE.md](docs/PLUGIN_AUTHORING_GUIDE.md).

2. **Design partners.** We need 5-10 users actively using 2+ AI agents who have the scattered-credentials problem. Phase 0 design partners get direct conversation with maintainers, early access to the vault MVP, and substantial say in the v1 API surface. Email dp@metalinxx.io with a one-paragraph "here's how I use AI agents and what's broken about it" — that's the application.

3. **Issues and feature requests.** Open one. We respond. Be specific about the user problem (not just the technical fix). "When I rotate my npm token, I have to update 4 places and one of my IDE configs always misses it" beats "add token rotation feature."

4. **Specification feedback.** Hestia is built on the Web4 ontology spec. If you spot ambiguity, contradiction, or under-specification in how Hestia uses Web4 concepts, file an issue here and we'll route to the upstream spec if needed.

## What we're not ready for yet

- **Large unsolicited PRs.** The API isn't stable. A 5,000-line PR proposing a new architecture will probably need to be largely thrown away. Open an issue first; let's converge on direction together.
- **Premium-tier work.** Hardware binding, cloud backup, payment integration — these are Phase 3 deliverables and intertwined with commercial strategy. Defer.

## Development setup

(Will be filled in as Phase 0 progresses. Watch this section.)

### Quick environment check (placeholder)

```bash
# Check you have the required toolchain
rustc --version        # 1.80+
cargo --version
node --version         # 20+
npm --version
python3 --version      # 3.10+
```

## How decisions get made

Hestia is part of the [Web4 project family](https://github.com/dp-web4/web4). Significant decisions are documented as ADRs in `docs/DESIGN_DECISIONS/`. The high-level strategy and PRD live in [`dp-web4/private-context/plans/`](https://github.com/dp-web4/private-context) (visible to maintainers; summaries surface here as ADRs).

Cross-model review is part of how we calibrate. Major design changes get reviewed by:
- The maintainers (humans + Claude instances on the dp-web4 fleet)
- External cold-context models (Kimi, Nova/GPT) — see prior reviews at [`web4/forum/`](https://github.com/dp-web4/web4/tree/main/forum) for the pattern.

If you want to propose a major change, frame it so a cold reader can evaluate it without context from this conversation. That makes review actually possible.

## Code style

- **Rust:** `cargo fmt` + `cargo clippy --all-targets`. No warnings on `main`.
- **TypeScript:** `prettier` defaults. `tsc --noEmit` clean. ESLint configured per-package.
- **Python:** `ruff` format + check.

Pre-commit hooks will be added in Phase 0.

## Licensing of contributions

By contributing, you agree your contribution is licensed under the same terms as the project: **AGPL-3.0-or-later**. We do not require a CLA. The AGPL terms apply to the project; if you contribute, your contribution becomes part of the AGPL-licensed work.

If you want to contribute under different terms (e.g., as part of a commercial integration that needs the commercial license), reach out — we'll figure out what makes sense.

## Authorship & methodology

Hestia is being developed by a small team that includes **multiple Claude instances (Anthropic) as active collaborators**. Code, documentation, and design iteration are substantially AI-assisted. This is the same methodology used across the Web4 family of projects.

We treat cross-model review as a discipline (Kimi, Nova/GPT, cold-context Claude). When external review flags drift between the framework and the empirical work, we either downgrade the claim or add the empirical scaffolding. We don't defend framing for its own sake.

Specific failure mode external reviewers have consistently flagged: AI-assisted teams tend toward *elegant isomorphism* (coherent frameworks) at the expense of *empirical novelty* (testable predictions). Contributors should be aware that this is structurally present and call it out when they see it.

## Conduct

Be respectful. Be specific. Disagree on substance, not on people. We're a small team in a small ecosystem; reputational damage from bad behavior is real and durable.

We don't have a separate code-of-conduct document yet — Phase 0 deliverable.

## Contact

dp@metalinxx.io for design-partner inquiries, commercial-license questions, and significant proposals. GitHub Issues for everything else.
