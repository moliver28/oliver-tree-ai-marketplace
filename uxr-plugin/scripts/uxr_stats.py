#!/usr/bin/env python3
"""Adoption rollup: journal stats and analytics counts, never joined.

``stats [--json] [--days=N]`` runs this and prints the output verbatim.

Journal rollup (``<state_dir>/work-log-YYYY-MM-DD.jsonl``): rows are
deduped by ``session_id`` keeping the latest ``ended_at``, then the
script reports ``distinct_sessions``, ``command_adoption`` (a command ->
distinct-session count), ``files_edited_total``,
``tracker_tool_calls_total``, and ``unprocessed_count``.

Analytics rollup (``<state_dir>/events-YYYY-MM.jsonl``):
``total_events``, ``event_type_counts``, and ``tool_failed_by_kind``.
The analytics ids are salted hashes; the two data sets are never joined.

``--days=N`` keeps only journal files dated within the last N days and
event months overlapping that window. ``--json`` prints one JSON object
with the two rollups under separate keys. A malformed line is skipped
silently; exit codes: 0 ok, 2 usage or state-dir error.

Usage::

    python scripts/uxr_stats.py
    python scripts/uxr_stats.py --days=7 --json
    python scripts/uxr_stats.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

JOURNAL_RE = re.compile(r"^work-log-(\d{4}-\d{2}-\d{2})\.jsonl$")
EVENTS_RE = re.compile(r"^events-(\d{4}-\d{2})\.jsonl$")


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def resolve_state_dir(config: dict | None, environ=None) -> Path | None:
    """UXR_STATE_DIR wins, then ``paths.state_dir``; an unexpanded placeholder is None."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get("UXR_STATE_DIR") or "").strip()
    if not raw and isinstance(config, dict):
        paths = config.get("paths", {})
        if isinstance(paths, dict):
            raw = str(paths.get("state_dir") or "").strip()
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if "${" in expanded:
        return None
    return Path(expanded)


def rollup_journal(state_dir: Path, today: date, days: int | None) -> dict:
    """Deduped journal counts; malformed lines are skipped."""
    rows: dict[str, dict] = {}
    for path in sorted(state_dir.glob("work-log-*.jsonl")):
        match = JOURNAL_RE.match(path.name)
        if not match:
            continue
        file_date = _parse_date(match.group(1))
        if days is not None and file_date is not None \
                and file_date < today - timedelta(days=days - 1):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except ValueError:
                continue
            if not isinstance(row, dict) or not row.get("session_id"):
                continue
            session_id = str(row["session_id"])
            prior = rows.get(session_id)
            if prior is None or str(row.get("ended_at") or "") >= str(prior.get("ended_at") or ""):
                rows[session_id] = row
    adoption: dict[str, int] = {}
    for row in rows.values():
        for command in row.get("commands_used") or []:
            name = str(command)
            adoption[name] = adoption.get(name, 0) + 1
    return {
        "distinct_sessions": len(rows),
        "command_adoption": dict(sorted(adoption.items())),
        "files_edited_total": sum(int(row.get("files_edited_count") or 0)
                                  for row in rows.values()),
        "tracker_tool_calls_total": sum(int(row.get("tracker_tool_calls") or 0)
                                        for row in rows.values()),
        "unprocessed_count": sum(1 for row in rows.values() if not row.get("processed")),
    }


def rollup_analytics(state_dir: Path, today: date, days: int | None) -> dict:
    """Consent-gated usage counts; malformed lines are skipped."""
    total = 0
    types: dict[str, int] = {}
    failures: dict[str, int] = {}
    cutoff = None if days is None else (today - timedelta(days=days - 1)).strftime("%Y-%m")
    for path in sorted(state_dir.glob("events-*.jsonl")):
        match = EVENTS_RE.match(path.name)
        if not match or (cutoff and match.group(1) < cutoff):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except ValueError:
                continue
            if not isinstance(event, dict) or not event.get("event"):
                continue
            total += 1
            kind = str(event["event"])
            types[kind] = types.get(kind, 0) + 1
            if kind == "tool_failed":
                failure = str(event.get("kind") or "unknown")
                failures[failure] = failures.get(failure, 0) + 1
    return {
        "total_events": total,
        "event_type_counts": dict(sorted(types.items())),
        "tool_failed_by_kind": dict(sorted(failures.items())),
    }


