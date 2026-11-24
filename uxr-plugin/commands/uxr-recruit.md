---
description: "Fill one study with participants: internal calendar-slot outreach with holds and reply tracking, or the external funnel (size, source, exclusions, booking page, mail merge) with one pre-send stop"
argument-hint: "<KEY> [--recruit=<name>] [--reply=<name>] [--level=i|ii|iii] [--external] [--status] [--check] [--dry-run]"
---

Recruit participants for one study. Internal flow (default): calendar
slots, a chat DM and email draft, private holds, reply tracking. External
flow (`--external`): sizing, sourcing, exclusions, booking page, mail-merge
draft, one stop at the pre-send review. Every run ends with the recruitment
table from `scripts/recruit_funnel.py`.

## Safety rules (they override everything below)

1. **Drafts only.** Never send a chat message or email; the sole exception is the external self-test, to the user's own inbox only.
2. **Per-move consent.** Every event move needs its own "go"; a private hold with no attendees is the only event created without one.
3. **Never move** an event with an attendee outside `org.internal_domains`, whatever the level or `--allow`. Max 3 moves per recruit per run (`calendar.max_moves_per_recruit`).
4. **Exclusions fail closed.** If the do-not-contact tab or open-deal list cannot be read, stop. `scripts/source_contacts.py` exits 2; never improvise around it.
5. **Customer personal data stays in the spreadsheet store.** No customer email or account list in the repository, the ticket (outside engaged roster rows), or chat logs. Refer to a contact as account + first name. `recruit_funnel.py` scrubs emails from its output; do not paste them back in.
6. **No URL in a mail draft body** when the mail tool rewrites links: keep the booking link in its merge column or print it for the user. Retest with check V2 on the user's own mail tool.
7. `--dry-run` writes nothing: no spec change, no event, no draft.

## Inputs

Grounding: consult registered sources in `references/sources/` (for this command: R-01 recruiting, R-15 ops); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

`$ARGUMENTS` is `<KEY>` with any of: `--recruit=<name>`, `--reply=<name>`,
`--level=i|ii|iii` (default `ii`), `--allow=<eventId>`, `--keep=<eventId>`,
`--window=<N>` (default 14, max 60), `--external`, `--coordinate`,
`--status`, `--check`, `--dry-run`, `--nudge-after=<N>` (default 2 business
days).

## Setup (every run)

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `recruit.*` (statuses, window_days, session_minutes, nudge_after_days, sheets, wave_tab_headers, booking_url_regex), `recruitment.*` (pipeline, suppression_list), `calendar.*`, `org.internal_domains`, and `org.notetaker_email`. Run the pipeline check - `python "${CLAUDE_PLUGIN_ROOT}/scripts/recruit_funnel.py" --pipeline-check` - once per run; an unknown stage name or an unreadable configured suppression list exits 2: report the error line and stop.
2. Resolve the workspace with `scaffold_workspace.py lookup-workspace
   --ticket <KEY> --readme <research_root>/README.md`.
3. Read the ticket: summary, status, start date, target end date. Load the
   roster from the spec at `<state_dir>/specs/<KEY>.spec.json` (never
   parse it from the ticket body; a missing spec means run
   `backfill_spec.py` first, read-only).
4. Window start = the later of today and the start date. Window end = the
   earlier of the target date and today plus `--window` days. If the end
   is not after the start, print "The study window is closed; pass
   `--window=<N>` to extend it." and stop.
5. Empty roster: print the `roster+=Name|email|slack|reason|status|channel`
   hint (via `uxr-edit`) and stop.
6. Run `scaffold_workspace.py validate-recruitment --path
   <workspace>/recruitment/participants.md --method <method_key> --channel
   <channel>`; its warnings are advisory; never block on them.

## Status gates (workspace participants table)

The workspace `recruitment/participants.md` status column uses the
locked vocabulary: identified, screened, invited, scheduled,
completed, incentive-sent, withdrawn. A status may not advance while
its gate columns are empty on the row; check the gates mechanically
from the row before every status change (no model call):

- `screened` needs a recorded `screener result`.
- `invited` needs `contact` filled (external flow) or
  `source (org-chart path)` filled (internal flow).
- `scheduled` needs an outreach/contact action recorded: `DM sent
  (date)` holds the date of the DM, chat note, merged send, or email
  send that reached the participant.
- `completed` needs `consent-to-record` set to yes.
- `incentive-sent` needs the row already `completed`.
- `withdrawn` needs nothing; it is allowed from any status at any
  time.

