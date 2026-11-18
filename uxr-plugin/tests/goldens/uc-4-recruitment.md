# UC4 — Recruitment flow (`/uxr-plugin:uxr-recruit UXR-101`, internal)

Run: 2026-11-17, 21:55:30 start. Level ii (default), window 14 days. Calendar reads, DM/email sends, and event creates are BLOCKED-EXTERNAL and fixture-backed from `baseline-fixtures/calendar-window.json` / `roster.csv`.

## Run 1 — empty roster stop (verbatim)

Setup ran: config (cached), `lookup-workspace` -> workspace path printed, exit 0; ticket read fixture (Planned, start 2026-11-17, target 2026-12-01); spec loaded, roster empty. Window check: start = max(today, start date) = 2026-11-17; end = min(target, today+14) = 2026-12-01. `validate-recruitment` -> `recruitment table matches interview/internal: header and statuses are valid` (exit 0). Then:

> The roster is empty. Add participants with the shorthand:
>
> `roster+=Name|email|slack|reason|status|channel` (via `edit UXR-101`)

Command stops.

## Roster fill (plugin write path: `roster_apply.py`, exit 0)

```
applied: 5 change(s)
  add: Participant A (Potential Candidate, internal)
  add: Participant B (Potential Candidate, internal)
  add: Participant C (Potential Candidate, internal)
  add: Participant D (Potential Candidate, internal)
  add: Participant E (Potential Candidate, external)
  wrote spec: .../specs/UXR-101.spec.json
  wrote body: .../UXR-101-body.json
```

## Run 2 — internal flow

Phase B (pick): four internal rows at the initial status; external row skipped with the pointer line:

> Participant E is on the external channel; the internal calendar flow does not contact customers. Use `--external` for the customer funnel.

Phase C (slots): BLOCKED-EXTERNAL calendar read -> fixture dump. `calendar_prep.py` classification (verbatim, exit 0):

```
PTO       evt-003 'PTO: Taylor Brooks'            rule: out-of-office title (pto)
IMMOVABLE evt-004 'Roadmap review with leadership' rule: protected title (roadmap review)
IMMOVABLE evt-005 '1:1 Jordan / Sam'              rule: 1:1 with a manager (Sam Okafor)
IMMOVABLE evt-006 'All-hands'                     rule: protected title (all-hands)
IMMOVABLE evt-008 'Hiring loop: UX researcher panel' rule: protected title (hiring loop)
MOVABLE   evt-002 'Design sync: navigation concept' rule: movable title (design sync)
OTHER     evt-001 'Daily standup'                rule: ordinary event (level iii only)
SKIPPED   evt-007 'Team lunch (optional)'        rule: declined
```

Level ii picks free + movable; 3 slots chosen across days, 30 minutes, inside 09:00-17:00:

> - Wed 11/18, 1:00-1:30 PM
> - Tue 11/24, 10:00-10:30 AM
> - Thu 11/26, 2:00-2:30 PM

Phase D (drafts, per recruit; `top_rq` = "Where do first-week users look for the timeline when they want to plan?"). Participant A verbatim block:

> **Chat DM draft** (Participant A):
>
> Hey Participant, quick ask. I'm running a research session for New user navigation study: timeline discoverability. Looking for 30 minutes of your time in the next couple of weeks (you own the first-run funnel metrics). The session focuses on where new users look for planning features. Any of these work?
>
> - Wed 11/18, 1:00-1:30 PM
> - Tue 11/24, 10:00-10:30 AM
> - Thu 11/26, 2:00-2:30 PM
>
> If none fit, send a few that do. I'll send the calendar invite once we land on a time.
>
> **Email draft** (Participant A) — Subject: `Quick research chat on New user navigation study: timeline discoverability?`
>
> (same body, closing with) Thanks, Jordan
>
> **Calendar holds** (private, no attendees; BLOCKED-EXTERNAL event create, titles verbatim):
>
> - `[HOLD] Timeline Discoverability chat: P. A (Wed 11/18)`
> - `[HOLD] Timeline Discoverability chat: P. A (Tue 11/24)`
> - `[HOLD] Timeline Discoverability chat: P. A (Thu 11/26)`
> - (same three holds per Participant B, C, D — 12 total)
>
> Reply with: `sent` · `edit slack` · `edit email` · `skip` · `go ahead and move <id>`

Participants B, C, D: same shape with their own reasons; C has no slack handle so only the email draft (roster row has no slack -> DM skipped per the command rule).

Scripted user: `sent` (all four).

Phase E (sent): `roster_apply.py` update verbatim (exit 0):

```
  update: Participant A Potential Candidate -> Outreach Sent
  update: Participant B Potential Candidate -> Outreach Sent
  update: Participant C Potential Candidate -> Outreach Sent
  update: Participant D Potential Candidate -> Outreach Sent
  wrote spec: .../specs/UXR-101.spec.json
  wrote body: .../UXR-101-body.json
```

BLOCKED-EXTERNAL `update_item` fixture: fixture UXR-101 body refreshed with the roster table. `append-outreach-entry` x4 exit 0; `recruitment/outreach-log.md` now holds (verbatim):

```
- **2026-11-17** Participant D via chat


- **2026-11-17** Participant C via email


- **2026-11-17** Participant B via email


- **2026-11-17** Participant A via email
```

Reminder printed: update `recruitment/participants.md`.

## Run-ending recruitment table (`recruit_funnel.py --spec`, exit 0, verbatim)

```
| Metric | Internal users | In-product accounts | In-product users | Other accounts | Other users |
|---|---|---|---|---|---|
| Fit | 4 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (0) |
| Looked at | 4 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (0) |
| Allowed | 4 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (0) |
| Not allowed | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| Sent | 4 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| Bounced | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| Scheduled | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| Attempted % of fit | 100% (0%) | - (-) | - (-) | - (-) | 0% (0%) |
| Recruited % of fit | 0% (0%) | - (-) | - (-) | - (-) | 0% (0%) |

wave: Wave 1; recorded tabs: none yet
```

(The `Other users` column is Participant E, external, never contacted — output carries no email addresses per the script contract.)

## UC4 metering

| Metric | Value |
|---|---|
| Wall time | 21:55:30 -> 22:05:40 (10m10s) |
| Inference turns | 9 tool-call rounds |
| Token delta | 15,515 consumed (meter 14,850,203 -> 14,834,688) |
| Script executions (plugin-instructed) | 8 (lookup-workspace, validate-recruitment, roster_apply x2, calendar_prep, build_body (markdown refresh), append-outreach-entry x4, recruit_funnel) |
| Subagent dispatches | 0 |
| Blocked-external steps | calendar events read (fixture dump); hold event creates x12; DM/email sends (drafts only by design); `update_item` body push (fixture) |
