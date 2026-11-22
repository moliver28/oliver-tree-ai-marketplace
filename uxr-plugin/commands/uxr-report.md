---
description: "Turn a finished study into a report sized to its stakes: script-computed tier, verdicts, evidence counts, and citation checks; optional HTML render through a mechanical check and two reviewer agents; optional publish to the gallery. Every stakeholder message is a draft."
argument-hint: "<KEY> [--audience=internal|product-team|leadership] [--tier=lite|standard|strategic] [--dry-run] [--video] [--altitude=brief|standard|deep] [--render-only] [--format=html] [--stakeholder-role=<role>]"
---

Scripts compute the tier, verdicts, evidence counts, and citation checks;
you write the narrative on that skeleton. Nothing sends without the user.

## Safety rules (they override everything below)

1. **Every external action is a draft first.** Chat/mail draft tools only; a mail draft body carries no URL when the mail tool rewrites links. Nothing sends without the user's reply.
2. **A calendar agenda update appends one line after `go`.** Never change a meeting's time or attendees.
3. **A revenue lookup message is drafted and waits for `go`.**
4. **The gitignore gate passes before any deliverable write.** Run `scripts/gitignore_gate.py assert-ignored` on the `.sessions/gather-brief-*.md` path plus one path per `workspace.gitignored_paths` entry (config adds to the hardcoded path); exit 3 stops the whole run before any file is written.
5. **Publish is never automatic.** Gallery publish runs only on the user's explicit `go`; never pass `--force` on the user's behalf.
6. **`--dry-run` writes no file and calls no write tool.** Show every draft and computed number under a `DRY RUN - nothing written` heading; stop before phase 5.
7. **Verdict labels are copied verbatim from the script.** Never reword, soften, or upgrade a computed verdict.

## Inputs

`$ARGUMENTS` is `<KEY>` with any of:
`--audience=internal|product-team|leadership` (default `internal`),
`--tier=lite|standard|strategic` (default: computed by `scope-tier`),
`--dry-run`, `--video`, `--altitude=brief|standard|deep`,
`--render-only`, `--format=html`, `--stakeholder-role=<role>`
(one of PD, EM, PM, Leadership; one dispatch per role).

Every gate in this command uses the same words: `go`, `edit`,
`cancel`.

## Setup (every run)

Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `paths.research_root`, `paths.state_dir`, `routing.group_to_channels`, `routing.group_to_area`, `report.verdict_threshold`, `report.multi_group_bump`, `report.tier_matrix`, `publish.repo`, `publish.pages_url`, `ssot.finished_title_pattern`, `comments.footer`, and `tracker.ticket_regex`.

## Phases

