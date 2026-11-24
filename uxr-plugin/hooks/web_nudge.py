#!/usr/bin/env python3
"""Web-tool nudge hook (grounding law, design decision 7 / build item 12).

Fires on PreToolUse for the web search/fetch tools. When the session's
working directory sits inside a uxr workspace (the same ``_gate_open``
predicate ``ux_research_context.py`` uses, workspace granularity), it
prints one PreToolUse ``additionalContext`` JSON object carrying the
nudge line: registered source first; cite the URL with the claim.
Outside a uxr workspace, or on any other event or tool, it prints
nothing.

Hook contract (all hooks in this plugin):

1. Read the event JSON from stdin.
2. Catch every exception. Exit 0 on any error.
3. Print nothing unless the event contract asks for output.

Usage::

    python hooks/web_nudge.py   (event JSON on stdin)

Wired in ``hooks/hooks.json`` as a PreToolUse entry with matcher
``WebSearch|WebFetch``; one interpreter spawn per web event.
"""

from __future__ import annotations

import json
import os
import sys

try:
    from ux_research_context import _gate_open  # same directory import
except ImportError:  # direct execution: python hooks/web_nudge.py
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ux_research_context import _gate_open  # type: ignore

#: The one line injected ahead of a web call in a uxr workspace.
NUDGE_LINE = (
    "Grounding nudge: a registered source may answer this - check the "
    "matching entry under references/sources/ (index: "
    "references/research-sources.md) and fetch its bookmarked page "
    "first; cite the URL with the claim."
)

#: The PreToolUse tool names the nudge rides.
WEB_TOOLS = ("WebSearch", "WebFetch")


def handle_event(event, config: dict | None = None, environ: dict | None = None, home=None) -> str:
    """Return the stdout payload for one event (empty string = print nothing)."""
    try:
        if not isinstance(event, dict):
            return ""
        if event.get("hook_event_name") != "PreToolUse":
            return ""
        if str(event.get("tool_name", "")) not in WEB_TOOLS:
            return ""
        cwd = event.get("cwd") or os.getcwd()
        if not _gate_open(cwd, config=config, environ=environ, home=home):
            return ""
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": NUDGE_LINE,
            }
        }
        return json.dumps(payload)
    except Exception:
        return ""


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        out = handle_event(event)
        if out:
            print(out)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
