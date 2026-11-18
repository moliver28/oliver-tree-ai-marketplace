#!/usr/bin/env python3
"""Analytics event listener: one consent-gated counter per interaction.

Wired for four events (see hooks/hooks.json); other events are classified
too when they arrive:

- UserPromptExpansion, and UserPromptSubmit (the turn-start event
  runtimes without the expansion event do support, e.g. ZCode 0.17.1):
  a prompt that expands a slash command records ``command_invoked`` with
  the normalized command name. Claude Code fires both events for one
  command (Submit before the expansion, Expansion at it), so the same
  session counting the same command twice inside a short window is one
  invocation: a small dedup marker in the state dir keeps the count at
  one. Legitimate re-invocations outside the window count again.
- SubagentStop: a dispatch of a plugin agent (every agent under agents/
  is allowlisted; the allowlist is discovered from the directory, so a
  new agent file never needs a code change) records ``agent_dispatched``.
  Stop is wired for the ZCode path too but records nothing: the
  turn-end transcript is already covered by SubagentStop where that
  event exists, and a Stop-side scan would double-count on Claude Code.
- PostToolUse (defensive, not wired today): the Skill tool records
  ``skill_invoked``; a failed tool result records ``tool_failed`` with the
  tool name and a kind, never the detail.

With consent off (analytics_common.analytics_enabled) nothing is recorded
and nothing else runs. Events land in the monthly buffer; this hook never
touches the network.

Hook contract (all hooks in this plugin): read the event JSON from stdin,
catch every exception, exit 0 on any error, print nothing.

Usage::

    python hooks/analytics.py selftest     # run the self-test
    python hooks/analytics.py --selftest   # same, flag form
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import analytics_common  # noqa: E402
from provenance import failure_kind  # noqa: E402  (same hooks/ directory)

#: How much transcript tail to scan for a plugin agent name, in bytes.
TAIL_BYTES = 262144

#: Command directory override (selftests point this at a fixture dir).
COMMANDS_DIR = None

#: Prompt events that may expand a plugin command.
PROMPT_EVENTS = ("UserPromptExpansion", "UserPromptSubmit")

#: Event payload fields that may name the dispatched agent.
AGENT_FIELDS = ("agent_type", "agent_name", "agent", "subagent_type")

#: One slash command counted twice for one session inside this window is
#: the same invocation seen through UserPromptSubmit and (Claude Code)
#: UserPromptExpansion; outside the window it counts again.
COMMAND_DEDUP_WINDOW_SECONDS = 60

#: The dedup marker file, inside the state dir. Keys are salted session
#: ids plus the command, so the file never holds a raw session id.
COMMAND_DEDUP_FILENAME = "command-dedup.json"

#: Upper bound on kept dedup entries (oldest dropped on write).
COMMAND_DEDUP_MAX_ENTRIES = 200


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def plugin_agents(agents_dir=None) -> list[str]:
    """The allowlist: every agent under agents/ (discovered, not hardcoded)."""
    base = Path(agents_dir) if agents_dir is not None else PLUGIN_ROOT / "agents"
    try:
        return sorted(item.stem for item in base.glob("*.md"))
    except OSError:
        return []


def normalize_command(prompt: str, commands_dir=None) -> str:
    """The shipped command name a prompt expands, or empty when it is none.

    /uxr-plugin:uxr-eod (the installed namespace) and /uxr-eod (the file
    name) both normalize to /uxr-eod. Only shipped commands count: the
    names come from commands/, so a renamed or dropped command stops being
    counted and a new one never needs a code change.
    """
    text = str(prompt or "").strip()
    if not text.startswith("/"):
        return ""
    head = text.split()[0].strip()
    stem = head[1:]
    if ":" in stem:
        stem = stem.rsplit(":", 1)[-1]
    if not stem.startswith("uxr"):
        return ""
    base = Path(commands_dir) if commands_dir is not None \
        else (COMMANDS_DIR or PLUGIN_ROOT / "commands")
    try:
        shipped = {item.stem for item in base.glob("*.md")}
    except OSError:
        shipped = set()
    return "/" + stem if stem in shipped else ""


def explicit_agent(event: dict) -> str:
    """The event's explicit agent name, or empty when it has none."""
    for field in AGENT_FIELDS:
        value = str(event.get(field) or "").strip()
        if value:
            return value
    return ""


