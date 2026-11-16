# Recommendation architecture and offline evaluation

Design scale this was validated at: one user (or one household), tens to
hundreds of verdicts, ~10k library titles, 5-15 weekly picks. Everything
below is directional until the replay evaluator measures it on your data.

## Runtime shape (what the pick run computes)

- One similarity-affinity pass over recency-decayed, skip-handicapped,
  DNA-tier-boosted seeds; per-seed vote attribution plus lane votes from the
  sidecar lanes dict.
- A second small pass restricted to co-view seeds (the shared shelf).
- Optional second hop from the strongest in-library hubs
  (`config.graph`: {hops 2, hop2_seeds 20, hop2_weight 0.4}), or
  personalized PageRank (`ppr_enabled`) over a persisted similarity-edge
  cache: `p = alpha*x + (1-alpha)*W*p` from vote-weighted seeds, alpha
  ~0.15, 5-8 rounds.
- `build_shelves()` ranks four mutually exclusive rows (BINGE with
  finishability + watchlist boost, mood/late-night, CO-VIEW, one WILDCARD)
  with MMR-style creator caps, plus one shelf per `persona_shelves` entry.
  Movies stay a single affinity list.
- Efficiency shape: the show and movie libraries are fetched once per run
  and reused by every pass; the two mining passes run concurrently. Full
  runs are graph-endpoint bound, not CPU-bound; raising thread counts does
  not help. If runtime must shrink, cap seeds to the top ~300 by trained
  weight (trades long-tail lane coverage) and never drop the fetch dedupe.

## Shelf contract

Pick contract per run: 3-5 solo, 0-1 mood/late-night, 0-1 co-view, 0-1
wildcard, one preference-stretch slot preferring series over films. Max
2 picks per creator per shelf. Report verdicts per shelf, so a rejection
says which objective failed (personal fit, co-view fit, or lane fit).

## Offline acceptance gate (replay evaluation)

Never compare a live code change on its own. The replay harness:

1. Walk verdicts in chronological order; for each, rebuild seeds, lane
   weights, and demote lists from earlier verdicts only.
2. Hold the verdict's title out; record hit@5 / hit@15 / mean-rank.
3. Bootstrap a confidence interval over verdicts; report per-shelf
   breakdowns. Proxy metrics: intra-list diversity (1 - mean pairwise genre
   Jaccard), novelty (-log2 of normalized vote counts), catalog coverage.
4. Acceptance gate: beat the baseline by >1 bootstrap SE on hit@5 with no
   worse novelty or diversity.
5. Compare frozen replay runs only, never two live code states. Offline
   results mislead below ~50 points; live verdicts stay part of the loop.
   The similarity-edge cache is machine-local and large (gigabytes of
   growth are normal); cache-refresh, then rerun.

## Scored-verdict ingestion (verdict fields worth carrying)

`{title, rating, who, source, landed_ts}`; source carries the lane tag
(`chat-YYYY-MM-DD-<lane>`). Verdict-confidence extensions that trained
models grow into: exposure tier (watched-fresh vs from-memory), context
(late-night / co-view), and velocity effects. Whole-category verdicts
("X is not my style") become negatives WITH the nuance attached, never bare
exclusions.

## Prioritized improvement menu (dependency order)

1. **Replay harness first** (effort S; no direct quality gain, but the
   acceptance gate for everything else). Design above.
2. **Personalized PageRank over the persisted similarity-edge cache** (M):
   multi-path vote diffusion and per-candidate path evidence for pick
   explanations. Reference study: icaiit.org/proceedings/13th_ICAIIT_5/
   3-4-ICAIIT_2025_13(5).pdf (CF+PPR reranking beating either alone).
3. **Empirical-Bayes lane shrinkage + continuous exponential recency** (S,
   one combined pass): `m' = (n*lane_avg + k*global_mean)/(n+k)` with k~3
   fixes 1-2-point lanes swinging wide. Recency: `w = 2^(-age_days/half_life)`,
   half_life 45-60d, floor 0.2. References:
   chris-said.io/2017/05/03/empirical-bayes-for-multiple-sample-sizes;
   mdpi.com/2076-3417/12/13/6398 (exponential beat linear/power/logistic on
   rating data).

Also worth building (S effort, ride-along wins):

- Verdict-confidence fields (landed_ts, exposure tier, context) for velocity
  and time-of-week effects; split models stay observational until data
  grows.
- Watched-unrated as weak positives plus graded skip velocity; popularity-
  normalize implicit signals.
- Active-learning ask block in the weekly output: 1-2 unwatched candidates
  with maximal lane ambiguity, phrased as quick rateables (a reported
  offline-precision gain exists; a small-user online eval could not confirm
  it, so expect a modest gain: nature.com/articles/s41598-025-09708-2).
- Thompson sampling for slot allocation: Beta(alpha, beta) per shelf/slot;
  verdict >= 7 on a surfaced title is a success; sample per run to set slot
  counts. Modest gain at weekly verdict cadence (Microsoft Research 2016,
  thompson.pdf).
- Overview-embedding tie-breaker: embed overviews + titles once, local
  vector store, cosine-to-seeds used only when a candidate has zero graph
  votes; reuse vectors for the diversity metric. Tie-breaker, never the
  ranking primary.
- Watchlist staleness decay: `wl_boost = 2.0 * max(0.3, 2^(-months/4))`;
  surfaced-then-ignored titles decay harder.
- Cross-run franchise exposure: rolling record of (franchise, last-pick
  date) with a decay multiplier over the previous 2-4 runs; a per-run cap
  cannot hide a weeks-long pattern. Evidence found no nonlinear fatigue:
  light discount, not a fitted curve.
- Rewatch-eligibility flag: comfort-tier lanes only; serialized titles stay
  suppressed. Shelf-mix fix, not accuracy.

## Overkill list (do NOT build at this scale)

- LightGCN / GraphSAGE: embedding-based CF needs thousands of interactions;
  it degenerates to memorization below ~300 ratings. PageRank uses the same
  graph signal correctly at this scale.
- Matrix factorization (ALS/BPR): the user dimension is 1-3 people.
- Determinantal point-process reranking: 5-6-pick shelves already enforce
  diversity structurally; revisit only once an embedding store exists.
- Embeddings as the primary similarity source: graph edges + audience
  ratings dominate at ~10k titles.
- Deep session/sequential models: no clickstream at weekly cadence.
- Fitted franchise-fatigue curves: evidence inconclusive; a rolling window
  suffices.
- Real-time bandit serving / A-B infrastructure: one user, weekly; the
  replay evaluator substitutes.
- Full group-recommendation aggregation: one co-viewer; the co-view pass
  implements the useful subset.

## Caveats carried forward

- A hard creator cap is not true MMR; a similarity-term MMR over genre
  vectors is a near-free upgrade riding any change above.
- External vote-count joins key on (title, year); if mismatch exceeds a few
  percent, demote novelty to a soft metric.
- Verdict timestamps are a harness prerequisite: record them at ingest.