A blocked advance is one line: name the row and the empty gate column,
then stop and ask for the value. The spec roster keeps its own status
vocabulary (Outreach Sent, Scheduled, and the rest); these gates gate
the workspace table only.

## Pipeline and suppression (deterministic, zero model calls)

The pipeline is the ordered stage list in config `recruitment.pipeline`.
Shipped default: identify, screen, suppress, invite, schedule, send.
Every stage name names a deterministic check or action; the stage
machinery makes no model call. `recruit_funnel.py --pipeline-check`
prints the resolved stages and exits 2 on an unknown name.

The suppress stage is default-on and runs three checks, in order,
before any invite:

1. Status law: a participant at `completed`, `incentive-sent`,
   `withdrawn` (workspace vocabulary), or `cancelled` (roster
   vocabulary) is never re-contacted.
2. Bounce marks: a recipient marked " (bounced)" on an earlier wave tab
   is not emailed again.
3. Suppression list: the file at `recruitment.suppression_list` (one
   identifier per line, an email or an account id). An organization's
   own never-contact list is one instance of this file; the plugin
   ships none. The list must read when configured; the checks fail
   closed (exit 2) otherwise.

A suppressed row stays in the sheet: blank Recipient, `skip: suppressed
(<check>)` in Email Sent (the same skip law as every other skip). Never
delete the row. The suppress stage feeds the funnel table's Not allowed
row, and `--preflight` prints the suppressed counts per check with the
ready count.

## The recruitment table (the default chat visual)

The recruitment table is the default visual for recruitment chat
output: answer any recruitment question or status question with the
table, not a prose list. The caption line names the target persona from
`funnel.fit` (issue 51), and the fixed schema holds across waves. The
population sample size stays out of the table; note it beside the table
when the study needs it.

## Internal flow (default)

