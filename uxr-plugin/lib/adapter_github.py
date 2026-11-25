#!/usr/bin/env python3
"""GitHub Issues adapter: the second sync-half module (issue 114, wave P1).

Implements the four adapter operations for ``tracker.kind == "github"``
under the interface contract documented in ``lib/adapters.py``. All four
are deterministic, network-free, and tool-call-free: they compute facts,
payloads, and bodies. The commands make the tracker tool calls (the
GitHub Issues column of the operations table in ``references/tracker.md``,
with the per-operation parameters in ``references/tracker-github.md``)
and hold the live session steps (current-user lookup, the ``gh`` auth
context) — this module does not duplicate them.

- ``connect(config)``: reads the connection facts from ``tracker.*`` and
  reports which are still empty. Pure config reading. For GitHub,
  ``tracker.workspace_id`` is the ``owner/repo`` the issues live in and
  ``tracker.base_url`` is the web root (``https://github.com`` or a
  GitHub Enterprise root); ``tracker.project_key`` stays empty (GitHub
  has no project-key concept) and ``tracker.body_format`` is
  ``markdown``.
- ``pull(key, config)``: the ``normalize_key`` rule of
  ``references/tracker.md`` (GitHub Issues column) in code, one key at a
  time. A bare number composes ``#<n>`` in the repo from
  ``tracker.workspace_id`` — GitHub keys issues by number, so no
  ``tracker.bare_number_prefix`` is needed. A key matching
  ``tracker.ticket_regex`` passes unchanged; the composed key validates
  against the regex when one is configured. Returns ``{"key": ...}`` or
  ``{"error": "..."}`` with a deterministic message; never raises and
  never reads the network. The actual item read stays a command tool
  call (``gh issue view <number>`` takes the bare number).
- ``push(spec, shorthands, config)``: field payloads through
  ``lib/field_map.resolve_shorthand`` (the interval object rule keys on
  ``tracker.kind``, so GitHub payloads carry the plain object, not the
  Jira JSON string), the body through ``scripts/build_body.run`` with
  its exit-code contract: 0 ok, 3 validation refused with zero writes,
  2/4 errors. Returns ``{"exit", "body", "fields", "stderr"}``.
- ``spec_transform(spec, config, body_format=None)``: delegates to
  ``lib/spec_blocks.build_document``; byte-identical outputs because it
  is the same function. GitHub bodies render as Markdown.

GitHub field specifics (label conventions, Projects field ids) stay
config-driven with shipped empty defaults: the payload machinery runs
with empty ids, and nothing in this module needs them.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

try:
    from . import config as _config  # package context: import lib.adapter_github
    from . import field_map as _field_map
    from . import spec_blocks as _spec_blocks
except ImportError:  # direct execution: python lib/adapter_github.py
    import config as _config  # type: ignore
    import field_map as _field_map  # type: ignore
    import spec_blocks as _spec_blocks  # type: ignore

try:
    from scripts import build_body as _build_body  # plugin root on sys.path
except ImportError:  # direct execution: add the plugin root, then retry
    if str(_config.PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(_config.PLUGIN_ROOT))
    from scripts import build_body as _build_body  # type: ignore

#: The ``tracker.*`` connection keys, in record order. ``tracker.kind`` is
#: the selector, not a fact, so it is not in this tuple.
_CONNECTION_KEYS = ("base_url", "project_key", "workspace_id", "ticket_regex", "body_format")


def connect(config: Mapping[str, Any]) -> dict:
    """Return the connection facts, the empty ones, and readiness.

    The record carries ``tracker.kind`` and the five ``tracker.*``
    connection keys, plus ``missing`` (the dotted keys still empty) and
    ``ready`` (true when nothing is missing). The live session steps stay
    command-side prose in ``references/tracker-github.md``.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    record: dict[str, Any] = {"kind": str(tracker.get("kind") or "")}
    for key in _CONNECTION_KEYS:
        record[key] = str(tracker.get(key) or "")
    missing = [f"tracker.{key}" for key in _CONNECTION_KEYS if not record[key]]
    record["missing"] = missing
    record["ready"] = not missing
    return record


