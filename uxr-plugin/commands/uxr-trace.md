---
description: "Show the evidence trail behind a study: sessions, sources, outputs, drift, and the prompts that got there"
argument-hint: "[<KEY> | --file=<path> | --source=<type> | --project | --timeline | --links | --prompts]"
---

Trace what a research session actually read and wrote, from the
provenance the SessionEnd hook records in each workspace's `.sessions/`
folder. Read-only: it never calls a tracker operation that writes, never
edits a file, and never invents a trace.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` takes exactly one of:

1. `<KEY>`: the trail for one ticket (a bare number like `42` is
   normalized with `tracker.bare_number_prefix`).
2. `--file=<path>`: every session where the file is an output or a
   `local_file` source.
3. `--source=<type>`: every session that read a source of that type
   (`drive`, `tracker`, `wiki`, `chat`, `feedback`, `notebook`, `mail`,
   `calendar`, `web`, `local_file`).
4. `--project`: the workspace overview (the default when no argument is
   given and the cwd is inside a workspace).
5. `--timeline`: sessions in chronological order.
6. `--links`: every source and output URL.
7. `--prompts`: the user prompts behind the key
   (`scripts/trace_prompts.py`).

When `$ARGUMENTS` is empty and the current directory holds `.sessions/`
or `00-overview.md`, treat it as `--project`; when it is empty outside a
workspace, ask which key to trace (one line, no command menu).

## Steps

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `paths.research_root`, `paths.state_dir`, `tracker.ticket_regex`, `tracker.bare_number_prefix`, `tracker.base_url`, and `tracker.kind`.
2. **No data: stop here.** Scan `<research_root>/*/.sessions/` and
   `<state_dir>/work-log-*.jsonl`. When there are no `.sessions/`
   folders and no journal rows at all, print exactly one line and stop:

   `No provenance data yet. It will start accumulating automatically in
   your next research session.`

   Never print a table, a summary, or a guess alongside it, and never
   reconstruct a trail from memory.
3. **Ticket trace (`<KEY>`)**: scan every
   `<research_root>/<workspace>/.sessions/` folder -- the
   `<ended_at>.json` session records and `provenance.jsonl` -- for the
   key (session records carry `ticket_keys`; edge lines carry
   `source_id` / `output`). Print:
   - `Sessions`: one line per session with the workspace name and
     `ended_at`.
   - `Sources by type`: deduped by `source_id`, grouped by type, each
     with the number of sessions that consulted it.
   - `Outputs`: each output with its type and the count of sources in
     its `informed_by` (for example
     `deliverables/summary.md - file_edit, informed by 3 sources`).
   - With a spec (see step 8), also the spec view for this key.
   - Relationship counts are a session audit trail, not proof that one
     source caused one claim; say so in one line under the outputs.
4. **File trace (`--file=<path>`)**: resolve the path relative to the
   workspace root when needed; list sessions where the file appears in
   `outputs` (with `informed_by` counts) or as a `file:` source.
5. **Project overview (`--project`)**: session count, date range
   (oldest to newest `ended_at`), commands used with session counts,
   tickets touched, unique sources by type (from the session records
   and `sources-index.json`), the most-consulted sources
   (`times_consulted`, top 5), and files produced (all `outputs`
   across sessions).
6. **`--timeline`**: one line per session, oldest first:
   `<ended_at>  <workspace>  <N> files edited  <ticket keys>`.
7. **`--source=<type>`**: sessions that read that type, with per-session
   counts and the consulted ids.
8. **Spec view (only when `<state_dir>/specs/<KEY>.spec.json` exists)**:
   show the raw spec, then a drift check, then the six `_meta` keys
   (`created_at`, `last_edited_at`, `last_edited_by_command`,
   `tracker_updated_at`, `session_id`, `transcript_path` -- print
   `(not set)` for a missing one). Drift: render the saved spec through
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/build_body.py" < spec` and
   diff the rendered body against the live tracker body from `get_item`
   (Markdown format). Identical: `Spec and tracker body match.` A diff
   means the tracker moved after the spec was saved -- print the diff
   and suggest `edit <KEY>` to reconcile. When the live body is
   unavailable, say so as its own line instead of guessing.
9. **`--prompts`**: run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/trace_prompts.py" <KEY>` and
   print its stdout verbatim. It prints `[{session_id, ts, text,
   origin}]` from the spec's `_meta.transcript_path` and the manifests,
   or `[]`; never restate or summarize its output, and never widen it.
10. **`--links`**: every source and output with its URL rendered as a
    Markdown link (`[label](url)`). A search or query has no stable URL
    -- render its query text in a code span instead. Never invent a URL
    that the manifests do not carry.
11. Empty result for any view (no session matches the key, file, type,
    or date): print `No provenance entries match.` on its own line,
    nothing else.

## Safety

Read-only: this command performs no tracker write operation and writes
no file. Every number, id, and URL comes from the `.sessions/` data or
the journal; when a fact is missing, the output says so rather than
reconstructing it.
