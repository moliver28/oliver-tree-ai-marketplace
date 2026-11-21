#!/usr/bin/env python3
"""Shared plumbing for the uxr-plugin payload (Design D dedupe).

One home for the helpers that hooks, scripts, and lib modules all carried
in identical form: the fail-open config load, UTF-8 stdio forcing, UTC
timestamps, path and workspace resolution, research-root enumeration,
comma-list parsing, and the JSON-argument loader family. Each site
imports from here instead of carrying its own copy; behavior and print
strings are unchanged. stdlib only; paths via ``Path`` methods.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

#: Research-root override (os.pathsep-separated directories) read by every
#: module that enumerates research roots.
ENV_RESEARCH_DIRS = "UXR_RESEARCH_DIRS"

#: Workspace markers: a research workspace holds one of these.
SESSIONS_DIRNAME = ".sessions"
OVERVIEW_MARKER = "00-overview.md"


def load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        if str(PLUGIN_ROOT) not in sys.path:
            sys.path.insert(0, str(PLUGIN_ROOT))
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def force_utf8_stdio() -> None:
    """Keep emoji and unicode content intact on every platform pipe."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def utcnow() -> str:
    """ISO 8601 UTC time with a ``Z`` suffix, second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve(path) -> Path:
    """Expand and resolve a path; fall back to the absolute form on failure."""
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        try:
            return Path(path).expanduser().absolute()
        except OSError:
            return Path(path)


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


def find_workspace(cwd) -> Path | None:
    """The cwd, or its nearest ancestor, holding ``.sessions/`` or ``00-overview.md``."""
    real = resolve(cwd)
    if (real / SESSIONS_DIRNAME).is_dir() or (real / OVERVIEW_MARKER).is_file():
        return real
    for parent in real.parents:
        if (parent / SESSIONS_DIRNAME).is_dir() or (parent / OVERVIEW_MARKER).is_file():
            return parent
    return None


def parse_list(value: str | None) -> list[str]:
    """Split a comma-separated argument into trimmed, non-empty tokens."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


class JsonReadError(Exception):
    """Structured JSON-argument read failure.

    ``kind`` is ``"notfound"`` | ``"invalid"`` | ``"unreadable"``; ``path``
    is the attempted path and ``exc`` the underlying error (None for
    "notfound"). Sites format their own messages from these fields so the
    exact per-script print strings stay byte-identical.
    """

    def __init__(self, kind: str, path: Path, exc: Exception | None):
        super().__init__(f"{kind}: {path}")
        self.kind = kind
        self.path = path
        self.exc = exc


def json_error_message(exc: JsonReadError, what: str) -> str:
    """Canonical per-kind message for sites that print exactly this wording."""
    if exc.kind == "notfound":
        return f"{what} not found: {exc.path}"
    if exc.kind == "invalid":
        return f"{what} is not valid JSON ({exc.path}): {exc.exc}"
    return f"{what} cannot be read ({exc.path}): {exc.exc}"


def read_json_document(path) -> object:
    """Raw JSON file read (``~`` expanded); errors propagate unchanged."""
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def read_json_arg(
    value: str | Path | None,
    what: str = "",
    *,
    missing: str = "error",
    stdin_if_empty: bool = False,
    expanduser: bool = True,
) -> object:
    """Parse one JSON argument; family home for the per-script loaders.

    ``value`` is a file path. An empty/None ``value`` reads stdin when
    ``stdin_if_empty``, else returns ``{}`` when ``missing="empty"``. With
    ``missing="empty"`` a missing file also returns ``{}`` (and an
    unreadable file raises the raw OSError, as the phase_gates loader
    always did); with ``missing="error"`` a missing file raises
    :class:`JsonReadError`("notfound"), an unreadable one "unreadable",
    and invalid JSON "invalid".
    """
    if not value:
        if stdin_if_empty:
            return json.loads(sys.stdin.read())
        if missing == "empty":
            return {}
    path = Path(value)
    if expanduser:
        path = path.expanduser()
    if missing == "empty":
        if not path.is_file():
            return {}
        text = path.read_text(encoding="utf-8")
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise JsonReadError("notfound", path, None) from None
        except OSError as exc:
            raise JsonReadError("unreadable", path, exc) from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise JsonReadError("invalid", path, exc) from exc
