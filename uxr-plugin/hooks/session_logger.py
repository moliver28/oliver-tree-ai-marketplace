#!/usr/bin/env python3
"""Session-end journal: one research-session row per session, plus provenance.

Reads the session-end event from stdin (``hook_event_name`` must be
SessionEnd or Stop; also used: ``cwd``, ``transcript_path``,
``session_id``), walks the transcript JSONL once, and:

1. Collects ticket keys (``tracker.ticket_regex`` over user text and
   tracker tool inputs), commands used (a prompt line that starts with a
   plugin command, or a ``<command-name>`` tag for one), files edited
   (Edit / Write / MultiEdit / NotebookEdit), tracker tool calls, the
   user message count with first/last timestamps and a 280-character
   last-message snippet, skills invoked, and agents dispatched.
2. A session is a research session when cwd is in a research root, or a
   ticket key appeared, or a plugin command was used. Anything else
   writes nothing.
3. Extracts provenance (hooks/provenance.py) in the same single walk.
4. Upserts one row in ``<state_dir>/work-log-<local YYYY-MM-DD>.jsonl``
   under a file lock, keyed by ``session_id``. A replace keeps an old
   row's ``processed: true``; malformed lines stay as they are.
5. Only when the row is new: emits the analytics ``session_summary``.
6. When provenance exists and cwd is in a workspace: writes the
   workspace manifests (session record, provenance.jsonl edges,
   sources-index.json). SessionEnd only: a Stop fire stops after the
   row upsert, so per-turn fires never duplicate manifest files, edge
   lines, or source-index counts.
7. Calls the optional workspace sync only when ``sync.enabled`` is true.

Both events are wired (hooks/hooks.json): SessionEnd is the Claude Code
session end; Stop is the per-turn turn end that runtimes without
SessionEnd (ZCode 0.17.1) do support, so the journal row stays current
and ``session_summary`` is emitted once per session either way.

The hook prints nothing and exits 0 on any error (the fail-open contract).

Usage::

"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import analytics_common  # noqa: E402
from provenance import (  # noqa: E402  (same hooks/ directory)
    TranscriptWalk,
    file_lock,
    find_workspace,
    ticket_regex,
    write_workspace_manifests,
)

SNIPPET_CHARS = 280
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
COMMAND_TAG_START = "<command-name>"
COMMAND_TAG_END = "</command-name>"
ENV_RESEARCH_DIRS = "UXR_RESEARCH_DIRS"


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def local_now() -> str:
    """ISO 8601 local time with offset, second precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def research_roots(config: dict | None, environ=None) -> list[str]:
    """Candidate research roots: UXR_RESEARCH_DIRS entries, then the config path."""
    environ = os.environ if environ is None else environ
    roots: list[str] = []
    for part in str(environ.get(ENV_RESEARCH_DIRS) or "").split(os.pathsep):
        if part.strip():
            roots.append(part.strip())
    if isinstance(config, dict):
        value = config.get("paths", {})
        if isinstance(value, dict):
            root = value.get("research_root")
            if isinstance(root, str) and root.strip():
                roots.append(root)
    return roots


def normalize_commands(text: str, commands_dir=None, plugin_root=None) -> list[str]:
    """Plugin command names used in one user text.

    A prompt line that starts with a plugin command (its first token
    normalizes to a shipped command) or a ``<command-name>`` tag for one.
    Normalization is shared with analytics: ``/uxr-plugin:uxr-eod`` and
    ``/uxr-eod`` both become ``/uxr-eod``.
    """
    from analytics import normalize_command

    if plugin_root is not None:
        base = Path(plugin_root) / "commands"
    else:
        base = commands_dir
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            found.append(name)

    if COMMAND_TAG_START in text:
        head, remainder = text, True
        while head and COMMAND_TAG_START in head:
            head = head.split(COMMAND_TAG_START, 1)[1]
            tag = head.split(COMMAND_TAG_END, 1)[0] if COMMAND_TAG_END in head else ""
            add(normalize_command(tag, base))
            if COMMAND_TAG_END in head:
                head = head.split(COMMAND_TAG_END, 1)[1]
            else:
                break
    for line in text.splitlines():
        add(normalize_command(line, base))
    return found


