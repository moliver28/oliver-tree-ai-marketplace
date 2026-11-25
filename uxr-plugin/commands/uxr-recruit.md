---
description: "Fill one study with participants: internal calendar-slot outreach with holds and reply tracking, or the external funnel (size, source, exclusions, booking page, mail merge) with one pre-send stop"
argument-hint: "<KEY> [--recruit=<name>] [--reply=<name>] [--level=i|ii|iii] [--external] [--status] [--check] [--dry-run]"
---

Recruit participants for one study: internal flow (default), external flow on `--external`. Every run ends with the recruitment table from `scripts/recruit_funnel.py`.

## Safety rules (they override everything below)

1. **Drafts only.** Never send a chat message or email; the sole exception is the external self-test, to the user's own inbox only.
2. **Per-move consent.** Every event move needs its own "go"; a private hold with no attendees is the only event created without one.
3. **Never move** an event with an attendee outside `org.internal_domains`, whatever the level or `--allow`. Max 3 moves per recruit per run (`calendar.max_moves_per_recruit`).
4. **Exclusions fail closed.** If the do-not-contact tab or open-deal list cannot be read, stop. `scripts/source_contacts.py` exits 2; never improvise around it.
5. **Customer personal data stays in the spreadsheet store.** No customer email or account list in the repository, the ticket (outside engaged roster rows), or chat logs. Refer to a contact as account + first name. `recruit_funnel.py` scrubs emails from its output; do not paste them back in.
6. **No URL in a mail draft body** when the mail tool rewrites links: keep the booking link in its merge column or print it for the user. Retest with check V2 on the user's own mail tool.
7. `--dry-run` writes nothing: no spec change, no event, no draft.
8. **Meeting-service law.** Calendar events created by recruitment
   never auto-attach a conferencing link; the join link comes only from
   the configured meeting service's own flow: `recruitment.meeting_service`
   (default `appointment-link`; one of `appointment-link`, `none`,
   `google-meet`, `zoom`, `other`). The default means zero auto-created
   links. No Google Meet link may ever appear unless the config names
   `google-meet` and the user's own flow creates it.

## Inputs

Grounding: registered sources in `references/sources/` (this command: R-01 recruiting, R-15 ops); page-first lookup; cite the URL with the claim. Index: `references/research-sources.md`.

`$ARGUMENTS` is `<KEY>` plus any of: `--recruit=<name>`, `--reply=<name>`, `--level=i|ii|iii` (default `ii`), `--allow=<eventId>`, `--keep=<eventId>`, `--window=<N>` (default 14, max 60), `--external`, `--coordinate`, `--status`, `--check`, `--dry-run`, `--nudge-after=<N>` (default 2 business days).

## Setup (every run)

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - follow it. Note `recruit.*` (statuses, window_days, session_minutes, nudge_after_days, sheets, wave_tab_headers, booking_url_regex), `recruitment.*` (pipeline, suppression_list, meeting_service), `calendar.*`, `org.internal_domains`, `org.notetaker_email`. Pipeline check - `python "${CLAUDE_PLUGIN_ROOT}/scripts/recruit_funnel.py" --pipeline-check` - once per run; an unknown stage name or an unreadable configured suppression list exits 2: report the error line, stop.
2. Workspace: `scaffold_workspace.py lookup-workspace --ticket <KEY> --readme <research_root>/README.md`.
3. Ticket: summary, status, start date, target end date. Roster from spec `<state_dir>/specs/<KEY>.spec.json` - never parse from ticket body; missing spec: `backfill_spec.py` first, read-only.
4. Window start: later of today and start date. Window end: earlier of target date and today plus `--window` days. End not after start: print "The study window is closed; pass `--window=<N>` to extend it." and stop.
5. Empty roster: print the `roster+=Name|email|slack|reason|status|channel` hint (via `uxr-edit`); stop.
6. `scaffold_workspace.py validate-recruitment --path <workspace>/recruitment/participants.md --method <method_key> --channel <channel>`; warnings advisory; never block.

## Status gates (workspace participants table)

