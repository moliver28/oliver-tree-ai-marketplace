#!/usr/bin/env python3
"""Shared adapter machinery for the built tracker adapters.

One home for the code the four adapter modules carried in identical
shape: ``connect`` over the five ``tracker.*`` keys, the ``push``
pipeline (field shorthands through ``lib.field_map``, the body through
``scripts.build_body`` with its exit-code contract), the
``spec_transform`` delegation, and the ``pull`` rule. Each adapter
module keeps its public names and signatures; it passes its per-kind
message strings and compose rule as arguments, so every record and
error string stays byte-identical to the pre-extraction adapters.
stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

try:
    from . import config as _config  # package context
    from . import field_map as _field_map
    from . import spec_blocks as _spec_blocks
except ImportError:  # direct execution: python lib/adapter_common.py
    import config as _config  # type: ignore
    import field_map as _field_map  # type: ignore
    import spec_blocks as _spec_blocks  # type: ignore

try:
    from scripts import build_body as _build_body  # plugin root on sys.path
except ImportError:  # direct execution: add the plugin root, then retry
    if str(_config.PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(_config.PLUGIN_ROOT))
    from scripts import build_body as _build_body  # type: ignore


def connect(config: Mapping[str, Any], keys: tuple[str, ...]) -> dict:
    """Return the connection facts, the empty ones, and readiness.

    The record carries ``kind`` and the ``tracker.*`` connection keys the
    adapter names, plus ``missing`` (the dotted keys still empty) and
    ``ready`` (true when nothing is missing). The live session steps stay
    command-side prose in the kind's tracker reference.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    record: dict[str, Any] = {"kind": str(tracker.get("kind") or "")}
    for key in keys:
        record[key] = str(tracker.get(key) or "")
    missing = [f"tracker.{key}" for key in keys if not record[key]]
    record["missing"] = missing
    record["ready"] = not missing
    return record


def pull(
    key: Any,
    config: Mapping[str, Any],
    *,
    empty_msg: str,
    compose: Any = None,
    compose_none_msg: str = "",
    mismatch_hint: str = "check the configured issue-key pattern",
    unmatched_template: str = (
        "pull: {text!r} does not match tracker.ticket_regex"
        " and is not a bare number"
    ),
) -> dict:
    """Normalize one tracker key: the ``normalize_key`` rule in code.

    A key matching ``tracker.ticket_regex`` passes unchanged. A bare
    number composes through ``compose(text, tracker)``; ``None`` result
    means the kind cannot compose (reported through ``compose_none_msg``);
    the
    composed key validates against the regex when one is configured.
    With no regex configured, a non-bare key passes unchanged and a bare
    number still composes. Anything else returns ``{"error": ...}`` with
    the kind's deterministic message — no exception, no network call.
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    tracker = tracker if isinstance(tracker, Mapping) else {}
    text = str(key or "").strip()
    if not text:
        return {"error": empty_msg}
    regex = str(tracker.get("ticket_regex") or "")
    pattern = None
    if regex:
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            return {"error": f"pull: tracker.ticket_regex does not compile: {exc}"}
    if pattern is not None and pattern.fullmatch(text):
        return {"key": text}
    if text.isdecimal() and compose is not None:
        composed = compose(text, tracker)
        if composed is None:
            return {"error": compose_none_msg}
        if pattern is not None and not pattern.fullmatch(composed):
            return {
                "error": f"pull: {composed!r} does not match tracker.ticket_regex; "
                f"{mismatch_hint}"
            }
        return {"key": composed}
    if pattern is None:
        return {"key": text}
    return {"error": unmatched_template.format(text=text)}


def push(
    label: str,
    spec: Any,
    shorthands: list[str] | None,
    config: Mapping[str, Any] | None = None,
) -> dict:
    """Resolve the field payloads and render the body; the command writes.

    ``label`` names the adapter module (``adapter_jira``), used verbatim
    in its two config/serialization error strings. ``spec`` is the spec
    dict or None (a field-only edit). ``shorthands`` is a list of field
    shorthand strings, resolved in order through
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
                "stderr": f"{label}: config error: {exc}\n",
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
                "stderr": f"{label}: spec is not JSON-serializable: {exc}\n",
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

    Byte-identical to ``lib.spec_blocks.build_document`` because it is
    the same function. ``body_format`` overrides ``tracker.body_format``;
    when both are empty the body renders as Markdown.
    """
    return _spec_blocks.build_document(spec, config=config, body_format=body_format)
