#!/usr/bin/env python3
"""Phase readiness gates for study tickets (issue 07 / command gates).

A study moves through phases (``workflow.phase_order``) and ``move`` may only
push a ticket into a phase when the ticket is ready for it: the required
tracker fields are set and the spec-level checks pass. This module owns the
deterministic half of that decision; ``commands/uxr-move.md`` and
``commands/uxr-edit.md`` call it and never re-derive a gate themselves.

Contract (issue 07):

- ``check_phase_readiness(target_status, spec, field_state)`` returns
  ``(ok, missing)``. Ungated statuses -- ones that match no requirement key,
  such as Summarizing Data or Blocked -- always pass with no missing items.
- ``suggest_next_phase(current_status, spec, field_state)`` looks only at the
  next phase in ``phase_order`` and returns it only when that phase has
  requirements and they all pass; otherwise ``None``.
- ``build_field_state(tracker_fields)`` turns the field values a ticket read
  returned into ``{requirement field key: bool}``.

Status matching is case-insensitive with every whitespace character removed,
as a substring in either direction, so ``Writing Script/Survey`` matches the
phase ``Writing Script / Survey``. When several keys match, the exact
(normalization-equal) key wins, then the longest key.

Reference requirements ship here because they are plugin structure, not
organization identity; a non-empty ``workflow.requirements`` in
``config/org.yaml`` replaces them entirely (the organization owns the full
table it ships). Every reference key is verified against the reference
``phase_order`` in the self-test.

Missing-item strings are exactly:

- ``field '<key>' is not set``
- ``spec check failed: <predicate>``

CLI (exit codes: 0 pass / 1 not ready / 2 usage or config)::

    python lib/phase_gates.py check --status "Recruiting" --spec spec.json --fields fields.json
    python lib/phase_gates.py suggest --status "Recruiting" --spec spec.json --fields fields.json
    python lib/phase_gates.py missing --json check-output.json --key UXR-101

``check`` prints one JSON object: ``{"target", "gated", "ok", "missing"}``
where every ``missing`` entry is ``{"item", "fix"}`` and ``fix`` is the
``edit`` shorthand that closes the gap. ``suggest`` prints the suggested
phase name, or nothing when there is no suggestion. ``missing`` prints the
blocked-move lines for a ``check`` output (one per missing item, golden
format), which the command prints verbatim.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from . import config as _config  # package context: import lib.phase_gates
    from . import spec_blocks  # package context
except ImportError:  # direct execution: python lib/phase_gates.py
    import config as _config  # type: ignore

try:
    from .util import force_utf8_stdio as _force_utf8_stdio, read_json_arg as _read_json_arg_util, JsonReadError as _JsonReadError  # package context
except ImportError:  # direct execution: python lib/phase_gates.py
    from util import force_utf8_stdio as _force_utf8_stdio, read_json_arg as _read_json_arg_util, JsonReadError as _JsonReadError  # type: ignore
    import spec_blocks  # type: ignore

ConfigError = _config.ConfigError

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

#: The reference phase order (issue 07). ``workflow.phase_order`` in config
#: replaces this when it is a non-empty list.
REFERENCE_PHASE_ORDER: tuple[str, ...] = (
    "Planned",
    "Writing Script / Survey",
    "Recruiting",
    "Collecting Data",
    "Summarizing Data",
    "Creating Report",
    "Done",
)

#: The reference readiness rules (issue 07). Entries are ``field:<key>`` or
#: ``spec:<predicate>``; a bare name is accepted and classified against the
#: known predicates. A non-empty ``workflow.requirements`` in config replaces
#: this table entirely (the organization owns the full table it ships).
REFERENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "Planned": (
        "field:ux_researcher",
        "field:pod",
        "spec:background_filled",
        "spec:research_questions_nonempty",
    ),
    "Writing Script / Survey": ("field:research_method",),
    "Recruiting": (
        "field:research_method",
        "spec:roster_nonempty",
        "spec:recruitment_strategy_filled",
    ),
    "Collecting Data": ("spec:roster_has_scheduled",),
    "Creating Report": ("field:output_link",),
    "Done": ("field:output_link", "spec:results_filled"),
}

#: The spec-level predicates and their implementations. Every predicate takes
#: the spec (already coerced to a dict) and answers one question.
SPEC_CHECKS: dict[str, Any] = {}


def _predicate(function: Any) -> Any:
    SPEC_CHECKS[function.__name__] = function
    return function


#: Requirement field keys, and where each reads its value from in a ticket
#: read: the requirement key itself, or the config field shorthand name.
#: Field ids from ``fields.<name>.id`` resolve too when ``config`` is passed.
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "ux_researcher": ("ux_researcher", "uxr"),
    "pod": ("pod",),
    "research_method": ("research_method", "method"),
    "output_link": ("output_link", "output"),
}

#: The ``edit`` shorthand that sets each requirement field.
FIELD_FIX_HINTS: dict[str, str] = {
    "ux_researcher": "uxr=<name>",
    "pod": "pod=<value>",
    "research_method": "method=<value>",
    "output_link": "output=<url>",
}

#: The ``edit`` shorthand that fills each spec predicate.
SPEC_FIX_HINTS: dict[str, str] = {
    "background_filled": "history=<text> decision=<text>",
    "research_questions_nonempty": "questions=<q1 | q2 | q3>",
    "roster_nonempty": "roster+=Name|email|slack|reason|status|channel",
    "recruitment_strategy_filled": "sample=<size> persona=<personas> length=<length>",
    "roster_has_scheduled": "roster~=Name|status=Scheduled",
    "results_filled": "results=<text>",
}


# ---------------------------------------------------------------------------
# spec predicates
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _filled_not_placeholder(value: Any, placeholder: str) -> bool:
    text = _text(value)
    return bool(text) and text != placeholder


@_predicate
def background_filled(spec: dict) -> bool:
    """History and decision are both filled and neither is its placeholder."""
    return _filled_not_placeholder(
        spec.get("history"), spec_blocks.PLACEHOLDERS["history"]
    ) and _filled_not_placeholder(spec.get("decision"), spec_blocks.PLACEHOLDERS["decision"])


@_predicate
def research_questions_nonempty(spec: dict) -> bool:
    """At least one research question is a non-empty string."""
    questions = spec.get("research_questions")
    return isinstance(questions, list) and any(
        isinstance(question, str) and question.strip() for question in questions
    )


@_predicate
def roster_nonempty(spec: dict) -> bool:
    """The roster has at least one row with a name."""
    roster = spec.get("roster")
    return isinstance(roster, list) and any(
        isinstance(row, dict) and _text(row.get("name")) for row in roster
    )


@_predicate
def recruitment_strategy_filled(spec: dict) -> bool:
    """Sample, persona, and session length are all filled (no placeholders)."""
    return all(
        _filled_not_placeholder(spec.get(key), spec_blocks.PLACEHOLDERS[key])
        for key in ("sample_size", "persona", "session_length")
    )


@_predicate
def roster_has_scheduled(spec: dict) -> bool:
    """At least one roster row is in the Scheduled status."""
    roster = spec.get("roster") or []
    if not isinstance(roster, list):
        return False
    return any(
        isinstance(row, dict) and _text(row.get("status")).casefold() == "scheduled"
        for row in roster
    )


@_predicate
def results_filled(spec: dict) -> bool:
    """Results are filled and not the placeholder."""
    return _filled_not_placeholder(spec.get("results"), spec_blocks.PLACEHOLDERS["results"])


@_predicate
def ask_verbatim_present(spec: dict) -> bool:
    """The verbatim original ask is present and non-empty (the issue 60 ask keys).

    Standing-mandate predicate (issue 53): reachable only through checklist
    items (``lib/checklist_gate.py``), never through the reference
    requirements table, so no pinned gate output changes.
    """
    ask = spec.get("ask_verbatim")
    return isinstance(ask, str) and bool(ask.strip())


@_predicate
def ask_source_present(spec: dict) -> bool:
    """The ask source is present and non-empty (the issue 60 ask keys).

    Standing-mandate predicate (issue 53): reachable only through checklist
    items (``lib/checklist_gate.py``), never through the reference
    requirements table, so no pinned gate output changes.
    """
    source = spec.get("ask_source")
    return isinstance(source, str) and bool(source.strip())


# ---------------------------------------------------------------------------
# status matching
# ---------------------------------------------------------------------------


def _norm(text: Any) -> str:
    """Lowercase with every whitespace character removed."""
    return re.sub(r"\s+", "", str(text)).casefold()


def match_phase(name: Any, candidates: Any) -> str | None:
    """Match ``name`` against candidates: lowercase, whitespace removed,
    substring in either direction.

    An exact (normalization-equal) candidate wins; among substring hits the
    longest candidate wins (most specific). ``None`` when nothing matches.
    """
    needle = _norm(name)
    if not needle:
        return None
    for candidate in candidates:
        if _norm(candidate) == needle:
            return str(candidate)
    hits = [
        str(candidate)
        for candidate in candidates
        if needle in _norm(candidate) or _norm(candidate) in needle
    ]
    if not hits:
        return None
    return max(hits, key=lambda candidate: len(_norm(candidate)))


# ---------------------------------------------------------------------------
# configuration plumbing
# ---------------------------------------------------------------------------


def _workflow(config: dict | None) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Effective ``(phase_order, requirements)`` for a config (None = reference).

    A non-empty ``workflow.phase_order`` list replaces the reference order; a
    non-empty ``workflow.requirements`` mapping replaces the reference table
    entirely. An empty or absent key keeps the shipped reference.
    """
    order = REFERENCE_PHASE_ORDER
    requirements = dict(REFERENCE_REQUIREMENTS)
    workflow = (config or {}).get("workflow")
    if isinstance(workflow, dict):
        configured_order = workflow.get("phase_order")
        if isinstance(configured_order, list) and configured_order:
            order = tuple(str(status) for status in configured_order)
        configured_requirements = workflow.get("requirements")
        if isinstance(configured_requirements, dict) and configured_requirements:
            requirements = {
                str(phase): (
                    (str(entries),) if isinstance(entries, str) else tuple(str(entry) for entry in entries)
                )
                for phase, entries in configured_requirements.items()
                if isinstance(entries, (list, tuple, str))
            }
    return order, requirements


