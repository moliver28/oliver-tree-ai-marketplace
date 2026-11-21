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

"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import sys
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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    print(__doc__.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
