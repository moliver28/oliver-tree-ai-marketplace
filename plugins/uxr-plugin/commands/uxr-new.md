---
description: "Open a study: guided interview, parallel evidence sweep, drafts of the background, decision, hypotheses, and research questions that you refine, a method recommendation, routing to the right researcher, and a preview before anything is created"
argument-hint: "[topic | notes | fast | retro]"
---

Create a study ticket. Instead of a blank form you answer a short guided
interview; the plugin searches the team's existing evidence in one
parallel batch, drafts the background, decision, hypotheses, and research
questions for you to refine, recommends a method, routes the ticket to the
right researcher, and creates the ticket only after a preview you approve.

Quality bars live in `references/research-craft.md`, the evidence sweep in
`references/evidence-lookup.md`, the review contract in
`references/research-grounding.md`, and the tracker operations in
`references/tracker.md`. Hardcode nothing: every organization value comes
from config.

## Input paths (`$ARGUMENTS`)

| Input | Behavior |
|---|---|
| empty | Full interview, phases 1 to 8 |
| a topic phrase | Full interview with the topic filled in |
| a paragraph of notes | Targeted interview: run the sweep, then ask only for the gaps the notes leave |
| contains `fast` | Fast path below: no interview |
| contains `retro` | Retrospective path below: build a ticket for a finished study from its files |

The `fast` and `retro` words are checked anywhere in the input and win over
the other paths.

## Setup (once)

