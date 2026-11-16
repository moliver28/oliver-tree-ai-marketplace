---
version: 1
---

# Operator config reference (sidecar config keys, runtime rules)

Depth file for the zero-code-edit contract. Every key below lives in the
sidecar `config` block (or the named persona's block) and flows to the
pipeline through `trained_params.config` on the next training pass. Code
fallbacks exist for every key; the sidecar value wins.

## Metadata-signal operator lists

- `config.seed_creators`: creators/showrunners tied to 8-10 seeds. Matching a
  candidate's director or lead writer adds +40. Extending the list after a
  newly loved creator is a sidecar append, not a code edit.
- `config.indie_studios`: +10 per match (boutique-label class).
- `config.filler_franchises`: -25 per franchise-sequel collection match.
  Judgment-call exceptions stay in taste-lessons.md, not list entries.
- The pipeline binds all three to its metadata table after each training
  load; code built-ins are fallbacks only.

## Graph hopping

- `config.graph`: {hops, hop2_seeds, hop2_weight}. hops >= 2 expands the
  affinity pass a second hop from the top in-library hubs of hop 1, votes
  discounted (default 20 hubs at 0.4). hops: 1 disables. Second-hop seeds
  must be in-library items; external candidates cannot seed a hop. Hop-2
  adds runtime roughly proportional to hub count; shrink hop2_seeds to tune
  latency. Hop-2 picks explain via their hub lineage; per-seed vote
  attribution coarsens deliberately.

## External-candidate genre tagging

The metadata enrichment and the library miner both return genre tags, so
anti-lane penalties, the genre core-filter, and [ANTI-LANE] tags apply to
external (not-in-library) candidates too. If a candidate row shows no genre
info, the upstream source carried none; do not guess.

## Time-gated and proxy lanes

- Seasonal lanes (holiday/event romance etc.) carry their gate inside
  `demographics.lane_rules`: surface in the stated window, never off-season.
  They stay seeded but seasonal, never always-on, and the gate text is
  copy-able between personas.
- `lane_rules` proxy entries ("use the audience rating as the personal rating
  for lane X") let a loved genre family train without individual ratings;
  seed 1-2 exemplar titles so the shelf has anchors.

## Training and algorithm keys

- `config.training`: {shrink_k 3.0, recency_half_life_days 50,
  recency_floor 0.2, implicit_weight 0.25, skip_threshold 5}.
- `config.algorithm`: feature flags {eb_shrink_enabled,
  exponential_recency_enabled, implicit_positives_enabled,
  graded_skips_enabled, ppr_enabled, watchlist_decay_enabled,
  franchise_cross_run_enabled, thompson_slots_enabled, rewatch_fill_enabled};
  all default true. The replay evaluator flips these per variant; flipping
  any in the sidecar flips the live math on the next run.
- `config.graph` gains: {edge_cache (`<CACHE_DIR>/similar_edges.json`),
  cache_ttl_hours 168, ppr_alpha 0.15, ppr_iterations 8}. Personalized
  PageRank replaces the fixed 2-hop when ppr_enabled; hops/hop2_seeds/
  hop2_weight govern the fallback path and the hub cap reused by PPR.
- `config.slots.thompson`: {enabled true, prior_alpha 2, prior_beta 2,
  solo_extra_threshold 0.5, lane_threshold 0.45, wildcard_threshold 0.55}.
  Draws are seeded by ISO week; verdicts >= 7 on surfaced titles count as
  wins.
- `config.watchlist_decay_months` 4 (+ `watchlist_decay_floor` 0.3),
  `config.franchise_cross_run` {weeks 4, decay 0.6, floor 0.3},
  `config.rewatch_ok` (comfort-tier lane list), `config.ask` {enabled true,
  n 2}, `config.explain` true,
  `config.embeddings` {enabled false, bonus 0.5, endpoint, model, timeout_s}
  (tie-breaker off until a local backend exists).

## Enrichment and discovery keys

- `config.enrichment` / `config.discovery`: enrichment URLs, rating-dataset
  cache (cache_dir/cache_days/download_budget_sec), meta_refresh_days,
  max_items_per_run (300; caps one full fetch run's new rows, later sources
  carry to the next run), max_age_days (14), fetch_akas (off); discovery:
  enabled, tmdb_api_key/omdb_api_key (absent = graceful skip), export-date
  walkback, critic_rss_feeds + news queries, rss_max_age_days,
  rss_items_per_feed (also the critic-seed per-feed cap), awards_pages,
  awards_catalog_pages (historical winners pages for backlist recall depth),
  rating-baseline path, timeouts/retries.
- `config.discovery.source_bonus`: {source-prefix: bonus} applied to
  discovery-pool rows in ranking. Fallback when absent:
  {critic: config.discovery.critic_bonus (10), awards-catalog: 5, awards: 8};
  longest prefix wins; unknown sources score 0. Keep the numbers small:
  ranking nudges, not rescoring. EXPLAIN mode adds provenance lines to pool
  rows.
- `config.critic_seeds`: slug -> {name, outlet, feed_urls, genres_covered,
  match_personas, evidence_url, note}; consumed by the discoveries fetcher's
  critic-seeds source (RSS/Atom entry titles -> source=critic-<slug> pool
  rows; per-feed and age caps).

## Rotation and persona keys

- `config.suggestions_cooldown_weeks` (default 6, 0 disables): titles in the
  recorded `surfaced_history` inside the window are suppressed from all
  shelves and persona pools, so picks rotate. Fallback keeps rows unfiltered
  if the window would empty a shelf. `surfaced_history` records persona
  surfaces too.
- `config.persona_movie_keyword_block`: title-keyword exclusion list applied
  to every persona's movie pool. Per persona: `<per-persona> exclusions`
  extend it; `keep_franchise_movies: true` opts that person out entirely.
- `config.persona_aliases`: {alias: persona_key} for the front door's
  audience resolution.
- `config.persona_*`-style keys are the pattern for the next hand-coded
  constant you find: config-side with a fallback default in code.

## Runtime fetch contract (recap for debugging)

- Libraries are fetched once per run and reused by every pass. A single
  "server unreachable (timeout)" is server load: probe the endpoint, then
  rerun in the background with a generous window instead of re-engineering
  the fetch layer.
- Compile is necessary, not sufficient: broad exception handlers convert
  order-of-definition and missing-argument bugs into one anonymous line. Run
  the pipeline end-to-end and grep for ERROR: before calling a structural
  change verified.
