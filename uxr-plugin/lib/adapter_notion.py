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

from collections.abc import Mapping
from typing import Any

try:
    from .adapter_common import (  # package context
        connect as _connect,
        pull as _pull,
        push as _push,
        spec_transform as _spec_transform,
    )
except ImportError:  # direct execution: python lib/adapter_notion.py
    from adapter_common import (  # type: ignore
        connect as _connect,
        pull as _pull,
        push as _push,
        spec_transform as _spec_transform,
    )

#: The ``tracker.*`` connection keys, in record order. ``tracker.kind`` is
#: the selector, not a fact, so it is not in this tuple.
_CONNECTION_KEYS = ("base_url", "project_key", "workspace_id", "ticket_regex", "body_format")


def connect(config: Mapping[str, Any]) -> dict:
    """Connection facts, empty keys, and readiness over the five keys."""
    return _connect(config, _CONNECTION_KEYS)


def pull(key: Any, config: Mapping[str, Any]) -> dict:
    """Pass-through key rule; the regex validates when configured."""
    return _pull(
        key,
        config,
        empty_msg="pull: no page key given",
        compose=None,
        unmatched_template=(
            "pull: {text!r} does not match tracker.ticket_regex"
        ),
    )


def push(spec, shorthands, config=None) -> dict:
    """The shared push pipeline; ``adapter_notion`` labels its two errors."""
    return _push("adapter_notion", spec, shorthands, config)


def spec_transform(spec, config=None, body_format=None):
    """Render the tracker body; byte-identical to build_document."""
    return _spec_transform(spec, config, body_format)
