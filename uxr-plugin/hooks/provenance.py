#!/usr/bin/env python3
"""Provenance: which sources a session read, which outputs it wrote (issue 09).

Library for ``hooks/session_logger.py`` and the ``trace`` command. One
``TranscriptWalk`` pass over a transcript JSONL collects:

- ``sources``: things the session read. Source ids: ``drive:<fileId>``,
  ``drive:search:<hash12>``, ``<tracker-prefix>:<KEY>`` (the prefix is
  ``tracker.kind``, renamed per tracker), ``confluence:<pageId>``,
  ``slack:search:<hash12>``, ``wisdom:query:<hash12>``, ``web:<hash12>``,
  and ``file:<path>``. Types: drive, tracker, wiki, chat, feedback,
  notebook, mail, calendar, web, local_file. Paths under ``~/.claude/``
  and ``/tmp/`` are never sources.
- ``outputs``: ``file_edit``, ``tracker_edit``, ``tracker_create``. Each
  output records ``informed_by``: every source id read earlier in the same
  session. This is a session audit trail, not proof that one source caused
  one claim.
- ``files_read``: local paths the session read.
- ``relationships``: one edge per output x source pair, ``informed_by``.
- ``tool_failures``: a failed result whose text contains "doesn't want to
  proceed", "user rejected", or "declined" is a ``user_rejection``; any
  other failure is a ``tool_error``.

Tool calls are classified by the MCP operation name, the part after the
last ``__`` in the tool name: server ids can be UUIDs that change, so the
server keyword decides first and the operation name's keyword decides
when the server is a UUID. ``hash12`` is the first 12 hex characters of
the SHA-256 of the query text, so a repeated query keeps one source id.

Workspace manifests (written by :func:`write_workspace_manifests`, best
effort, under file locks):

- ``<workspace>/.sessions/<ended_at, colons to hyphens>.json`` -- the
  per-session record.
- ``<workspace>/.sessions/provenance.jsonl`` -- one line per edge:
  ``timestamp``, ``session_id``, ``relationship: "informed_by"``,
  ``output``, ``output_type``, ``output_url``, ``source_id``,
  ``source_url``.
- ``<workspace>/.sessions/sources-index.json`` -- sources deduped by id
  with ``first_seen``, ``last_seen``, and ``times_consulted`` (a mapping
  ``id -> {type, first_seen, last_seen, times_consulted}``).

Usage::


The file is also wired on ``Stop`` (hooks/hooks.json): a runtime pipes the
event JSON to stdin and the hook exits 0 silently -- the transcript walk
itself runs inside ``hooks/session_logger.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.util import (
    find_workspace,
    load_config as _load_config,
    resolve as _resolve,
    utcnow as _utcnow,
)  # noqa: E402  (shared plumbing)

SESSIONS_DIRNAME = ".sessions"
PROVENANCE_FILE = "provenance.jsonl"
SOURCES_INDEX_FILE = "sources-index.json"
OVERVIEW_MARKER = "00-overview.md"

#: Generic ticket key shape when ``tracker.ticket_regex`` is unusable.
FALLBACK_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")

#: Rejection phrases; a failed tool result holding one is a user rejection.
REJECTION_PHRASES = ("doesn't want to proceed", "user rejected", "declined")

#: Built-in tools that read a local file or the web, by tool name.
LOCAL_READ_TOOLS = ("Read",)
WEB_TOOLS = {"WebFetch": "url", "WebSearch": "query"}
#: Built-in tools that write or edit a file, mapped to their path input key.
EDIT_TOOLS = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}

#: Server-name keyword -> provenance type, checked in order.
SERVER_KEYWORDS = (
    ("drive", "drive"),
    ("confluence", "wiki"),
    ("slack", "chat"),
    ("wisdom", "feedback"),
    ("calendar", "calendar"),
    ("gmail", "mail"),
    ("mail", "mail"),
    ("notebook", "notebook"),
)
#: Operation-name keyword -> provenance type, for UUID-named servers.
OPERATION_KEYWORDS = (
    ("jira", "tracker"),
    ("linear", "tracker"),
    ("issue", "tracker"),
    ("ticket", "tracker"),
    ("drive", "drive"),
    ("confluence", "wiki"),
    ("slack", "chat"),
    ("wisdom", "feedback"),
    ("calendar", "calendar"),
    ("gmail", "mail"),
    ("mail", "mail"),
    ("notebook", "notebook"),
)
#: Exact server names that are tracker operations.
TRACKER_SERVERS = {"jira", "linear", "github", "asana"}

#: Source id prefixes per type (tracker uses ``tracker.kind`` instead).
ID_PREFIX = {
    "drive": "drive",
    "wiki": "confluence",
    "chat": "slack",
    "feedback": "wisdom",
    "mail": "mail",
    "calendar": "calendar",
    "notebook": "notebook",
    "web": "web",
    "local_file": "file",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def hash12(text: str) -> str:
    """First 12 hex characters of the SHA-256 of ``text`` (UTF-8)."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def strip_anchors(pattern: str) -> str:
    """Drop one leading ``^`` and one trailing ``$`` from a regex string.

    ``tracker.ticket_regex`` doubles as a full-match validator in the
    commands and a free-text search pattern in the hooks; an anchored
    validator shape (``^UXR-[0-9]+$``) never matches inside a longer
    sentence, so the hooks search with the anchors stripped.
    """
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1]
    return pattern


