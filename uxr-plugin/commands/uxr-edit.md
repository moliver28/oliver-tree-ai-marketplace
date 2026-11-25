---
description: "Edit one study ticket with shorthand keys: template sections go through the spec, tracker fields go through the adapter, one write per run"
argument-hint: "<KEY> [key=value ...]"
---

Edit a study ticket without breaking its template: sections and the roster
patch the spec (the source of truth), validate, and push as one full body;
tracker fields resolve through `lib/field_map.py`. One run makes at most one
`update_item` call. Writes only through the `references/tracker.md` ops
`get_item`, `find_user`, `update_item`, `add_comment`, `item_url`; never
`create_item` or `set_state` -- `edit` never moves a ticket.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` takes one of three shapes:

1. `<KEY>` alone: read the ticket, show it, and ask what to change.
2. `<KEY> key=value ...`: one or more shorthands; apply after a confirm.
3. `<KEY> "free text"`: a quoted sentence instead of shorthands; translate
   it into a section update or a comment (step 4).

## Shorthand keys

| Kind | Keys |
|---|---|
| Spec scalars | `history=`, `decision=`, `results=`, `sample=` (to `sample_size`), `persona=`, `length=` (to `session_length`), `artifact=`, `questions=` |
| Spec lists | `hypotheses+=label\|text`, `hypotheses~=label\|field=value`, `hypotheses-=label`; same for `assumptions`; `resources+=label\|url_or_text\|share_status\|share_note`, `resources~=`, `resources-=`, `roster+=Name\|email\|slack\|reason\|status\|channel`, `roster~=Name\|field=value`, `roster-=Name` |
| Fields | every shorthand in the issue 03 field table (`lib/field_map.py`); multi-select fields accept `=A,B` (replace), `+=A` (add), `-=A` (remove) |
| Standard | `summary=`, `assignee=me\|<name>`, `priority=`, `labels=a,b` or `labels=+x`, `duedate=`, `description=` |

Spec-path keys: the spec scalars and every list operation in the table
above; everything else is a field-path key. Any spec-path key routes the
whole run through the spec path; a field-only run skips steps 6 to 9 and
go straight to step 10.

Special rules:

- `artifact=<url>` writes the spec's `artifact_link` AND resolves a
  `script=<url>` field payload in the same call. It never writes the output
  link field; `output=` is the only shorthand that does.
- A Drive URL in `resources` triggers a permission check every time (step
  7c). A local path triggers the local-to-Drive flow from issue 06 (step
  7d).
- `assignee=me` resolves to the cached current user (`references/tracker.md`
  session rules); `assignee=<name>` resolves with `find_user`.
- `description=` replaces the entire ticket body. Warn, require an explicit
  yes, and refuse to combine it with spec-path shorthands in one run;
  prefer sections.

## Steps

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `tracker.kind`, `tracker.project_key`, `tracker.ticket_regex`, `tracker.bare_number_prefix`, `paths.state_dir`, `paths.research_root`, the `comments.footer`, `recruit.statuses`, and every entry under `fields` (shorthand name, `id`, `kind`, `values`).

2. Parse `$ARGUMENTS`. The first token is the ticket key. The rest are
   `key=value` shorthands split on whitespace (a value may be quoted to
   hold spaces), or exactly one quoted free-text string. Normalize the key
   with the `normalize_key` rule (`references/tracker.md`) and refuse a key
   outside the study project the way `show` does; never search for it.

3. No shorthand and no free text: call `get_item` once and render it the way `show` renders it now - through `lib/render.py show` (the canonical item JSON, `commands/uxr-show.md` step 5). Then ask
   `What should change? For example: history=<text>, method+=Survey, roster+=Name|email|slack|reason|status|channel, priority=High`
   and stop. Continue at step 6 or 10 with whatever the user answers.

4. Free text (step 2 input shape 3): this is the command's exception lane (the one metered model call). Decide what it is and say which you picked.
   - It reads like a note for the team ("add a note ...", an aside, a
     status remark): treat it as a comment request.
   - It answers "what happened before this" or "what did we learn": propose
     it as `history=<text>` or `results=<text>`, show the proposed
     shorthand, and continue at step 6 with the user's confirm.
   - It is ambiguous: ask.

5. Comment request: call `add_comment` once, with the text verbatim, then
   one blank line, then the `comments.footer` with your display name. It
   never touches the body and never loads the spec. When the run also has
   shorthands, post the comment after the update call succeeded. Then stop.

6. Spec path begins: with at least one spec-path shorthand, load
   `<state_dir>/specs/<KEY>.spec.json`.
   - The file is missing: print exactly this line and nothing else:

     ```
     No spec found for <KEY>. Cannot edit sections; recreate the ticket via `new` or run a one-time backfill: `backfill_spec.py`
     ```

     Then stop. Make zero tracker calls for the rest of the run -- no
     `get_item`, no `find_user`, no write. Never auto-migrate, never run
     `backfill_spec.py` yourself.

7. Spec-path preparation, in order:
   a. **Drift check.** Call `get_item` once, read the live `updated` time.
      When it differs from `_meta.tracker_updated_at` (including unset),
      print exactly `<KEY> was edited in the tracker after the spec was last saved; recompiling will overwrite that change`
      and wait for go or cancel. Keep the fields from this read; they feed
      steps 9 and 12.
   b. **Patch the spec in memory.** Scalars assign; `questions=` splits on `|` or literal newlines into
      trimmed, non-empty strings. List operations go through
      `scripts/parse_shorthand.py`: pipe one JSON request per operation --
      `{"kind": "roster|hypotheses|assumptions|resources", "op": "+=|~=|-=", "arg": "<pipe string>"}`
      -- and apply the printed delta. `+=` appends; `~=` matches rows by
      case-insensitive substring on name/label and patches that field; `-=`
      removes the exact case-insensitive match. Zero or several matches:
      show what matched, ask, change nothing until the user picks.
   c. **Drive permission check.** For every resources row added or patched
      with a Drive URL: read current sharing (never a permission change) and
      set `share_status` to what you observe -- team domain, `private`, or
      `unknown` when undeterminable. Say what you found in the preview.
   d. **Local path.** A resources row holding a local path is invalid; stop
      before writing and run the issue-06 local-to-Drive flow: search Drive
      for a match, propose candidates one at a time for yes/no, upload only
      on an explicit yes. Never write a local path into the spec.
   e. **Validate and render in one call.** Pipe the patched spec JSON into
      `python scripts/build_body.py`. Non-zero exit writes nothing: exit 3
      is a validation failure, exit 4 an incomplete document; print the
      `  - <error>` lines from stderr verbatim, save no file, make no
      tracker call, stop. (A bad roster status dies here with exit 3 -- the
      "nothing is written" guarantee.)

8. **Preview and gate.** Show a diff preview and wait for `yes`, `go`, or
   `apply` (anything else cancels and writes nothing):

   ```
   ABC-42 (proposed updates):
     history:   [placeholder] → "..."
     pod:       [unset]       → Platform
     roster:    2 rows → 3 rows (added Ada Example)
     method:    + Survey
   ```

   One line per change: `  <name>:<spaces> <old> → <new>`. Old is
   `[placeholder]` for template placeholder text, `[unset]` when empty or
   absent; quote string values; list edits summarize rows before and after.
   Field changes show the resolved payload (`method: + Survey`,
   `priority: → High`, `uxr: → <resolved name>`) after applying the
   `__op__` wrappers of `lib/field_map.py` payloads against the step 7a
   live values and resolving every `{"__resolve_user__": token}` with
   `find_user` (`me` is the cached current user). Resolve shorthands with
   `python "${CLAUDE_PLUGIN_ROOT}/lib/field_map.py" resolve --shorthand "<shorthand>"`.

9. **Save and push, in this order.** On `yes`, `go`, or `apply`:
   a. Save the spec file (pretty-printed, indent 2) with `_meta` updated:
      `last_edited_at` = now in ISO 8601 UTC, `last_edited_by_command` =
      `edit`, `session_id` = `$CLAUDE_SESSION_ID`, `transcript_path` = the
      current session transcript path when the environment provides one.
      Keep `created_at` and every other `_meta` key unchanged.
      Then run `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py" assert-ask --file <spec path>`
      and print its line verbatim: `ask OK` continues; `ask missing (pre-ask
      spec)` records the legacy gap and continues; exit 5 prints the gap
      line and stops before the update call. The ask keys are never edited
      through the shorthand table - up-levels live only in `ask_uplevels`.
   b. Push the full body AND the resolved field payloads in one
      `update_item` call. The body is the whole rendered document from step
      7e -- never a fragment.
   c. Read the live `updated` time back from the same call's response (or
      one `get_item`), save it to `_meta.tracker_updated_at`, and save the
      spec file again.

10. Field-only path: no spec load, no body push. Preview the resolved
    payloads (step 8 format), gate on the same words, then one
    `update_item` call with the fields only -- no description or body
    parameter at all. (`assignee=` and `description=` are not configured
    fields: assignee writes the tracker's standard assignee, description
    follows its own warning rule.)

11. **Refresh the workspace overview.** Run
    `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`.
    When it prints `WORKSPACE_NOT_FOUND`, print one line
    `No local workspace for <KEY>; skipping the overview refresh.` and
    continue. Otherwise run
    `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" render-overview --ticket <KEY> --readme <research_root>/README.md --spec <spec path>`.

12. **Suggest the next phase.** Run
    `python "${CLAUDE_PLUGIN_ROOT}/lib/phase_gates.py" suggest --status "<live status from step 7a>" --spec <spec path> --fields <fields file>`
    where the fields file holds the fields object from the step 7a read as
    JSON. When the command prints a phase name, print exactly:
    `This ticket now meets the bar for <phase>. Run move <KEY> <phase> to advance it.`
    When it prints nothing, say nothing about phases. Never transition from
    `edit` -- `move` owns transitions.
