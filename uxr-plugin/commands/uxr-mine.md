---
description: "List your studies in the tracker project: open ones by default, everything with the argument `all`"
argument-hint: "[all]"
---

Read-only list of the tracker items assigned to the current user in the study
project. The model calls only `current_user()` and `search(filter)` (the read
rows of `references/tracker.md`); the render is a script. It never calls
`create_item`, `update_item`, `set_state`, or `add_comment`, and it writes no
file outside the one temp JSON.

Input: `$ARGUMENTS`. The word `all` alone (case-insensitive) includes closed
statuses. Anything else, including no input, means the default open-only view.

Steps:

1. Setup: render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `tracker.kind`, `tracker.project_key`, and `tracker.closed_states`.
2. Call `current_user()` (the `current_user()` row of the `tracker.kind`
   column in `references/tracker.md`). Cache it for the session. On failure,
   print the error and stop.
3. Call `search(filter)` and read the first page only; never fetch a second.
   The filter selects items in `<project_key>` assigned to the current user,
   newest update first. Default: exclude every status in `<closed_states>`.
   With `all`: no status clause. Ask the search for the fields the table
   needs: key, status, item type, priority, summary, and last update time.
   Jira reference, built from the config values (quote values that contain
   spaces):

   `project = <project_key> AND assignee = <current user account id> ORDER BY updated DESC`

   with `AND status not in (<closed_states>)` appended unless the argument is
   `all`.
4. Write one temp JSON file of mechanical field copies - no judgment, no
   renaming: `{"project_key": <project_key>, "mode": "default" or "all",
   "now": <ISO now>, "items": [{"key", "url" (from `item_url`), "status",
   "type", "priority" (or null), "summary", "updated"}]}` in the order the
   search returned.
5. Run `python "${CLAUDE_PLUGIN_ROOT}/lib/render.py" mine <rows.json>`
   and print its stdout verbatim, then stop. It prints the one table
   (`Key | Status | Type | Pri | Summary | Updated`) and the footer
   (`N open`, or `N total` with `all`), or the exact one-line empty case
   (`No open <project_key> issues assigned to you.` / with `all`:
   `No <project_key> issues assigned to you.`). Print no other prose.
