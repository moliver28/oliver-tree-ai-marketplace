#!/usr/bin/env python3
"""Data-driven render helpers for the tracker views (W2 efficiency pass).

The table shapes, the relative-time ladder, the show-card field order, and
the emoji map live as JSON data under ``prompts/render/``; the loops here
render from that data so the output cannot drift from the spec. Byte-exact
targets: the ``mine`` table and footer, the ``show`` card, and the relative
ladder ("just now", then ``<N>m|h|d|w|mo|y ago``, rounded down).

Canonical input JSON (commands assemble it mechanically from the tracker
read; this library renders it):

- mine item: ``{key, url, status, type, priority|null, summary, updated}``
- show item: ``{key, url, summary, status, type, priority, assignee,
  reporter, created, updated, labels, description, issuelinks: [{type, key,
  url, summary, status}], comments: [{author, created, body}],
  fields: {<shorthand>: {kind, value|start, end|name}}}``

Field value rendering by kind: ``single_select``/``single_name`` the value;
``multi_select`` a comma-separated list; ``user`` the display name;
``interval`` ``start .. end`` (or the single date when equal); ``date``
``YYYY-MM-DD``; ``url`` ``[url](url)``; ``text``/``labels`` as-is.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RENDER_DIR = PLUGIN_ROOT / "prompts" / "render"


class RenderError(Exception):
    """A render spec or its input is malformed."""


def _spec(name: str) -> dict:
    return json.loads((RENDER_DIR / f"{name}.json").read_text(encoding="utf-8"))


def convert_emoji(text: str) -> str:
    """Replace every mapped ``:name:`` shortcode with its unicode emoji;
    a shortcode the map does not know stays as written."""
    for shortcode, emoji in _spec("show")["emoji"].items():
        text = text.replace(shortcode, emoji)
    return text


def relative_time(iso_ts: str, now: str | datetime) -> str:
    """Relative time from ``now`` minus ``iso_ts``, rounded down, per the
    ``prompts/render/relative.json`` ladder."""
    ladder = _spec("relative")
    moment = iso_ts if isinstance(iso_ts, datetime) else _parse_iso(iso_ts)
    reference = now if isinstance(now, datetime) else _parse_iso(now)
    seconds = max(0, int((reference - moment).total_seconds()))
    for step in ladder["ladder"]:
        if step["max"] is None or seconds < step["max"]:
            if step["unit"] == "s":
                return step["label"]
            n = seconds // ladder["divisors"][step["unit"]]
            return step["label"].format(n=n)
    raise RenderError("relative ladder has no terminal bucket")


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def render_mine(items: list[dict], mode: str = "default", now: str | datetime = "now",
                project_key: str = "") -> str:
    """The one table and one footer line, or the exact one-line empty case."""
    spec = _spec("mine")
    if not items:
        return spec["empty"][mode].format(project_key=project_key)
    if mode not in spec["footer"]:
        raise RenderError(f"mine mode {mode!r} has no footer spec")
    lines = ["| " + " | ".join(spec["columns"]) + " |",
             "|" + "---|" * len(spec["columns"])]
    for item in items:
        priority = item.get("priority")
        lines.append("| [{key}]({url}) | {status} | {type} | {pri} | {summary} | {updated} |".format(
            key=item["key"], url=item["url"], status=item.get("status", ""),
            type=item.get("type", ""), pri=priority if priority not in (None, "") else "-",
            summary=item.get("summary", ""),
            updated=relative_time(item["updated"], now)))
    lines.append(spec["footer"][mode].format(n=len(items)))
    return "\n".join(lines)


def _field_value(field: dict) -> str:
    kind = field.get("kind", "text")
    if kind in ("single_select", "single_name"):
        return str(field.get("value", ""))
    if kind == "multi_select":
        return ", ".join(str(v) for v in field.get("values", []))
    if kind == "user":
        return str(field.get("name", ""))
    if kind == "interval":
        start, end = field.get("start", ""), field.get("end", "")
        return start if start == end else f"{start} .. {end}"
    if kind == "url":
        url = str(field.get("value", ""))
        return f"[{url}]({url})"
    return str(field.get("value", ""))


def render_show(item: dict, now: str | datetime = "now") -> str:
    """The read-only ticket card. Empty blocks are left out; ``·`` separates
    one line's pieces; sections are blank-line separated; no other prose."""
    spec = _spec("show")
    sections: list[str] = [f"## [{item['key']}]({item['url']}) · {item['summary']}"]
    meta: list[str] = []
    status_line = " · ".join(
        f"**{label}** {value}" for label, value in (
            ("Status", item.get("status")), ("Type", item.get("type")),
            ("Priority", item.get("priority"))) if value)
    if status_line:
        meta.append(status_line)
    people = " · ".join(f"**{label}** {value}" for label, value in (
        ("Assignee", item.get("assignee")), ("Reporter", item.get("reporter"))) if value)
    if people:
        meta.append(people)
    times = " · ".join(f"**{label}** {relative_time(item[key], now)}"
                       for label, key in (("Updated", "updated"), ("Created", "created"))
                       if item.get(key))
    if times:
        meta.append(times)
    labels = item.get("labels") or []
    if labels:
        meta.append("**Labels** " + ", ".join(str(v) for v in labels))
    if meta:
        sections.append("\n".join(meta))
    rows = []
    for shorthand, row_label in spec["field_rows"]:
        field = (item.get("fields") or {}).get(shorthand)
        if field is None:
            continue
        rendered = _field_value(field)
        if rendered.strip():
            rows.append(f"| {row_label} | {rendered} |")
    if rows:
        sections.append("### UXR fields\n\n| Field | Value |\n|---|---|\n" + "\n".join(rows))
    description = (item.get("description") or "").strip("\n")
    if description.strip():
        sections.append("### Description\n\n" + description.rstrip())
    links = item.get("issuelinks") or []
    if links:
        lines = [f"**{link['type']}** [{link['key']}]({link['url']}) · "
                 f"{link.get('summary', '')} · {link.get('status', '')}".rstrip(" ·")
                 for link in links]
        sections.append(f"### Linked issues ({len(links)})\n\n" + "\n".join(lines))
    comments = item.get("comments") or []
    if comments:
        blocks = [f"**{comment['author']} · {relative_time(comment['created'], now)}**\n"
                  .rstrip("\n") + "\n" + str(comment["body"]).rstrip()
                  for comment in comments[: spec["max_comments"]]]
        sections.append(f"### Comments ({len(comments)})\n\n" + "\n\n".join(blocks))
    return convert_emoji("\n\n".join(sections))


