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

    python hooks/ux_research_context.py selftest     # run the self-test
    python hooks/ux_research_context.py --selftest   # same, flag form
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
OVERVIEW_MARKER = "00-overview.md"
ENV_RESEARCH_DIRS = "UXR_RESEARCH_DIRS"


def _resolve(path) -> Path:
    """Expand and resolve a path; fall back to the absolute form on failure."""
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        try:
            return Path(path).expanduser().absolute()
        except OSError:
            return Path(path)


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        if str(PLUGIN_ROOT) not in sys.path:
            sys.path.insert(0, str(PLUGIN_ROOT))
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


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


def _selftest() -> int:
    """Cover the gate, the marker walk, the output shape, and ignored events."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    def run(event: dict, **kwargs) -> str:
        kwargs.setdefault("environ", {})
        return handle_event(event, home=HOME, **kwargs)

    def is_session_start_json(output: str) -> dict:
        if not output or "\n" in output.strip():
            return {}
        try:
            payload = json.loads(output)
        except ValueError:
            return {}
        specific = payload.get("hookSpecificOutput") or {}
        if specific.get("hookEventName") != "SessionStart":
            return {}
        if not isinstance(specific.get("additionalContext"), str):
            return {}
        return specific

    print("hooks/ux_research_context.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        plain = tmp / "plain"
        plain.mkdir()
        root = tmp / "research"
        study = root / "Study A"
        study.mkdir(parents=True)
        env_roots = {ENV_RESEARCH_DIRS: f"{root}{os.pathsep}{tmp / 'other'}"}
        config_root = {"paths": {"research_root": str(root)}}
        start = {"hook_event_name": "SessionStart"}

        # 1. Outside a research root with no marker: no output.
        check(
            "outside a research root prints nothing",
            run({**start, "cwd": str(plain)}) == "",
            "expected empty output",
        )

        # 2. Inside a UXR_RESEARCH_DIRS root: one SessionStart JSON line.
        output = run({**start, "cwd": str(study)}, config=None, environ=env_roots)
        specific = is_session_start_json(output)
        check(
            "UXR_RESEARCH_DIRS root opens the gate",
            bool(specific),
            repr(output[:120]),
        )
        check(
            "output is one SessionStart JSON object with context text",
            bool(specific) and len(specific["additionalContext"]) > 0,
            repr(output[:120]),
        )

        # 3. Inside the config research root: the gate opens too.
        output = run({**start, "cwd": str(study)}, config=config_root)
        check(
            "paths.research_root from the config opens the gate",
            bool(is_session_start_json(output)),
            repr(output[:120]),
        )

        # 4. A folder holding 00-overview.md opens the gate without any root.
        marked = tmp / "marked-study"
        marked.mkdir()
        (marked / OVERVIEW_MARKER).write_text("# overview\n", encoding="utf-8")
        output = run({**start, "cwd": str(marked)})
        specific = is_session_start_json(output)
        check(
            "a cwd with 00-overview.md opens the gate",
            bool(specific),
            repr(output[:120]),
        )
        check(
            "context text names the tracker and the routing note",
            bool(specific) and "Tracker:" in specific["additionalContext"]
            and "Routing:" in specific["additionalContext"],
            repr(specific.get("additionalContext", "")[:200]),
        )

        # 5. A parent below $HOME holding the marker opens the gate.
        (HOME / "docs").mkdir(parents=True)
        (HOME / "docs" / OVERVIEW_MARKER).write_text("# overview\n", encoding="utf-8")
        nested = HOME / "docs" / "spring study"
        nested.mkdir()
        check(
            "a parent below $HOME with 00-overview.md opens the gate",
            bool(is_session_start_json(run({**start, "cwd": str(nested)}))),
            "gate stayed closed",
        )

        # 6. The marker at $HOME itself does not open the gate for siblings.
        other = HOME / "unrelated"
        other.mkdir()
        check(
            "$HOME itself holding the marker does not open sibling folders",
            run({**start, "cwd": str(other)}) == "",
            "expected empty output",
        )

        # 7. UserPromptSubmit never injects text, even inside a research root.
        for environ in ({}, env_roots):
            output = handle_event(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "cwd": str(study),
                    "prompt": "summarize the study",
                },
                environ=environ,
                home=HOME,
            )
            check(
                f"UserPromptSubmit prints nothing (environ={'roots' if environ else 'empty'})",
                output == "",
                repr(output[:120]),
            )

        # 8. Other events print nothing.
        for name in ("SessionEnd", "Stop", "PreToolUse"):
            check(
                f"{name} prints nothing",
                handle_event({"hook_event_name": name, "cwd": str(study)},
                             environ=env_roots, home=HOME) == "",
                "expected empty output",
            )

        # 9. Missing hook_event_name is treated as an unknown event.
        check(
            "an event without hook_event_name prints nothing",
            run({"cwd": str(study)}) == "",
            "expected empty output",
        )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in args or "--selftest" in args:
        return _selftest()
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
