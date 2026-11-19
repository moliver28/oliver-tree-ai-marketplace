#!/usr/bin/env python3
"""Analytics plumbing shared by ``analytics.py`` and ``analytics_flush.py``.

Consent (issue 09): analytics run only when ``analytics.enabled`` is true
in the config, the file ``~/.claude/.uxr-analytics-off`` is absent,
``DO_NOT_TRACK`` is unset or false, and ``UXR_ANALYTICS`` is not ``off``.
Any error while checking consent means disabled -- collection is
opt-in, so a failure never turns it on.

Identity: a random salt file (mode 0600) lives in the state dir. Both
``uid`` and ``session_id`` in an event envelope are the first 12 hex
characters of ``sha256(salt|value)`` -- never the raw values, so the
analytics ids never join the journal (the journal keeps raw session ids).

Envelope: ``{"v": 1, "event", "ts", "session_id", "uid",
"plugin_version", ...}`` plus the event payload. The fields ``prompt``,
``text``, ``path``, ``file_path``, ``body``, and ``content`` are dropped
silently, at any depth. Only counts and names travel.

Buffer: one JSONL file per month, ``<state_dir>/events-YYYY-MM.jsonl``.
Flushing to the network happens only in ``analytics_flush.py``.

Usage::

    python hooks/analytics_common.py selftest     # run the self-test
    python hooks/analytics_common.py --selftest   # same, flag form
"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

SALT_FILE = "analytics-salt"
OFF_FILE = ".uxr-analytics-off"
ENV_ANALYTICS = "UXR_ANALYTICS"
ENV_DO_NOT_TRACK = "DO_NOT_TRACK"
ENV_STATE_DIR = "UXR_STATE_DIR"
#: Payload keys dropped silently from every event, at any depth.
SCRUB_KEYS = frozenset({"prompt", "text", "path", "file_path", "body", "content"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def resolve_state_dir(config: dict | None = None, environ=None) -> Path | None:
    """The state dir: ``UXR_STATE_DIR``, else ``paths.state_dir`` from config.

    An unexpanded ``${VAR}`` reference (the variable is unset) means the
    plugin is not installed in an environment with plugin data, so the
    result is None and nothing persists. Never raises.
    """
    environ = os.environ if environ is None else environ
    raw = str(environ.get(ENV_STATE_DIR) or "").strip()
    if not raw:
        value = config.get("paths", {}).get("state_dir") if isinstance(config, dict) else None
        raw = str(value or "").strip()
    if not raw:
        return None
    expanded = os.path.expanduser(os.path.expandvars(raw))
    if "${" in expanded:
        return None
    try:
        path = Path(expanded)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        return None


def buffer_path(state_dir, month: str | None = None) -> Path:
    """``<state_dir>/events-YYYY-MM.jsonl`` for the given or current local month."""
    if not month:
        month = datetime.now().astimezone().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    return Path(state_dir) / f"events-{month}.jsonl"


# ---------------------------------------------------------------------------
# consent
# ---------------------------------------------------------------------------


def _env_true(value) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def analytics_enabled(config: dict | None = None, environ=None, home=None) -> bool:
    """True only when every consent gate says on; any error means disabled."""
    try:
        environ = os.environ if environ is None else environ
        if str(environ.get(ENV_ANALYTICS) or "").strip().lower() == "off":
            return False
        if _env_true(environ.get(ENV_DO_NOT_TRACK)):
            return False
        base = Path(home) if home is not None else Path.home()
        if (base / ".claude" / OFF_FILE).is_file():
            return False
        if not isinstance(config, dict):
            return False
        analytics = config.get("analytics")
        if not isinstance(analytics, dict) or not analytics.get("enabled"):
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------


def pseudonymous_id(salt: str, value: str) -> str:
    """First 12 hex of ``sha256(salt|value)``; empty when there is no salt."""
    if not salt:
        return ""
    digest = hashlib.sha256(f"{salt}|{value}".encode("utf-8")).hexdigest()
    return digest[:12]


def load_or_create_salt(state_dir) -> str:
    """The random salt from ``<state_dir>/analytics-salt``, creating it 0600."""
    if state_dir is None:
        return ""
    path = Path(state_dir) / SALT_FILE
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        import secrets

        salt = secrets.token_hex(16)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(salt + "\n")
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return salt
    except OSError:
        return ""


def plugin_version() -> str:
    """The version from ``.claude-plugin/plugin.json``; empty on failure."""
    try:
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        return str(manifest.get("version") or "")
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# envelope and buffer
# ---------------------------------------------------------------------------


def scrub(value):
    """Deep-copy ``value`` dropping the silent-scrub keys at every level."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if str(k) not in SCRUB_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def build_envelope(event: str, payload: dict | None, session_id: str, salt: str,
                   now: str | None = None, uid_value: str | None = None) -> dict:
    """One event envelope: version, ts, salted ids, plugin version, payload."""
    if not now:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
    if not uid_value:
        with contextlib.suppress(Exception):
            uid_value = getpass.getuser()
        uid_value = uid_value or "anonymous"
    envelope = {
        "v": 1,
        "event": str(event),
        "ts": now,
        "session_id": pseudonymous_id(salt, str(session_id or "")),
        "uid": pseudonymous_id(salt, uid_value),
        "plugin_version": plugin_version(),
    }
    envelope.update(scrub(dict(payload or {})))
    return envelope


