---
description: "Turn a finished study into a report sized to its stakes: script-computed tier, verdicts, evidence counts, and citation checks; optional HTML render through a mechanical check and two reviewer agents; optional publish to the gallery. Every stakeholder message is a draft."
argument-hint: "<KEY> [--audience=internal|product-team|leadership] [--tier=lite|standard|strategic] [--dry-run] [--video] [--altitude=brief|standard|deep] [--render-only] [--format=html] [--stakeholder-role=<role>]"
---

Scripts compute the tier, verdicts, evidence counts, and citation checks; you write the narrative on that skeleton.

## Safety rules (they override everything below)

1. **Every external action is a draft first.** Chat/mail draft tools only; a mail draft body carries no URL when the mail tool rewrites links. Nothing sends without the user's reply.
2. **A calendar agenda update appends one line after `go`.** Never change a meeting's time or attendees.
3. **A revenue lookup message is drafted and waits for `go`.**
4. **The gitignore gate passes before any deliverable write.** Run `scripts/gitignore_gate.py assert-ignored` on the `.sessions/gather-brief-*.md` path plus one path per `workspace.gitignored_paths` entry (config adds to the hardcoded path); exit 3 stops the whole run before any file is written.
5. **Publish is never automatic.** Gallery publish runs only on the user's explicit `go`; never pass `--force` on the user's behalf.
6. **`--dry-run` writes no file and calls no write tool.** Show every draft and computed number under a `DRY RUN - nothing written` heading; stop before phase 5.
7. **Verdict labels are copied verbatim from the script.** Never reword, soften, or upgrade a computed verdict.

## Inputs

Grounding: registered sources in `references/sources/` (this command: R-01 metrics, R-04 COREQ, R-20 scoring, R-21 HEART); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

`$ARGUMENTS` is `<KEY>` with any of: `--audience=internal|product-team|leadership` (default `internal`), `--tier=lite|standard|strategic` (default: computed by `scope-tier`), `--dry-run`, `--video`, `--altitude=brief|standard|deep`, `--render-only`, `--format=html`, `--stakeholder-role=<role>` (one of PD, EM, PM, Leadership; one dispatch per role).

Every gate uses the same words: `go`, `edit`, `cancel`.

## Setup (every run)

Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - follow it. Note `paths.research_root`, `paths.state_dir`, `routing.group_to_channels`, `routing.group_to_area`, `report.verdict_threshold`, `report.multi_group_bump`, `report.tier_matrix`, `publish.repo`, `publish.pages_url`, `ssot.finished_title_pattern`, `comments.footer`, `tracker.ticket_regex`.

## Phases

