"""Cross-calendar availability selftest (the mail-merge wave): --dump union.

Two overlapping calendar dumps must behave as one merged calendar: dump
A plus a second dump whose busy intervals sit inside A's picks exactly
the slots dump A picks alone (the union dedups the overlap), while a
dump that extends A's busy time pushes the first free slot past the
union's end. The classification spans every dump, the repeatable
``--dump`` flag works without a positional file, and no input at all is
a usage error. Rides the smoke check-3 glob.
"""
from _harness import bind

bind("scripts.calendar_prep", globals())

import contextlib  # selftest-only imports (no shipped surface)
import io
import json
import tempfile

EXIT_SELFTEST = 3  # selftest failure exit (runner convention)

#: Monday 2026-11-16. The morning hold is immovable ([hold] keyword);
#: the other events carry two attendees and no keyword, so they classify
#: as ``other`` and stay busy at every level.
DUMP_A = [
    {"id": "hold-morning", "title": "[hold] prep block",
     "start": "2026-11-16T09:00:00", "end": "2026-11-16T13:00:00"},
    {"id": "sync", "title": "Team sync",
     "start": "2026-11-16T13:00:00", "end": "2026-11-16T14:00:00",
     "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}]},
]

#: B's busy interval sits inside the sync block: the union changes nothing.
DUMP_B_INSIDE = [
    {"id": "budget", "title": "Budget chat",
     "start": "2026-11-16T13:15:00", "end": "2026-11-16T13:45:00",
     "attendees": [{"email": "c@example.com"}, {"email": "d@example.com"}]},
]

#: This dump's busy interval extends past the sync block, so the merged
#: calendar's first free gap starts half an hour later.
DUMP_EXTEND = [
    {"id": "review", "title": "Project review",
     "start": "2026-11-16T13:30:00", "end": "2026-11-16T14:30:00",
     "attendees": [{"email": "e@example.com"}, {"email": "f@example.com"}]},
]


def _pick(argv: list[str]) -> tuple[int, dict]:
    """One CLI invocation of calendar_prep with ``--pick``; stdout captured."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv + ["--pick"])
    return code, json.loads(buffer.getvalue())


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/calendar_prep_multi.py selftest")

    with tempfile.TemporaryDirectory() as directory:
        path_a = Path(directory) / "dump-a.json"
        path_a.write_text(json.dumps(DUMP_A), encoding="utf-8")
        path_b = Path(directory) / "dump-b-inside.json"
        path_b.write_text(json.dumps(DUMP_B_INSIDE), encoding="utf-8")
        path_extend = Path(directory) / "dump-extend.json"
        path_extend.write_text(json.dumps(DUMP_EXTEND), encoding="utf-8")

        code, single = _pick([str(path_a)])
        check("one dump picks cleanly", code == EXIT_OK and single["pick"]["slots"],
              f"code={code}")

        code, merged_inside = _pick([str(path_a), "--dump", str(path_b)])
        check("a contained second dump leaves the slots unchanged (overlap dedup)",
              code == EXIT_OK
              and merged_inside["pick"]["slots"] == single["pick"]["slots"],
              json.dumps(merged_inside["pick"]["slots"]))
        check("the merged run classifies both dumps' events",
              sorted(entry["id"] for entry in merged_inside["classes"]["other"])
              == ["budget", "sync"],
              str(merged_inside["classes"]["other"]))

        code, merged_extend = _pick([str(path_a), "--dump", str(path_extend)])
        first_single = single["pick"]["slots"][0] if single["pick"]["slots"] else {}
        first_extend = merged_extend["pick"]["slots"][0] if merged_extend["pick"]["slots"] else {}
        check("an extending dump pushes the first free slot past the union",
              code == EXIT_OK and first_extend
              and first_extend["start"] > first_single.get("start", ""),
              f"single={first_single} extend={first_extend}")
        check("the extending run still offers the later gap on the same day",
              first_extend.get("date") == first_single.get("date"),
              f"single={first_single} extend={first_extend}")

        code, dump_only = _pick(["--dump", str(path_a)])
        check("--dump works without a positional file",
              code == EXIT_OK and dump_only["pick"]["slots"] == single["pick"]["slots"],
              f"code={code}")

    check("no input at all is a usage error", main([]) == EXIT_USAGE)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