def record_event(event: str, payload: dict | None = None, session_id: str | None = None,
                 config: dict | None = None, state_dir=None, environ=None, home=None,
                 now: str | None = None) -> bool:
    """Append one event to the monthly buffer; True when written.

    Consent off, no state dir, or no salt: False and nothing is written.
    This function never touches the network.
    """
    try:
        if not analytics_enabled(config, environ=environ, home=home):
            return False
        state = Path(state_dir) if state_dir is not None \
            else resolve_state_dir(config, environ=environ)
        if state is None:
            return False
        salt = load_or_create_salt(state)
        if not salt:
            return False
        envelope = build_envelope(event, payload, str(session_id or ""), salt, now=now)
        path = buffer_path(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(envelope, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def read_buffer_lines(path, offset: int = 0, limit: int | None = None) -> tuple[list[str], int]:
    """At most ``limit`` complete JSON lines past ``offset``.

    Returns ``(lines, next_offset)``. A trailing partial line (no newline
    yet) is never read, and the offset only ever counts complete lines, so
    the buffer is never rewritten and nothing is sent twice.
    """
    path = Path(path)
    lines: list[str] = []
    consumed = offset
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index < offset:
                    continue
                if not line.endswith("\n"):
                    break  # partial line: leave it for the next flush
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
                consumed = index + 1
                if limit is not None and len(lines) >= limit:
                    break
    except OSError:
        return [], offset
    return lines, consumed


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def _selftest() -> int:
    """Cover the consent matrix, the salted ids, the envelope scrub, and the
    buffer behavior. This module never imports a network function; the
    flush-level no-network test lives in analytics_flush.py."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("hooks/analytics_common.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        state = tmp / "state"
        enabled = {"analytics": {"enabled": True, "endpoint": "", "api_key": ""}}
        disabled = {"analytics": {"enabled": False, "endpoint": "", "api_key": ""}}

        # 1. The consent matrix.
        check("analytics.enabled false means off",
              not analytics_enabled(disabled, environ={}, home=HOME))
        check("analytics.enabled true means on",
              analytics_enabled(enabled, environ={}, home=HOME))
        check("UXR_ANALYTICS=off overrides the config",
              not analytics_enabled(enabled, environ={"UXR_ANALYTICS": "off"}, home=HOME))
        check("DO_NOT_TRACK=1 means off",
              not analytics_enabled(enabled, environ={"DO_NOT_TRACK": "1"}, home=HOME))
        (HOME / ".claude" / OFF_FILE).write_text("", encoding="utf-8")
        check("the off file means off",
              not analytics_enabled(enabled, environ={}, home=HOME))
        (HOME / ".claude" / OFF_FILE).unlink()
        check("a missing config means off",
              not analytics_enabled(None, environ={}, home=HOME))
        check("an error during the check means off",
              not analytics_enabled(enabled, environ={}, home=123))

        # 2. Salted identity: 12 hex, stable, salt-dependent.
        salt = load_or_create_salt(state)
        check("salt file created and non-empty", bool(salt), repr(salt))
        if os.name == "posix":
            check("salt file mode is 0600",
                  (state / SALT_FILE).stat().st_mode & 0o777 == 0o600,
                  oct((state / SALT_FILE).stat().st_mode & 0o777))
        else:
            check("salt file created (POSIX modes not enforced on this OS)",
                  (state / SALT_FILE).is_file())
        check("load_or_create_salt is stable", load_or_create_salt(state) == salt)
        uid = pseudonymous_id(salt, "sess-1")
        check("pseudonymous id is 12 hex",
              len(uid) == 12 and all(c in "0123456789abcdef" for c in uid), uid)
        check("same value keeps one id, different value differs",
              pseudonymous_id(salt, "sess-1") == uid
              and pseudonymous_id(salt, "sess-2") != uid)
        check("a different salt changes the id",
              pseudonymous_id("other", "sess-1") != uid)
        check("no salt means no id", pseudonymous_id("", "sess-1") == "")

        # 3. Envelope: shape, salted session id, deep scrub.
        envelope = build_envelope(
            "command_invoked",
            {"command": "/uxr-eod", "prompt": "secret", "nested":
             {"text": "secret", "command": "/uxr-show"}},
            "sess-1", salt, now="2026-11-09T12:00:00-05:00", uid_value="researcher")
        check("envelope carries v, ts, event, plugin_version",
              envelope["v"] == 1 and envelope["event"] == "command_invoked"
              and envelope["ts"] == "2026-11-09T12:00:00-05:00"
              and envelope["plugin_version"] == plugin_version(), repr(envelope))
        check("session_id and uid are salted, never raw",
              envelope["session_id"] == pseudonymous_id(salt, "sess-1")
              and envelope["uid"] == pseudonymous_id(salt, "researcher")
              and "sess-1" not in json.dumps(envelope), repr(envelope))
        check("prompt/text/content are dropped silently",
              "prompt" not in envelope and "text" not in envelope.get("nested", {})
              and envelope.get("nested", {}).get("command") == "/uxr-show",
              repr(envelope))

        # 4. record_event: consent gates the buffer; no network here.
        check("consent off writes nothing",
              not record_event("session_summary", {}, "s", config=disabled,
                               state_dir=state, environ={}, home=HOME)
              and not any(state.glob("events-*.jsonl")))
        check("consent on writes one buffer line",
              record_event("session_summary", {"user_messages": 4}, "s1",
                           config=enabled, state_dir=state, environ={}, home=HOME,
                           now="2026-11-09T12:00:01-05:00")
              and record_event("session_summary", {"user_messages": 2}, "s2",
                               config=enabled, state_dir=state, environ={}, home=HOME,
                               now="2026-11-09T12:00:02-05:00"))
        buffer = buffer_path(state, "2026-11")
        rows = [json.loads(line) for line in
                buffer.read_text(encoding="utf-8").splitlines() if line.strip()]
        check("buffer is one JSON line per event with scrubbed payload",
              len(rows) == 2 and rows[0]["event"] == "session_summary"
              and rows[0]["session_id"] == pseudonymous_id(salt, "s1")
              and "prompt" not in json.dumps(rows) and "text" not in json.dumps(rows),
              repr(rows))

        # 5. read_buffer_lines: offsets, limits, partial lines.
        lines, next_offset = read_buffer_lines(buffer, 0, limit=1)
        check("limit reads at most N complete lines",
              len(lines) == 1 and next_offset == 1, repr((lines, next_offset)))
        rest, rest_offset = read_buffer_lines(buffer, next_offset)
        check("the remainder resumes at the offset",
              len(rest) == 1 and rest_offset == 2, repr((rest, rest_offset)))
        with open(buffer, "a", encoding="utf-8") as handle:
            handle.write('{"v":1,"event":"partial"}')  # no trailing newline
        partial_lines, partial_offset = read_buffer_lines(buffer, 0)
        check("a trailing partial line is never read",
              len(partial_lines) == 2 and partial_offset == 2,
              repr((partial_lines, partial_offset)))

        # 6. resolve_state_dir: env override and unexpanded placeholder.
        check("UXR_STATE_DIR overrides config",
              str(resolve_state_dir(None, environ={ENV_STATE_DIR: str(tmp / "other")}))
              == str((tmp / "other").resolve())
              or str(resolve_state_dir(None, environ={ENV_STATE_DIR: str(tmp / "other")}))
              == str(tmp / "other"))
        check("an unexpanded ${VAR} resolves to None",
              resolve_state_dir({"paths": {"state_dir": "${UNSET_VAR_X}/state"}},
                                environ={}) is None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in args or "--selftest" in args:
        return _selftest()
    print(__doc__.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
