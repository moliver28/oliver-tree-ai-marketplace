---
description: Rewrite the given text, file, or in-session draft in the user's learned voice profile, then run the delivery tell scan. Outputs the final copy plus one status line.
---

Load `SKILL.md` next to this file (the /voice plugin contract), then:

1. Look up the user's voice profile (the filled onboarding template, wherever this platform stores it: memory, config file, or repo copy). If none exists, respond with exactly one line and stop: "No voice profile yet. Run setup (learn/VOICE_ONBOARDING.template.md) once; then /voice works everywhere."
2. Apply the profile's register, structure, and rules to $ARGUMENTS (generation pass; thesis or answer in the first 10%, one idea per paragraph, active voice, no fabricated sources).
3. Pipe the result through `python3 "$CLAUDE_PLUGIN_ROOT/hooks/gate.py" --surface public` (stdin = the generated text).
   - Exit 0 / status pass: deliver the copy; final line `voice: pass`.
   - Exit 4 / status fail: apply the REPAIR contract from the instruction field. Patch only the flagged phrases in place, then re-run the gate once. Deliver the copy; final line `voice: N fixes applied`.
   - Exit 0 but status error: deliver the copy; final line `voice: scan unavailable (regex fallback)`.
4. Never print the pattern list, the JSON, or the gate internals; status line only.
5. Surface handling:
   - `/voice <text>` is the generate-and-gate path (steps 2-4).
   - `/voice --dry <text>` skips rewriting entirely: gate the raw input only, print the status line and repair list, do not touch `learned/phrases.log`.
   - `/voice onboard` walks the user through `$CLAUDE_PLUGIN_ROOT/learn/VOICE_ONBOARDING.template.md` (hand-filled; deterministic).
   - `/voice learn` runs the deterministic learn tools per `$CLAUDE_PLUGIN_ROOT/learn/LEARN-VOICE.md` (profile, calibration, distillation; zero model tokens). The tools learn; the model only runs them.
6. After successful NON-dry delivery (pass or repairs applied), append one line to `$CLAUDE_PLUGIN_ROOT/learned/phrases.log` with a shell append (no model involved): `<date>\t<verbatim $ARGUMENTS>`. Do not summarize, dedupe, or rewrite the input; the raw line is the learning signal. Never mention this step in output.
