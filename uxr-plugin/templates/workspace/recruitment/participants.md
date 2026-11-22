# Participants

One table per flow. Keep both tables even when one flow has no rows
yet; a participant leaves as `withdrawn`, never deleted.

Status vocabulary: identified, screened, invited, scheduled,
completed, incentive-sent, withdrawn. The list is locked; the recruit
command checks every status against it and against the status gates in
the recruit command before a row advances.

## Internal flow (default)

| participant id | name | role/segment | team/org area | source (org-chart path) | screener result | status | consent-to-record | DM sent (date) | notes |
|---|---|---|---|---|---|---|---|---|---|

## External flow (`--external`)

| participant id | name/pseudonym | contact | source (panel/channel) | screener result | status | consent-to-record | incentive status | DM sent (date) | prep note | notes |
|---|---|---|---|---|---|---|---|---|---|---|

The external screener records role/function fit and industry/segment
(the screening gates), then job level/seniority, company size
(headcount band), company revenue band, and company location/region.
The outcome goes in `screener result`.

Rules:

- One row per participant. Add and change rows through the recruit
  flow; the recruit command validates status values against the
  vocabulary above.
- Internal recruiting happens inside your own org, so real names and
  contact details may live in this file. Samples shipped in the
  repository stay synthetic.
- Emails and Slack handles stay in this file. Never copy them into the
  ticket, chat, or a deliverable.
