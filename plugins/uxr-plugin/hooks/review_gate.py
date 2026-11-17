#!/usr/bin/env python3
"""HCD review gate: reminder hook for research artifacts (issue 06).

Wired for two events (see ``hooks/hooks.json``):

- **SubagentStop** for the ``hcd-researcher`` review agent: write the
  per-study marker ``<workspace>/.sessions/hcd-review-<KEY>.json`` with
  ``ran_at``, ``agent_id``, and ``session_id``. **Stop** is accepted as
  the same marker check (the turn-end event runtimes without
  SubagentStop do support, e.g. ZCode 0.17.1): it scans the transcript
  tail, and a Stop fire never overwrites a marker that a SubagentStop
  wrote with a real agent id.
- **PreToolUse** for Write or Edit on a reviewable path (under
  ``deliverables/``, ``scripts/``, ``analysis/``, or a numbered root file
  like ``09-findings.md``; never ``README.md``, ``00-overview.md``,
  ``interviews/``, ``sources/``, ``recruitment/``): when no marker exists
  for the study and this session has not been reminded for it yet, print
  ONE reminder as a ``systemMessage`` plus ``additionalContext``. The hook
  never sets a permission decision and never blocks a write. One reminder
  per session per study. Opt out entirely with
  ``~/.claude/.uxr-hcd-gate-off``.

The marker proves the agent ran on the study; it does not prove its
findings were used. The reminder text says so.

Study and key resolution: the workspace is the event ``cwd`` or its
nearest ancestor holding ``.sessions/`` or ``00-overview.md``; the key is
the first ``tracker.ticket_regex`` match on the workspace's
``00-overview.md`` ``Ticket:`` line, else the workspace directory name.

Hook contract (all hooks in this plugin):

1. Read the event JSON from stdin.
2. Catch every exception. Exit 0 on any error.
3. Print nothing unless the event contract asks for output.

Usage::

    python hooks/review_gate.py selftest     # run the self-test
    python hooks/review_gate.py --selftest   # same, flag form
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

AGENT_NAME = "hcd-researcher"
OVERVIEW_MARKER = "00-overview.md"
SESSIONS_DIRNAME = ".sessions"
MARKER_TEMPLATE = "hcd-review-{key}.json"
STATE_FILENAME = "hcd-gate-state.json"
OPT_OUT_ENV = "UXR_HCD_GATE_OFF"
#: Fall back pattern when ``tracker.ticket_regex`` is unset or config is
#: unreadable. Generic tracker key shape: letters and digits, a hyphen, a number.
FALLBACK_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
TICKET_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?Ticket(?:s)?(?:\*\*)?\s*[:=]\s*(.+)$", re.MULTILINE)

#: Prefixes (relative to the workspace root) that are reviewable.
REVIEWABLE_DIRS = ("deliverables", "scripts", "analysis")
#: Prefixes and names that are never reviewable, whatever else matches.
NEVER_REVIEWABLE_DIRS = ("interviews", "sources", "recruitment", ".sessions", ".git", ".claude", "node_modules")
NEVER_REVIEWABLE_FILES = ("README.md", OVERVIEW_MARKER, "CLAUDE.md")
#: Root-level reviewable artifacts: numbered research files like 09-findings.md.
ROOT_ARTIFACT_RE = re.compile(r"^\d{2}[-_.].+\.md$")

REMINDER_TEXT = (
    "HCD review gate: no hcd-researcher review marker exists for this study yet. "
    "Dispatch the hcd-researcher agent on the artifact before it hardens, or record "
    "a one-line decline. The marker (.sessions/hcd-review-<KEY>.json) proves the "
    "agent ran on the study; it does not prove the findings were used."
)

#: How much transcript tail to scan for the agent name, in bytes.
TRANSCRIPT_SCAN_BYTES = 262_144


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    """ISO 8601 UTC time with a ``Z`` suffix, second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _ticket_regex(config: dict | None):
    """Compile ``tracker.ticket_regex``; fall back to the generic pattern."""
    pattern = ""
    if config and isinstance(config.get("tracker"), dict):
        pattern = str(config["tracker"].get("ticket_regex") or "").strip()
    if pattern:
        try:
            return re.compile(pattern)
        except re.error:
            pass
    return FALLBACK_KEY_RE


