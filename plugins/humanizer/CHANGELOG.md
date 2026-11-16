# Changelog

## [0.1.0] - 2026-11-16
### Added
- /voice command with learn/scan/apply stages and one-line gate status.
- Deterministic hooks/gate.py: pass = silence (0 tokens); fail = span-level repair contract (max 5, family-deduped); fail-open.
- Learned invocation sidecar (phrases.log), zero-LLM.
