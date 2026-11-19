---
description: "Open a study: guided interview, parallel evidence sweep, drafts of the background, decision, hypotheses, and research questions that you refine, a method recommendation, routing to the right researcher, and a preview before anything is created"
argument-hint: "[topic | notes | fast | retro]"
---

Create a study ticket. You answer a short guided interview; the plugin
searches the team's existing evidence in one parallel batch, drafts the
background, decision, hypotheses, and research questions in ONE structured
call for you to refine, recommends a method from a classified RQ shape, and
creates the ticket only after a preview you approve.

Golden path inference: this command spends three model calls - the evidence
signals synthesis (phase 2), the structured drafts call (phases 3 to 5), and
the HCD gate (phase 6). Everything else is scripts. The prompt assets it
renders (`prompts/`) and the script contracts it runs carry the shapes; the
old reference stack (`tracker.md` ops excepted) is gone.

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

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it.
2. Phase 0. Call `current_user()` (the `current_user()` row of the
   `tracker.kind` column in `references/tracker.md`) one time and cache
   it. Detect the role with the routing section of `references/tracker.md`:
   `detect_role(<display name>, <routing>)` returns `uxr`, `manager`, or
   `stakeholder`. The role changes routing only; the interview is the same.

## Phases (full interview)

One phase at a time. Each phase marked **Wait** ends with a question to
the user and stops; do not pre-fill the next phase while waiting.

### Phase 1. Topic and scope (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render new-intake --set "pod_options=<comma list of the configured fields.pod values, joined with , or>"`,
print its stdout verbatim, and stop.

### Phase 2. Evidence sweep (no waiting after it)

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" plan --topic "<topic>"` (`--tactical` when the study answers a build-or-ship question for one team this quarter). It prints one query spec per enabled source in `evidence.sources` - tool, window, limit, query text.
2. Fire EVERY planned source in ONE parallel batch of tool calls, exactly
   per the plan. Do not wait between sources; do not run them one at a
   time. A source whose tool call fails is logged, not retried twice.
3. Save every raw result to one temp file and run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" digest --results <file> --topic "<topic>" --topic-class "<first-run adoption | churn | satisfaction | other>"`.
   It prints the evidence digest and the synthesis table. The model NEVER
   re-reads, quotes, or synthesizes from the raw results - the digest is
   the only evidence input from here on.
4. Render the signals call - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render signals --set "topic=<topic>" --set "digest=<the digest JSON, one line>"` - and run it as this run's FIRST model call: it writes only the four Top signals lines, appended under the script's `Top signals` heading. Print the whole block verbatim (table, unavailable lines, Top signals).

### Phase 2.5. Shareability (mandatory, same turn)

For every Drive URL the digest surfaced, read its permissions and tag it
`shared` (team domain or anyone-with-link at Commenter or higher), `private`
(owner only), or `unknown` (say the check failed; never guess). Never change
a permission. Never put a local file path in Resources: search Drive for a
match and ask for a separate "yes" per candidate before linking one.

### Phases 3 to 5. Background, decision, hypotheses (one call, three gates)

1. Render the structured drafts call - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render drafts --set "ask=<topic and answers so far>" --set "digest=<digest>" --set "group=<group>" --set "owner=<decision owner>" --set "evidence_total=<from the digest>" --set "feedback_gap=<true|false>"` - and run it as this run's SECOND model call. It returns ONE JSON object: background, resources, decision, decision_shape, hypotheses, assumptions.
2. Walk the user through the same three gates as before, using the
   pre-drafted content; do not re-call the model for each phase:
   - **Phase 3 (Wait)**: show the background and the resource list with
     share tags. Ask for edits. Apply edits verbatim.
   - **Phase 4 (Wait)**: show the decision, then the mechanical shape gate:
     run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" decision "<decision text>"`.
     A good shape (`good: true`) prints `This matches a good shape (<shape
     words>: one sentence, named owner). Approve, or edit?`; a bad shape
     (`good: false`) shows what is wrong and proposes a tightened version
     with an owner before waiting.
   - **Phase 5 (Wait)**: show the hypotheses and assumptions as
     `Label. Claim.` lines. Push back with a rewrite when the JSON carries
     claims that are not falsifiable, mix mechanisms, or ignore the
     decision - the craft bars are in the drafts prompt. Wait for edits.

