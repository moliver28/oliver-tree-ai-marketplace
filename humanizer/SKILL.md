---
name: humanizer-voice
description: "Applies the user's learned voice profile to public-facing copy via the /voice command, with a quiet tell gate. Use when the user says: '/voice polish this post', 'make this sound like me', 'humanize this before it ships', 'learn my voice from these samples'."
version: 1.0.0
author: Michael Oliver (moliver28)
license: MIT
---

# /voice plugin (canonical)

Quiet-background writing profile system. Three stages, only one of which the user ever sees. The inference boundary: the ONLY place a language model runs is the `/voice` rewrite itself; learning, calibration, and the gate are deterministic scripts that spend zero model tokens.

1. **Learn (quiet, zero-LLM).** Walk the user through `learn/VOICE_ONBOARDING.template.md` once (hand-filled; the model asks and records, never answers). Optionally prefill sections 2/3/5 deterministically: `python3 $CLAUDE_PLUGIN_ROOT/learn/build_voice_profile.py <sample files or dirs>` (prints the draft, writes `learned/profile.json`). Then calibrate the gate to the user's clean writing: `python3 $CLAUDE_PLUGIN_ROOT/learn/calibrate.py <corpus dir>` (writes `learned/calibration.json`; flagged patterns print "decide by hand"). The full procedure lives in `learn/LEARN-VOICE.md`. The filled profile lives wherever the platform stores config (memory, `~/.voice-profile.md`, or the platform equivalent). Nothing ships to the user during learning beyond the onboarding questions.
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

## Surface contract

- The plugin never asks the user to fill things in twice; learning happens once at setup.
- Default output is the copy, not commentary. Status line last, one line.
- If no profile exists yet, `/voice <text>` responds with a single line: "No voice profile yet. Run setup (learn/VOICE_ONBOARDING.template.md) once; then /voice works everywhere."
- `/voice --dry` runs the gate only: no rewrite, no profile work, no learning log write. Pipe the raw `--dry` text through `python3 $CLAUDE_PLUGIN_ROOT/hooks/gate.py --surface public`, then respond with the one-line status and (on fail) the repair list, so the author can edit by hand.
- `/voice learn` and `/voice onboard` are deterministic pointers, not model work: run the learn tools from `learn/` per `learn/LEARN-VOICE.md` (onboard = the template walkthrough; learn = profile, calibration, distillation, centroid + classifier build). The tools learn; the model only runs them and reports one line.
- `/voice fit <file>` is a deterministic pointer too: run `python3 $CLAUDE_PLUGIN_ROOT/learn/voice_fit.py <file>` (add `--samples <dir>` when the client sample directory is at hand) and print the advisory voice-fit table verbatim: surface stats plus Burrows' Delta, sample column vs candidate column, lower = closer, with the length confidence note. The table advises; it never gates, never rewrites, and never enters the delivery gate's blocking path.
- `/voice-fit <file>` prints the on-demand gestalt report of the 79-measure battery (`learn/voice_battery_report.py`; add `--samples <dir>` for the character 3-gram row): one block per level with inside / near the edge / outside counts, one edit-class sentence per row, the overall band, and the length confidence note. Bands come from the user's own profile only (no public norms). Human-only surface, advisory only: it never gates, never rewrites, and the model never receives the report.
- `/voice-setup <samples-root>` runs the install experience (`learn/voice_setup.py`; re-runnable with `--remeasure` and `--level N`): measure the machine, pick the measurement level against the user's delay budget (the gate fast core is always on and targets the 100 ms perception threshold), learn the voice per situation (blog, linkedin, report; 3 or more documents of 500 or more words each, otherwise the pooled band applies), and print the plain-words report. State lands in `learned/state/` (machine bench, chosen level, per-situation bands with layer-2 factors), user-local only. Deterministic pointer like `/voice learn`; it writes files and never touches gate output.
- `/voice learn-edit <edited-file> <delivered-original>` teaches the plugin from a hand edit of a delivered copy: run `python3 $CLAUDE_PLUGIN_ROOT/learn/edit_learning.py <edited-file> <delivered-original>` and print its one-line result verbatim (`learned: substantial edit (34% changed) -> classifier retrain pending` / `learned: light edit (6% changed) -> corpus updated` / `no matching delivery recorded; nothing learned`). Nothing else on the surface.
- After successful NON-dry delivery, append one line to `$CLAUDE_PLUGIN_ROOT/learned/phrases.log` (shell append, no model): `<date>\t<verbatim request>`, and one line to `$CLAUDE_PLUGIN_ROOT/learned/deliveries.log` (shell append + sha256 of the delivered copy, no model): `<date>\t<sha256(delivered)>\t<target>`; the second log is what `/voice learn-edit` matches against later.
- Ambiguous rule conflict (a ban and an allowance both apply, or learned rules contradict): print "decide by hand" and stop. Never auto-ask a model to arbitrate; the user resolves it in the profile or the state file.