| Phase | Steps |
|---|---|
| 0. Resolve | Find the workspace: `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`. Require at least one `interviews/*-summary.md` and a non-empty `analysis/codes.md` or `analysis/themes.md`. Else stop and point to `debrief` - there is nothing to report yet. Then run the checklist gate - `python "${CLAUDE_PLUGIN_ROOT}/lib/checklist_gate.py" check --type <qual-interviews when the method is an interview, quant-surveys for a survey> --spec <state_dir>/specs/<KEY>.spec.json --workspace <workspace>` - and print its missing list as record-gap lines: warn and continue, never block (`checklists.enforcement: record`; in `block` mode the phase 5 write stops when more than half the items lack evidence). |
| 1. Scope | Read the ticket (summary, body, fields via `get_item` in `references/tracker.md`) and the workspace `00-overview.md` in parallel. Run `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" scope-tier --type "<research type>" --investment "<investment>" --pod-names "<raw group string>"`. Show the scope card: type, investment, groups, computed tier (an explicit `--tier` flag overrides, and says so). The scope card opens with the verbatim ask line `Original ask (<ask_source date>): <ask_verbatim>` from the spec (a pre-ask spec says `Original ask: not recorded (pre-ask spec)` in one line). Gate. |
| 2. Gather | In one parallel batch: (A) the workspace analysis files (`analysis/codes.md`, `analysis/themes.md`, all summaries); (B) prior finished studies: tracker search (limit 8), Drive (past 18 months, limit 12), wiki (past 180 days, limit 8); (C) the feedback store, chat search in the study's channels, and the next 21 days of calendar. A failed source logs one line `<Tool>: unavailable (skipped)` and never blocks. Compress B and C into `<workspace>/.sessions/gather-brief-<KEY>-<date>.md` - the brief carries names, counts, and verdicts, not raw search JSON. Gate. |
| 3. Synthesize | Run `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" evidence-weight --workspace <workspace>`, then `verdict` on the tallies (or read them from the evidence-weight output). It warns when fewer than half of the sessions have an alignment block - show that warning and keep going. Copy verdict labels verbatim into the draft. Map each finding to its source as `[S:slug]`; a claim with no source is marked `UNCITED: <claim>` on its own line. Run the bias check: `codebook-codes --file <workspace>/analysis/codes.md` then `classify-themes --codes-file ... --themes-file ...`. Show the synthesis table (finding, verdict, sources) and the bias-check table. Gate. |
| 4. Draft | This is the run's FIRST model call: write the narrative by the tier spec below, into `deliverables/<filename draft>` shape (front matter below), ending the draft with one `Headline:` line (one sentence, computed numbers and verdict labels verbatim) that phase 6 reuses. Run `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" word-count-sections --file <draft>`; mark a section `OVER` at more than 20% above its limit; loop (rewrite the over sections) until none is over. Then the mandatory HCD gate (below): one checklist-scoped call that judges only the qualitative residual after the deterministic fact-check; fold in, or record a one-line decline; re-invoke only on a `p0` verdict. Optional: dispatch `stakeholder-reviewer` once per requested `--stakeholder-role`. Optional: run `cross-study --current-file <draft> --priors-glob "<the prior reports from phase 2>"` and show its `{confirms, reverses, new}` counts next to the draft. When no `--stakeholder-role` was requested, say in one line that a per-role stakeholder review is available by re-running with `--stakeholder-role=<role>`. |
| 5. Create | Run `report-filename --key <KEY> --audience <audience> --date <today>`. Run `check-citations --draft-file <draft> --sources-dir <workspace>/sources`; any missing slug returns to phase 4 (fix the citation or mark the claim `UNCITED`). Run the gitignore gate; then write `deliverables/<filename>` with the front matter below. Appendix A (strategic tier): the revenue lookup message is drafted and waits for `go`; write `arr-parse --reply-file <reply>` output to `<state_dir>/arr-<KEY>.json`; build the appendix with `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" render-appendix --key <workspace>/interviews/participant-key.md --arr-file <state_dir>/arr-<KEY>.json`. With `--format=html`: render, check, and run the review loop below. `--render-only` stops here. Optional, after an explicit `go`: publish (below), Drive upload under the finish rules, and the output link field update. Tell the user in one line that gallery publish, the Drive upload, and the output-link update are available on an explicit `go`, each optional. When `--format=html` was not passed, say in one line that the HTML render with its mechanical check and review loop is available by re-running with `--format=html`. |
| 6. Distribute | Drafts only, assembled mechanically from the phase 4 `Headline:` line (zero model calls in this phase), then render the drafts - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render distribution --set "tier=<tier>" --set "date=<today>" --set "filename=<filename>" --set "headline=<sentence>" --set "next_line=<one deterministic next step from the draft>" --set "prelim=<`. Single session; treat as preliminary.` (leading period-space included) when a finding has fewer than 2 sources, else empty; the render skips the clause when the bound headline already carries it>" --set "footer=<comments.footer with {display_name} replaced>" --set "channels=<channels --pod <group> --tier <tier>>" --set "video=<requested or none>"` - and print its output as the drafts (tier variants and the chat/mail/agenda/video fragments fire per tier). Without `--video`, say in one line that the video script draft is available by re-running with `--video`. Nothing sends without the user. Show every draft and wait. |

## Deliverable front matter (the renderer and validator parse it)

```yaml
---
slug: report-<audience>-<date>-<key>
ticket: <KEY>
tier: <lite|standard|strategic>
audience: <audience>
date: <YYYY-MM-DD>
hypotheses:
  - id: <H-id>
    label: "<label>"
    verdict: <verdict>
