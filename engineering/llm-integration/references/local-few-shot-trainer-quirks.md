# Local few-shot trainer quirks (SetFit / sentence-transformers on an OpenAI-compatible local stack)

Verified patterns from training SetFit classifiers in a sidecar venv against
LM Studio-served corpora. Read before writing any training script.

## Install (sidecar venv, offline training)
- `uv venv ~/.hermes/venvs/<name> --python 3.11; uv pip install --python ~/.hermes/venvs/<name>/bin/python setfit` lands setfit + torch quickly (~1-2 min). Training runs fully local after the base model downloads once from HF.
- Pin everything per deterministic-engineering: SEED, MODEL_ID constant in the script, and train/eval separated into two scripts so eval re-runs WITHOUT retraining (a 4-6 min training step must not rerun to fix a JSON bug).

## SetFit 1.2 API facts (checked against the installed signature, not docs memory)
- `TrainingArguments` exposes `body_learning_rate` and `head_learning_rate`; there is NO `learning_rate` kwarg (TypeError otherwise).
- `model.predict()` returns model-dependent objects (tensors on this stack): cast with `int(p)` / `float(p)` before `json.dump`, or the whole eval crashes AFTER training completes. Save the model with `save_pretrained` BEFORE the eval block.
- `model.predict_proba(texts)` gives calibrated-ish per-class floats; prefer it over argmax labels whenever a policy threshold must be chosen: report a THRESHOLD TABLE (positive rate at 0.5/0.6/0.7/0.8/0.9) instead of one cut, so the fire rate is a policy decision a human makes from data.

## Few-shot behavior (about 30 human labels)
- With unbalanced or rubric-shifted labels, SetFit over-fires on generic declaratives: messages like bare status updates and arrival chatter predicted as restart-worthy. Fix is DATA, not params: mine deterministic hard negatives from the corpus (links-only messages, bare reactions <= 45 chars keyed on a fill-marker regex, im-in/brb forms) and retrain. Tighten the regex to WHOLE-message short reactions; a prefix match catches takes that merely start with 'True'.
- Compare scorers under the SAME pinned sample + seed; report full-pool vs held-out slices separately (an in-sample accuracy number is decorative).
- Evaluate against the OWNERS rubric when the weak-label recipe and a human disagree at scale: a systematic disagreement is a ground-truth correction, not label noise. Keep the ambiguous (X) rows OUT of training but IN the eval file as boundary probes.

## Two-attempt web rule (standing owner rule for any script debugging)
On the second failed attempt at the same problem (same command, same fix failing twice), stop trial-and-error and web_search the error or method first; two attempts maximum before research. Write this rule into the BRIEF of any subagent or cron step that runs scripts, because children do not inherit conversational habits.