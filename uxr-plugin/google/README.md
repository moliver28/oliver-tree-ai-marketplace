# Google mail merge (SETUP)

`mail-merge.gs` is the Google-side engine for the recruit flow (#91 tracking,
#92 event-timed follow-ups). Google runs the sends from your account. The repo
owns the script source. The plugin's `recruit_send.py` covers the SMTP path.

## Setup

1. Open the merge Sheet in Google Sheets.
2. Select `Extensions > Apps Script`. The editor opens.
3. Delete the sample code in `Code.gs`.
4. Paste all of `mail-merge.gs` into `Code.gs`. Save the project.
5. Choose `mergeSend` in the function list. Click **Run**.
6. Google asks you to approve access. Review the scopes and approve. The run
   creates the five tabs and sends nothing.
7. Fill the Config tab (see the table below). Set `calendar_name`,
   `event_regex`, `followup_hours`, and `booking_url` at least.
8. Select `Deploy > New deployment`. Choose **Web app** as the type.
9. Set `Execute as: me`. Set `Who has access: Anyone`.
10. Click **Deploy**. Copy the web app URL.
11. Paste the URL into the `webapp_url` cell on the Config tab.
12. Choose `setupScreener` in the function list. Click **Run**. The script
    builds the screener Form, writes `Book your session: <booking_url>` to the
    confirmation page, and logs the Form edit URL.
13. Install the recurring trigger. Click the **Triggers** icon (clock) in the
    editor. Click **Add Trigger**. Choose `syncEvents`. Choose **Time-driven**
    as the event source. Choose **Minute timer** and **Every 15 minutes**.
    Click **Save**.
14. Test with one row. Add one row to the Wave tab with your own address in
    the Email cell. Choose `mergeSend`. Click **Run**. Check the message and
    the Tracking tab.

## Schedule a send

Add a small wrapper to `Code.gs` and edit the date:

```
function sendAtNine() {
  scheduleSend("Wave", "2026-11-30 09:00");
}
```

Choose `sendAtNine`. Click **Run**. Google creates a one-off trigger and sends
near the requested time. Google picks the exact minute. The trigger deletes
itself after it fires.

## Merge rules

The Wave tab holds one row per recipient. The columns are fixed:
`Tracking ID | Email | Name | Study | Subject | Body | Email Sent`.

- `mergeSend` sends to rows with an address, a Subject, and a Body.
- The stamp in `Email Sent` blocks a second send. Never edit it by hand.
- Recipients with an `unsub` row on Tracking are skipped.
- `{{token}}` in Subject or Body names a column. The token is lowercase. Runs
  of non-letter characters read as one underscore (`name/pseudonym` becomes
  `{{name_pseudonym}}`). `{{booking_url}}` pulls the Config cell.
- An unknown token stops the pass before any send. Fix the token and run again.
- Write links as `[text](https://example.com)`. Tracking wraps them, so a
  click logs before the reader lands on the page.

## Tracking limits

Open counts are an estimate. Readers who block images never log an open. The
Gmail image proxy fetches the pixel once and serves its cache later, so repeat
opens do not log. The proxy can also log an open before anyone reads. Treat
opens as a rough signal. Clicks and unsubscribes are direct events. The script
logs only what the web app sees: opens, clicks, unsubscribes, and calendar
cancellations. No script can watch a mailbox from outside. Deletes and trash
moves are not trackable.

## Tabs and columns

| Tab | Columns | Notes |
|---|---|---|
| Wave | `Tracking ID` `Email` `Name` `Study` `Subject` `Body` `Email Sent` | one row per recipient; the merge stamps `Email Sent` |
| Tracking | `date` `route` `email` `study` `target` `note` | routes: `open` `click` `unsub` `cancelled` |
| Followups | `when` `email` `template_key` `study` `status` | status: `pending` `sent` `cancelled` |
| Prep | `when` `event` `email` `items` | a cancelled event prefixes the event cell with `[cancelled]` |
| Config | `name` `value` | one row per setting; the first run creates it |

## Config cells

| Cell (column A) | Value (column B) | Default |
|---|---|---|
| `webapp_url` | The web app URL from the deploy step. Paste it after you deploy. | (empty) |
| `tracking_on` | `true` logs opens and clicks. `false` turns both off. | `true` |
| `unsub_on` | `true` adds the Unsubscribe footer to every message. | `true` |
| `calendar_name` | The exact name of the calendar that carries the session events. | (empty) |
| `event_regex` | `syncEvents` follows events whose title matches this expression. | `Session\|Interview` |
| `followup_hours` | Hours between the event start and the follow-up send. | `48` |
| `prep_on` | `true` creates Prep rows and emails you the prep brief. | `false` |
| `prep_lead_hours` | Hours before the event start for the prep brief. | `24` |
| `booking_url` | The appointment schedule link. See `references/checklists/appointment-link.md`. | (empty) |
| `form_id` | The screener Form id. `setupScreener` fills this cell. | (empty) |

## Follow-ups and prep

`syncEvents` scans the named calendar every 15 minutes. Events whose title
matches `event_regex` create a follow-up at `followup_hours` after the start.
The contact is the event guest who is not you. Delete the event, or rename it
away from the regex, and pending follow-ups are cancelled. Sent follow-ups stay
sent. The follow-up carries the booking link when `booking_url` is set. With
`prep_on` on, the script adds a Prep row at `prep_lead_hours` before the start
and emails you the brief. Fill the `items` cell before the session.

## Screener and booking

`setupScreener` builds the screener Form. The confirmation page carries the
booking link, so the respondent books straight after the form. Google Forms
has no per-respondent gate. Review the answers in the Form after each
submission. Each submission lands as a Wave-tab row with a fresh Tracking ID.

## Quotas

MailApp counts one unit per recipient per day. A consumer account sends to
about 100 recipients a day. Keep each wave under that number. One recurring
trigger scans due work, so the trigger cap never binds.
