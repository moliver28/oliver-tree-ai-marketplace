---
name: survey-script
description: "Write a burden-capped survey instrument with routing, alternatives, and join fields from a study ticket: question-type mapping per research question, writing-rules check by id, reader review loop, survey-mode checker. Use when the user says: 'draft the survey', 'build the survey instrument'."
---

Write a complete survey instrument from a study ticket so the survey tool
can be filled in without a second review pass. Every hard rule is checked
by the survey mode of `scripts/review_checks.py` before anything saves. No
tracker write until the instrument is done; never sends or shares anything.
This skill is the counterpart of `skills/interview-script` and runs the
same writing workflow on survey law (checklist item B1.4).

## Setup

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it.
   Note `tracker.kind` (the ticket header label follows the tracker),
   `tracker.ticket_regex`, `script.default_minutes`, and
   `workflow.script_status_candidates`. Hardcode nothing.
2. Dispatched agents (`expert-participant`, `novice-participant`,
   `script-writer`) resolve to a workspace `.claude/agents/<name>.md` first
   when one exists, otherwise the plugin's `agents/<name>.md`.
3. Read the writing rules by id from `references/writing-rules.md`. The
   survey families are R-S and X-S; R-H and R-A apply to participant
   respect and claim honesty. The skills never restate rule text; they
   apply the ids.

Grounding: consult registered sources in `references/sources/` (for this skill: R-02 question wording, R-03 survey stages, R-07 wording law); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

## Flow

### 1. Inputs

From a study ticket, gather: research questions, the decision or goal, the
target population, the survey tool in use, and the data-join inventory
(fields the org already holds; checklist item B3.8). Or take them inline:
research questions, a decision, and a population, with no ticket.

Missing research questions or a decision with no ticket: print exactly
`Missing inputs to write a useful survey:` then one bullet per missing
item, only the missing items, and stop.

### 2. Output path

Find the matching workspace via
`python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`
and write to its `scripts/` folder; with no workspace, use the current
folder. File name: `survey-instrument-<KEY>.md`.

If that file already exists, ask before overwriting and offer `-v2`
(`survey-instrument-<KEY>-v2.md`).

### 3. Sequence the research questions

Map each research question to a question type and the expected engagement
per type (checklist item B1.3): open text, single select, multi select,
scale, ranking, or factual. Record the mapping per research question; keep
the research question text unchanged everywhere it appears.

Then order the instrument: topic-grouped, logical order, simple first,
demographics last (rule R-S2).

### 4. Build the instrument

Burden budget (rule R-S3; checklist item B3.3): count questions per
section and keep the questionnaire short. The budget line is
`**Burden budget**: N questions`; the section totals stay inside it.

Routing (rule R-S4; checklist item B3.10): plan the conditional logic
before the build. Every skip path gets a row in the Routing Map; no dead
ends; irrelevant questions stay hidden.

Alternatives (rule R-S3; checklist item B3.9): design each core question
through two to five alternatives and record the kept winner and why
respondent efficiency picked it.

Join and segmentation fields (rule R-S5; checklist items B3.8 and B3.11):
name the join and embed fields for the analysis; every item feeds at least
one segmentation or grouping path.

Fixed document order:

```
# Survey Instrument: <Study Title>
<Tracker> Ticket: <KEY>
UXR: <name>
**Time budget**: N min
**Burden budget**: N questions
**Method**: <method>
**Date drafted**: YYYY-MM-DD
**Drafted from**: <ticket or inline inputs>

## Research Questions
## Routing Map
## Survey                      <- ### N. Title (K questions) sections
## Alternatives
## Join and Segmentation Fields
## Research Question -> Survey Question Map
## Quality Check
```

The map table shape: `| RQ | Question type | Survey Qs | Stakeholder Value |`;
every row names at least one survey question number in `Survey Qs`.

Question grammar inside `## Survey`:

- Sections are `### N. Title (K questions)`; K is the question count.
- Main questions numbered continuously `N.`; conditional questions carry
  the criteria in brackets: `N. [criteria] Question?` and always end in a
  question mark.
- Scaled items from `references/quant-measures.md` keep the item wording
  verbatim: `**[LABEL]. **` then the item text.
- Never use an em dash or en dash anywhere in the instrument.

Routing Map rows: one bullet per skip path, shaped
`- from Q3 [criteria] to Q7`.

Alternatives rows: one bullet per core question, shaped
`- Q4: 3 alternatives tried; kept: <the winner>`.

### 5. Question rules

Apply the registry ids, not restatements: R-S1 (neutral wording, balanced
scales), R-S2 (order), R-S3 (burden and alternatives), R-S4 (routing),
R-S5 (join and segmentation), R-S6 (coverage); X-S1 (no double-barreled or
double-negative items), X-S2 (bounded list lengths, bounded scales); R-H1
(participant respect), R-H2 (method fit); R-A1 and R-A2 on any claim the
instrument text makes (checklist items B3.1, and B3.5 to B3.7 for the
response process, sensitive items, and satisficing guards).

Coverage law: every research question is covered by at least one survey
question; the map records it (rule R-S6; checklist item B3.12).

### 6. Review loop (always runs, including on `-v2`, before the overwrite prompt)

1. Resolve each agent per Setup step 2.
2. Give each reader the full instrument draft. Dispatch in parallel:
   `expert-participant` and `novice-participant` as participant
   simulations (flags: over-explanation, redundant-question,
   jargon-mismatch, unfamiliar-term, ambiguous-instruction,
   unexecutable-step). Validate each returned flag array against
   `references/review-flags.schema.json`; re-dispatch the reader once on
   schema failure.
3. Dispatch `script-writer` once, after both reader flag arrays are back.
   Include the instrument, both flag arrays, and the burden budget. Apply
   the writer's output; drop an edit whose `before_text` does not match.
   Copy each edit-log entry into `## Quality Check` in the interview
   script's line shape.
4. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/review_checks.py" survey <path>`.
   - Exit 0 or 1: save the file.
   - Exit 3: dispatch `script-writer` one more time with the checker's
     findings, apply its edits, and run the checker again.
   - Second exit 3: stop. Show the failing checks to the user. Do not
     save the file and do not touch the ticket.

### 7. Save and report

Save the instrument, then print the absolute path and a 3-line summary:
question total against the burden budget, section count, research
question coverage count. Do not paste the instrument into chat.

Ticket status (only after the loop succeeded) follows the interview
script's law: move the ticket to the first match in
`workflow.script_status_candidates`; with no match, or on any tracker
error, skip the move and say so in one line. Never move before the loop
succeeded.

Optional publish follows the interview script's law: build the
team-format buffer, run
`python "${CLAUDE_PLUGIN_ROOT}/scripts/render_script_docx.py" render <buffer.md> <out.docx>`,
upload the `.docx` into the matching study folder in Drive, and print the
doc URL. Never share the doc and never change its permissions. Published
docs contain no Quality Check text.

## Hard rules recap

- No tracker write until the checker passes.
- The burden budget line and the section counts never disagree.
- Every skip path has a routing row; every routing row lands on a real
  question.
- Every research question keeps at least one survey question.
