# Changelog

## [0.3.1] - 2026-11-18
### Fixed
- State-file loader now trial-compiles each learned/register pattern: an entry that does not compile is dropped and logged (`state_skip`, with source + entry id) instead of crashing the merged compile and silently disabling the whole gate (regex + vector). Belt-and-braces try/except on the final compile falls back to embedded-only with an `error` log. Contract now matches the docs: entry-level problems skip just that entry; valid entries still apply.
- `voice-vector-build.py` repo-root resolution walks up to the dir whose `.claude-plugin` holds `marketplace.json` (was `parents[1]`, which escaped the repo after the plugins/* flatten and broke the documented default rebuild). verify.py now checks the resolved default corpus root is inside the repo (CI-safe, no embedders).

### Changed
- Pattern-count claims corrected 55 -> 61 in README + both plugin manifests, with a verifier parity check (claimed count == PATTERNS) so the number cannot drift again; docstring signature drift fixed; verify 0-byte scan scoped to tracked files; description checks read the full frontmatter block (multi-line YAML), bound aligned at 300.

## [0.3.0] - 2026-11-17
### Added
- Learn/apply decoupling, marketplace half (issue #5): rules load at scan time from the runtime state file `<HERMES_HOME>/state/voice-rules.json` (path override `VOICE_RULES_STATE`), keyed per-source provenance (register, learn pass, owner manual entries). Valid state entries merge/override the embedded PATTERNS/EXEMPLARS (identical regex replaces the earlier label in place, later source wins; exemplars dedupe on exact text) and per-class thresholds override the embedded calibration. The runtime gate and the published plugin share this one loading contract.
- Fail-open posture unchanged: absent state file -> embedded defaults silently (pre-loader behavior identical); corrupt/invalid file -> embedded defaults + one `state_skip` log line per state change; entry-level problems skip just that entry and log while valid entries still apply. New log events: `state_load`, `state_skip`, `state_uncalibrated` (learned exemplar not yet vectorized; rebuild to enforce it in the vector layer).
- verify.py drift check (issue #5): the runtime gate's embedded rule data must hash-match the published mirror, and a state file present on the machine must parse under the shared loader; a machine with neither gets an explicit SKIP line (CI path). The check is deterministic and can never fail CI.
- voice-vector-build.py rebuilds from the effective exemplar set (embedded + state-file; state exemplars beyond the embedded list get auto-labels tell-<i>).
- `VOICE_GATE_LOG` env override for the log sink (resolves per call; tests and side-by-side installs).

### Changed
- Exemplar-cache verifier check generalized from a hardcoded count (18) to "covers every embedded exemplar", since state exemplars can legitimately grow the cache after a rebuild.

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
