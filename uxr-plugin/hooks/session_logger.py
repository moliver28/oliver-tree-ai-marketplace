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

    python hooks/session_logger.py selftest     # run the self-test
    python hooks/session_logger.py --selftest   # same, flag form
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
    selftest_fixture_dir,
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
    """Cover the acceptance items: the same session id twice yields one row,
    an old ``processed: true`` survives a rewrite, a second fire emits no
    duplicate analytics, and a non-research session writes nothing."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/session_logger.py selftest")

    with tempfile.TemporaryDirectory(dir=str(selftest_fixture_dir())) as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        research = tmp / "research"
        workspace = research / "permissions-study"
        (workspace / ".sessions").mkdir(parents=True)
        (workspace / "00-overview.md").write_text(
            "# Permissions study\n\nTicket: ABC-274\n", encoding="utf-8")
        outside = tmp / "plain"
        outside.mkdir()
        state = tmp / "state"
        commands = tmp / "commands"
        commands.mkdir()
        for stem in ("uxr-eod", "uxr-new"):
            (commands / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        config = {
            "tracker": {"kind": "jira", "ticket_regex": r"\bABC-\d+\b",
                        "base_url": "https://example.atlassian.net"},
            "paths": {"research_root": str(research)},
            "analytics": {"enabled": True, "endpoint": "", "api_key": ""},
            "sync": {"enabled": False},
        }
        study_file = tmp / "notes.md"
        study_file.write_text("notes", encoding="utf-8")
        transcript = tmp / "transcript.jsonl"
        drive_hash = __import__("provenance").hash12("permissions research")
        lines = [
            {"type": "user", "timestamp": "2026-11-09T10:00:00.000Z",
             "message": {"role": "user",
                         "content": "Check ABC-274 and refresh the summary, then /uxr-eod --dry-run"}},
            {"type": "user", "timestamp": "2026-11-09T10:00:01.000Z",
             "message": {"role": "user",
                         "content": "<command-name>/uxr-plugin:uxr-eod</command-name>"}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:05.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t1", "name": "mcp__jira__getJiraIssue",
                  "input": {"key": "ABC-274"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:06.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "issue"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:07.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t2",
                  "name": "mcp__04b27de0-5b5d-4d1e-9f3a-a1b2c3d4e5f6__searchDrive",
                  "input": {"query": "permissions research"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:08.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t2", "content": "hits"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:09.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t3", "name": "Read",
                  "input": {"file_path": str(study_file)}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:10.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t3", "content": "text"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:11.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t4", "name": "Write",
                  "input": {"file_path": str(workspace / "deliverables" / "summary.md")}},
                 {"type": "tool_use", "id": "t5", "name": "Task",
                  "input": {"subagent_type": "hcd-researcher"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:12.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t4", "content": "ok"},
                 {"type": "tool_result", "tool_use_id": "t5", "content": "done"}]}},
        ]
        transcript.write_text("".join(json.dumps(line) + "\n" for line in lines)
                              + "not json at all\n", encoding="utf-8")

        def run(session_id, cwd, name="SessionEnd", now="2026-11-09T12:00:00-05:00"):
            return handle_event(
                {"hook_event_name": name, "cwd": str(cwd),
                 "transcript_path": str(transcript), "session_id": session_id},
                config=config, state_dir=state, environ={}, home=HOME,
                commands_dir=commands, now=now)

        def journal_rows():
            path = state / "work-log-2026-11-09.jsonl"
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        rows.append(line)
            return rows

        # 1. A research session writes one row with the contract fields.
        run("s1", workspace)
        rows = journal_rows()
        check("one journal row after the first fire", len(rows) == 1, repr(rows))
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        expected_keys = ["session_id", "ended_at", "cwd", "in_research_dir",
                         "ticket_keys", "commands_used", "files_edited",
                         "files_edited_count", "tracker_tool_calls",
                         "user_message_count", "first_user_at", "last_user_at",
                         "last_user_snippet", "transcript_path", "provenance",
                         "processed"]
        check("the row carries the contract keys in order",
              list(row.keys()) == expected_keys, repr(list(row.keys())))
        check("ticket keys come from user text and tracker inputs",
              row.get("ticket_keys") == ["ABC-274"], repr(row.get("ticket_keys")))
        check("commands come from prompts and command-name tags",
              row.get("commands_used") == ["/uxr-eod"], repr(row.get("commands_used")))
        check("files edited are collected from the edit tools",
              row.get("files_edited") == [str(workspace / "deliverables" / "summary.md")],
              repr(row.get("files_edited")))
        check("tracker tool calls are counted",
              row.get("tracker_tool_calls") == 1, repr(row.get("tracker_tool_calls")))
        check("user message facts are kept",
              row.get("user_message_count") == 2
              and row.get("first_user_at") == "2026-11-09T10:00:00.000Z"
              and row.get("last_user_at") == "2026-11-09T10:00:01.000Z",
              repr(row))
        check("the row is not processed and ended_at is local ISO",
              row.get("processed") is False and row.get("ended_at")
              == "2026-11-09T12:00:00-05:00", repr(row.get("ended_at")))
        check("the provenance summary counts the walk",
              row.get("provenance", {}).get("source_count") == 3
              and row.get("provenance", {}).get("output_count") == 1
              and row.get("provenance", {}).get("files_read_count") == 1
              and row.get("provenance", {}).get("relationship_count") == 3,
              repr(row.get("provenance")))

        # 2. The workspace manifests were written.
        manifests = sorted(item.name for item in
                           (workspace / ".sessions").iterdir())
        check("session record, provenance lines, and the sources index exist",
              "2026-11-09T12-00-00-05-00.json" in manifests
              and "provenance.jsonl" in manifests
              and "sources-index.json" in manifests, repr(manifests))
        record = json.loads((workspace / ".sessions"
                             / "2026-11-09T12-00-00-05-00.json").read_text(encoding="utf-8"))
        check("the session record holds the detailed provenance",
              record.get("session_id") == "s1"
              and len(record.get("provenance", {}).get("sources", [])) == 3,
              repr(record.get("provenance", {})))
        check("the drive search source id is stable",
              any(source.get("id") == "drive:search:%s" % drive_hash
                  for source in record.get("provenance", {}).get("sources", [])),
              repr([s.get("id") for s in record.get("provenance", {}).get("sources", [])]))

        # 3. Analytics: exactly one session_summary on the new row.
        buffer_rows = [json.loads(line) for line in
                       (analytics_common.buffer_path(state)).read_text(
                           encoding="utf-8").splitlines() if line.strip()]
        check("one analytics event on the new row",
              len(buffer_rows) == 1
              and buffer_rows[0].get("event") == "session_summary",
              repr(buffer_rows))
        check("the payload maps each field to its own stat",
              buffer_rows[0].get("user_messages") == 2
              and buffer_rows[0].get("tracker_calls") == 1
              and buffer_rows[0].get("files_edited") == 1
              and buffer_rows[0].get("commands") == 1,
              repr(buffer_rows[0]))

        # 4. Same session twice: one row; processed survives; malformed kept.
        rows[0]["processed"] = True
        path = state / "work-log-2026-11-09.jsonl"
        path.write_text("not json at all\n"
                        + json.dumps(rows[0], ensure_ascii=False) + "\n",
                        encoding="utf-8")
        run("s1", workspace)
        rows = journal_rows()
        kept = [r for r in rows if isinstance(r, dict)]
        check("the same session id twice still yields one row", len(kept) == 1, repr(len(kept)))
        check("processed: true survives the rewrite",
              kept and kept[0].get("processed") is True, repr(kept))
        check("the malformed line was preserved verbatim",
              any(isinstance(r, str) and r.strip() == "not json at all" for r in rows),
              repr(rows))
        buffer_rows = [json.loads(line) for line in
                       analytics_common.buffer_path(state).read_text(
                           encoding="utf-8").splitlines() if line.strip()]
        check("a second fire emits no duplicate analytics",
              len(buffer_rows) == 1, repr(len(buffer_rows)))

        # 5. A non-research session (plain cwd, no ticket, no command) writes nothing.
        plain_transcript = tmp / "plain.jsonl"
        plain_transcript.write_text(json.dumps(
            {"type": "user", "timestamp": "2026-11-09T09:00:00.000Z",
             "message": {"role": "user", "content": "what is the weather"}}) + "\n",
            encoding="utf-8")
        handle_event({"hook_event_name": "SessionEnd", "cwd": str(outside),
                      "transcript_path": str(plain_transcript), "session_id": "s2"},
                     config=config, state_dir=state, environ={}, home=HOME,
                     commands_dir=commands, now="2026-11-09T12:02:00-05:00")
        rows = journal_rows()
        check("a non-research session adds no row",
              len([r for r in rows if isinstance(r, dict)]) == 1, repr(rows))
        check("a non-research session writes no analytics",
              len([json.loads(l) for l in analytics_common.buffer_path(state)
                   .read_text(encoding="utf-8").splitlines() if l.strip()]) == 1)
        check("a non-research session writes no workspace manifests",
              not (outside / ".sessions").exists(), "")

        # 6. A research cwd alone (no ticket, no command) still journals.
        run("s3", research / "second-study")
        rows = journal_rows()
        check("a research-cwd session journals",
              len([r for r in rows if isinstance(r, dict)]) == 2, repr(rows))

        # 7. The last-user snippet is capped at 280 characters.
        long_text = "x" * 400
        long_transcript = tmp / "long.jsonl"
        long_transcript.write_text(json.dumps(
            {"type": "user", "timestamp": "2026-11-09T11:00:00.000Z",
             "message": {"role": "user", "content": long_text}}) + "\n", encoding="utf-8")
        handle_event({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                      "transcript_path": str(long_transcript), "session_id": "s4"},
                     config=config, state_dir=state, environ={}, home=HOME,
                     commands_dir=commands, now="2026-11-09T12:05:00-05:00")
        rows = journal_rows()
        row4 = [r for r in rows if isinstance(r, dict) and r.get("session_id") == "s4"]
        check("the snippet is capped at 280 characters",
              bool(row4) and len(row4[0].get("last_user_snippet", "")) == 280,
              repr(len(row4[0].get("last_user_snippet", "")) if row4 else -1))

        # 8. Wrong event names and missing session ids are silent.
        check("a non-SessionEnd event writes nothing",
              handle_event({"hook_event_name": "SessionStart", "cwd": str(workspace),
                            "session_id": "s9"}, config=config, state_dir=state,
                           environ={}, home=HOME) .get("research") is False, "")
        check("a missing session id writes nothing",
              handle_event({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                            "transcript_path": str(transcript)},
                           config=config, state_dir=state, environ={}, home=HOME,
                           commands_dir=commands)["row_written"] is False, "")

        # 9. Stop behaves like SessionEnd for the row upsert, and the
        # Stop -> SessionEnd double fire stays one row with one summary.
        def dict_rows():
            return [r for r in journal_rows() if isinstance(r, dict)]

        def buffer_count():
            return len([line for line in analytics_common.buffer_path(state)
                        .read_text(encoding="utf-8").splitlines() if line.strip()])

        summary = run("s10", workspace, name="Stop",
                      now="2026-11-09T12:10:00-05:00")
        check("a Stop fire journals the session",
              summary.get("row_written") is True and summary.get("row_is_new") is True,
              repr(summary))
        check("a Stop fire writes no workspace manifests",
              not (workspace / ".sessions" / "2026-11-09T12-10-00-05-00.json").exists(), "")
        rows_after_stop = buffer_count()
        check("a Stop fire emits the session summary once",
              rows_after_stop == 4, repr(rows_after_stop))
        run("s10", workspace, name="Stop", now="2026-11-09T12:11:00-05:00")
        kept = [r for r in dict_rows() if r.get("session_id") == "s10"]
        check("repeated Stop fires keep one row",
              len(kept) == 1, repr(len(kept)))
        check("the repeated Stop fire refreshes ended_at in place",
              kept and kept[0].get("ended_at") == "2026-11-09T12:11:00-05:00",
              repr(kept[0].get("ended_at") if kept else None))
        check("the repeated Stop fire emits no duplicate analytics",
              buffer_count() == rows_after_stop, repr(buffer_count()))
        summary = run("s10", workspace, name="SessionEnd",
                      now="2026-11-09T12:12:00-05:00")
        kept = [r for r in dict_rows() if r.get("session_id") == "s10"]
        check("the Stop then SessionEnd double fire still holds one row",
              summary.get("row_is_new") is False and len(kept) == 1,
              repr((summary, len(kept))))
        check("the double fire adds no duplicate analytics",
              buffer_count() == rows_after_stop, repr(buffer_count()))
        check("SessionEnd alone writes the workspace manifests",
              (workspace / ".sessions" / "2026-11-09T12-12-00-05-00.json").exists(), "")
        edges = [json.loads(line) for line in
                 (workspace / ".sessions" / "provenance.jsonl")
                 .read_text(encoding="utf-8").splitlines() if line.strip()]
        check("the double fire appends the edge set once",
              len([e for e in edges if e.get("session_id") == "s10"]) == 3,
              repr(len([e for e in edges if e.get("session_id") == "s10"])))
        check("an unrelated event name is silent",
              handle_event({"hook_event_name": "PreToolUse", "cwd": str(workspace),
                            "session_id": "s11"}, config=config, state_dir=state,
                           environ={}, home=HOME).get("row_written") is False, "")

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
