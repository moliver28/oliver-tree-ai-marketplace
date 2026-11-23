---
description: "Turn a finished study into a slide deck shaped for one audience: script-computed slide caps, a story arc over the research questions, a persona lens check, and a geometry-linted generator; nothing renders without the user."
argument-hint: "<KEY> [--audience=leadership|design|product|research|org] [--tier=lite|standard|strategic] [--dry-run] [--refresh-persona=<name>] [--altitude=brief|standard|deep] [--render-only]"
---

Build the deck for one study: scripts compute the slide cap, story
skeleton, source counts, and geometry lint; you fill the text slots.
Generated from an outline file, never hand-edited `.pptx`, never raster
images.

## Safety rules (they override everything below)

1. **`--dry-run` writes no file and calls no write tool.** Show plan, beats, outline under `DRY RUN - nothing written`; stop before phase 5.
2. **The persona cache lives in `<state_dir>`, never the plugin source tree.** Cached `pe_framing_prompt` values go to `<state_dir>/deck-persona-cache.json` via `deck_helpers.py write-persona-field --cache-dir`; never write persona fields into `references/` at runtime.
3. **The gitignore gate passes before generation.** `scripts/gitignore_gate.py assert-ignored` on the deliverable path plus one path per `workspace.gitignored_paths` entry; exit 3 stops the run before the generator writes anything.
4. **The deck is regenerated, never edited.** A change means: edit the outline, re-lint, regenerate.
5. **The Critic panel member is mandatory.** When `deck.critic_agent` (default `hcd-researcher`) has no agent file under `agents/`, stop before the panel and say which agent is missing.
6. **Verdict labels and evidence numbers are copied verbatim** from `report_helpers.py` output.
7. **An optional Drive upload happens only after an explicit `go`**, under the finish rules.

## Inputs

Grounding: consult registered sources in `references/sources/` (for this command: R-01 metrics, R-04 COREQ, R-20 scoring, R-21 HEART); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

