# AI Marketplace

Private index of reusable system assets for pointing ANY AI tool (Claude, Codex, other Hermes profiles) at, without copy-pasting prompts each session.

## Index

| Asset | Path | Use |
|---|---|---|
| Voice spec (Michael Oliver) | `voice/voice-michael-oliver/` | Generation half: register, structure, validation gates for any prose carrying Michael's name. `voice-spec-ssot.txt` is the authoritative spec. |
| Humanizer (35 anti-AI patterns) | `humanizer/` | Enforcement half: the tell scan + aphorism budget gate before any public prose ships. |
| Anti-pattern rules (Daneel voice) | `anti-patterns/` | Regex rules YAML (em dash, completion claims, sycophancy, etc.) for assistant-voice linting. |
| Distilled anti-patterns | `anti-patterns/anti-patterns.md` | Plain-language version for tools that cannot run YAML rules. |

## Pairing rule

Voice skill sets register and structure; humanizer's 35 patterns plus the pattern 35 aphorism budget (max one kicker per section, two to three per piece) gate the pass before delivery.

## Out of scope (pointed, not stored here)

- **corpus-kb**: local RAG/KG/SQL corpus. Code and docs at `moliver28/corpus-kb` (public repo); live data in `~/.corpus-kb/corpus.db`. Do NOT copy corpus content into this marketplace; tools connect directly.
- **Obsidian vault**: KB notes live in `moliver28/obsidian-vault`. Referenced by wikilink, never copied here.
- **Daneel-style linter engine**: mirrored in `plugins/daneel-style/` plus the runtime CLI `~/.hermes/scripts/daneel_style_lint.py`; only the portable rules YAML also sits in `anti-patterns/`.
- **Voice-gate hook (humanizer mechanical enforcement)**: mirrored in `plugins/voice-gate/` (voice-gate.py, voice-check.py, voice-tells.py, voice-vector-build.py). Runs as a pre_tool_call hook with regex + vector layers, fail-open when Ollama is down. Live install is `~/.hermes/agent-hooks/`.

## Canonical copy policy

The canonical copies live in the Hermes skill directories; this repo mirrors them. When a skill updates, re-copy it here in the same pass (same rule as profile propagation in humanizer's maintenance note). This repo is the distribution target for external tools; do not fork edits here first.