def transcript_agent(event: dict, allowlist: list[str]) -> str:
    """Scan the transcript tail for a dispatch naming an allowlisted agent."""
    where = str(event.get("transcript_path") or "")
    if not where or not allowlist:
        return ""
    try:
        with open(where, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read(TAIL_BYTES)
    except OSError:
        return ""
    for name in allowlist:
        if name.encode("utf-8") in tail:
            return name
    return ""


def is_tool_failure(event: dict) -> tuple[bool, str]:
    """(failed, response text) for one PostToolUse event."""
    reply = event.get("tool_response")
    if isinstance(reply, dict):
        text = str(reply.get("content") or reply.get("text") or reply.get("error") or "")
        failed = bool(reply.get("is_error") or reply.get("error"))
        return failed, text
    text = str(reply or "")
    return bool(text and '"is_error": true' in text.lower()), text


def _dedup_path(state_dir, config=None, environ=None):
    """The command dedup marker file, or None when there is no state dir."""
    try:
        state = Path(state_dir) if state_dir is not None \
            else analytics_common.resolve_state_dir(config, environ=environ)
    except Exception:
        return None
    return state / COMMAND_DEDUP_FILENAME if state is not None else None


def _parse_stamp(value) -> datetime | None:
    """Parse a stored ISO stamp (or pass a datetime through); None on failure."""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _dedup_key(salt: str, session_id: str, command: str) -> str:
    """One dedup key: salted session id (never raw) plus the command."""
    return "%s|%s" % (analytics_common.pseudonymous_id(salt, str(session_id or "")),
                      command)


def command_counted(command: str, session_id: str, config=None, state_dir=None,
                    environ=None, home=None, now=None) -> bool:
    """True when this session already counted this command in the window.

    Consent off counts as counted: nothing would be recorded anyway, and
    the state dir stays untouched. Any state error counts as not counted
    (fail open): a rare duplicate beats a lost count.
    """
    try:
        if not analytics_common.analytics_enabled(config, environ=environ, home=home):
            return True
        path = _dedup_path(state_dir, config=config, environ=environ)
        if path is None or not path.is_file():
            return False
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, dict):
            return False
        salt = analytics_common.load_or_create_salt(path.parent)
        stamp = entries.get(_dedup_key(salt, session_id, command))
        moment, seen = _parse_stamp(now), _parse_stamp(stamp)
        if moment is None or seen is None:
            return False
        return (moment - seen).total_seconds() < COMMAND_DEDUP_WINDOW_SECONDS
    except Exception:
        return False