Workspace `recruitment/participants.md` status column, locked vocabulary: identified, screened, invited, scheduled, completed, incentive-sent, withdrawn. No advance while its gate columns are empty on the row; check mechanically from the row before every status change (no model call):

- `screened` needs a recorded `screener result`.
- `invited` needs `contact` filled (external flow) or `source (org-chart path)` filled (internal flow).
- `scheduled` needs an outreach/contact action recorded: `DM sent (date)` holds the date of the DM, chat note, merged send, or email send that reached the participant.
- `completed` needs `consent-to-record` set to yes.
- `incentive-sent` needs the row already `completed`.
- `withdrawn` needs nothing; allowed from any status at any time.

Blocked advance: one line - row and empty gate column; stop, ask for the value. Spec roster has its own status vocabulary (Outreach Sent, Scheduled, and the rest); these gates gate the workspace table only.

## Pipeline and suppression (deterministic, zero model calls)

Pipeline = ordered stages in config `recruitment.pipeline`; shipped default: identify, screen, suppress, invite, schedule, send. Each stage: one deterministic check or action; no model call. `recruit_funnel.py --pipeline-check` prints resolved stages.

Suppress stage: default-on; three checks, in order, before any invite:

1. Status law: a participant at `completed`, `incentive-sent`, `withdrawn` (workspace vocabulary) or `cancelled` (roster vocabulary) is never re-contacted.
2. Bounce marks: a recipient marked " (bounced)" on an earlier wave tab is not emailed again.
3. Suppression list: file at `recruitment.suppression_list`, one identifier per line (email or account id). An organization's own never-contact list is one instance; the plugin ships none. Configured list must read; checks fail closed (exit 2) otherwise.

Suppressed row stays in the sheet: blank Recipient, `skip: suppressed (<check>)` in Email Sent. Never delete the row. Suppress feeds the funnel table's Not allowed row; `--preflight` prints suppressed counts per check with the ready count.

## The recruitment table (the default chat visual)

Default chat visual: answer any recruitment or status question with the table, not prose. Caption names the target persona from `funnel.fit` (issue 51); schema fixed across waves. Sample size stays out of the table; note it beside it when needed.

## Internal flow (default)

