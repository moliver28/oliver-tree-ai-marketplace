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

#: How much transcript tail to scan for a plugin agent name, in bytes.
TAIL_BYTES = 262144

#: Command directory override (tests point this at a fixture dir).
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
                from provenance import failure_kind  # same hooks/ directory
                analytics_common.record_event(
                    "tool_failed", {"tool_name": tool_name, "kind": failure_kind(text)},
                    session_id=session_id, config=config, state_dir=state_dir,
                    environ=environ, home=home)
        return ""
    except Exception:
        return ""


def main(argv=None) -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    if analytics_common.consent_off_without_config():
        return 0
    from lib.util import load_config as _load_config  # shared plumbing
    with contextlib.suppress(Exception):
        handle_event(event, config=_load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