| Phase | Steps |
|---|---|
| 0. Resolve | Find the workspace (none: point to `init`; stop): `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`. Need at least one `interviews/*-summary.md` and a non-empty `analysis/codes.md` or `analysis/themes.md`; else stop at `debrief` - nothing to report yet. Then method-selection - `python "${CLAUDE_PLUGIN_ROOT}/lib/checklist_gate.py" check --type method-selection --spec <state_dir>/specs/<KEY>.spec.json --workspace <workspace>` - missing list as record-gap lines, never block; no shipped checklist: record its named-gap line in `method-selection.md`; study proceeds under the shared law. Then the type checklist gate - `python "${CLAUDE_PLUGIN_ROOT}/lib/checklist_gate.py" check --type <qual-interviews when the method is an interview, quant-surveys for a survey> --spec <state_dir>/specs/<KEY>.spec.json --workspace <workspace>` - same treatment: warn, continue, never block (`checklists.enforcement: record`; `block` mode: the phase 5 write stops at more than half the items lacking evidence). |
| 1. Scope | Ticket (summary, body, fields via `get_item` in `references/tracker.md`) and workspace `00-overview.md`, in parallel. Run `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" scope-tier --type "<research type>" --investment "<investment>" --pod-names "<raw group string>"`. Scope card: type, investment, groups, computed tier (explicit `--tier` overrides; say so). Opens with the verbatim ask line `Original ask (<ask_source date>): <ask_verbatim>` from the spec (pre-ask spec: `Original ask: not recorded (pre-ask spec)`, one line). Gate. |
| 2. Gather | One parallel batch: (A) `analysis/codes.md`, `analysis/themes.md`, all summaries; (B) prior finished studies: tracker (limit 8), Drive (18 months back, limit 12), wiki (180 days back, limit 8); (C) feedback store, chat search in the study's channels, next 21 days of calendar. Failed source: log `<Tool>: unavailable (skipped)`, never block. Compress B and C into `<workspace>/.sessions/gather-brief-<KEY>-<date>.md` - names, counts, verdicts; not raw search JSON. Gate. |
| 3. Synthesize | Run `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" evidence-weight --workspace <workspace>`, then `verdict` on the tallies (or read from the evidence-weight output). Fewer than half the sessions with an alignment block: it warns - show it, keep going. Map each finding to its source as `[S:slug]`; no source: `UNCITED: <claim>` on its own line. Bias check: `codebook-codes --file <workspace>/analysis/codes.md`, then `classify-themes --codes-file ... --themes-file ...`. Show the synthesis table (finding, verdict, sources) and the bias-check table. Gate. |
| 4. Draft | The run's FIRST model call: narrative to the tier spec below, `deliverables/<filename draft>` shape (front matter below), ending with one `Headline:` line (one sentence, computed numbers, verdict labels verbatim) for phase 6 reuse. `python "${CLAUDE_PLUGIN_ROOT}/references/report_helpers.py" word-count-sections --file <draft>`: section `OVER` at more than 20% above its limit; rewrite overs until none; still OVER after two passes: show counts, ask `go` / `edit` / `cancel`. Then the mandatory HCD gate (below). Optional: one `stakeholder-reviewer` dispatch per `--stakeholder-role`. Optional: `cross-study --current-file <draft> --priors-glob "<prior reports from phase 2>"`; show `{confirms, reverses, new}` beside the draft. No `--stakeholder-role`: one line - available by re-running with `--stakeholder-role=<role>`. |
| 5. Create | `report-filename --key <KEY> --audience <audience> --date <today>`. `check-citations --draft-file <draft> --sources-dir <workspace>/sources`: missing slug returns to phase 4 (fix the citation or mark the claim `UNCITED`). Run the gitignore gate; write `deliverables/<filename>` with the front matter below. Appendix A (strategic tier): revenue lookup message drafted, waits for `go`; `arr-parse --reply-file <reply>` output to `<state_dir>/arr-<KEY>.json`; appendix via `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" render-appendix --key <workspace>/interviews/participant-key.md --arr-file <state_dir>/arr-<KEY>.json`. With `--format=html`: render, check, review loop below. `--render-only` stops here. Optional, after an explicit `go`: publish (below), Drive upload under the finish rules, output link field update - one line to the user: available on an explicit `go`, each optional. No `--format=html`: one line - available by re-running with `--format=html`. |
| 6. Distribute | Drafts only, assembled mechanically from the phase 4 `Headline:` line (zero model calls here); render - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render distribution --set "tier=<tier>" --set "date=<today>" --set "filename=<filename>" --set "headline=<sentence>" --set "next_line=<one deterministic next step from the draft>" --set "prelim=<`. Single session; treat as preliminary.` (leading period-space included) when a finding has fewer than 2 sources, else empty; the render skips the clause when the bound headline already carries it>" --set "footer=<comments.footer with {display_name} replaced>" --set "channels=<channels --pod <group> --tier <tier>>" --set "video=<requested or none>"` - print its output as the drafts (tier variants, chat/mail/agenda/video fragments fire per tier). No `--video`: one line - available by re-running with `--video`. Show every draft; wait. |

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

Analyst inference: label exactly `Analyst inference`, no slug. Describe diagrams in words; never generate images. `--altitude=brief`/`standard`/`deep` = lite/standard/strategic shape (map with `altitude --level`). Methodology: original ask first - the phase 1 ask line; a draft may quote an up-level after it; up-levels live only in the spec's `ask_uplevels`, never in `ask_verbatim`. Methodology also names the analysis plan actually followed - the deterministic gates, in order.

## The HCD gate (phase 4; one call per run)

Render the dispatch - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render hcd-gate --set "artifact=<the draft>" --set "artifact_kind=report" --set "factcheck=<the settled gates JSON: check-citations, word-count-sections, evidence-weight verdicts>"` - dispatch to `hcd-researcher` (Task tool, `subagent_type: hcd-researcher`). The fact-check settled numbers, citations, stance vocabulary; the agent judges only the qualitative residual (claim-evidence trace, method/RQ alignment, stance justification), ending with a checklist-scoped `verdict: {"result": "pass"|"p0", "p0": [...]}` line. Fold in every finding or record a one-line decline. Print the agent's Summary, Risks, What to change verbatim. Re-invoke only on `p0`, after the fix.

Before dispatch: `python "${CLAUDE_PLUGIN_ROOT}/scripts/researcher_state.py" digest --key <KEY>`; printed reviews go into the study context under a `Prior reviews:` line; `no prior reviews` changes nothing. The study context opens with the spec's verbatim ask (phase 1 has the line; a pre-ask spec continues).

## Verdicts (from `report.verdict_threshold`, default 0.60)