| Phase | What you do |
|---|---|
| A. Read | Setup steps above. First research question = `top_rq` for the drafts. |
| B. Pick | Filter roster rows by `--recruit=<name>`, else the initial status (Potential Candidate). Skip `channel: external` rows; one-line pointer to `--external`. |
| C. Slots | Dump window calendar events to JSON; run `scripts/calendar_prep.py <dump> --manager "<calendar.manager_names>" [--keep <id>] [--allow <id>] --pick --level <level> --session-minutes <recruit.session_minutes>`. `pick`, deterministic: free gaps inside `calendar.working_hours`, 15-minute grid, first fit per day in window order, 3 slots across days (`--slots` raises to at most 5), PTO days blocked, weekends and declined events never busy. Print each slot line verbatim: `- <label>`. No-free-gap days: `move_candidates` (movable at level ii, movable plus other at iii) - propose each as a move, one plain-word confirm per event, per `references/calendar-rules.md`. Fewer than 3 slots: say so; ask to try `--level=iii`. |
| D. Draft | Per picked recruit: render the outreach template - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render outreach --set ...` - binding every field verbatim from roster row and spec: `first_name`, `study_title`, `session_length`, `why_this_recruit` (roster `reason`), `focus_clause` (`" The session focuses on {work_area}."` with work_area; spec's one-line condensed topic otherwise; empty when neither - never two spaces in a row), `slots_block` (phase C slot lines), `sender_first_name`, `has_slack`, `holds` (`requested`; `none` under `--dry-run`), hold-title fields (`study_short`, `initial`, `last_name`, `day_abbrev`, `m_d`). Missing `reason`: exception lane - name the field; draft only after the user supplies it; never invent a why-this-recruit line. DM fires only on a slack handle; email always. One private hold per slot: rendered title, no attendees, description per `references/recruit-outreach.md`. Print the block with reply options `sent`, `edit slack`, `edit email`, `skip`, `go ahead and move <id>`. `--dry-run` prints drafts and hold titles, creates none. |
| E. Sent | On `sent`: `scripts/roster_apply.py --spec <spec> --ops '{"update":[{"match":"<name>","set":{"status":"Outreach Sent"}}]}' --out <body.json>` (survey studies: `Survey Sent`); body through `references/tracker.md` `update_item`; one `outreach-log.md` entry (`scaffold_workspace.py append-outreach-entry`); remind: update `participants.md`. |
| F. Reply | `--reply=<name>`: user pastes reply; run `scripts/classify.py reply "<the reply>"` - verbatim to the classifier, never paraphrased. `slot-picked` with a hold: user adds recruit to hold guests; row to `Scheduled` via `roster_apply.py`; remind: delete other holds. `booked`: same flip from the booking link. `declined`: row to `Cancelled`. `new-options`: back to phase C for new slots and holds. `free-text` (`lane: exception`): the one metered model call - read the reply, state the action picked, continue as above. |
| G. Moves | Only on `go ahead and move <id>`: show current and proposed time, attendees, and the `calendar-rules.md` rule; wait for a plain `yes`; move, read the event back, show the result. |
| H. Check | `--check`: per active study: roster rows in outreach status; search chat and mail for replies, last 14 days; classify each via `scripts/classify.py reply` (slot-picked, new-options, declined, free-text; a reply found but empty of text counts as no reply); propose exactly one action per row via the script's `action`: `book <name>`, `send <name>`, `edit`, `skip`, `decline`, `go`. Then `recruit_funnel.py --reminder`: after `--nudge-after` business days, no reply - draft one shorter follow-up (template first; free-text is the exception lane). |

Every internal run (and `--status`) ends with the recruitment table: `recruit_funnel.py --spec <spec> [--funnel-data <export>]`; `--status` prints the table and nothing else.

## External flow (`--external`)

One run, one stop (step 10). Never re-source a person already on a wave tab.

1. Roster rows past the initial status; every tab in `funnel.tabs`.
2. First wave: persona = product-analytics cohort; record `funnel.fit` (`users`, `accounts`, `as_of`, `basis`) via `roster_apply.py` funnel ops. Keep the first fit unless the user says `refit`.
3. Default cold wave: 50 sends, 1 to 2 contacts per account, most active accounts first.
4. Export allowed-to-send, do-not-contact, open-deal tabs to CSV; `scripts/source_contacts.py --contacts <csv> --dnc <csv> --deals <csv> --accounts "<list>" [--filter --industry --job-level --segment] [--stale-days <N>]`.
5. Ask every connected channel; merge by email; record the lowest-numbered source in the wave tab's Email Source column: (1) contact sheet; (2) analytics cohort; (3) feedback knowledge graph; (4) mail and calendar search on the account domain; (5) call-recording profiles; (6) roster rows; (7) any other connected CRM. Never guess an address from a pattern; never probe a mail server.
6. `source_contacts.py --check-emails "<emails>" --accounts "<accounts>"`. Drop do-not-contact, withheld, open-deal, opt-out contacts; at-risk account: hold for the account manager's OK (with `--coordinate`, draft chat notes asking for those OKs and the warm intro; never send; without it, one line - re-running with `--coordinate` drafts them). Org-chart search (issue 50): with `--coordinate`, search the org-chart connectors in `recruiting.org_chart_paths` for other teams and accounts that could help recruit; name findings in the drafted chat notes; empty list: one line - org chart not configured; continue without it.
7. Reuse a verified booking page or build one per `references/recruit-outreach.md`. Verify the public link shows bookable slots.
8. Copy the merge template sheet once per study to `funnel.sheet`. Draft, then: V1 `recruit_funnel.py --check-draft <draft>`; V2 self-test to the user's own inbox only; V3 open the link; V4 `recruit_funnel.py --spec <spec> --preflight --funnel-data <export>`. Export = `suppression_list` (identifiers from `recruitment.suppression_list`) + `participants` (workspace participants rows), so the suppress stage checks them deterministically.
9. Run the suppress stage (the three checks above). Tab with the reference headers; each skip: a row with `skip: <reason>` in Email Sent. Tab name into `funnel.tabs` (`roster_apply.py`).
10. Pre-send review (the stop): recruitment table, off-sheet contacts, the no-email-found list, flagged accounts, proposed calendar moves, the exact subject and body, the V1 to V4 results. Last line: "Click Mail Merge > Send Emails on the <tab> tab, or reply `send` and I will." Wait. `--dry-run` never reaches this stop.
11. Rerun V4; confirm the active tab; mark bounces " (bounced)" (never delete a row); append everyone emailed to the do-not-contact tab; flip named roster rows with `roster_apply.py`.
12. Every later run: find booking-page bookings; add each booker as `Scheduled` in one `roster_apply.py` batch.

The external run ends with the recruitment table: `recruit_funnel.py --spec <spec> --funnel-data <export> --wave <tab>`. Output never contains an email address; keep that true in anything pasted into chat or the ticket.

## Email send (MVP)

External participants table send path; no mail-merge add-on. Safety rule 1 keeps the agent at zero sends; the researcher runs the real send (`--send`) after the review.

1. Command: `python "${CLAUDE_PLUGIN_ROOT}/scripts/recruit_send.py" --participants <workspace>/recruitment/participants.md --template <workspace>/recruitment/email-merge-template.md`. Without `--send`: dry run - merged messages print; nothing changes (no send, no stamp, no write).
2. Status gates apply: sendable only at `invited`, `contact` filled, `DM sent (date)` empty; on success stamp `DM sent (date)`, advance to `scheduled`; a failed row: no stamp, stays `invited`. Suppression gate first: contact email on the configured `recruitment.suppression_list` file - row skipped and reported, dry run and real send alike.
3. One email per recipient: one `To`, no `Cc`/`Bcc`; a duplicate address sends once, later row reported. Contact values masked in the report; `--show-contacts` shows them.
4. `--send` needs the SMTP account in `recruit.email.*` (values in gitignored `config/org.yaml` or the `UXR_RECRUIT_*` env vars, never in the repo).
5. Template ships as `templates/workspace/recruitment/email-merge-template.example.md` (synthetic values only): copy into the workspace, rename, fill the message. A `{{token}}` names an approved column (`{{name_pseudonym}}` from `name/pseudonym`); unknown token stops the run before anything is sent.

If the researcher follows the email with a chat DM, it carries context plus the row's `prep note`, or nothing - no other content.

## Scripts

| Script | Contract |
|---|---|
| `scripts/recruit_funnel.py --spec <path> [--wave <tab>] [--preflight] [--reminder] [--funnel-data <json>] [--check-draft <file>] [--today <date>]` | Nine-row recruitment table; `--preflight` exits 2 with `BLOCK <account> / <first>: <reason>` lines or prints `PREFLIGHT OK: <n> rows ready on <tab>`; `--reminder` drafts nudges. |
| `scripts/recruit_send.py --participants <participants.md> --template <file> [--send] [--show-contacts] [--today <date>]` | MVP send (see Email send); exit 0 clean, 1 a send failed, 2 usage. |
| `scripts/source_contacts.py` | Sources and clears contacts; account match: normalized whole words ("Box" never matches "Dropbox"); missing do-not-contact or open-deal tab exits 2, sources nothing. |
| `scripts/roster_apply.py --spec <path> --ops <json-or-@file> --out <body.json> [--dry-run]` | Only spec write path: validate, render, write spec and body; exit 3 on validation failure, nothing written; duplicate adds promote only, never demote. |
| `scripts/calendar_prep.py <events.json> [--manager <names>] [--keep <id>] [--allow <id>]` | Classifies window events into `pto`, `immovable`, `movable`, `other`; weekends and declined events skipped. |
| `scripts/scaffold_workspace.py lookup-workspace / append-outreach-entry / validate-recruitment` | Workspace resolution, outreach log entries, participants table checks (issue 08). |

## Rules of last resort

- Every gate waits for a plain human word: `sent`, `yes`, `go`, `send`, `skip`, `decline`, `edit`. Never act on a guessed confirmation.
- One `update_item` per run via the spec pipeline; comments carry the `comments.footer`.
- "who have we contacted": answer with `--status`'s table, not a chat search transcript.
