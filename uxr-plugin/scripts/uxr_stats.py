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

from lib.util import load_config as _load_config  # noqa: E402  (shared plumbing)

JOURNAL_RE = re.compile(r"^work-log-(\d{4}-\d{2}-\d{2})\.jsonl$")
EVENTS_RE = re.compile(r"^events-(\d{4}-\d{2})\.jsonl$")


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


MCP_SURFACE = {
    "description": (
        "uxr_stats.py: read-only journal and analytics rollup. Reads the state "
        "directory from UXR_STATE_DIR or paths.state_dir in the plugin "
        "config; prints the table, or one JSON object with 'json'."),
    "switches": [
        {"name": "json", "flag": "--json", "type": "boolean",
         "help": "print one JSON object"},
        {"name": "days", "flag": "--days", "type": "integer",
         "help": "restrict the journal to the last N days"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "--print-mcp-surface":
        print(json.dumps(MCP_SURFACE))
        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
