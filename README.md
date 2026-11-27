# Oliver Tree AI Marketplace

Private index of reusable system assets for pointing ANY AI tool (Claude, Codex, other Hermes profiles) at, without copy-pasting prompts each session.

## Index

| Asset | Path | Use |
|---|---|---|
| /voice plugin (canonical voice system) | `humanizer/` | Learn a voice profile with deterministic tools, rewrite copy via `/voice`, quiet tell gate on delivery; the gate also reports voice-fit to the user's clean-corpus centroid and source fidelity (`--source`, zero tokens), `/voice learn-edit` teaches the plugin from hand-edited deliveries, `/voice fit` prints the advisory stylometry table (`learn/voice_fit.py`: surface stats + Burrows' Delta vs the learned sample, parity-pinned to the sitefactory P18 block, never gates), and `/voice-setup` is the install experience (machine bench, measurement-level picker against the user's delay budget, per-situation voice learning with pooled + shrunk situation factors, plain-words report), `/voice-fit` prints the on-demand gestalt report of the 79-measure battery (`learn/voice_battery.py`: one band per level plus the overall band, each row mapped to an edit class, bands from the user's own profile; closed R0/R1 lists only, about 5.6 KB, one PROVENANCE row per list; the gate carries the battery fast core only, one marker fail line, pass line byte-identical). The owner's personal voice artifacts were removed from this mirror (de-personalization, 2026-11-21); the shipped plugin is fully generic. |
| Engineering workflows | `engineering/` | codebase-inspection, llm-integration, node/python debuggers, meta-decision, prompt-engineering, deliberation, iit-hci-integration. |
| Research workflows | `research/` | grounded-citations, document-to-action-items, meeting-action-items, nlp-analyst, academic, literature-review. |
| Prompt engineering | `engineering/prompt-engineering/` | COSTAR prompt optimization with evidence-based technique selection; explains every change it makes. |
| Deliberation | `engineering/deliberation/` | Multi-perspective stress-test: initial analysis, simulated stakeholder reactions from parallel subagents, refined conclusion. |
| IIT+HCI integration | `engineering/iit-hci-integration/` | Discovers the agent CLI's components at runtime, maps workflow gaps, wires dual-layer enforcement. |
| Academic sourcing | `research/academic/` | Parallel scholarly database search; peer-review status, evidence hierarchy, citation rigor. |
| Literature review | `research/literature-review/` | FSM-based systematic review protocol: scoping through PRISMA-style reporting. |
| Decision advisor plugin | `decision-advisor/` | `/decide` and the decision-advisor agent run the meta-decision pipeline on one-way doors; pairs with `engineering/meta-decision/`. |
| UX research operations plugin | `uxr-plugin/` | Full UXR ops: study tickets, specs, recruitment, interview scripts, reports, decks; 16 `/uxr-*` commands, 3 skills, fail-open local analytics hooks. |
| Triage of everything else | `catalog.md` | Assessed: move-port / list / exclude, with reasons. |
| Provenance ledger | `PROVENANCE.md` | Origin verification per published asset; removals and folds documented |

## Install (Claude Code)

```
claude plugin marketplace add moliver28/oliver-tree-ai-marketplace
claude plugin install humanizer-voice@oliver-tree-ai-marketplace
claude plugin install decision-advisor@oliver-tree-ai-marketplace
claude plugin install uxr-plugin@oliver-tree-ai-marketplace

Updates (run after any release note here):
```
claude plugin update humanizer-voice@oliver-tree-ai-marketplace
claude plugin update decision-advisor@oliver-tree-ai-marketplace
claude plugin update uxr-plugin@oliver-tree-ai-marketplace
```

Then one onboarding pass (`humanizer/learn/VOICE_ONBOARDING.template.md`), after which `/voice <text>` works everywhere. Consumable from any other AI tool by pointing it at `CLAUDE.md` in this repo.

## Verify

```
python3 scripts/verify.py
```

Exit 0 = manifests parse, all skills carry frontmatter, the delivery gate demonstrably fails sloppy text and passes clean text, the learn tools behave deterministically on fixture corpora, and the de-personalization token scan is clean. Run before any publish claim.

## Pairing rule

Profile sets register and structure; the tell scan plus the aphorism budget (max one kicker per section, two to three per piece) gate the pass before delivery. Enforcement code lives inside the plugin: `humanizer/hooks/` (gate, scanner, pattern register), learn tools in `humanizer/learn/`.

## Out of scope (pointed, not stored here)

- **corpus-kb**: local RAG/KG/SQL corpus. Code and docs at `moliver28/corpus-kb` (public repo); live data in `~/.corpus-kb/corpus.db`. Do NOT copy corpus content into this marketplace; tools connect directly.
- **Obsidian vault**: KB notes live in `moliver28/obsidian-vault`. Referenced by wikilink, never copied here.
- **Owner's personal voice artifacts** (voice spec, register, exemplar vectors, calibration, runtime hook adapter, real article briefs): removed from this public mirror by the de-personalization ruling (2026-11-21) and archived privately outside this repo. The shipped plugin is the generic engine; per-user artifacts are built at runtime into `humanizer/learned/`.

## Canonical copy policy

The canonical copies live in the Hermes skill directories; this repo mirrors them. When a skill updates, re-copy it here in the same pass (same rule as profile propagation in humanizer's maintenance note). This repo is the distribution target for external tools; do not fork edits here first.
