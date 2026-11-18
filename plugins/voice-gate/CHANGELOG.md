# Changelog

## [0.2.0] - 2026-11-17
### Added
- Lazy in-process ONNX embedder fallback (bge-small-en-v1.5 int8, cached on first use) when the Ollama daemon is absent; Ollama stays the fast path, fail-open posture unchanged (issue #2).
- Exemplar vector cache keyed by backend ("ollama" | "onnx") so embedding spaces never mix; onnxruntime imported inside the fallback path only.
- Per-class thresholds: background p99 + 0.03 per tell class from clean repo prose, replacing the global 0.66; versioned calibration table `voice-tells-calibration.json` committed beside the exemplar cache, emitted by `voice-vector-build.py` per backend (issue #3).
- Warn-mode collision logging: background chunks crossing a class threshold are logged `vec_collision` (log-only) and recorded in the calibration table; repair contract unchanged.
- `VOICE_GATE_VECTOR=off` kill switch, `VOICE_GATE_OLLAMA_URL` endpoint override.

### Fixed
- tokenizer.json read as UTF-8 (locale codec crashed the fallback path on Windows).
- `_log_vec` creates the logs directory, so vec_* events are visible on fresh installs.

## [0.1.0] - 2026-11-16
### Added
- 55-pattern regex tell scan + optional embedder cosine (fail-open), from the live Hermes voice-gate.
- Span-level repair contracts consumed by the /voice gate.