def mark_command_counted(command: str, session_id: str, config=None, state_dir=None,
                         environ=None, home=None, now=None) -> None:
    """Best effort: remember that this session counted this command just now."""
    try:
        path = _dedup_path(state_dir, config=config, environ=environ)
        if path is None:
            return
        salt = analytics_common.load_or_create_salt(path.parent)
        if not salt:
            return
        entries = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    entries = loaded
            except ValueError:
                entries = {}
        moment = _parse_stamp(now) or datetime.now().astimezone()
        entries[_dedup_key(salt, session_id, command)] = moment.isoformat(timespec="seconds")
        cutoff = moment - timedelta(seconds=COMMAND_DEDUP_WINDOW_SECONDS)
        kept = {key: stamp for key, stamp in entries.items()
                if isinstance(_parse_stamp(stamp), datetime)
                and _parse_stamp(stamp) >= cutoff}
        if len(kept) > COMMAND_DEDUP_MAX_ENTRIES:
            kept = dict(sorted(kept.items(), key=lambda item: str(item[1]))
                        [-COMMAND_DEDUP_MAX_ENTRIES:])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def handle_event(event, config=None, state_dir=None, environ=None, home=None,
                 now=None) -> str:
    """Classify one hook event and record its counter; always empty string."""
    try:
        if not isinstance(event, dict):
            return ""
        session_id = str(event.get("session_id") or "")
        name = event.get("hook_event_name")
        if name in PROMPT_EVENTS:
            expansion = str(event.get("expansion_type") or "").strip().lower()
            if expansion and expansion != "slash_command":
                return ""
            command = normalize_command(str(event.get("prompt") or ""))
            if command:
                if command_counted(command, session_id, config=config,
                                   state_dir=state_dir, environ=environ,
                                   home=home, now=now):
                    return ""
                if analytics_common.record_event(
                        "command_invoked", {"command": command},
                        session_id=session_id, config=config, state_dir=state_dir,
                        environ=environ, home=home, now=now):
                    mark_command_counted(command, session_id, config=config,
                                         state_dir=state_dir, environ=environ,
                                         home=home, now=now)
            return ""
        if name == "Stop":
            # Wired for the ZCode turn end; nothing to count there.
            return ""
        if name == "SubagentStop":
            agent = explicit_agent(event)
            if not agent:
                agent = transcript_agent(event, plugin_agents())
            if agent and agent in plugin_agents():
                analytics_common.record_event(
                    "agent_dispatched", {"agent": agent}, session_id=session_id,
                    config=config, state_dir=state_dir, environ=environ, home=home)
            return ""
        if name == "PostToolUse":
            tool_name = str(event.get("tool_name") or "")
            tool_input = event.get("tool_input") \
                if isinstance(event.get("tool_input"), dict) else {}
            if tool_name == "Skill" and str(tool_input.get("skill") or "").strip():
                analytics_common.record_event(
                    "skill_invoked", {"skill": str(tool_input["skill"]).strip()},
                    session_id=session_id, config=config, state_dir=state_dir,
                    environ=environ, home=home)
                return ""
            failed, text = is_tool_failure(event)
            if failed:
                analytics_common.record_event(
                    "tool_failed", {"tool_name": tool_name, "kind": failure_kind(text)},
                    session_id=session_id, config=config, state_dir=state_dir,
                    environ=environ, home=home)
        return ""
    except Exception:
        return ""


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in args or "--selftest" in args:
        return _selftest()
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    with contextlib.suppress(Exception):
        handle_event(event, config=_load_config())
    return 0


