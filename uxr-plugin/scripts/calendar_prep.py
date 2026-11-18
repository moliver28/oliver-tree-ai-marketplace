#!/usr/bin/env python3
"""Classify a saved calendar dump so recruit never proposes a bad move (issue 10).

The recruit command saves the study window's calendar events to a JSON file
and this script classifies each event into one of four classes:

- ``pto``: out-of-office time; booking slots may never land on it.
- ``immovable``: never proposed as a move, at any level.
- ``movable``: safe to propose moving at level ii (with one confirm each).
- ``other``: ordinary events; movable only at level iii (with one confirm).

Weekends and events the user declined are skipped entirely. Immovable,
in priority order: any event with an attendee outside ``org.internal_domains``;
a 1:1 (or 1 on 1 / one on one) whose other attendee is a manager; the
protected titles (perf review, calibration, comp review, career conversation,
all hands, town hall, kickoff, QBR, hiring panels); titles or descriptions
with ``do not move``, ``dnm``, ``protected``, or ``[hold]``; config
``calendar.immovable_keywords``. Movable at level ii: focus / deep work /
block / hold / heads down / writing time / thinking time titles; untitled
holds (no title at all); a tentative response; the user is optional; a solo
working session; config ``calendar.movable_keywords``. Everything else is
``other``.

``--keep <id>`` marks one event immovable for this run (the recruit command's
``--keep`` flag). ``--allow <id>`` marks one event movable for this run --
never an event with an external attendee; classification order makes the
override impossible for those.

Usage::

    python scripts/calendar_prep.py <events.json> [--manager <names or emails>]
        [--keep <id>] [--allow <id>]
    python scripts/calendar_prep.py selftest

Exit codes: 0 classified, 2 usage or unreadable input, 3 selftest failed.

Output is JSON on stdout::

    {
      "pto":        [{"id", "title", "rule"}],
      "immovable":  [{"id", "title", "rule"}],
      "movable":    [{"id", "title", "rule"}],
      "other":      [{"id", "title", "rule"}],
      "skipped":    [{"id", "title", "reason"}],
      "counts":     {"pto": n, "immovable": n, "movable": n, "other": n,
                     "skipped": n}
    }

The script never writes anything and never touches the calendar; commands
write.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import config as _config  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SELFTEST = 3

#: Titles that mean out-of-office time. These are their own class: the
#: booking page must never open slots over them.
PTO_KEYWORDS: tuple[str, ...] = (
    "pto",
    "out of office",
    "ooo",
    "holiday",
    "vacation",
    "parental leave",
    "leave",
    "jury duty",
)

#: Protected titles (issue 10; config ``calendar.immovable_keywords`` adds).
IMMOVABLE_KEYWORDS: tuple[str, ...] = (
    "perf review",
    "performance review",
    "calibration",
    "comp review",
    "career conversation",
    "all hands",
    "all-hands",
    "town hall",
    "kickoff",
    "qbr",
    "hiring panel",
    "debrief",
    "onsite interview",
    "do not move",
    "dnm",
    "protected",
    "[hold]",
)

#: Titles level ii may propose moving (issue 10; config
#: ``calendar.movable_keywords`` adds). Untitled holds and response states
#: are handled separately, not by keyword.
MOVABLE_KEYWORDS: tuple[str, ...] = (
    "focus",
    "deep work",
    "block",
    "hold",
    "heads down",
    "writing time",
    "thinking time",
)

#: Titles that are a 1:1 with someone; only a manager 1:1 is immovable.
ONE_ON_ONE_RE = re.compile(r"\b1\s?[:\-]\s?1\b|1 on 1|one[- ]on[- ]one", re.IGNORECASE)


def _load_events(path: Path) -> list[dict]:
    """Read the saved dump: a bare list, or ``{"events": [...]}``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise _Usage(f"events file is not valid JSON: {exc}")
    except OSError as exc:
        raise _Usage(f"events file cannot be read: {exc}")
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        return data["events"]
    if isinstance(data, list):
        return data
    raise _Usage("events file must be a JSON list or {\"events\": [...]}")


class _Usage(Exception):
    pass


def _event_date(event: dict) -> date | None:
    """The local start date of an event, from ``start`` or ``date``."""
    for key in ("start", "start_time", "date"):
        value = event.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def _attendees(event: dict) -> list[dict]:
    people = event.get("attendees") or event.get("attendee_list") or []
    return [p for p in people if isinstance(p, dict)] if isinstance(people, list) else []