def find_workspace(cwd) -> Path | None:
    """The cwd, or its nearest ancestor, holding ``.sessions/`` or ``00-overview.md``."""
    real = _resolve(cwd)
    if (real / SESSIONS_DIRNAME).is_dir() or (real / OVERVIEW_MARKER).is_file():
        return real
    for parent in real.parents:
        if (parent / SESSIONS_DIRNAME).is_dir() or (parent / OVERVIEW_MARKER).is_file():
            return parent
    return None


def _overview_text(workspace: Path) -> str:
    """Read the workspace's 00-overview.md; empty string when absent."""
    try:
        return (workspace / OVERVIEW_MARKER).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def study_key(workspace: Path, config: dict | None = None) -> str:
    """Ticket key from the overview's Ticket line, else the workspace name."""
    regex = _ticket_regex(config)
    text = _overview_text(workspace)
    line = ""
    match = TICKET_LINE_RE.search(text)
    if match:
        line = match.group(1)
    key_match = regex.search(line) if line else None
    if not key_match:
        key_match = regex.search(text)
    if key_match:
        return key_match.group(0)
    # Fall back to the workspace directory name, sanitized for a filename.
    name = workspace.name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return sanitized or "study"


# ---------------------------------------------------------------------------
# reviewable path check
# ---------------------------------------------------------------------------


def is_reviewable(file_path, workspace) -> bool:
    """True when the Write/Edit target is a reviewable artifact path."""
    try:
        target = _resolve(file_path)
        root = _resolve(workspace)
        relative = target.relative_to(root).as_posix()
    except (ValueError, OSError):
        return False
    parts = relative.split("/")
    head = parts[0]
    if relative in NEVER_REVIEWABLE_FILES or head in NEVER_REVIEWABLE_DIRS:
        return False
    if head in REVIEWABLE_DIRS:
        return True
    # A root-level numbered research artifact, e.g. 09-findings.md.
    return len(parts) == 1 and bool(ROOT_ARTIFACT_RE.match(head))


# ---------------------------------------------------------------------------
# marker and per-session reminder state
# ---------------------------------------------------------------------------


def marker_path(workspace: Path, key: str) -> Path:
    return workspace / SESSIONS_DIRNAME / MARKER_TEMPLATE.format(key=key)


def marker_exists(workspace: Path, key: str) -> bool:
    try:
        return marker_path(workspace, key).is_file()
    except OSError:
        return False


def write_marker(workspace: Path, key: str, agent_id: str, session_id: str) -> bool:
    """Write the hcd-review marker; best effort, returns True when written."""
    path = marker_path(workspace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "ran_at": _utcnow(),
                    "agent_id": agent_id,
                    "session_id": session_id,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def reminded_this_session(workspace: Path, key: str, session_id: str) -> bool:
    """True when this session already received the reminder for this study."""
    if not session_id:
        return False
    state = _load_state(workspace / SESSIONS_DIRNAME / STATE_FILENAME)
    studies = state.get("studies")
    if not isinstance(studies, dict):
        return False
    entry = studies.get(key)
    if not isinstance(entry, dict):
        return False
    sessions = entry.get("sessions")
    return isinstance(sessions, dict) and session_id in sessions


def record_reminder(workspace: Path, key: str, session_id: str) -> None:
    """Persist the per-session reminder; prunes sessions beyond the newest few."""
    if not session_id:
        return
    path = workspace / SESSIONS_DIRNAME / STATE_FILENAME
    state = _load_state(path)
    studies = state.get("studies") if isinstance(state.get("studies"), dict) else {}
    entry = studies.get(key) if isinstance(studies.get(key), dict) else {}
    sessions = entry.get("sessions") if isinstance(entry.get("sessions"), dict) else {}
    sessions.pop(session_id, None)
    sessions[session_id] = _utcnow()
    # Keep the state file small: at most 5 sessions per study, 20 studies.
    while len(sessions) > 5:
        oldest = min(sessions, key=sessions.get)
        sessions.pop(oldest)
    entry["sessions"] = sessions
    entry["reminded_at"] = _utcnow()
    studies.pop(key, None)
    studies[key] = entry
    while len(studies) > 20:
        oldest = min(studies, key=lambda k: str(studies[k].get("reminded_at") or ""))
        studies.pop(oldest)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"studies": studies}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# SubagentStop: did hcd-researcher run?
