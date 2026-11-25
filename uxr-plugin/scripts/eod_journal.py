#!/usr/bin/env python3
"""Deterministic journal work for the eod command (W2): the filter, the
draft cap check, the ``--auto`` facts template, and the ``processed``
rewrite were inline heredocs; they are one script now. The command owns
tracker calls and gates. ``filter`` prints the group JSON; ``check``
prints ``<words> <True|False>``; ``draft-auto`` prints the draft;
``rewrite`` is silent. Subcommands: ``filter --state <dir> --days
<D1,D2|A..B> [--ticket <KEY>]`` / ``check --file <draft> --footer <text>``
/ ``draft-auto --state ... --ticket <KEY> --date <D> [--footer]`` /
``rewrite --state ... --posted <K1,K2> --readonly <sid,sid>``. Exit: 0 ok, 2 usage.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date as _date, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
def _day_list(spec: str, today: _date | None = None) -> list[str]:
    text = str(spec or "").strip()
    if ".." in text:
        start, end = (_date.fromisoformat(part) for part in text.split("..", 1))
        return [(start + timedelta(days=offset)).isoformat()
                for offset in range((end - start).days + 1)]
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
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))
    from lib.util import file_lock  # noqa: E402  (moved from hooks/provenance)
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
    sub = args[0] if args else ""
    days = _day_list(_value_of(args, "--days"))
    state = Path(_value_of(args, "--state")).expanduser() if _value_of(args, "--state") else None
    if state is None and sub in ("filter", "draft-auto", "rewrite"):
        print(f"eod_journal: {sub} needs --state <dir>", file=sys.stderr)
        return 2

    def csv_set(value: str) -> set[str]:
        return {part.strip() for part in value.split(",") if part.strip()}

    if sub == "filter":
        print(json.dumps(filter_rows(_read_rows(state, days, _value_of(args, "--ticket"))), indent=2))
        return 0
    if sub == "check":
        print(check_draft(Path(_value_of(args, "--file")).expanduser().read_text(encoding="utf-8"),
                          _value_of(args, "--footer")))
        return 0
    if sub == "draft-auto":
        ticket = _value_of(args, "--ticket")
        rows = _read_rows(state, days, ticket)
        if not rows:
            print(f"No unposted UX research work for {days[-1] if days else ''}.")
            return 0
        print(draft_auto(rows, ticket, _value_of(args, "--date") or (days[-1] if days else ""),
                         _value_of(args, "--footer")))
        return 0
    if sub == "rewrite":
        rewrite_journal(state, days, csv_set(_value_of(args, "--posted")),
                        csv_set(_value_of(args, "--readonly")))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