def _selftest() -> int:
    print("lib/render.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    check("ladder just now", relative_time("2026-11-17T21:54:00Z", "2026-11-17T21:54:24Z") == "just now")
    check("ladder 12h", relative_time("2026-11-17T09:54:00Z", "2026-11-17T21:54:24Z") == "12h ago")
    check("ladder 2d", relative_time("2026-11-15T20:00:00Z", "2026-11-17T21:54:24Z") == "2d ago")
    check("ladder 7d", relative_time("2026-11-10T21:30:00Z", "2026-11-17T21:54:24Z") == "7d ago")
    check("ladder 1w", relative_time("2026-11-08T21:54:00Z", "2026-11-17T21:54:24Z") == "1w ago")
    check("ladder 1mo", relative_time("2026-10-17T21:00:00Z", "2026-11-17T21:54:24Z") == "1mo ago")
    check("ladder 1y", relative_time("2025-11-17T21:00:00Z", "2026-11-17T21:54:24Z") == "1y ago")
    check("emoji known", convert_emoji("look :eyes: now") == "look \U0001f440 now")
    check("emoji unknown stays", convert_emoji(":nope:") == ":nope:")
    check("priority dash", "- " in render_mine(
        [{"key": "A-1", "url": "u", "status": "x", "type": "y", "priority": None,
          "summary": "s", "updated": "2026-11-17T21:54:00Z"}], now="2026-11-17T21:54:24Z"))
    check("multi_select", _field_value({"kind": "multi_select", "values": ["a", "b"]}) == "a, b")
    check("interval same day", _field_value({"kind": "interval", "start": "2026-11-17", "end": "2026-11-17"}) == "2026-11-17")
    check("url link", _field_value({"kind": "url", "value": "https://x.example"}) == "[https://x.example](https://x.example)")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
