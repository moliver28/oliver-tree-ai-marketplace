#!/usr/bin/env python3
"""Deterministic journal work for the eod command (W2 efficiency pass).

The journal filter, the draft word-cap check, the ``--auto`` facts-only
template, and the ``processed`` rewrite used to live as inline heredocs in
the command prompt; they are one script now. The command owns every
tracker call and the gate; this script only computes. Exit codes: 0 ok,
2 usage, 3 selftest failed. ``filter`` prints the group JSON verbatim;
``check`` prints ``<words> <True|False>``; ``draft-auto`` prints the draft;
``rewrite`` is silent on success.

Subcommands::

    filter  --state <dir> --days <D1,D2 | A..B> [--ticket <KEY>]
    check   --file <draft> --footer <footer text>
    draft-auto --state <dir> --days <...> --ticket <KEY> --date <YYYY-MM-DD> [--footer <text>]
    rewrite --state <dir> --days <...> --posted <KEY1,KEY2> --readonly <sid1,sid2>
    selftest
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date as _date, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures" / "eod"


def _day_list(spec: str, today: _date | None = None) -> list[str]:
    text = str(spec or "").strip()
    if ".." in text:
        start_text, end_text = text.split("..", 1)
        start = _date.fromisoformat(start_text)
        end = _date.fromisoformat(end_text)
        days = []
        cursor = start
        while cursor <= end:
            days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        return days
    if not text:
        return [(today or _date.today()).isoformat()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _read_rows(state: Path, days: list[str], ticket: str = "") -> list[dict]:
    rows: list[dict] = []
    for day in days:
        path = state / ("work-log-%s.jsonl" % day)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue  # malformed lines stay as they are
            if not isinstance(row, dict) or row.get("processed"):
                continue
            if ticket and ticket not in (row.get("ticket_keys") or []):
                continue
            rows.append(row)
    return rows


def filter_rows(rows: list[dict]) -> dict:
    """Group unprocessed rows: active per ticket, read-only buckets, and
    sessions with no ticket key that still ran inside a research dir."""
    active: dict[str, list[dict]] = {}
    readonly: list[dict] = []
    unlinked: list[dict] = []
    for row in rows:
        keys = row.get("ticket_keys") or []
        if not keys and row.get("in_research_dir"):
            unlinked.append(row)
            continue
        for key in keys:
            active.setdefault(key, []).append(row)
    for key in list(active):
        bucket = active[key]
        if all(not row.get("files_edited_count") and not row.get("tracker_tool_calls")
               for row in bucket):
            readonly.extend(bucket)
            del active[key]
    return {"active": {key: len(bucket) for key, bucket in active.items()},
            "readonly_sessions": [row.get("session_id") for row in readonly],
            "unlinked_sessions": [row.get("session_id") for row in unlinked]}


def check_draft(text: str, footer: str) -> str:
    """The mechanical cap check: ``<word count> <True|False>`` where True
    means the draft ends with the footer (one blank line before it)."""
    return f"{len(text.split())} {text.rstrip().endswith(footer.strip())}"


def draft_auto(rows: list[dict], ticket: str, day: str, footer: str = "") -> str:
    """The --auto facts-only template: one short sentence per fact group,
    no narrative. Anything the journal does not show is left out."""
    commands = sorted({c for row in rows for c in (row.get("commands_used") or [])})
    files = sum(int(row.get("files_edited_count") or 0) for row in rows)
    calls = sum(int(row.get("tracker_tool_calls") or 0) for row in rows)
    sessions = len(rows)
    facts: list[str] = []
    if commands:
        facts.append("commands: " + ", ".join(commands))
    if files:
        facts.append(f"{files} file edit(s)")
    if calls:
        facts.append(f"{calls} tracker call(s)")
    body = f"{ticket}: {sessions} session(s)" + ("" if not facts else "; " + "; ".join(facts)) + "."
    lines = [f"[ux-eod {day}]", "", body]
    if footer.strip():
        lines.extend(["", footer.strip()])
    return "\n".join(lines)


def rewrite_journal(state: Path, days: list[str], posted: set[str], readonly: set[str]) -> int:
    """Flip ``processed`` for every posted ticket's rows and every skipped
    read-only session, atomically, under the provenance file lock."""
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    from provenance import file_lock  # noqa: E402
    changed = 0
    for day in days:
        path = state / ("work-log-%s.jsonl" % day)
        if not path.is_file():
            continue
        with file_lock(path.with_name(path.name + ".lock")):
            out = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except ValueError:
                    out.append(stripped)
                    continue
                if (isinstance(row, dict) and not row.get("processed")
                        and (set(row.get("ticket_keys") or []) & posted
                             or row.get("session_id") in readonly)):
                    row["processed"] = True
                    changed += 1
                out.append(json.dumps(row, ensure_ascii=False) if isinstance(row, dict) else stripped)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(out) + "\n")
            os.replace(tmp, path)
    return changed


def _value_of(args: list[str], name: str) -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    sub = args[0] if args else ""
    days = _day_list(_value_of(args, "--days"))
    state = Path(_value_of(args, "--state")).expanduser() if _value_of(args, "--state") else None
    if sub == "filter":
        if state is None:
            print("eod_journal: filter needs --state <dir>", file=sys.stderr)
            return 2
        print(json.dumps(filter_rows(_read_rows(state, days, _value_of(args, "--ticket"))), indent=2))
        return 0
    if sub == "check":
        draft = Path(_value_of(args, "--file")).expanduser()
        text = draft.read_text(encoding="utf-8")
        print(check_draft(text, _value_of(args, "--footer")))
        return 0
    if sub == "draft-auto":
        if state is None:
            print("eod_journal: draft-auto needs --state <dir>", file=sys.stderr)
            return 2
        ticket = _value_of(args, "--ticket")
        rows = _read_rows(state, days, ticket)
        if not rows:
            print(f"No unposted UX research work for {days[-1] if days else ''}.")
            return 0
        print(draft_auto(rows, ticket, _value_of(args, "--date") or (days[-1] if days else ""),
                         _value_of(args, "--footer")))
        return 0
    if sub == "rewrite":
        if state is None:
            print("eod_journal: rewrite needs --state <dir>", file=sys.stderr)
            return 2
        posted = {part.strip() for part in _value_of(args, "--posted").split(",") if part.strip()}
        readonly = {part.strip() for part in _value_of(args, "--readonly").split(",") if part.strip()}
        rewrite_journal(state, days, posted, readonly)
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


def _selftest() -> int:
    print("scripts/eod_journal.py selftest")
    import tempfile
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    footer = "_Posted by Claude Code on behalf of Jordan Reyes._"
    check("check: word count and footer",
          check_draft("[ux-eod 2026-11-17]\n\nOne session today.\n\n" + footer, footer) == "14 True")
    check("check: missing footer is False",
          check_draft("[ux-eod 2026-11-17]\n\nNo footer yet.", footer) == "5 False")

    golden = FIXTURES / "journal-2026-11-17.jsonl"
    if golden.is_file():
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            (state / "work-log-2026-11-17.jsonl").write_text(
                golden.read_text(encoding="utf-8"), encoding="utf-8")
            rows = _read_rows(state, ["2026-11-17"])
            grouped = filter_rows(rows)
            check("filter: matches the baseline grouping",
                  grouped == {"active": {"UXR-101": 1}, "readonly_sessions": ["ro-1"],
                              "unlinked_sessions": ["ul-1"]}, json.dumps(grouped))
            draft = draft_auto([row for row in rows if "UXR-101" in (row.get("ticket_keys") or [])],
                               "UXR-101", "2026-11-17", footer)
            check("draft-auto: first line is the heading", draft.startswith("[ux-eod 2026-11-17]"))
            check("draft-auto: facts only, capped, footered",
                  draft.splitlines()[2].startswith("UXR-101: 1 session(s)")
                  and len(draft.split()) < 300 and draft.rstrip().endswith(footer), draft)
            empty = filter_rows([])
            check("filter: empty input", empty == {"active": {}, "readonly_sessions": [],
                                                   "unlinked_sessions": []})
            changed = rewrite_journal(state, ["2026-11-17"], {"UXR-101"}, {"ro-1"})
            after = {row["session_id"]: bool(row.get("processed")) for row in
                     (json.loads(line) for line in
                      (state / "work-log-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())}
            check("rewrite: flips posted and readonly, leaves unlinked unprocessed",
                  changed == 2 and after.get("baseline-uc8-session") is True
                  and after.get("ro-1") is True and after.get("ul-1") is False,
                  json.dumps(after))
    else:
        check("journal fixture", False, "tests/fixtures/eod/journal fixture missing")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
