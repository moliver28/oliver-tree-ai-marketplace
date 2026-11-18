#!/usr/bin/env python3
"""Render tracker views from canonical JSON (W2): the shapes come from
``prompts/render/`` via ``lib/render.py``; this CLI adds no prose. Usage:
``mine <items.json> [--all] [--now <ISO>] [--project-key <KEY>]`` |
``show <item.json> [--now <ISO>]`` | ``selftest``. Exit: 0 ok, 2 usage,
3 selftest failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import render  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return render._selftest()
    if len(args) < 2 or args[0] not in ("mine", "show"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    view, path, flags = args[0], Path(args[1]), args[2:]

    def flag(name: str) -> str | None:
        return flags[flags.index(name) + 1] if name in flags and flags.index(name) + 1 < len(flags) else None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if view == "mine":
            print(render.render_mine(
                data.get("items") or [],
                "all" if "--all" in flags else flag("--mode") or data.get("mode") or "default",
                flag("--now") or data.get("now") or "now",
                flag("--project-key") or data.get("project_key") or ""))
        else:
            print(render.render_show(data["item"], flag("--now") or data.get("now") or "now"))
        return 0
    except (render.RenderError, KeyError, OSError, ValueError) as exc:
        print(f"render_view: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