def unknown_requirement_keys(config: dict | None = None) -> list[str]:
    """Requirement keys that match no status in the effective phase order.

    The self-test asserts this list is empty for the reference workflow
    ("every key in workflow.requirements matches a live status name"); the
    CLI warns when an organization config ships inert keys.
    """
    order, requirements = _workflow(config)
    return [phase for phase in requirements if match_phase(phase, order) is None]


# ---------------------------------------------------------------------------
# field state
# ---------------------------------------------------------------------------


def _value_set(value: Any) -> bool:
    """A field value counts as set when it carries content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple)):
        return len(value) > 0
    return True


def build_field_state(tracker_fields: Any, config: dict | None = None) -> dict[str, bool]:
    """Map a ticket's field values to ``{requirement field key: bool}``.

    ``tracker_fields`` is the fields mapping a ticket read returned. Keys may
    be requirement keys (``research_method``), config field shorthand names
    (``method``), or tracker field ids (resolved through
    ``fields.<name>.id`` when ``config`` is passed). A mapping whose values
    are all booleans passes through as an already-built state.
    """
    fields = tracker_fields if isinstance(tracker_fields, dict) else {}
    if fields and all(isinstance(value, bool) for value in fields.values()):
        return {
            key: any(bool(fields.get(source)) for source in sources)
            for key, sources in FIELD_SOURCES.items()
        }
    name_to_id: dict[str, str] = {}
    schema = (config or {}).get("fields")
    if isinstance(schema, dict):
        for name, entry in schema.items():
            if isinstance(entry, dict) and entry.get("id"):
                name_to_id[str(name)] = str(entry["id"])
    state: dict[str, bool] = {}
    for key, sources in FIELD_SOURCES.items():
        state[key] = False
        for source in sources:
            if source in fields:
                if _value_set(fields[source]):
                    state[key] = True
                    break
            field_id = name_to_id.get(source)
            if field_id is not None and field_id in fields and _value_set(fields[field_id]):
                state[key] = True
                break
    return state


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def check_phase_readiness(
    target_status: Any,
    spec: Any,
    field_state: Any,
    config: dict | None = None,
) -> tuple[bool, list[str]]:
    """Is the ticket ready for ``target_status``? Return ``(ok, missing)``.

    ``spec`` is the study spec dict (a non-dict counts as empty, so spec
    checks fail closed). ``field_state`` is ``build_field_state`` output.
    Statuses that match no requirement key are ungated and always pass.
    Never raises.
    """
    try:
        _, requirements = _workflow(config)
        phase = match_phase(str(target_status), requirements.keys())
        if phase is None:
            return True, []
        source = spec if isinstance(spec, dict) else {}
        missing: list[str] = []
        for entry in requirements[phase]:
            kind, _, name = str(entry).partition(":")
            if kind not in ("field", "spec") or not name:
                name = str(entry)
                kind = "spec" if name in SPEC_CHECKS else "field"
            if kind == "field":
                if not isinstance(field_state, dict) or not field_state.get(name):
                    missing.append(f"field {name!r} is not set")
            elif name not in SPEC_CHECKS or not SPEC_CHECKS[name](source):
                missing.append(f"spec check failed: {name}")
        return (not missing), missing
    except Exception as exc:  # a gate must never crash a command
        return False, [f"phase gate crashed on malformed input: {exc}"]


def suggest_next_phase(
    current_status: Any,
    spec: Any,
    field_state: Any,
    config: dict | None = None,
) -> str | None:
    """The next phase in ``phase_order`` when the ticket already meets its bar.

    Looks only one phase ahead. Returns the phase name only when that phase
    has requirements and they all pass; an ungated next phase, a current
    status outside ``phase_order``, the last phase, and any failed
    requirement all return ``None``.
    """
    order, requirements = _workflow(config)
    current = match_phase(str(current_status), order)
    if current is None:
        return None
    index = order.index(current)
    if index + 1 >= len(order):
        return None
    nxt = order[index + 1]
    key = match_phase(nxt, requirements.keys())
    if key is None or not requirements[key]:
        return None
    ok, _ = check_phase_readiness(nxt, spec, field_state, config)
    return nxt if ok else None


def edit_fix(item: str) -> str:
    """The ``edit`` shorthand hint for one missing-item string ('' if unknown)."""
    if item.startswith("field '") and "' is not set" in item:
        key = item[len("field '"):].split("' is not set", 1)[0]
        return FIELD_FIX_HINTS.get(key, "")
    if item.startswith("spec check failed: "):
        predicate = item[len("spec check failed: "):].strip()
        return SPEC_FIX_HINTS.get(predicate, "")
    return ""


def missing_lines(items: Any, key: str) -> list[str]:
    """The blocked-move lines, one per gate-JSON ``missing`` entry.

    ``items`` is the ``check`` output itself (the ``{"target", "gated",
    "ok", "missing"}`` object) or the bare ``missing`` list. A ``spec
    check failed: <predicate>`` item renders its predicate in single
    quotes (the golden format); every other item renders verbatim. The
    ``-> run edit`` part drops when the entry carries no fix. Gate
    semantics stay in ``check``: this only formats what ``check`` emitted.
    """
    if isinstance(items, dict):
        items = items.get("missing")
    lines: list[str] = []
    for entry in items if isinstance(items, list) else []:
        if isinstance(entry, dict):
            item, fix = str(entry.get("item") or ""), str(entry.get("fix") or "")
        else:
            item, fix = str(entry), ""
        if item.startswith("spec check failed: "):
            item = "spec check failed: '" + item[len("spec check failed: "):].strip() + "'"
        lines.append(f"missing: {item}" + (f" -> run edit {key} {fix}" if fix else ""))
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

USAGE = """usage:
  python lib/phase_gates.py check --status "<status>" --spec <spec.json> [--fields <fields.json>]
  python lib/phase_gates.py suggest --status "<status>" --spec <spec.json> [--fields <fields.json>]
  python lib/phase_gates.py missing --json <check-output.json|-> --key <KEY>

