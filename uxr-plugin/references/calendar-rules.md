# Calendar rules for recruit

These rules decide which events `recruit` may offer as session slots and
which it may propose moving; `scripts/calendar_prep.py` enforces the
deterministic parts and the command follows the same lists. Config: `calendar.working_hours`,
`calendar.default_level`, `calendar.max_moves_per_recruit`,
`calendar.manager_names`, `calendar.movable_keywords`,
`calendar.immovable_keywords`, and `org.internal_domains`.

## Slot levels

| Level | Allowed |
|---|---|
| i | Free slots only |
| ii (default) | Free slots, then propose moves of movable events, one confirm each |
| iii | Any event that is not immovable, one confirm each |

The level flag is `--level=i|ii|iii` on `recruit` (default `ii`).

## Immovable (never proposed as a move, at any level)

- A 1:1 (or 1-1 / one on one) whose other attendee is a manager or
  skip-level manager (`calendar.manager_names`, or `--manager` on
  `calendar_prep.py`).
- Titles with: perf review, performance review, calibration, comp review,
  career conversation, all hands, town hall, kickoff, QBR, hiring panels,
  onsite interviews.
- Any event with an attendee whose email domain is not in
  `org.internal_domains` (or an attendee explicitly flagged external when
  the domain list is empty). Immovable at every level; `--allow` can never
  override it.
- Titles or descriptions containing `do not move`, `dnm`, `protected`, or
  `[hold]`. A bare "hold" title is movable; a `[hold]` title is not.
- Anything listed in `calendar.immovable_keywords`.

## Movable at level ii (one confirm each)

- Titles with: focus, deep work, block, hold, heads down, writing time,
  thinking time; plus `calendar.movable_keywords`.
- Untitled holds (no title at all).
- A tentative response on the user's own invite.
- Events where the user is an optional attendee.
- A solo working session (only the user is attending).

Everything else is `other`: movable only at level iii, one confirm each.

## Overrides for one run

- `--keep=<eventId>`: never propose moving this event, whatever it is.
- `--allow=<eventId>`: treat this event as movable for this run. Never
  effective on an event with an external attendee.

## Hard limits

- At most 3 moves per recruit per run (`calendar.max_moves_per_recruit`).
- Every move needs its own "go" for that one proposal (phase G shows the
  current time, the proposed time, the attendees, and the rule).
- Never move an event that has an attendee outside `org.internal_domains`.
- A private hold (`[HOLD] ...`, no attendees) is the only event the
  command creates without a separate go.

## Hold titles

```
[HOLD] {study_short_name} chat: {first_initial}. {last_name} ({day_abbrev} {M/D})
```

No attendees. The description carries the recruit's name, email, the line
"Copy either line above into 'Add guests' to send the invite.", the study
title, and the ticket URL. Because the title starts with `[hold]`, the hold
protects itself: `calendar_prep.py` classifies it immovable.

## Running the classifier

Save the study window's calendar events to a JSON file (a bare list or
`{"events": [...]}`), then:

```
python scripts/calendar_prep.py <events.json> [--manager "<names or emails>"]
    [--keep <id>] [--allow <id>]
```

Output is JSON with `pto`, `immovable`, `movable`, `other`, `skipped`
(weekends and declined events), and `counts`. Weekends and declined events
are never offered and never moved. Pick 3 to 5 slots across days, rounded
to 15 minutes, inside `calendar.working_hours`; fewer than 3 means ask to
try level iii.
