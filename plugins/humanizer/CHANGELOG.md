# Changelog

## [0.2.0] - 2026-11-16
### Added
- ASD-STE100 layer in the gate: sentence/paragraph length, active voice, filler chains, -ing chains, vague intensifiers, dangling this/these. `--surface chat` enforces STE on chat output; `--surface public` runs tell scan + STE.
- Source-context-only rule: rewrites draw only on the onboarding profile and provided text; nothing invented; missing context marked `[note: needs source]`.
- Onboarding sections 6/6b: STE-mode choice and the chat/public nudge hooks, woven into setup.

## [0.1.0] - 2026-11-16
### Added
- /voice command with learn/scan/apply stages and one-line gate status.
- Deterministic hooks/gate.py: pass = silence (0 tokens); fail = span-level repair contract (max 5, family-deduped); fail-open.
- Learned invocation sidecar (phrases.log), zero-LLM.
