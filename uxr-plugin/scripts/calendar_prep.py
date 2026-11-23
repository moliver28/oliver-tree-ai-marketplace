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

``--dump <file>`` adds one more saved calendar dump; repeat it once per
calendar. The dumps' events are read after the positional file's, and
``pick_slots`` unions each day's busy intervals with overlap dedup
before picking, so availability spans calendars; one dump is unchanged.

Usage::

    python scripts/calendar_prep.py <events.json> [--dump <events.json>]...
        [--manager <names or emails>] [--keep <id>] [--allow <id>]
    python scripts/calendar_prep.py <events.json> --pick [--level i|ii|iii]
        [--session-minutes <N>] [--slots <3-5>]   (W2: the slot picker)

Exit codes: 0 classified, 2 usage or unreadable input.

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
from lib.util import force_utf8_stdio as _force_utf8_stdio, parse_list as _parse_list  # noqa: E402  (shared plumbing)

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


def _h12(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}"


def _slot_label(day: date, start: datetime, end: datetime) -> str:
    """Golden slot-line format (R10 byte parity): ``Wed 11/18, 1:00-1:30 PM``
    - the meridiem rides on the end time only."""
    meridiem = "AM" if end.hour < 12 else "PM"
    return f"{day.strftime('%a %m/%d')}, {_h12(start)}-{_h12(end)} {meridiem}"


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
        if name in ("movable", "other"):
            (movable if name == "movable" else other).setdefault(day, []).append(
                {"id": _event_id(event), "title": str(event.get("title") or "")})
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


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK

    keep: list[str] = []
    allow: list[str] = []
    managers: list[str] = []
    dumps: list[str] = []
    options: dict[str, str] = {}
    positional: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--pick":
            options["--pick"] = "1"
            index += 1
            continue
        if token == "--dump":
            if index + 1 >= len(args):
                print(f"calendar_prep: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            dumps.append(args[index + 1])
            index += 2
            continue
        if token in ("--manager", "--keep", "--allow", "--level", "--session-minutes", "--slots"):
            if index + 1 >= len(args):
                print(f"calendar_prep: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            values = _parse_list(args[index + 1])
            if token == "--manager":
                managers.extend(values)
            elif token == "--keep":
                keep.extend(values)
            elif token == "--allow":
                allow.extend(values)
            else:
                options[token] = values[0] if values else ""
            index += 2
            continue
        positional.append(token)
        index += 1

    if len(positional) > 1 or (not positional and not dumps):
        print(
            "usage: calendar_prep.py <events.json> [--dump <events.json>]... "
            "[--manager <names or emails>] [--keep <id>] [--allow <id>] "
            "[--pick [--level i|ii|iii] [--session-minutes <N>] [--slots <3-5>]]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        events: list[dict] = []
        sources = ([Path(positional[0]).expanduser()] if positional else []) + [
            Path(value).expanduser() for value in dumps
        ]
        for source in sources:
            events.extend(_load_events(source))
    except _Usage as exc:
        print(f"calendar_prep: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = _config.load_config()
    except _config.ConfigError:
        config = {}
    result = classify_events(events, config=config, managers=managers, keep=keep, allow=allow)
    if "--pick" in options:
        try:
            session_minutes = int(options.get("--session-minutes") or 30)
            slots_wanted = max(3, min(5, int(options.get("--slots") or 3)))
        except ValueError:
            print("calendar_prep: --session-minutes and --slots take integers", file=sys.stderr)
            return EXIT_USAGE
        calendar = config.get("calendar") if isinstance(config.get("calendar"), dict) else {}
        working_hours = str(calendar.get("working_hours") or "09:00-17:00")
        pick = pick_slots(events, result, level=options.get("--level") or "ii",
                          working_hours=working_hours,
                          session_minutes=session_minutes, slots_wanted=slots_wanted)
        print(json.dumps({"classes": result, "pick": pick}, ensure_ascii=False, indent=2))
        return EXIT_OK
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(main())
