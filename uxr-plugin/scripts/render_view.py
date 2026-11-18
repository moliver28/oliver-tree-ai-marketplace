#!/usr/bin/env python3
"""Render the tracker views from canonical JSON (issue: W2 efficiency pass).

``mine`` prints the one table and one footer line (or the exact empty
line); ``show`` prints the read-only ticket card. Shapes, column order,
the relative-time ladder, and the emoji map come from ``prompts/render/``
through ``lib/render.py``; this script adds no prose of its own.

Usage::

    python scripts/render_view.py mine <items.json> [--all]
        [--now <ISO8601>] [--project-key <KEY>]
    python scripts/render_view.py show <item.json> [--now <ISO8601>]
    python scripts/render_view.py selftest

``mine`` input: ``{"items": [{key, url, status, type, priority|null,
summary, updated}], "now": ..., "mode": ..., "project_key": ...}`` (flags
override the file's fields). ``show`` input: ``{"now": ..., "item": {...}}``
with the canonical item shape documented in ``lib/render.py``. Exit codes:
0 ok, 2 usage, 3 selftest failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import render  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures" / "render"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if len(args) < 2 or args[0] not in ("mine", "show"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    view, path = args[0], Path(args[1])
    flags = args[2:]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"render_view: unreadable input: {exc}", file=sys.stderr)
        return 2

    def flag_value(name: str) -> str | None:
        return flags[flags.index(name) + 1] if name in flags and flags.index(name) + 1 < len(flags) else None

    try:
        if view == "mine":
            print(render.render_mine(
                data.get("items") or [],
                "all" if "--all" in flags else flag_value("--mode") or data.get("mode") or "default",
                flag_value("--now") or data.get("now") or "now",
                flag_value("--project-key") or data.get("project_key") or ""))
        else:
            print(render.render_show(data["item"], flag_value("--now") or data.get("now") or "now"))
        return 0
    except (render.RenderError, KeyError) as exc:
        print(f"render_view: {exc}", file=sys.stderr)
        return 2


def _selftest() -> int:
    print("scripts/render_view.py selftest")
    failures: list[str] = []
    cases = sorted(FIXTURES.glob("*.json"))
    if not cases:
        failures.append("no fixtures under tests/fixtures/render")
    for case_path in cases:
        expected = case_path.with_suffix(".expected.txt")
        if not expected.is_file():
            failures.append(f"{case_path.name}: no expected.txt")
            continue
        data = json.loads(case_path.read_text(encoding="utf-8"))
        if case_path.name.startswith("mine"):
            got = render.render_mine(data.get("items") or [], data.get("mode") or "default",
                                     data.get("now") or "now", data.get("project_key") or "")
        else:
            got = render.render_show(data["item"], data.get("now") or "now")
        if got + "\n" == expected.read_text(encoding="utf-8"):
            print(f"  [ok] {case_path.stem}")
        else:
            failures.append(f"{case_path.stem}: rendered output differs from expected.txt")
    return _finish(failures)


def _finish(failures: list[str]) -> int:
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