def ticket_regex(config: dict | None):
    """Compile ``tracker.ticket_regex`` for search use; fall back to the generic pattern.

    The hooks search free text (user messages, tool results), so one
    leading ``^`` and one trailing ``$`` are stripped before compiling
    (F3): the documented validator shape ``^UXR-[0-9]+$`` is a full-match
    check and would otherwise match nothing mid-sentence, leaving
    ``ticket_keys`` empty. Full-match validation in the commands keeps
    the configured pattern unchanged.
    """
    pattern = ""
    if config and isinstance(config.get("tracker"), dict):
        pattern = str(config["tracker"].get("ticket_regex") or "").strip()
    pattern = strip_anchors(pattern)
    if pattern:
        with contextlib.suppress(re.error):
            return re.compile(pattern)
    return FALLBACK_KEY_RE


def tracker_prefix(config: dict | None) -> str:
    """Source-id prefix for tracker items: ``tracker.kind`` or ``jira``."""
    kind = ""
    if config and isinstance(config.get("tracker"), dict):
        kind = str(config["tracker"].get("kind") or "").strip().lower()
    return kind or "jira"


def _first_query(tool_input: dict) -> str:
    """The query-ish text of a tool input, else a stable dump of the input."""
    for key in ("query", "q", "search", "text", "jql", "cql", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        return json.dumps(tool_input, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(tool_input)


def _input_id(tool_input: dict) -> str:
    """First id-ish value of a tool input, else empty."""
    for key in ("file_id", "fileId", "page_id", "pageId", "id", "key",
                "issue_key", "issueId", "issue_id", "message_id", "event_id",
                "channel_id", "channel"):
        value = tool_input.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def is_excluded_path(path, home=None) -> bool:
    """True for paths under ``~/.claude/`` or ``/tmp/``; they are never sources."""
    home = Path(home) if home is not None else Path.home()
    raw = Path(str(path)).expanduser().as_posix()
    if raw == "/tmp" or raw.startswith("/tmp/"):
        return True
    try:
        resolved = _resolve(path)
        claude = _resolve(home / ".claude")
        if resolved == claude or claude in resolved.parents:
            return True
        posix = resolved.as_posix()
    except (OSError, ValueError):
        return False
    return posix == "/tmp" or posix.startswith("/tmp/")


@contextlib.contextmanager
def file_lock(path, timeout: float = 5.0, stale_after: float = 10.0):
    """Best-effort exclusive lock file; yields ``True`` when acquired.

    A lock older than ``stale_after`` seconds is treated as crashed and
    removed. On timeout the caller proceeds unlocked (hooks fail open);
    writes stay atomic through temporary-file replacement either way.
    """
    lock_path = Path(path)
    with contextlib.suppress(OSError):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > stale_after:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
        except OSError:
            break
    try:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.write(fd, str(os.getpid()).encode())
        yield fd is not None
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(OSError):
                lock_path.unlink(missing_ok=True)


def _atomic_write(path: Path, text: str) -> bool:
    """Replace ``path`` with ``text`` via a temporary file; True when written."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, str(path))
        return True
    except OSError:
        with contextlib.suppress(OSError):
            for leftover in path.parent.glob(f"{path.name}*.tmp"):
                leftover.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# tool call classification
# ---------------------------------------------------------------------------


def split_tool_name(tool_name: str) -> tuple[str, str] | None:
    """``mcp__<server>__<op>`` -> ``(server, op)``; None for other names.

    The operation is the part after the last ``__``: a server id can be a
    UUID that changes between installs, so only the operation segment is
    treated as stable.
    """
    if not tool_name.startswith("mcp__") or "__" not in tool_name[5:]:
        return None
    parts = tool_name.split("__")
    return parts[1], parts[-1]


def classify_tool(tool_name: str, config: dict | None = None) -> tuple[str | None, str]:
    """Return ``(provenance type, operation)``; type None when not a source tool."""
    parts = split_tool_name(tool_name)
    if parts is None:
        return None, tool_name
    server, op = parts
    server_l = server.lower()
    op_l = op.lower()
    if server_l in TRACKER_SERVERS or server_l == tracker_prefix(config):
        return "tracker", op
    for keyword, kind in SERVER_KEYWORDS:
        if keyword in server_l:
            return kind, op
    for keyword, kind in OPERATION_KEYWORDS:
        if keyword in op_l:
            return kind, op
    return None, op_l


def _tracker_write_kind(op_l: str) -> str | None:
    """``tracker_create`` / ``tracker_edit`` for write-ish tracker operations."""
    if "create" in op_l:
        return "tracker_create"
    for word in ("update", "edit", "transition", "assign", "comment"):
        if word in op_l:
            return "tracker_edit"
    return None


def source_id_for(kind: str, op_l: str, tool_input: dict,
                  config: dict | None = None) -> str | None:
    """The source id for one read-style tool call, or None when not a source."""
    if kind == "tracker":
        prefix = tracker_prefix(config)
        if "search" in op_l:
            return f"{prefix}:search:{hash12(_first_query(tool_input))}"
        key = _input_id(tool_input)
        return f"{prefix}:{key}" if key else None
    prefix = ID_PREFIX.get(kind, kind)
    if kind == "web":
        return f"web:{hash12(_first_query(tool_input))}"
    if kind == "feedback" and ("query" in op_l or "search" in op_l):
        return f"wisdom:query:{hash12(_first_query(tool_input))}"
    if "search" in op_l:
        return f"{prefix}:search:{hash12(_first_query(tool_input))}"
    key = _input_id(tool_input)
    if key:
        return f"{prefix}:{key}"
    return f"{prefix}:search:{hash12(_first_query(tool_input))}"


def failure_kind(result_text: str) -> str:
    """``user_rejection`` when the text carries a rejection phrase, else ``tool_error``."""
    text_l = str(result_text).lower()
    for phrase in REJECTION_PHRASES:
        if phrase in text_l:
            return "user_rejection"
    return "tool_error"


# ---------------------------------------------------------------------------
# the single-pass transcript walk
# ---------------------------------------------------------------------------


class TranscriptWalk:
    """One pass over transcript JSONL lines, collecting provenance.

    ``feed(obj)`` consumes one parsed transcript line and returns the list
    of events it produced, so a caller (``session_logger``) collects its
    own statistics during the same single walk:

    - ``("user", text, timestamp)`` -- one user-authored text message
      (never a tool result, never a meta line);
    - ``("tool", tool_name, operation, tool_input, timestamp)`` -- one
      tool call, one event per ``tool_use`` block.
    """

    def __init__(self, config: dict | None = None, home=None) -> None:
        self.config = config
        self.home = home if home is not None else Path.home()
        self.sources: dict[str, dict] = {}
        self.source_order: list[str] = []
        self.outputs: list[dict] = []
        self.files_read: list[str] = []
        self.tool_failures: list[dict] = []
        self._pending: dict[str, dict] = {}  # tool_use_id -> call record

    # -- feeding -----------------------------------------------------------

    def feed(self, obj) -> list[tuple]:
        """Consume one parsed transcript line; return its event tuples."""
        if not isinstance(obj, dict):
            return []
        kind = obj.get("type")
        message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        content = message.get("content")
        timestamp = str(obj.get("timestamp") or "")
        if kind == "user":
            return self._feed_user(content, timestamp, obj)
        if kind == "assistant":
            return self._feed_assistant(content, timestamp)
        return []

    def _text_parts(self, content) -> tuple[str, list[dict]]:
        """Split message content into ``(joined text, tool_result blocks)``."""
        if isinstance(content, str):
            return content, []
        texts: list[str] = []
        blocks: list[dict] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    texts.append(block["text"])
                elif block.get("type") == "tool_result":
                    blocks.append(block)
        return "\n".join(texts), blocks

    def _feed_user(self, content, timestamp: str, obj: dict) -> list[tuple]:
        if obj.get("isMeta"):
            return []
        text, blocks = self._text_parts(content)
        if blocks:
            for block in blocks:
                self._feed_result(block, timestamp)
            return []
        text = text.strip()
        if not text:
            return []
        return [("user", text, timestamp)]

    def _feed_assistant(self, content, timestamp: str) -> list[tuple]:
        events: list[tuple] = []
        if not isinstance(content, list):
            return events
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                event = self._feed_tool_use(block, timestamp)
                if event is not None:
                    events.append(event)
        return events

    def _feed_tool_use(self, block: dict, timestamp: str) -> tuple | None:
        tool_name = str(block.get("name") or "")
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        call_id = str(block.get("id") or "")
        kind, op = classify_tool(tool_name, self.config)
        op_l = op.lower()
        self._pending[call_id] = {
            "tool_name": tool_name, "kind": kind, "op_l": op_l,
            "input": tool_input, "timestamp": timestamp,
        }
        # A read that is a source.
        source_id = None
        if kind:
            source_id = source_id_for(kind, op_l, tool_input, self.config)
        elif tool_name in LOCAL_READ_TOOLS:
            path = str(tool_input.get("file_path") or "")
            if path and not is_excluded_path(path, home=self.home):
                source_id = f"file:{path}"
                kind = "local_file"
        elif tool_name in WEB_TOOLS:
            source_id = f"web:{hash12(_first_query(tool_input))}"
            kind = "web"
        if source_id:
            self._add_source(source_id, kind, tool_input, timestamp)
        # An output: file edits now; tracker writes finalize on the result.
        if tool_name in EDIT_TOOLS:
            path = str(tool_input.get(EDIT_TOOLS[tool_name]) or "")
            if path:
                self._add_output({
                    "type": "file_edit", "id": path, "path": path,
                    "tool_use_id": call_id, "url": "",
                    "informed_by": list(self.source_order),
                }, timestamp)
        elif kind == "tracker":
            write_kind = _tracker_write_kind(op_l)
            if write_kind:
                self._add_output({
                    "type": write_kind, "id": _input_id(tool_input) or None,
                    "path": "", "tool_use_id": call_id, "url": "",
                    "informed_by": list(self.source_order),
                }, timestamp)
        return ("tool", tool_name, op, tool_input, timestamp)

    def _add_source(self, source_id: str, kind: str, tool_input: dict,
                    timestamp: str) -> None:
        url = ""
        label = ""
        if kind == "web":
            url = _first_query(tool_input)
            label = url
        elif source_id.startswith("file:"):
            path = source_id[5:]
            url = path
            label = path
        else:
            label = _input_id(tool_input) or _first_query(tool_input)
        if source_id not in self.sources:
            self.sources[source_id] = {
                "id": source_id, "type": kind or "", "label": label[:200],
                "url": url, "first_read_at": timestamp,
            }
            self.source_order.append(source_id)
        if kind == "local_file":
            path = source_id[5:]
            if path not in self.files_read:
                self.files_read.append(path)

    def _add_output(self, output: dict, timestamp: str) -> None:
        self.outputs.append({**output, "timestamp": timestamp})

    def _finalize_tracker_output(self, call_id: str, result_text: str) -> None:
        """Fill a tracker output id from the result text when the input had none."""
        regex = ticket_regex(self.config)
        for output in self.outputs:
            if output.get("tool_use_id") == call_id and not output.get("id"):
                match = regex.search(result_text)
                if match:
                    output["id"] = match.group(0)

    def _feed_result(self, block: dict, timestamp: str) -> None:
        call_id = str(block.get("tool_use_id") or "")
        record = self._pending.get(call_id)
        content = block.get("content")
        if isinstance(content, str):
            result_text = content
        else:
            texts = []
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
            result_text = "\n".join(texts)
        is_error = bool(block.get("is_error")) or bool(block.get("isError"))
        if record is not None:
            if is_error:
                self.tool_failures.append({
                    "tool": record["tool_name"], "kind": failure_kind(result_text),
                    "timestamp": timestamp,
                })
            if record["kind"] == "tracker":
                self._finalize_tracker_output(call_id, result_text)
            self._pending.pop(call_id, None)

    # -- results -----------------------------------------------------------

    def result(self, research_dirs=None) -> dict:
        """The provenance record: sources, outputs, files_read, relationships,
        tool_failures. ``research_dirs`` tags local files inside research dirs."""
        roots = [_resolve(r) for r in (research_dirs or []) if str(r).strip()]
        sources = []
        for source_id in self.source_order:
            source = dict(self.sources[source_id])
            if source_id.startswith("file:") and roots:
                path = _resolve(source_id[5:])
                source["in_research"] = any(
                    path == root or root in path.parents for root in roots
                )
            sources.append(source)
        relationships = []
        for output in self.outputs:
            for source_id in output.get("informed_by", []):
                relationships.append({
                    "relationship": "informed_by",
                    "output": output.get("id") or output.get("path") or "",
                    "output_type": output["type"],
                    "source_id": source_id,
                })
        return {
            "sources": sources,
            "outputs": [
                {
                    "type": o["type"], "id": o.get("id") or o.get("path") or "",
                    "path": o.get("path", ""), "url": o.get("url", ""),
                    "informed_by": o.get("informed_by", []),
                    "timestamp": o.get("timestamp", ""),
                }
                for o in self.outputs
            ],
            "files_read": list(self.files_read),
            "relationships": relationships,
            "tool_failures": list(self.tool_failures),
        }


# ---------------------------------------------------------------------------
# workspace manifests
# ---------------------------------------------------------------------------


def session_manifest_path(workspace, ended_at: str) -> Path:
    """``<workspace>/.sessions/<ended_at, colons to hyphens>.json``."""
    return Path(workspace) / SESSIONS_DIRNAME / f"{str(ended_at).replace(':', '-')}.json"


def append_provenance_edges(workspace, edges: list[dict]) -> bool:
    """Append one JSON line per edge to ``<workspace>/.sessions/provenance.jsonl``.

    Each edge must already carry ``timestamp``, ``session_id``,
    ``relationship``, ``output``, ``output_type``, ``output_url``,
    ``source_id``, and ``source_url``. Best effort under a file lock.
    """
    if not edges:
        return False
    path = Path(workspace) / SESSIONS_DIRNAME / PROVENANCE_FILE
    lines = "".join(
        json.dumps(edge, ensure_ascii=False, sort_keys=True) + "\n" for edge in edges
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.parent / "provenance.jsonl.lock"):
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(lines)
        return True
    except OSError:
        return False


def update_sources_index(workspace, sources: list[dict], now: str | None = None) -> bool:
    """Merge sources into ``sources-index.json``, deduped by id.

    Each entry keeps ``first_seen``, updates ``last_seen``, and bumps
    ``times_consulted``. The file is a mapping ``id -> entry``. Best effort
    under a file lock.
    """
    if not sources:
        return False
    path = Path(workspace) / SESSIONS_DIRNAME / SOURCES_INDEX_FILE
    stamp = now or _utcnow()
    index: dict = {}
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                index = loaded
    except (OSError, ValueError):
        index = {}
    for source in sources:
        entry = index.get(source["id"])
        if isinstance(entry, dict):
            entry["last_seen"] = stamp
            try:
                entry["times_consulted"] = int(entry.get("times_consulted", 0)) + 1
            except (TypeError, ValueError):
                entry["times_consulted"] = 1
        else:
            index[source["id"]] = {
                "type": source.get("type", ""),
                "first_seen": stamp,
                "last_seen": stamp,
                "times_consulted": 1,
            }
    text = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.parent / "sources-index.json.lock"):
            return _atomic_write(path, text)
    except OSError:
        return False


def write_workspace_manifests(workspace, record: dict, provenance: dict,
                              config: dict | None = None) -> dict:
    """Write the session record, the provenance edges, and the sources index.

    Returns the paths that were written (entries are missing when a write
    failed or had nothing to write). Best effort: never raises.
    """
    written: dict[str, str] = {}
    base_url = ""
    prefix = tracker_prefix(config)
    if config and isinstance(config.get("tracker"), dict):
        base_url = str(config["tracker"].get("base_url") or "").strip().rstrip("/")
    session_id = str(record.get("session_id") or "")
    ended_at = str(record.get("ended_at") or _utcnow())
    try:
        manifest = session_manifest_path(workspace, ended_at)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written["session_record"] = str(manifest)
    except OSError:
        pass

    source_url_by_id = {s["id"]: str(s.get("url") or "") for s in provenance.get("sources", [])}
    edges = []
    for edge in provenance.get("relationships", []):
        output_id = str(edge.get("output") or "")
        output_type = str(edge.get("output_type") or "")
        output_url = ""
        if output_type in ("tracker_edit", "tracker_create") and output_id and base_url \
                and prefix == "jira":
            output_url = f"{base_url}/browse/{output_id}"
        edges.append({
            "timestamp": ended_at,
            "session_id": session_id,
            "relationship": "informed_by",
            "output": output_id,
            "output_type": output_type,
            "output_url": output_url,
            "source_id": edge.get("source_id", ""),
            "source_url": source_url_by_id.get(edge.get("source_id", ""), ""),
        })
    if edges and append_provenance_edges(workspace, edges):
        written["provenance"] = str(Path(workspace) / SESSIONS_DIRNAME / PROVENANCE_FILE)
    if update_sources_index(workspace, provenance.get("sources", []), now=ended_at):
        written["sources_index"] = str(
            Path(workspace) / SESSIONS_DIRNAME / SOURCES_INDEX_FILE)
    return written


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def stdin_names_hook_event(stream) -> bool:
    """True when piped stdin carries a hook event payload.

    A runtime invokes this file as a hook with the event JSON on stdin;
    a TTY or an empty pipe stays CLI mode. Never raises.
    """
    try:
        if stream is None or stream.isatty():
            return False
        return "hook_event_name" in stream.read()
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    if stdin_names_hook_event(sys.stdin):
        return 0  # wired on Stop (hooks/hooks.json): the walk lives in session_logger.py
    print(__doc__.strip().splitlines()[0])  # terse CLI pointer; full doc in this file
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
