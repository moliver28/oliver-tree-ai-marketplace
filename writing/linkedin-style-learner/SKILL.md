---
name: linkedin-style-learner
description: Use when deriving an author's LinkedIn voice and post gates.
version: 0.1.0
author: Michael Oliver
license: MIT
metadata:
  hermes:
    tags: [linkedin, style-learning, voice, gates, ollama]
    related_skills: [social-post-approval-pipeline, humanizer, platform-channel-gates]
---

# LinkedIn Style Learner (engagement posts)

## When to Use
Use when an author wants their LinkedIn engagement posts mechanically enforcable: deriving voice rules, template variants, slot contracts, and calibration gates from published posts. Not for the publishing flow itself (social-post-approval-pipeline does that).

Derive an author's voice, template variants, and mechanical enforcement from published posts. LinkedIn only. No Notion dependency: the knowledge base is plain Markdown files with YAML frontmatter in any folder (works in Obsidian or git).

## Inputs (ask once, then proceed)
- 3-10 published post bodies (markdown or pasted text), one file each.
- 2-3 full articles or essays in the same voice (corpus for style calibration).
- The author's hard rules, if any exist (banned words, punctuation tics, link rules). If none, derive them (Step 2).

All work lives in one folder: `<workdir>/Social/linkedin/` (create if missing).

## Step 1: Style inventory
Read all posts and corpus in one pass. Extract per post: opener type, stanza count, sentences per stanza, close type (question? which kind?), link position, numbers/sources used, first-person markers, punctuation habits. Build an inventory note: `style-inventory.md` (frontmatter: `type: style-inventory`, `status: active`, `created: <date>`). Record facts only, no judgments.

