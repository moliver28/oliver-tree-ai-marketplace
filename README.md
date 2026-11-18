# Oliver Tree AI Marketplace

Private index of reusable system assets for pointing ANY AI tool (Claude, Codex, other Hermes profiles) at, without copy-pasting prompts each session.

## Index

| Asset | Path | Use |
|---|---|---|
| Voice spec (Michael Oliver) | `voice/voice-michael-oliver/` | Generation half: register, structure, validation gates for any prose carrying Michael's name. `voice-spec-ssot.txt` is the authoritative spec. |
| /voice plugin (user surface) | `humanizer/` | Rewrites copy in your learned voice, quiet tell gate, `/voice` applies and reports one line. Learns your phrasing on the side, zero LLM tokens. |
| Zero-AI-Tells Register | `onboarding/zero-ai-tells-register.md` | The 37-pattern rulebook + hard bans behind the gate, the portable copy of the owner's canonical register. |
| Voice onboarding template | `onboarding/VOICE_ONBOARDING.template.md` | Fill-in profile for any end user: voice, reader, channels/situations, hard rules, conditions, validation gates. |
| Author voice learner (LinkedIn) | `writing/linkedin-style-learner/` | Derive an author's voice + post gates from their existing posts; pairs with the voice system. |
| Engineering workflows | `engineering/` | codebase-inspection, llm-integration, node/python debuggers, meta-decision, prompt-engineering, deliberation, iit-hci-integration. |
| Research workflows | `research/` | grounded-citations, document-to-action-items, meeting-action-items, nlp-analyst, academic, literature-review. |
| Prompt engineering | `engineering/prompt-engineering/` | COSTAR prompt optimization with evidence-based technique selection; explains every change it makes. |
| Deliberation | `engineering/deliberation/` | Multi-perspective stress-test: initial analysis, simulated stakeholder reactions from parallel subagents, refined conclusion. |
| IIT+HCI integration | `engineering/iit-hci-integration/` | Discovers the agent CLI's components at runtime, maps workflow gaps, wires dual-layer enforcement. |
| Academic sourcing | `research/academic/` | Parallel scholarly database search; peer-review status, evidence hierarchy, citation rigor. |
| Literature review | `research/literature-review/` | FSM-based systematic review protocol: scoping through PRISMA-style reporting. |
| Decision advisor plugin | `decision-advisor/` | `/decide` and the decision-advisor agent run the meta-decision pipeline on one-way doors; pairs with `engineering/meta-decision/`. |
| Triage of everything else | `catalog.md` | Assessed: move-port / list / exclude, with reasons. |
| Provenance ledger | `PROVENANCE.md` | Origin verification per published asset; community-derived pulls |

## Install (Claude Code)

```
claude plugin marketplace add moliver28/oliver-tree-ai-marketplace
claude plugin install humanizer-voice@oliver-tree-ai-marketplace
claude plugin install voice-gate@oliver-tree-ai-marketplace
claude plugin install decision-advisor@oliver-tree-ai-marketplace

Updates (run after any release note here):
```
claude plugin update humanizer-voice@oliver-tree-ai-marketplace
claude plugin update voice-gate@oliver-tree-ai-marketplace
claude plugin update decision-advisor@oliver-tree-ai-marketplace
```

Then `/voice <text>` after one onboarding pass. Consumable from any other AI tool by pointing it at `CLAUDE.md` in this repo.

## Verify

```
python3 scripts/verify.py
```

Exit 0 = manifests parse, all skills carry frontmatter, and the delivery gate demonstrably fails sloppy text and passes clean text. Run before any publish claim.

## Pairing rule

Profile sets register and structure; the tell scan plus the aphorism budget (max one kicker per section, two to three per piece) gate the pass before delivery. Enforcement code in `voice-gate/`.

## Out of scope (pointed, not stored here)

- **corpus-kb**: local RAG/KG/SQL corpus. Code and docs at `moliver28/corpus-kb` (public repo); live data in `~/.corpus-kb/corpus.db`. Do NOT copy corpus content into this marketplace; tools connect directly.
- **Obsidian vault**: KB notes live in `moliver28/obsidian-vault`. Referenced by wikilink, never copied here.
- **Delivery-gate hook (mechanical enforcement)**: mirrored in `voice-gate/` (voice-gate.py, voice-check.py, voice-tells.py, voice-vector-build.py). Runs as a pre_tool_call hook with regex + vector layers, fail-open when Ollama is down. Live install is `~/.hermes/agent-hooks/`. Scope note: the gate as deployed also enforces personal assistant-voice rules; for public/work installs, trim the pattern list in `voice-tells.py` to the public-facing tells only.

## Canonical copy policy

The canonical copies live in the Hermes skill directories; this repo mirrors them. When a skill updates, re-copy it here in the same pass (same rule as profile propagation in humanizer's maintenance note). This repo is the distribution target for external tools; do not fork edits here first.
