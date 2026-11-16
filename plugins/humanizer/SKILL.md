---
name: humanizer-voice
description: "Applies the user's learned voice profile to public-facing copy via the /voice command, with a quiet tell gate. Use when the user says: '/voice polish this post', 'make this sound like me', 'humanize this before it ships'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
---

# /voice plugin

Quiet-background writing profile system. Three stages, only one of which the user ever sees:

1. **Learn (quiet).** The hosting tool reads `onboarding/VOICE_ONBOARDING.template.md` from this repo and walks the user through it once. The filled profile (channels/situations/rules/reader) lives wherever the platform stores config (memory, `~/.voice-profile.md`, or the platform equivalent). Nothing ships to the user during learning beyond the onboarding questions.
2. **Hook setup (quiet).** If the platform supports pre-delivery hooks, register the scan-on-delivery hook (the repo's `plugins/voice-gate/` is a reference implementation: regex tell-scan, fail-open, one line on block with a rewrite instruction). If hooks are not available, the `/voice` command carries the scan inline. No regular output mentions the gate; it fires in logs only.
3. **Apply (user-facing, minimal).** The user (or the tool's command surface) invokes:

```
/voice <target>
```

where `<target>` is the text, file, or draft slot to process. Behavior:

- Load the learned profile (error once, with the onboarding pointer, if none exists).
- SOURCE-CONTEXT-ONLY RULE (ASD-STE100 discipline applied to fidelity): the rewrite may use ONLY (a) the user's onboarding profile (voice, channels, bans) and (b) the facts present in the provided text or attachments. Never add facts, statistics, examples, metaphors, or emphasis from internal priors. If a passage needs context the profile and source do not carry, write it plainly and mark `[note: needs source]`; never invent.
- Rewrite the target in that profile's register and structure within the source boundary (generation pass).
- Run the delivery gate: `python3 $CLAUDE_PLUGIN_ROOT/hooks/gate.py --surface public` (stdin = the generated text).
- Return final copy plus a one-line gate status (`voice: pass` or `voice: 2 fixes applied`). Never narrates the pattern list.

## Surface contract

- The plugin never asks the user to fill things in twice; learning happens once at setup.
- Default output is the copy, not commentary. Status line last, one line.
- If no profile exists yet, `/voice <text>` responds with a single line: "No voice profile yet. Run setup (the onboarding template) once; then /voice works everywhere."
- `/voice --dry` runs the scan only and emits the report without rewriting.