## Step 2: Rules derivation
From the inventory, write `voicebook.md` in the same folder. Sections, in order:
1. Hard rules: zero em dashes; banned words (start with: leverage, unlock, supercharge, game-changer, journey, synergy, delve, robust, seamless(ly), effortlessly, best-in-class, deep dive, excited to share, thrilled to share, happy to announce, i just posted, diving in); no all-caps except standard acronyms; no hashtag stacks in body; one link, last line.
2. Banned constructions (construction classes, not instances): pronoun-restatement inversions across sentence pairs ("X was not Y. It was Z."), filler concessions ("There is real weight there"), pivot markers ("Here is the case it misses"), reassurance kicks ("And that's okay"), self-answered questions, stacked staccato kickers (3+ short declaratives in a row outside the close), adverb openers.
3. Close contract: exactly one experience-shaped question in the final paragraph (asked about the reader's own work); bait forms banned ("comment YES", "agree?").
4. Hook contract: a number or named source inside the first 210 characters.
5. Dwell floor: 150 words minimum.

## Step 3: Variant skeletons (templates, not prose)
Abstract the posts into 4-6 variant skeletons. Each is a stanza-function sequence with named slots, not sentences. Slot union (mark which each variant requires): STAT (digit-bearing figure), SOURCE (named survey or person), TOPIC_CLAIM (settled consensus restated as fact), STORY_EXAMPLES (2-3 one-sentence concrete examples), THESIS (the piece's core answer), DESIGN_MOVES (2-3 imperative practices), COUNTER (what the consensus misses), DEFINITION (coined term + definition), GAP_STAT_PAIR (two contrasting figures, delta >= 5), TAKEAWAY (one-line imperative), PERSON_CONTEXT (the author's standing clause), CONSENSUS_HOLDER (who holds the steelman view), FAILURE_ROW (a real failure receipt: system, date, what broke, what now catches it), QUESTION_TAIL, LINK. Starter variants: flat-opener receipt; named-source claim; steelman-then-pivot; first-person failure receipt (skipped unless a real receipt exists); definition-in-passing.
Voice conventions across skeletons: flat concrete claims; semicolon-bridged single sentences instead of stacked kickers; no pronoun-restatement inversions.

## Step 4: Brief files (the data contract)
One brief JSON per post, co-located: `<workdir>/Social/linkedin/briefs/<slug>.json`. Fields mirror the slot union plus title, primary_keyword, tags. Schema lives next to the templates as `slots.schema.json`. Missing or malformed required slot = loud failure, never a guessed fill.

## Step 5: Mechanical gates (install in this order)

The stack has three layers enforcing the same zero-tell standard, applied per surface:

**Layer A: deterministic structure** (per surface): banned words, allowed-caps list, hook position, one question close, dwell floor, keyword+topics weave. Exit 0/1/2 (pass/hard fail/warnings).

**Layer B: semantic tell guard** (shared engine, calibrated per author): embedding classifier over a small local model (nomic-embed-text via Ollama is the proven default): kNN-over-exemplars scoring (not single centroids) over anti-pattern classes; one stylometric feature arm (11 deterministic features z-scored against the author corpus; catches what rules cannot spell out); gate rule = a hard tell requires the semantic hit AND style agreement, disagreement demotes to warning unless the semantic margin is 0.10+; optional owner-gold canon list. Calibration law: thresholds sit above the author-corpus background; a class that cannot clear it degrades to warn-mode; an owner verdict flagging a construction makes it canon (hard-fail in any position, bypassing the style veto). Growth loop (learning, never blocking): snapshot each draft before review; after approval edits land, diff prev/cur, label removed/changed sentences hit-or-clean into `ledger/labels.jsonl`; recalibrate after 5+ new labels; at 20+ labels per class, train a logistic head over raw embeddings (ship at F0.5 >= 0.70 held-out or keep the calibrated centroid/kNN layer).

**Layer C: humanizer judgment pass** (LLM scan, semantic): a per-piece improvement scan against an anti-pattern register (35 numbered pattern families in the reference implementation: announcements, hedged openers, moral-pivot lines, aphorism budget, question-bait, signposting, and similar). Any hit gets rewritten, never explained; rewrite, re-scan, resubmit. This layer catches what regex and embeddings miss because it reads intent; keep it as judgment, seed it from the same ledger, and keep its pattern list versioned in the folder (`patterns.md`).

Order matters: A blocks fast and free, B blocks what A cannot spell out, C rewrites what neither can catch. All three run before any review; the gate ladder never weakens a lower layer to satisfy a render.

## Multi-surface enforcement (social category, shared guard)
The guard and ledger are author-level; templates and rules are surface-level. One folder, many surfaces:
- `surfaces/linkedin/` (or at the folder root for the first surface): `voicebook.md` (surface rules: hook contract, close contract, link rules, dwell floor), `templates/` (variant skeletons), `briefs/`, `posts/`, `review/`, `tests/`.
- `guard/`: the calibrated engine state (class store, canon list, corpus, ledger). One engine serves every surface; canon lines and labels are author-wide, so a tell learned on any surface never lands on another.
- `patterns.md`: the shared humanizer register (Layer C), versioned, referenced by every surface's gate line.
- Per-surface differences live ONLY in voicebook + templates (X may allow shorter dwell, a newsletter no close-question, LinkedIn one link last line). The tell classes, style arm, canon list, and ledger never fork per surface. Adding a surface = adding a voicebook + templates + a gate line; the engine learns for all surfaces at once.

Engagement-lever gates, evidence-based (LinkedIn defaults, retune per surface): concreteness floor (>=2 concrete-noun hits per 100 words in the examples paragraph), gap delta >= 5 for GAP_STAT_PAIR, imperative open on TAKEAWAY (slot-driven), vague-fill lint (a-lot-of, many-teams, significantly-better, better-results, higher-quality pattern families).

Lever-to-evidence map: specificity/social proof -> hook; concrete language -> sharing effect (QJEP/SAGE 2025 line); practical utility -> saves (strongest algorithm signal; saves ~2x comments ~2x likes; dwell independent); curiosity gap -> counter paragraph (semantic, judged not regexed); specific questions -> substantive comments; link last line -> reach preservation.

## Slot registry + post-type selection (registry-era installs)
When the install carries the registry layer, slot definitions live once in `slots.yaml` (name, brief keys, kind, constraints, list-join mode) and BOTH the renderer and the structural validator read it; adding a slot then touches only slots.yaml plus the skeleton requiring it. Skeletons may carry inline list modes (`{{SLOT|clauses}}`). An engagement selection engine (`--select --brief F [--situations k=v... --used-kinds V1,V3]`) ranks viable post kinds from `post_types.yaml` x `weights.yaml` (weights cite their evidence anchor: Berger&Milkman practical utility, concrete-language sharing effect, saves ~2x comments ~2x likes, curiosity gap); selection only orders candidates — it never bypasses gates, and the pipeline re-ranks past already-used kinds via `--used-kinds` (derived automatically from the posted log's recent variant/kind rows, not a hand-maintained list).

Slot maximization is the default posture, not minimal requirements: audit each kind's required+recommended slots against the lever-to-evidence map and add every evidence-supported lever as `recommended` (weighted in the score, surfaced as fill-gaps), reserving `required` for levers the type's integrity demands; each addition cites its anchor as a YAML comment. Commentary kinds (link-optional) gain STORY_EXAMPLES and PERSON_CONTEXT for grounding and first-person authenticity; tips-style kinds gain QUESTION_TAIL and STORY_EXAMPLES for comment velocity and concreteness. Prove maximization mechanically: the same kind must score strictly higher for a brief that fills the recommended slots than for one that omits them, with fill-gaps shrinking. Details: `references/calibration-recipe.md` covers embedding batching, threshold law, canon arming, and the invariants battery.

## Step 6: Calibration ritual
Embed everything at init (batches <=64 with retry: small-model tokenizers crash on large batches). Prove two invariants before shipping any calibration change: (a) sweep all author-corpus files with zero errors; (b) all canon tell lines hard-fail in split pairs and mid-sentence positions. Keep fixture files for both. Give each verification-battery run its own temp directory (a fixed shared scratch path races with runs of itself and can fail a cell on a file that run itself just wrote), and treat a suspected flake as fixed only after two consecutive all-green full runs, not one.

## Deliverable
`voicebook.md` + templates + briefs + gates + fixtures inside `<workdir>/Social/linkedin/`, all frontmatter-typed, all paths relative to that folder. Hand the folder to social-post-approval-pipeline for render, approval, and publish.
