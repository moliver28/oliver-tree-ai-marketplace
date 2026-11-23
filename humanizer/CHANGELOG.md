# Changelog

## [1.2.0] - 2026-11-22
### Added
- Humanizer gap patterns in the shared scan core, each tagged `humanizer N` (43 new patterns; embedded register now 98): sycophancy (22), generic positive conclusions (25), persuasive-authority leftovers (27), signposting leftovers (28), rhetorical questions (32), sentence-opener tics (33), reassurance leftover (34), curly quotes (19), inline-header lists (16), Title Case headings (17, case-scoped so the shared IGNORECASE flag cannot defeat it), emoji decoration (18), false ranges (12). The humanizer skill's numbered families are now fully mirrored where regexable.
- Michael-voice hard bans now mechanically scanned: north star, delight, impactful, drive impact/change/results, stakeholder value.
- Env-configured voice-rules layer (`humanizer/hooks/voice_tells.py voice_rules_hits`, consumed by gate.py): point `DANEEL_RULES_YAML` at a named-regex YAML (same schema as the daneel style rules file) and the standing voice rules and anti-patterns ride on every scan; unset keeps the de-personalized default, fail-open. Compile semantics mirror the daneel lint engine (`make_flexible`), so one YAML source of truth drives both systems.
- `--profile resume` (ATS profile from the humanizer skill's document-type condition logic): bullets and labeled section lines exempt from S1/S3, humanizer 16/17 hits filtered; all other prose rules in force.
- STE S1/S2 fix: line-aware unit splitting (headings and bullet list items are not paragraph sentences; S1/S3/S5 still scan their text).

## [1.1.0] - 2026-11-21
### Added
- Tier 1, attraction-side embedding scores (issue #127): `learn/voice_vector_build.py` also persists the user's clean-corpus voice centroid (`learned/voice-centroid.json`, per-document chunk embeddings, optional per-channel centroids via `--channel`); `hooks/voice_tells.py` gains `voice_fit`/`vector_scores`/`vector_pass` computed inside the same single embedding pass as the tell scan (one embed per unique text per process, shared memo). Hash guard: with unchanged corpus/exemplar/background hashes the build prints `current (hash <12 chars>), nothing rebuilt` and exits without loading the embedder.
- Source-fidelity check: `hooks/gate.py --source FILE` reports `source_fidelity` (cosine of source vs rewrite embedding); the source embedding is disk-cached, hash-keyed and bounded (`learned/embed-cache.json`, max 64 entries, oldest dropped, atomic write), so a repeated /voice run on the same draft does not re-embed the source. /voice status line becomes `voice: pass (fidelity 0.91)` / `voice: N fixes applied (voice-fit 0.72)` when the signals exist.
- Tier 2, trained authorship classifier (issue #127): `learn/train_voice_classifier.py` — character 3-5-gram hashing trick (2^16 buckets, md5, log-tf, L2-normalized) + pure-Python offline SGD logistic regression (fixed seed, deterministic order, lr 0.1 with decay, 8 epochs, early stop on loss plateau, class-balanced weights). Trains on the user corpus (weight 1.0) + edit-confirmed texts (weight 0.5) against pre-edit deliveries + a deterministic synthetic AI-prose seeder (200 docs, zero personal content). Writes `learned/voice-classifier.json`; the gate exposes `p_ai` + `voice_delta` as advisory fields (fail-open, never blocking in 1.1.0); hash guard prints `nothing retrained` on unchanged inputs.
- Tier 2, post-hoc edit learning (owner ruling, issue #127): /voice records every delivery in `learned/deliveries.log` (`date`, `sha256(delivered)`, `target`); the new `/voice learn-edit <edited-file> <delivered-original>` command (core in `learn/edit_learning.py`) matches the delivery hash, measures the edit with difflib, and files it: >15% changed -> `learned/edit-delta/{before,after}/` pair (classifier retrain pending), <=15% -> durable light copy + `learned/clean-corpus-index.txt` entry (`edit-confirmed`). calibrate.py scans index entries too; the centroid builder and the classifier trainer consume the same index, hash-guarded.
- Tier 3, offline acceptance check (issue #127): `learn/acceptance_check.py` — Signal A Burrows' Delta over 60 hardcoded function words z-scored against the new `function_words` section of `learned/profile.json` (stdlib, zero setup); Signal B optional `--backend onnx` local GPT-2 small perplexity + burstiness (onnxruntime + model files in `learned/models/gpt2-onnx/`, setup estimate 3-6 min documented, defined absence line + exit 2). Never in the delivery gate; plain-number table or `--json`.
- `scripts/verify.py` enforcement for all of the above: no-rebuild/no-retrain proof without any embedder, deterministic gate advisory fields, classifier training/determinism/empty-input, learn-edit classifications, acceptance-check paths, 1.1.0 version parity.

### Changed
- `voice_vector_build.py` chunks the calibration background per document (the same chunks the centroid consumes), so one embedding pass truly serves exemplars, calibration and centroid; thresholds may shift slightly on rebuild (per-user artifacts).
- `voice_tells.py` exposes the per-user `learned/` directory via `VOICE_LEARNED_DIR` (same override contract as `VOICE_RULES_STATE`/`VOICE_GATE_LOG`) and writes artifacts atomically.
- Manifests/docs updated for the new artifacts, flags and commands; versions bumped to 1.1.0 in `plugin.json`, `plugin.yaml` and the marketplace entry.

## [1.0.0] - 2026-11-21
### Added
- Canonical consolidation: the plugin is now self-contained. The detection core moved from the separate voice-gate plugin into `hooks/voice_tells.py`, the standalone scanner into `hooks/voice_check.py`, and the gate loads its scanner from its own directory.
- Zero-LLM learn tools in `learn/`: `build_voice_profile.py` (deterministic voice profile + onboarding draft from writing samples), `calibrate.py` (per-pattern hit rates over a clean-writing corpus, writes `learned/calibration.json`), `distill_phrases.py` (recurring request phrasings from `learned/phrases.log` into `learned/rules.json`), `voice_vector_build.py` (per-user exemplar vectors + calibration into `learned/`).
- `learn/LEARN-VOICE.md`: the procedure doc (install, onboard, initial learn, enforce, continuous learn) with the explicit zero-model statement per stage and the decide-by-hand conflict rule.
- Runtime hook adapters documented in `hooks/HOOKS.md`: surfaces come from the user's learned profile, never from hard-coded path lists.
- De-personalization: every personal voice artifact left the public mirror. The machine register is the pattern list in `hooks/voice_tells.py` (55 patterns, synthetic exemplars); vectors and calibration are per-user `learned/` artifacts built by the learn tools, no longer shipped.
- LinkedIn post pipeline folded in from the linkedin-style-learner skill, de-personalized: `learn/linkedin/` (renderer, voicebook checker, lever check, templates, synthetic briefs, verification battery with regenerated goldens). Factory link allowlist default is example.org, config-driven.

### Changed
- Description and surfaces updated for the three-stage canonical contract (learn via the deterministic tools, hooks self-contained, `/voice` applies).
- `/voice --dry` and the onboarding pointer now reference `learn/VOICE_ONBOARDING.template.md`.

### Removed
- The separate voice-gate plugin entry; the owner's personal voice skill, register, exemplar vectors, calibration, and the real article briefs (all archived privately outside this repository).

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
