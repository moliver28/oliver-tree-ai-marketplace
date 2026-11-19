---
description: "Open a study: guided interview, parallel evidence sweep, drafts of the background, decision, hypotheses, and research questions that you refine, a method recommendation, routing to the right researcher, and a preview before anything is created"
argument-hint: "[topic | notes | fast | retro]"
---

Create a study ticket: guided interview, one parallel evidence sweep, drafts
of background/decision/hypotheses in ONE structured call, method pick, HCD
gate, preview, create. Three model calls on the golden path (phases 2, 3–5,
6); everything else is scripts.

## Input paths (`$ARGUMENTS`)

| Input | Behavior |
|---|---|
| empty | Full interview, phases 1 to 8 |
| a topic phrase | Full interview with the topic filled in |
| a paragraph of notes | Targeted interview: run the sweep, then ask only for the gaps the notes leave |
| contains `fast` | Fast path below: no interview |
| contains `retro` | Retrospective path below: build a ticket for a finished study from its files |

`fast`/`retro` win over the other paths.

## Setup (once)

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it.
2. Phase 0. Call `current_user()` (the `current_user()` row of the
   `tracker.kind` column in `references/tracker.md`) once and cache it.
   `detect_role(<display name>, <routing>)` from the routing section of
   `references/tracker.md` returns `uxr`, `manager`, or `stakeholder`.
   Role changes routing only.

## Phases (full interview)

One phase at a time. **Wait** phases end with a question and stop; do not
pre-fill the next phase while waiting.

### Phase 1. Topic and scope (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render new-intake --set "pod_options=<comma list of the configured fields.pod values, joined with , or>"`,
print its stdout verbatim, and stop.

### Phase 2. Evidence sweep (no waiting after it)

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" plan --topic "<topic>"` (`--tactical` when the study answers a build-or-ship question for one team this quarter). It prints one query spec per enabled source in `evidence.sources`.
2. Fire EVERY planned source in ONE parallel batch of tool calls, exactly per the plan. No sequencing. A source whose tool call fails is logged, not retried twice.
3. Save every raw result to one temp file and run `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" digest --results <file> --topic "<topic>" --topic-class "<first-run adoption | churn | satisfaction | other>"`. The digest is the only evidence input from here on; never read, quote, or synthesize from raw results.
4. Render the signals call - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render signals --set "topic=<topic>" --set "digest=<the digest JSON, one line>"` - and run it as this run's FIRST model call: it writes only the four Top signals lines under the script's `Top signals` heading. Print the whole block verbatim (table, unavailable lines, Top signals).

### Phase 2.5. Shareability (mandatory, same turn)

For every Drive URL the digest surfaced: tag `shared` (team domain or
anyone-with-link at Commenter+), `private` (owner only), or `unknown` (say
the check failed; never guess). Never change a permission. Never put a
local path in Resources: search Drive for a match and ask for a separate
"yes" per candidate before linking one.

### Phases 3 to 5. Background, decision, hypotheses (one call, three gates)

1. Render the structured drafts call - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render drafts --set "ask=<topic and answers so far>" --set "digest=<digest>" --set "group=<group>" --set "owner=<decision owner>" --set "evidence_total=<from the digest>" --set "feedback_gap=<true|false>"` - and run it as this run's SECOND model call. It returns ONE JSON object: background, resources, decision, decision_shape, hypotheses, assumptions.
2. Walk the three gates on the pre-drafted content; no re-call per phase:
   - **Phase 3 (Wait)**: show background + resource list with share tags. Ask for edits; apply verbatim.
   - **Phase 4 (Wait)**: show the decision, then run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" decision "<decision text>"`. A good shape (`good: true`) prints `This matches a good shape (<shape words>: one sentence, named owner). Approve, or edit?`; a bad shape (`good: false`) shows what is wrong and proposes a tightened version with an owner before waiting.
   - **Phase 5 (Wait)**: show hypotheses/assumptions as `Label. Claim.` lines. Push back with a rewrite when claims are not falsifiable, mix mechanisms, or ignore the decision (craft bars are in the drafts prompt). Wait for edits.

### Phase 6. Research questions and the mandatory HCD gate (**Wait**)

1. Save the phase 5 set to a temp spec JSON and run `python "${CLAUDE_PLUGIN_ROOT}/scripts/trace_prompts.py" --rq-map <spec.json>`. Drop an RQ in the `unmapped` list, and say you dropped it and why.
2. Fact-check first (citations/counts/stances come from the gates that already ran), then assemble the gate input and run it as this run's THIRD model call: `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render hcd-gate --set "artifact=<draft spec>" --set "artifact_kind=draft" --set "factcheck=<the settled JSON>"`, dispatched to the `hcd-researcher` agent (Task tool, `subagent_type: hcd-researcher`). It judges only the qualitative residual and ends with `verdict: {"result": "pass"|"p0", "p0": [...]}`.
3. Fold every finding in, or record a one-line decline. Print the agent's Summary, Risks, and What to change verbatim, plus your fold-in or decline per finding. Re-invoke only on `p0`, after the fix. Wait for the user's go-ahead on the revised set.

