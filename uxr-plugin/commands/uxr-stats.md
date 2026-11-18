---
description: "Plugin adoption rollup from the session journal and usage counts: read-only, prints the script output verbatim"
argument-hint: "[--json] [--days=<N>]"
---

Report how much the plugin is used, from two independent data sources:
the session journal the SessionEnd hook writes, and the consent-gated
usage counts (collected only when the user opted in). The two are never
joined: analytics ids are salted hashes, journal ids are not.

Read-only: it runs one script and prints its output. It computes
nothing itself.

## Steps

1. Run, exactly:

   `python "${CLAUDE_PLUGIN_ROOT}/scripts/uxr_stats.py" $ARGUMENTS`

   `$ARGUMENTS` accepts `--json` and `--days=<N>`; anything else is a
   usage error the script reports itself (exit 2). Print the script's
   stdout verbatim, then stop. Never restate, summarize, or recompute
   its numbers, and never add commentary between the output and your
   closing line.

2. On exit 2 (no usable state directory), print the script's stderr
   message and nothing else.

3. Close with exactly one line: `Stats are local to this machine; the
   usage counts are anonymous and never joined with the journal.`

## Notes

- `--json` prints one JSON object with `journal` and `analytics` under
  separate keys (`distinct_sessions`, `command_adoption`,
  `files_edited_total`, `tracker_tool_calls_total`, `unprocessed_count`;
  `total_events`, `event_type_counts`, `tool_failed_by_kind`). When the
  user asks to automate over the numbers, point them at `--json` instead
  of parsing the text view.
- `--days=<N>` restricts the journal files to the last N days and the
  event files to months overlapping that window.
- Journal rows are deduped by `session_id` (the latest `ended_at` wins),
  so a session rewritten across days never counts twice.
