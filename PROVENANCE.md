# Provenance

Published assets in this repo must originate with us (moliver28 / Hermes Agent / collaborators), not be slightly modified community tools. Every asset carries an origin row. Community-derived items are removed from the mirror and dropped, not rewritten, unless the owner approves a rewrite in chat (decision 2026-11-16: all six dropped, issue #1 closed).

## Origin table (verified 2026-11-16 by header grep)

| Asset | Origin | Status |
|---|---|---|
| voice/voice-michael-oliver | Michael Oliver, built here from his Notion voice spec | ours, published |
| onboarding/ | built here | ours, published |
| voice-gate | Michael + Hermes Agent, built here (regex + vector gate) | ours, published |
| humanizer (the /voice plugin) | Michael + Hermes Agent, built here | ours, published |
| writing/linkedin-style-learner | Michael Oliver, built here | ours, published |
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
| uxr-plugin (port) | Michael Oliver + ZCode agent (zcode), built in zcode runtime, ported 2026-11-17 | APPROVED, NOT PUBLISHED — security-gate triage pending owner decision 2026-11-17 (see catalog.md row; two remediation fixes sit in the feat-branch stash) |
| ~~humanizer (35-pattern SKILL mirror)~~ | Siqi Chen / blader + Wikipedia AI-signs project (MIT) | REMOVED from mirror. The tell knowledge is enforced in our own voice-gate code; a from-scratch our-own writing-scan SKILL.md is the rewrite debt, tracked in issue #1. |
| ~~engineering/plan, spike~~ | obra/superpowers, gsd-build/get-shit-done adaptations | REMOVED. Rewrite from our own methodology before publishing. |
| ~~engineering/systematic-debugging, test-driven-development, requesting-code-review~~ | obra/superpowers adaptations | REMOVED. Same. |

## Rule

Before mirroring a skill, grep its header for origin (`author`, `ported/adapted from`, upstream URL). Adapted community tooling stays in the private Hermes runtime; only skills authored here, or genuinely rewritten from scratch, publish. Credit stays in this file regardless: MIT attribution obligations for anything we learned from remain honored in place.
