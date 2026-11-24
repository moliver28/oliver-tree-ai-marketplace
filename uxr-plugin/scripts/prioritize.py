#!/usr/bin/env python3
"""Prioritization calculator for research requests (issue 114, section 2).

One deterministic scorer for every backend. Zero LLM on the calculation
path: the score is a weighted sum over the configured inputs, computed in
plain Python from values the caller supplies. The command makes no network
call and writes nothing; it computes and prints.

Input resolution (first hit wins):

1. ``priority.formula`` set: the formula names the inputs and carries
   explicit term weights (``impact*3``). A term without an explicit weight
   takes ``priority.weights[name]`` when present, else 1.
2. ``priority.weights`` set: the inputs are the mapped field names for the
   backend, then any weight-only names; a weight-keyed input uses its
   weight, every other input carries weight 1.
3. ``prioritization.fields[<backend>]`` set: those keys are the inputs,
   weight 1 each.
4. Otherwise the built-in default, so a zero-configuration install gets a
   working calculator::

       score = impact*3 + confidence*2 + urgency*1

The backend selects the ``prioritization.fields`` mapping; the backend key
is ``tracker.kind`` (the adapter registry selector), so an adapter that
lands later lights the mapping up by kind with no calculator change. The
per-backend conventions (Jira custom field ids, GitHub label names,
GitLab labels and weights, Notion property names) live in the adapter
reference docs and in this config data, never in this code.

Normalization (documented law, one integer 1 to 3 per input):

- no rule (the input has no mapping entry): the value arrives
  pre-normalized; a number that rounds to 1, 2, or 3 passes.
- ``select``: the value must match one entry of ``values`` (the ordinal
  list, low to high; matched without case). One entry scores 1; otherwise
  the position maps proportionally: ``round(1 + 2 * position / (n - 1))``.
- ``labels``: the value is the tracker's label set for the field as one
  comma-separated token list; a token that matches an entry of ``values``
  (without case) scores at its position, the highest match wins, no match
  is a value error.
- ``number``: with ``low`` and ``high`` the value maps linearly onto 1 to
  3; without them the value is rounded and clamped onto 1 to 3.

Exit codes: 0 ok, 2 usage or configuration error (an unknown input name,
an unknown backend kind, a formula that does not parse, a missing config
key), 3 value error (a value no configured rule can normalize).

Usage::

    python scripts/prioritize.py inputs [--backend <kind>] [--json]
    python scripts/prioritize.py score --value impact=3 --value confidence=2
        [--backend <kind>] [--json]
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

try:
    from lib.config import TRACKER_KINDS, ConfigError, load_config
except ImportError:  # direct execution: python scripts/prioritize.py
    PLUGIN_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))
    from lib.config import TRACKER_KINDS, ConfigError, load_config  # type: ignore

#: The built-in default (issue 114): zero configuration, always works.
#: Input order is the printed term order.
BUILTIN_INPUTS: tuple[tuple[str, int], ...] = (
    ("impact", 3),
    ("confidence", 2),
    ("urgency", 1),
)
BUILTIN_FORMULA = "impact*3 + confidence*2 + urgency*1"

#: Mapping-entry kinds the normalizer knows.
RULE_KINDS = ("select", "number", "labels")

_TERM_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(?:\*\s*(\d+(?:\.\d+)?))?$")

USAGE = (
    "usage:\n"
    "  python scripts/prioritize.py inputs [--backend <kind>] [--json]\n"
    "  python scripts/prioritize.py score --value <name>=<value> "
    "[--backend <kind>] [--json]\n"
    "\n"
    "exit codes: 0 ok, 2 usage or config error, 3 value error."
)


class UsageError(ValueError):
    """Raised when a name, flag, formula, or config value is invalid (exit 2)."""


class NormalizeError(ValueError):
    """Raised when a raw value cannot be normalized (exit 3)."""


# ---------------------------------------------------------------------------
# config resolution (pure functions of the config dict; no file access here)
# ---------------------------------------------------------------------------


def _mapping(config: Any, dotted: str) -> dict:
    """The mapping at a dotted config path, or {} (absent or not a mapping)."""
    cursor: Any = config
    for part in dotted.split("."):
        cursor = cursor.get(part) if isinstance(cursor, dict) else None
        if cursor is None:
            return {}
    return cursor if isinstance(cursor, dict) else {}


def backend_of(config: dict, backend: str | None) -> str:
    """The effective backend kind: the flag wins, then ``tracker.kind``.

    An empty flag and an empty ``tracker.kind`` give "" (the built-in
    path). A non-empty flag must be a shipped kind (exit 2 otherwise).
    """
    kind = str(backend or "").strip()
    if not kind:
        tracker = config.get("tracker")
        kind = str(tracker.get("kind") or "").strip() if isinstance(tracker, dict) else ""
    if kind and kind not in TRACKER_KINDS:
        raise UsageError(
            f"unknown backend kind {kind!r}; shipped kinds: {', '.join(TRACKER_KINDS)}"
        )
    return kind


def field_rules(config: dict, backend: str) -> dict[str, dict]:
    """The ``prioritization.fields[<backend>]`` mapping, validated in shape.

    Each entry maps one input name to ``{id, kind, values, low, high}``;
    ``kind`` defaults to ``select`` and must be one of the rule kinds. A
    ``select`` or ``labels`` rule needs a non-empty ``values`` list.
    Entry order is the printed order; bad shapes raise exit 2.
    """
    if not backend:
        return {}
    section = _mapping(config, "prioritization.fields")
    raw = section.get(backend)
    if not isinstance(raw, dict):
        return {}
    rules: dict[str, dict] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise UsageError(f"prioritization.fields.{backend}.{name} must be a mapping")
        kind = str(entry.get("kind") or "select").strip()
        if kind not in RULE_KINDS:
            raise UsageError(
                f"prioritization.fields.{backend}.{name}.kind must be one of "
                f"{', '.join(RULE_KINDS)}; got {kind!r}"
            )
        values = entry.get("values")
        values = [str(v) for v in values] if isinstance(values, list) else []
        if kind in ("select", "labels") and not values:
            raise UsageError(
                f"prioritization.fields.{backend}.{name} needs a non-empty "
                f"values list for kind {kind}"
            )
        rules[str(name)] = {
            "id": str(entry.get("id") or ""),
            "kind": kind,
            "values": values,
            "low": entry.get("low"),
            "high": entry.get("high"),
        }
    return rules


def _parse_formula(formula: str) -> list[tuple[str, float | None]]:
    """Parse a flat sum of terms: ``name[*number] + name[*number] ...``.

    Duplicate input names raise; a malformed term raises. Returns the
    terms in order with the explicit weight (None when absent).
    """
    text = formula.strip()
    if not text:
        raise UsageError("priority.formula is empty")
    terms: list[tuple[str, float | None]] = []
    seen: set[str] = set()
    for chunk in text.split("+"):
        match = _TERM_RE.match(chunk.strip())
        if not match:
            raise UsageError(
                f"priority.formula term {chunk.strip()!r} does not parse; "
                "expected <input> or <input>*<number> in a + separated sum"
            )
        name = match.group(1)
        weight = float(match.group(2)) if match.group(2) is not None else None
        if name in seen:
            raise UsageError(f"priority.formula names {name!r} more than once")
        seen.add(name)
        terms.append((name, weight))
    return terms


def resolve_inputs(config: dict, backend: str) -> list[dict]:
    """The resolved input set in printed order: name, weight, rule.

    The resolution order is documented in the module docstring; every
    branch is a pure function of the config. A weight that is not a
    number raises exit 2.
    """
    weights_raw = _mapping(config, "priority.weights")
    weights: dict[str, float] = {}
    for name, value in weights_raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UsageError(f"priority.weights.{name} must be a number; got {value!r}")
        weights[str(name)] = float(value)
    formula = str(config.get("priority", {}).get("formula") or "").strip() \
        if isinstance(config.get("priority"), dict) else ""
    rules = field_rules(config, backend)

    inputs: list[dict] = []
    if formula:
        for name, explicit in _parse_formula(formula):
            weight = explicit if explicit is not None else weights.get(name, 1.0)
            inputs.append({"name": name, "weight": weight, "rule": rules.get(name)})
    elif weights:
        ordered = list(rules.keys()) + [n for n in weights if n not in rules]
        for name in ordered:
            inputs.append(
                {"name": name, "weight": weights.get(name, 1.0), "rule": rules.get(name)}
            )
    elif rules:
        inputs = [{"name": n, "weight": 1.0, "rule": rules[n]} for n in rules]
    else:
        inputs = [
            {"name": n, "weight": float(w), "rule": None} for n, w in BUILTIN_INPUTS
        ]
    if not inputs:
        raise UsageError("no calculator inputs resolve from the configuration")
    return inputs


def formula_text(config: dict, inputs: list[dict]) -> str:
    """The formula as one string: the override when set, else the resolved sum."""
    override = ""
    priority = config.get("priority")
    if isinstance(priority, dict):
        override = str(priority.get("formula") or "").strip()
    return override if override else " + ".join(
        f"{item['name']}*{_fmt(item['weight'])}" for item in inputs
    )


# ---------------------------------------------------------------------------
# normalization and scoring (pure)
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    """One number: integral floats print without the decimal tail."""
    return str(int(value)) if float(value).is_integer() else repr(round(float(value), 6))


def _normalized_of_position(position: int, count: int) -> int:
    """Map a 0-based position in an ordinal list of length count onto 1 to 3."""
    if count <= 1:
        return 1
    scaled = round(1 + 2 * position / (count - 1))
    return max(1, min(3, int(scaled)))


def _match_token(token: str, values: list[str]) -> int | None:
    """The position of the first values entry the token equals (without case)."""
    low = token.strip().lower()
    for position, entry in enumerate(values):
        if str(entry).strip().lower() == low:
            return position
    return None


def normalize_input(item: dict, raw: str) -> int:
    """Normalize one raw value to an integer 1 to 3 per the documented law."""
    name = item["name"]
    rule = item.get("rule")
    text = str(raw).strip()
    if rule is None:
        try:
            value = float(text)
        except ValueError as exc:
            raise NormalizeError(
                f"{name}: {text!r} has no mapping rule and is not a 1 to 3 number"
            ) from exc
        rounded = round(value)
        if rounded not in (1, 2, 3) or abs(value - rounded) > 1e-9:
            raise NormalizeError(
                f"{name}: {text!r} has no mapping rule; answer it 1 to 3 "
                "(low to high) or map it in prioritization.fields"
            )
        return int(rounded)
    kind = rule["kind"]
    if kind == "select":
        position = _match_token(text, rule["values"])
        if position is None:
            raise NormalizeError(
                f"{name}: {text!r} is not one of the configured values "
                f"({' | '.join(rule['values'])})"
            )
        return _normalized_of_position(position, len(rule["values"]))
    if kind == "labels":
        best: int | None = None
        for token in text.split(","):
            position = _match_token(token, rule["values"])
            if position is not None and (best is None or position > best):
                best = position
        if best is None:
            raise NormalizeError(
                f"{name}: no label in {text!r} matches the configured values "
                f"({' | '.join(rule['values'])})"
            )
        return _normalized_of_position(best, len(rule["values"]))
    # kind == "number"
    try:
        value = float(text)
    except ValueError as exc:
        raise NormalizeError(f"{name}: {text!r} is not a number") from exc
    low, high = rule.get("low"), rule.get("high")
    if low is not None and high is not None:
        span = float(high) - float(low)
        if span <= 0:
            raise UsageError(
                f"{name}: prioritization.fields rule needs high > low "
                f"(got low={low}, high={high})"
            )
        share = max(0.0, min(1.0, (value - float(low)) / span))
        return int(round(1 + 2 * share))
    return max(1, min(3, int(round(value))))


def score(config: dict, backend: str, raw_values: dict[str, str]) -> dict:
    """Score one request: resolved inputs, normalized values, weighted sum."""
    inputs = resolve_inputs(config, backend)
    unknown = sorted(set(raw_values) - {item["name"] for item in inputs})
    if unknown:
        raise UsageError(
            "unknown input name(s): " + ", ".join(unknown)
            + f"; configured inputs: {', '.join(item['name'] for item in inputs)}"
        )
    missing = [item["name"] for item in inputs if item["name"] not in raw_values]
    if missing:
        raise UsageError("missing input value(s): " + ", ".join(missing))
    terms: list[dict] = []
    total = 0.0
    for item in inputs:
        raw = raw_values[item["name"]]
        normalized = normalize_input(item, raw)
        product = normalized * float(item["weight"])
        total += product
        terms.append(
            {
                "input": item["name"],
                "raw": raw,
                "normalized": normalized,
                "weight": item["weight"],
                "product": product,
            }
        )
    return {
        "backend": backend,
        "formula": formula_text(config, inputs),
        "terms": terms,
        "score": total,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_plain(result: dict) -> None:
    header = result["backend"] or "no backend configured"
    print(f"prioritize: backend {header}")
    print(f"formula: {result['formula']}")
    for term in result["terms"]:
        print(
            f"{term['input']}: raw {term['raw']} -> normalized {term['normalized']}"
            f" x weight {_fmt(term['weight'])} = {_fmt(term['product'])}"
        )
    print(f"score {_fmt(result['score'])}")


def _print_inputs(config: dict, backend: str) -> None:
    inputs = resolve_inputs(config, backend)
    print(f"prioritize inputs: backend {backend or 'none (built-in)'}")
    print(f"formula: {formula_text(config, inputs)}")
    for item in inputs:
        rule = item["rule"]
        if rule is None:
            detail = "no mapping rule: answer 1 to 3"
        elif rule["kind"] == "number":
            detail = f"number (low {rule.get('low')}, high {rule.get('high')})"
        else:
            detail = f"{rule['kind']}: {' | '.join(rule['values'])}"
        source = f" id {rule['id']}" if rule is not None and rule["id"] else ""
        print(f"{item['name']}: weight {_fmt(item['weight'])} - {detail}{source}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args else 2
    command, rest = args[0], args[1:]
    if command not in ("inputs", "score"):
        print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    backend: str | None = None
    as_json = False
    values: dict[str, str] = {}
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--backend":
            index += 1
            if index >= len(rest):
                print("--backend needs a value", file=sys.stderr)
                return 2
            backend = rest[index]
        elif arg == "--json":
            as_json = True
        elif arg == "--value":
            index += 1
            if index >= len(rest) or "=" not in rest[index]:
                print("--value needs a name=value pair", file=sys.stderr)
                return 2
            name, _, value = rest[index].partition("=")
            name = name.strip()
            if not name:
                print("--value needs a name before '='", file=sys.stderr)
                return 2
            if name in values:
                print(f"--value names {name!r} more than once", file=sys.stderr)
                return 2
            values[name] = value
        elif arg.startswith("--backend="):
            backend = arg[len("--backend="):]
        else:
            print(f"unknown argument {arg!r}\n\n{USAGE}", file=sys.stderr)
            return 2
        index += 1
    if command == "score" and not values:
        print("score needs at least one --value name=value\n\n" + USAGE, file=sys.stderr)
        return 2
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"prioritize: config error: {exc}", file=sys.stderr)
        return 2
    try:
        kind = backend_of(config, backend)
        if command == "inputs":
            if as_json:
                inputs = resolve_inputs(config, kind)
                print(
                    json.dumps(
                        {
                            "backend": kind,
                            "formula": formula_text(config, inputs),
                            "inputs": [
                                {
                                    "name": item["name"],
                                    "weight": item["weight"],
                                    "rule": item["rule"],
                                }
                                for item in inputs
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                _print_inputs(config, kind)
            return 0
        result = score(config, kind, values)
        if as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            _print_plain(result)
        return 0
    except UsageError as exc:
        print(f"prioritize: {exc}", file=sys.stderr)
        return 2
    except NormalizeError as exc:
        print(f"prioritize: value error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
