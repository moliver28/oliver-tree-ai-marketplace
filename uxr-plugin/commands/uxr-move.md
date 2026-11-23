---
description: "Move a study ticket to its next phase, gated on readiness: Recruiting needs a roster, Done needs results"
argument-hint: "<KEY> [<status name> | <number>]"
---

Move a study ticket through its phases: one tracker transition, gated on a
readiness check per target phase; finish checks warn when a move to Done
leaves gaps behind. Ops from `references/tracker.md`: `get_item`,
`list_state_changes`, `set_state`, `item_url`, `find_user`; never
`create_item`, `update_item`, `add_comment`, and never writes the spec
file.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` takes one of three shapes:

1. `<KEY>`: list the available moves and ask.
2. `<KEY> <status name>`: match a shown move by name, case-insensitive,
   ignoring whitespace differences, as a substring in either direction
   (`writing script /survey` matches `Writing Script / Survey`). Ask when
   the name matches more than one move.
3. `<KEY> <number>`: the 1-based index into the list this run showed.

## Steps

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `tracker.kind`, `tracker.project_key`, `tracker.ticket_regex`, `tracker.bare_number_prefix`, `paths.state_dir`, and the `ssot.*` keys.

2. Parse `$ARGUMENTS`: the ticket key and an optional target (a status
   phrase or a number). Normalize the key with the `normalize_key` rule
   (`references/tracker.md`) and refuse a key outside the study project the
   way `show` does; never search for it.

3. Call `get_item` once: the live status name, the fields of every
   configured `fields.*` entry, the body (Markdown format), and the URL
   from `item_url(key)`.

4. Call `list_state_changes(KEY)` now -- the live list, in this session,
   never a remembered one. Print, then the numbered list, one move per line
   in the order the tracker returned:

   `<KEY> is currently **<status>**. Available moves:`

   ```
   ABC-42 is currently **Planned**. Available moves:
   1. Writing Script / Survey
   2. Blocked
   ```

5. Resolve the target.
   - A number: that line of the list you just printed. Out of range: say
     so, show the list again, and ask.
   - A status name: normalize both sides (lowercase, all whitespace
     removed) and match as a substring in either direction against the
     shown names. Exactly one hit: use it. Several hits: show only the
     matching lines, numbered as in the list, and ask. No hit: say the
     status is not an available move from here, show the list, and stop.
   - No target given: show the list and ask.

6. **Readiness gate.** Run it for every target; the gate itself knows
   which statuses are gated. Write the fields object from step 3 to a
   temporary file as JSON, then run:

   `python "${CLAUDE_PLUGIN_ROOT}/lib/phase_gates.py" check --status "<resolved target name>" --spec <spec path> --fields <fields file>`

   The spec path is `<state_dir>/specs/<KEY>.spec.json`. When that file
   does not exist, recover a spec read-only instead: pipe the live body
   from step 3 through
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`, write the
   recovered JSON to a temporary file, and pass that path. Never save a
   recovered spec into `specs/` -- `move` never writes the spec file, not
   even `_meta.tracker_updated_at`.

   Exit codes: 0 means the gate passed (an ungated target passes with an
   empty missing list); 1 means blocked; 2 is a usage or config error --
   print the error and stop. On 1, save the gate's JSON output to a
   temporary file and print verbatim the output of:

   `python "${CLAUDE_PLUGIN_ROOT}/lib/phase_gates.py" missing --json <file> --key <KEY>`

   one line per missing item, in the golden format:

   `missing: spec check failed: 'roster_has_scheduled' -> run edit UXR-101 roster~=Name|status=Scheduled`

   Then stop. `set_state` is never called for a blocked move. Offer nothing
   beyond the fix lines until the user changes something.

7. **Finish checks** -- only when the resolved target is Done (the same
   contains match against `Done`). Warn, never block; show all gaps
   together, each with the fix that closes it, and then continue with the
   move:
   - The output link field is set (`fields.output`). Fix:
     `edit <KEY> output=<url>`.
   - A deliverable file name matches `ssot.finished_title_pattern`
     (check the workspace `deliverables/` folder). Fix: rename the file to
     match the pattern.
   - The file sits in the product-area subfolder of
     `ssot.finished_artifacts_folder_id` (check the folder listing on
     Drive). Fix: move the file into the area subfolder.
   - The ticket links the file (in the body or the issue links). Fix:
     `edit <KEY>` with the link added to a section, or attach it in the
     tracker.
   When a check needs a Drive or workspace listing that is unavailable,
   say so as its own gap instead of guessing.

8. **Transition.** Call `set_state` with the transition `id` from the step
   4 list -- never the name, never a remembered id. If the tracker rejects
   the transition because a field is required (for example a resolution on
   Done), show the error, ask for the value, resolve it (`find_user` for
   users, `lib/field_map.py resolve` for the rest), set the field, and
   retry the same transition once. A second failure: show the error and
   stop, still un-moved.

9. Print exactly one line:

   `Moved [KEY](url) to **<status>**.`

   with the URL from `item_url(key)` and the live status after the move
   when the tracker returns it, otherwise the target name. Add nothing
   else -- suggestions and next steps are not part of `move`.