def _parse_date(text: str):
    try:
        parts = [int(part) for part in text.split("-")]
        return date(*parts)
    except (ValueError, TypeError):
        return None


def render(rollup: dict, days: int | None) -> str:
    """The human view; the command prints this verbatim."""
    window = "last %d day(s)" % days if days else "all recorded days"
    out = ["UXR stats (%s)" % window, ""]
    out.append("Journal (deduped by session_id, latest ended_at kept)")
    out.append("  distinct_sessions: %d" % rollup["journal"]["distinct_sessions"])
    out.append("  command_adoption:")
    adoption = rollup["journal"]["command_adoption"]
    if adoption:
        for command, count in adoption.items():
            out.append("    %s: %d" % (command, count))
    else:
        out.append("    (none)")
    out.append("  files_edited_total: %d" % rollup["journal"]["files_edited_total"])
    out.append("  tracker_tool_calls_total: %d"
               % rollup["journal"]["tracker_tool_calls_total"])
    out.append("  unprocessed_count: %d" % rollup["journal"]["unprocessed_count"])
    out.append("")
    out.append("Analytics (consent-gated usage counts; never joined with the journal)")
    out.append("  total_events: %d" % rollup["analytics"]["total_events"])
    out.append("  event_type_counts:")
    types = rollup["analytics"]["event_type_counts"]
    if types:
        for kind, count in types.items():
            out.append("    %s: %d" % (kind, count))
    else:
        out.append("    (none)")
    out.append("  tool_failed_by_kind:")
    failed = rollup["analytics"]["tool_failed_by_kind"]
    if failed:
        for kind, count in failed.items():
            out.append("    %s: %d" % (kind, count))
    else:
        out.append("    (none)")
    return "\n".join(out)


def run(state_dir: Path, days: int | None, as_json: bool,
        today: date | None = None, environ=None) -> tuple[int, str]:
    """Compute both rollups and render; returns (exit_code, stdout)."""
    today = today or date.today()
    if state_dir is None or not state_dir.is_dir():
        return 2, ""
    rollup = {
        "journal": rollup_journal(state_dir, today, days),
        "analytics": rollup_analytics(state_dir, today, days),
        "days": days,
    }
    if as_json:
        return 0, json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True)
    return 0, render(rollup, days)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in raw or "--selftest" in raw:
        return _selftest()
    parser = argparse.ArgumentParser(
        prog="uxr_stats.py", description="Journal and analytics rollup (read-only).")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--days", type=int, default=None, metavar="N",
                        help="restrict the journal to the last N days")
    args = parser.parse_args(raw)
    if args.days is not None and args.days < 1:
        parser.error("--days must be a positive number")
    config = _load_config()
    state_dir = resolve_state_dir(config)
    if state_dir is None or not state_dir.is_dir():
        print("stats: no usable state directory (set paths.state_dir in "
              "config/org.yaml or UXR_STATE_DIR); nothing to report yet",
              file=sys.stderr)
        return 2
    code, output = run(state_dir, args.days, args.json)
    if output:
        print(output)
    return code


