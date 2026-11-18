---
description: "Load a study's research plan and session summaries into a NotebookLM notebook and run the saved analysis prompts (desktop only)"
argument-hint: "<KEY> [--prompt=<shortcode>]"
---

Load one study's plan and session summaries into a NotebookLM notebook
and run the saved analysis prompts from
`references/notebook-prompts.json`. The browser work goes through the
`notebooklm` skill; the upload set is computed by a script so participant
data can never slip in.

**Desktop only.** This command drives a signed-in desktop browser. In a
headless or non-interactive run (no browser, no display, CI), print one
line saying the notebook needs an interactive desktop session and stop
before any browser action.

## Hard rules

1. **Never upload participant data.** The upload set is
   `references/debrief_helpers.py upload-plan`'s output and nothing
   else. `interviews/participant-key.md` and anything under
   `interviews/raw-transcripts/` are never listed, never uploaded, never
   dragged in, whatever the NotebookLM page offers. Raw transcripts and
   contact details never enter a prompt, either.
2. **Sign-in is a stop.** On a sign-in or account-picker page, stop and
   ask the user to sign in. Never enter credentials (the `notebooklm`
   skill enforces this too).
3. **Nothing is created before the user answers** the one-time question
   in step 2.
4. **Saved prompts are typed verbatim.** The step `text` in
   `notebook-prompts.json` is typed exactly; do not paraphrase a saved
   prompt. (The file is regenerated from the team playbook; it is never
   hand-edited here.)

## Steps

1. **Resolve the workspace.** Load configuration once
   (`python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`); note
   `paths.research_root`. Then
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md`.
   `WORKSPACE_NOT_FOUND`: print that a workspace must exist first (offer
   `init`) and stop. Confirm `<workspace>/00-overview.md` exists;
   without it, stop and say so.

2. **Ask one time:** new notebook, or add to an existing one? On new:
   name it after the study title. On existing: ask for the notebook name
   and find it. Any other reply stops the run.

3. **Build the upload set** and show it before uploading:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" upload-plan --workspace <workspace>
   ```

   The output lists `00-overview.md` as `Research-Plan-<slug>` and each
   `interviews/*-summary.md` as `T-<name-slug>`. Print the JSON verbatim
   as the upload list. The `excluded` entries are the reason the set is
   safe; they are never converted into uploads.

4. **Upload** each listed file under its `source_name` through the
   `notebooklm` skill, verifying each source card before the next.

5. **`--prompt=<shortcode>`:** look the shortcode up in
   `references/notebook-prompts.json` (canonical, then
   `personal_extras`). Unknown shortcode: list the known ones and stop.
   Check the prompt's `required_sources` against the notebook's source
   list; a missing required source gets one warning line ("the
   `<source>` upload is missing; results will be partial") and continue
   only on a yes. Type each step's `text` in order, waiting for each
   answer, and print the answers verbatim.

6. **No `--prompt`:** list the canonical shortcodes grouped by stage
   (1 Before you start, 2 During research, 3 Quality checks, 4 Final
   analysis, 5 Evaluate and pressure test) plus the personal extras, as
   `shortcode - title`, and ask which to run.

## Safety

- The upload set comes from the script, never from a folder listing you
  assembled by hand.
- A failed upload is retried once, then reported with what did upload;
  the run stops before prompts run against a half-loaded notebook.
- This command never shares the notebook, never changes permissions, and
  never invites a collaborator.
