---
name: interview-script
description: "Write a bias-controlled interview script, discussion guide, or moderator protocol from a study ticket (also on /script): Double Diamond flow, technique mapping, review loop, hard-rule gate. Not for code scripts. Use when the user says: 'draft the interview script', 'write the discussion guide'."
---

Write a complete interview script from a study ticket so a moderator can
run the session without a second review pass. Every hard rule is checked
by `scripts/review_checks.py` before anything saves. No tracker write
until the script is done; never sends or shares anything.

## Setup

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it.
   Note `tracker.kind` (the ticket header label follows the tracker, for
   example `Jira Ticket:` on Jira, `Linear Issue:` on Linear),
   `tracker.ticket_regex`, `script.default_minutes`, `script.time_buffer`,
   `script.word_cap`, `script.grade_warn`, `script.grade_block`, and
   `workflow.script_status_candidates`. Hardcode nothing.
2. Dispatched agents (`expert-participant`, `novice-participant`,
   `script-writer`, `hcd-researcher`) resolve to a workspace
   `.claude/agents/<name>.md` first when one exists, otherwise the
   plugin's `agents/<name>.md`.

Grounding: consult registered sources in `references/sources/` (for this skill: R-01 interview pages, R-04 COREQ); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

## Flow

### 1. Inputs

From a study ticket, gather: research questions, JTBD, the decision or
goal, hypotheses and assumptions, the recruitment strategy, and the
workspace fields. Or take them inline: RQs, JTBD, and a goal, with no
ticket. The default time budget is `script.default_minutes` (60).

Missing RQs or a goal with no ticket: print exactly
`Missing inputs to write a useful script:` then one bullet per missing
item, only the missing items, and stop.

### 2. Output path

Find the matching workspace via
`python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`
and write to its `scripts/` folder; with no workspace, use the current
folder. File name: `interview-script-<KEY>.md`.

If that file already exists, ask before overwriting and offer `-v2`
(`interview-script-<KEY>-v2.md`).

### 3. Sequence the research questions

Order the RQs in Double Diamond order and label each phase:

1. Discover Problem
2. Validate Problem
3. Discover Solution
4. Validate Solution

Map a technique to each RQ:

- Past behavior asks for a **Critical Incident** or a **Switch Interview**.
- Decisions and circumstances ask for **Think-Aloud** or circumstance
  **JTBD**.
- Broad needs ask for **JTBD**.
- Eligibility asks for a **Screener**.

Keep the RQ text unchanged everywhere it appears.

### 4. Pick quant measures

Pick from `references/quant-measures.md` by study type (concept testing,
usability test, onboarding tour, idea pooling, discovery). Copy the item
wording verbatim; a labeled item that differs from that file makes the
checker warn. Pure discovery gets none. Place each measure right after the
exposure it measures.

### 5. Build sections for the budget

Default plan for a 60-minute session:

| Section | Minutes |
|---|---|
| Intro & Consent | 4 |
| Context & Current State | 10 to 12 |
| Critical Incident | 15 to 20 |
| Probe Themes | 10 to 15 |
| Design Walkthrough | 10, only with an artifact |
| Strategic Close | 5 |
| Wrap | 2 |

Hard cap: the scripted minutes total at most
`script.default_minutes - script.time_buffer` (52 by default). When the
plan above exceeds that line, trim sections inside their ranges or drop
optional ones; the checker blocks a total over the cap. Consent text
depends on the participant ring: internal sessions say how the recording
is stored and who sees it; external sessions add purpose, voluntariness,
and the same recording honesty. Never over-promise confidentiality: do
not claim anonymity the tooling cannot deliver.

No section runs over 15 minutes without a reset transition (a
`**Read Aloud:**` line that moves the participant to a new topic).

### 6. Question rules

- No yes or no questions: never open with do, does, did, is, are, was,
  were, can, could, will, would, has, or have.
- At most `script.word_cap` (20) words per main question. Probes are
  exempt.
- Reading grade 8 to 10 on spoken text and questions.
- No leading, double-barreled, assumptive, or loaded wording; at most one
  negation per main question.
