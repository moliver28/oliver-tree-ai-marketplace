# learned/ - per-user artifacts (zero-LLM)

Everything in this directory is built at runtime by the learn tools or the /voice command; nothing here is a shipped payload except this README and the empty phrase sink.

- `phrases.log`: append-only, zero-LLM. After each successful /voice run, the command appends one line:
  `<date>\t<verbatim user input>`. No model tokens; a shell redirect. Ships empty: the contract is
  existence, not content.
- `profile.json`: written by `learn/build_voice_profile.py` (sentence-length distribution, paragraph
  shape, punctuation frequencies, top content n-grams, opener histogram, passive/intensifier density,
  per-pattern hit rates against the gate patterns).
- `rules.json`: written by `learn/distill_phrases.py` (recurring request phrasings, deterministic merge;
  preserves a `manual` list across runs).
- `calibration.json`: written by `learn/calibrate.py` (per-pattern hit rates over the user's clean
  corpus + deviations to decide by hand).
- `voice-tells-vectors.json` / `voice-tells-calibration.json`: written by `learn/voice_vector_build.py`
  (per-user exemplar vectors + per-class thresholds, backend-keyed). Never committed: with these files
  absent the vector layer skips itself (fail-open) and the regex layer stands.

Maintenance passes distill recurring phrasings from phrases.log into plugin descriptions per
MAINTENANCE.md section 10; the gate never spends tokens on vocabulary updates.