def _selftest() -> int:
    """Cover the acceptance items: ``--json`` is valid JSON and duplicate
    rows count once, plus the --days window and the never-joined rule."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("scripts/uxr_stats.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        state = tmp / "state"
        state.mkdir()
        journal = state / "work-log-2026-11-08.jsonl"
        rows = [
            # Duplicate session: same id, older and newer ended_at.
            {"session_id": "s1", "ended_at": "2026-11-08T09:00:00-05:00",
             "commands_used": ["/uxr-new"], "files_edited_count": 2,
             "tracker_tool_calls": 1, "processed": False},
            {"session_id": "s1", "ended_at": "2026-11-08T17:00:00-05:00",
             "commands_used": ["/uxr-new", "/uxr-eod"], "files_edited_count": 3,
             "tracker_tool_calls": 2, "processed": False},
            {"session_id": "s2", "ended_at": "2026-11-08T10:00:00-05:00",
             "commands_used": ["/uxr-eod"], "files_edited_count": 0,
             "tracker_tool_calls": 0, "processed": True},
            {"session_id": "s3", "ended_at": "2026-11-08T11:00:00-05:00",
             "commands_used": [], "files_edited_count": 1,
             "tracker_tool_calls": 0, "processed": True},
        ]
        journal.write_text("".join(json.dumps(r) + "\n" for r in rows)
                           + "not json at all\n", encoding="utf-8")
        old = state / "work-log-2026-10-01.jsonl"
        old.write_text(json.dumps(
            {"session_id": "s9", "ended_at": "2026-10-01T09:00:00-05:00",
             "commands_used": ["/uxr-new"], "files_edited_count": 4,
             "tracker_tool_calls": 3, "processed": False}) + "\n", encoding="utf-8")
        events = state / "events-2026-11.jsonl"
        lines = []
        for index in range(4):
            lines.append({"v": 1, "event": "command_invoked"})
        for index in range(2):
            lines.append({"v": 1, "event": "tool_failed", "kind": "tool_error"})
        lines.append({"v": 1, "event": "tool_failed", "kind": "user_rejection"})
        lines.append({"v": 1, "event": "agent_dispatched"})
        lines.append("broken line")
        events.write_text("".join(
            (line if isinstance(line, str) else json.dumps(line)) + "\n"
            for line in lines), encoding="utf-8")
        old_events = state / "events-2026-01.jsonl"
        old_events.write_text(json.dumps({"v": 1, "event": "command_invoked"}) + "\n",
                              encoding="utf-8")
        today = date(2026, 11, 9)

        code, out = run(state, None, False, today=today)
        check("all files roll up without --days",
              code == 0 and "distinct_sessions: 4" in out, repr(out[:80]))
        check("duplicate rows count once (latest ended_at kept)",
              "distinct_sessions: 4" in out and "files_edited_total: 8" in out
              and "tracker_tool_calls_total: 5" in out, repr(out))
        check("command adoption counts distinct sessions per command",
              "/uxr-eod: 2" in out and "/uxr-new: 2" in out, repr(out))
        check("the unprocessed count uses the kept rows",
              "unprocessed_count: 2" in out, repr(out))

        code, out = run(state, 7, False, today=today)
        check("--days excludes the old journal month",
              code == 0 and "distinct_sessions: 3" in out, repr(out))
        check("--days keeps only overlapping event months",
              "total_events: 8" in out, repr(out))

        code, out = run(state, None, True, today=today)
        try:
            payload = json.loads(out)
            valid = True
        except ValueError:
            payload, valid = {}, False
        check("--json is valid JSON", code == 0 and valid, repr(out[:60]))
        check("the two rollups stay separate (never joined)",
              set(payload.get("journal", {}).get("command_adoption", {}).keys()).isdisjoint(
                  set(payload.get("analytics", {}).get("event_type_counts", {}).keys())),
              repr(payload))
        check("the json payload carries the contract keys",
              payload.get("journal", {}).get("distinct_sessions") == 4
              and payload.get("analytics", {}).get("total_events") == 9
              and payload.get("analytics", {}).get("tool_failed_by_kind", {})
              .get("tool_error") == 2
              and payload.get("analytics", {}).get("tool_failed_by_kind", {})
              .get("user_rejection") == 1,
              repr(payload.get("analytics")))

        check("malformed lines are skipped silently",
              payload.get("analytics", {}).get("total_events") == 9,
              repr(payload.get("analytics", {}).get("total_events")))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
