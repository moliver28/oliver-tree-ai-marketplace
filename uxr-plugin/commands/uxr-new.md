---
description: "Open a study: guided interview, parallel evidence sweep, drafts of the background, decision, hypotheses, and research questions that you refine, a method recommendation, routing to the right researcher, and a preview before anything is created"
argument-hint: "[topic | notes | fast | retro]"
---
Create a study ticket: guided interview, ONE parallel evidence sweep, one structured drafts call, method pick, HCD gate, preview, create. Three model calls on the golden path (phases 2, 3–5, 6); everything else is scripts.

## Inputs (`$ARGUMENTS`)

| Input | Behavior |
|---|---|
| empty | Full interview, phases 1 to 8 |
| a topic phrase | Full interview, topic filled in |
| a paragraph of notes | Targeted: run the sweep, ask only for the gaps the notes leave |
| contains `fast` | Fast path below: no interview |
| contains `retro` | Retro path below: ticket from a finished study's files |

`fast`/`retro` win over the other paths.

Grounding: registered sources in `references/sources/` (here: R-01 method pages); page-first; cite URL with claim. Index: `references/research-sources.md`.

## Setup (once)

1. Render the canonical block (`python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup`) and follow it.
2. Phase 0. Call `current_user()` (the `current_user()` row of the `tracker.kind` column in `references/tracker.md`) once; cache it. `detect_role(<display name>, <routing>)` (routing section of `references/tracker.md`) returns `uxr`, `manager`, or `stakeholder`; role changes routing only.

## Phases (full interview)

One phase at a time. **Wait** phases end with a question, then stop; never pre-fill the next while waiting. Record answers verbatim, in the user's own words; never paraphrase, never fill an answer the user did not give - record the gap.

### Phase 1. Topic and scope (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render new-intake --set "pod_options=<comma list of the configured fields.pod values, joined with , or>"`, print its stdout verbatim, stop.

### Phase 2. Evidence sweep (no waiting after it)

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" plan --topic "<topic>"` (`--tactical` for a build-or-ship question one team answers this quarter); it prints one query spec per enabled source in `evidence.sources`.
2. Fire EVERY planned source in ONE parallel batch of tool calls, exactly per plan; no sequencing. A failed source call is logged, not retried twice.
3. Save every raw result to one temp file; run `python "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_sweep.py" digest --results <file> --topic "<topic>" --topic-class "<first-run adoption | churn | satisfaction | other>"`. The digest is then the only evidence input; never read, quote, or synthesize from raw results.
4. Run as this run's FIRST model call: `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render signals --set "topic=<topic>" --set "digest=<the digest JSON, one line>"`. It writes only the four Top signals lines under the script's `Top signals` heading. Print the whole block verbatim (table, unavailable lines, Top signals).

### Phase 2.5. Shareability (mandatory, same turn)

Tag each digest-surfaced Drive URL `shared` (team domain or anyone-with-link at Commenter+), `private` (owner only), `unknown` (check failed: say so; never guess). Never change a permission. Never put a local path in Resources: search Drive for a match, get a separate "yes" per candidate before linking.

### Phases 3–5. Background, decision, hypotheses (one call, three gates)

1. Run as this run's SECOND model call: `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render drafts --set "ask=<topic and answers so far>" --set "digest=<digest>" --set "group=<group>" --set "owner=<decision owner>" --set "evidence_total=<from the digest>" --set "feedback_gap=<true|false>"`. Returns ONE JSON object: background, resources, decision, decision_shape, hypotheses, assumptions.
2. Walk the three gates on the pre-drafted content; no re-call per phase:
   - **Phase 3 (Wait)**: show background + resource list with share tags; ask for edits; apply verbatim.
   - **Phase 4 (Wait)**: show the decision, then run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" decision "<decision text>"`. Good shape (`good: true`) prints `This matches a good shape (<shape words>: one sentence, named owner). Approve, or edit?`; bad shape (`good: false`): show what is wrong, propose a tightened version with an owner, wait.
   - **Phase 5 (Wait)**: show hypotheses/assumptions as `Label. Claim.` lines; push back with a rewrite when claims are unfalsifiable, mix mechanisms, or ignore the decision (craft bars: drafts prompt); wait for edits.

### Phase 6. RQs and the mandatory HCD gate (**Wait**)

1. Save the phase 5 set to a temp spec JSON; run `python "${CLAUDE_PLUGIN_ROOT}/scripts/trace_prompts.py" --rq-map <spec.json>`. Drop any `unmapped` RQ; say why.
2. Fact-check first (citations/counts/stances come from gates already run), then run the gate as this run's THIRD model call: `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render hcd-gate --set "artifact=<draft spec>" --set "artifact_kind=draft" --set "factcheck=<the settled JSON>"`, dispatched to the `hcd-researcher` agent (Task tool, `subagent_type: hcd-researcher`). It judges only the qualitative residual; ends with `verdict: {"result": "pass"|"p0", "p0": [...]}`.
3. Fold every finding in or record a one-line decline. Print the agent's Summary, Risks, What to change verbatim plus your fold-in or decline per finding. Re-invoke only on `p0`, after the fix. Wait for go-ahead on the revised set.
4. Prior reviews (retro path, workspace resolved): run `python "${CLAUDE_PLUGIN_ROOT}/scripts/researcher_state.py" digest --key <study key>` (overview `Ticket:` line match, else workspace folder name); paste printed reviews into the step 2 gate input's study context under a `Prior reviews:` line; `no prior reviews` continues unchanged.
5. The gate input's study context opens with the verbatim ask: `Original ask: <the user's recorded ask, word-for-word from the interview>`.

### Phase 7. Method, sample, investment (**Wait**)

Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" method --rqs "<RQ1; RQ2; ...>"`. Show: method, reason (the shape), sample size, session length, investment level, alternative when one exists (omit the Alternative line when the script returns it empty). Research type from the decision: shipping = Evaluative; direction or opportunity = Generative or Strategic. Wait for the pick. Overrides accepted.

