# Runbook — Create a Google Calendar appointment schedule and wire the booking link

Executor: computer-use agent (desktop browser). Purpose: create the appointment
schedule that the screener confirmation page points to. Finish: the booking
link sits in the `booking_url` cell on the merge Sheet Config tab.

## Before you start

- Use a desktop browser. The Calendar mobile apps cannot create appointment
  schedules.
- Read the `event_regex` cell on the merge Sheet Config tab first. The booking
  title must match it, or `syncEvents` will not see the bookings.
- Read the `calendar_name` cell on the same tab. The schedule must live on that
  calendar.

## Steps

1. Open `https://calendar.google.com` in the browser. Sign in with the research
   account.
2. Click **Create** at the top left.
3. Click **Appointment schedule**.
4. Type the schedule title in the title box. Use a title the `event_regex`
   cell matches. The default regex matches `Session` or `Interview`, so
   `Research session` fits.
5. Set the appointment duration. Use the study session length.
6. Set the days and hours under **General availability**.
7. Check the time zone. Set it to the research time zone.
8. Open the **Calendars** section. Pick the calendar the `calendar_name` cell
   names.
9. Review the **Scheduling window**. Google sets a 4-hour minimum lead time.
   Keep it, unless the study books same-day sessions.
10. Click **Next**.
11. Type the booking page description. Keep **Google Meet** for remote
    sessions. Remove it for in-person studies.
12. Click **Save**. Google creates the booking page.
13. Find the booking page under **Booking pages** in the left rail.
14. Hover over the booking page. Click **Copy link**. The link is on the
    clipboard.
15. Open the merge Sheet. Open the Config tab.
16. Find the `booking_url` row in column A.
17. Paste the link into the cell in column B on that row.
18. Open the pasted link in a new tab. The booking page must load.

## After you finish

- Run `setupScreener` again if you changed the `booking_url` cell. The script
  writes the link into the Form confirmation text at run time.
- New bookings create calendar events. The event title carries the schedule
  title, so `syncEvents` matches it and schedules the follow-up.
- Do not rename the schedule later without checking `event_regex`. A title the
  regex does not match cancels pending follow-ups.

## Source

Steps verified against the Google Calendar Help pages "Create an appointment
schedule" (support.google.com/calendar/answer/10729749) and "Share your
appointment schedule" (support.google.com/calendar/answer/10733297), fetched
2026-11-23.