def _selftest() -> int:
    """Cover command normalization, the discovered agent allowlist, the
    consent gate, and the failure-kind split. The buffer goes to a temp
    state dir; nothing here touches the network."""
    global COMMANDS_DIR
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/analytics.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        state = tmp / "state"
        commands = tmp / "commands"
        commands.mkdir()
        for stem in ("uxr-eod", "uxr-trace", "uxr-stats", "uxr-new"):
            (commands / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        COMMANDS_DIR = commands
        agents = tmp / "agents"
        agents.mkdir()
        agent_names = ["expert-participant", "hcd-researcher", "novice-participant",
                       "novice-report-reader", "research-dataviz-designer",
                       "script-writer", "stakeholder-reviewer"]
        for stem in agent_names:
            (agents / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        enabled = {"analytics": {"enabled": True, "endpoint": "", "api_key": ""}}
        disabled = {"analytics": {"enabled": False, "endpoint": "", "api_key": ""}}

        def rows():
            path = analytics_common.buffer_path(state)
            if not path.is_file():
                return []
            return [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]

        # 1. Command normalization.
        check("installed namespace normalizes",
              normalize_command("/uxr-plugin:uxr-eod --dry-run", commands) == "/uxr-eod")
        check("a bare shipped command counts",
              normalize_command("/uxr-trace", commands) == "/uxr-trace")
        check("an unshipped command does not count",
              normalize_command("/uxr-absent", commands) == "")
        check("a non-slash prompt does not count",
              normalize_command("summarize the study", commands) == "")

        # 2. The allowlist is discovered from agents/.
        check("the allowlist holds every shipped agent",
              plugin_agents(agents) == agent_names, repr(plugin_agents(agents)))

        # 3. Consent off: nothing recorded.
        check("consent off records nothing",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "prompt": "/uxr-eod", "session_id": "s1"},
                           config=disabled, state_dir=state, environ={}, home=HOME) == ""
              and not rows())

        # 4. command_invoked from a slash-command expansion.
        check("slash-command expansion records command_invoked",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "expansion_type": "slash_command",
                            "prompt": "/uxr-plugin:uxr-eod", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "command_invoked"
                      and row.get("command") == "/uxr-eod" for row in rows()))
        salt = analytics_common.load_or_create_salt(state)
        check("recorded session ids are salted, never raw",
              bool(rows())
              and all(row.get("session_id") == analytics_common.pseudonymous_id(salt, "s1")
                      for row in rows()))
        check("a plain prompt expansion records nothing",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "prompt": "what is on my plate", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len(rows()) == 1)

        # 5. agent_dispatched from SubagentStop.
        transcript = tmp / "transcript.jsonl"
        transcript.write_text('{"tool": "Task", "subagent_type": "script-writer"}\n',
                              encoding="utf-8")
        check("explicit plugin agent records agent_dispatched",
              handle_event({"hook_event_name": "SubagentStop",
                            "agent_type": "hcd-researcher", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "agent_dispatched"
                      and row.get("agent") == "hcd-researcher" for row in rows()))
        check("a non-plugin agent is not recorded",
              handle_event({"hook_event_name": "SubagentStop",
                            "agent_type": "general-purpose", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len([row for row in rows()
                       if row.get("event") == "agent_dispatched"]) == 1)
        check("transcript scan resolves an allowlisted agent",
              transcript_agent({"transcript_path": str(transcript)},
                               plugin_agents(agents)) == "script-writer")
        check("transcript scan with an empty allowlist finds nothing",
              transcript_agent({"transcript_path": str(transcript)}, []) == "")

        # 6. tool_failed kinds; the detail never travels.
        check("a plain failure records tool_failed with kind tool_error",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                            "tool_response": {"is_error": True,
                                              "content": "exit code 1: boom"},
                            "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "tool_failed"
                      and row.get("tool_name") == "Bash"
                      and row.get("kind") == "tool_error"
                      and "boom" not in json.dumps(row) for row in rows()))
        check("a rejection phrase records kind user_rejection",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Write",
                            "tool_response": {"is_error": True,
                                              "content": "The user doesn't want to proceed."},
                            "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "tool_failed"
                      and row.get("kind") == "user_rejection" for row in rows()))
        check("skill use records skill_invoked",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                            "tool_input": {"skill": "notebooklm"}, "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "skill_invoked"
                      and row.get("skill") == "notebooklm" for row in rows()))

        # 7. Malformed events are silent.
        check("malformed events print nothing and record nothing",
              handle_event(None, config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and handle_event({}, config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len(rows()) == 5)

        # 8. UserPromptSubmit counts like UserPromptExpansion, and the
        # Claude Code double fire (Submit before the expansion, Expansion
        # at it) stays one command_invoked inside the dedup window.
        base = "2026-11-09T10:30:00-05:00"
        submit = {"hook_event_name": "UserPromptSubmit",
                  "prompt": "/uxr-trace", "session_id": "s9"}
        check("UserPromptSubmit records command_invoked",
              handle_event(submit, config=enabled, state_dir=state,
                           environ={}, home=HOME, now=base) == ""
              and any(row.get("event") == "command_invoked"
                      and row.get("command") == "/uxr-trace" for row in rows())
              and len(rows()) == 6, repr(rows()))
        check("the Submit then Expansion double fire counts once",
              handle_event(dict(submit, hook_event_name="UserPromptExpansion",
                                expansion_type="slash_command"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME, now=base) == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 1,
              repr(rows()))
        check("the same command counts again outside the window",
              handle_event(dict(submit, prompt="/uxr-trace --json"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME,
                           now="2026-11-09T10:32:00-05:00") == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 2,
              repr(rows()))
        check("a different session is not deduped away",
              handle_event(dict(submit, session_id="s10"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME,
                           now="2026-11-09T10:32:30-05:00") == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 3,
              repr(rows()))

        # 9. Stop is wired for the ZCode turn end but records nothing.
        stop_buffer = len(rows())
        check("a Stop fire records nothing",
              handle_event({"hook_event_name": "Stop", "session_id": "s9"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and handle_event({"hook_event_name": "Stop", "session_id": "s9",
                                "agent_type": "hcd-researcher",
                                "transcript_path": str(transcript)},
                               config=enabled, state_dir=state, environ={},
                               home=HOME) == ""
              and len(rows()) == stop_buffer, repr(rows()))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
