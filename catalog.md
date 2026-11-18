# Catalog: assessed, not mirrored yet

Skills present in the Hermes runtime, triaged against the marketplace scope (portable, end-user/work value). Copy them here when a consumer needs them.

| Item | Source tier | Assessment |
|---|---|---|
| agent-engineering: deliberation | (ported) | Published at engineering/deliberation, 0.1.0, delegate_task language generalized to parallel subagents. Port approved in chat 2026-11-17; this row supersedes the earlier ask-in-chat note. |
| agent-engineering: prompt-engineering | (ported) | Published at engineering/prompt-engineering, 0.1.0, dangling skill references generalized to "if your agent has one". |
| agent-engineering: iit-hci-integration | (ported) | Published at engineering/iit-hci-integration, 0.1.0, runtime config paths generalized to any agent CLI. |
| research: academic | (ported) | Published at research/academic, 0.1.0, internal-workflow marker removed. |
| research: literature-review | (ported) | Published at research/literature-review, 0.1.0. |
| plugin: decision-advisor | (ported) | Published at decision-advisor/, 0.1.0; packaging of the decision bundle (agent + /decide) over engineering/meta-decision; the full-form meta-decision text lives at engineering/meta-decision/reference.md. |
| plugin: voice-gate | (ported) | Published at voice-gate/, 0.3.0. Learn/apply decoupling (issue #5) marketplace-side landed: rules load from the runtime state file at scan time (shared loading contract, fail-open unchanged) and verify.py hashes the runtime gate against this mirror; runtime side pending (Mac learner + regenerate pass). |
| plugin: uxr-plugin | (ported) | Published at uxr-plugin/, 0.1.0. Owner approval 2026-11-17; Mimosa static scan triaged with owner ruling: 6+1 FP-class findings accepted (user-supplied CSVs are the tool's purpose; the user is the machine owner), the real SSRF class fixed upstream via the https-guard in analytics_flush.py with enforced https endpoints (upstream PR #3, squash 27675ad). Staged copy = upstream main at 27675ad plus documented stage-local convention adaptations (description-law lines on 3 skills, .gitkeep placeholder content, ADF taskItem verify-allow, marketplace entry, bracketed changelog heading). Published 2026-11-18. |
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
