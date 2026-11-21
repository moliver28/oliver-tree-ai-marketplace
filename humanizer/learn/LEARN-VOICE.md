# LEARN-VOICE: the zero-LLM learning procedure

How the humanizer plugin learns a user's voice and enforces it. Every stage
here is deterministic code: no model is prompted, no tokens are spent, and no
output is inferred. The ONLY stage in the whole plugin where a language model
runs is the `/voice` rewrite itself (the generation pass). Learning, scanning,
calibrating, and distilling are scripts.

The machine register lives in code: `hooks/voice_tells.py` holds the pattern
list (each entry: one regex, one label) and the tell exemplars. There is no
separate register document to keep in sync; read the pattern list in that file
to see exactly what the gate enforces. Users extend or override rules as DATA
in the runtime state file (`<HERMES_HOME>/state/voice-rules.json`), never by
editing the shipped code.

## Stage 1: Install

Install the plugin (`claude plugin install humanizer-voice@oliver-tree-ai-marketplace`
or point any agent CLI at this repo). Zero tokens: installation is file copying;
nothing runs at install time except the host's own plugin loader.

## Stage 2: Onboard (hand-fill, no model)

1. Copy `humanizer/learn/VOICE_ONBOARDING.template.md` and walk through it with
   the user. The host tool asks the questions and records the answers; it does
   not generate answers for the user.
2. Optional deterministic prefill: run
   `python3 humanizer/learn/build_voice_profile.py <sample files or dirs>`
   over 3 or more of the user's real .md/.txt samples. The tool prints a draft
   of template sections 2 (voice DNA), 3 (reader), and 5 (hard rules) computed
   from the samples and writes `learned/profile.json` (sentence-length
   distribution, paragraph shape, punctuation frequencies, top content
   n-grams, opener histogram, passive and intensifier density, per-pattern hit
   rates against the gate patterns). The user confirms or corrects every line;
   the draft is an input to the hand-fill, never a replacement for it.
3. The filled profile is stored wherever the platform keeps config (memory,
   `~/.voice-profile.md`, or the platform equivalent). Zero tokens: this stage
   is a questionnaire plus two shell commands.

## Stage 3: Initial learn

1. `python3 humanizer/learn/calibrate.py <corpus dir> [--deliveries DIR]`
   over a directory of the user's real clean writing. The tool runs the
   `voice_tells.py` regex layer over the corpus and writes
   `learned/calibration.json` (per-pattern hit rates, deviation flags). A
   pattern that fires on clean prose is a candidate personalization: the user
   decides whether to ban it, allow it, or add a state-file override.
2. Optional vector layer: `python3 humanizer/learn/voice_vector_build.py
   --backend ollama` (or `--backend onnx`) embeds the effective exemplars and
   writes `learned/voice-tells-vectors.json` plus
   `learned/voice-tells-calibration.json`. Without these files the vector
   layer skips itself and the regex layer stands; with them, paraphrase-level
   tells are caught as well. This step needs a local embedder (Ollama or the
   ONNX fallback); it never calls a hosted model.
3. Optional phrase distillation: after `/voice` has logged real requests, run
   `python3 humanizer/learn/distill_phrases.py` to fold recurring phrasings
   from `learned/phrases.log` into `learned/rules.json`. Zero tokens: all
   frequency counting is string arithmetic.

## Stage 4: Enforce

- The delivery gate `hooks/gate.py` runs on every generated surface: pass =
  zero tokens delivered (the model is never re-engaged); fail = one repair
  contract naming at most 5 family-deduped patterns with patch-in-place
  instructions; scan error = fail-open (deliver).
- `/voice` applies the profile and gates the result. `/voice --dry` gates the
  raw text only. Nothing in the gate loop calls a model.

## Stage 5: Continuous learn

- `/voice` appends one line per successful run to `learned/phrases.log`
  (`<date>\t<verbatim request>`); a shell append, not a model call.
- Periodically (or during a maintenance pass), rerun `learn/calibrate.py` on
  new clean writing, `learn/distill_phrases.py` on the grown log, and
  `learn/voice_vector_build.py` after any exemplar or state-file change.
- Rule edits from learned data go into the runtime state file
  (`voice-rules.json`) as DATA with per-source provenance; the gate picks them
  up at scan time without a restart.

## Conflict rule (no model arbitration)

When two learned rules conflict, or a rule is ambiguous on a given sentence
(both a ban and an allowance could apply), the plugin prints one line: "decide
by hand". It NEVER silently picks a winner and NEVER sends the conflict to a
model for arbitration. The user resolves conflicts by editing the profile or
the state file; the gate keeps enforcing the deterministic union until they do.

## LinkedIn post pipeline (optional module)

`learn/linkedin/` carries the LinkedIn rendering + checking stack
(`linkedin_render.py`, `linkedin_voicebook_check.py`, `linkedin_lever_check.py`,
`templates/`, `tests/linkedin/run_linkedin_battery.py`). See
`learn/linkedin/README.md` for the derivation procedure. The verification
battery is deterministic and runnable by hand:

```
python3 humanizer/learn/linkedin/tests/linkedin/run_linkedin_battery.py
```

Exit 0 = every gate cell green against the committed goldens. It is not wired
into `scripts/verify.py`; run it when touching the linkedin module.