Pass `--spec -` or `--fields -` to read that JSON from stdin (at most one
of them per run). A missing spec file counts as an empty spec (spec checks
fail closed). `missing` prints one blocked-move line per missing item of a
`check` output (pass the JSON via a file or `--json -`), in the golden
format. Exit codes: 0 pass, 1 not ready, 2 usage or config, 4
self-test failed."""


def _read_json_arg(value: str | None, label: str) -> Any:
    """Read a JSON document from a path; a missing file counts as empty."""
    try:
        return _read_json_arg_util(value, f"--{label} file", missing="empty", expanduser=False)
    except _JsonReadError as exc:
        if exc.kind == "invalid":
            raise ValueError(f"--{label} file {exc.path} is not valid JSON: {exc.exc}") from None
        raise exc.exc


def _cli_check(rest: list[str]) -> int:
    target = ""
    spec_arg: str | None = None
    fields_arg: str | None = None
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--status" and index + 1 < len(rest):
            target = rest[index + 1]
            index += 2
            continue
        if arg == "--spec" and index + 1 < len(rest):
            spec_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--fields" and index + 1 < len(rest):
            fields_arg = rest[index + 1]
            index += 2
            continue
        print(f"check: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not target:
        print(f"check: --status is required\n\n{USAGE}", file=sys.stderr)
        return 2
    try:
        spec_data = (
            json.loads(sys.stdin.read() or "{}")
            if spec_arg == "-"
            else _read_json_arg(spec_arg, "spec")
        )
        fields_data = (
            json.loads(sys.stdin.read() or "{}")
            if fields_arg == "-"
            else _read_json_arg(fields_arg, "fields")
        )
    except ValueError as exc:
        print(f"check: {exc}", file=sys.stderr)
        return 2
    try:
        config = _config.load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    for inert in unknown_requirement_keys(config):
        print(
            f"warning: workflow.requirements key {inert!r} matches no status in "
            "workflow.phase_order; it never fires.",
            file=sys.stderr,
        )
    field_state = build_field_state(fields_data, config=config)
    ok, missing = check_phase_readiness(target, spec_data, field_state, config=config)
    _, requirements = _workflow(config)
    print(
        json.dumps(
            {
                "target": target,
                "gated": match_phase(target, requirements.keys()) is not None,
                "ok": ok,
                "missing": [
                    {"item": item, "fix": edit_fix(item)} for item in missing
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


def _cli_suggest(rest: list[str]) -> int:
    target = ""
    spec_arg: str | None = None
    fields_arg: str | None = None
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--status" and index + 1 < len(rest):
            target = rest[index + 1]
            index += 2
            continue
        if arg == "--spec" and index + 1 < len(rest):
            spec_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--fields" and index + 1 < len(rest):
            fields_arg = rest[index + 1]
            index += 2
            continue
        print(f"suggest: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not target:
        print(f"suggest: --status is required\n\n{USAGE}", file=sys.stderr)
        return 2
    try:
        spec_data = (
            json.loads(sys.stdin.read() or "{}")
            if spec_arg == "-"
            else _read_json_arg(spec_arg, "spec")
        )
        fields_data = (
            json.loads(sys.stdin.read() or "{}")
            if fields_arg == "-"
            else _read_json_arg(fields_arg, "fields")
        )
    except ValueError as exc:
        print(f"suggest: {exc}", file=sys.stderr)
        return 2
    try:
        config = _config.load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    field_state = build_field_state(fields_data, config=config)
    phase = suggest_next_phase(target, spec_data, field_state, config=config)
    if phase:
        print(phase)
    return 0


def _cli_missing(rest: list[str]) -> int:
    json_arg: str | None = None
    key = ""
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--json" and index + 1 < len(rest):
            json_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--key" and index + 1 < len(rest):
            key = rest[index + 1]
            index += 2
            continue
        print(f"missing: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not json_arg or not key:
        print(f"missing: --json and --key are required\n\n{USAGE}", file=sys.stderr)
        return 2
    try:
        data = (
            json.loads(sys.stdin.read() or "{}")
            if json_arg == "-"
            else _read_json_arg(json_arg, "json")
        )
    except ValueError as exc:
        print(f"missing: {exc}", file=sys.stderr)
        return 2
    for line in missing_lines(data, key):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args and args[0] == "check":
        return _cli_check(args[1:])
    if args and args[0] == "suggest":
        return _cli_suggest(args[1:])
    if args and args[0] == "missing":
        return _cli_missing(args[1:])
    print(USAGE)
    return 2


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def _fields(**overrides: bool) -> dict[str, bool]:
    state = {key: False for key in FIELD_SOURCES}
    state.update(overrides)
    return state


if __name__ == "__main__":
    raise SystemExit(main())
