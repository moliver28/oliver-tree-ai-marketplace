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

from collections.abc import Mapping
from typing import Any

try:
    from .adapter_common import connect as _connect
    from .adapter_common import pull as _pull
    from .adapter_common import push as _push
    from .adapter_common import spec_transform as _spec_transform
except ImportError:  # direct execution: python lib/adapter_jira.py
    from adapter_common import (  # type: ignore
        connect as _connect,
        pull as _pull,
        push as _push,
        spec_transform as _spec_transform,
    )

#: The ``tracker.*`` connection keys, in record order. ``tracker.kind`` is
#: the selector, not a fact, so it is not in this tuple.
_CONNECTION_KEYS = ("base_url", "project_key", "workspace_id", "ticket_regex", "body_format")


def _compose(text: str, tracker: Mapping[str, Any]) -> str | None:
    prefix = str(tracker.get("bare_number_prefix") or "")
    return f"{prefix}-{text}" if prefix else None


def connect(config: Mapping[str, Any]) -> dict:
    """Connection facts, empty keys, and readiness over the five keys."""
    return _connect(config, _CONNECTION_KEYS)


def pull(key: Any, config: Mapping[str, Any]) -> dict:
    """The Jira ``normalize_key`` rule: prefix composition through common."""
    return _pull(
        key,
        config,
        empty_msg="pull: no ticket key given",
        compose=_compose,
        compose_none_msg=(
            "pull: bare number needs tracker.bare_number_prefix; it is empty"
        ),
        mismatch_hint="check tracker.bare_number_prefix",
    )


def push(spec, shorthands, config=None) -> dict:
    """The shared push pipeline; ``adapter_jira`` labels its two errors."""
    return _push("adapter_jira", spec, shorthands, config)


def spec_transform(spec, config=None, body_format=None):
    """Render the tracker body; byte-identical to build_document."""
    return _spec_transform(spec, config, body_format)
