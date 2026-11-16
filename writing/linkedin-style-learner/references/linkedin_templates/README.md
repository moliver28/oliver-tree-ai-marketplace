# LinkedIn slot templates: article-announcement skeletons + brief contract

The five voicebook variants are skeletons with slots, not article-specific
prose. Any article works if its facts fit the slot union below; rendering and
coverage are mechanical. No LLM anywhere in the path.

Files in this directory:

| File | Role |
|---|---|
| `V1.md` `V2.md` `V3.md` `V5.md` | skeletons: `{{SLOT}}` placeholders + frontmatter (name, stanzas in order, required slots, per-stanza word floors, constraint notes) |
| `slots.yaml` | **declarative slot registry: single source of truth for slot names, brief keys, kinds and constraints** |
| `post_types.yaml` | evidence-driven catalog of post kinds (announcement-receipt, named-source, steelman-pivot, definition, failure-receipt, practical-tips, news-reaction, pure-question) with required/recommended slots, purpose, situation flags and the data-sourced V4 refusal |
| `weights.yaml` | engagement weights for `--select`: one base weight per (lever x post_type) plus situation multipliers, each with its evidence anchor in a comment |
| `config.example.json` | config template: copy to `~/.hermes/scripts/linkedin_config.json` (or drop `config.json` inside a redirect dir + `LINKEDIN_TEMPLATES_DIR`) |
| `V4` | not templated, by design: the failure receipt needs a verified Ledger receipt and first-person facts the card drafts by hand (see `marketing/linkedin-voicebook.md`); the refusal is sourced from `post_types.yaml` |
| `slots.schema.json` | JSON Schema (draft-07) for the brief JSON |
| `briefs/` | example briefs: `brief_test.json` (synthetic article, the generality fixture) plus real briefs for the two 2026 articles |
| renders | outputs stay out of source control; render to a scratch path |

Skeletons beyond V1..V5 are discovered automatically: any `V*.md` file in the
effective templates dir is renderable (`--variant V6`, fixtures, etc.). The
verification fixtures live outside this directory, in
`~/.hermes/scripts/tests/linkedin/` (fixtures V_FIXTURES skeleton + briefs,
`expected/` goldens, `run_linkedin_battery.py`).

Renderer: `~/.hermes/scripts/linkedin_render.py --variant V{n} --brief FILE --out FILE`
(deterministic string substitution; exit 1 with the slot names and no output
file on any missing or malformed required slot).

Checker (template coverage):
`~/.hermes/scripts/linkedin_voicebook_check.py --post FILE --log LOG --template V{n} --slots-file brief.json [--keyword KW --topics T1,T2 --check-og]`
`--template` and `--slots-file` must be used together; without both, the
checker's behavior is byte-identical to its pre-template self. `--template`
accepts V-numbers and any file-backed `V*.md` skeleton name in the effective
templates dir.

## slots.yaml: the declarative slot registry

One entry per slot: `kind` (text | list | object), `brief_keys` (the JSON
keys read from the brief), and constraints. The render's `validate_slot` and
the brief-key maps in renderer and checker READ this file; there is no
per-slot if-chain in python. Adding a slot = add the entry here + use it in
a skeleton: no python change. Proof: the `TAGLINE` slot (declared in
slots.yaml only) renders and checks through the tests fixture; the battery
[ b] check also greps that no linkedin python file mentions TAGLINE.

Fields (render-side enforcement, semantics frozen to the legacy behavior):

- `trim: end|plain` - "end" strips trailing `[.!?,;:\s]` (the skeleton owns
  sentence ends); "plain" keeps the value's marks (QUESTION_TAIL's `?`).
- `digit`, `single_fragment` (no internal sentence break), `max_sentences`
  (implies `?`/`!` rejected), `is_token` (DEFINITION shape), `question`,
  `you_your`, `no_punct` (em dash / ` -- ` / `!` scan).
- `min_chars` / `max_chars` (+ optional `length_msg` wording).
- `must_be_url` + `must_be_public: config` (see config below).
- lists: `min_items` / `max_items` / `item_min_chars` / `item_max_chars` and
  `default_mode` (list join when the skeleton token carries no modifier).
- objects: `keys` (per-key constraints incl. `strip_end`, `lower_first`,
  `string_only`, `digit`, `max_chars`) + `join` template
  (GAP_STAT_PAIR: `"{gap_stat_a}, while {gap_stat_b}"`;
  FAILURE_ROW: `"in {system} on {date}, {what_broke}; what catches it now: {what_now_catches}"`).
- `starts_imperative` + `imperative_verbs` on TAKEAWAY: consumed by
  `linkedin_lever_check.py` (imperative-gate verb set, unioned with the
  builtin list). The render does not enforce it, unchanged.

### List join modes (generic tokens)

Any list slot in a skeleton may carry an inline modifier, and the default
join comes from slots.yaml per slot:

| Token / mode | Behavior |
|---|---|
| `{{SLOT\|commas}}` (or no modifier for DESIGN_MOVES) | comma-joined clause list, items lowerfirst (DESIGN_MOVES legacy) |
| `{{SLOT\|clauses}}` | semicolon-bridged single sentence, items lowerfirst |
| `{{SLOT\|para}}` | item 1 lowerfirst, later items Sentence-cased, joined with ". " |
| `{{SLOT\|pair}}` | exactly two items semicolon-bridged; any other count fails loudly with the slot name |

STORY_EXAMPLES keeps its exact legacy behavior: a modifier present (any of
the three) selects `clauses`; no modifier selects `para` for 3 items and
`pair` for 2 (its `default_mode: count`).

The full brief-key table (from slots.yaml `brief_keys`; "Required by" also
mirrors the post_types catalog):

| Slot | Brief key(s) | Meaning | Required by |
|---|---|---|---|
| STAT | `stat` | number the post opens on; must contain a digit | V1, V2 |
| SOURCE | `source` | survey, study, standard or person, as a phrase | V2 |
| TOPIC_CLAIM | `topic_claim` | settled consensus restated as fact, one sentence | V1, V2, V3 |
| STORY_EXAMPLES | `story_examples` | 2-3 concrete one-sentence tool/agent examples | V1, V2, V3, V5 |
| THESIS | `thesis` | the article's core architecture answer, 1-3 sentences | V1, V2, V3, V5 |
| DESIGN_MOVES | `design_moves` | 2-3 imperative practices | V1 |
| COUNTER | `counter` | what the consensus misses, 1-2 sentences | V2 |
| DEFINITION | `definition` | coined term plus plain-words definition, one sentence, contains ` is ` | V5 |
| GAP_STAT_PAIR | `gap_stat_a`, `gap_stat_b` | two contrasting percentages; rendered `<a>, while <b>` | V5 |
| TAKEAWAY | `takeaway` | one-line specification, 1-2 sentences | V1, V5 |
| QUESTION_TAIL | `question_tail` | the experience-shaped close question (`?` and you/your exactly once) | V1, V2, V3, V5 |
| LINK | `link` | public article URL (config allowlist; never app.notion.com) | all link-required kinds |
| PERSON_CONTEXT | `person_context` | the author's standing clause | V1, V3 |
| CONSENSUS_HOLDER | `consensus_holder` | named holder of the steelman consensus | V3 |
| FAILURE_ROW | `failure_row` | object (system, date, what_broke, what_now_catches) | failure-receipt (V4) |
| TAGLINE | `tagline` | registry-extension fixture slot (10-60 chars), used only by the tests fixture | - |

Brief keys `title`, `primary_keyword`, `tags` are contract fields the render
does not substitute: the caller passes `primary_keyword` as the checker's
`--keyword` and `tags` as `--topics`. `QUESTION_TAIL` is the one slot not in
the original brief list: it is carried in the brief JSON like every other slot
because the close question must match the article, and reuse of a stock
question across posts would read as scaffolding.

Rule for the primary keyword: it must appear verbatim in at least one required
slot (thesis or takeaway carries it in the example briefs); the checker's
seo-keyword gate enforces it per render.

## Config file (author/surface config)

Discovery, same contract in every script (one local loader copy each, no
cross-imports): `$LINKEDIN_TEMPLATES_DIR/config.json` first, then
`~/.hermes/scripts/linkedin_config.json`. Neither file present -> factory
defaults, byte-identical to the pre-config behavior. Fields:

- `template_dir` - the surfaces' templates dir; consulted only when
  `LINKEDIN_TEMPLATES_DIR` is unset (the env var wins).
- `url_allowlist` - regex list; the LINK slot gate (render), the checker's
  link-line gate + template LINK presence check, and selection viability
  validate against it. Factory default behavior is the substring rule
  (notion.site or the synology-nas KB mirror). The `app.notion.com`
  rejection is hardcoded privacy: no config can relax it.
- `ollama_url` - the `/api/embed` endpoint voice_guard.py uses.
- `voice_corpus` - voice-corpus paths for voice_guard.py (init + checks).

## Post-type selection (`--select`)

`linkedin_render.py --select --brief brief.json [--situations k=v,...]
[--used-kinds V1,V3] [--explain] [--out selection.json]` prints one JSON
object ranking the post kinds from post_types.yaml:

- Viability: every `requires` slot (plus one of `requires_alt` when declared)
  must be fillable from the brief (presence-based); LINK additionally must
  pass the configured allowlist. Kinds that fail presence are reported under
  `not_viable` with their required-missing lists; recommended-but-unfilled
  slots are reported as `fill_gaps`, never as errors.
- Score = sum over levers (weights.yaml) of `base * product(situation
  multipliers that hold)`. A lever triggers when its slots are filled per
  its match rule (`any` / `all`); `link_penalty` triggers only for
  commentary-type kinds (news-reaction, pure-question) when `has_link` is
  true. Ordering: score desc, then kind name asc; `top_pick` is ranked[0].
- Situations: `has_link`, `has_failure_row`, `has_definition`,
  `has_gap_pair` are derived from the brief; `news_hook`, `debate_active`
  default false; `--situations k=true|false` overrides deterministically.
- `--explain` adds per-kind breakdown lines (lever contributions and
  situation multipliers) to each ranked entry.