Denominator: the count for that one hypothesis or assumption label. Hypothesis: Supports share at or above 0.60 = `Supported`; Challenges share at or above 0.60 = `Not supported`; no dominant side = `Partially supported`; no evidence = `Insufficient evidence`. Assumption: `Holds`, `Breaks`, `Untested`, `Insufficient evidence`; same rule.

## HTML render, check, and review loop

1. Render: `python "${CLAUDE_PLUGIN_ROOT}/scripts/report_html.py" render <deliverable.md> <deliverable-dir>/<slug>.html`. Self-contained, byte-identical on two runs, `<` escaped before conversion (participant quotes cannot inject script).
2. Check: `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_report_html.py" check <html> --deliverable=<deliverable.md>`. Any `WARN` line exits 1 - fix the Markdown or render; repeat before review.
3. Gate and closure (the review loop is one HCD gate, not parallel dispatches): phase 4 findings arrive checklist-scoped with a category; route each mechanically - `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" route-finding --category "<category>"` - to the renderer (re-render from fixed Markdown) or the Markdown (fix the text); re-check with `validate_report_html.py`; re-run the word-count and citation gates; re-invoke the gate only on `p0`. Write `deliverables/report-review-<date>-<KEY>.md`: each finding Resolved or Deferred, final `PASS` or `FAIL` line (the deterministic closure re-check). A FAIL is a valid result - report it, do not force a pass.

## Publish (optional, only on the user's explicit `go`)

`python "${CLAUDE_PLUGIN_ROOT}/scripts/publish_artifact.py" publish <html> --slug <slug> --ticket <KEY> --pod "<area>" --tier <tier> --audience <audience> --date <date> --title "<finish-rule title>" --repo-path <publish.repo> --pages-url <publish.pages_url>`

Refuses a dirty or non-`main` repo and a slug folder with foreign files (never `--force` for the user); print the refusal verbatim. Writes `<slug>/index.html`, upserts `manifest.json`, rebuilds the gallery, updates the README list between markers, commits, pushes, prints the page URL. Finish rules first: `pod-to-area --pod <group>` for the area; `validate-finish-title --title "<title>" --pod "<area>"` for the title (shape `<Product Area> <What it was> <YYYY-MM>`). Drive upload files the deliverable under `ssot.finished_artifacts_folder_id` in a product-area subfolder, same pattern; then update the ticket's output link field.

## Scripts

| Script | Contract |
|---|---|
| `report_helpers.py scope-tier [--pod-count <n>]` | Prints `lite`, `standard`, or `strategic`; two or more groups bump one step unless investment is `0`. |
| `report_helpers.py evidence-weight` | `{rq_coverage, hypothesis_verdicts, assumption_verdicts, sessions_tallied, sessions_with_alignment_block}`. |
| `report_helpers.py verdict [--json-file <f>] [--kind hypothesis\|assumption]` | `{label: verdict}` from stance tallies. |
| `report_helpers.py word-count-sections` | `{H2 title: words}`. |
| `report_helpers.py check-citations` | `[{slug, found}]`, missing slugs first. |
| `report_helpers.py codebook-codes` / `classify-themes` | Bias-check inputs and the `Theme \| Origin \| RQs supporting \| Fragile?` table with the `Researcher-framed: N. Emergent: N. Single-RQ conclusions: <ids>.` line. |
| `report_helpers.py channels` | Chat channel names for the distribution drafts, from `routing.group_to_channels`. |
| `report_helpers.py cross-study` | `{confirms, reverses, new}` against prior reports' front matter. |
| `report_helpers.py report-filename` | `report-<aud>-<date>-<key>.md`, lowercase. |
| `report_helpers.py altitude` | The tier the altitude maps to. |
| `report_helpers.py pod-to-area` / `validate-finish-title` | Finish rules for the Drive upload and the publish title. |
| `report_helpers.py arr-parse` | `{account: "$1.2M"}`. |
| `scripts/report_html.py render <md> <html>` | The self-contained render. |
| `scripts/validate_report_html.py check <html> --deliverable=<md>` | The mechanical check; exit 1 on any WARN. |
| `scripts/publish_artifact.py publish <html> --slug ... --ticket ... --pod ... --tier ... --audience ... --date ... --title ... --repo-path ... --pages-url ... [--force]` | The gallery publish; no commit on a refusal. |
| `scripts/gitignore_gate.py assert-ignored --repo <workspace> .sessions/gather-brief-<KEY>-<date>.md` | The gate before any deliverable write; exit 3 stops. |

## Rules of last resort

- No file write before this run's gitignore gate passes.
- Never claim a live tracker, chat, calendar, or Drive result the run did not produce.
- Comment draft only on the ticket; body, status, and fields untouched except the output link field after the user's `go`.
- Two failed attempts on any problem: search the web before trying again.
