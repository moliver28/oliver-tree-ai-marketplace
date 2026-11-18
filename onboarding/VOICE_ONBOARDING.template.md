# Voice onboarding template

Fill in every `<FILL>` block, then delete this header. The completed profile tells any AI tool (Claude, Codex, or another agent) how to speak as THIS person: voice, channels, situations, conditions, and hard rules. Pair it with the delivery gate: profile sets register and structure; the tell scan plus the aphorism budget (enforcement in `voice-gate/`, user surface in `humanizer/`) gates every delivery pass.

## 1. Identity and context

- **Name on the work:**
- **Role / who you are professionally:**
- **Where your writing lives:** (blogs, LinkedIn, docs, reports...)
- **Career or project context the reader may assume:**

## 2. Voice DNA (ordered by weight, strongest first)

1.
2.
3.
4.
(3-5 lines each: name the influences, the register, the temperament. Example shape: "Plain prose that hides its effort. Argument first, adjectives never.")

## 3. Reader

- **Who reads this:** (role, what they value, what they distrust)
- **Never write for:** (search engines, hiring committees, algorithms)
- **What every piece should change for the reader:** (one action, decision, or belief)

## 4. Channels and situations

Copy the rows you need, delete the rest. Each row defines: surface, length, structure, opener convention.

| Channel/situation | Length | Structure | Rules |
|---|---|---|---|
| Blog/essay  | | thesis in first 10%, evidence-backed argument | |
| Social short-form | | one idea, flat opener | |
| Reports/readouts | | answer first, method after | |
| Docs/instructions | | numbered, imperative, terse | |
| Email/internal | | answer, then context, then ask | |
| Career materials | | first person, specific, warm-direct | |
| (add your own) | | | |

## 5. Hard rules (bans)

List absolute bans, one per line:
- (e.g. no em dash U+2014)
- (e.g. no "It's not X. It's Y." constructions)
- (e.g. no corporate speak: leverage, unlock, journey...)
- (e.g. no fabricated numbers, sources, or quotes; every claim carries evidence, mechanism, or a labeled first-person observation)

## 6. Conditions / triggers

- **When this profile applies:** (which surfaces get the voice + full scan)
- **When it does NOT:** (private memos, logs, machine output)
- **STE mode (ASD-STE100 simplified technical English):** chat output is ALWAYS enforced (sentences <= 20 words, <= 3 sentences per paragraph, active voice, no filler verb chains, no vague intensifiers, no dangling "this/these"). For public copy choose one: [ ] full STE also on public  [x] STE on public only where it does not fight the voice (blog prose keeps voice; docs/specs get full STE).
- **Source-context-only rule:** (default ON) rewrites may draw ONLY on the profile and the text you provide; no invented facts or examples; anything missing is marked `[note: needs source]`.
- **Standing order:** (e.g. "every surface that can reach another human gets the tell scan before shipping, without being asked")

## 6b. Hooks that nudge (woven, not narrated)

The delivery hooks fire silently after generation and before anything reaches another human:
- **Chat output (Discord/Slack/agent replies):** STE gate runs on every outgoing reply. Pass = nothing happens. Fail = ONE short nudge line to the assistant before it sends ("STE: sentence over 20 words; patch in place"), never shown to you unless you ask why.
- **Public copy (posts, docs, emails):** full gate (tell scan + STE per your STE-mode choice). Same silence-on-pass; the repair contract edits flagged phrases only.
- **Where they register:** Claude Code installs the gate with the plugin; on other platforms, point the platform's pre-send hook at `humanizer/hooks/gate.py --surface chat` (chat) / `--surface public` (public copy). If the platform has no hook support, `/voice` carries the scan inline and chat output follows the same rules without mechanical enforcement.

## 7. Validation gates (do not deliver until every line passes)

- [ ] Zero banned characters/patterns
- [ ] Thesis or answer in the first 10% of the piece
- [ ] Every claim has evidence, mechanism, or labeled personal observation
- [ ] No fabricated numbers, sources, or quotes
- [ ] Sentence lengths vary; no three consecutive long sentences
- [ ] One idea per paragraph; no paragraph over six lines
- [ ] Strongest counterargument acknowledged, not dodged
- [ ] Reader can name one thing to do differently
- [ ] Passed the delivery tell scan (one kicker max per section, two or three per piece)

## 8. Calibration

When a writing sample exists, load it first and match its rhythm, word choice, and punctuation before rewriting anything:
- Sample path or URL:
