---
description: "Draft end-of-day ticket comments from the session journal: shows every draft, posts only on approval"
argument-hint: "[--dry-run] [--days=<YYYY-MM-DD | A..B>] [--ticket=<KEY>] [--auto] [--polish]"
---

Draft end-of-day ticket comments for the study tickets touched today (or
over a day range), from the session journal the SessionEnd hook writes.
Drafts are template-built facts by default (`scripts/eod_journal.py`); the
posting decision is always the user's -- except `--auto`, which posts facts
only and skips anything already commented today. `--polish` opts into one
narrative rewrite per draft (a metered model call; the exception lane).
Read-only activity is listed, never posted, unless the user pulls it in.

It uses `get_item` and `add_comment` from `references/tracker.md` (never
`update_item`, `create_item`, or `set_state`), reads the journal under
`paths.state_dir`, and never sends anything else. On the golden path this
command spends zero model calls.

## Inputs

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

`$ARGUMENTS` may hold any of:

1. `--dry-run`: show the drafts, post nothing, leave `processed`
   untouched. This flag always wins.
2. `--days=<YYYY-MM-DD>` or `--days=<A>..<B>` (inclusive; default today).
3. `--ticket=<KEY>`: draft for that ticket only.
4. `--auto`: non-interactive for a scheduled run (the user sets up
   launchd or cron themselves; this command never configures a
   scheduler).
5. `--polish`: rewrite each shown draft narratively (facts preserved),
   one model call per ticket, after the template draft passes its check.

## Steps

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `paths.state_dir`, `tracker.kind`, `tracker.ticket_regex`, `tracker.bare_number_prefix`, and `comments.footer`.
2. Build the day list from `--days` (one date, or `A..B` expanded
   inclusive; default: today only). The journal lives at
   `<state_dir>/work-log-<YYYY-MM-DD>.jsonl`, one file per local day.
3. Filter and group deterministically -- run this and use its output
   verbatim, never a re-computation:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/eod_journal.py" filter \
     --state <state_dir> --days <day 1,day 2> [--ticket <KEY>]
   ```

4. No rows at all: print exactly one line and stop --
   `No unposted UX research work for <date>.` (a single date) or
   `No unposted UX research work for <A>..<B>.` (a range). Nothing else.
5. Groups with no ticket key but `in_research_dir: true` go under a
   `No ticket linked` heading (session ids and cwd only). Post nothing
   for them; offer `new` as the follow-up in one line.
6. Read-only groups (no file edits, no tracker calls) print under
   `Skipped (read-only activity)`. The user can pull one in later with
   `include <KEY>`.
7. For each active ticket: call `get_item` (fields + Markdown body +
   comments, per `references/tracker.md`) and `item_url(key)`. Look for
   an existing comment whose first line is `[ux-eod <date>]` for the
   target date.
8. Draft ONE comment per active ticket, mechanically: run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/eod_journal.py" draft-auto --state <state_dir> --days <days> --ticket <KEY> --date <date> --footer "<comments.footer with {display_name} replaced>"`
   (display name from the cached `current_user()`), then verify it:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/eod_journal.py" check --file <draft file> --footer "<footer>"`.
   The check prints `<words> <True|False>`; a draft over 300 words or
   with `False` is regenerated from the template, never shown broken.
   With `--polish` (never with `--auto`): rewrite the verified draft
   narratively - same facts, no new ones, no session ids - re-run the
   check, and show the polished text. That rewrite is the one metered
   model call per ticket.
9. **The gate.** Show every draft together, then stop and wait for one
   reply: `go` (post all), `skip <KEY>` (leave that one unprocessed),
   `edit <KEY>` (apply the user's wording, re-verify the cap, show it
   again), `include <KEY>` (draft for a skipped read-only group after
   pulling its rows), or `cancel`. When today's `[ux-eod <date>]`
   comment already exists, ask for that ticket: append or replace.
   Under `--dry-run`: show the drafts under a `DRY RUN - nothing posted`
   heading, then stop -- no posting, no journal rewrite.
10. On `go`: call `add_comment(key, <draft>)` once per approved ticket.
    A failed post is reported and leaves that ticket unprocessed. Then
    rewrite the journal so `processed: true` for every posted ticket's
    rows AND every skipped read-only row (read-only work is done; it
    must not resurface tomorrow). Run the rewrite once:

    ```
    python "${CLAUDE_PLUGIN_ROOT}/scripts/eod_journal.py" rewrite \
      --state <state_dir> --days <day 1,day 2> \
      --posted <KEY 1,KEY 2> --readonly <session id,session id>
    ```

    Print one line per posted ticket:
    `Posted [ux-eod <date>] to [KEY](url).` using `item_url(key)`.
11. `--auto` (no user present): the template drafts are facts only by
    construction; skip any ticket that already has today's
    `[ux-eod <date>]` comment; post; run the step 10 rewrite; print the
    same `Posted ...` lines. `--auto` never combines with `--polish`.
    Under `--auto` the gate is skipped by design; without `--auto` the
    gate in step 9 is never skipped.

## Safety

- Every draft is shown before anything posts; only `go` (or `--auto`)
  posts. `cancel` and `skip <KEY>` are always honored first.
- `--dry-run` posts nothing and leaves `processed` untouched: a second
  `--dry-run` on the same day shows the same unprocessed rows.
- Read-only work is listed under `Skipped (read-only activity)`, never
  drafted into a ticket comment unless `include <KEY>` says so.
