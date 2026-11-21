#!/usr/bin/env python3
"""SessionStart context injection for research folders.

Fires on SessionStart only; every other event (including UserPromptSubmit)
prints nothing. The gate opens when the session's working directory sits
inside a research root -- ``paths.research_root`` from the config contract,
or a directory in the ``UXR_RESEARCH_DIRS`` environment variable (entries
separated by the platform path separator) -- or when the working directory
or a parent below ``$HOME`` holds ``00-overview.md``. With the gate open it
prints one SessionStart ``additionalContext`` JSON object naming the plugin's
commands, the tracker constants, and the routing note. Otherwise it prints
nothing.

Hook contract (all hooks in this plugin):

1. Read the event JSON from stdin.
2. Catch every exception. Exit 0 on any error.
3. Print nothing unless the event contract asks for output.

Usage::

"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.util import ENV_RESEARCH_DIRS, load_config as _load_config, resolve as _resolve  # noqa: E402  (shared plumbing)
OVERVIEW_MARKER = "00-overview.md"


def _research_roots(config: dict | None, environ: dict) -> list[str]:
    """Candidate research roots: the environment list, then the config path."""
    roots: list[str] = []
    for part in environ.get(ENV_RESEARCH_DIRS, "").split(os.pathsep):
        if part.strip():
            roots.append(part.strip())
    if config:
        value = config.get("paths", {}).get("research_root")
        if isinstance(value, str) and value.strip():
            roots.append(value)
    return roots


def _gate_open(
    cwd,
    config: dict | None = None,
    environ: dict | None = None,
    home=None,
) -> bool:
    """True when cwd sits inside a research root or a marker folder."""
    environ = os.environ if environ is None else environ
    home = _resolve(home if home is not None else Path.home())
    real = _resolve(cwd)
    for root in _research_roots(config, environ):
        resolved = _resolve(root)
        if real == resolved or resolved in real.parents:
            return True
    # The working directory itself holds the marker.
    if (real / OVERVIEW_MARKER).is_file():
        return True
    # A parent strictly below $HOME holds the marker; never walk into or
    # above $HOME itself.
    for parent in real.parents:
        if parent == home or home not in parent.parents:
            break
        if (parent / OVERVIEW_MARKER).is_file():
            return True
    return False


def _commands_line() -> str:
    """List the shipped slash commands; empty while none exist."""
    try:
        names = sorted(path.stem for path in (PLUGIN_ROOT / "commands").glob("*.md"))
    except OSError:
        return ""
    if not names:
        return ""
    return "Commands: " + ", ".join(f"/uxr-plugin:{name}" for name in names)


def _tracker_line(config: dict | None) -> str:
    if not config:
        return "Tracker: not configured (copy config/org.example.yaml to config/org.yaml)."
    tracker = config.get("tracker", {}) if isinstance(config.get("tracker"), dict) else {}
    parts: list[str] = []
    if tracker.get("kind"):
        parts.append(str(tracker["kind"]))
    if tracker.get("project_key"):
        parts.append(f"project {tracker['project_key']}")
    if tracker.get("ticket_regex"):
        parts.append(f"ticket keys match {tracker['ticket_regex']}")
    if tracker.get("bare_number_prefix"):
        parts.append(f"bare numbers become {tracker['bare_number_prefix']}-<n>")
    if not parts:
        return "Tracker: not configured (copy config/org.example.yaml to config/org.yaml)."
    return "Tracker: " + ", ".join(parts)


def _routing_note(config: dict | None) -> str:
    default = ""
    if config and isinstance(config.get("routing"), dict):
        default = str(config["routing"].get("default_researcher") or "")
    if default:
        return (
            "Routing: each study belongs to its product area's researcher; "
            f"default owner {default}."
        )
    return (
        "Routing: each study belongs to its product area's researcher; "
        "fall back to routing.default_researcher."
    )


def _context_text(config: dict | None) -> str:
    lines = [
        "UX research workspace detected. The uxr-plugin workflows are active.",
        _commands_line(),
        _tracker_line(config),
        _routing_note(config),
    ]
    return "\n".join(line for line in lines if line)


def _session_start_output(
    event: dict,
    config: dict | None = None,
    environ: dict | None = None,
    home=None,
) -> str:
    cwd = event.get("cwd") or os.getcwd()
    if not _gate_open(cwd, config=config, environ=environ, home=home):
        return ""
    text = _context_text(config)
    if not text:
        return ""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    return json.dumps(payload)


def handle_event(
    event,
    config: dict | None = None,
    environ: dict | None = None,
    home=None,
) -> str:
    """Return the stdout payload for one event (empty string = print nothing)."""
    try:
        if not isinstance(event, dict):
            return ""
        if event.get("hook_event_name") != "SessionStart":
            return ""
        return _session_start_output(event, config=config, environ=environ, home=home)
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        output = handle_event(event, config=_load_config())
    except Exception:
        return 0
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
