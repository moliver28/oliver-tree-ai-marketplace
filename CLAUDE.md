# CLAUDE.md / any-AI-tool entry point

Before doing anything, read `README.md` (the asset index) and, if the user has not completed one yet, walk them through `humanizer/learn/VOICE_ONBOARDING.template.md` first. A filled onboarding profile is a prerequisite for prose work.

If your task is to MODIFY this repository (add or change plugins, skills, hooks, manifests, indexes), read `MAINTENANCE.md` FIRST: it is the official change procedure, and `python3 scripts/verify.py` must exit 0 before any change can commit (pre-commit hook + CI enforce this).

Before writing prose that will carry the user's name:
1. Load the user's learned profile first (the filled `humanizer/learn/VOICE_ONBOARDING.template.md`): register, structure, and validation gates come from it, not from priors.
2. Run the delivery gate before anything reaches another human: `humanizer/hooks/gate.py --surface public` (the scan is deterministic; the procedure is `humanizer/learn/LEARN-VOICE.md`). Profile plus the aphorism budget gate the pass.
3. Em dash (U+2014) is banned everywhere in output.
