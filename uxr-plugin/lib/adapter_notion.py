#!/usr/bin/env python3
"""Notion adapter: the fourth sync-half module (issue 114, wave P3).

Implements the four adapter operations for ``tracker.kind == "notion"``
under the interface contract documented in ``lib/adapters.py``. All four
are deterministic, network-free, and tool-call-free: they compute facts,
payloads, and bodies. The commands make the tracker tool calls (the
Notion column of the operations table in ``references/tracker.md``, with
the per-operation parameters in ``references/tracker-notion.md``) and
hold the live session steps (the integration's user lookup, the token
context) — this module does not duplicate them.

Notion is a database-backed tracker: one study item is one page in the
database ``tracker.workspace_id`` names, and the phase lives in the
database's Status property. The shipped registration moves Notion from
the declared KB entry to a built issues-area adapter; the knowledge-base
area keeps its own separate declared entry keyed ``notion-kb`` (same
system, different areas = two entries, per ``references/onboarding.md``).

- ``connect(config)``: reads the connection facts from ``tracker.*`` and
  reports which are still empty. Pure config reading. For Notion,
  ``tracker.workspace_id`` is the database id and ``tracker.base_url``
  is the web root (``https://www.notion.so`` unless the operator runs a
  self-hosted instance); ``tracker.project_key`` is not a Notion concept
  and stays empty; ``tracker.body_format`` is ``markdown``.
- ``pull(key, config)``: the ``normalize_key`` rule of
  ``references/tracker.md`` (Notion column) in code. Notion pages carry
  no numbers, so nothing composes: the key passes through unchanged —
  a page id, a saved short key, whatever the operator's
  ``tracker.ticket_regex`` accepts when one is configured. Returns
  ``{"key": ...}`` or ``{"error": "..."}`` with a deterministic
  message; never raises and never reads the network. The actual item
  read stays a command tool call; the issue-52 mention then shows the
  key and the short title the read returned.
- ``push(spec, shorthands, config)``: field payloads through
  ``lib/field_map.resolve_shorthand`` (the interval object rule keys on
  ``tracker.kind``, so Notion payloads carry the plain object, not the
  Jira JSON string), the body through ``scripts/build_body.run`` with
  its exit-code contract: 0 ok, 3 validation refused with zero writes,
  2/4 errors. Returns ``{"exit", "body", "fields", "stderr"}``.
- ``spec_transform(spec, config, body_format=None)``: delegates to
  ``lib/spec_blocks.build_document``; byte-identical outputs because it
  is the same function. Notion bodies render as Markdown; the command
  maps the rendered body into the page content through the API.

Notion field specifics (the status property name, the database schema
ids) stay config-driven with shipped empty defaults: the payload
machinery runs with empty ids, and nothing in this module needs them.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

try:
    from . import config as _config  # package context: import lib.adapter_notion
    from . import field_map as _field_map
    from . import spec_blocks as _spec_blocks
except ImportError:  # direct execution: python lib/adapter_notion.py
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
    command-side prose in ``references/tracker-notion.md``.
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
    """Normalize one page key: the Notion ``normalize_key`` rule in code.

    Notion pages carry no numbers, so nothing composes: a key passes
    through unchanged. With ``tracker.ticket_regex`` configured, the key
    must match it and a mismatch returns ``{"error": "..."}`` with a
    deterministic message — no exception, no network call. With no
    regex configured there is nothing to validate against, so any
    non-empty key passes through.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    text = str(key or "").strip()
    if not text:
        return {"error": "pull: no page key given"}
    regex = str(tracker.get("ticket_regex") or "")
    if not regex:
        return {"key": text}
    try:
        pattern = re.compile(regex)
    except re.error as exc:
        return {"error": f"pull: tracker.ticket_regex does not compile: {exc}"}
    if pattern.fullmatch(text):
        return {"key": text}
    return {"error": f"pull: {text!r} does not match tracker.ticket_regex"}


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
                "stderr": f"adapter_notion: config error: {exc}\n",
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
                "stderr": f"adapter_notion: spec is not JSON-serializable: {exc}\n",
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
    both are empty the body renders as Markdown (the Notion body format).
    """
    return _spec_blocks.build_document(spec, config=config, body_format=body_format)