# ---------------------------------------------------------------------------


def _explicit_agent_name(event: dict) -> str:
    """The event's explicit agent name, or empty string when it has none."""
    for field in ("agent_type", "agent_name", "agent"):
        value = str(event.get(field) or "").strip()
        if value:
            return value
    return ""


def _transcript_names_agent(transcript_path) -> bool:
    """Scan the transcript tail for a dispatch naming the agent."""
    if not transcript_path:
        return False
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TRANSCRIPT_SCAN_BYTES))
            tail = handle.read(TRANSCRIPT_SCAN_BYTES)
    except OSError:
        return False
    return AGENT_NAME.encode("utf-8") in tail


def subagent_ran(event: dict) -> bool:
    """True when this SubagentStop belongs to the hcd-researcher agent.

    An explicit agent name decides on its own: another agent's name never
    falls through to the transcript scan, even if the session dispatched
    hcd-researcher earlier. Only an event with no agent name scans the
    transcript tail for the dispatch.
    """
    explicit = _explicit_agent_name(event)
    if explicit:
        return explicit == AGENT_NAME
    return _transcript_names_agent(event.get("transcript_path"))


# ---------------------------------------------------------------------------
# event handling
# ---------------------------------------------------------------------------


def gate_off(environ=None, home=None) -> bool:
    """True when the opt-out file (or env var) is present."""
    environ = os.environ if environ is None else environ
    if environ.get(OPT_OUT_ENV):
        return True
    try:
        base = Path(home) if home is not None else Path.home()
    except OSError:
        return False
    try:
        return (base / ".claude" / ".uxr-hcd-gate-off").is_file()
    except OSError:
        return False


def handle_subagent_stop(event: dict, config: dict | None = None, home=None) -> str:
    """Write the marker when hcd-researcher ran; always print nothing."""
    if not subagent_ran(event):
        return ""
    cwd = event.get("cwd") or os.getcwd()
    workspace = find_workspace(cwd)
    if workspace is None:
        return ""
    key = study_key(workspace, config)
    # A Stop fire (no explicit agent name) is the transcript-scan backstop
    # for runtimes without SubagentStop; it must never overwrite a marker
    # that a SubagentStop wrote with a real agent id.
    if not _explicit_agent_name(event) and marker_exists(workspace, key):
        return ""
    write_marker(
        workspace,
        key,
        agent_id=str(event.get("agent_id") or event.get("agent_type") or AGENT_NAME),
        session_id=str(event.get("session_id") or ""),
    )
    return ""


def handle_pre_tool_use(event: dict, config: dict | None = None, environ=None, home=None) -> str:
    """One reminder per session per study; never a permission decision."""
    tool_name = str(event.get("tool_name") or "")
    if tool_name not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ""
    tool_input = event.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not file_path:
        return ""
    cwd = event.get("cwd") or os.getcwd()
    workspace = find_workspace(cwd)
    if workspace is None or not is_reviewable(file_path, workspace):
        return ""
    if gate_off(environ=environ, home=home):
        return ""
    key = study_key(workspace, config)
    if marker_exists(workspace, key):
        return ""
    session_id = str(event.get("session_id") or "")
    if reminded_this_session(workspace, key, session_id):
        return ""
    record_reminder(workspace, key, session_id)
    payload = {
        "systemMessage": REMINDER_TEXT,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": REMINDER_TEXT,
        },
    }
    return json.dumps(payload)


