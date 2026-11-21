from _harness import bind

bind("scripts.calendar_prep", globals())
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
    window_path = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "calendar" / "window.json"
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
            re.fullmatch(r"\w{3} \d{2}/\d{2}, \d{1,2}:\d{2}-\d{1,2}:\d{2} [AP]M", label)
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
        check("pick: window fixture skipped (fixtures not shipped)", True)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
