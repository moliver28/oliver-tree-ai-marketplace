# Outreach templates and the external send checks (recruit)

Everything here is drafts only; the one exception is the external
self-test, which goes only to the user's own inbox.

## Internal chat DM (verbatim shape)

```
Hey {first_name}, quick ask. I'm running a research session for {study_title}.
Looking for {session_length} of your time in the next couple of weeks
({why_this_recruit}).{focus_clause} Any of these work?

<slot lines>

If none fit, send a few that do. I'll send the calendar invite once we land
on a time.
```

The focus clause is " The session focuses on {work_area}." when the roster
row has a work_area; otherwise a one-line condensed topic from the spec;
otherwise nothing. Never two spaces in a row when the clause is dropped.

## Internal email

Subject: `Quick research chat on {study_title}?`

Body: the same content as the DM, closing with "Thanks," and the user's
first name.

## After the user says "sent"

1. Set the roster row to `Outreach Sent` (or `Survey Sent`) through the
   spec pipeline (`scripts/roster_apply.py`), push the body, and append one
   `outreach-log.md` entry (`scaffold_workspace.py append-outreach-entry`).
2. Remind the user to update `participants.md`.

Reply options offered with every draft block: `sent`, `edit slack`,
`edit email`, `skip`, `go ahead and move <eventId>`.

## Mass email (external waves)

- Merge tokens match the sheet headers exactly: `{{First name}}`,
  `{{Booking link}}`. A single-brace or wrong-case token ships as literal
  text; never mix `{first_name}` and `{{First name}}`.
- Wave tab headers, in order: `Account Name | First name | Last name |
  Recipient | Email Sent | Booking link | Email Source`.
- Every skip is still a row, with a blank Recipient and
  `skip: <reason>` in Email Sent. Never delete a row; mark bounces with
  " (bounced)". The suppress stage marks its rows the same way:
  `skip: suppressed (status law)`, `skip: suppressed (bounce)`, or
  `skip: suppressed (suppression list)`.
- One wave tab per send; save the tab name into `funnel.tabs` in the spec.

## The suppress stage (deterministic, zero model calls)

Before any invite, three checks remove rows from the ready count:

1. Status law: never re-contact `completed`, `incentive-sent`,
   `withdrawn`, or `cancelled`.
2. Bounce marks: never email a recipient marked " (bounced)" on an
   earlier wave.
3. Suppression list: never contact anyone on the file at
   `recruitment.suppression_list` (one identifier per line, an email or
   an account id). The plugin ships no list; the file must read when
   configured, or the checks fail closed (exit 2).

## The four checks before any mass send

- **V1**: the draft keeps `{{First name}}` and `{{Booking link}}` and the
  body holds no `http`. (`recruit_funnel.py --check-draft <file>`)
- **V2**: the self-test email (to the user's own inbox only) shows the
  exact booking link and no redirect URL.
- **V3**: the link opens the booking page and the page shows bookable
  slots.
- **V4**: `recruit_funnel.py --spec <spec> --preflight` prints
  `PREFLIGHT OK: <n> rows ready on <wave>` plus one suppressed counts
  line per check (`status-law`, `bounce`, `suppression-list`).

Rule 6 of the issue: if your mail tool rewrites links (the reference tool
redirected every URL), the draft body carries no URL at all. The booking
link travels in its merge column, or the command prints it for the user to
paste. Retest V2 on your own mail tool.

## Booking page settings (build or reuse a verified page)

- Window: 2 to 3 weeks out. Duration: 60 minutes. Buffer: none.
- At most 4 bookings per day.
- The notetaker (`org.notetaker_email`) joins as co-host.
- The moderator's meeting link goes in the description.
- One required field: "Current Work Title".
- Reminders at 1 day, 8 hours, 10 minutes, and 0 minutes.
- Never open slots over PTO (`calendar_prep.py` classifies `pto` events).
- Verify the public link shows bookable slots before V3.

## The meeting-service law

Calendar events created by recruitment never auto-attach a conferencing
link. The join link comes only from the configured meeting service's
own flow: `recruitment.meeting_service` (default `appointment-link`;
one of `appointment-link`, `none`, `google-meet`, `zoom`, `other`).
The default means zero auto-created links. No Google Meet link may ever
appear unless the config names `google-meet` and the user's own flow
creates it. The V2 self-test law is unchanged: the self-test email
shows the exact booking link and no redirect URL.

## The pre-send stop (external flow, exactly once)

Show, in order: the recruitment table, off-sheet contacts, the "no email
found" list, flagged accounts (open deals, at-risk), proposed calendar
moves, the exact subject and body, and the V1 to V4 results. Last line:

```
Click Mail Merge > Send Emails on the <tab> tab, or reply `send` and I will.
```

`--dry-run` never reaches this stop; nothing is created.

## After the send

Rerun V4 and confirm the active tab. Mark bounces " (bounced)" (never
delete the row). Append everyone emailed to the do-not-contact tab. Flip
named roster rows with `roster_apply.py`. Every later run: find booking-page
bookings and add each booker as `Scheduled` in one `roster_apply.py` batch.

## Privacy

No customer email or account list goes into the repository, the ticket
(outside engaged roster rows), or chat logs. Refer to a contact as account
plus first name; `recruit_funnel.py` scrubs email addresses from its output
as a last resort.