| Phase | What you do |
|---|---|
| A. Read | The setup steps above. Take the first research question as `top_rq` for the drafts. |
| B. Pick | Filter roster rows by `--recruit=<name>`, else the initial status (Potential Candidate). Skip `channel: external` rows with a one-line pointer to `--external`. |
| C. Slots | Save the window's calendar events to a JSON dump, then run `scripts/calendar_prep.py <dump> --manager "<calendar.manager_names>" [--keep <id>] [--allow <id>] --pick --level <level> --session-minutes <recruit.session_minutes>`. The `pick` block emits the slots deterministically: free gaps inside `calendar.working_hours` on a 15-minute grid, first fit per day in window order, 3 slots across days (`--slots` raises to at most 5), PTO days blocked, weekends and declined events never busy. Print each slot line verbatim: `- <label>`. Days with no free gap emit `move_candidates` instead (movable at level ii, movable plus other at iii): propose each as a move - one plain-word confirm per event, per `references/calendar-rules.md`. Fewer than 3 slots: say so and ask to try `--level=iii`. |
| D. Draft | For each picked recruit, render the outreach template - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render outreach --set ...` - binding every field verbatim from the roster row and spec: `first_name`, `study_title`, `session_length`, `why_this_recruit` (the roster `reason` field), `focus_clause` (`" The session focuses on {work_area}."` when the row has a work_area; the one-line condensed topic from the spec otherwise; empty when neither - never two spaces in a row), `slots_block` (the phase C slot lines), `sender_first_name`, `has_slack`, `holds` (`requested`; `none` under `--dry-run`), and the hold-title fields (`study_short`, `initial`, `last_name`, `day_abbrev`, `m_d`). A roster row missing `reason` is the exception lane: say which field is missing and draft only after the user supplies it - never invent a why-this-recruit line. The DM fires only when the row has a slack handle; the email always. Place one private hold per slot per the rendered title, no attendees, description per `references/recruit-outreach.md`. Print the block with reply options `sent`, `edit slack`, `edit email`, `skip`, `go ahead and move <id>`. `--dry-run` prints the drafts and hold titles and creates none of them. |
| E. Sent | On `sent`: `scripts/roster_apply.py --spec <spec> --ops '{"update":[{"match":"<name>","set":{"status":"Outreach Sent"}}]}' --out <body.json>` (survey studies use `Survey Sent`), push the body through `references/tracker.md` `update_item`, append one `outreach-log.md` entry with `scaffold_workspace.py append-outreach-entry`, and remind the user to update `participants.md`. |
| F. Reply | `--reply=<name>`: ask the user to paste the reply, then run `scripts/classify.py reply "<the reply>"` - the pasted reply goes
to the classifier verbatim, never paraphrased. `slot-picked` with a hold: tell the user to add the recruit to the hold guests, set the row to `Scheduled` with `roster_apply.py`, and remind them to delete the other holds. `booked`: same flip from the booking link. `declined`: set the row to `Cancelled`. `new-options`: back to phase C for new slots and holds. `free-text` (`lane: exception`): the one metered model call - read the reply, say which action you picked, and continue as above. |
| G. Moves | Only on `go ahead and move <id>`: show the current time, the proposed time, the attendees, and the rule from `calendar-rules.md`; wait for a plain `yes`; then move, read the event back, and show the result. One go moves one event; count to 3 per recruit per run. |
| H. Check | `--check`: for each active study, find roster rows in an outreach status, search chat and mail for replies over the last 14 days, classify each with `scripts/classify.py reply` (slot-picked, new-options, declined, free-text; a reply found but empty of text counts as no reply), and propose exactly one action per row via the script's `action`: `book <name>`, `send <name>`, `edit`, `skip`, `decline`, `go`. Then run `recruit_funnel.py --reminder` logic: after `--nudge-after` business days with no reply, draft one shorter follow-up (template first; a free-text follow-up is the exception lane). |

Finish every internal run (and every `--status`) by printing the
recruitment table: `recruit_funnel.py --spec <spec> [--funnel-data
<export>]`. `--status` prints the table and nothing else.

## External flow (`--external`)

One run, one stop at the pre-send review. Never re-source a person already
on a wave tab.

1. **Resume.** Read roster rows past the initial status and every tab in
   `funnel.tabs`.
2. **Fit.** On the first wave, define the persona as a product-analytics
   cohort and record `funnel.fit` (`users`, `accounts`, `as_of`, `basis`)
   via `roster_apply.py` funnel ops. Keep the first fit unless the user
   says `refit`.
3. **Size.** Default cold wave: 50 sends, 1 to 2 contacts per account,
   most active accounts first.
4. **Source.** Export the allowed-to-send, do-not-contact, and open-deal
   tabs to CSV, then `scripts/source_contacts.py --contacts <csv> --dnc
   <csv> --deals <csv> --accounts "<list>" [--filter --industry
   --job-level --segment] [--stale-days <N>]`. Exit 2 means stop: the
   exclusions failed closed.
5. **Email ladder.** Ask every connected channel, merge by email, and
   record the lowest-numbered source in the wave tab's Email Source
   column: (1) the contact sheet; (2) the analytics cohort; (3) the
   feedback knowledge graph; (4) mail and calendar search on the account
   domain; (5) call-recording profiles; (6) roster rows; (7) any other
   connected CRM. Never guess an address from a pattern. Never probe a
   mail server.
6. **Clear.** `source_contacts.py --check-emails "<emails>" --accounts
   "<accounts>"`. Drop do-not-contact, withheld, open-deal, and opt-out
   contacts; hold an at-risk account for the account manager's OK (with
   `--coordinate`, draft the chat notes asking for those OKs and the warm
   intro; never send them; without `--coordinate`, say in one line that
   re-running with `--coordinate` drafts those chat notes).
   Org-chart search (issue 50): with `--coordinate`, search the
   org-chart connectors saved in `recruiting.org_chart_paths` for other
   teams and accounts that could help recruit, and name what you find in
   the drafted chat notes; the list empty means print one line that the
   org chart is not configured and continue without it.
7. **Booking page.** Reuse a verified page or build one to the settings in
   `references/recruit-outreach.md`. Verify the public link shows bookable
   slots.
8. **Mail merge.** Copy the merge template sheet once per study and save
   it to `funnel.sheet`. Create the draft, then run the checks: V1 with
   `recruit_funnel.py --check-draft <draft>`; V2 self-test to the user's
   own inbox only; V3 open the link; V4 `recruit_funnel.py --spec <spec>
   --preflight --funnel-data <export>`. Assemble the export with
   `suppression_list` (the identifiers read from
   `recruitment.suppression_list`) and `participants` (the workspace
   participants rows) so the suppress stage checks them
   deterministically; V4 prints the suppressed counts per check with
   the ready count.
9. **Wave tab.** Run the suppress stage (the three checks above): a
   suppressed row is a tab row with a blank Recipient and `skip:
   suppressed (<check>)` in Email Sent; it stays in the sheet. Build
   the tab with the headers from the reference; each skip is a row
   with `skip: <reason>` in Email Sent. Save the tab name into
   `funnel.tabs` with `roster_apply.py`.
10. **Pre-send review (the stop).** Show the recruitment table, off-sheet
    contacts, the no-email-found list, flagged accounts, proposed calendar
    moves, the exact subject and body, and the V1 to V4 results. Last line:
    "Click Mail Merge > Send Emails on the <tab> tab, or reply `send` and
    I will." Wait. `--dry-run` never reaches this stop.
11. **After the send.** Rerun V4, confirm the active tab, mark bounces
    " (bounced)" (never delete a row), append everyone emailed to the
    do-not-contact tab, and flip named roster rows with `roster_apply.py`.
12. **Replies.** Every later run: find booking-page bookings and add each
    booker as `Scheduled` in one `roster_apply.py` batch.

Finish the external run with the recruitment table from
`recruit_funnel.py --spec <spec> --funnel-data <export> --wave <tab>`.
Output never contains an email address; keep it that way in anything you
paste into chat or the ticket.

## Email send (MVP)

The send path for the external participants table: one email per
recipient, no mail-merge add-on. The draft-only rule (safety rule 1)
keeps the agent at zero sends; the researcher runs the real send
themselves, with `--send`, after the review.

1. The command is `python "${CLAUDE_PLUGIN_ROOT}/scripts/recruit_send.py"
   --participants <workspace>/recruitment/participants.md --template
   <workspace>/recruitment/email-merge-template.md`. Without `--send` it
   is a dry run: the merged messages print, and nothing changes - no
   send, no stamp, no write.
2. The send follows the status gates above: a row is sendable only at
   `invited`, with `contact` filled and `DM sent (date)` empty; on send
   success the row's `DM sent (date)` is stamped and the row advances to
   `scheduled`; a failed row gets no stamp and stays at `invited`. The
   suppression gate runs before all of it: a row whose contact email is
   on the configured `recruitment.suppression_list` file is skipped and
   reported, in the dry run and the real send alike.
3. One email per recipient: each message carries one `To` and no `Cc` or
   `Bcc`; a duplicate address sends once and the later row is reported.
   Contact values are masked in the report; `--show-contacts` shows
   them.
4. `--send` needs the SMTP account in `recruit.email.*` (real values in
   the gitignored `config/org.yaml` or the `UXR_RECRUIT_*` env vars,
   never in the repo).
5. The template ships as
   `templates/workspace/recruitment/email-merge-template.example.md`
   (synthetic values only). Copy it into the workspace, rename it, and
   fill in the message there. A `{{token}}` names an approved column
   (`{{name_pseudonym}}` from `name/pseudonym`); an unknown token stops
   the run before anything is sent.

When the researcher follows the email with a chat DM, the DM carries
context plus the row's `prep note`, or nothing - no other content.

## Scripts

| Script | Contract |
|---|---|
| `scripts/recruit_funnel.py --spec <path> [--wave <tab>] [--preflight] [--reminder] [--funnel-data <json>] [--check-draft <file>] [--today <date>]` | Prints the nine-row recruitment table; `--preflight` exits 2 with `BLOCK <account> / <first>: <reason>` lines or prints `PREFLIGHT OK: <n> rows ready on <tab>`; `--reminder` drafts nudges; `--check-draft` is check V1. Output never contains an email address. |
| `scripts/recruit_send.py --participants <participants.md> --template <file> [--send] [--show-contacts] [--today <date>]` | The MVP email send from the external participants table (see Email send). Dry run by default: the merged messages print, nothing changes. `--send` needs the `recruit.email.*` SMTP account; exit 0 clean, 1 a send failed, 2 usage. |
| `scripts/source_contacts.py` | Sources and clears contacts; account match is normalized whole words ("Box" never matches "Dropbox"); missing do-not-contact or open-deal tab exits 2 and sources nothing. |
| `scripts/roster_apply.py --spec <path> --ops <json-or-@file> --out <body.json> [--dry-run]` | The only spec write path: validate, render, then write spec and body; exit 3 on validation failure with nothing written; duplicate adds promote only, never demote. |
| `scripts/calendar_prep.py <events.json> [--manager <names>] [--keep <id>] [--allow <id>]` | Classifies the window's events into `pto`, `immovable`, `movable`, `other`; weekends and declined events are skipped. |
| `scripts/scaffold_workspace.py lookup-workspace / append-outreach-entry / validate-recruitment` | Workspace resolution, outreach log entries, participants table checks (from issue 08). |

## Rules of last resort

- Every gate waits for a plain human word: `sent`, `yes`, `go`, `send`,
  `skip`, `decline`, `edit`. Never act on a guessed confirmation.
- One `update_item` per run via the spec pipeline; comments carry the
  `comments.footer`.
- If the user asks "who have we contacted", answer with `--status`'s table,
  not a chat search transcript.
