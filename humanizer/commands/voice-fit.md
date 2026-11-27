---
description: Print the on-demand voice-fit gestalt report for a file (79-measure battery, one band per level, overall band, edit classes). Advisory and human-only; never gates.
---

Deterministic pointer, like `/voice learn` and `/voice fit`. No rewriting, no model work.

1. Run the tool and print its report verbatim:

   ```
   python3 "$CLAUDE_PLUGIN_ROOT/learn/voice_battery_report.py" <file>
   ```

   Add `--samples <dir>` when the client sample directory is at hand; it adds the pooled character 3-gram rows for the L11-8 distance row. Without a built profile the report still prints (exit 0): the candidate values appear without bands under a defined note.

2. The report reads the candidate against the learned profile's battery section (`learned/profile.json`, built by `learn/build_voice_profile.py`). One block per level L1 to L11: the measures with a reading, the inside / near the edge / outside counts, and the level band. Each row names the observed value, the reference band with the seen range, the verdict, and one edit sentence (edit class: sentence length, word choice, punctuation, structure, links, tone, machine patterns, no edit). Rows outside the band print first. The last two lines give the overall band and the length confidence note (suppressed measures listed by name; the rank false alarm 1/(k+1) stated).

3. Say one line of context at most; the report speaks for itself. Read the overall band and the first rows aloud if the user asks for a summary; never paste a decimal fit score (the report has none by design).

4. Advisory only: this command never gates, never rewrites, never enters the delivery gate, and never sends the report to the model (token law: the report is a human-only surface).
