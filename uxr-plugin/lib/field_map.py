#!/usr/bin/env python3
"""Field shorthand resolver and routing helpers for the UX research plugin.

This is the deterministic half of the tracker adapter (issue 03): it turns a
user shorthand such as ``method=Survey`` into the tracker field payload, and
it implements the config-driven researcher routing that ``new`` uses. It
computes only; it never calls a tracker. Commands read the payload, preview
it, and write it through the tracker tools listed in ``references/tracker.md``.

Shorthand grammar::

    KEY=VALUE      replace (all kinds)
    KEY+=VALUE     add      (multi_select and labels only)
    KEY-=VALUE     remove   (multi_select and labels only)

VALUE shapes by kind:

- ``single_select`` / ``multi_select``: comma-separated tokens, matched
  against the field's configured ``values`` without case; the canonical
  configured case is emitted. A select field with an empty ``values`` list
  accepts any token until the organization fills in its real list.
- ``single_name``: one token, validated against ``tracker.priority_values``
  when that list is non-empty.
- ``labels``: comma-separated plain tokens (``a,b,c`` replaces), or signed
  tokens (``+urgent`` adds, ``-stale`` removes). Mixing plain and signed
  tokens in one shorthand raises; mixing add and remove signs raises.
- ``interval``: ``YYYY-MM-DD`` or ``YYYY-MM-DD..YYYY-MM-DD``. One date gives
  start equal to end. An end before the start raises. For a Jira tracker the
  payload is the JSON string ``{"start":"...","end":"..."}``; for every other
  tracker it is the equivalent object.
- ``date``: one real calendar date as ``YYYY-MM-DD``.
- ``url`` / ``text``: a trimmed non-empty string.
- ``user``: ``{"__resolve_user__": token}``; the command calls ``find_user()``
  and then writes the tracker's user shape. The token ``me`` means the cached
  current user.

The earliest operator among ``+=``, ``-=``, ``=`` splits the shorthand; if
two operators start at the same position the longer one wins. ``+=`` and
``-=`` are rejected on every kind except ``multi_select`` and ``labels``.

Payloads with an ``__op__`` wrapper describe a change against the live value:
the adapter layer reads the current value, applies the add or remove, and
writes the merged result (see ``references/tracker.md``).

Routing (config-driven, no prose in commands): ``detect_role`` matches the
current user's display name against ``routing.researchers`` and returns
``uxr``, ``manager``, or ``stakeholder``. ``resolve_researcher`` walks
``routing.group_to_area`` and ``routing.area_to_researcher`` (each area maps
to ``{"primary": name, "fallbacks": [names]}`` or a plain name); an unknown
group falls back to ``routing.default_researcher`` and returns the
map-update note the command must print.

Exit codes for the CLI: 0 ok, 2 usage or configuration error, 3 rejected
shorthand (ResolveError), 4 self-test failed.

Usage::

    python lib/field_map.py resolve --shorthand "method=External Interviews,Survey"
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from datetime import date
from typing import Any

try:
    from . import config as _config  # package context: import lib.field_map
except ImportError:  # direct execution: python lib/field_map.py
    import config as _config  # type: ignore

ConfigError = _config.ConfigError

#: Kinds that accept the add and remove operators.
_INCREMENTAL_KINDS = ("multi_select", "labels")

#: Kinds the resolver knows how to emit.
FIELD_KINDS = (
    "single_select",
    "multi_select",
    "single_name",
    "interval",
    "date",
    "labels",
    "url",
    "text",
    "user",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ResolveError(ValueError):
    """Raised when a field shorthand cannot be resolved into a payload."""


# ---------------------------------------------------------------------------
# shorthand parsing
# ---------------------------------------------------------------------------


def _split_operator(shorthand: str) -> tuple[str, str, str]:
    """Split ``KEY<op>VALUE`` at the earliest operator; ties go to the longer."""
    candidates: list[tuple[int, int, str]] = []
    for op in ("+=", "-=", "="):
        index = shorthand.find(op)
        if index != -1:
            candidates.append((index, -len(op), op))
    if not candidates:
        raise ResolveError(
            f"no operator in {shorthand!r}; expected KEY=VALUE, KEY+=VALUE, or KEY-=VALUE"
        )
    candidates.sort()
    index, _, op = candidates[0]
    key = shorthand[:index].strip()
    value = shorthand[index + len(op):].strip()
    if not key:
        raise ResolveError(f"missing field name before the operator in {shorthand!r}")
    return key, op, value


def _split_list(value: str) -> list[str]:
    """Split a comma-separated value into trimmed, non-empty tokens."""
    tokens = [token.strip() for token in value.split(",")]
    if any(not token for token in tokens):
        raise ResolveError(f"empty token in value {value!r}")
    return tokens


def _canonical(token: str, allowed: list[str], label: str) -> str:
    """Return the configured spelling of ``token``, matched without case."""
    if not allowed:
        # The organization has not filled in values yet; accept the token as
        # typed so the plugin works before configuration is complete.
        return token
    lookup = {str(item).casefold(): str(item) for item in allowed}
    hit = lookup.get(token.casefold())
    if hit is None:
        raise ResolveError(
            f"{label}: {token!r} is not an allowed value; allowed: {', '.join(str(a) for a in allowed)}"
        )
    return hit


def _parse_date(token: str, label: str) -> str:
    """Validate one strict ``YYYY-MM-DD`` real calendar date and return it."""
    if not _DATE_RE.match(token):
        raise ResolveError(f"{label}: {token!r} is not a YYYY-MM-DD date")
    year, month, day = (int(part) for part in token.split("-"))
    try:
        date(year, month, day)
    except ValueError:
        raise ResolveError(f"{label}: {token!r} is not a real calendar date") from None
    return token


# ---------------------------------------------------------------------------
# payload emission by kind
# ---------------------------------------------------------------------------


def _emit_single_select(field_id: str, op: str, value: str, field: Mapping[str, Any], label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: single_select fields take '=' only")
    allowed = [str(v) for v in field.get("values") or []]
    return {field_id: {"value": _canonical(value, allowed, label)}}


def _emit_multi_select(field_id: str, op: str, value: str, field: Mapping[str, Any], label: str) -> dict:
    allowed = [str(v) for v in field.get("values") or []]
    tokens = [_canonical(token, allowed, label) for token in _split_list(value)]
    items = [{"value": token} for token in tokens]
    if op == "=":
        return {field_id: items}
    direction = "add" if op == "+=" else "remove"
    return {field_id: {"__op__": direction, "values": items}}


def _emit_single_name(field_id: str, op: str, value: str, config: Mapping[str, Any], label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: single_name fields take '=' only")
    tracker = config.get("tracker") or {}
    allowed = [str(v) for v in (tracker.get("priority_values") or []) if str(v)]
    return {field_id: {"name": _canonical(value, allowed, label)}}


def _emit_interval(field_id: str, op: str, value: str, tracker_kind: str, label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: interval fields take '=' only")
    parts = value.split("..")
    if len(parts) == 1:
        start = _parse_date(parts[0].strip(), label)
        end = start
    elif len(parts) == 2:
        start = _parse_date(parts[0].strip(), label)
        end = _parse_date(parts[1].strip(), label)
    else:
        raise ResolveError(f"{label}: {value!r} is not DATE or DATE..DATE")
    if end < start:
        raise ResolveError(f"{label}: interval end {end} is before start {start}")
    window = {"start": start, "end": end}
    if tracker_kind == "jira":
        # Jira's period field wants the window as a JSON string.
        return {field_id: json.dumps(window, separators=(",", ":"))}
    return {field_id: window}


def _emit_date(field_id: str, op: str, value: str, label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: date fields take '=' only")
    return {field_id: _parse_date(value, label)}


def _emit_labels(field_id: str, op: str, value: str, label: str) -> dict:
    tokens = _split_list(value)
    signed = [token for token in tokens if token.startswith(("+", "-"))]
    plain = [token for token in tokens if not token.startswith(("+", "-"))]
    stripped = [token[1:] for token in signed]
    if any(not token for token in stripped):
        raise ResolveError(f"{label}: a signed label token with no name in {value!r}")
    if op in ("+=", "-="):
        if signed:
            raise ResolveError(
                f"{label}: do not sign tokens with {op!r}; the operator already sets the direction"
            )
        direction = "add" if op == "+=" else "remove"
        return {field_id: {"__op__": direction, "values": plain}}
    if plain and signed:
        raise ResolveError(
            f"{label}: cannot mix plain and signed label tokens in {value!r}; "
            "replace with labels=A,B, add with labels=+A, remove with labels=-A"
        )
    if signed:
        adds = [token[1:] for token in signed if token.startswith("+")]
        removes = [token[1:] for token in signed if token.startswith("-")]
        if adds and removes:
            raise ResolveError(
                f"{label}: cannot add and remove labels in one shorthand; run two edits"
            )
        if adds:
            return {field_id: {"__op__": "add", "values": adds}}
        return {field_id: {"__op__": "remove", "values": removes}}
    return {field_id: plain}


def _emit_string(field_id: str, op: str, value: str, kind: str, label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: {kind} fields take '=' only")
    text = value.strip()
    if not text:
        raise ResolveError(f"{label}: {kind} fields need a non-empty value")
    return {field_id: text}


def _emit_user(field_id: str, op: str, value: str, label: str) -> dict:
    if op != "=":
        raise ResolveError(f"{label}: user fields take '=' only")
    token = value.strip()
    if not token:
        raise ResolveError(f"{label}: user fields need a name, email, or 'me'")
    return {field_id: {"__resolve_user__": token}}


# ---------------------------------------------------------------------------
# public contract
# ---------------------------------------------------------------------------


def resolve_shorthand(shorthand: str, config: Mapping[str, Any] | None = None) -> dict:
    """Resolve one field shorthand into a tracker payload; raise ResolveError.

    Returns ``{field_id: payload}`` as described in the module docstring.
    ``config`` defaults to :func:`lib.config.load_config` when omitted.
    """
    if config is None:
        config = _config.load_config()
    key, op, value = _split_operator(shorthand)

    fields = config.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        raise ResolveError(
            "config has no fields entries; add fields.<name> to config/org.yaml"
        )
    entry = fields.get(key)
    if not isinstance(entry, Mapping):
        known = ", ".join(sorted(str(name) for name in fields))
        raise ResolveError(f"unknown field {key!r}; known fields: {known}")
    field_id = str(entry.get("id") or "")
    kind = str(entry.get("kind") or "")
    if kind not in FIELD_KINDS:
        raise ResolveError(
            f"{key}: kind {kind!r} is not supported; use one of {', '.join(FIELD_KINDS)}"
        )
    if op in ("+=", "-=") and kind not in _INCREMENTAL_KINDS:
        raise ResolveError(
            f"{key}: operator {op!r} is only valid on multi_select and labels fields, not {kind}"
        )

    if kind == "single_select":
        return _emit_single_select(field_id, op, value, entry, key)
    if kind == "multi_select":
        return _emit_multi_select(field_id, op, value, entry, key)
    if kind == "single_name":
        return _emit_single_name(field_id, op, value, config, key)
    if kind == "interval":
        tracker = config.get("tracker") or {}
        return _emit_interval(field_id, op, value, str(tracker.get("kind") or ""), key)
    if kind == "date":
        return _emit_date(field_id, op, value, key)
    if kind == "labels":
        return _emit_labels(field_id, op, value, key)
    if kind in ("url", "text"):
        return _emit_string(field_id, op, value, kind, key)
    return _emit_user(field_id, op, value, key)


# ---------------------------------------------------------------------------
# researcher routing (config-driven; the `new` command consumes this)
# ---------------------------------------------------------------------------


def detect_role(display_name: str, routing: Mapping[str, Any]) -> str:
    """Return ``uxr`` or ``manager`` when the name is in routing.researchers.

    Any other name, including an entry whose role is not one of the two
    recognized roles, returns ``stakeholder``.
    """
    target = display_name.strip().casefold()
    if not target:
        return "stakeholder"
    for entry in routing.get("researchers") or []:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("display_name") or "").strip()
        if not name or name.casefold() != target:
            continue
        role = str(entry.get("role") or "").strip().casefold()
        return role if role in ("uxr", "manager") else "stakeholder"
    return "stakeholder"


def _area_assignment(entry: Any) -> tuple[str, list[str]]:
    """Read an area_to_researcher entry: dict with primary/fallbacks or a name."""
    if isinstance(entry, str):
        return entry.strip(), []
    if isinstance(entry, Mapping):
        primary = str(entry.get("primary") or "").strip()
        fallbacks = [
            str(name).strip()
            for name in (entry.get("fallbacks") or [])
            if str(name).strip()
        ]
        return primary, fallbacks
    return "", []


def _lookup_key(mapping: Mapping[str, Any], token: str) -> str | None:
    """Case-insensitive key match; returns the configured key spelling."""
    if not token:
        return None
    for key in mapping:
        if str(key).strip().casefold() == token:
            return str(key)
    return None


def resolve_researcher(group: str, routing: Mapping[str, Any]) -> dict:
    """Resolve the researcher who owns a study for ``group``.

    Returns ``{"group", "area", "researcher", "fallbacks", "notes"}``. An
    unknown group or an unmapped area falls back to
    ``routing.default_researcher`` and adds the map-update note the command
    must print verbatim as the first ``notes`` entry.
    """
    notes: list[str] = []
    group_token = group.strip()
    folded = group_token.casefold()

    group_to_area = routing.get("group_to_area") or {}
    area: str | None = None
    matched_key = _lookup_key(group_to_area, folded) if isinstance(group_to_area, Mapping) else None
    if matched_key is not None:
        area = str(group_to_area[matched_key]).strip()

    default_researcher = str(routing.get("default_researcher") or "").strip()
    researcher = ""
    fallbacks: list[str] = []

    if area is None:
        notes.append(
            f"Unknown group {group_token!r}: it has no entry in routing.group_to_area. "
            "Update the routing map (routing.group_to_area and routing.area_to_researcher "
            f"in config/org.yaml) so this group routes to its researcher; "
            f"using the default researcher {default_researcher!r} for now."
        )
    else:
        area_to_researcher = routing.get("area_to_researcher") or {}
        entry: Any = None
        if isinstance(area_to_researcher, Mapping):
            area_key = _lookup_key(area_to_researcher, area.casefold())
            if area_key is not None:
                entry = area_to_researcher[area_key]
        primary, chain = _area_assignment(entry)
        if primary:
            researcher = primary
            fallbacks = chain
        elif chain:
            researcher = chain[0]
            fallbacks = chain[1:]
            notes.append(
                f"Area {area!r} has no primary researcher in routing.area_to_researcher; "
                f"using the first fallback {researcher!r}. Update the routing map."
            )
        else:
            notes.append(
                f"Area {area!r} has no entry in routing.area_to_researcher. "
                "Update the routing map (routing.area_to_researcher in config/org.yaml) "
                f"so this area routes to its researcher; using the default researcher "
                f"{default_researcher!r} for now."
            )

    if not researcher:
        researcher = default_researcher
        if not researcher:
            notes.append(
                "routing.default_researcher is not set in config/org.yaml; "
                "no researcher could be resolved. Update the routing map."
            )
    return {
        "group": group_token,
        "area": area,
        "researcher": researcher,
        "fallbacks": fallbacks,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

USAGE = """usage:
  python lib/field_map.py resolve --shorthand "<KEY=VALUE | KEY+=VALUE | KEY-=VALUE>"
  python lib/field_map.py --help

exit codes: 0 ok, 2 usage or configuration error, 3 rejected shorthand,
4 self-test failed."""


def _cli_resolve(rest: list[str]) -> int:
    """Handle `resolve --shorthand ...`; returns the process exit code."""
    shorthand: str | None = None
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--shorthand":
            index += 1
            if index >= len(rest):
                print("resolve: --shorthand needs a value", file=sys.stderr)
                return 2
            shorthand = rest[index]
        elif arg.startswith("--shorthand="):
            shorthand = arg[len("--shorthand="):]
        else:
            print(f"resolve: unknown argument {arg!r}", file=sys.stderr)
            return 2
        index += 1
    if shorthand is None or not shorthand.strip():
        print("resolve: --shorthand is required", file=sys.stderr)
        return 2
    try:
        payload = resolve_shorthand(shorthand)
    except ResolveError as exc:
        print(f"rejected shorthand: {exc}", file=sys.stderr)
        return 3
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not args:
        print(USAGE)
        return 2
    if args[0] == "resolve":
        return _cli_resolve(args[1:])
    print(f"unknown command {args[0]!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