### Phase 7. Method, sample, investment (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" method --rqs "<RQ1; RQ2; ...>"`.
Show its output as: method, reason (the shape), sample size, session length,
investment level, and the alternative when one exists (omit the Alternative
line when the script returns it empty). Research type comes from the
decision: a shipping decision is Evaluative; a direction or opportunity
question is Generative or Strategic. Wait for the pick. Overrides accepted.

### Phase 8. Fields, preview, create (**Wait**, the last gate)

Resolve routing with the routing section of `references/tracker.md`:

- Role `uxr`: assignee and UX Researcher are the current user.
- Role `manager`/`stakeholder`: both go to `resolve_researcher(<group>, <routing>)` (lib/field_map.py). Print `notes[0]` verbatim when its `notes` list is non-empty. Offer the `fallbacks` chain when the user marks the primary out of office.

Show the field panel, one line each, with value and source: Group (`pod`),
research type, method, support level, investment, outcomes (`outcome`),
UX Researcher (`uxr`), assignee, priority `tracker.default_priority`; start
date: today to today + `defaults.start_window_days` days; labels
`<topic-slug>, <quarter>` (slug: lowercase, non-alphanumeric runs become one
hyphen; quarter: current `YYYY-QN`). Accept overrides.

Then the preview: item type (`tracker.study_item_type`), summary (working
title), people, labels, resolved field payloads, a body STRUCTURE summary
(the ten template blocks, one line each; never the raw rich text), and the
count of resources whose share check succeeded. Wait for `yes`, `create`,
or `go`.

## Build, validate, persist (shared with `init`)

1. Assemble the spec in memory: `history`, `decision`, `hypotheses` (`{label, text}`, never empty), `assumptions`, `resources` (`{label, url or text, share_status, share_note}` from phase 2.5), `research_questions` (never empty), `sample_size`, `persona`, `session_length`, `results` (null unless `retro`), `study_title`, `method_key` (`interview` or `survey`; `survey` only when the method is Survey), `channel` (`internal`/`external`/`mixed`), the people names `init` reads (`uxr`, `pm`, `pd`, `em` owners when gathered), `jtbd_refs`, `persona_refs` (with ring tags), `slack_channel`.
2. Pipe it through `python "${CLAUDE_PLUGIN_ROOT}/scripts/build_body.py"` (spec JSON on stdin). Non-zero exit: print stderr verbatim, write nothing, call no tracker tool, return to the interview phase that owns the failing content. Empty hypotheses exits 3 and never reaches `create_item`.
3. `create_item` (`references/tracker.md`) with `tracker.study_item_type`, summary, rendered body, resolved field payloads. The plugin's only create call; runs only after the phase 8 gate.
4. Read the body back (`get_item`), save to a temp file, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" check-readback --file <readback file>`. Report any miss and stop before the next step.
5. Save the draft spec to a temp JSON file, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" save-spec --key <KEY> --file <draft file>`. Non-zero exit: say the ticket exists but the spec is not saved, point to `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`, stop before the scaffold.
6. Print `Created [KEY](url)`, then run `init KEY` in the same turn (the `uxr-init` command) and list next steps (script, recruit, sessions). When `commands/uxr-init.md` is absent, print `init is not in this build yet; the ticket and spec are ready.` and stop.

## Fast path (`fast` in the input)

Skip phases 1 to 7. Ask for the topic in one line if the input names none.
Use `defaults.fast_path` values for group, research type, method,
investment, support, outcomes; run `current_user()` and routing exactly as
in phase 0/8. Validator requires: ask in ONE message for one hypothesis
(`Label. Claim.`), one open RQ, and a yes on the one-line decision you
propose from the topic. Then run the build block.

## Retro path (`retro` in the input)

Input is a workspace path or Drive folder link for a finished study.

1. List visible artifacts (files or Drive listing); ask "Correct?".
2. Derive from the files ONLY: history, decision, hypotheses, assumptions, RQs, method, sample, 2-3 sentence `results`.
3. Ask before adding scope the files do not support.
4. Run the build block. No `init`: a finished study gets no new workspace.

## Safety gates

- Preview before create; the only create call runs after the phase 8 approval word.
- Per-candidate "yes" for local-to-Drive matches; never change a Drive permission.
- Validation failure = zero writes (no tracker calls, no spec file).
- The HCD gate runs before phase 7; a one-line decline is the only substitute (`Declined hcd-researcher review: <one line why>`); `p0` always re-invokes after the fix.
- A synthetic persona needs a user yes before use.

## Voice

Lead with the result. No em dashes. One phase's questions at a time. When a
tool fails, print the `<Tool>: unavailable (skipped)` line and continue;
never fake a source.
