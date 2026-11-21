# Changelog

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
