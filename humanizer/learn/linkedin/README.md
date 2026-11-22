# LinkedIn style learner (folded into humanizer)

Derives an author's LinkedIn voice rules, post templates, and enforceable
quality gates from their published posts, then renders and gates engagement
posts mechanically. LinkedIn only. No knowledge-base dependency: the working
folder is plain Markdown files with YAML frontmatter in any directory (works
in Obsidian or git). No LLM anywhere in the render/check/lever path; the
plugin's `/voice` rewrite pass and the delivery gate in `hooks/` are the only
model-adjacent surfaces, and the gate itself is deterministic (see
`../../LEARN-VOICE.md`).

## When to use

Use when an author wants their LinkedIn engagement posts mechanically
enforced: deriving voice rules, template variants, slot contracts, and
calibration gates from published posts. Not for the publishing flow itself.

## Inputs (ask once, then proceed)

- 3-10 published post bodies (markdown or pasted text), one file each.
- 2-3 full articles or essays in the same voice (corpus for style calibration).
- The author's hard rules, if any exist (banned words, punctuation habits,
  link rules). If none, derive them (Step 2).

All work lives in one folder chosen by the author (create if missing).

## Step 1: Style inventory

Read all posts and corpus in one pass. Extract per post: opener type, stanza
count, sentences per stanza, close type (question? which kind?), link
position, numbers/sources used, first-person markers, punctuation habits.
Build an inventory note (`style-inventory.md`, frontmatter:
`type: style-inventory`, `status: active`, `created: <date>`). Record facts
only, no judgments.

## Step 2: Rules derivation

From the inventory, write `voicebook.md` in the same folder. Sections, in
order:

1. Hard rules: zero em dashes; banned words (start from the generic AI-tell
   vocabulary the checker enforces: leverage, unlock, supercharge,
   game-changer, journey, synergy, delve, best-in-class, seamless(ly),
   effortlessly, robust, deep dive, in today's rapidly evolving, plus the
   engagement-bait artifacts: excited to share, thrilled to share, happy to
   announce, i just posted, drop a comment, agree?); no all-caps outside the
   standard acronym allowlist; no hashtag stacks in body; one link, last line.
2. Banned constructions (construction classes, not instances): pronoun-
   restatement inversions across sentence pairs, filler concessions, pivot
   markers, reassurance kicks, self-answered questions, stacked staccato
   kickers (3+ short declaratives in a row outside the close), adverb openers.
   The delivery gate's machine list (`hooks/voice_tells.py`) already enforces
   the generic versions of these; the voicebook carries only the author's
   additions.
3. Close contract: derived from the author's corpus (the shape of the close
   question their posts actually ask); the default the checker enforces is
   exactly one experience-shaped question in the final paragraph, asked about
   the reader's own work; bait forms ("comment YES", "agree?") are banned.
4. Hook contract: derived from the author's corpus; the default the checker
   enforces is a number or named source inside the first 210 characters.
