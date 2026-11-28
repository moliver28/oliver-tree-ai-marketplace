# learned/ - per-user artifacts (zero-LLM)

Everything in this directory is built at runtime by the learn tools or the /voice command; nothing here is a shipped payload except this README and the empty phrase sink.

- `phrases.log`: append-only, zero-LLM. After each successful /voice run, the command appends one line:
  `<date>\t<verbatim user input>`. No model tokens; a shell redirect. Ships empty: the contract is
  existence, not content.
- `profile.json`: written by `learn/build_voice_profile.py` (sentence-length distribution, paragraph
  shape, punctuation frequencies, top content n-grams, opener histogram, passive/intensifier density,
  per-pattern hit rates against the gate patterns, the `function_words` Burrows' Delta profile:
  per-document mean + sample stddev over 60 hardcoded function words, unit per-1000-words (sample
  stddev, divide by k - 1), the reference profile for `learn/acceptance_check.py --backend delta`,
  and the 1.2.0 `battery` section: per-measure mean, sample deviation, min, max, and k over the 79
  Tier A rows, plus the pooled reference rows, the per-level holdout counts, and the rank vector).
- `profile-pca.json` / `<profile-stem>-pca.json` and `profile-covariance.json` /
  `<profile-stem>-covariance.json`: written beside profile.json by
  `learn/build_voice_profile.py` (1.2.0, the delta1 rows L7-6 and L11-11). User-local R3 data
  computed from the user's samples: the PCA eigenvector with its means, deviations, and projection
  band, and the Cholesky factor of the shrunk covariance with its leave-one-out distance band.
  Rebuilt by the same command; nothing ships; absent files make the two report rows read n/a.
- `rules.json`: written by `learn/distill_phrases.py` (recurring request phrasings, deterministic merge;
  preserves a `manual` list across runs).
- `calibration.json`: written by `learn/calibrate.py` (per-pattern hit rates over the user's clean
  corpus + deviations to decide by hand). Entries of `clean-corpus-index.txt` are scanned in addition
  to the `--corpus` directory.
- `voice-tells-vectors.json` / `voice-tells-calibration.json`: written by `learn/voice_vector_build.py`
  (per-user exemplar vectors + per-class thresholds, backend-keyed). Never committed: with these files
  absent the vector layer skips itself (fail-open) and the regex layer stands.
- `voice-centroid.json`: written by `learn/voice_vector_build.py` (backend-keyed; the L2-normalized
  mean of per-document chunk embeddings of the user's clean corpus, unit `document-chunks`, plus
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
- `state/machine-bench.json`, `state/setup.json`, `state/voice-bands.json`: written by
  `learn/voice_setup.py` (1.3.0, the /voice-setup install experience). The machine bench (measured
  interpreter spawn, gate command, and battery costs), the chosen measurement level and budget, and
  the per-situation voice bands with the layer-2 factors (pooled source-blind bands + shrunk
  situation factors, k / (k + 5)). Samples and bands stay user-local; never committed; never shipped.

## The private reference store (voice-setup, 1.3.0)

The reference pool lives where the user points it, in this order:

1. The `VOICE_REFERENCE_DIR` environment variable (wins when set).
2. The setup settings file: `learned/state/setup.json`'s `reference_dir`
   (written by `learn/voice_setup.py --reference-dir <path>`).
3. The default: the learned directory itself (the plugin's `learned/`,
   movable with `VOICE_LEARNED_DIR`).

Pool layout: one `<sha256(text)[:16]>.txt` (the document text) beside one
`<same-id>.json` (the per-document vector: format version, measure-set
version, situation tag, word count, every battery row value; a harvested
document also carries its provenance row: source `harvest`, the UTC
timestamp, the word count, and the situation tag). Storing is
idempotent by the text sha256: a re-store refreshes the vector in place.
The bands and factors derive from the stored vectors; they are never
stored per-source. Nothing from a real pool enters the repo, the payload,
CI, or a test.

## Passive harvest (wave G6, consent-gated, default OFF)

The hook `hooks/harvest.py` appends accepted final drafts to this pool and
rebuilds the derived measurements mechanically. It runs only when the
settings file carries both the flag and the accepted input:

    "harvest": {
      "enabled": true,
      "accepted_dir": "<directory of accepted drafts>",
      "accepted_glob": "*.md",
      "situation": "blog"
    }

(`accepted_glob` and `situation` are optional.) With the flag off or
without `accepted_dir` the hook does nothing and logs nothing. Turning the
flag on means: accepted drafts get stored in your own local reference
pool. They are never transmitted anywhere. No model distill runs and no
repository file is written. An exact duplicate skips silently. A draft
under the battery's 500-word document floor skips with one line. Full
details: `hooks/HOOKS.md`, section "Passive harvest".

Two more files join the state files above when the loop runs:

- `state/voice-bands.json` (existing): refreshed silently by the shared
  `learn/regenerate.py` `rebuild_pool()` body after pool growth; the
  bands are advisory rows.
- `state/band-approvals.json` (wave G6): pending budget-band rows
  (candidate + active numbers, plain-words note). A budget-override band
  (`aphorism`) can change a fail line, so its candidate never lands
  silently. `python3 hooks/harvest.py --approve-bands` promotes the rows
  into the runtime state file under the source name `harvest-bands`.
  Until then the old budget stays active.

`--remeasure` refreshes: any stored vector whose measure set is stale, or
that lacks rows the current battery carries, is recomputed from the stored
text, and the bands and factors rebuild from the refreshed vectors even
with no fresh samples. The one-shot way to refresh every derived artifact
at once is the scripted regenerate pass:
`python3 learn/regenerate.py --corpus <clean writing dir> --samples <sample dir>`
(one line per step, hash-guarded builders, zero model tokens).

To point the store at a NAS mount, set the pool root to any private path
the user controls, for example:

    VOICE_REFERENCE_DIR=<reference-store-root>/Writing Style References python3 learn/voice_setup.py --samples <samples-root>

or record it once with `--reference-dir <reference-store-root>/Writing Style References`.
Replace `<reference-store-root>` with the mount point of the share. The
report names the store path, its document count, the measure-set version,
and the measured free bytes of the store drive. Nothing from a real pool
enters the repo, the payload, CI, or a test.

## Detector bands in the runtime state file (wave H-C, 2026-11-27)

The new detection methods read their thresholds from the runtime state
file (`$VOICE_RULES_STATE` or `<HERMES_HOME>/state/voice-rules.json`), not
from code constants: a source there may carry a `bands` object, for
example `"bands": {"cycling": {"t_sem": 0.62, "t_lex": 0.35},
"compression": {"sd_hi": 0.09}}`. Absent bands mean the signal stays
advisory with no fail line; invalid band entries skip per entry and log
`state_skip`; valid numbers load at scan time (issue #5 data contract,
clause 4).

Maintenance passes distill recurring phrasings from phrases.log into plugin descriptions per
MAINTENANCE.md section 10; the gate never spends tokens on vocabulary updates. Every tool above is
deterministic and spends zero model tokens; the per-user directory can be relocated with
`VOICE_LEARNED_DIR` (tests, side-by-side installs; same override contract as `VOICE_RULES_STATE`
and `VOICE_GATE_LOG`).
