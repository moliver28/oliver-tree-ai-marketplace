---
description: "List your studies in the tracker project: open ones by default, everything with the argument `all`"
argument-hint: "[all]"
---

Read-only list of the tracker items assigned to the current user in the study
project. It calls only the read operations in `references/tracker.md`:
`current_user()`, `search(filter)`, and `item_url(key)`. It never calls
`create_item`, `update_item`, `set_state`, or `add_comment`, and it writes no
file.

Input: `$ARGUMENTS`. The word `all` alone (case-insensitive) includes closed
statuses. Anything else, including no input, means the default open-only view.

Steps:

1. Read configuration once: run `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`
   (when `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin
   directory that holds `lib/`, `config/`, and `references/`). Note
   `tracker.kind`, `tracker.project_key`, and `tracker.closed_states`. Every
   `<placeholder>` below is filled from that output; hardcode nothing.
2. Call `current_user()` (the `current_user()` row of the `tracker.kind`
   column in `references/tracker.md`). Cache it for the session. On failure,
   print the error and stop.
3. Call `search(filter)` and read the first page only; never fetch a second
   page. The filter selects items in `<project_key>` assigned to the current
   user, newest update first. Default: exclude every status in
   `<closed_states>`. With `all`: no status clause. Ask the search for the
   fields the table needs: key, status, item type, priority, summary, and
   last update time. Jira reference, built from the config values (quote
   values that contain spaces):

   `project = <project_key> AND assignee = <current user account id> ORDER BY updated DESC`

   with `AND status not in (<closed_states>)` appended unless the argument is
   `all`.
4. Empty result: print exactly one line and nothing else (no table, no footer,
   no other prose):
   - default: `No open <project_key> issues assigned to you.`
   - `all`: `No <project_key> issues assigned to you.`

   In both sentences `<project_key>` is replaced by the value of
   `tracker.project_key`.
5. Non-empty result: render exactly one table and one footer line, and no
   other prose. The columns are `Key | Status | Type | Pri | Summary | Updated`:

   | Key | Status | Type | Pri | Summary | Updated |
   |---|---|---|---|---|---|
   | [ABC-42](<url>) | In Progress | Idea | Medium | Example study | 2d ago |

   Link each key with `item_url(key)` (`references/tracker.md`). Pri is the
   priority value, or `-` when the item has none. Updated is relative, from
   now minus the last update time, rounded down: under a minute `just now`,
   then `<N>m ago` under an hour, `<N>h ago` under 24 hours, `<N>d ago` under
   7 days, `<N>w ago` under 30 days, `<N>mo ago` under a year, otherwise
   `<N>y ago`.
6. Footer: default `N open`, where N is the number of table rows; with `all`
   the footer is `N total`.
