---
description: "Show one study ticket: header lines, UXR fields, description, linked issues, and the latest comments"
argument-hint: "<KEY>"
---

Read-only view of one ticket. The model calls only `get_item(key, fields,
format)`, `item_url(key)`, and the `normalize_key` prefix rule (the read rows
of `references/tracker.md`); the render is a script. It never calls
`create_item`, `update_item`, `set_state`, or `add_comment`.

Input: `$ARGUMENTS`: one ticket key or a bare number.

Steps:

1. Setup: render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `tracker.kind`, `tracker.project_key`, `tracker.bare_number_prefix`, `tracker.ticket_regex`, and the `id` of every entry under `fields`.
2. No argument (empty after trimming): print exactly
   `Which issue? (e.g. <PREFIX>-42 or just 42)`
   where `<PREFIX>` is `tracker.bare_number_prefix`, and stop.
3. Normalize the argument with the `normalize_key` rule
   (`references/tracker.md`):
   - digits only: it becomes `<PREFIX>-<digits>`.
   - matches `tracker.ticket_regex`: it is used unchanged.
   - looks like `<WORD>-<digits>` but fails `tracker.ticket_regex` (a key from
     another project): refuse and ask. Print
     `<ARGUMENT> is in another project; this plugin reads the <project_key> study project only. Which <project_key> issue did you mean?`
     and stop. Never search for it.
   - anything else: print the step 2 question and stop.
4. Call `get_item` once, in Markdown format (Jira:
   `responseContentFormat: markdown`), with the tracker's standard fields
   (`summary, status, issuetype, priority, assignee, reporter, created,
   updated, labels, description, issuelinks, comment`) plus the field `id`
   of every entry under `fields`.
5. Write one temp JSON file of mechanical field copies - no judgment, no
   re-shaping: `{"now": <ISO now>, "item": {"key", "url" (from `item_url`),
   "summary", "status", "type", "priority", "assignee", "reporter",
   "created", "updated", "labels": [...], "description" (the verbatim body),
   "issuelinks": [{"type", "key", "url", "summary", "status"}],
   "comments": [{"author", "created", "body"}] newest first,
   "fields": {"<shorthand>": {"kind", "value" or "values"/"name"/"start"
   and "end"}}}}`. Field kinds: single_select and single_name carry
   `value`; multi_select `values`; user `name`; interval `start` and `end`;
   date `value`; url `value`. Copy empty fields too - the script drops empty
   blocks.
6. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/render_view.py" show <item.json>`
   and print its stdout verbatim, then stop. The script owns the whole card:
   the header line, the meta lines (`·`-separated), the UXR fields table
   (the 19 fixed rows in `prompts/render/show.json`, empty rows dropped),
   the description verbatim, linked issues, at most 5 newest comments, the
   relative-time ladder, and the emoji shortcode conversion (the 12-entry
   map in `prompts/render/show.json`; an unmapped shortcode stays as
   written). Print no other prose.