5. Dwell floor: 150 words minimum (the checker's default).

## Step 3: Variant skeletons (templates, not prose)

Abstract the posts into 4-6 variant skeletons. Each is a stanza-function
sequence with named slots, not sentences. Slot union (mark which each variant
requires): STAT (digit-bearing figure), SOURCE (named survey or person),
TOPIC_CLAIM (settled consensus restated as fact), STORY_EXAMPLES (2-3
one-sentence concrete examples), THESIS (the piece's core answer),
DESIGN_MOVES (2-3 imperative practices), COUNTER (what the consensus misses),
DEFINITION (coined term + definition), GAP_STAT_PAIR (two contrasting figures,
delta >= 5), TAKEAWAY (one-line imperative), PERSON_CONTEXT (the author's
standing clause), CONSENSUS_HOLDER (who holds the steelman view), FAILURE_ROW
(a real failure receipt: system, date, what broke, what now catches it),
QUESTION_TAIL, LINK. Starter variants ship in `templates/`: flat-opener
receipt (V1), named-source claim (V2), steelman-then-pivot (V3), definition-
in-passing (V5); the first-person failure receipt (V4) stays hand-drafted from
a verified receipt row.

Voice conventions across skeletons: flat concrete claims; semicolon-bridged
single sentences instead of stacked kickers; no pronoun-restatement inversions.

## Step 4: Brief files (the data contract)

One brief JSON per post, co-located: `<workdir>/briefs/<slug>.json`. Fields
mirror the slot union plus title, primary_keyword, tags. Schema:
`templates/slots.schema.json`. Missing or malformed required slot = loud
failure, never a guessed fill.

## Step 5: Mechanical gates (install in this order)

Three layers enforce the same zero-tell standard, applied per surface:

**Layer A: deterministic structure** (this module): banned words, allowed-caps
list, hook position, one question close, dwell floor, keyword+topics weave.
Exit 0/1/2 (pass/hard fail/warnings). Scripts: `linkedin_render.py` (slot
filler + post-type selector), `linkedin_voicebook_check.py` (voicebook +
template coverage), `linkedin_lever_check.py` (engagement-lever floors).

**Layer B: the plugin's deterministic gate**: `hooks/gate.py` +
`hooks/voice_check.py` run the regex tell layer (plus the optional per-user
vector layer built by `learn/voice_vector_build.py`) over the assembled post.
Surfaces and thresholds come from the user's learned profile; nothing is
hard-coded here.

**Layer C: human judgment pass** (model, run by the host tool): a per-piece
improvement scan against the author's anti-pattern register. Any hit gets
rewritten, never explained; rewrite, re-scan, resubmit. This layer catches
what regex and structure cannot spell out because it reads intent; keep its
pattern list versioned in the author's folder (`patterns.md`), and seed it
from the same ledger as Layer B.

Order matters: A blocks fast and free, B blocks what A cannot spell out,
C rewrites what neither can catch. All three run before any review; the gate
ladder never weakens a lower layer to satisfy a render.

## Slot registry + post-type selection

Slot definitions live once in `templates/slots.yaml` (name, brief keys, kind,
constraints, list-join mode) and BOTH the renderer and the structural
validator read it; adding a slot then touches only slots.yaml plus the
skeleton requiring it (the fixtures prove it: the TAGLINE slot has zero python
references). Skeletons may carry inline list modes (`{{SLOT|clauses}}`). An
engagement selection engine (`linkedin_render.py --select --brief F
[--situations k=v... --used-kinds V1,V3]`) ranks viable post kinds from
`templates/post_types.yaml` x `templates/weights.yaml` (weights cite their
evidence anchor: Berger&Milkman practical utility, concrete-language sharing
effect, saves outweigh comments and likes, curiosity gap); selection only
orders candidates — it never bypasses gates, and the pipeline re-ranks past
already-used kinds via `--used-kinds` (derived automatically from the posted
log's recent variant/kind rows, not a hand-maintained list).

Slot maximization is the default posture, not minimal requirements: audit
each kind's required+recommended slots against the lever-to-evidence map and
add every evidence-supported lever as `recommended` (weighted in the score,
surfaced as fill-gaps), reserving `required` for levers the type's integrity
demands; each addition cites its anchor as a YAML comment. Commentary kinds
(link-optional) gain STORY_EXAMPLES and PERSON_CONTEXT for grounding;
tips-style kinds gain QUESTION_TAIL and STORY_EXAMPLES for comment velocity
and concreteness. Prove maximization mechanically: the same kind must score
strictly higher for a brief that fills the recommended slots than for one
that omits them, with fill-gaps shrinking.

## Step 6: Calibration ritual

Keep fixture files for the invariants (the battery covers them). Give each
verification-battery run its own temp directory (a fixed shared scratch path
races with runs of itself and can fail a cell on a file that run itself just
wrote), and treat a suspected flake as fixed only after two consecutive
all-green full runs, not one.

## Verification battery

`python3 tests/linkedin/run_linkedin_battery.py` (from this folder) runs the
full gate set: the 12-cell matrix, the TAGLINE registry proof, the
portable-config matrix, default-path goldens, the plugin gate invariants, and
the selection checks. Exit 0 = all green. Regenerate
`tests/linkedin/expected/` goldens only after a deliberate change to briefs,
skeletons or checker semantics. The battery is runnable by hand; it is not
wired into `scripts/verify.py`.

## Deliverable

`voicebook.md` + templates + briefs + gates + fixtures inside the author's
working folder, all frontmatter-typed, all paths relative to that folder.
