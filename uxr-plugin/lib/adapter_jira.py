#!/usr/bin/env python3
"""Jira adapter: the first sync-half module (issue 112).

Implements the four adapter operations for ``tracker.kind == "jira"``
under the interface contract documented in ``lib/adapters.py``. All four
are deterministic, network-free, and tool-call-free: they compute facts,
payloads, and bodies. The commands make the tracker tool calls (the Jira
column of the operations table in ``references/tracker.md``) and hold the
live session steps (current-user lookup, the cloudId cache) — this module
does not duplicate them.

- ``connect(config)``: reads the connection facts from ``tracker.*`` and
  reports which are still empty. Pure config reading.
- ``pull(key, config)``: the ``normalize_key`` rule of
  ``references/tracker.md`` in code, one key at a time. Returns
  ``{"key": ...}`` or ``{"error": "..."}`` with a deterministic message;
  never raises and never reads the network. The actual item read stays a
  command tool call.
- ``push(spec, shorthands, config)``: field payloads through
  ``lib/field_map.resolve_shorthand`` (the Jira interval JSON-string rule
  keys on ``tracker.kind``, not on any project key or field id), the body
  through ``scripts/build_body.run`` with its exit-code contract: 0 ok,
  3 validation refused with zero writes, 2/4 errors. Returns
  ``{"exit", "body", "fields", "stderr"}``.
- ``spec_transform(spec, config, body_format=None)``: delegates to
  ``lib/spec_blocks.build_document``; byte-identical outputs because it is
  the same function.

Jira field specifics (project key, custom field ids) stay config-driven
with shipped empty defaults: the payload machinery runs with empty ids,
and nothing in this module needs them.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

try:
    from . import config as _config  # package context: import lib.adapter_jira
    from . import field_map as _field_map
    from . import spec_blocks as _spec_blocks
except ImportError:  # direct execution: python lib/adapter_jira.py
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
    command-side prose in ``references/tracker.md``.
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
    """Normalize one ticket key: the ``normalize_key`` rule in code.

    A key matching ``tracker.ticket_regex`` passes unchanged. A bare
    number gets ``tracker.bare_number_prefix`` (``42`` becomes
    ``<prefix>-42``); the composed key is validated against the regex when
    one is configured. Anything else returns ``{"error": "..."}`` with a
    deterministic message — no exception, no network call. With no
    ``ticket_regex`` configured there is nothing to validate against, so a
    non-bare key passes unchanged and a bare number still composes.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    text = str(key or "").strip()
    if not text:
        return {"error": "pull: no ticket key given"}
    regex = str(tracker.get("ticket_regex") or "")
    prefix = str(tracker.get("bare_number_prefix") or "")
    pattern = None
    if regex:
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            return {"error": f"pull: tracker.ticket_regex does not compile: {exc}"}
    if pattern is not None and pattern.fullmatch(text):
        return {"key": text}
    if text.isdecimal():
        if not prefix:
            return {"error": "pull: bare number needs tracker.bare_number_prefix; it is empty"}
        composed = f"{prefix}-{text}"
        if pattern is not None and not pattern.fullmatch(composed):
            return {
                "error": f"pull: {composed!r} does not match tracker.ticket_regex; "
                "check tracker.bare_number_prefix"
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
                "stderr": f"adapter_jira: config error: {exc}\n",
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
                "stderr": f"adapter_jira: spec is not JSON-serializable: {exc}\n",
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
    both are empty the body renders as Markdown.
    """
    return _spec_blocks.build_document(spec, config=config, body_format=body_format)
