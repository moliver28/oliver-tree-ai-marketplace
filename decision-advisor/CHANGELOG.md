# Changelog

## [0.1.0] - 2026-11-17
### Added
- `decision-advisor` agent: runs the meta-decision pipeline (Expand, Contract, Embed) on one-way-door questions and returns a structured decision record.
- `/decide` command: delegates to the agent (runs the pipeline itself if delegation is unavailable).
- Dependency note: pairs with the `engineering/meta-decision` skill (0.2.0) in this marketplace; the agent loads it at run time.