1. Read configuration once: run `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`
   (when `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin
   directory that holds `lib/`, `config/`, and `references/`). Note
   `tracker.kind`, `tracker.project_key`, `tracker.study_item_type`,
   `tracker.default_priority`, `fields.*`, `routing.*`, `evidence.*`,
   `ssot.*`, `org.team_share_domain`, `defaults.start_window_days`, and
   `defaults.fast_path`.
2. Phase 0. Call `current_user()` (the `current_user()` row of the
   `tracker.kind` column in `references/tracker.md`) one time and cache
   it. Detect the role with the routing section of `references/tracker.md`:
   `detect_role(<display name>, <routing>)` returns `uxr`, `manager`, or
   `stakeholder`. The role changes routing only; the interview is the same.

## Phases (full interview)

One phase at a time. Each phase marked **Wait** ends with a question to
the user and stops; do not pre-fill the next phase while waiting.

### Phase 1. Topic and scope (**Wait**)

One message, exactly three questions: the working title; the group or
area (a `fields.pod` value when the team list is configured); and the
decision owner's name.

### Phase 2. Evidence sweep (no waiting after it)

Run EVERY source enabled in `evidence.sources` in ONE parallel batch of
tool calls, following `references/evidence-lookup.md` for each source's
window, limit, and query shape. Do not wait for the user during or after
the batch. Do not run the sources one at a time.

- The user's recent items in other tracker projects (last 90 days,
  limit 20).
- Topic search in other tracker projects (last 180 days, limit 10).
- Drive full-text search (limit 15) plus the 25 most recently modified
  files.
- The customer feedback store. Never skip it when the topic is churn,
  satisfaction, or adoption.
- Chat search in the `evidence.chat_channels` channels (limit 20).
- Wiki search (last 180 days, limit 10). Skip for a tactical study.
- The jobs-to-be-done and persona sources from `ssot.*` (top 3 to 5 each,
  each with a ring tag).
- Chat channel discovery for the study.

Then print the one synthesis block from `references/evidence-lookup.md`:
a hit count for each source, one `<Tool>: unavailable (skipped)` line per
failed source, and Top signals (owning group, hypotheses in flight, pain
strength high/medium/low, stakeholders).

### Phase 2.5. Shareability (mandatory, same turn)

For every Drive URL the sweep surfaced, read its permissions and tag it
`shared`, `private`, or `unknown` exactly as `references/evidence-lookup.md`
defines. Never change a permission. Never put a local file path in
Resources: for a local file, search Drive for a match and ask the user for
a separate "yes" for each candidate before linking it.

### Phase 3. Background draft (**Wait**)

Draft 3 to 5 sentences: why now, what already exists (cite the sweep's
counts and document names), who needs the answer, and the problem area.
Show the draft and the resource list with its share tags. Ask for edits.

### Phase 4. Decision (**Wait**)

Ask for the decision in one sentence. Show the good and bad shapes from
`references/research-craft.md` when the user's answer matches a bad shape,
and propose a tightened version with an owner. Wait for approval of the
final wording.

### Phase 5. Hypotheses and assumptions (**Wait**)

Propose 3 to 5 hypotheses and 2 to 3 assumptions as `Label. Claim.` lines
(`H1. ...`, `A1. ...`). Push back, with a rewrite, on claims that are not
falsifiable, mix mechanisms, or do not tie to the decision
(`references/research-craft.md`). Wait for edits.

### Phase 6. Research questions and the mandatory review (**Wait**)

Propose 3 to 6 open research questions and show the RQ-to-hypothesis map.
Drop an RQ that traces to no hypothesis, and say you dropped it and why.

Then run the mandatory review: dispatch the `hcd-researcher` agent (Task
tool, `subagent_type: hcd-researcher`) on the decision, hypotheses, and
RQs, with the contract in `references/research-grounding.md`. Fold every
finding in, or record a one-line decline. Print the agent's Summary,
Risks, and What to change verbatim, plus your fold-in or decline per
finding. Wait for the user's go-ahead on the revised set.

### Phase 7. Method, sample, investment (**Wait**)

Read the dominant RQ shape and take that row of the method table in
`references/research-craft.md`. Show: method, reason, sample size, session
length, investment level, research type, and one alternative. Rules:
qualitative leads, never default to a survey for a why question, and on a
tie pick the lighter method. Wait for the pick.

### Phase 8. Fields, preview, create (**Wait**, the last gate)

Resolve the researcher routing with the routing section of
`references/tracker.md`:

- Role `uxr`: assignee and UX Researcher are the current user.
- Role `manager` or `stakeholder`: both go to the researcher for the
  group: `resolve_researcher(<group>, <routing>)` (lib/field_map.py).
  When its `notes` list is non-empty, print `notes[0]` verbatim (it names
  the unmapped group and the map update). Offer the `fallbacks` chain when
  the user marks the primary out of office.

Show the field panel, one line each, with the value and where it came
from:

- Group (`pod`), research type, method, support level, investment,
  outcomes (`outcome`), UX Researcher (`uxr`), assignee, priority
  `tracker.default_priority`
- Start date: today to today + `defaults.start_window_days` days
- Labels: `<topic-slug>, <quarter>` (topic-slug: lowercase, runs of
  non-alphanumeric characters become one hyphen; quarter: the current
  `YYYY-QN`)

Accept overrides for any line. Then show the preview: item type
(`tracker.study_item_type`), summary (the working title), people, labels,
the resolved field payloads, a body STRUCTURE summary (the ten template
blocks with one line each; never the raw rich text), and the count of
resources whose share check succeeded. Wait for `yes`, `create`, or `go`.

## Build, validate, persist (shared with `init`)

Run these steps in order, in the same turn once approved:

1. Assemble the spec in memory from the interview: `history`, `decision`,
   `hypotheses` (`{label, text}`, never empty), `assumptions`,
   `resources` (`{label, url or text, share_status, share_note}` from
   phase 2.5), `research_questions` (never empty), `sample_size`,
   `persona`, `session_length`, `results` (null unless `retro`),
   `study_title`, `method_key` (`interview` or `survey`; `survey` only
   when the method is Survey), `channel` (`internal`, `external`, or
   `mixed`), the people names `init` reads (`uxr`, `pm`, `pd`, `em`
   owners when gathered), `jtbd_refs`, `persona_refs` (with their ring
   tags), and `slack_channel`.
2. Pipe it through the renderer: `python "${CLAUDE_PLUGIN_ROOT}/scripts/build_body.py"`
   with the spec JSON on stdin. A non-zero exit means validation or
   rendering failed: print the stderr lines verbatim, write nothing, call
   no tracker tool, and return to the interview phase that owns the
   failing content. A spec with empty hypotheses exits 3 and never
   reaches `create_item`.
3. Call `create_item` (`references/tracker.md`) with
   `tracker.study_item_type`, the summary, the rendered body, and the
   resolved field payloads from the approved panel. This is the plugin's
   only call in this flow that creates anything, and it runs only after
   the phase 8 gate.
4. Read the body back with `get_item` and verify the node counts from
   issue 04. Save the read-back to a temp file, then run:

   ```
   python - <<'PY'
   import sys
   sys.path.insert(0, r"<plugin root>")
   from lib import spec_blocks
   text = open(r"<read-back file>", encoding="utf-8").read()
   ok, problems = spec_blocks.assert_full_document(text)
   print(spec_blocks.document_counts(text))
   print("counts OK" if ok else "\n".join(problems))
   PY
   ```

   Report any miss to the user and stop before the next step.
5. Save the spec with `_meta`. Write the assembled spec plus
   `_meta = make_meta("new")` (exactly the six keys) pretty-printed to
   `<state_dir>/specs/<KEY>.spec.json`:

   ```
   python - <<'PY'
   import json, sys
   sys.path.insert(0, r"<plugin root>")
   from lib import spec_blocks
   from lib.config import load_config
   spec = json.load(open(r"<draft spec file>", encoding="utf-8"))
   spec["_meta"] = spec_blocks.make_meta("new")
   path = spec_blocks.spec_path("<KEY>", load_config())
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
   print(path)
   PY
   ```

   If the save fails: say the ticket exists but the spec is not saved,
   point to `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`,
   and stop before the scaffold.
6. Print `Created [KEY](url)` (the url from `item_url`), then run
   `init KEY` in the same turn (the `uxr-init` command, issue 08) and
   list the next steps (write the script, recruit, plan sessions). When
   `commands/uxr-init.md` does not exist in this build, print one line
   `init is not in this build yet; the ticket and spec are ready.` and
   stop after the next steps.

## Fast path (`fast` in the input)

Skip phases 1 to 7. Ask the user for the topic in one line if the input
names none. Use the `defaults.fast_path` values for group, research type,
method, investment, support, and outcomes; run `current_user()` and the
routing resolution exactly as in phase 0 and phase 8.

The validator requires them, so ask in ONE message for: one hypothesis
(`Label. Claim.`), one open research question, and a yes on the one-line
decision you propose from the topic. Then run the build block.

## Retro path (`retro` in the input)

Input is a workspace path or a Drive folder link for a finished study.

1. List the artifacts you can see (files in the folder, or the Drive
   listing) and ask "Correct?".
2. Derive, from the files ONLY: the history, the decision, the
   hypotheses, the assumptions, the RQs, the method, the sample, and a
   2 to 3 sentence result for the `results` field.
3. Ask before adding scope the files do not support.
4. Run the build block. Do NOT run `init`: a finished study gets no new
   workspace.

## Safety gates

- Preview before create. No silent create: the only create call runs
  after the phase 8 approval word.
- Per-candidate "yes" for a local-to-Drive match. Never change a Drive
  permission.
- A validation failure means zero writes: no tracker calls, no spec file.
- The `hcd-researcher` review runs before phase 7; a one-line decline is
  the only substitute (`references/research-grounding.md`).
- A synthetic persona needs a yes from the user before use.

## Voice

Lead with the result. No em dashes. Ask one phase's questions at a time.
When a tool fails, print the `<Tool>: unavailable (skipped)` line and
continue; never fake a source.