def _email(person: dict) -> str:
    return str(person.get("email") or person.get("mail") or "").strip()


def _name(person: dict) -> str:
    return str(
        person.get("display_name") or person.get("name") or person.get("label") or ""
    ).strip()


def _self_entry(event: dict, people: list[dict]) -> dict | None:
    """The user's own attendee row, from ``self`` or the ``self: true`` mark."""
    marker = event.get("self")
    if isinstance(marker, dict):
        return marker
    for person in people:
        if person.get("self") or person.get("is_self"):
            return person
    return None


def _response(value: str | None) -> str:
    return str(value or "").strip().lower()


def _is_external(person: dict, internal_domains: list[str]) -> tuple[bool, str]:
    """``(True, detail)`` when the attendee is provably outside the org.

    A non-empty ``org.internal_domains`` list is the authority: an attendee
    with an email whose domain is not listed is external. When config lists
    no domains, an explicit ``external: true`` attendee flag is the only
    signal (fail open here would let recruit move a customer meeting).
    """
    email = _email(person)
    if person.get("external") is True:
        return True, _name(person) or email or "attendee flagged external"
    if email and internal_domains:
        domain = email.rsplit("@", 1)[-1].strip().lower()
        if domain and domain not in {d.strip().lower() for d in internal_domains if d.strip()}:
            return True, domain
    return False, ""


def _is_manager(person: dict, managers: list[str]) -> bool:
    email = _email(person).lower()
    name = _name(person).lower()
    for token in managers:
        probe = token.strip().lower()
        if not probe:
            continue
        if email and email == probe:
            return True
        if name and (name == probe or probe in name):
            return True
    return False


def _contains(text: str, keywords: tuple[str, ...]) -> str:
    """The first keyword found in ``text`` (case-insensitive), else ''."""
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return keyword
    return ""


def _entry(event: dict, rule: str) -> dict:
    return {"id": _event_id(event), "title": str(event.get("title") or ""), "rule": rule}


def _event_id(event: dict, index: int = 0) -> str:
    for key in ("id", "event_id", "uid"):
        value = event.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    title = str(event.get("title") or "").strip()
    start = str(event.get("start") or event.get("date") or "").strip()
    return f"{title}-{start}-{index}" if title or start else f"event-{index}"


def classify_events(
    events: list[dict],
    config: dict | None = None,
    managers: list[str] | None = None,
    keep: list[str] | None = None,
    allow: list[str] | None = None,
) -> dict:
    """Classify every event; pure, no config load, safe to call directly.

    ``config`` carries ``org.internal_domains`` and ``calendar.*_keywords``;
    with no config the shipped keyword lists and no internal domains apply
    (then only an explicit attendee ``external`` flag proves externality).
    """
    config = config if isinstance(config, dict) else {}
    org = config.get("org") if isinstance(config.get("org"), dict) else {}
    calendar = config.get("calendar") if isinstance(config.get("calendar"), dict) else {}
    internal_domains = [str(d) for d in (org.get("internal_domains") or []) if str(d).strip()]
    manager_list = list(managers or []) + [str(m) for m in (calendar.get("manager_names") or [])]
    immovable_extra = tuple(
        str(k) for k in (calendar.get("immovable_keywords") or []) if str(k).strip()
    )
    movable_extra = tuple(
        str(k) for k in (calendar.get("movable_keywords") or []) if str(k).strip()
    )
    keep_ids = {str(v).strip() for v in (keep or []) if str(v).strip()}
    allow_ids = {str(v).strip() for v in (allow or []) if str(v).strip()}

    result: dict = {"pto": [], "immovable": [], "movable": [], "other": [], "skipped": []}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            result["skipped"].append(
                {"id": f"event-{index}", "title": "", "reason": "not an object"}
            )
            continue
        event_id = _event_id(event, index)
        title = str(event.get("title") or "")
        description = str(event.get("description") or event.get("notes") or "")
        haystack = f"{title} {description}"

        start = _event_date(event)
        if start is not None and start.weekday() >= 5:
            result["skipped"].append(_entry(event, "weekend"))
            continue

        people = _attendees(event)
        mine = _self_entry(event, people)
        others = [p for p in people if p is not mine]

        declined = _response(event.get("status")) in ("declined", "cancelled") or _response(
            (mine or {}).get("response")
        ) in ("declined", "cancelled", "no")
        if declined:
            result["skipped"].append(_entry(event, "declined"))
            continue

        external_hits = [
            detail for person in people for ok, detail in [_is_external(person, internal_domains)] if ok
        ]
        if event_id in keep_ids:
            result["immovable"].append(_entry(event, "keep override for this run"))
            continue
        if external_hits:
            # Acceptance: an external attendee is immovable at every level,
            # and --allow can never override it (this check runs first).
            result["immovable"].append(
                _entry(event, f"external attendee ({external_hits[0]})")
            )
            continue
        keyword = _contains(haystack, PTO_KEYWORDS)
        if keyword:
            result["pto"].append(_entry(event, f"out-of-office title ({keyword})"))
            continue
        keyword = _contains(haystack, IMMOVABLE_KEYWORDS + immovable_extra)
        if keyword:
            # A bare "hold" title is movable at level ii; only the protected
            # forms ("[hold]", "do not move", ...) land here.
            result["immovable"].append(_entry(event, f"protected title ({keyword})"))
            continue
        if ONE_ON_ONE_RE.search(title) and any(
            _is_manager(person, manager_list) for person in others
        ):
            manager_hit = next((_name(p) or _email(p) for p in others if _is_manager(p, manager_list)), "")
            result["immovable"].append(_entry(event, f"1:1 with a manager ({manager_hit})"))
            continue
        if event_id in allow_ids:
            result["movable"].append(_entry(event, "allow override for this run"))
            continue
        keyword = _contains(haystack, MOVABLE_KEYWORDS + movable_extra)
        if keyword:
            result["movable"].append(_entry(event, f"movable title ({keyword})"))
            continue
        if not title.strip():
            result["movable"].append(_entry(event, "untitled hold"))
            continue
        if _response((mine or {}).get("response")) == "tentative":
            result["movable"].append(_entry(event, "tentative response"))
            continue
        if (mine or {}).get("optional") is True or (mine or {}).get("is_optional") is True:
            result["movable"].append(_entry(event, "user is optional"))
            continue
        if len(people) <= 1:
            result["movable"].append(_entry(event, "solo working session"))
            continue
        result["other"].append(_entry(event, "ordinary event (level iii only)"))

    result["counts"] = {key: len(rows) for key, rows in result.items()}
    return result


