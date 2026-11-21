---
description: Rewrite the given text, file, or in-session draft in the user's learned voice profile, then run the delivery tell scan. Outputs the final copy plus one status line.
---

Load `SKILL.md` next to this file (the /voice plugin contract), then:

1. Look up the user's voice profile (the filled onboarding template, wherever this platform stores it: memory, config file, or repo copy). If none exists, respond with exactly one line and stop: "No voice profile yet. Run setup (learn/VOICE_ONBOARDING.template.md) once; then /voice works everywhere."
2. Apply the profile's register, structure, and rules to $ARGUMENTS (generation pass; thesis or answer in the first 10%, one idea per paragraph, active voice, no fabricated sources).
3. Pipe the result through `python3 "$CLAUDE_PLUGIN_ROOT/hooks/gate.py" --surface public` (stdin = the generated text). When the source text exists as a file or saved draft, add `--source <original file>` so the gate reports source fidelity (zero tokens; the source embedding is disk-cached, hash-keyed and bounded — a repeated run on the same draft does not re-embed the source).
   - Exit 0 / status pass: deliver the copy; final line `voice: pass`, or `voice: pass (fidelity 0.91)` when the pass JSON carried `source_fidelity` (read the number from the gate's JSON output; no extra model work).
   - Exit 4 / status fail: apply the REPAIR contract from the instruction field. Patch only the flagged phrases in place, then re-run the gate once. Deliver the copy; final line `voice: N fixes applied`, or `voice: N fixes applied (voice-fit 0.72)` when the fail JSON carried `voice_fit`.
   - Exit 0 but status error: deliver the copy; final line `voice: scan unavailable (regex fallback)`.
4. Never print the pattern list, the JSON, or the gate internals; status line only. Advisory JSON fields (`voice_fit`, `source_fidelity`, `p_ai`, `voice_delta`) surface ONLY through the status line's one parenthesized number; they are informational and never change delivery in 1.1.0.
5. Surface handling:
   - `/voice <text>` is the generate-and-gate path (steps 2-4).
   - `/voice --dry <text>` skips rewriting entirely: gate the raw input only, print the status line and repair list, do not touch `learned/phrases.log`.
   - `/voice onboard` walks the user through `$CLAUDE_PLUGIN_ROOT/learn/VOICE_ONBOARDING.template.md` (hand-filled; deterministic).
   - `/voice learn` runs the deterministic learn tools per `$CLAUDE_PLUGIN_ROOT/learn/LEARN-VOICE.md` (profile, calibration, distillation, centroid + classifier build; zero model tokens). The tools learn; the model only runs them.
   - `/voice learn-edit <edited-file> <delivered-original>` (two-argument contract): when the user edited a delivered copy by hand, run `python3 "$CLAUDE_PLUGIN_ROOT/learn/edit_learning.py" <edited-file> <delivered-original>` and print its one-line result verbatim: `learned: substantial edit (34% changed) -> classifier retrain pending` (pair filed to learned/edit-delta/), `learned: light edit (6% changed) -> corpus updated` (learned/clean-corpus-index.txt gains an edit-confirmed entry), or `no matching delivery recorded; nothing learned` (the delivered original's hash was not in learned/deliveries.log). Nothing else on the surface; never mentions model tokens.
6. After successful NON-dry delivery (pass or repairs applied), append one line to `$CLAUDE_PLUGIN_ROOT/learned/phrases.log` with a shell append (no model involved): `<date>\t<verbatim $ARGUMENTS>`. Do not summarize, dedupe, or rewrite the input; the raw line is the learning signal. Also append one line to `$CLAUDE_PLUGIN_ROOT/learned/deliveries.log` (shell append + sha256 of the delivered copy, no model): `<date>\t<sha256(delivered)>\t<target>` — e.g. save the delivered copy to a temp file, then `printf '%s\t%s\t%s\n' "$(date +%F)" "$(sha256sum "$tmp" | cut -d' ' -f1)" "<target>" >> "$CLAUDE_PLUGIN_ROOT/learned/deliveries.log"`. Never mention this step in output.
