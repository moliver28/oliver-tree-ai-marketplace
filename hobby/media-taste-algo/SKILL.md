---
name: media-taste-algo
version: 0.1.0
author: Michael Oliver
license: MIT
description: "Learns each person's movie and show taste from their verdicts and scores watchlists into ranked picks. Use when the user says: 'log that we hated that show', 'what did it learn from my ratings', 'refresh the picks for tonight'."
metadata:
  tags: [media, recommendations, taste-algorithm, feedback-loop, ratings]
---

# Media Taste Algorithm (self-learning loop)

## What this is, and is not

A portable framework for one loop:

**user rates items, the engine learns a taste vector, watchlists get scored.**

Concretely: verdicts (numeric ratings, "nahh", volunteered loves) land in a
ratings sidecar; a training pass derives the taste vector (per-lane weights,
penalties, demote lists, per-person blocks) from those ratings plus the media
library; a scoring pipeline ranks candidate titles into shelves and keeps
watchlists healthy. The learning is statistical (empirical-Bayes shrinkage
plus recency decay), not LLM output; an LLM is cosmetic at presentation time
only.

This port carries the loop, the data model, the training math, the
calibration protocols, and the operator contract. It is NOT a drop-in engine:
the internal reference implementation couples to a specific media server API
(similarity-graph affinity edges, a cloud watchlist service) and its runner
lives in the maintainer's private repo. Fill-in points used throughout:
`<MEDIA_SERVER>` (library + similarity edges), `<RATINGS_SIDECAR.json>`
(ratings store), `<SCORE_PIPELINE>` (ranking/picks runner), `<WATCHLIST>`
(watchlist store), `<PICKS_SCHEDULE>` (your scheduler).

## When to Use

Use whenever a person gives ratings or verdicts, asks to add titles to (or
review) the watchlist, asks what the system learned, asks to onboard a NEW
PERSON, asks for an anti-lane or watchlist-behavior change, or asks to tune
or re-run the scheduled picks run. Load this skill first for any of these.

## The feedback loop (run every time ratings/verdicts land)

1. INGEST: append the verdict batch to `<RATINGS_SIDECAR.json>`
   (chat_ratings / chat_watched / negative_signals / mid_band). Tag each
   verdict's `source` with its context (for example
   `chat-YYYY-MM-DD-<lane>`); one execution handles a whole batch, never a
   per-item hand edit.
2. TRAIN (automatic after ingest): the trainer reads the sidecar plus any
   platform rating export and derives `trained_params`: per-lane vote
   multipliers from average rating and sample size (3+ points = CONFIRMED,
   fewer shrunk by a confidence factor), negative-lane penalties, mid-band
   titles promoted into the hard-demote list, per-person blocks. The scoring
   pipeline consumes `trained_params` at runtime; ordinary weight changes
   need no code edits.
3. LEARN (manual, judgment layer only): write one dated lesson line per NEW
   pattern in `references/taste-lessons.md`. Weights and demotions never need
   lesson-driven edits; lessons record interpretation and candidates for
   structural changes to the trainer or scorer.
4. PERSIST: source-of-truth lists (watchlist, watched lists) refresh on the
   scheduled pipeline run; a manual pipeline run can push them early.