### Phase 8. Fields, preview, create (**Wait**, the last gate)

Routing (routing section of `references/tracker.md`): role `uxr` - assignee and UX Researcher are the current user; role `manager`/`stakeholder` - both go to `resolve_researcher(<group>, <routing>)` (lib/field_map.py), print `notes[0]` verbatim when its `notes` list is non-empty, offer the `fallbacks` chain when the user marks the primary out of office.

Show the field panel, one line each with value and source: Group (`pod`), research type, method, support level, investment, outcomes (`outcome`), UX Researcher (`uxr`), assignee, priority `tracker.default_priority`; start date today to today + `defaults.start_window_days` days; labels `<topic-slug>, <quarter>` (slug: lowercase, non-alphanumeric runs become one hyphen; quarter: current `YYYY-QN`). Accept overrides.

Preview: item type (`tracker.study_item_type`), summary (working title), people, labels, resolved field payloads, body STRUCTURE summary (ten template blocks, one line each; never raw rich text), and the count of resources whose share check succeeded. Wait for `yes`, `create`, or `go`.

## Build, validate, persist (shared with `init`)

1. Assemble the spec in memory: `history`; `decision`; `hypotheses` (`{label, text}`, never empty); `assumptions`; `resources` (`{label, url or text, share_status, share_note}`, from phase 2.5); `research_questions` (never empty); `sample_size`; `persona`; `session_length`; `results` (null unless `retro`); `study_title`; `method_key` (`interview`/`survey`; `survey` only when the method is Survey); `channel` (`internal`/`external`/`mixed`); people names `init` reads (`uxr`, `pm`, `pd`, `em` owners when gathered); `jtbd_refs`; `persona_refs` (with ring tags); `slack_channel`. Ask keys: `ask_verbatim` (the user's ask, word-for-word from source; fast path uses the topic line), `ask_source` (where copied from, with a date), optional `ask_uplevels` (`{text, note}` up-levels; additive only, never a replacement).
2. Pipe through `python "${CLAUDE_PLUGIN_ROOT}/scripts/build_body.py"` (spec JSON on stdin). Non-zero exit: print stderr verbatim, write nothing, call no tracker tool, return to the interview phase owning the failing content. Empty hypotheses exits 3, never reaches `create_item`.
3. `create_item` (`references/tracker.md`) with `tracker.study_item_type`, summary, rendered body, resolved field payloads. The plugin's only create call, after the phase 8 gate only.
4. Read the body back (`get_item`), save to temp; run `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" check-readback --file <readback file>`. Report any miss; stop before the next step.
5. Save the draft spec to temp JSON; run `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" save-spec --key <KEY> --file <draft file>`. Non-zero exit: say the ticket exists but the spec is not saved, point to `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`, stop before the scaffold.
6. Print `Created [KEY](url)`; run `init KEY` same turn (`uxr-init`); list next steps (script, recruit, sessions). Without `commands/uxr-init.md`, print `init is not in this build yet; the ticket and spec are ready.` and stop.

## Fast path (`fast` in the input)

Skip phases 1 to 7; ask the topic in one line if none named. Use `defaults.fast_path` for group, research type, method, investment, support, outcomes; run `current_user()` and routing exactly as in phase 0/8. Validator requires in ONE message: one hypothesis (`Label. Claim.`), one open RQ, a yes on the one-line decision you propose from the topic. Then run the build block.

## Retro path (`retro` in the input)

Input: a workspace path or Drive folder link for a finished study.

1. List visible artifacts (files or Drive listing); ask "Correct?".
2. Derive from the files ONLY: history, decision, hypotheses, assumptions, RQs, method, sample, 2-3 sentence `results`.
3. Ask before adding scope the files do not support.
4. Run the build block; no `init` (a finished study gets no new workspace). Pass `--command retro` to `save-spec`: the study saves as retro; an ask the source files do not carry records `ask_verbatim` empty with `ask_source: "unrecovered"` instead of blocking.

## Safety gates

- Preview before create; the only create call follows the phase 8 approval word.
- Per-candidate "yes" for local-to-Drive matches; never change a Drive permission.
- Validation failure = zero writes (no tracker calls, no spec file).
- HCD gate before phase 7; the only substitute is a one-line decline (`Declined hcd-researcher review: <one line why>`); `p0` always re-invokes after the fix.
- A synthetic persona needs a user yes before use.

## Voice

Lead with the result. No em dashes. One phase's questions at a time. Tool fails: print the `<Tool>: unavailable (skipped)` line and continue; never fake a source.
