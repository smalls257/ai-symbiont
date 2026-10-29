# ai-symbiont

**The frontier is for everyone. Symbiont makes it yours.**

A self-improvement loop for your own projects: it mines your agent's history for what went wrong and how it was fixed, learns overnight, and brings those lessons back the next time you work. It remembers what went wrong, so your agent doesn't repeat it.

- **Plug** (any coding agent, via MCP and hooks): a small Llama 3.2 1B reader behind a no-model ranker. Round 1 of its scored test tied on the primary measure, and it abstains instead of inventing a fix when given the wrong repository's lessons. Round 2 is pre-registered and running.
- **Core** (a personal Glimmer): learns from a repository's own history plus teacher runs by Muse Spark. Scored test pending.
- **Evolve** (plays Freedoom via ViZDoom): a toy loop where lessons from the agent's own play are tested on levels it never saw. Held-out test running; evolution itself has tied so far.

Pre-registered plans, controls, reported ties and guards (spend caps, privacy, held-out integrity) are part of the design, not an afterthought.

- **Start here:** [the explainer](docs/explainer/index.html). It reads at four depths (newcomer, builder, expert, judge) and covers how we built it, how we test it and what we've measured, including the results that hurt.
- [Design page](docs/design/2026-10-27-ai-symbiont-design.html) · [Quality-gates standard](docs/standards/quality-gates.html) · [Engineering rules](CLAUDE.md)