- `--used-kinds V1,V3 --used-kinds announcement-receipt` (kind or variant
  names, comma-separated) demotes those kinds one effective rank step
  downstream in a single stable pass, deterministic. This is how the
  pipeline re-ranks past the rotation set: the checker still enforces
  variant-ladder rotation and open-sha256 no-repeat, so selection lists
  kinds and the operator steers past used ones; there is no auto-fallback
  loop.
- Gates are never bypassed: the chosen kind renders and gates exactly like
  today (render -> checker -> lever -> guard). If a gate run fails for a
  shape reason the presence check could not see, fall back manually to the
  next ranked kind.

Selection evidence map (full anchors in the per-entry/per-weight comments):

- hook specificity (digit or named source) -> saves + scroll-stop
- STORY_EXAMPLES concreteness -> concrete-language sharing effect (SAGE QJEP 2025)
- practical utility block (DESIGN_MOVES + imperative TAKEAWAY) -> practical
  utility strongest virality predictor (Berger & Milkman, r = .31)
- COUNTER -> curiosity / information gap (base weight; the semantic layer is
  not required to quantify it further)
- QUESTION_TAIL -> specific-experience comment velocity
- GAP_STAT_PAIR -> contrast / dwell
- DEFINITION -> social currency / idea association
- FAILURE_ROW receipt -> narrative transportation
- link penalty -> only commentary types when has_link

## Smoothing rules (deterministic, owned by the renderer)

- Every slot value carries no terminal punctuation. The render strips trailing
  `[.!?,;:]`; the skeleton owns sentence ends (each skeleton line after a
  paragraph-final token ends with an explicit period).
- STORY_EXAMPLES, 3 items: separate sentences in the V1 paragraph pattern
  after the skeleton's colon lead-in; item 1 stays lowercase, later items
  Sentence-cased. 2 items: semicolon-bridged single sentence.
- `{{STORY_EXAMPLES|clauses}}` (V3 pivot): items semicolon-bridged into one
  sentence (the owner's semicolon move) to stay inside the 4-sentence
  paragraph cap.
- DESIGN_MOVES: one comma-joined clause list after the colon lead-in.
- GAP_STAT_PAIR: `<gap_stat_a>, while <gap_stat_b>`.
- Case normalization is mechanical (first letter lower- or upper-cased at
  join points); acronyms that start a word (LLMs, UX) are left alone.

## Voice conventions visible in today's renders

Flat concrete claims, semicolon-bridged single sentences instead of stacked
kickers, no pronoun-restatement inversions, no em dashes, no exclamation
marks, no placeholder residue. Slot values and skeleton prose both scanned.
Banned words are enforced downstream by `linkedin_voicebook_check.py`; the
render additionally rejects em dashes, ` -- `, `!`, and any `{{` surviving
assembly.

## Checker template coverage (mechanical, after default checks pass)

With `--template Vn --slots-file brief.json`:

- Presence: every slot the variant's frontmatter marks required must be
  present and fillable in the brief; otherwise exit 1 listing them
  (`missing-slots`), even when other checks fail. Brief keys come from
  slots.yaml.
- `template-hook`: the paragraph carrying STAT/SOURCE/GAP_STAT_PAIR must
  contain a digit or a capitalized source token within its first 210 chars
  (extends the existing hook rule; V3 has no stat, so paragraph 1 is checked
  against the brief's source/stat tokens when present).
- `examples-coverage`: the paragraph carrying story examples must contain at
  least two clauses of 40+ characters, split on sentence ends and semicolons
  (so the semicolon-bridged shapes count their clauses).
- Close: the existing exactly-one-experience-question rule stays; the template
  adds nothing there.
- `unrendered-slot`: any `{{...}}` surviving anywhere in the post fails exit 1,
  unconditionally in template mode.
- `template-floor`: per-stanza word floors from the skeleton frontmatter
  (words before the link, blank-line stanza split).

## Verification battery

`~/.hermes/scripts/tests/linkedin/run_linkedin_battery.py` runs the full gate
set: 12-cell matrix (3 briefs x 4 variants through render + checker + lever +
guard), the TAGLINE registry proof, the portable-config matrix, default-path
golden comparison, guard invariants (tells test, canon sweep, corpus), and
the selection checks (determinism, weights sanity, used-kinds demotion).
Exit 0 = all green. Regenerate `tests/linkedin/expected/` goldens only after
a deliberate change to checker semantics or the seeded article.

## Fail-loudly contract

- Render: missing/type mismatch/format violation lists the slot names, exits 1,
  writes no `--out` file. Refusal (V4 without a verified FAILURE_ROW) exits 1
  with the message from post_types.yaml.
- Checker: template errors use codes `missing-slots`, `template-slot-type`,
  `template-hook`, `examples-coverage`, `unrendered-slot`, `template-floor`,
  `template-usage` (flags used apart or unknown name), `template-unavailable`
  (refusal entry applies).
- Malformed slots.yaml / post_types.yaml / weights.yaml / config file: loud
  failure (ValueError / config-unreadable), never a silent misread.
