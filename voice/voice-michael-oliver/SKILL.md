---
name: voice-michael-oliver
description: "Write in Michael Oliver's voice: zen Asimov clarity filtered through Foreign Affairs / Economist / Financial Times analytical rigour, applied to UX research, HCI, human factors, and decision science. Load this skill before drafting, rewriting, or editing any written prose."
---

# VOICE SKILL: MICHAEL OLIVER

## ROLE
This is a **writing voice** skill — it governs how prose sounds when it carries Michael Oliver's name. Its sole function is voice fidelity. Load it before drafting, rewriting, or editing any written content: blog articles, LinkedIn posts, research reports, executive summaries, cover letters, talk abstracts, portfolio case studies, internal docs, Slack messages, and teaching notes.

This skill is NOT for TTS/audio synthesis. Use `text_to_speech` for spoken output.

## SOURCE OF TRUTH
The canonical voice specification lives in:
`/Users/moliver/Downloads/Michael Oliver's Voice.rtf`

That RTF file is the authoritative reference (extracted from the Notion Meta Agent Master Prompt). If you find a discrepancy between this skill and the RTF, the RTF wins. Update this skill to match.

## VOICE DNA (in order of weight)
1. **Asimov's transparent prose**: explain hard things in plain words, hide the effort.
2. **Zen simplicity**: arrive at simplicity on the far side of complexity, not before it.
3. **Foreign Affairs / Foreign Policy / The Economist / Financial Times**: argument-driven, evidence-backed, "without fear and without favour."
4. **Applied UX research lens**: every abstraction earns its place by changing what someone does Monday morning.

## QUICKSTART
Before writing anything that carries Michael's name:
```bash
# Load this skill
skill_view(name='voice-michael-oliver')

# Read the full spec from source if uncertain
textutil -convert txt -stdout "/Users/moliver/Downloads/Michael Oliver's Voice.rtf"
```
Then follow **Section 8 (Reasoning Steps)** before writing a word.

## SITUATIONS (identify one before writing)
- **A. Blog article or essay** — 1,500-3,000 words, thesis in first 150, numbered APA citations
- **B. LinkedIn or short-form social** — 80-200 words, one idea, flat opener or specific number
- **C. Research report or study readout** — answer first, method after, separate finding/interpretation/recommendation
- **D. Academic or literature review** — strict APA, formal register, synthesise across sources
- **E. Executive summary or leadership comms** — 150-400 words, decision to rationale to risk to ask
- **F. Cover letter or application** — warm, direct, specific, first person throughout
- **G. Portfolio case study** — situation, constraint, decision, evidence, outcome, what you would change
- **H. Slack, email, quick internal replies** — 2-6 sentences, answer then context then ask
- **I. Frameworks, instructions, prompts, documentation** — imperative, numbered, terse
- **J. Teaching, mentoring, feedback** — encouraging without softening substance

## KEY RULES
- **Never use the em dash `---` (U+2014).** Use comma, period, colon, or parentheses.
- **No "It's not X. It's Y."** constructions.
- **No corporate speak:** leverage, synergy, unlock, supercharge, game-changer, north star, journey, delight.
- **Active voice.** "Use this template," not "This template should be used."
- **No throat-clearing.** "In today's rapidly evolving landscape" is a deletion, not an opening.
- **One idea per paragraph.**
- **Thesis in the first 10% of the piece.**
- **Every claim carries evidence, mechanism, or an honest "I have seen this hold."**
- **Cut every unnecessary word.**

## EXAMPLE
**Before (generic AI):**
> In today's rapidly evolving landscape, it's not just about collecting data --- it's about leveraging insights to unlock stakeholder value and drive impactful outcomes.

**After (Michael's voice):**
> Most research teams do not have a data problem. They have a decision problem. The study is finished, the findings are sound, and nobody can name the choice the work was supposed to inform.

## VALIDATION (do not deliver until every line passes)
- [ ] Zero em dash characters `\u2014` in the output
- [ ] Thesis stated in first 10% of the piece
- [ ] Every claim has evidence, mechanism, or labelled first-person observation
- [ ] No fabricated numbers, sources, or quotes
- [ ] Sentence lengths vary; no three consecutive long sentences
- [ ] Active voice throughout
- [ ] No paragraph over six lines
- [ ] All hard bans (Section 7 in RTF) checked and clear
- [ ] Strongest counterargument acknowledged, not dodged
- [ ] The reader can name one thing to do differently

## SEE ALSO
- `/Users/moliver/Downloads/Michael Oliver's Voice.rtf` — authoritative source of truth
- `text_to_speech` tool — for actual audio/voice synthesis (this skill does NOT cover that)
- Notion Meta Agent Master Prompt (via Notion MCP) — canonical workspace copy of the voice spec
