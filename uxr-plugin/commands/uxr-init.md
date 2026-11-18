---
description: "Create the local research workspace for a study: overview that mirrors the ticket, fixed folder structure, and git rules that keep participant data out of version control"
argument-hint: "<KEY> [--dir=<name>] [--no-ticket]"
---

Give a study its local folder: `00-overview.md` that mirrors the ticket,
folders for sources, scripts, interviews, analysis, recruitment, and
deliverables, and git rules that keep participant data out of version
control. Every later command (`recruit`, `debrief`, `report`, `deck`,
`trace`) finds its files here.

Input: `$ARGUMENTS`. Exactly one of:

- `<KEY>` - a ticket key (bare numbers resolve per `references/tracker.md`).
- `--no-ticket` - a workspace with no ticket behind it; you ask for a
  title and every ticket field becomes `TBD`. No tracker calls are made.
- `--dir=<name>` - folder name override; the folder is still created
  under the research root. Reject any `<name>` containing a path
  separator or leading dots.

Neither `<KEY>` nor `--no-ticket`: ask which one applies and end the turn.

Steps:

1. Read configuration once: run
   `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print` (when
   `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin
   directory that holds `lib/` and `scripts/`). Note `paths.research_root`,
   `paths.state_dir`, `workspace.remote`, and `workspace.slug_max_body`.
2. Spec guard. The spec lives at
   `<state_dir>/specs/<KEY>.spec.json`.
   - Spec present: load it; it feeds the overview and the mapping below.
   - Spec absent: read the live ticket body (read-only `get_item`, the
     description only) and pipe it through
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/backfill_spec.py"`.
     - The recovered spec has content (history, decision, hypotheses, or
       research questions): this study predates the plugin. Show the
       recovered spec as a JSON preview, tell the user to run
       `edit <KEY>` to save a spec, and ask
       `Scaffold now with placeholder sections, or stop? (scaffold / stop)`.
       On `stop`, end. On `scaffold`, continue with no spec file.
     - The recovery is empty (the body is the unfilled template): this is
       a new study. Run the guided build block from the `new` command
       without the create: interview for a working title, group, key
       decision, 3-5 hypotheses (`Label. Claim.`), 2-3 assumptions, 3-6
       open research questions, method, sample, persona, and session
       length. Build the spec JSON (including `study_title`, `method_key`,
       and `channel`), validate it by piping it through
       `python "${CLAUDE_PLUGIN_ROOT}/scripts/build_body.py"` (a nonzero
       exit prints errors; show them and return to the interview, writing
       nothing), then save the spec to
       `<state_dir>/specs/<KEY>.spec.json` with the six `_meta` keys
       (`created_at`, `last_edited_at`, `last_edited_by_command: "init"`,
       `tracker_updated_at: null`, `session_id` from `$CLAUDE_SESSION_ID`,
       `transcript_path`).
   - `--no-ticket`: skip the guard; ask for a working title; no spec file.
3. Read the live ticket for summary and status only (never the full field
   panel): one `get_item(<KEY>)` call per `references/tracker.md`.
   With `--no-ticket`, skip this step.
4. Derive the slug:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" slug
   --title "<title>" --quarter q<N>-<yyyy> --max-body <workspace.slug_max_body>`
   using the current quarter. With `--dir=<name>`, use that name instead
   (still under the research root).
5. The target folder `<research_root>/<slug>` exists: print exactly
   `That directory already exists. Use \`show\` to work with an existing
   project, or pass \`--dir=\` to pick a different name.` and stop.
6. Show the plan and wait. One message with: ticket key and URL (or
   `no ticket`), status, folder path, UXR, group, sync target
   (`workspace.remote`, or `local only` when unset), and the file tree
   the template creates (`00-overview.md`, `CLAUDE.md`, `.gitignore`,
   `.claude/settings.json`, `.sessions/`, `analysis/`, `deliverables/`,
   `interviews/`, `recruitment/`, `scripts/`, `sources/` with one folder
   per source type plus `interviews/`). End with exactly
   `Proceed? (yes / edit path / cancel)`. `edit path` asks for a new
   folder name and re-runs this check; `cancel` ends.
7. Scaffold. Run:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" scaffold \
     --template "${CLAUDE_PLUGIN_ROOT}/templates/workspace" \
     --target "<research_root>/<slug>" \
     --mapping '<JSON scalars>' \
     --readme "<research_root>/README.md" \
     --spec "<state_dir>/specs/<KEY>.spec.json"
   ```

   `--spec` is omitted when no spec file exists (old-ticket path and
   `--no-ticket`). The mapping JSON carries every scalar token, filled
   from the live ticket fields and the spec: `STUDY_TITLE`, `STUDY_SLUG`,
   `TICKET_KEY`, `STATUS`, `POD`, `UXR_NAME`, `PM_NAME`, `DESIGNER_NAME`,
   `EM_NAME`, `DECISION`, `RESEARCH_TYPE`, `METHOD`, `SAMPLE`, `PERSONA`,
   `SESSION_LENGTH`, `INVESTMENT`, plus `TICKET_URL` for the README index
   row (the `item_url(<KEY>)` value). `--no-ticket` sends `TBD` for every
   ticket field except the title and slug. Exit 3 from the script: show
   its stderr and stop without retrying; exit 2: fix the invocation.

8. Run the gitignore gate:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/gitignore_gate.py" assert-ignored \
     --repo "<research_root>/<slug>" \
     interviews/raw-transcripts/x.txt interviews/participant-key.md \
     <one path argument per workspace.gitignored_paths entry>
   ```

   Append every `workspace.gitignored_paths` entry from the step-1
   configuration as an extra path argument; config adds to the
   hardcoded entries and never replaces them. Exit 3: hard stop before
   any `git add`. Print the blocked paths, tell
   the user to fix `<workspace>/.gitignore`, and end. Never write
   participant data while the gate fails.
9. If `workspace.remote` is set: run
   `git -C "<target>" remote add origin <remote>` (ignore an
   already-exists error), then `git -C "<target>" push -u origin HEAD`.
   A push failure only warns: print the git error, note the workspace is
   committed locally, and continue.
10. Print next steps, one line each, as plain command names with the key:

    - `show <KEY>` - open the study view
    - `edit <KEY>` - change sections from shorthand
    - `recruit <KEY>` - fill the roster and outreach log
    - `trace --project` - the evidence trail for this workspace
    - `notebook <KEY>` - upload the overview and summaries

Never call a tracker write operation in this command; `init` reads the
ticket, writes local files, and runs local git only.