5. REPORT plainly: what was recorded, the trained weights now in force
   (lane/weight/points/status), what remains (for example "logged 5; a lane
   trained to 1.5x on 3 points; another lane provisional at 2 points until
   one more").

## Data model (the sidecar)

`data/sidecar.template.json` is the fill-in schema: ratings rows merged from
chat and platform stores, watched lists, negative signals, lanes map, anti
lanes, mid band, watchlist-only rows, co-view seeds, persona blocks plus
per-person rating lists, `trained_params` (derived, never hand-edited), and
the `config` block (all operator knobs).

Keep engine and data disjoint: code lives in the skill/pipeline directories,
learned state lives in data files (live sidecar plus its repo snapshot). A
code pull then cannot clobber learned state; resolve any data conflict by
re-copying the live sidecar in. `imdb_rated`-style platform export rows
(title, year, user_rating, date_rated, num_votes, runtime, directors) enrich
training; wire the reader in the same change as the fetcher.

## Training math (the taste vector)

- Lane weight: shrink toward the global mean,
  `m' = (n * lane_avg + k * global_mean) / (n + k)` with `k ~ 3`, then map
  through a multiplier curve. 3+ consistent points promote a lane; below 3 it
  stays UNCONFIRMED (recorded in taste-lessons.md, never hard-coded).
- Negative signals outrank affinity: a 4-6/10 or an explicit "nahh" demotes
  the whole adjacent lane. Titles staying mediocre after 2+ exposures hard
  demote via `mid_band`, regardless of graph affinity.
- Off-scale ratings become DNA-tier seeds: related titles inherit top weight;
  state the skew caveat when picks lean on a single DNA seed.
- Recency: continuous decay `w = 2^(-age_days / half_life)`, half_life 45-60
  days, floor 0.2, instead of step cliffs.
- Merge rule across stores: prefer MAX, never platform-wins. Platform
  ratings clamp (often to a 10) and hold stale values, so taking their lower
  number can erase a strong chat verdict; off-scale ratings live only in the
  sidecar.
- Watched-but-unrated titles enter lane statistics as weak positives
  (~0.25 weight), graded by watch velocity rather than a binary skip rule.
- Hand-tuning posture: constants are data-derived; change at most one weight
  mapping per scheduled cycle (single-variable tuning, the next verdict
  batch is the measurement). Hand-edit code only for structural changes (a
  new shelf, a new objective, a change to the training math itself).
- Offline acceptance gate for any ranking change: replay-style chronological
  leave-one-out evaluation, never a live code comparison. Design:
  `references/recommendation-architecture.md`.

## Scoring and shelves (watchlists get scored)

- Candidates come from an affinity pass over the library's similarity graph
  (co-rating or "similar to" edges; a local embedding cosine only as the
  zero-vote tie-breaker): recency-decayed, skip-handicapped,
  DNA-tier-boosted seed votes, with per-seed vote attribution and lane votes
  from the sidecar. Optional second hop expands from the strongest
  in-library hubs with discounted votes (`config.graph`).
- Weekly shelves, mutually exclusive after the first: BINGE (affinity +
  finishability + watchlist boost), a mood/late-night shelf (lane-seed votes
  boosted), CO-VIEW (shared seeds boosted), and one exploratory WILDCARD
  (single seed). Plus one edition per persona block (below). Cap picks per
  creator per shelf (MMR-style, 2 is a proven value) and give exactly one
  preference-stretch slot per run, preferring series over films.
- Auto-watchlist: with `config.auto_watchlist`, the pipeline adds its top
  external discovery candidates to `<WATCHLIST>` when they clear audience
  thresholds, records them in the sidecar, and re-reads the watchlist in the
  same run so the SSOT snapshot never lags a run behind the add.
- Suggestion cooldown: `config.suggestions_cooldown_weeks` (default 6)
  suppresses re-surfacing anything in `surfaced_history` inside the window,
  so picks rotate; fall back to unfiltered when the window would empty a
  shelf. Watchlist staleness decays with first-seen age.

## Operator quick reference (job, one action, code edits?)

| Ask | Action | Code edits? |
|---|---|---|
| Rate/verdict titles | append the batch to the sidecar (source-tagged); trainer fires | No |
| What did the algo learn / retrain | run the trainer | No |
| Kill/off a genre or pattern ("no more X") | sidecar `anti_lanes` (or `mid_band` for one title), then train | No |
| Watchlist behavior (auto-adds, cap, thresholds) | sidecar `config.auto_watchlist`, then train | No |
| Franchise caps, discovery genres | sidecar `config` keys, then train | No |
| Refresh the discovery pool | run the discovery fetcher, `--source all` (single transports: `--source <name>`) | No |
| Measure a ranking change offline | run the replay evaluator | No |
| Onboard a person | onboarding protocol below | No |
| "What should we watch" for any audience | run the front door with the resolved audience (`me` / `us` / `<person>`) | No |
| Run picks off-schedule | run `<SCORE_PIPELINE>` manually | No |
| New shelf type / new objective / training-math change | edit the pipeline + trainer as one batch | Only here |

Front door: one query script resolves the audience without code edits. `me`
(or no name), `us`/`together`, or any person's name fuzzy-matching
`config.persona_aliases` ({alias: persona_key}); add an alias when a name
fails. The front door prints with a presentation contract (what each shelf
means, why each title is there, what verdicts would improve).

## Zero-code-edit contract (an agent never edits the pipeline for operation)

Every operator surface is data in the sidecar `config` block, read at runtime
through `trained_params.config`:

- `franchise_keywords` + `max_per_franchise`: franchise diversity caps.
- `genre_tags_core`: which genres qualify for the discovery pool.
- `anti_lanes`: list of {name, match (genres), penalty, media filter,
  reason}; matched candidates score down and are tagged [ANTI-LANE <name>].
  Verdicts ("nahh", 4-6 ratings) become anti_lanes or mid_band rows, not
  script edits.
- `auto_watchlist`: {enabled, max_per_run, min_aud, min_aud_discovery}.
- `graph`: {hops, hop2_seeds, hop2_weight}; hops: 1 disables expansion.
- `seed_creators` (+40 class), `indie_studios` (+10),
  `filler_franchises` (-25): metadata signals, built-ins as fallbacks.
- `suggestions_cooldown_weeks`, `watchlist_decay_months`,
  `franchise_cross_run` {weeks, decay, floor}, `rewatch_ok` comfort-lane list.
- `training`: {shrink_k, recency_half_life_days, recency_floor,
  implicit_weight, skip_threshold}.
- `algorithm` feature flags; flippable per variant offline by the replay
  evaluator, and live via the sidecar.
- `persona_movie_keyword_block` plus per-persona exclusions and
  `keep_franchise_movies: true` opt-outs; `config.persona_*` is the pattern
  for the next hand-coded constant you find: config-side with a fallback
  default in code.

When you find a hand-coded constant inside the pipeline, move it to sidecar
`config` (or the persona's block) and read it with a built-in fallback in the
same edit, or the code-edit dependency returns. Exact key semantics and
defaults: `references/operator-config.md`. Legitimate code edits are only
structural: a new shelf type, a new objective, a change to the training math.

## Adding a person (per-person editions)

All data lives in the sidecar; no code changes.

1. PREFERRED: run the onboarding script with a spec JSON (name, lanes,
   genres, genre_penalty, negatives, content_flags, demographics, initial
   ratings); it writes the blocks, trains, and commits in one execution. A
   spec file is expected, not parsed chat edits.
2. Manual fallback: add `persona_shelves.<person>` and `<person>_ratings`.
   Their verdicts record with `who: <person>`, never as primary-user
   affinity; a dead title also joins the persona `negatives`, and content
   hard-nos join `content_flags.hard_no`.
3. SEED-THEN-RATE calibration when their ratings are thin: build a rated
   slate of 15-25 titles across their stated lanes plus at most one
   extension lane, excluding anything already rated by anyone in the setup;
   deliver as a grouped sheet with a one-clause reason per title; accept
   free-text answers; ALWAYS append an INVERSE section of off-taste probes
   (a hit means the model was too narrow, a miss is clean falsification);
   iterate until the lanes carry 2+ points, then train. Widening and
   lane-hunting mechanics: `references/niche-probe-menu.md`.
4. Train: per-person TV and movie lane weights, negatives, and the demo
   brief land in `trained_params.personas`. Person lane weights only bind
   when the lane's seed titles exist in the library; an off-library rating
   feeds the person's raw rating profile, not a lane weight, so prefer
   library-shaped seeds and record off-library ratings anyway.

Sidecar shape pitfalls for hand edits: persona `negatives` and top-level
`negative_signals` are LISTS; persona `notes` is a string; `coview_seeds`
is a FLAT list of titles (a dict-shaped write is silently skipped by its own
type guard). Inspect a field's type before the first append of a session.
Shared verdicts ("we both love X") go to `coview_seeds`, not just the persona
block, so the co-view shelf trains too. Time-gated lanes carry their gate
inside `demographics.lane_rules` and stay seasonal, never always-on.

## Discovery (where new candidates come from)

`references/discovery-sources.md`: verified free/OSS sources with per-source
access methods, transports in cost order (HTTP client, static extractor,
browser automation), a candidate-pool schema, and pacing rules. First
tranche: one media-metadata spine (TMDB class) + public rating datasets +
critic RSS + Wikipedia awards API + a free-tier aggregation API. A dead
source logs FETCH-FAIL and never fails a run; per-run item caps bound the
append.

## Presentation per audience

Persona editions present as their own list addressed to that person, never
blended into the main list. Each persona may carry its own register (warm,
neutral, technical); the operator's register applies to the operator's lists
and the engineer register to tuning reports. Affinity numbers and shelf
names stay off persona lists unless asked; a 30-second read per list, one
line per pick tying it to something that person liked.

## Conventions and pitfalls (distilled)

- Every data change ends with a training run; every code change ends with
  compile, repo/snapshot sync, and push. Compile is necessary, not
  sufficient: run the pipeline end-to-end once after structural edits and
  grep the output for ERROR before calling it verified (broad except blocks
  hide tracebacks).
- Tag lane context in each verdict's `source` at ingest; an untagged verdict
  trains affinity only, not the lane, and the lane starves.
- Keep the sidecar small: fold duplicates instead of appending; prune stale
  duplicate rows when touching the file.
- External-state readback rule: after anything mutates a remote (watchlist
  add), verify by reading the target back; a repo commit is not proof the
  write landed.
- A scheduler-owned auto-commit can make a manual commit report a clean tree
  right after a sidecar edit: that is the scheduler consuming it, not a lost
  write. Diff the snapshot's parsed content instead of retrying blindly.
- One canonical repo copy of the pipeline only; a second mirror goes stale
  within a day and can silently win a later copy in the wrong direction.
- Before adding a source or signal, inventory which fields the pipeline
  actually reads: owned-but-unread data is free signal, fetched-but-unwired
  fields are dead weight.

## Portability note (what stays installation-specific)

- The reference implementation couples to a media server's similarity-graph
  endpoint and a cloud watchlist service (Plex ecosystem is the proven
  case). Equivalents: any co-rating similarity signal, server
  recommendations, or embedding recall; any watchlist store with an API.
  Transient server timeouts are server load: probe, then rerun with a
  generous window; do not re-engineer the fetch layer.
- Delivery channel, scheduler wiring, channel IDs, persona demo data, and
  the rating store path are fill-ins per installation; none ship with this
  skill. Data stores are pointed at, never copied in.
