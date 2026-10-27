# docs: specs, plans, standards and research

See root CLAUDE.md for the repo rules. This file covers `docs/`.

**Purpose.** `design/` (the design page `design/2026-10-27-ai-symbiont-design.html`), `plan/` (the high-level plan page), `standards/` (the quality-gates standard, `standards/quality-gates.html`), `research/` (survey and checks), working notes kept outside version control are not linked from tracked docs.

**Violation prevented: Paper Tiger and Fossil Comments.** The deliverable is the claim, so a number with a unit needs a tag; a document that contradicts the code is a fossil, so it is amended in the same change.

## Invariants
- Every claim is tagged `[measured]`, `[established]` or `[hypothesis]` on its line or table row (`check_claims.py`; `docs/standards/` is exempt because it states the rules).
- Diagrams are mermaid only, never ASCII art.
- No private address, hostname, user name or home path in any tracked doc (gitleaks rules enforce it); use a role name or an environment variable.
- Say "plays Freedoom via ViZDoom"; no speed-of-learning claims.
- The design page is approved by the owner before the plan builds on it.

## Commands
`uv run python scripts/gates/check_claims.py docs/<file>`

## Review focus
Is a number untagged? Did the code change make a paragraph false?
