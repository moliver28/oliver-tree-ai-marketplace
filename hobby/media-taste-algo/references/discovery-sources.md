# Discovery sources (verified menu; re-verify per installation)

Three transports, in cost order: (1) an HTTP client (curl or any language's
HTTP stack) for JSON and RSS, (2) a static-HTML extraction tool where data is
embedded in the page, (3) a browser-automation tool (real browser session)
for JS-rendered or bot-walled pages. robots.txt and rate limits hold on all
three. Egress behavior differs per network: what 403s on a datacenter IP may
work from residential egress, and vice versa; verify before planning around
any source.

## Verified menu

- TMDB API + keyless daily ID export dumps (files.tmdb.org export pages).
  Free key, ~50 req/s, non-commercial license. /watch/providers is
  JustWatch-sourced and official: the clean availability path, since JustWatch
  itself blocks scraping. THE ENRICHMENT SPINE.
- IMDb public datasets (datasets.imdbws.com title.ratings.tsv.gz): keyless
  daily, mass ratings + vote counts. Cheapest scoring baseline.
- Critic RSS: outlet feeds (avclub.com/feed, polygon.com/rss/index.xml, film
  sections of major outlets via Google News RSS with a site: query). Zero-key
  buzz, weekly pull.
- Wikipedia Action API for award nominee tables (Oscars/Emmys/Globes/Critics
  Choice): keyless, parse wikitext defensively (see parser note below).
- Box Office Mojo /weekly/: extract the HTML table, map top titles to spine
  IDs (robots.txt permits personal use).
- Metacritic: scores live in the JS payload; static extraction of title pages
  unlocks the verdict language. Low cadence, cache aggressively (robots
  blocks crawler-class bots).
- Rotten Tomatoes: server-rendered HTML is extractable, but ToS bars
  automated collection at scale; keep cadence manual-ish. Numeric scores
  prefer OMDb.
- OMDb free tier (1000/day, free key): one call returns IMDb + RT +
  Metacritic ratings per title. Preferred enrichment over scraping RT/MC.
- Watchmode free dev tier (2500 credits/mo, 30-day cache rule, attribution
  required): availability pass on top-N only.
- Letterboxd: per-user RSS feeds work (letterboxd.com/<user>/rss/), public
  list pages extract; the API is closed to new keys, no bulk scraping.
  Social/niche curation signal.
- Trakt: API works with a free client_id (500 GET/5min, may need residential
  egress); web pages are a JS SPA and need browser automation.
- MUBI Notebook: the article index needs browser automation; article pages
  extract cleanly; RSS retired.
- MovieLens ml-25m (grouplens): static, ends ~2019. Recall baseline for cold
  lanes only.

## Known-blocked (verify before retrying)

- Reddit .json endpoints: often egress-blocked upstream.
- JustWatch: ToS bans scraping; use TMDB providers instead.
- Taste.io / Simkl / Reelgood: Cloudflare walls.
- Kaggle dumps: account-gated; check for mirrors.
- Paywalled critics (NYT, New Yorker): outlet RSS 200s but full reviews sit
  behind the meter; do not seed what you cannot read.

## Pool schema (discovery_pool.json)

rows: {title, year, media_type, source, genres, rating, watch_providers,
source_url, added_at}; dedupe on ids or (title, year); one spine-enrichment
pass normalizes external ids, genres, creators, providers after any fetcher
append. Bounded per run by `config.discovery.max_items_per_run`; dead sources
log FETCH-FAIL and never fail the run.

## Awards pages recipe

Two tiers: a small seasonal set (the current cycle's major ceremonies) and a
backlist catalog of historical winners-list pages for recall depth (all
probed 200 with wikitables before use). Wikipedia rate-limits back-to-back
Action API calls: pace ~2s/page with one longer backoff retry; (title, year)
dedupe lets reruns converge on tail pages. Parser lesson: ceremony pages use
section headers your parser may not expect (for example "Winners and
nominees", "In Competition", decade-header pages); allow-list section headers
widely (winner/nominee/award/film/television/competition + decade headers),
or annual pages zero out while their wikitext carries the tables. Prose-format
pages (no tables) are left out of the table parser and enter via their catalog
Best-Picture pages instead.

## Critic seeds (per-persona recipe)

Find critics whose documented taste overlaps a persona's lanes/genres/loves,
then use their review feeds and best-of lists as candidate seeds.

- Data shape: `config.critic_seeds` maps slug -> {name, outlet, feed_urls,
  genres_covered, match_personas, evidence_url, note}.
- Matching: rank the roster per persona by taste-vector overlap between the
  persona's lanes/genres/loves and the critic's genres_covered, minus
  conflict signals (known noes). Tie-break on documented year-end/all-time
  lists (evidence_url) and feed health (items in the last 14 days). Keep the
  top 1-2 per persona. A new critic needs an evidence_url plus a feed that
  returned 200 the same day before anyone subscribes it.
- Verified feed patterns (public info): outlet RSS (rogerebert.com/feed),
  Guardian per-author and film-section RSS (profile/<name>/rss + film/rss),
  site-filtered Google News queries for a byline, outlet-level feeds when no
  author feed exists, podcast feeds only when articles matter (usually they
  do not).
- Fetcher behavior: RSS 2.0 and Atom, namespace-tolerant; outlet suffixes and
  podcast/interview/recap markers stripped; the (YYYY) parenthetical becomes
  the row year; rows enter as source=critic-<slug> with genres_covered
  attached; per-feed cap rss_items_per_feed, age filter rss_max_age_days;
  dead feeds log FETCH-FAIL and never fail the run.