- Open broad question first in each section.
- The first design question is an open reaction ("What is your first
  reaction to this?"), never a task.
- Probes sit under their main question; laddering runs at most 3 rungs
  (what, why that matters, why that matters more broadly).
- Moderator cues read `*[Moderator: ...]*`.

### 7. Document order (fixed)

```
# Interview Script: <Study Title>
<Tracker> Ticket: <KEY>
Prototype Link: <url or omitted>
UXR: <name>
PD and-or PM: <names>
**Time budget**: N min
**Method**: <method>
**Date drafted**: YYYY-MM-DD
**Drafted from**: <ticket or inline inputs>

## Research Questions
## Moderator Notes
## Script                      <- ### N. Title (M min) sections
## Research Question → Script Question Map
   | RQ | Phase | Technique | Script Qs | Stakeholder Value |
## Quality Check
## Critical-to-Success         <- when hcd-researcher ran
## Quant Measures              <- when measures were picked
## Tour Implementation Capture <- for onboarding-tour studies
## Leadership Read             <- 3 to 5 bullets
```

Every RQ map row names at least one script question in `Script Qs`.

### 8. Format grammar

- Spoken text: `**Read Aloud:**` then an italic block (`*...*`).
- Unspoken notes: `- Note: ...`.
- Main questions numbered continuously `N.`; probes lettered and indented
  three spaces `   a.`; no letter gaps.
- Conditionals: `N. [criteria] Question?` and always end in a question
  mark.
- Survey items: `**[LABEL]. **` then the item text verbatim.
- Navigation as a literal path: `Go to 'Settings' > Click 'Integrations'`.
- Never use an em dash or en dash anywhere in the script.

### 9. Review loop (always runs, including on `-v2`, before the overwrite prompt)

1. Resolve each agent per Setup step 2.
2. Ingest the artifact. Read the ticket's resources. A design tool link
   goes to the design MCP (pull metadata and screenshots); a Drive link
   goes to the Drive MCP. No such link is the legitimate no-artifact
   branch; do not invent an artifact. Write
   `<workspace>/.sessions/artifact-manifest-<KEY>.md` holding the
   observed screens, controls, labels, task steps, and a JTBD map. Name
   only what the ingest actually showed.
3. Dispatch in parallel:
   - `expert-participant` (flags: over-explanation, redundant-question,
     jargon-mismatch, flat-answer-risk),
   - `novice-participant` (flags: unfamiliar-term,
     ambiguous-instruction, unexecutable-step, artifact-mismatch),
   - `hcd-researcher`, only for concept testing, usability, and
     onboarding-tour studies, with the rider from
     `references/script-rigor.md` appended to the dispatch; it returns
     the Critical-to-Success block. For other study types, skip it.
     For the `hcd-researcher` dispatch: run
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/researcher_state.py" digest --key <KEY>`
     first; when it prints reviews, paste its output into the dispatch
     under a `Prior reviews:` line and add the label line
     `Artifact kind: script`; `no prior reviews` continues unchanged. The
     dispatch input opens with the verbatim ask from the spec:
     `Original ask (<ask_source date>): <ask_verbatim>`; a pre-ask spec
     says `Original ask: not recorded (pre-ask spec)` in one line and
     continues.
   Give each reader the full script draft; give the novice the manifest
   when one exists, and say in the dispatch that no artifact was fetched
   when it does not. Validate each returned flag array against
   `references/review-flags.schema.json` (a bare JSON array, every flag
   `synthetic: true`, `flat-answer-risk` always `confidence: hedged`,
   and no flag outside the emitting agent's owned types); re-dispatch the
   reader once on schema failure.
4. Dispatch `script-writer` once, after both reader flag arrays are back.
   Include the script, both flag arrays, and the manifest.
5. Apply the writer's output. Confirm every quoted span existed in the
   draft; drop an edit whose `before_text` does not match. Then copy each
   edit-log entry into `## Quality Check` as:

   `agent: script-writer. Resolves flag(s): <ids>. Flag type: <type>. Before: "<text>". After: "<text>". Hard rules preserved: <values>.`

6. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/review_checks.py" check <path>`.
   - Exit 0 or 1: save the file.
   - Exit 3: dispatch `script-writer` one more time with the checker's
     findings, apply its edits, and run the checker again.
   - Second exit 3: stop. Show the failing checks to the user. Do not
     save the file and do not touch the ticket.

### 10. Save and report

Save the script, then print the absolute path and a 3-line summary:
total time, section count, question count. Do not paste the script into
chat.

### 11. Ticket status (only after the loop succeeded)

Read the live state list from the tracker. Move the ticket to the first
match in `workflow.script_status_candidates` (reference order: `writing
script / survey`, `writing script`, `script`, `in progress`). With no
match, or on any tracker error: skip the move and say so in one line.
Never move before the loop succeeded.

### 12. Optional publish

Publish when the user passes `--drive`, or answers yes to one question
(default no): "Publish this script to the study folder as a Google Doc?"

1. Build the team-format buffer: title, ticket link, RQ bullets, the
   moderator guide note, UXR name, goal list, then the script sections.
   Leave out the RQ map, Quality Check, Critical-to-Success, and
   Leadership Read.
2. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/render_script_docx.py" render <buffer.md> <out.docx>`.
3. Upload the `.docx` into the matching study folder in Drive and convert
   it to a Google Doc. Print the doc URL. Never share the doc and never
   change its permissions.
4. Offer chat and mail drafts to reviewers. Never send them; drafts only.

## Hard rules recap

- No artifact fetched means zero `artifact_grounded: true` flags.
- Writer edits never change headings, question numbers, minute values, or
  RQ map cells, and every edit resolves at least one flag.
- Published docs contain no Quality Check text.
