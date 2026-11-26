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

from collections.abc import Mapping
from typing import Any

try:
    from .adapter_common import connect as _connect
    from .adapter_common import pull as _pull
    from .adapter_common import push as _push
    from .adapter_common import spec_transform as _spec_transform
except ImportError:  # direct execution: python lib/adapter_github.py
    from adapter_common import (  # type: ignore
        connect as _connect,
        pull as _pull,
        push as _push,
        spec_transform as _spec_transform,
    )

#: The ``tracker.*`` connection keys, in record order. ``tracker.kind`` is
#: the selector, not a fact, so it is not in this tuple.
_CONNECTION_KEYS = ("base_url", "project_key", "workspace_id", "ticket_regex", "body_format")

_compose = lambda text, tracker: f"#{text}"  # noqa: E731  (the #<n> composition)


def connect(config: Mapping[str, Any]) -> dict:
    """Connection facts, empty keys, and readiness over the five keys."""
    return _connect(config, _CONNECTION_KEYS)


def pull(key: Any, config: Mapping[str, Any]) -> dict:
    """The GitHub ``normalize_key`` rule: #<n> composition through common."""
    return _pull(
        key,
        config,
        empty_msg="pull: no issue key given",
        compose=_compose,
    )


def push(spec, shorthands, config=None) -> dict:
    """The shared push pipeline; ``adapter_github`` labels its two errors."""
    return _push("adapter_github", spec, shorthands, config)


def spec_transform(spec, config=None, body_format=None):
    """Render the tracker body; byte-identical to build_document."""
    return _spec_transform(spec, config, body_format)