sources_cited: [<slug>, ...]
---
```

## Narrative size (words)

| Tier | Sections |
|---|---|
| Lite (~400) | Key Findings 250-300 (3 to 5 bullets, 1 citation each), Implications 80-100, Next Steps 40-60 |
| Standard (~1000) | Executive Summary 60-80, Key Decision Framing 80-100, Key Findings 400-500 (4 to 7), Implications 150-200, Next Steps 80-100 |
| Strategic (~2000) | Executive Summary 150-200, Key Decision 80-100, Background 150-200, Methodology 100-120, Key Findings 700-900 (5 to 8, a verdict each, 2 sources each or the line "single source; treat as preliminary"), Implications 200-250, Strategic Recommendations 200-250, Appendices A (participants), B (method detail), C (source registry) |

Label analyst inference exactly `Analyst inference` with no slug. Describe diagrams in words;
never generate images. `--altitude=brief` writes the lite shape,
`standard` the standard shape, `deep` the strategic shape (map it with
`altitude --level`). The methodology section prints the original ask
first - `Original ask (<ask_source date>): <ask_verbatim>` from the spec;
a draft may quote an up-level after it, and up-levels live only in the
spec's `ask_uplevels`, never in `ask_verbatim`.

## The HCD gate (phase 4; one call per run)

Render the dispatch - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render hcd-gate --set "artifact=<the draft>" --set "artifact_kind=report" --set "factcheck=<the settled gates JSON: check-citations, word-count-sections, evidence-weight verdicts>"` - and dispatch it to `hcd-researcher` (Task tool, `subagent_type: hcd-researcher`). The deterministic fact-check already settled numbers, citations, and stance vocabulary; the agent judges only the qualitative residual (claim-evidence trace, method/RQ alignment, stance justification) and ends with a checklist-scoped `verdict: {"result": "pass"|"p0", "p0": [...]}` line. Fold every finding in, or record a one-line decline. Print the agent's Summary, Risks, and What to change verbatim. Re-invoke only on a `p0` verdict, after the fix.

Before the dispatch, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/researcher_state.py" digest --key <KEY>` and, when it prints reviews, paste its output into the dispatch input's study context under a `Prior reviews:` line; `no prior reviews` continues unchanged. The dispatch input's study context opens with the verbatim ask from the spec: `Original ask (<ask_source date>): <ask_verbatim>`; a pre-ask spec says `Original ask: not recorded (pre-ask spec)` in one line and continues.

## Verdicts (from `report.verdict_threshold`, default 0.60)

The denominator is the count for that one hypothesis or assumption
label. Hypothesis: Supports share at or above 0.60 is `Supported`;
Challenges share at or above 0.60 is `Not supported`; other evidence
without a dominant side is `Partially supported`; no evidence is
`Insufficient evidence`. Assumption: `Holds`, `Breaks`, `Untested`,
`Insufficient evidence` by the same rule. Copy the labels verbatim.

## HTML render, check, and review loop

1. Render: `python "${CLAUDE_PLUGIN_ROOT}/scripts/report_html.py" render <deliverable.md> <deliverable-dir>/<slug>.html`. Self-contained, byte-identical on two runs, `<` escaped before conversion (participant quotes cannot inject script).
2. Check: `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_report_html.py" check <html> --deliverable=<deliverable.md>`. Any `WARN` line exits 1 - fix the Markdown or the render and repeat before review.
3. Gate and closure (the review loop is one HCD gate now, not parallel dispatches): the phase 4 gate's findings arrive checklist-scoped with a category. Route each mechanically - `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" route-finding --category "<category>"` - to the renderer (re-render from the fixed Markdown) or the Markdown (fix the text); re-check with `validate_report_html.py`, re-run the word-count and citation gates, and re-invoke the gate only on a `p0` verdict. Write `deliverables/report-review-<date>-<KEY>.md` with each finding marked Resolved or Deferred and a final `PASS` or `FAIL` line (the deterministic closure re-check). A FAIL is a valid result - report it, do not force a pass.

## Publish (optional, only on the user's explicit `go`)

`python "${CLAUDE_PLUGIN_ROOT}/scripts/publish_artifact.py" publish <html> --slug <slug> --ticket <KEY> --pod "<area>" --tier <tier> --audience <audience> --date <date> --title "<finish-rule title>" --repo-path <publish.repo> --pages-url <publish.pages_url>`

Refuses a dirty or non-`main` repo and a slug folder with foreign files
(never `--force` for the user); writes `<slug>/index.html`, upserts
`manifest.json`, rebuilds the gallery, updates the README list between
markers, commits, pushes, prints the page URL. Finish rules first:
`pod-to-area --pod <group>` for the area and `validate-finish-title --title "<title>" --pod "<area>"` for the title (shape
`<Product Area> <What it was> <YYYY-MM>`). The Drive upload files the
deliverable under `ssot.finished_artifacts_folder_id` in a product-area
subfolder of the same pattern; then update the ticket's output link field.