### Phase 6. Research questions and the mandatory HCD gate (**Wait**)

1. Save the phase 5 set to a temp spec JSON and run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/trace_prompts.py" --rq-map <spec.json>`.
   It prints the RQ-to-hypothesis map and lists unmapped RQs. Drop an RQ in
   the `unmapped` list, and say you dropped it and why.
2. Run the deterministic fact-check first: citations, counts, and stance
   vocabulary come from the gates that already ran (the drafts JSON; no
   external claims yet). Assemble the gate input - fact-check output plus
   the draft - and run it as this run's THIRD model call:
   `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render hcd-gate --set "artifact=<draft spec>" --set "artifact_kind=draft" --set "factcheck=<the settled JSON>"`,
   dispatched to the `hcd-researcher` agent (Task tool,
   `subagent_type: hcd-researcher`). The agent judges only the qualitative
   residual (claim-evidence trace, method/RQ alignment, stance
   justification) and ends with a checklist-scoped
   `verdict: {"result": "pass"|"p0", "p0": [...]}` line.
3. Fold every finding in, or record a one-line decline. Print the agent's
   Summary, Risks, and What to change verbatim, plus your fold-in or
   decline per finding. Re-invoke the gate only on a `p0` verdict, after
   the fix. Wait for the user's go-ahead on the revised set.

### Phase 7. Method, sample, investment (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" method --rqs "<RQ1; RQ2; ...>"`.
It prints the dominant shape, the method-table row (method, sample, length,
investment), and one alternative (the highest other matching row; empty when
no other row matches - omit the Alternative line then, never print it empty).
Rules the script already applies:
qualitative leads, never a survey for a why question, ties pick the lighter
method. Show its output as: method, reason (the shape), sample size, session
length, investment level, and the alternative when one exists. Research type comes from the
decision: a shipping decision is Evaluative; a direction or opportunity
question is Generative or Strategic. Wait for the pick. Overrides are
accepted for any line.

### Phase 8. Fields, preview, create (**Wait**, the last gate)

Resolve the researcher routing with the routing section of
`references/tracker.md`:

- Role `uxr`: assignee and UX Researcher are the current user.
- Role `manager` or `stakeholder`: both go to the researcher for the group:
  `resolve_researcher(<group>, <routing>)` (lib/field_map.py). When its
  `notes` list is non-empty, print `notes[0]` verbatim (it names the
  unmapped group and the map update). Offer the `fallbacks` chain when the
  user marks the primary out of office.

Show the field panel, one line each, with the value and where it came from:

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
4. Read the body back with `get_item`, save it to a temp file, then run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" check-readback --file <readback file>`.
   It prints the node counts and `counts OK`, or the problems. Report any
   miss to the user and stop before the next step.
5. Save the draft spec to a temp JSON file, then run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" save-spec --key <KEY> --file <draft file>`.
   It writes `<state_dir>/specs/<KEY>.spec.json` with the six `_meta` keys
   and prints the path. If it exits non-zero: say the ticket exists but
   the spec is not saved, point to
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`, and stop
   before the scaffold.
6. Print `Created [KEY](url)` (the url from `item_url`), then run
   `init KEY` in the same turn (the `uxr-init` command) and
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
- The HCD gate runs before phase 7; a one-line decline is the only
  substitute (`Declined hcd-researcher review: <one line why>`), and a
  `p0` verdict always re-invokes after the fix.
- A synthetic persona needs a yes from the user before use.

## Voice

Lead with the result. No em dashes. Ask one phase's questions at a time.
When a tool fails, print the `<Tool>: unavailable (skipped)` line and
continue; never fake a source.
