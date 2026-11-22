# learned/ - per-user artifacts (zero-LLM)

Everything in this directory is built at runtime by the learn tools or the /voice command; nothing here is a shipped payload except this README and the empty phrase sink.

- `phrases.log`: append-only, zero-LLM. After each successful /voice run, the command appends one line:
  `<date>\t<verbatim user input>`. No model tokens; a shell redirect. Ships empty: the contract is
  existence, not content.
- `profile.json`: written by `learn/build_voice_profile.py` (sentence-length distribution, paragraph
  shape, punctuation frequencies, top content n-grams, opener histogram, passive/intensifier density,
  per-pattern hit rates against the gate patterns, plus the `function_words` Burrows' Delta profile:
  per-document mean + stddev over 60 hardcoded function words, unit per-1000-words — the reference
  profile for `learn/acceptance_check.py --backend delta`).
- `rules.json`: written by `learn/distill_phrases.py` (recurring request phrasings, deterministic merge;
  preserves a `manual` list across runs).
- `calibration.json`: written by `learn/calibrate.py` (per-pattern hit rates over the user's clean
  corpus + deviations to decide by hand). Entries of `clean-corpus-index.txt` are scanned in addition
  to the `--corpus` directory.
- `voice-tells-vectors.json` / `voice-tells-calibration.json`: written by `learn/voice_vector_build.py`
  (per-user exemplar vectors + per-class thresholds, backend-keyed). Never committed: with these files
  absent the vector layer skips itself (fail-open) and the regex layer stands.
- `voice-centroid.json`: written by `learn/voice_vector_build.py` (backend-keyed; the L2-normalized
  mean of per-document chunk embeddings of the user's clean corpus — unit `document-chunks` — plus
  optional per-channel centroids under `channels` when built with `--channel`). Consumed by
  `hooks/voice_tells.py` `voice_fit` for the gate's attraction-side score. Hash-keyed/no-recompute rule:
  the build hashes the sorted corpus contents + the exemplar set first; with unchanged hashes it prints
  `current (hash <12 chars>), nothing rebuilt` and never loads the embedder.
- `embed-cache.json`: written by `hooks/gate.py --source` (bounded disk cache of source-text embeddings,
  max 64 entries, oldest dropped on overflow, atomic write; key `<backend>:<sha256(text)[:16]>`). The
  no-recompute rule: a repeated /voice run on the same draft reuses the cached source embedding instead
  of re-embedding it.
- `voice-classifier.json`: written by `learn/train_voice_classifier.py` (hashed char 3-5-gram logistic
  regression: buckets, hash algo, sparse weights, bias, `voice_baseline`, advisory `thresholds`,
  `corpus_hash`, `seeder_version`, plain-number train stats). Hash-keyed/no-recompute rule: the corpus
  hash covers every contributing document (clean corpus, edit-delta, clean-corpus-index) plus the
  seeder/bucket config; unchanged inputs print `nothing retrained` and skip training.
- `deliveries.log`: append-only, written by /voice after each successful NON-dry delivery (shell append
  + sha256 of the delivered copy, zero model tokens): `<date>\t<sha256(delivered)>\t<target id/path>`.
  Ships absent (created by the first delivery); `/voice learn-edit` matches its edited file against
  column 2.
- `edit-delta/`: written by `learn/edit_learning.py` (`/voice learn-edit`). `after/<sha256(AFTER)>.txt`
  + `before/<sha256(AFTER)>.txt` pairs from substantial edits (>15% of tokens changed; classifier
  positives at weight 0.5 / negatives) and `light/<sha256(AFTER)>.txt` copies from light edits
  (<=15%). Deterministic filenames keyed by the AFTER hash; re-runs overwrite identical content.
- `clean-corpus-index.txt`: append-only index of edit-confirmed texts, one
  `<path>\tedit-confirmed` line per light edit (the durable copy under `edit-delta/light/`). Consumed
  by `learn/calibrate.py` (regex layer), the centroid builder and the classifier trainer; all three
  are hash-guarded, so a new index entry changes the hash and triggers the one rebuild that reflects it.
- `models/gpt2-onnx/`: optional user-placed GPT-2 small ONNX files (`model.onnx`, `vocab.json`,
  `merges.txt`, ~250 MB) for `learn/acceptance_check.py --backend onnx`; never downloaded by the plugin,
  never shipped, never in the delivery gate.

Maintenance passes distill recurring phrasings from phrases.log into plugin descriptions per
MAINTENANCE.md section 10; the gate never spends tokens on vocabulary updates. Every tool above is
deterministic and spends zero model tokens; the per-user directory can be relocated with
`VOICE_LEARNED_DIR` (tests, side-by-side installs — same override contract as `VOICE_RULES_STATE`
and `VOICE_GATE_LOG`).