`$ARGUMENTS` is `<KEY>` with any of: `--audience=leadership|design|product|research|org` (no flag: show the 1-5 persona menu from `list-personas` and ask), `--tier=lite|standard|strategic` (default: computed in phase 1), `--dry-run`, `--refresh-persona=<name>` (drop that persona's cached `pe_framing_prompt`, regenerate in phase 4), `--altitude=brief|standard|deep` (maps through `altitude --level` when `--tier` absent), `--render-only` (skip phases 1-4; render the existing outline through phase 5).

Every gate uses `go`, `edit`, `cancel` -- except the phase 4 lens check: `apply`, `edit`, `skip`.

## Setup (every run)

Load config once (`python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`). Note `paths.research_root`, `paths.state_dir`, `deck.personas_file`, `deck.generator_path`, `deck.critic_agent`, `report.verdict_threshold`, `comments.footer`, `tracker.ticket_regex`. Hardcode nothing.

Generator resolution: `deck.generator_path` empty means the shipped `scripts/deck_render.py`; non-empty means the user's own generator (same contract: outline JSON in, `.pptx` out, geometry lint on overflow/overlap, no raster images).

## Phases

| Phase | Steps |
|---|---|
| 0. Resolve | Find the workspace: `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`. Require at least one `interviews/*-summary.md` and a non-empty `analysis/codes.md` or `analysis/themes.md` (else stop and point to `debrief` - there is nothing to present yet). Load the persona: `python "${CLAUDE_PLUGIN_ROOT}/references/deck_helpers.py" load-persona --persona <name> --tier <tier> --cache-dir <state_dir>`. With `--refresh-persona=<name>`, first run `write-persona-field --persona <name> --field pe_framing_prompt --value null --cache-dir <state_dir>` to drop the stale prompt. |
| 1. Synthesize | Compute the tier: `report_helpers.py scope-tier --type "<research type>" --investment "<investment>" --pod-names "<groups>"` (an explicit `--tier` flag wins and says so; `--altitude` maps through `altitude --level` when no `--tier`). Reuse `<workspace>/.sessions/gather-brief-<KEY>-<date>.md` when it exists; otherwise collect a brief from the workspace analysis files and summaries into `<workspace>/deck/deck-collect-brief-<KEY>-<date>.md`. Run `report_helpers.py evidence-weight --workspace <workspace>` — its JSON already carries `hypothesis_verdicts` and `assumption_verdicts`; read the verdicts from that output (a separate `verdict` run duplicates it). Run the rater panel in parallel (below): Support, Challenge, Critic (mandatory; stop if the agent file is missing), and Strategic (strategic tier only). Each returns the fixed JSON block. Merge the panel output into `/tmp/uxr-synthesis-<KEY>.md` with one `RQ{N}` block per research question. Run `report_helpers.py check-citations --draft-file <synthesis> --sources-dir <workspace>/sources` and dispatch `hcd-researcher` on the synthesis (fold in or record a one-line decline). A missing citation or an RQ block with zero evidence stops: `fix` (repair and re-check), `continue with gaps flagged` (mark each gap `GAP: <RQ>` in the synthesis and keep going), or `cancel`. Gate. |
| 1.5 Arc | Write `<workspace>/deck/rqs.json` as `[{"id": "RQ1", "topic": ..., "question": ...}]` from the synthesis blocks. Run `deck_helpers.py beat-skeleton --rqs-file <workspace>/deck/rqs.json --persona <persona>`. Assign each RQ to exactly one beat (`setup`, `conflict`, `resolution`, `implication`) and write a declarative title and a one-line connector per assigned beat into `<workspace>/deck/beats.json`. Gate. `validate-beats --beats-file ... --rqs-file ...` must pass (exit 1: fix the assignments and re-run). |
| 2. Story | Run `deck_helpers.py scaffold --beats-file <workspace>/deck/beats.json --rqs-file <workspace>/deck/rqs.json --persona <persona> --tier <tier> --key <KEY> --audience <audience> --title "<deck title>" --date <today>`, writing the printed outline to `<workspace>/deck/deck-outline-<KEY>.json`. Fill only the text slots: titles, connectors, bullets, quotes, stats, columns, captions, `sources: [<slug>]` per finding (as `[S:slug]` slugs), and optional `visual` specs (the 20 kinds in `deck_helpers.py`, validated shapes; a bad spec renders as a labeled placeholder). Quote text
is copied verbatim from the session summaries' speaker-labeled quotes -
never paraphrased. Never add or remove structural slides the scaffold defines without the user's edit note. Gate. |
| 3. Iterate | Run `deck_helpers.py slide-plan --persona <persona> --tier <tier>` and order the outline slides by the persona `slide_priority_order` (the cover stays first, `end` stays last, each slide keeps its `category`). This is where the deck earns its cap: trim or merge slides that do not carry their category's point. Gate. |
| 4. Lens check | Read the persona's cached `pe_framing_prompt` from `load-persona` output. When it is null, generate one - `role` (who critiques for this audience), `attack` (the one question this audience always asks), `checklist` (4 to 6 pass/fail items) - and cache it: `deck_helpers.py write-persona-field --persona <persona> --field pe_framing_prompt --value '<json>' --cache-dir <state_dir>`. Run `deck_helpers.py lint-outline --outline <workspace>/deck/deck-outline-<KEY>.json --persona <persona> --tier <tier>` and print the outline verbatim. Add only `[move]`, `[trim]`, `[add]`, `[flag]`, `[ok]` tags per slide, judged through the persona lens. PASS only when every tag is `[ok]`; otherwise gate with `apply` (make the moves and trims, re-lint), `edit` (the user dictates changes), or `skip` (proceed, recording each `[flag]`). |
| 5. Generate | Run `deck_helpers.py deck-filename --audience <audience> --date <today> --key <KEY>`. Run the gitignore gate on `<workspace>/deliverables/<filename>`; exit 3 means offer to add `deck/` and `deliverables/*.pptx` to the workspace `.gitignore` and wait for `go`. Run `lint-outline` again; any FAIL line is fixed before generating. Strategic tier: run `deck_helpers.py finding-sources --synthesis /tmp/uxr-synthesis-<KEY>.md` and append exactly `single source; treat as preliminary` to every finding with fewer than 2 sources (set `note` on the finding slide). Generate: `python <generator> render <workspace>/deck/deck-outline-<KEY>.json <workspace>/deliverables/<filename>` (shipped generator: `scripts/deck_render.py`). Fix every geometry `FAIL` line by editing the outline and regenerating - at most 3 passes, then stop and show the failures. Optional visual pass: convert to PDF (only when a converter exists), one vision critic pass, at most 3 loops, never editing the `.pptx` directly. Optional Drive upload under the finish rules, on `go` only. Tell the user in one line that the optional visual pass (PDF plus one vision critic pass) is available and skipped on request, and that the Drive upload waits for an explicit `go`. `--render-only` starts here with the existing outline; when an outline from an earlier run already exists, say in one line that re-running with `--render-only` skips phases 1 to 4. |

## Rater panel (phase 1; one fixed JSON block each)

Dispatch the panel members in one parallel batch. Support and Challenge
are model passes over the synthesis; Critic is a dispatch of
`deck.critic_agent` (default `hcd-researcher`); Strategic is a model
pass and runs at strategic tier only. Each returns exactly:

```json
{"stance": "support|challenge|critic|strategic", "notes": [{"rq": "RQ1", "note": "...", "confidence": "high|medium|low"}], "summary": "one line"}
```

Support argues the evidence for each RQ; Challenge argues the
counter-evidence and the weak links; Critic applies the HCD review;
Strategic names the business risk and the opportunity cost. The
synthesis merge keeps every note line attributable to its stance.

The Critic dispatch first runs `python "${CLAUDE_PLUGIN_ROOT}/scripts/researcher_state.py" digest --key <KEY>`; when it prints reviews, paste its output into the dispatch input under a `Prior reviews:` line and add the label line `Artifact kind: deck`; `no prior reviews` continues unchanged. The Critic dispatch input opens with the verbatim ask from the spec: `Original ask (<ask_source date>): <ask_verbatim>`; a pre-ask spec says `Original ask: not recorded (pre-ask spec)` in one line and continues.

## Personas (`deck.personas_file`; one file shared with the report reader)

| Persona | Base slide cap | Priority order | Methodology | Arc order |
|---|---|---|---|---|
| leadership | 5 | exec_summary, strategy_framing, visuals | appendix | implication, setup, conflict, resolution |
| design | 8 | visuals, implications, strategy_framing | inline_brief | default |
| product | 7 | strategy_framing, next_steps, exec_summary | appendix | default |
| research | 12 | methodology_framing, findings_depth, visuals | full_section | default |
| org | 10 | strategy_framing, exec_summary, visuals | inline_brief | default |

Cap = `max(3, round(base * factor))` with factor lite 0.6, standard
1.0, strategic 1.5. The cap counts content slides only (`finding`,
`exec-summary`, `stats`, `three-col`, `quote`, `bullets`, `content`,
`diagram`); cover, agenda, question, recommendations, appendix, and end
slides never count. `slide-plan` prints the computed card.

## Scripts

| Script | Contract |
|---|---|
| `references/deck_helpers.py load-persona --persona <n> [--tier <t>] [--cache-dir <state_dir>] [--file <personas.json>]` | Persona JSON; cached fields merge over the file; `--tier` adds `cap` and `factor`. |
| `references/deck_helpers.py list-personas` | `[{"name", "label"}]`; the no-flag audience menu. |
| `references/deck_helpers.py validate-personas` | `ok personas (...)` or `FAIL <problem>` lines; exit 1 invalid. |
| `references/deck_helpers.py slide-plan --persona <n> --tier <t>` | `{persona, tier, factor, base_cap, cap, content_kinds, slide_priority_order, arc_order, methodology}`. |
| `references/deck_helpers.py beat-skeleton --rqs-file <f> [--arc-order "<a,b,c,d>"] [--persona <n>]` | The four beat shells in arc order, `rq_ids` empty. |
| `references/deck_helpers.py validate-beats --beats-file <f> --rqs-file <f>` | `[unknown]`/`[dup]`/`[orphan]` block (exit 1); `[empty]` never blocks. |
| `references/deck_helpers.py scaffold --beats-file <f> --rqs-file <f> [--persona <n>] [--tier <t>] [--key <KEY>] [--audience <a>] [--title <t>] [--date <d>]` | The outline JSON: cover, agenda, exec summary, background, per non-empty beat a section slide plus per RQ a question slide and a finding slide, recommendations, appendices (persona methodology `appendix` or `full_section`), end. |
| `references/deck_helpers.py lint-outline --outline <f> [--persona <n>] [--tier <t>]` | `ok <check>` / `FAIL <check>: <detail>` lines; exit 1 on any FAIL. |
| `references/deck_helpers.py write-persona-field --persona <n> --field <k> --value <json> (--file <personas.json> \| --cache-dir <state_dir>)` | One persona field into the file or the state-dir cache; exactly one target. |
| `references/deck_helpers.py deck-filename --audience <a> --date <d> --key <KEY>` | `deck-<audience>-<date>-<key>.pptx`, lowercase. |
| `references/deck_helpers.py finding-sources --synthesis <f> [--min-sources 2]` | `[{id, sources, count, preliminary}]` per RQ block. |
| `<deck.generator_path> render <outline.json> <out.pptx>` | Outline in, `.pptx` out; geometry `FAIL` lines mean nothing was written; shipped default `scripts/deck_render.py` (also `lint <outline.json>`). |
| `scripts/gitignore_gate.py assert-ignored --repo <workspace> deliverables/<filename>` | Exit 3 blocks the generation; the gate never edits `.gitignore` itself. |
| `references/report_helpers.py scope-tier \| evidence-weight \| verdict \| check-citations \| altitude` | The issue 03 computations, used verbatim. |

## Failure table (stop cleanly, never advance on bad state)

| State | Action |
|---|---|
| No workspace or no summaries | Point to `debrief`, stop |
| `deck.critic_agent` agent file missing | Name the missing agent, stop before the panel |
| Missing citation or zero-evidence RQ in the synthesis | `fix` / `continue with gaps flagged` / `cancel` |
| `validate-beats` exit 1 | Fix the assignments, re-run; never scaffold on a block |
| `lint-outline` FAIL after 3 fix passes | Show the failures, stop, no file written |
| Generator geometry FAIL after 3 passes | Show the `FAIL` lines, stop, no file written |
| Gitignore gate exit 3 | Offer the `.gitignore` addition, wait for `go` |
| Generator exits 2 (python-pptx missing) | Print the install hint verbatim, stop |

## Rules of last resort

- Never write any file before its gate passes in this run; `--dry-run`
  writes nothing anywhere (including `/tmp` synthesis files - draft
  them in the conversation instead).
- Never claim a live Drive, tracker, or chat result the run did not
  produce.
- The `.pptx` is regenerated from the outline, never edited; raster
  images are never generated.
- The deck may quote an up-level ask from the spec's `ask_uplevels`; the
  original ask (`ask_verbatim`) is never replaced or reworded.
- Two failed attempts on any problem: search the web before trying
  again.