def pull(key: Any, config: Mapping[str, Any]) -> dict:
    """Normalize one issue key: the GitHub ``normalize_key`` rule in code.

    A key matching ``tracker.ticket_regex`` passes unchanged. A bare
    number composes ``#<number>`` (``42`` becomes ``#42``, the repo comes
    from ``tracker.workspace_id``); the composed key is validated against
    the regex when one is configured. Anything else returns
    ``{"error": "..."}`` with a deterministic message — no exception, no
    network call. With no ``ticket_regex`` configured there is nothing to
    validate against, so a non-bare key passes unchanged and a bare
    number still composes.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    text = str(key or "").strip()
    if not text:
        return {"error": "pull: no issue key given"}
    regex = str(tracker.get("ticket_regex") or "")
    pattern = None
    if regex:
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            return {"error": f"pull: tracker.ticket_regex does not compile: {exc}"}
    if pattern is not None and pattern.fullmatch(text):
        return {"key": text}
    if text.isdecimal():
        composed = f"#{text}"
        if pattern is not None and not pattern.fullmatch(composed):
            return {
                "error": f"pull: {composed!r} does not match tracker.ticket_regex; "
                "check the configured issue-key pattern"
            }
        return {"key": composed}
    if pattern is None:
        return {"key": text}
    return {
        "error": f"pull: {text!r} does not match tracker.ticket_regex and is not a bare number"
    }


def push(
    spec: Any,
    shorthands: list[str] | None,
    config: Mapping[str, Any] | None = None,
) -> dict:
    """Resolve the field payloads and render the body; the command writes.

    ``spec`` is the spec dict or None (a field-only edit). ``shorthands``
    is a list of field shorthand strings, resolved in order through
    ``lib.field_map.resolve_shorthand``; ``fields`` keeps the input order.
    The body renders through ``scripts.build_body.run``, which validates
    first: a refusal keeps exit 3 with the stderr lines and zero writes,
    exactly as today. One failed shorthand or a failed render refuses the
    whole push: ``fields`` and ``body`` come back empty and ``exit`` names
    the failure (0 ok, 3 rejected shorthand or spec, 2 config or JSON
    error, 4 incomplete document — no new exit codes).
    """
    if config is None:
        try:
            config = _config.load_config()
        except _config.ConfigError as exc:
            return {
                "exit": 2,
                "body": "",
                "fields": [],
                "stderr": f"adapter_github: config error: {exc}\n",
            }
    fields: list[dict] = []
    for shorthand in shorthands or []:
        try:
            fields.append(_field_map.resolve_shorthand(str(shorthand), config))
        except _field_map.ResolveError as exc:
            return {
                "exit": 3,
                "body": "",
                "fields": [],
                "stderr": f"rejected shorthand: {exc}\n",
            }
        except _config.ConfigError as exc:
            return {
                "exit": 2,
                "body": "",
                "fields": [],
                "stderr": f"config error: {exc}\n",
            }
    body = ""
    if spec is not None:
        try:
            spec_text = json.dumps(spec, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return {
                "exit": 2,
                "body": "",
                "fields": [],
                "stderr": f"adapter_github: spec is not JSON-serializable: {exc}\n",
            }
        code, stdout, stderr = _build_body.run(spec_text, config)
        if code != 0:
            return {"exit": code, "body": "", "fields": [], "stderr": stderr}
        body = stdout
    return {"exit": 0, "body": body, "fields": fields, "stderr": ""}


def spec_transform(
    spec: Any,
    config: Mapping[str, Any] | None = None,
    body_format: str | None = None,
) -> dict | str:
    """Render one spec into the tracker body; delegates to build_document.

    Byte-identical to ``lib.spec_blocks.build_document`` because it is the
    same function. ``body_format`` overrides ``tracker.body_format``; when
    both are empty the body renders as Markdown (the GitHub body format).
    """
    return _spec_blocks.build_document(spec, config=config, body_format=body_format)