def collect_stats(event: dict, config: dict | None, walk: TranscriptWalk,
                  commands_dir=None, environ=None, home=None) -> dict:
    """One transcript walk collecting session facts and provenance together."""
    stats = {
        "user_message_count": 0,
        "first_user_at": "",
        "last_user_at": "",
        "last_user_snippet": "",
        "commands_used": [],
        "files_edited": [],
        "tracker_tool_calls": 0,
        "skills_invoked": [],
        "agents_dispatched": [],
        "ticket_keys": [],
    }
    regex = ticket_regex(config)
    keys_seen: set[str] = set()

    def add_key(value: str) -> None:
        for match in regex.finditer(value):
            key = match.group(0)
            if key not in keys_seen:
                keys_seen.add(key)
                stats["ticket_keys"].append(key)

    transcript_path = str(event.get("transcript_path") or "")
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for fact in walk.feed(obj):
                    if fact[0] == "user":
                        _, text, stamp = fact
                        stats["user_message_count"] += 1
                        if not stats["first_user_at"]:
                            stats["first_user_at"] = stamp
                        stats["last_user_at"] = stamp
                        stats["last_user_snippet"] = text[:SNIPPET_CHARS]
                        add_key(text)
                        for name in normalize_commands(
                                text, commands_dir,
                                plugin_root=event.get("_plugin_root")):
                            if name not in stats["commands_used"]:
                                stats["commands_used"].append(name)
                    elif fact[0] == "tool":
                        _, tool_name, _op, tool_input, _ts = fact
                        if tool_name in EDIT_TOOLS:
                            for field in ("file_path", "notebook_path"):
                                where = tool_input.get(field)
                                if where and where not in stats["files_edited"]:
                                    stats["files_edited"].append(str(where))
                        if tool_name == "Skill":
                            skill = str(tool_input.get("skill") or "").strip()
                            if skill and skill not in stats["skills_invoked"]:
                                stats["skills_invoked"].append(skill)
                        if tool_name == "Task":
                            agent = str(tool_input.get("subagent_type")
                                        or "").strip()
                            if agent and agent not in stats["agents_dispatched"]:
                                stats["agents_dispatched"].append(agent)
                        kind, _ = _classify(tool_name, config)
                        if kind == "tracker":
                            stats["tracker_tool_calls"] += 1
                            add_key(json.dumps(tool_input, sort_keys=True,
                                               ensure_ascii=False, default=str))
    except OSError:
        pass
    return stats


def _classify(tool_name: str, config: dict | None):
    """Shim so the stats walk can count tracker calls without a provenance import cycle."""
    from provenance import classify_tool

    return classify_tool(tool_name, config)


def build_row(session_id: str, ended_at: str, cwd: str, in_research: bool,
              stats: dict, provenance: dict, transcript_path: str,
              processed: bool = False) -> dict:
    """One journal row with exactly the contract keys, in contract order."""
    source_types: dict[str, int] = {}
    for source in provenance.get("sources", []):
        kind = str(source.get("type") or "")
        source_types[kind] = source_types.get(kind, 0) + 1
    return {
        "session_id": session_id,
        "ended_at": ended_at,
        "cwd": cwd,
        "in_research_dir": in_research,
        "ticket_keys": stats["ticket_keys"],
        "commands_used": stats["commands_used"],
        "files_edited": stats["files_edited"],
        "files_edited_count": len(stats["files_edited"]),
        "tracker_tool_calls": stats["tracker_tool_calls"],
        "user_message_count": stats["user_message_count"],
        "first_user_at": stats["first_user_at"],
        "last_user_at": stats["last_user_at"],
        "last_user_snippet": stats["last_user_snippet"],
        "transcript_path": transcript_path,
        "provenance": {
            "source_count": len(provenance.get("sources", [])),
            "source_types": source_types,
            "output_count": len(provenance.get("outputs", [])),
            "files_read_count": len(provenance.get("files_read", [])),
            "relationship_count": len(provenance.get("relationships", [])),
        },
        "processed": processed,
    }


def upsert_row(journal_path: Path, row: dict) -> bool:
    """Insert or replace the row for ``row["session_id"]``; True when new.

    Under a file lock, the file is rewritten atomically: malformed lines
    stay verbatim, a replaced row keeps the old ``processed`` value, and
    duplicate rows for the same session collapse into one.
    """
    new_id = str(row.get("session_id") or "")
    original: list[str] = []
    if journal_path.is_file():
        try:
            original = journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            original = []
    out: list[str] = []
    is_new = True
    replaced = False
    old_processed = False
    for line in original:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            assert isinstance(parsed, dict)
        except (ValueError, AssertionError):
            out.append(stripped)
            continue
        if str(parsed.get("session_id") or "") == new_id:
            if replaced:
                continue  # collapse an extra row for the same session
            replaced = True
            is_new = False
            old_processed = bool(parsed.get("processed"))
            continue
        out.append(stripped)
    if replaced:
        row = dict(row)
        row["processed"] = old_processed
    out.append(json.dumps(row, ensure_ascii=False))
    text = "\n".join(out) + "\n"
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(journal_path.with_name(journal_path.name + ".lock")):
            import tempfile

            fd, tmp_name = tempfile.mkstemp(dir=str(journal_path.parent),
                                            prefix=journal_path.name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp_name, str(journal_path))
    except OSError:
        pass
    return is_new


