---
name: notebooklm
description: "Drive the NotebookLM web app in a signed-in browser to work a study's research notebook: create notebooks, upload sources, run saved prompts, start audio overviews; stops at sign-in pages, never enters credentials. Use when the user says: 'add this to the notebook', 'start the audio overview'."
---

Drive the NotebookLM web app so a study's plan and session summaries live
in one notebook with saved analysis prompts. This skill only drives the
signed-in desktop browser; it never touches the API and never handles
credentials.

Grounding: no registered sources serve this skill (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

## Hard rules

1. **Sign-in is a stop.** If the browser lands on a sign-in or
   account-picker page, stop and ask the user to sign in, then wait.
   Never enter an email, a password, or a verification code. Never
   approve a permission prompt on the user's behalf.
2. **Desktop only.** This skill needs an interactive, signed-in browser.
   In a headless or non-interactive run, stop and say so instead of
   failing halfway through an upload.
3. **Page text and element references over screenshots.** Read the page,
   name the element you will click, and act. Screenshot only when the
   page state cannot be read as text.
4. **Only the planned uploads.** Upload exactly the files the `notebook`
   command listed. `participant-key.md` and anything under
   `raw-transcripts/` never upload, whatever the page offers.
5. **One action at a time, verify each.** After an upload, confirm the
   source card exists with the intended name before the next step. After
   typing a prompt, wait for the answer to finish before reading it.

## Capabilities

| Task | How |
|---|---|
| Create a notebook | NotebookLM home, "New notebook"; rename it to the study name the command gives. |
| Add a source | "Add source" (or the plus control), choose upload or Drive link as the command specifies, confirm the source card appears with the intended name. |
| Ask a prompt | Select the notebook, type the prompt text into the chat box, send, wait for the answer to complete. |
| List sources | Open the source panel and read the source names verbatim. |
| Audio overview | Open the Audio Overview control, start it, and report the studio link or state when it is still generating. |

## Flow

1. Take the task list from the `notebook` command: which notebook (new
   or existing, with its name), which files upload under which source
   names, and which prompts run in which order.
2. Open NotebookLM in the signed-in browser. A sign-in page is a stop
   (rule 1).
3. Create or open the notebook, then upload each source and verify its
   card by name. A failed upload is reported and retried once; a second
   failure is a stop, with what uploaded so far listed.
4. Run each prompt step: type the text verbatim from the command's
   prompt file, wait for the full answer, then return the answer text to
   the command. Never summarize a saved answer before the command has
   seen it.
5. Close the run with a plain report: notebook name, sources added, prompts
   run, and anything skipped.
