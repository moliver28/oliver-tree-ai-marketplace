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

CLI (exit codes: 0 pass / 1 not ready / 2 usage or config / 4 selftest)::

    python lib/phase_gates.py check --status "Recruiting" --spec spec.json --fields fields.json
    python lib/phase_gates.py suggest --status "Recruiting" --spec spec.json --fields fields.json
    python lib/phase_gates.py missing --json check-output.json --key UXR-101
    python lib/phase_gates.py --selftest

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
  python lib/phase_gates.py --selftest

Pass `--spec -` or `--fields -` to read that JSON from stdin (at most one
of them per run). A missing spec file counts as an empty spec (spec checks
fail closed). `missing` prints one blocked-move line per missing item of a
`check` output (pass the JSON via a file or `--json -`), in the golden
format. Exit codes: 0 pass, 1 not ready, 2 usage or config, 4
self-test failed."""


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _read_json_arg(value: str | None, label: str) -> Any:
    """Read a JSON document from a path; a missing file counts as empty."""
    if value is None:
        return {}
    path = Path(value)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"--{label} file {value} is not valid JSON: {exc}") from None


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
            indent=2,
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
    if "--selftest" in args or args and args[0] == "selftest":
        return _selftest()
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


def _ready_spec() -> dict:
    """A spec that passes every reference spec predicate."""
    return {
        "history": "Support tickets doubled after the billing rework shipped.",
        "decision": "Should the redesigned invoice page ship to all tenants?",
        "hypotheses": [{"label": "H1", "text": "Admins cannot find invoice export."}],
        "research_questions": ["How do admins export invoices today?"],
        "sample_size": "8-10 admins",
        "persona": "Tenant admins",
        "session_length": "45 min interviews",
        "roster": [{"name": "Ada Example", "status": "Scheduled"}],
        "results": "Ship it: admins completed exports faster with the new page.",
    }


def _fields(**overrides: bool) -> dict[str, bool]:
    state = {key: False for key in FIELD_SOURCES}
    state.update(overrides)
    return state


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/phase_gates.py --selftest")

    spec = _ready_spec()
    all_fields = _fields(
        ux_researcher=True, pod=True, research_method=True, output_link=True
    )

    # --- every gated phase passes when everything is set ---------------------
    for phase in (
        "Planned",
        "Writing Script / Survey",
        "Recruiting",
        "Collecting Data",
        "Creating Report",
        "Done",
    ):
        ok, missing = check_phase_readiness(phase, spec, all_fields)
        check(f"ready ticket passes the gate for {phase}", ok and missing == [], str(missing))

    # --- each phase blocks on its own gap -------------------------------------
    cases = (
        ("Planned", _fields(ux_researcher=True, pod=True), _ready_spec() | {"history": "", "decision": ""}, "background_filled"),
        ("Planned", _fields(ux_researcher=True, pod=True), _ready_spec() | {"research_questions": []}, "research_questions_nonempty"),
        ("Planned", _fields(pod=True), spec, "field 'ux_researcher' is not set"),
        ("Planned", _fields(ux_researcher=True), spec, "field 'pod' is not set"),
        ("Writing Script / Survey", _fields(), spec, "field 'research_method' is not set"),
        ("Recruiting", _fields(research_method=True), _ready_spec() | {"roster": []}, "roster_nonempty"),
        ("Recruiting", _fields(research_method=True), _ready_spec() | {"persona": ""}, "recruitment_strategy_filled"),
        ("Recruiting", _fields(), spec, "field 'research_method' is not set"),
        ("Collecting Data", _fields(), _ready_spec() | {"roster": [{"name": "Bo", "status": "Outreach Sent"}]}, "roster_has_scheduled"),
        ("Creating Report", _fields(), spec, "field 'output_link' is not set"),
        ("Done", _fields(output_link=True), _ready_spec() | {"results": None}, "results_filled"),
        ("Done", _fields(), spec, "field 'output_link' is not set"),
    )
    for phase, fields, gated_spec, needle in cases:
        ok, missing = check_phase_readiness(phase, gated_spec, fields)
        check(
            f"{phase} blocks when its bar is unmet ({needle})",
            not ok and any(needle in item for item in missing),
            f"ok={ok} missing={missing}",
        )

    # --- exact missing-item strings --------------------------------------------
    ok, missing = check_phase_readiness("Done", spec, _fields())
    check(
        "field missing strings use the exact issue format",
        not ok and missing == ["field 'output_link' is not set"],
        str(missing),
    )
    ok, missing = check_phase_readiness(
        "Done", _ready_spec() | {"results": None}, _fields(output_link=True)
    )
    check(
        "spec missing strings use the exact issue format",
        not ok and missing == ["spec check failed: results_filled"],
        str(missing),
    )

    # --- slash variant and whitespace-insensitive matching ---------------------
    ok, _ = check_phase_readiness("Writing Script/Survey", spec, _fields(research_method=True))
    check("slash variant matches the phase key", ok)
    check(
        "match_phase is case- and whitespace-insensitive in both directions",
        match_phase("writing script /survey", REFERENCE_REQUIREMENTS)
        == "Writing Script / Survey"
        and match_phase("collecting", REFERENCE_REQUIREMENTS) == "Collecting Data"
        and match_phase("done", REFERENCE_REQUIREMENTS) == "Done",
    )

    # --- ungated statuses pass --------------------------------------------------
    for status in ("Summarizing Data", "Blocked", "Somewhere Unheard Of"):
        ok, missing = check_phase_readiness(status, {}, _fields())
        check(f"ungated status {status!r} passes with no requirements", ok and missing == [])

    # --- suggestion cases ---------------------------------------------------------
    check(
        "suggest returns the next phase when its bar is met",
        suggest_next_phase("Planned", spec, _fields(research_method=True))
        == "Writing Script / Survey",
    )
    check(
        "suggest returns None when the next phase fails its bar",
        suggest_next_phase("Planned", spec, _fields()) is None,
    )
    check(
        "suggest crosses into Collecting Data on a scheduled roster",
        suggest_next_phase("Recruiting", spec, _fields(research_method=True))
        == "Collecting Data",
    )
    check(
        "suggest returns None when no roster row is scheduled",
        suggest_next_phase(
            "Recruiting", _ready_spec() | {"roster": [{"name": "Bo", "status": "No Response"}]},
            _fields(research_method=True),
        )
        is None,
    )
    check(
        "suggest returns None when the next phase is ungated (Collecting Data -> Summarizing Data)",
        suggest_next_phase("Collecting Data", spec, _fields()) is None,
    )
    check(
        "suggest reaches Done only with output and results",
        suggest_next_phase("Creating Report", spec, _fields(output_link=True)) == "Done"
        and suggest_next_phase("Creating Report", spec, _fields()) is None,
    )
    check(
        "suggest returns None at the last phase and off the phase_order",
        suggest_next_phase("Done", spec, all_fields) is None
        and suggest_next_phase("Blocked", spec, all_fields) is None,
    )

    # --- config overrides ------------------------------------------------------------
    custom = {
        "workflow": {
            "phase_order": ["Drafting", "Fieldwork", "Wrapped"],
            "requirements": {
                "Fieldwork": ("spec:roster_nonempty",),
                "Wrapped": ("spec:results_filled",),
            },
        }
    }
    check(
        "config phase_order and requirements drive the gate",
        check_phase_readiness("Fieldwork", _ready_spec() | {"roster": []}, _fields(), config=custom)
        == (False, ["spec check failed: roster_nonempty"])
        and check_phase_readiness("Drafting", {}, _fields(), config=custom) == (True, [])
        and suggest_next_phase("Drafting", _ready_spec() | {"roster": []}, _fields(), config=custom)
        is None
        and suggest_next_phase("Drafting", _ready_spec(), _fields(), config=custom)
        == "Fieldwork",
    )
    check(
        "config phase_order replaces the reference order",
        unknown_requirement_keys(custom) == [],
    )
    check(
        "empty config requirements keep the reference table",
        check_phase_readiness("Done", {}, _fields(output_link=True), config={"workflow": {"requirements": {}}})
        == (False, ["spec check failed: results_filled"]),
    )

    # --- every requirements key matches a live status name ----------------------------
    check(
        "every reference requirements key matches a phase_order status",
        unknown_requirement_keys() == [],
        str(unknown_requirement_keys()),
    )
    check(
        "every field fix hint covers a requirement field key",
        set(FIELD_FIX_HINTS) == set(FIELD_SOURCES),
    )
    check(
        "every spec predicate has a fix hint",
        set(SPEC_FIX_HINTS) == set(SPEC_CHECKS),
        f"predicates={sorted(SPEC_CHECKS)} hints={sorted(SPEC_FIX_HINTS)}",
    )
    check(
        "edit_fix maps missing items to edit shorthands",
        edit_fix("field 'research_method' is not set") == "method=<value>"
        and edit_fix("spec check failed: results_filled") == "results=<text>"
        and edit_fix("phase gate crashed on malformed input: x") == "",
    )

    # --- missing_lines (the blocked-move golden format) -------------------------
    check(
        "missing_lines quotes the spec-check predicate",
        missing_lines([{"item": "spec check failed: roster_has_scheduled",
                        "fix": "roster~=Name|status=Scheduled"}], "UXR-101")
        == ["missing: spec check failed: 'roster_has_scheduled' -> run edit UXR-101 roster~=Name|status=Scheduled"],
    )
    check(
        "missing_lines renders other items verbatim and drops an empty fix",
        missing_lines([{"item": "field 'research_method' is not set", "fix": ""}], "ABC-42")
        == ["missing: field 'research_method' is not set"],
    )
    check(
        "missing_lines accepts the whole check output",
        missing_lines({"ok": False, "missing": [{"item": "spec check failed: results_filled",
                                                 "fix": "results=<text>"}]}, "UXR-101")
        == ["missing: spec check failed: 'results_filled' -> run edit UXR-101 results=<text>"],
    )
    gates_fixture = PLUGIN_ROOT / "tests" / "fixtures" / "gates"
    blocked_path, blocked_expected = gates_fixture / "blocked-move.json", gates_fixture / "blocked-move.expected.txt"
    if blocked_path.is_file() and blocked_expected.is_file():
        case = json.loads(blocked_path.read_text(encoding="utf-8"))
        got = missing_lines(case, case["key"])
        check("blocked-move fixture byte-matches the golden line",
              "\n".join(got) + ("\n" if got else "") == blocked_expected.read_text(encoding="utf-8"),
              repr(got))
    else:
        check("blocked-move fixture present", False, "missing tests/fixtures/gates")

    # --- build_field_state --------------------------------------------------------------
    check(
        "field state reads shorthand-named values",
        build_field_state({"uxr": "Ada", "pod": ["Platform"], "method": [], "output": ""})
        == {"ux_researcher": True, "pod": True, "research_method": False, "output_link": False},
    )
    check(
        "field state resolves tracker field ids through config",
        build_field_state(
            {"cf_uxr": "Ada", "cf_method": "Survey"},
            config={"fields": {"uxr": {"id": "cf_uxr"}, "method": {"id": "cf_method"}}},
        )
        == {"ux_researcher": True, "pod": False, "research_method": True, "output_link": False},
    )
    check(
        "boolean field state passes through",
        build_field_state({"research_method": True})
        == {"ux_researcher": False, "pod": False, "research_method": True, "output_link": False},
    )
    check(
        "empty and whitespace values count as unset; non-dict input counts as nothing",
        build_field_state({"pod": "   ", "method": {}})["pod"] is False
        and build_field_state(None) == {key: False for key in FIELD_SOURCES},
    )

    # --- gates never raise ----------------------------------------------------------------
    ok, missing = check_phase_readiness("Done", "not a spec", None)
    check(
        "non-dict spec and missing field state fail closed without raising",
        ok is False and "results_filled" in " ".join(missing),
        str(missing),
    )
    ok, _ = check_phase_readiness(None, None, None)
    check("None target status matches nothing and passes", ok)

    # --- the real CLI: a blocked check exits 1, a pass exits 0 ------------------------------
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec_file = tmp / "spec.json"
            spec_file.write_text(json.dumps(_ready_spec()), encoding="utf-8")
            blocked = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py"),
                 "check", "--status", "Recruiting", "--spec", str(spec_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check(
                "CLI check on an empty-fields ticket exits 1 with fix hints",
                blocked.returncode == 1
                and '"ok": false' in blocked.stdout
                and "method=<value>" in blocked.stdout,
                f"code={blocked.returncode} out={blocked.stdout[:200]!r}",
            )
            fields_file = tmp / "fields.json"
            fields_file.write_text(
                json.dumps({"output": "https://example.com/report"}), encoding="utf-8"
            )
            passing = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py"),
                 "suggest", "--status", "Creating Report", "--spec", str(spec_file),
                 "--fields", str(fields_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check(
                "CLI suggest on a ready ticket prints the phase and exits 0",
                passing.returncode == 0 and passing.stdout.strip() == "Done",
                f"code={passing.returncode} out={passing.stdout!r}",
            )
            usage = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py")],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check("CLI with no subcommand prints usage and exits 2", usage.returncode == 2)
    except OSError as exc:
        check("CLI subprocess checks ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