def _event_datetime(event: dict, key: str) -> datetime | None:
    raw = str(event.get(key) or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _h12(moment: datetime, meridiem: str | None = None) -> str:
    hour = moment.hour % 12 or 12
    text = f"{hour}:{moment.minute:02d}"
    mer = meridiem or ("AM" if moment.hour < 12 else "PM")
    return f"{text} {mer}"


def _slot_label(day: date, start: datetime, end: datetime) -> str:
    start_m = "AM" if start.hour < 12 else "PM"
    end_m = "AM" if end.hour < 12 else "PM"
    span = f"{_h12(start, start_m)}-{_h12(end, end_m)}" if start_m == end_m \
        else f"{_h12(start)}-{_h12(end)}"
    return f"{day.strftime('%a %m/%d')}, {span}"


def pick_slots(
    events: list[dict],
    classes: dict,
    level: str = "ii",
    working_hours: str = "09:00-17:00",
    session_minutes: int = 30,
    slots_wanted: int = 3,
) -> dict:
    """Deterministic slot picking (W2): free gaps inside the working hours on
    a 15-minute grid, first fit per day in window order, one slot per day,
    3 to 5 slots across days. PTO blocks the whole day; weekend and declined
    events are never busy and never offered. A day with no free gap offers
    move candidates instead (movable events at level ii, movable plus other
    at level iii) - every move still needs its own confirm."""
    class_by_id: dict[str, str] = {}
    for name in ("pto", "immovable", "movable", "other", "skipped"):
        for entry in classes.get(name) or []:
            class_by_id[str(entry.get("id"))] = name
    try:
        start_text, end_text = working_hours.split("-")
        sh, sm = (int(part) for part in start_text.split(":"))
        eh, em = (int(part) for part in end_text.split(":"))
    except ValueError as exc:
        raise SystemExit(f"calendar_prep: working_hours must look like 09:00-17:00 ({exc})")

    pto_days: set[date] = set()
    busy: dict[date, list[tuple[datetime, datetime]]] = {}
    movable: dict[date, list[dict]] = {}
    other: dict[date, list[dict]] = {}
    seen_days: set[date] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        name = class_by_id.get(_event_id(event))
        if name is None or name == "skipped":
            continue
        start = _event_datetime(event, "start")
        end = _event_datetime(event, "end")
        if start is None or end is None:
            continue
        day = start.date()
        seen_days.add(day)
        if name == "pto":
            pto_days.add(day)
            continue
        if name == "immovable":
            busy.setdefault(day, []).append((start, end))
        elif name == "movable":
            movable.setdefault(day, []).append({"id": _event_id(event),
                                                "title": str(event.get("title") or "")})
            busy.setdefault(day, []).append((start, end))
        else:
            other.setdefault(day, []).append({"id": _event_id(event),
                                              "title": str(event.get("title") or "")})
            busy.setdefault(day, []).append((start, end))

    slots: list[dict] = []
    move_candidates: list[dict] = []
    for day in sorted(seen_days):
        if day.weekday() >= 5 or day in pto_days or len(slots) >= slots_wanted:
            continue
        work_start = datetime(day.year, day.month, day.day, sh, sm)
        work_end = datetime(day.year, day.month, day.day, eh, em)
        merged: list[tuple[datetime, datetime]] = []
        for start, end in sorted(busy.get(day) or []):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        gaps: list[tuple[datetime, datetime]] = []
        cursor = work_start
        for start, end in merged:
            if start > cursor:
                gaps.append((cursor, min(start, work_end)))
            cursor = max(cursor, end)
        if cursor < work_end:
            gaps.append((cursor, work_end))
        placed = False
        for gap_start, gap_end in gaps:
            minute = (15 - gap_start.minute % 15) % 15
            slot_start = gap_start.replace(second=0, microsecond=0) + timedelta(
                minutes=minute + (1 if minute == 0 and gap_start.second else 0))
            slot_end = slot_start + timedelta(minutes=session_minutes)
            if slot_end > gap_end:
                continue
            slots.append({"date": day.isoformat(),
                          "label": _slot_label(day, slot_start, slot_end),
                          "start": slot_start.strftime("%H:%M"),
                          "end": slot_end.strftime("%H:%M"), "kind": "free"})
            placed = True
            break
        if not placed and level != "i":
            pool = list(movable.get(day) or [])
            if level == "iii":
                pool += other.get(day) or []
            for source in pool:
                if all(candidate["id"] != source["id"] for candidate in move_candidates):
                    move_candidates.append(source)
    return {"level": level, "session_minutes": session_minutes,
            "slots": slots[:slots_wanted], "move_candidates": move_candidates,
            "fewer_than_3": len(slots) < 3}


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _parse_list(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK

    keep: list[str] = []
    allow: list[str] = []
    managers: list[str] = []
    positional: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("--manager", "--keep", "--allow"):
            if index + 1 >= len(args):
                print(f"calendar_prep: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            values = _parse_list(args[index + 1])
            if token == "--manager":
                managers.extend(values)
            elif token == "--keep":
                keep.extend(values)
            else:
                allow.extend(values)
            index += 2
            continue
        positional.append(token)
        index += 1

    if len(positional) != 1:
        print(
            "usage: calendar_prep.py <events.json> [--manager <names or emails>] "
            "[--keep <id>] [--allow <id>]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        events = _load_events(Path(positional[0]).expanduser())
    except _Usage as exc:
        print(f"calendar_prep: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = _config.load_config()
    except _config.ConfigError:
        config = {}
    result = classify_events(events, config=config, managers=managers, keep=keep, allow=allow)
    if "--pick" in args:
        level = "ii"
        if "--level" in args and args.index("--level") + 1 < len(args):
            level = args[args.index("--level") + 1]
        session_minutes = 30
        if "--session-minutes" in args and args.index("--session-minutes") + 1 < len(args):
            session_minutes = int(args[args.index("--session-minutes") + 1])
        slots_wanted = 3
        if "--slots" in args and args.index("--slots") + 1 < len(args):
            slots_wanted = max(3, min(5, int(args[args.index("--slots") + 1])))
        calendar = config.get("calendar") if isinstance(config.get("calendar"), dict) else {}
        working_hours = str(calendar.get("working_hours") or "09:00-17:00")
        pick = pick_slots(events, result, level=level, working_hours=working_hours,
                          session_minutes=session_minutes, slots_wanted=slots_wanted)
        print(json.dumps({"classes": result, "pick": pick}, ensure_ascii=False, indent=2))
        return EXIT_OK
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/calendar_prep.py selftest")

    config = {
        "org": {"internal_domains": ["example.com"]},
        "calendar": {
            "manager_names": ["Dana Lead"],
            "immovable_keywords": ["release freeze"],
            "movable_keywords": ["admin time"],
        },
    }
    events = [
        {
            "id": "e-manager-1on1",
            "title": "1:1 Dana / Sam",
            "start": "2026-11-09T10:00:00",
            "attendees": [
                {"email": "sam@example.com", "display_name": "Sam Researcher", "self": True},
                {"email": "dana@example.com", "display_name": "Dana Lead"},
            ],
        },
        {
            "id": "e-peer-1on1",
            "title": "1:1 catchup",
            "start": "2026-11-09T11:00:00",
            "attendees": [
                {"email": "sam@example.com", "self": True},
                {"email": "pat@example.com", "display_name": "Pat Peer"},
            ],
        },
        {
            "id": "e-external",
            "title": "Vendor sync",
            "start": "2026-11-09T12:00:00",
            "attendees": [
                {"email": "sam@example.com", "self": True},
                {"email": "rep@vendordomain.io", "display_name": "Vera Vendor"},
            ],
        },
        {
            "id": "e-external-allow",
            "title": "Customer call",
            "start": "2026-11-09T13:00:00",
            "attendees": [{"email": "sam@example.com", "self": True}, {"email": "c@client.co"}],
        },
        {"id": "e-focus", "title": "Focus block", "start": "2026-11-10T09:00:00", "attendees": []},
        {"id": "e-untitled", "title": "", "start": "2026-11-10T10:00:00", "attendees": []},
        {"id": "e-hold", "title": "[HOLD] Interview", "start": "2026-11-10T11:00:00", "attendees": []},
        {"id": "e-bare-hold", "title": "Hold for research", "start": "2026-11-10T14:00:00", "attendees": []},
        {
            "id": "e-dnm",
            "title": "Team sync",
            "description": "do not move this week",
            "start": "2026-11-10T12:00:00",
            "attendees": [],
        },
        {"id": "e-pto", "title": "OOO - family trip", "start": "2026-11-11T09:00:00", "attendees": []},
        {"id": "e-qbr", "title": "QBR prep", "start": "2026-11-11T10:00:00", "attendees": []},
        {"id": "e-hiring", "title": "Hiring panel - PM loop", "start": "2026-11-11T11:00:00", "attendees": []},
        {"id": "e-weekend", "title": "Saturday work", "start": "2026-11-14T10:00:00", "attendees": []},
        {
            "id": "e-declined",
            "title": "Optional all hands",
            "start": "2026-11-12T10:00:00",
            "status": "declined",
            "attendees": [],
        },
        {
            "id": "e-tentative",
            "title": "Team standup",
            "start": "2026-11-12T11:00:00",
            "attendees": [{"email": "sam@example.com", "self": True, "response": "tentative"}],
        },
        {
            "id": "e-optional",
            "title": "Brown bag",
            "start": "2026-11-12T12:00:00",
            "attendees": [{"email": "sam@example.com", "self": True, "optional": True}],
        },
        {"id": "e-solo", "title": "Draft review", "start": "2026-11-12T13:00:00", "attendees": []},
        {
            "id": "e-other",
            "title": "Design critique",
            "start": "2026-11-13T10:00:00",
            "attendees": [{"email": "sam@example.com", "self": True}, {"email": "pat@example.com"}],
        },
        {"id": "e-freeze", "title": "Release freeze", "start": "2026-11-13T11:00:00", "attendees": []},
        {"id": "e-admin", "title": "Admin time", "start": "2026-11-13T12:00:00", "attendees": []},
    ]

    result = classify_events(events, config=config, managers=["Dana Lead"])

    def ids(name: str) -> list[str]:
        return [row["id"] for row in result[name]]

    # Acceptance: a manager "1:1" is never offered as movable.
    check("manager 1:1 is immovable", "e-manager-1on1" in ids("immovable"), str(ids("immovable")))
    check("peer 1:1 (non-manager) is not immovable", "e-peer-1on1" not in ids("immovable"))
    # Acceptance: an external attendee is immovable at every level.
    check("external attendee is immovable", "e-external" in ids("immovable"))
    check(
        "allow override cannot move an external-attendee event",
        "e-external-allow" in ids("immovable"),
        str(ids("movable")),
    )
    check("focus block is movable", "e-focus" in ids("movable"))
    check("untitled hold is movable", "e-untitled" in ids("movable"))
    check("[hold] title is immovable", "e-hold" in ids("immovable"))
    check("bare hold title is movable", "e-bare-hold" in ids("movable"))
    check("do-not-move description is immovable", "e-dnm" in ids("immovable"))
    check("PTO title lands in pto", "e-pto" in ids("pto"))
    check("QBR is immovable", "e-qbr" in ids("immovable"))
    check("hiring panel is immovable", "e-hiring" in ids("immovable"))
    check("weekend is skipped", "e-weekend" in [s["id"] for s in result["skipped"]])
    check("declined is skipped", "e-declined" in [s["id"] for s in result["skipped"]])
    check("tentative response is movable", "e-tentative" in ids("movable"))
    check("optional attendee is movable", "e-optional" in ids("movable"))
    check("solo working session is movable", "e-solo" in ids("movable"))
    check("ordinary event is other", "e-other" in ids("other"))
    check("config immovable keyword applies", "e-freeze" in ids("immovable"))
    check("config movable keyword applies", "e-admin" in ids("movable"))

    # keep override: an ordinary event pinned for one run.
    kept = classify_events(events, config=config, keep=["e-other"])
    check(
        "keep override forces immovable",
        "e-other" in [row["id"] for row in kept["immovable"]],
    )

    # allow override on a non-external event works.
    allowed = classify_events(events, config=config, allow=["e-peer-1on1"])
    check(
        "allow override makes a level-iii event movable",
        "e-peer-1on1" in [row["id"] for row in allowed["movable"]],
    )

    # No config: only the explicit external flag proves externality.
    noconfig = classify_events(
        [
            {
                "id": "e-flag",
                "title": "Sync",
                "start": "2026-11-09T10:00:00",
                "attendees": [{"email": "a@somewhere.io", "external": True}],
            }
        ],
        config={},
    )
    check("explicit external flag works with empty config", "e-flag" in [r["id"] for r in noconfig["immovable"]])

    # Every event lands in exactly one class (or is skipped), and counts add up.
    seen = [row["id"] for key in ("pto", "immovable", "movable", "other") for row in result[key]]
    skipped_ids = [row["id"] for row in result["skipped"]]
    check(
        "classification is total: no event in two classes",
        len(seen) + len(skipped_ids) == len(events)
        and len(set(seen)) == len(seen)
        and not (set(seen) & set(skipped_ids)),
        f"{len(seen)} classified + {len(skipped_ids)} skipped vs {len(events)} events",
    )
    check(
        "counts match the lists",
        result["counts"] == {
            "pto": len(result["pto"]),
            "immovable": len(result["immovable"]),
            "movable": len(result["movable"]),
            "other": len(result["other"]),
            "skipped": len(result["skipped"]),
        },
    )

    # W2 slot picking: deterministic free-gap fit on the shipped window fixture.
    window_path = PLUGIN_ROOT / "tests" / "fixtures" / "calendar" / "window.json"
    if window_path.is_file():
        dump = json.loads(window_path.read_text(encoding="utf-8"))
        window_events = dump.get("events") or []
        window_classes = classify_events(
            window_events,
            config={"org": {"internal_domains": ["example.com"]},
                    "calendar": {"manager_names": ["Sam Okafor"]}},
        )
        pick = pick_slots(window_events, window_classes, level="ii",
                          working_hours="09:00-17:00", session_minutes=30)
        labels = [slot["label"] for slot in pick["slots"]]
        dates = [slot["date"] for slot in pick["slots"]]
        check("pick: 3 slots across days", len(pick["slots"]) == 3 and len(set(dates)) == 3,
              json.dumps(labels, ensure_ascii=False))
        check("pick: no PTO-day slot", all(slot["date"] != "2026-11-19" for slot in pick["slots"]),
              json.dumps(dates))
        check("pick: no weekend slot", all(
            datetime.fromisoformat(slot["date"]).weekday() < 5 for slot in pick["slots"]))
        check("pick: label shape", all(
            re.fullmatch(r"\w{3} \d{2}/\d{2}, \d{1,2}:\d{2}(?: [AP]M)?-\d{1,2}:\d{2} [AP]M", label)
            for label in labels), json.dumps(labels, ensure_ascii=False))
        check("pick: 15-minute grid", all(
            int(slot["start"].split(":")[1]) % 15 == 0 and int(slot["end"].split(":")[1]) % 15 == 0
            for slot in pick["slots"]))
        check("pick: deterministic", pick_slots(window_events, window_classes, level="ii") == pick_slots(
            window_events, window_classes, level="ii"))
        check("pick: declined event never busy", all(
            "Team lunch" not in slot["label"] for slot in pick["slots"]))
        level_i = pick_slots(window_events, window_classes, level="i")
        check("pick: level i stays free-only", level_i["move_candidates"] == [])
    else:
        check("pick: window fixture", False, "tests/fixtures/calendar/window.json missing")

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
