---
description: "File a bug or idea against the plugin repository in one command: the user's text goes into the issue byte for byte, nothing is created before an explicit go"
argument-hint: "[feedback text]"
---

File the user's feedback as a GitHub issue on the plugin repository.
The text is the user's, byte for byte: this command never invents,
rewords, translates, or completes it. One issue per run, created only
after the user says `go`.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` is all text after the command name (everything the user
typed past `/uxr-plugin:uxr-feedback`), kept as one raw string:
leading and trailing whitespace trimmed for the title only; the body
keeps the text exactly as given.

## Steps

1. **Take the text.** Use `$ARGUMENTS` as the feedback text. When it
   is empty, ask exactly one time - "What is the feedback? I will file
   it as written." - and stop; whatever the user answers next is the
   text. Never invent, summarize, or extend the text, and never file
   an empty issue.

2. **Build the title.** `[uxr-feedback] ` plus the first 60 characters
   of the text (trim trailing whitespace of that slice; no ellipsis,
   no rewriting). A text shorter than 60 characters is used whole.

3. **Build the body.** Exactly this, in order:
   - the text verbatim (byte for byte; newlines and formatting kept),
   - one blank line,
   - `---`,
   - `Plugin: <name> v<version>` - name and version read live from
     `.claude-plugin/plugin.json` in the plugin root (never
     hardcoded),
   - `Invoking command: <name or "none">` - the plugin command the
     user was working in when they filed this (for example `deck`);
     `none` when feedback was filed outside any command flow.

4. **Show and gate.** Display the exact title and the exact body in a
   fenced code block, then ask for `go` (anything else cancels and
   writes nothing). **Nothing is created before `go`**: no file, no
   temp file, no gist, no `gh` call of any kind - not even a dry run.

5. **Create on `go`.** Read `feedback.repo` and `feedback.label` from the configuration (render `prompt: config-setup@1` via `lib/prompts.py`). When `feedback.repo` is empty, stop with: `feedback.repo
   is not set; add it to config/org.yaml (for example:
   moliver28/uxr-plugin)` and offer the manual URL shape below. On
   `go`, run:

   ```
   gh issue create --repo <feedback.repo> --label <feedback.label> \
     --title "<title>" --body-file -
   ```

   with the body piped to stdin (`--body-file -`), so the text passes
   through shell-safe and byte for byte.

6. **Report.** Print the issue URL exactly as `gh` returned it. When
   `gh` fails (not installed, not authenticated, label missing,
   network), show the error verbatim and the manual issue URL
   `https://github.com/<feedback.repo>/issues/new` plus the title and
   body to paste; never retry silently and never fall back to another
   channel.

## Rules

- The user's text is never altered between step 1 and the issue body:
  no reflowing, no smart quotes, no truncation (the only truncation in
  this command is the 60-character title slice).
- One `gh` call per run, only after `go`.
- The label is applied as given by `feedback.label`; a missing label
  surfaces as a `gh` error in step 6, never as a second unasked-for
  call without the label.
- Two failed attempts on any problem: search the web before trying
  again.
