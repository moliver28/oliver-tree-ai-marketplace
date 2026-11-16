# Calibration recipe (semantic tell guard)

Verified configuration for Layer B. Source engine: `voice_guard.py` (owner's install) — reproduce the same semantics for any author.

## Embedding batching
- Batch embeds in chunks of <= 64 with one retry per chunk. Ollama's tokenizer subprocess crashes on large batches (~170+ items in one request) and on unlucky items; on final failure of a chunk, mark those sentences as uncovered (embeddings None) and skip them in vector scoring rather than aborting — the rules arm still covers every sentence, so coverage gaps degrade, never break the gate.
- Warm the model (`keep_alive: "15m"`) and expect a ~0.5-2s check after warmup.

## Mean-centering (required)
Subtract the author-corpus centroid from both sentence and exemplar embeddings before each cosine for tell classes. Why: every sentence in one domain shares a large direction (topic), which inflates background similarity and buries paraphrase tells; centering removes the domain direction and is what makes paraphrase-level detection possible with a small retrieval model.

## Threshold law (init calibration)
For each tell class: `threshold = max(base_floor, min_exemplar_self_sim - 0.05, corpus_background_p99 + 0.03)` where background = author-corpus sentences' similarity to that class, computed the same centered way. If a class cannot clear the corpus without collision, degrade that class to warn-mode (warnings only, no hard fail) and say so in output. Re-run calibration on every init.

## Stylometric arm
11 deterministic features per sentence, z-normalized against the author corpus. Floor the feature sigma at 0.20: a single binary feature (e.g. there/here-opener) carries ~12-sigma leverage under raw corpus variance, which vetoes everything. Gate rule: hard error only when the semantic hit AND the stylometric vote agree; disagreement downgrades to a warning unless the semantic margin is >= +0.10 over threshold (high-confidence catch stands alone).

## Voice-fit arm
Per-sentence similarity against the author corpus with raw (uncentered) similarity; a per-sentence floor from the corpus nearest-neighbor distribution (15th percentile - 0.02, clamped 0.18-0.42). Rewrite warnings; more than N warnings per piece escalates to a block.

## Owner-gold canon list
Owner verdicts (flagged lines) are gold: store normalized forms plus their own exemplar embeddings. Catch = normalized containment either direction with >= 3 words, or centered kNN above the canon threshold. Canon hits bypass the stylometric veto AND the class threshold and are labeled `src:canon` in output. Calibration check before arming: measure every canon line's self-similarity; if any line self-matches INTO the corpus background band, fall back to exact-form matching only for that line (an LOO-style verification). Fixtures must contain canon lines in split sentence-pair form and mid-sentence form, plus benign fillers — expect all canon forms to hard-fail and all fillers to pass.

## Growth loop numbers
- Diffs label removed/materially-changed sentences (tell if the guard hits them, clean for passing replacements), deduped on (class, sentence-hash, verdict, src).
- Auto-recalibrate when >= 5 new label rows accumulate behind the persisted cursor.
- At 20+ labels per class, train a logistic head over raw embeddings; ship at F0.5 >= 0.70 on held-out rows, otherwise keep the calibrated kNN layer.

## Invariants battery (every calibration change)
1. Author-corpus sweep (3+ real files): zero errors.
2. Catch fixture with all canon lines present: expected hard-fail count in the expected classes.
3. Canon fixture (canon lines in split-pair and mid-sentence positions, benign fillers) hard-fails canon lines only.
4. Owner-approved clean drafts: zero errors. Report each number; never ship a calibration change that regresses either invariant.
