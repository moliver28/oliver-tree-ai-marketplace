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
| plugin: voice-gate | (ported) | Folded 2026-11-21: the generic engine (tells scanner, standalone checker, vector builder) is part of humanizer 1.0.0 (humanizer/hooks/, humanizer/learn/); the separate plugin entry is gone from marketplace.json and the personal artifacts are archived private. Supersedes the 0.3.0 row. |
| plugin: uxr-plugin | (ported) | Published at uxr-plugin/, 0.3.0. Owner approval 2026-11-17; Mimosa static scan triaged with owner ruling: 6+1 FP-class findings accepted (user-supplied CSVs are the tool's purpose; the user is the machine owner), the real SSRF class fixed upstream via the https-guard in analytics_flush.py with enforced https endpoints (upstream PR #3, squash 27675ad). Staged copy = upstream main at 27675ad plus documented stage-local convention adaptations (description-law lines on 3 skills, .gitkeep placeholder content, ADF taskItem verify-allow, marketplace entry, bracketed changelog heading). Published 2026-11-18 (PR #118). Updated to 0.3.0 2026-11-21: efficiency pass — install payload −5,783 lines, one interpreter spawn per hook event, QA tree relocated to repo-level tests/, stdout discipline, verbatim-capture tightening, optional-step disclosure. Updated to 0.5.0 2026-11-22: source-registry content wave — the grounding law + 109-row condition index, 161 one-file-per-entry sources, pointer lines on every command and skill surface, the web-tool nudge hook, and the gate citation check; content authored here from the orchestrator's verified research notes (origin unchanged). Updated to 0.7.0 2026-11-24: optional MCP server (Phase 1 + rounds 2-4) at uxr-plugin/mcp-server/ -- ten curated tools over newline-delimited JSON-RPC (dual-era protocol, stdlib only, no lib imports, no send tool), schemas/docs derived from per-script MCP_SURFACE tables (docs generator drift check), an install/uninstall/status command for zcode, codex, and claude-code configs, the universal ~/uxr-workspaces default root, and an OAuth 2.1 HTTP bridge for app hosts like Gemini Connected Apps. | Updated to 0.8.0 2026-11-24: backend parity wave P1 — the GitHub Issues adapter ships (`lib/adapter_github.py` + `references/tracker-github.md`); the registry entry flips to built; origin unchanged. Updated to 0.8.0 2026-11-24: backend parity wave P2 — the GitLab Issues adapter ships (`lib/adapter_gitlab.py` + `references/tracker-gitlab.md`); the shipped kind joins the registry and config as built; origin unchanged. |
| voice system (personal spec + register + linkedin learner) | (private) | De-personalization ruling 2026-11-21: the owner's personal voice spec, the zero-ai-tells register, the exemplar vectors/calibration, the runtime hook adapter with personal surfaces, and the real article briefs left the public mirror (canonical private). The generic engine ships inside humanizer 1.0.0: learn tools (humanizer/learn/), delivery gate (humanizer/hooks/), and the de-personalized LinkedIn pipeline (humanizer/learn/linkedin/). |
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

## De-personalization (2026-11-21)

Removed from the public mirror by owner directive: the personal voice skill, the zero-ai-tells register, the packaged exemplar vectors + calibration, the runtime hook adapter with personal surfaces, and the real article briefs. The voice-gate plugin and the linkedin-style-learner skill were folded into humanizer 1.0.0 in generic form. Details: PROVENANCE.md; the enforcement is the forbidden-token scan in scripts/verify.py.
