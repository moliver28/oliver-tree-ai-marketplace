# Catalog: assessed, not mirrored yet

Skills present in the Hermes runtime, triaged against the marketplace scope (portable, end-user/work value). Copy them here when a consumer needs them.

| Item | Source tier | Assessment |
|---|---|---|
| agent-engineering: deliberation | on-request | Not mirrored; portable once the delegate_task language is generalized to "parallel subagents". Ask in chat to trigger the port; it is not scheduled on its own. |
| agent-engineering: meta-decision | (ported) | Published at engineering/meta-decision, 0.2.0, de-Hermes-ized. The original catalog row is superseded. |
| software-development: node-inspect-debugger / python-debugpy | (mirrored) | Portable as-is. |
| research: nlp-analyst | (ported) | Published at research/nlp-analyst, 0.2.0, decoupled from internal stores. |
| research: dataset-building | list | Mostly portable; internal references block contains corpus-specific recipes. |
| creative: claude-design, sketch, excalidraw, architecture-diagram | list | Generic and portable but off-marketplace-theme; include if the marketplace broadens beyond voice/work. |
| machine-learning-pro | list | Generic assistant skill, unreviewed for quality. |
| everything else (apple/*, hermes/*, messaging/*, smart-home, relationship-crm, job-applications, side-business-gtm, yuanbao, petdex, ...) | exclude | Personal, machine-specific, or Hermes-runtime machinery; out of marketplace scope. |

## Excluded by scope decision (2026-11-16)

Daneel persona assets (persona voice rules, style-enforcement plugin) are private-assistant machinery and stay in the Hermes runtime only.

## Provenance pull (2026-11-16)

Published skills must originate with us. DROPPED (owner decision 2026-11-16, not rewritten): plan, spike (gsd-build), systematic-debugging, test-driven-development, requesting-code-review (obra/superpowers), the humanizer 35-pattern SKILL.md mirror (blader). Provenance law: community derivatives are dropped by default; rewrite only on explicit owner approval. Details: PROVENANCE.md; issue #1 closed.
Added ports (ours, de-personalized): engineering/meta-decision, research/nlp-analyst, business/side-business-gtm, hobby/media-taste-algo (loop-level port; engine code stays private, boundary documented in the skill).
