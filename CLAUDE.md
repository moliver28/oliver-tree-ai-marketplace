# CLAUDE.md / any-AI-tool entry point

Before doing anything, read `README.md` (the asset index) and, if the user has not completed one yet, walk them through `onboarding/VOICE_ONBOARDING.template.md` first. A filled onboarding profile is a prerequisite for prose work.

If your task is to MODIFY this repository (add or change plugins, skills, hooks, manifests, indexes), read `MAINTENANCE.md` FIRST: it is the official change procedure, and `python3 scripts/verify.py` must exit 0 before any change can commit (pre-commit hook + CI enforce this).

Before writing prose that will carry Michael Oliver's name:
1. Read `voice/voice-michael-oliver/voice-spec-ssot.txt` (authoritative voice spec) for register, structure, and validation gates.
2. Read `humanizer/SKILL.md` for the /voice surface and `voice-gate/voice-tells.py` for the delivery scan; the profile's hard rules plus the aphorism budget gate before delivering.
3. Em dash (U+2014) is banned everywhere in output.
