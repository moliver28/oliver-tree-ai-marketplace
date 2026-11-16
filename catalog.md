# Catalog: assessed, not mirrored yet

Skills present in the Hermes runtime, triaged against the marketplace scope (portable, end-user/work value). Copy them here when a consumer needs them.

| Item | Source tier | Assessment |
|---|---|---|
| agent-engineering: deliberation | move-port | Portable once delegate_task language is generalized to "parallel subagents". |
| agent-engineering: meta-decision | move-port | Strong generic framework; needs the same delegation-wording pass plus trimming Hermes wiring (skill_manage, cronjob, SOUL.md). |
| software-development: node-inspect-debugger / python-debugpy | (mirrored) | Portable as-is. |
| research: nlp-analyst | list | Depends on internal corpus-kb and cx-feedback-dataset; portable only after decoupling the local-corpus step. |
| research: dataset-building | list | Mostly portable; internal references block contains corpus-specific recipes. |
| creative: claude-design, sketch, excalidraw, architecture-diagram | list | Generic and portable but off-marketplace-theme; include if the marketplace broadens beyond voice/work. |
| machine-learning-pro | list | Generic assistant skill, unreviewed for quality. |
| everything else (apple/*, hermes/*, messaging/*, smart-home, relationship-crm, job-applications, side-business-gtm, yuanbao, petdex, ...) | exclude | Personal, machine-specific, or Hermes-runtime machinery; out of marketplace scope. |

## Excluded by scope decision (2026-11-16)

Daneel persona assets (persona voice rules, style-enforcement plugin) are private-assistant machinery and stay in the Hermes runtime only.