## Scripts

| Script | Contract |
|---|---|
| `references/report_helpers.py scope-tier --type <type> --investment <level> [--pod-names "<groups>"] [--pod-count <n>]` | Prints `lite`, `standard`, or `strategic`; two or more groups bump one step unless investment is `0`. |
| `references/report_helpers.py evidence-weight --workspace <dir>` | `{rq_coverage, hypothesis_verdicts, assumption_verdicts, sessions_tallied, sessions_with_alignment_block}`; warns under stderr when fewer than half the sessions have an alignment block. |
| `references/report_helpers.py verdict [--json-file <f>] [--kind hypothesis\|assumption]` | `{label: verdict}` from stance tallies. |
| `references/report_helpers.py word-count-sections --file <draft>` | `{H2 title: words}`; a section is OVER at more than 20% above its limit. |
| `references/report_helpers.py check-citations --draft-file <draft> --sources-dir <dir>` | `[{slug, found}]`, missing slugs first; a missing slug returns to phase 4. |
| `references/report_helpers.py codebook-codes --file <codes.md>` / `classify-themes --codes-file <c> --themes-file <t>` | Bias-check inputs and the `Theme \| Origin \| RQs supporting \| Fragile?` table with the `Researcher-framed: N. Emergent: N. Single-RQ conclusions: <ids>.` line. |
| `references/report_helpers.py channels --pod <group> --tier <tier>` | Chat channel names for the distribution drafts from `routing.group_to_channels`. |
| `references/report_helpers.py cross-study --current-file <report.md> --priors-glob "<prior reports>"` | `{confirms, reverses, new}` against prior reports' front matter. |
| `references/report_helpers.py report-filename --key <KEY> --audience <aud> --date <date>` | `report-<aud>-<date>-<key>.md`, lowercase. |
| `references/report_helpers.py altitude --level brief\|standard\|deep` | The tier the altitude maps to. |
| `references/report_helpers.py pod-to-area --pod <group>` / `validate-finish-title --title "<t>" --pod "<area>"` | Finish rules for the Drive upload and the publish title. |
| `references/report_helpers.py arr-parse --reply-file <reply>` | `{account: "$1.2M"}`; the command writes it to `<state_dir>/arr-<KEY>.json`, which `render-appendix --arr-file` reads. |
| `scripts/report_html.py render <md> <html>` | The self-contained render. |
| `scripts/validate_report_html.py check <html> --deliverable=<md>` | The mechanical check; exit 1 on any WARN. |
| `scripts/publish_artifact.py publish <html> --slug ... --ticket ... --pod ... --tier ... --audience ... --date ... --title ... --repo-path ... --pages-url ... [--force]` | The gallery publish; refuses a dirty tree or non-main branch, makes no commit then. |
| `scripts/gitignore_gate.py assert-ignored --repo <workspace> .sessions/gather-brief-<KEY>-<date>.md` | The gate before any deliverable write; exit 3 stops. |

## Failure table (stop cleanly, never advance on bad state)

| State | Action |
|---|---|
| No workspace | Point to `init`, stop |
| No summaries or no non-empty analysis file | Point to `debrief`, stop |
| Under half the summaries have an alignment block | Show the warning, continue with what parses |
| A missing citation slug | Return to phase 4; fix or mark `UNCITED: <claim>` |
| word-count sections still OVER after two passes | Show the counts, ask `go` / `edit` / `cancel` |
| Render check exits 1 | Fix and re-render before any review dispatch |
| Review loop FAIL | Write the review file with FAIL and report it; a FAIL is a valid result |
| Publish refused (dirty, not main, foreign files) | Print the refusal verbatim; never retry with `--force` |

## Rules of last resort

- Never write any file before the gitignore gate passes in this run.
- Never claim a live tracker, chat, calendar, or Drive result the run
  did not produce; a skipped source is one line in the gather brief.
- The ticket gets a comment draft only; the body, status, and fields
  are never touched here except the output link field after the user's
  `go`.
- Two failed attempts on any problem: search the web before trying
  again.
