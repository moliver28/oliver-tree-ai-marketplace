# Provenance

Published assets in this repo must originate with us (moliver28 / Hermes Agent / collaborators), not be slightly modified community tools. Every asset carries an origin row. Community-derived items are removed from the mirror and dropped, not rewritten, unless the owner approves a rewrite in chat (decision 2026-11-16: all six dropped, issue #1 closed).

## Origin table (verified 2026-11-16 by header grep)

| Asset | Origin | Status |
|---|---|---|
| ~~voice/voice-michael-oliver~~ | Michael Oliver, built here from his Notion voice spec | REMOVED from public mirror 2026-11-21 (de-personalization, owner directive); canonical private |
| ~~onboarding/~~ | built here | REMOVED 2026-11-21 (de-personalization): the zero-ai-tells register is personal, archived private; the onboarding template lives on at humanizer/learn/VOICE_ONBOARDING.template.md |
| ~~voice-gate~~ | Michael + Hermes Agent, built here (regex + vector gate) | REMOVED as separate plugin 2026-11-21 — generic engine folded into humanizer 1.0.0 (hooks/voice_tells.py, hooks/voice_check.py, learn/voice_vector_build.py); personal artifacts (exemplar vectors, calibration, the runtime hook adapter with personal surfaces) archived private |
| humanizer (the /voice plugin) | Michael + Hermes Agent, built here | ours, published (canonical 1.0.0: learn/hooks/apply consolidated, zero-LLM learn tools, de-personalized 2026-11-21) |
| ~~writing/linkedin-style-learner~~ | Michael Oliver, built here | de-personalized + folded into humanizer/learn/linkedin 1.0.0 (synthetic briefs, example.org links, generic ban list); voice_guard.py + the personal canon list archived private |
| engineering/codebase-inspection, llm-integration, node-inspect-debugger, python-debugpy | Hermes Agent | ours, published |
| research/grounded-citations, document-to-action-items, meeting-action-items | Hermes Agent + collaborator | ours, published |
| engineering/meta-decision (port) | Michael Oliver + Hermes Agent | ours, published (de-Hermes-ized 0.2.0) |
| research/nlp-analyst (port) | Michael Oliver + Hermes Agent | ours, published (decoupled from internal stores, 0.2.0) |
| business/side-business-gtm (port) | Michael Oliver | ours, published (de-personalized) |
| hobby/media-taste-algo (port) | agent-authored for Michael | ours, published (de-personalized; engine code stays private, documented boundary) |
| engineering/prompt-engineering (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published |
| engineering/deliberation (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published (delegate_task language generalized to parallel subagents) |
| engineering/iit-hci-integration (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published (runtime paths generalized to any agent CLI) |
| research/academic (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published (internal-workflow marker removed) |
| research/literature-review (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published |
| engineering/meta-decision/reference.md | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published (full-form companion to the 0.2.0 SKILL.md; additive file, no version bump) |
| decision-advisor (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | ours, published (decision bundle: agent + /decide, over engineering/meta-decision) |
| uxr-plugin (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime; upstream repo moliver28/uxr-plugin, first-party original authorship, origin gate pass; upstream main 27675ad staged after the PR #3 security-triage fixes (owner ruling 2026-11-17: 6+1 FP-class findings accepted with rationale, real SSRF class fixed upstream via https-guard); stage-local convention adaptations documented in catalog.md | ours, published 2026-11-18 (0.1.0); efficiency pass to 0.3.0 landed 2026-11-21; source-registry content wave to 0.5.0 2026-11-22 — registry content authored in this repo from the orchestrator's MO-verified source notes (fetch verification recorded in the upstream notes), origin unchanged; 0.7.0 2026-11-24 adds the optional MCP server (mcp-server/, authored in this repo): dual-era protocol, derived schemas/docs, install/uninstall/status, the universal uxr-workspaces root, and the OAuth 2.1 HTTP bridge |
| ~~humanizer (35-pattern SKILL mirror)~~ | Siqi Chen / blader + Wikipedia AI-signs project (MIT) | REMOVED from mirror. The tell knowledge is enforced in our own voice-gate code; a from-scratch our-own writing-scan SKILL.md is the rewrite debt, tracked in issue #1. |
| ~~engineering/plan, spike~~ | obra/superpowers, gsd-build/get-shit-done adaptations | REMOVED. Rewrite from our own methodology before publishing. |
| ~~engineering/systematic-debugging, test-driven-development, requesting-code-review~~ | obra/superpowers adaptations | REMOVED. Same. |

## Rule

Before mirroring a skill, grep its header for origin (`author`, `ported/adapted from`, upstream URL). Adapted community tooling stays in the private Hermes runtime; only skills authored here, or genuinely rewritten from scratch, publish. Credit stays in this file regardless: MIT attribution obligations for anything we learned from remain honored in place.