def handle_event(event, config: dict | None = None, environ=None, home=None) -> str:
    """Return the stdout payload for one event (empty string = print nothing)."""
    try:
        if not isinstance(event, dict):
            return ""
        name = event.get("hook_event_name")
        if name in ("SubagentStop", "Stop"):
            return handle_subagent_stop(event, config=config, home=home)
        if name == "PreToolUse":
            return handle_pre_tool_use(event, config=config, environ=environ, home=home)
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def _selftest() -> int:
    """Cover the acceptance items: reminder shape, session silence, overview
    silence, marker silence, plus the opt-out and the never-list."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("hooks/review_gate.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        workspace = tmp / "research" / "admin-permissions-study"
        (workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (workspace / OVERVIEW_MARKER).write_text(
            "# Admin permissions study\n\nTicket: ABC-237\n", encoding="utf-8"
        )
        config = None

        def pre_event(path, session_id="s1", tool="Write"):
            return {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": str(path)},
                "cwd": str(workspace),
                "session_id": session_id,
            }

        def run(event, **kwargs):
            kwargs.setdefault("environ", {})
            kwargs.setdefault("home", HOME)
            return handle_event(event, config=config, **kwargs)

        deliverable = workspace / "deliverables" / "report.md"

        # 1. First write on a reviewable path: one reminder, correct shape.
        output = run(pre_event(deliverable))
        check("first reviewable write prints one reminder", bool(output), "output was empty")
        try:
            payload = json.loads(output)
        except ValueError:
            payload = {}
        check(
            "reminder carries systemMessage and additionalContext",
            bool(payload.get("systemMessage"))
            and isinstance(payload.get("hookSpecificOutput"), dict)
            and bool(payload["hookSpecificOutput"].get("additionalContext")),
            repr(output[:160]),
        )
        check(
            "reminder has no permissionDecision key",
            "permissionDecision" not in output and "permission_decision" not in output,
            "found a permission decision key",
        )
        check(
            "reminder text says what the marker proves and does not",
            "proves the agent ran" in output and "does not prove" in output,
            "reminder text missing the marker caveat",
        )
        state = _load_state(workspace / SESSIONS_DIRNAME / STATE_FILENAME)
        check(
            "reminder is recorded per session and study",
            bool(state.get("studies", {}).get("ABC-237", {}).get("sessions", {}).get("s1")),
            repr(state)[:160],
        )

        # 2. A second write in the same session is silent.
        check(
            "second write in the same session is silent",
            run(pre_event(deliverable, session_id="s1")) == "",
            "expected empty output",
        )

        # 3. 00-overview.md is never reviewable, even in a fresh session.
        check(
            "00-overview.md is silent",
            run(pre_event(workspace / OVERVIEW_MARKER, session_id="s2")) == "",
            "expected empty output",
        )
        for relative in ("README.md", "interviews/summary.md", "sources/index.md", "recruitment/plan.md"):
            check(
                f"{relative} is silent",
                run(pre_event(workspace / relative, session_id="s3")) == "",
                "expected empty output",
            )

        # 4. A numbered root artifact is reviewable for a new session.
        findings = workspace / "09-findings.md"
        output = run(pre_event(findings, session_id="s4"))
        check("numbered root artifact reminds in a new session", bool(output), "output was empty")

        # 5. SubagentStop writes the marker; then writes are silent forever.
        transcript = tmp / "transcript.jsonl"
        transcript.write_text(
            '{"type":"assistant"}\n{"tool":"Task","subagent_type":"hcd-researcher"}\n',
            encoding="utf-8",
        )
        stop_event = {
            "hook_event_name": "SubagentStop",
            "cwd": str(workspace),
            "session_id": "s5",
            "agent_id": "agent-9",
            "transcript_path": str(transcript),
        }
        check(
            "SubagentStop for hcd-researcher prints nothing",
            run(stop_event) == "",
            "expected empty output",
        )
        marker = marker_path(workspace, "ABC-237")
        marker_ok = False
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            marker_ok = (
                bool(data.get("ran_at"))
                and data.get("agent_id") == "agent-9"
                and data.get("session_id") == "s5"
            )
        except (OSError, ValueError):
            marker_ok = False
        check(
            "marker file holds ran_at, agent_id, session_id",
            marker_ok,
            f"marker at {marker}",
        )
        check(
            "after the marker the write is silent (fresh session)",
            run(pre_event(deliverable, session_id="s6")) == "",
            "expected empty output",
        )

        # 6. A different agent's SubagentStop writes no marker.
        other_workspace = tmp / "research" / "other-study"
        (other_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (other_workspace / OVERVIEW_MARKER).write_text("# Other\n\nTicket: ABC-300\n", encoding="utf-8")
        other_transcript = tmp / "other-transcript.jsonl"
        other_transcript.write_text('{"tool":"Task","subagent_type":"novice-participant"}\n', encoding="utf-8")
        before = marker_path(other_workspace, "ABC-300")
        check(
            "SubagentStop for another agent writes no marker",
            run(
                {
                    "hook_event_name": "SubagentStop",
                    "cwd": str(other_workspace),
                    "session_id": "s7",
                    "agent_type": "novice-participant",
                    "transcript_path": str(other_transcript),
                }
            )
            == ""
            and not before.is_file(),
            "marker written for the wrong agent",
        )

        # 7. The opt-out file silences every reminder.
        (HOME / ".claude" / ".uxr-hcd-gate-off").write_text("", encoding="utf-8")
        fresh_workspace = tmp / "research" / "fresh-study"
        (fresh_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (fresh_workspace / OVERVIEW_MARKER).write_text("# Fresh\n\nTicket: ABC-310\n", encoding="utf-8")
        check(
            "the opt-out file silences the reminder",
            run(
                pre_event(fresh_workspace / "deliverables" / "deck.md", session_id="s8"),
                home=HOME,
            )
            == "",
            "expected empty output",
        )
        (HOME / ".claude" / ".uxr-hcd-gate-off").unlink()

        # 8. Unknown events and malformed input print nothing.
        check(
            "SessionStart prints nothing",
            run({"hook_event_name": "SessionStart", "cwd": str(workspace)}) == "",
            "expected empty output",
        )
        check(
            "malformed event prints nothing",
            run({"hook_event_name": "PreToolUse"}) == "",
            "expected empty output",
        )

        # 9. Study key falls back to the workspace name when no ticket exists.
        keyless = tmp / "research" / "no ticket yet"
        (keyless / SESSIONS_DIRNAME).mkdir(parents=True)
        (keyless / OVERVIEW_MARKER).write_text("# Draft study\n", encoding="utf-8")
        check(
            "study key falls back to the workspace name",
            study_key(keyless, config) == "no-ticket-yet",
            study_key(keyless, config),
        )

        # 10. Stop is the marker-check backstop: it writes the marker when
        # none exists and never degrades one a SubagentStop wrote.
        marker_before = json.loads(marker.read_text(encoding="utf-8"))
        check(
            "a Stop fire after SubagentStop leaves the marker untouched",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(workspace),
                    "session_id": "s9",
                    "transcript_path": str(transcript),
                }
            )
            == ""
            and json.loads(marker.read_text(encoding="utf-8")) == marker_before,
            repr(marker.read_text(encoding="utf-8")),
        )
        stop_workspace = tmp / "research" / "stop-marker-study"
        (stop_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (stop_workspace / OVERVIEW_MARKER).write_text(
            "# Stop marker study\n\nTicket: ABC-401\n", encoding="utf-8"
        )
        check(
            "a Stop fire writes the marker when none exists",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(stop_workspace),
                    "session_id": "s10",
                    "transcript_path": str(transcript),
                }
            )
            == ""
            and marker_path(stop_workspace, "ABC-401").is_file(),
            "marker missing after Stop",
        )
        stop_marker = json.loads(
            marker_path(stop_workspace, "ABC-401").read_text(encoding="utf-8")
        )
        check(
            "the Stop-written marker carries the fallback agent id",
            stop_marker.get("agent_id") == AGENT_NAME
            and stop_marker.get("session_id") == "s10"
            and bool(stop_marker.get("ran_at")),
            repr(stop_marker),
        )
        quiet_transcript = tmp / "quiet-transcript.jsonl"
        quiet_transcript.write_text(
            '{"tool":"Task","subagent_type":"novice-participant"}\n', encoding="utf-8"
        )
        no_marker_workspace = tmp / "research" / "no-dispatch-study"
        (no_marker_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (no_marker_workspace / OVERVIEW_MARKER).write_text(
            "# No dispatch\n\nTicket: ABC-402\n", encoding="utf-8"
        )
        check(
            "a Stop fire without a dispatch names no marker",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(no_marker_workspace),
                    "session_id": "s11",
                    "transcript_path": str(quiet_transcript),
                }
            )
            == ""
            and not marker_path(no_marker_workspace, "ABC-402").is_file(),
            "marker written without a dispatch",
        )
        check(
            "unrelated events print nothing",
            run({"hook_event_name": "UserPromptSubmit", "cwd": str(workspace),
                 "prompt": "/uxr-eod", "session_id": "s12"})
            == ""
            and run({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                     "session_id": "s13"})
            == "",
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
