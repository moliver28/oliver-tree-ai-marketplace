#!/usr/bin/env python3
"""Data-driven render helpers for the tracker views (W2).

Shapes, columns, ladder, field order, and the emoji map are JSON data under
``prompts/render/``; these loops render from that data so output cannot
drift from the spec. Canonical mine item: ``{key, url, status, type,
priority|null, summary, updated}``. Canonical show item: ``{key, url,
summary, status, type, priority, assignee, reporter, created, updated,
labels, description, issuelinks, comments, fields: {<shorthand>: {kind,
value|values|name|start, end}}}``. Values render by kind (single_select/
single_name value; multi_select comma list; user display name; interval
``start .. end`` or the single date; url ``[url](url)``; text as-is).
``scripts/render_view.py`` is the CLI.
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


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def convert_emoji(text: str) -> str:
    """Replace every mapped ``:name:`` shortcode; an unknown one stays as written."""
    for shortcode, emoji in _spec("show")["emoji"].items():
        text = text.replace(shortcode, emoji)
    return text


def relative_time(iso_ts: str | datetime, now: str | datetime) -> str:
    """``now`` minus ``iso_ts``, rounded down, per prompts/render/relative.json."""
    spec = _spec("relative")
    moment = iso_ts if isinstance(iso_ts, datetime) else _parse_iso(iso_ts)
    reference = now if isinstance(now, datetime) else _parse_iso(now)
    seconds = max(0, int((reference - moment).total_seconds()))
    for step in spec["ladder"]:
        if step["max"] is None or seconds < step["max"]:
            if step["unit"] == "s":
                return step["label"]
            return step["label"].format(n=seconds // spec["divisors"][step["unit"]])
    raise RenderError("relative ladder has no terminal bucket")


def _field_value(field: dict) -> str:
    kind = field.get("kind", "text")
    if kind in ("single_select", "single_name"):
        return str(field.get("value", ""))
    if kind == "multi_select":
        return ", ".join(str(v) for v in field.get("values", []))
    if kind == "user":
        return str(field.get("name", ""))
    if kind == "interval":
        start, end = str(field.get("start", "")), str(field.get("end", ""))
        return start if start == end else f"{start} .. {end}"
    if kind == "url":
        url = str(field.get("value", ""))
        return f"[{url}]({url})"
    return str(field.get("value", ""))


def render_mine(items: list[dict], mode: str = "default", now: str | datetime = "now",
                project_key: str = "") -> str:
    """The one table and one footer line, or the exact one-line empty case."""
    spec = _spec("mine")
    if not items:
        return spec["empty"][mode].format(project_key=project_key)
    lines = ["| " + " | ".join(spec["columns"]) + " |",
             "|" + "---|" * len(spec["columns"])]
    for item in items:
        priority = item.get("priority")
        lines.append("| [{key}]({url}) | {status} | {type} | {pri} | {summary} | {updated} |".format(
            key=item["key"], url=item["url"], status=item.get("status", ""),
            type=item.get("type", ""), pri=priority if priority not in (None, "") else "-",
            summary=item.get("summary", ""), updated=relative_time(item["updated"], now)))
    lines.append(spec["footer"][mode].format(n=len(items)))
    return "\n".join(lines)


def render_show(item: dict, now: str | datetime = "now") -> str:
    """The read-only ticket card: blank-line separated sections, empty blocks
    left out, ``·`` between one line's pieces, at most 5 newest comments,
    no other prose."""
    spec = _spec("show")
    sections: list[str] = [f"## [{item['key']}]({item['url']}) · {item['summary']}"]
    meta = []
    trio = " · ".join(f"**{label}** {value}" for label, value in (
        ("Status", item.get("status")), ("Type", item.get("type")),
        ("Priority", item.get("priority"))) if value)
    if trio:
        meta.append(trio)
    pair = " · ".join(f"**{label}** {value}" for label, value in (
        ("Assignee", item.get("assignee")), ("Reporter", item.get("reporter"))) if value)
    if pair:
        meta.append(pair)
    times = " · ".join(f"**{label}** {relative_time(item[key], now)}"
                       for label, key in (("Updated", "updated"), ("Created", "created"))
                       if item.get(key))
    if times:
        meta.append(times)
    if item.get("labels"):
        meta.append("**Labels** " + ", ".join(str(v) for v in item["labels"]))
    if meta:
        sections.append("\n".join(meta))
    rows = []
    for shorthand, row_label in spec["field_rows"]:
        field = (item.get("fields") or {}).get(shorthand)
        if field is not None and _field_value(field).strip():
            rows.append(f"| {row_label} | {_field_value(field)} |")
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
                  f"{str(comment['body']).rstrip()}"
                  for comment in comments[: spec["max_comments"]]]
        sections.append(f"### Comments ({len(comments)})\n\n" + "\n\n".join(blocks))
    return convert_emoji("\n\n".join(sections))


def _selftest() -> int:
    """Byte-compare every tests/fixtures/render case against its expected.txt."""
    import sys
    cases = sorted((PLUGIN_ROOT / "tests" / "fixtures" / "render").glob("*.json"))
    print("lib/render.py selftest")
    failures: list[str] = []
    if not cases:
        failures.append("no fixtures under tests/fixtures/render")
    for case_path in cases:
        expected = case_path.with_suffix(".expected.txt")
        if not expected.is_file():
            failures.append(f"{case_path.name}: no expected.txt")
            continue
        data = json.loads(case_path.read_text(encoding="utf-8"))
        if case_path.name.startswith("mine"):
            got = render_mine(data.get("items") or [], data.get("mode") or "default",
                              data.get("now") or "now", data.get("project_key") or "")
        else:
            got = render_show(data["item"], data.get("now") or "now")
        if got + "\n" != expected.read_text(encoding="utf-8"):
            failures.append(f"{case_path.stem}: differs from expected.txt")
        else:
            print(f"  [ok] {case_path.stem}")
    now = "2026-11-17T21:54:24Z"
    for label, ts, want in (("just now", "2026-11-17T21:54:00Z", "just now"),
                            ("12h", "2026-11-17T09:54:00Z", "12h ago"),
                            ("7d", "2026-11-10T21:30:00Z", "7d ago"),
                            ("1w", "2026-11-08T21:54:00Z", "1w ago"),
                            ("1mo", "2026-10-17T21:00:00Z", "1mo ago")):
        if relative_time(ts, now) != want:
            failures.append(f"ladder {label}: {relative_time(ts, now)} != {want}")
    if convert_emoji("look :eyes:") != "look \U0001f440" or convert_emoji(":nope:") != ":nope:":
        failures.append("emoji conversion")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
