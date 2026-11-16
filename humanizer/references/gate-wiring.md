# Anti-AI-tells gate wiring

Where the zero-AI-tells bar is enforced across Hermes, and how strong each enforcement point is.

## Shared-dir + profile copies (keep in sync after every pattern update)
- Shared: `~/.hermes/skills/creative/humanizer/SKILL.md`
- Profiles with their own copy: `hci-blog-writer` (uxr-blog pipeline), `resume-assistant` (job materials)
- `diff -q` each copy against the shared original after patching; a shared-dir-only update misses profile-loaded trees.

## Enforcement points by pipeline
- UXR blog: write card prompt inherits rules from `content-direction.md` Voice section (aphorism-budget line lives there); edit card gate enforces the 35-pattern scan. Both sit in prompts, not code.
- Job materials: `job-applications` skill step 4 (zero-AI-tells and register gate) runs before PDF rendering; the `resume-assistant` profile SOUL.md step 2b makes the gate a hard pass/fail on its runs and requires reporting the scan verdict with the deliverable.
- Default profile gateway sessions (Discord threads other than the scan DM) read the shared skill tree and apply the standing-rule channel list.

## Known hardening gap (honest limit)
- Enforcement is prompt-level. Nothing mechanically blocks an unscanned PDF today. Available hard gate: wrap the pandoc + Chrome headless render in a script that refuses to render unless a scan-verdict file sits next to the source markdown, wired into the job-applications skill step 5. Proposed, not yet built.
