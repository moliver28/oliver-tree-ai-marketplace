---
description: Run the install experience: measure the machine, pick the measurement level against the user's delay budget, learn the voice per situation, and report in plain words. Deterministic; never gates.
---

Deterministic pointer, like `/voice learn`. No rewriting, no model work.

1. Run the setup program and print its plain-words report verbatim:

   ```
   python3 "$CLAUDE_PLUGIN_ROOT/learn/voice_setup.py" <samples-root>
   ```

   `<samples-root>` is optional on a re-run. It is a directory with one subdirectory per situation: `blog/`, `linkedin/`, `report/` (ruling D5b). Each situation learns its own band from 3 or more documents of 500 or more words; a smaller situation falls back to the pooled band and the report says so. Sample documents stay user-local under `VOICE_LEARNED_DIR`; nothing is copied into the repository.

2. Flags:
   - `--remeasure` re-runs the machine bench (interpreter spawn, the gate command at a fixed 2,000-word fixture, the battery at 500 / 2,000 / 5,000 words). Without it, the measured numbers in `learned/state/machine-bench.json` are reused.
   - `--level N` (0 to 3) forces a level; without it the picker chooses the highest level whose measured cost fits `--budget` (default 1000 ms; choices 100 / 300 / 500 / 1000). If a forced level measures over budget, the report says so. Level 0 (the gate fast core) is always on; the gate path always targets the 100 ms perception threshold.
   - Exit codes: 0 = setup ran; 2 = bad usage (missing path, level outside 0 to 3, budget not one of the choices).

3. What the user gets: the machine's measured numbers, the chosen level and why, the situations learned with their document counts, and any fallback notes. The report reads for itself; add at most one sentence of context.

4. After setup: `/voice-fit <file>` reads the chosen level and, with `--situation <name>`, applies the learned layer-2 factors (pooled base + situation factor) to the tone and register rows. The setup writes files only; it never touches gate output (token law and hook contract unchanged).