def is_research_session(cwd, roots: list[str]) -> bool:
    """True when cwd sits in a research root (or a marker workspace)."""
    try:
        real = Path(cwd).expanduser().resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved = Path(root).expanduser()
            if hasattr(resolved, "resolve"):
                resolved = resolved.resolve()
        except OSError:
            resolved = Path(root)
        if real == resolved or resolved in real.parents:
            return True
    return find_workspace(real) is not None


def handle_event(event, config=None, state_dir=None, environ=None, home=None,
                 commands_dir=None, now=None) -> dict:
    """Process one session-end event (SessionEnd or Stop); returns a small
    summary for the self-test."""
    summary: dict = {"row_written": False, "row_is_new": False,
                     "manifests": {}, "research": False}
    try:
        name = event.get("hook_event_name") if isinstance(event, dict) else None
        if name not in ("SessionEnd", "Stop"):
            return summary
        session_id = str(event.get("session_id") or "")
        if not session_id:
            return summary
        # ZCode Stop events carry no cwd; the hook process runs in the
        # session's project directory, so fall back to it.
        cwd = str(event.get("cwd") or "") or os.getcwd()
        roots = research_roots(config, environ=environ)
        in_research = is_research_session(cwd, roots) if cwd else False
        walk = TranscriptWalk(config=config, home=home)
        stats = collect_stats(event, config, walk, commands_dir=commands_dir,
                              environ=environ, home=home)
        has_ticket = bool(stats["ticket_keys"])
        has_command = bool(stats["commands_used"])
        if not (in_research or has_ticket or has_command):
            return summary  # a non-research session writes nothing
        summary["research"] = True
        provenance = walk.result(research_dirs=roots)
        ended_at = now or local_now()
        row = build_row(session_id, ended_at, cwd, in_research, stats,
                        provenance, str(event.get("transcript_path") or ""))
        state = Path(state_dir) if state_dir is not None \
            else analytics_common.resolve_state_dir(config, environ=environ)
        if state is not None:
            journal = state / ("work-log-%s.jsonl" % ended_at[:10])
            is_new = upsert_row(journal, row)
            summary["row_written"] = True
            summary["row_is_new"] = is_new
            summary["journal"] = str(journal)
            if is_new:
                analytics_common.record_event(
                    "session_summary",
                    {"research_session": True,
                     "user_messages": stats["user_message_count"],
                     "files_edited": len(stats["files_edited"]),
                     "tracker_calls": stats["tracker_tool_calls"],
                     "commands": len(stats["commands_used"])},
                    session_id=session_id, config=config, state_dir=state,
                    environ=environ, home=home)
        workspace = find_workspace(cwd) if cwd else None
        has_provenance = any(bool(provenance.get(field)) for field in
                             ("sources", "outputs", "files_read", "relationships"))
        if name == "SessionEnd" and workspace is not None and has_provenance:
            sync_enabled = False
            if isinstance(config, dict):
                sync = config.get("sync")
                sync_enabled = bool(isinstance(sync, dict) and sync.get("enabled"))
            record = dict(row)
            record.pop("last_user_snippet", None)  # the journal keeps it; the workspace copy does not
            record["provenance"] = provenance  # the record keeps the details
            record["sync"] = {"enabled": sync_enabled}
            if sync_enabled:
                record["sync"]["result"] = _sync_workspace(workspace, config)
            summary["manifests"] = write_workspace_manifests(
                workspace, record, provenance, config=config)
        return summary
    except Exception:
        return summary


def _sync_workspace(workspace, config) -> dict:
    """Optional post-session workspace commit; only when sync.enabled is true."""
    try:
        from workspace_sync import sync_workspace

        return sync_workspace(workspace, config)
    except Exception:
        return {"committed": False, "pushed": False, "reason": "sync unavailable"}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    with contextlib.suppress(Exception):
        handle_event(event, config=_load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
