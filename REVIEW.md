# Review flow (MO / public / zcode / hermes)

Single surface: this repo's issues and PRs.

- Ideas: open an issue with the idea template (any depth of rigor; triage classifies).
- Triage (Daneel, every 6h): note + issues -> labeled TODOs.
- Build: issues labeled `zcode` are zcode's queue.
- Review: every PR gets label `mo-review` before merge. MO reviews from any UX
  (browser, zcode session, Hermes chat). Approve in one place = approved everywhere.

## Approval law (MO, 2026-11-17)

Automation (triage pipeline, agents, zcode) may FILE issues autonomously. Anything beyond filing (implementation, zcode dispatch, PRs, merges, agent-trigger labels) requires MO's explicit approval. `zcode-go` label = the only auto-start green light; a bare `zcode` label means queue only, never auto-run.
