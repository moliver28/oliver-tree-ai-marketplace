---
description: "Re-sync the one-page cheat sheet from its sources: run the validator, show the section-by-section diff, and write targeted fixes only after an explicit go"
argument-hint: "[--check] [--dry-run]"
---

Keep `docs/cheat-sheet.html` truthful. The validator compares every
generated section of the cheat sheet against its source files (the
command files, the config contract, the phase gates reference, the
craft method table, the workspace template) and `--remediate` rebuilds
exactly the drifted sections. Editorial sections - interview phases,
role cards, FAQ - are never rewritten by the validator.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` may carry `--check` (validate only, no fix offer, no
write) or `--dry-run` (validate, show the fixes that would apply,
write nothing). Without flags the command runs the full check, show,
gate, and fix loop.

Every gate in this command uses the same words: `go`, `edit`,
`cancel`.

## Steps

1. **Validate.** Run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_cheatsheet.py" --json`.
   Exit 0 with `"ok": true`: print one line (in sync, with the checked
   file path) and stop. That is the whole `--check` run.

2. **Show the drift, section by section.** From the `drifts` array,
   render one block per affected section:

   ```
   commands (2 drift items):
     - count word: "15 commands" -> "16 commands"
     - missing command: uxr-deck
   flags (1 drift item):
     - uxr-deck: flag --render-only missing from the flag table
   ```

   Pull expected values from the `expected` field and the current
   values from `actual`; never guess the fix content - it comes from
   the validator output.

3. **Gate.** Ask for `go` (apply the targeted fixes), `edit` (the user
   dictates the changes; apply them and re-validate), or `cancel`
   (write nothing). `--dry-run` shows this diff and stops before the
   gate - nothing is written in a dry run.

4. **Fix on `go`.** Run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_cheatsheet.py" --remediate --verbose`.
   The validator rebuilds each drifted generated section from its
   sources, writes the file in place, and prints one
   `FIX <section>: ...` line per repair; it still exits 1 because drift
   was found - that exit is expected after a fix run.

5. **Verify and report.** Re-run the validator with no flags; it must
   exit 0. Report: sections fixed, verification result, and the file
   path `docs/cheat-sheet.html`.

## Rules

- **Targeted fixes only.** The validator rewrites generated sections;
  it never rewrites the interview phases, role cards, or FAQ. If the
  user reports a wrong editorial section, propose the edit as
  `edit`, apply it as a one-spot text change, and re-validate - the
  generated sections stay untouched by that edit.
- Never regenerate the whole file from memory: the fix path is always
  the validator's `--remediate`, so the written content is computed
  from the sources, not recalled.
- Never touch any file other than `docs/cheat-sheet.html` in this
  command (the sources are read-only inputs).
- Two failed attempts on any problem: search the web before trying
  again.
