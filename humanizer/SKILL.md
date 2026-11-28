---
name: humanizer-voice
description: "Applies the user's learned voice profile to public-facing copy via the /voice command, with a quiet tell gate. Use when the user says: '/voice polish this post', 'make this sound like me', 'humanize this before it ships', 'learn my voice from these samples'."
version: 1.4.0
author: Michael Oliver (moliver28)
license: MIT
---

# /voice plugin (canonical)

Quiet-background writing profile system. Three stages, only one of which the user ever sees. The inference boundary: the ONLY place a language model runs is the `/voice` rewrite itself; learning, calibration, and the gate are deterministic scripts that spend zero model tokens.

1. **Learn (quiet, zero-LLM).** Walk the user through `learn/VOICE_ONBOARDING.template.md` once (hand-filled; the model asks and records, never answers). Optionally prefill sections 2/3/5 deterministically: `python3 $CLAUDE_PLUGIN_ROOT/learn/build_voice_profile.py <sample files or dirs>` (prints the draft, writes `learned/profile.json`). Then calibrate the gate to the user's clean writing: `python3 $CLAUDE_PLUGIN_ROOT/learn/calibrate.py --corpus <clean writing dir>` (writes `learned/calibration.json`; flagged patterns print "decide by hand"). The full procedure lives in `learn/LEARN-VOICE.md`. The filled profile lives wherever the platform stores config (memory, `~/.voice-profile.md`, or the platform equivalent). Nothing ships to the user during learning beyond the onboarding questions.
2. **Hook setup (quiet).** If the platform supports pre-delivery hooks, point them at `python3 $CLAUDE_PLUGIN_ROOT/hooks/gate.py --surface chat|public` (self-contained: the scanner is `hooks/voice_tells.py` beside it; chat = STE layer, public = tell scan + STE; pass = zero tokens, fail = one patch-in-place repair contract, scan error = fail-open). Surface lists come from the user's learned profile, never from hard-coded paths (see `hooks/HOOKS.md`). If hooks are not available, the `/voice` command carries the scan inline. No regular output mentions the gate; it fires in logs only.
3. **Apply (user-facing, minimal).** The user (or the tool's command surface) invokes:

```
/voice <target>
```

where `<target>` is the text, file, or draft slot to process. Behavior:

- Load the learned profile (error once, with the onboarding pointer, if none exists).
- SOURCE-CONTEXT-ONLY RULE (ASD-STE100 discipline applied to fidelity): the rewrite may use ONLY (a) the user's onboarding profile (voice, channels, bans) and (b) the facts present in the provided text or attachments. Never add facts, statistics, examples, metaphors, or emphasis from internal priors. If a passage needs context the profile and source do not carry, write it plainly and mark `[note: needs source]`; never invent.
- Rewrite the target in that profile's register and structure within the source boundary (generation pass; the one model stage).
- Run the delivery gate: `python3 $CLAUDE_PLUGIN_ROOT/hooks/gate.py --surface public` (stdin = the generated text). When the source text exists as a file or saved draft, add `--source <original file>`: the gate then reports source fidelity (source-context-only rule, mechanical; costs zero tokens; the source embedding is disk-cached so a repeated run on the same draft does not re-embed it).
- Return final copy plus a one-line gate status: `voice: pass` / `voice: pass (fidelity 0.91)` (when `--source` produced a fidelity number from the gate JSON) / `voice: 2 fixes applied` / `voice: 2 fixes applied (voice-fit 0.72)` (when the gate JSON carried voice_fit). One line, the numbers come straight from the gate's JSON, never narrate the pattern list.

## Voice-correction authority (2026-11-22)

The Hermes humanizer skill (35 patterns plus the pattern-35 aphorism budget) is the master source for what counts as an AI tell. The `hooks/voice_tells.py` pattern list is the mechanical mirror of that authority: every regexable humanizer family is implemented there, tagged `humanizer N` (issue #145 outcome, wave H-C 2026-11-27: family 35 aphorism density is now also enforced mechanically by the budget counter in `learn/voice_battery_core.py` (the gate's fail line names the section and the count against the skill's own budget); family 11 synonym cycling has a chunk-grain advisory signal (`voice_tells.cycling_signals`, advisory until the owner calibrates its bands in the state file; a measured sentence-grain variant stayed out, 166 to 961 ms at 500 to 5,000 words against the 100 ms gate cap); the skill-side execution during the `/voice` rewrite pass stays the master enforcement for both). Pattern families not in a numbered humanizer pattern (the Michael-voice hard bans: em dash, corporate speak, "It's not X. It's Y.", throat-clearing) are also in the pattern list. When a new tell is added to the humanizer skill, add a matching regex here in the same pass, or a comment noting the family is skill-side only.

Standing voice rules and anti-patterns adapt at scan time through the env-configured rules layer: point `DANEEL_RULES_YAML` at a named-regex YAML (schema: `pattern`, `severity`, optional `fix`, `message`, `allowlist`, same as the daneel style rules file) and every rule there rides on every gate scan. Compile semantics mirror the daneel lint engine's `make_flexible`, so one YAML drives both systems. Unset keeps the de-personalized default; the layer is purely additive and fail-open.

Profiles: `--surface public|chat` picks the tell set; `--profile resume` applies the humanizer skill's ATS condition profile (labeled section lines and Title Case headings exempt; all other prose rules in force). Default: `public`, full scan, no exemptions.

## Surface contract

- The plugin never asks the user to fill things in twice; learning happens once at setup.
- Default output is the copy, not commentary. Status line last, one line.
- If no profile exists yet, `/voice <text>` responds with a single line: "No voice profile yet. Run setup (learn/VOICE_ONBOARDING.template.md) once; then /voice works everywhere."
- `/voice --dry` runs the gate only: no rewrite, no profile work, no learning log write. Pipe the raw `--dry` text through `python3 $CLAUDE_PLUGIN_ROOT/hooks/gate.py --surface public`, then respond with the one-line status and (on fail) the repair list, so the author can edit by hand.
- `/voice learn` and `/voice onboard` are deterministic pointers, not model work: run the learn tools from `learn/` per `learn/LEARN-VOICE.md` (onboard = the template walkthrough; learn = profile, calibration, distillation, centroid + classifier build). The tools learn; the model only runs them and reports one line.
- `/voice fit <file>` is a deterministic pointer too: run `python3 $CLAUDE_PLUGIN_ROOT/learn/voice_fit.py <file>` (add `--samples <dir>` when the client sample directory is at hand) and print the advisory voice-fit table verbatim: surface stats plus Burrows' Delta, sample column vs candidate column, lower = closer, with the length confidence note. The table advises; it never gates, never rewrites, and never enters the delivery gate's blocking path.
- `/voice-fit <file>` prints the on-demand gestalt report of the 85-row battery (79 per-text spec rows plus the 3 corpus rows and the 3 detection-method rows: MMD two-sample, the two variability rows, and the wave H-C rows L10-18/19/20) (`learn/voice_battery_report.py`; add `--samples <dir>` for the character 3-gram row): one block per level with inside / near the edge / outside counts, one edit-class sentence per row, the overall band, and the length confidence note. Bands come from the user's own profile only (no public norms). Human-only surface, advisory only: it never gates, never rewrites, and the model never receives the report.
- `/voice-setup <samples-root>` runs the install experience (`learn/voice_setup.py`; re-runnable with `--remeasure` and `--level N`): measure the machine, pick the measurement level against the user's delay budget (the gate fast core is always on and targets the 100 ms perception threshold), learn the voice per situation (blog, linkedin, report; 3 or more documents of 500 or more words each, otherwise the pooled band applies), and print the plain-words report. State lands in `learned/state/` (machine bench, chosen level, per-situation bands with layer-2 factors), user-local only. Deterministic pointer like `/voice learn`; it writes files and never touches gate output.
- `/voice learn-edit <edited-file> <delivered-original>` teaches the plugin from a hand edit of a delivered copy: run `python3 $CLAUDE_PLUGIN_ROOT/learn/edit_learning.py <edited-file> <delivered-original>` and print its one-line result verbatim (`learned: substantial edit (34% changed) -> classifier retrain pending` / `learned: light edit (6% changed) -> corpus updated` / `no matching delivery recorded; nothing learned`). Nothing else on the surface.
- After successful NON-dry delivery, append one line to `$CLAUDE_PLUGIN_ROOT/learned/phrases.log` (shell append, no model): `<date>\t<verbatim request>`, and one line to `$CLAUDE_PLUGIN_ROOT/learned/deliveries.log` (shell append + sha256 of the delivered copy, no model): `<date>\t<sha256(delivered)>\t<target>`; the second log is what `/voice learn-edit` matches against later.
- Ambiguous rule conflict (a ban and an allowance both apply, or learned rules contradict): print "decide by hand" and stop. Never auto-ask a model to arbitrate; the user resolves it in the profile or the state file.
