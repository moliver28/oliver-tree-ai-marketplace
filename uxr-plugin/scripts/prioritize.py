#!/usr/bin/env python3
"""Prioritization calculator for research requests (issue 114, section 2).

One deterministic scorer for every backend. Zero LLM on the calculation
path: the score is computed in plain Python from values the caller
supplies or answers at runtime. The command makes no network call; it
computes, optionally asks and records, and prints.

Default preset (MO ruling 2026-11-24): the GitLab handbook priority
calculator, so a zero-configuration install scores. Source of the scale
wording and the bands:
https://handbook.gitlab.com/handbook/upstream-studios/experience-research/research-prioritization/

Six criteria - impact, users, dependency, timeline, alternatives,
alignment - each scored 1 to 5, 1 = most urgent, per the handbook scale
wording (printed by ``inputs`` and by the runtime ask). Aggregation is
the unweighted average (sum / 6), and the average maps onto the bands
verbatim::

    mean <= 1.5   P1 Must Do
    mean <= 2.4   P2 Should Do
    mean <= 3.5   P3 Nice to Do
    mean <= 4.5   P4 Backlog
    mean > 4.5    Will Not Do

Both calculators only generate recommendations; the researcher and the
stakeholders decide and agree on the final priority level (handbook
law).

Input resolution (first hit wins):

1. ``priority.formula`` set: the weighted-sum mode - the custom-formula
   path. The formula names the inputs and carries explicit term weights
   (``impact*3``). A term without an explicit weight takes
   ``priority.weights[name]`` when present, else 1.
2. ``priority.weights`` set: the weighted-sum mode. The inputs are the
   mapped field names for the backend, then any weight-only names; a
   weight-keyed input uses its weight, every other input carries
   weight 1.
3. Otherwise the handbook preset runs. ``prioritization.fields[<backend>]``
   maps each criterion to the tracker's field (a rule); a criterion with
   no rule is answered 1 to 5 directly, or asked at runtime with
   ``--ask``. A mapping naming a non-criterion input is a usage error:
   to score other inputs, set ``priority.weights`` or ``priority.formula``.

The backend selects the ``prioritization.fields`` mapping; the backend key
is ``tracker.kind`` (the adapter registry selector), so an adapter that
lands later lights the mapping up by kind with no calculator change. The
per-backend conventions (Jira custom field ids, GitHub label names,
GitLab labels and weights, Notion property names) live in the adapter
reference docs and in this config data, never in this code.

Normalization (documented law, one integer per input):

- preset mode: the integers 1 to 5, 1 = most urgent.
  - no rule (the criterion has no mapping entry): the value arrives
    pre-normalized; a number that rounds to 1, 2, 3, 4, or 5 passes.
  - ``select``: the value must match one entry of ``values`` (the ordinal
    list, most urgent first; matched without case). One entry scores 1;
    otherwise the position maps proportionally:
    ``round(1 + 4 * position / (n - 1))``.
  - ``labels``: the value is the tracker's label set for the field as one
    comma-separated token list; a token that matches an entry of
    ``values`` (without case) scores at its position, the highest match
    wins, no match is a value error.
  - ``number``: with ``low`` and ``high`` the value maps linearly onto
    1 to 5; without them the value is rounded and clamped onto 1 to 5.
- weighted-sum mode: the integers 1 to 3, the shipped override law.

Support mode (``--support``, MO ruling 2026-11-24, same handbook source):
the per-project support-level calculator. Six per-project judgments, not
tracker fields, scored and summed: Type (foundational 3 / problem
validation 2 / solution validation 1), Ownership (yes 3 / somewhat 2 /
no 1), Design Support (study led by UXR 3 / requesting team has
designers 2 / no designers 1), Complexity (yes 2 / no 1 / unknown 0),
Skill Development (yes 3 / somewhat 2 / no 1), Confidence (high 3 /
medium 2 / low 1). The sum divided by the total possible score
(17 - the summed maxima 3+3+3+2+3+3; divisor correction 2026-11-24) is
the percentage, and the percentage names the level with the MO-renamed
labels - never the handbook's metal names::

    > 80%    UXR to Lead     - the researcher drives the study end to end.
    51-80%   UXR to Support  - the researcher takes specified tasks
                               within the study.
    <= 50%   UXR to Review   - the researcher is consulted and reviews
                               the team's work.

Support criteria are collected through the same runtime ask when
supplied values are missing.

Runtime ask (``--ask``, preset and support modes): a missing tracker
field is asked at runtime - one deterministic numbered prompt printing
that criterion's handbook scale wording; the answer is recorded (in the
result and, with ``--record <path>``, as a deterministic JSON file) and
used. The ask never invents a value: an out-of-range answer gets one
bounded re-ask, then a value error; an ended ask (EOF) is a value error.
The weighted-sum mode keeps the shipped missing-input usage error.

Exit codes: 0 ok, 2 usage or configuration error (an unknown input name,
an unknown backend kind, a formula that does not parse, a missing config
key), 3 value error (a value no configured rule can normalize, an ended
ask, or an unwritable ``--record`` path).

Usage::

    python scripts/prioritize.py inputs [--backend <kind>] [--support] [--json]
    python scripts/prioritize.py score --value impact=2 --value users=3 ...
        [--backend <kind>] [--json]
    python scripts/prioritize.py score --ask [--record <path>] ...
    python scripts/prioritize.py score --support [--ask] [--record <path>] ...
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from lib.config import TRACKER_KINDS, ConfigError, load_config
except ImportError:  # direct execution: python scripts/prioritize.py
    PLUGIN_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))
    from lib.config import TRACKER_KINDS, ConfigError, load_config  # type: ignore

#: Source of the preset scale wording and the bands (cited in
#: references/onboarding.md and config/org.example.yaml).
PRESET_URL = (
    "https://handbook.gitlab.com/handbook/upstream-studios/experience-research/"
    "research-prioritization/"
)

#: The preset criterion scale: one integer 1 to 5, 1 = most urgent.
PRESET_SCALE = 5
#: The weighted-sum override scale (the shipped law).
SUM_SCALE = 3

#: The default preset (issue 114, MO ruling 2026-11-24): the GitLab
#: handbook priority calculator, verbatim wording per criterion.
PRESET_CRITERIA: tuple[dict[str, Any], ...] = (
    {
        "name": "impact",
        "question": "What is the business impact if we don't do this research?",
        "scale": (
            "Critical Impact - major risks",
            "High Impact - significant opportunity",
            "Moderate impact - helpful insights",
            "Low impact - nice to have",
            "Minimal impact - no clear case",
        ),
    },
    {
        "name": "users",
        "question": "How many users/customers would this affect?",
        "scale": (
            "All users/critical segment",
            "Large user segment",
            "Medium user segment",
            "Small user segment",
            "Very few users",
        ),
    },
    {
        "name": "dependency",
        "question": "Is this blocking any immediate decisions?",
        "scale": (
            "Blocking critical launch",
            "Blocking important decision",
            "Input needed soon",
            "Future planning",
            "No specific decision",
        ),
    },
    {
        "name": "timeline",
        "question": "What is the timeline flexibility?",
        "scale": (
            "This quarter",
            "Immediate (this month)",
            "Within 6 months",
            "Within 9 months",
            "No timeline pressure",
        ),
    },
    {
        "name": "alternatives",
        "question": "Are there alternative ways to get this information?",
        "scale": (
            "No alternatives exist",
            "Limited alternatives",
            "Some alternatives",
            "Some good alternatives",
            "Many alternatives",
        ),
    },
    {
        "name": "alignment",
        "question": "How does this align with our strategic goals?",
        "scale": (
            "Core strategic priority",
            "Aligns with quarterly goals",
            "Support team objectives",
            "Indirect alignment",
            "No clear alignment",
        ),
    },
)

PRESET_NAMES: tuple[str, ...] = tuple(str(c["name"]) for c in PRESET_CRITERIA)

#: The preset aggregation: the unweighted average (sum / 6).
PRESET_FORMULA = "mean(" + ", ".join(PRESET_NAMES) + ")"

#: The bands, names verbatim (MO ruling 2026-11-24): the first upper
#: bound the mean does not exceed names the band; the open tail is last.
PRESET_BANDS: tuple[tuple[float | None, str], ...] = (
    (1.5, "P1 Must Do"),
    (2.4, "P2 Should Do"),
    (3.5, "P3 Nice to Do"),
    (4.5, "P4 Backlog"),
    (None, "Will Not Do"),
)

#: The support-level calculator: six per-project judgments, not tracker
#: fields, summed against the total possible score. Handbook criteria
#: and point values, verbatim; the choice tokens are the ask's accepted
#: names (a numbered answer always works too). The total possible is
#: the summed maxima 3+3+3+2+3+3 = 17 (divisor correction 2026-11-24:
#: the earlier 16 was arithmetic error), so the all-max judgment lands
#: exactly 100 percent.
SUPPORT_TOTAL = 17

SUPPORT_CRITERIA: tuple[dict[str, Any], ...] = (
    {
        "name": "type",
        "label": "Type",
        "question": "The type of research the project falls into.",
        "choices": (
            ("foundational", 3),
            ("problem validation", 2),
            ("solution validation", 1),
        ),
    },
    {
        "name": "ownership",
        "label": "Ownership",
        "question": "Can this research be supported by someone other than a "
        "UX Researcher?",
        "choices": (("yes", 3), ("somewhat", 2), ("no", 1)),
    },
    {
        "name": "design",
        "label": "Design Support",
        "question": "Is this project being requested by a product team with "
        "designers, or created and led by UX Research?",
        "choices": (
            ("study led by uxr", 3),
            ("requesting team has designers", 2),
            ("no designers", 1),
        ),
    },
    {
        "name": "complexity",
        "label": "Complexity",
        "question": "Does this project involve multiple studies or methodologies?",
        "choices": (("yes", 2), ("no", 1), ("unknown", 0)),
    },
    {
        "name": "skill",
        "label": "Skill Development",
        "question": "Will this support skill development for the team or refine "
        "a process if a UX Researcher is involved?",
        "choices": (("yes", 3), ("somewhat", 2), ("no", 1)),
    },
    {
        "name": "confidence",
        "label": "Confidence",
        "question": "What level of confidence or knowledge do you have in the "
        "proposed solution or area of focus?",
        "choices": (("high", 3), ("medium", 2), ("low", 1)),
    },
)

SUPPORT_NAMES: tuple[str, ...] = tuple(str(c["name"]) for c in SUPPORT_CRITERIA)

#: The MO-renamed level labels (2026-11-24) with the one-line behavior
#: each names. The handbook's former metal-name labels never ship - the
#: parity suite pins their absence from this file.
SUPPORT_LEVELS: tuple[tuple[str, str], ...] = (
    ("UXR to Lead", "the researcher drives the study end to end"),
    ("UXR to Support", "the researcher takes specified tasks within the study"),
    ("UXR to Review", "the researcher is consulted and reviews the team's work"),
)


#: Mapping-entry kinds the normalizer knows.
RULE_KINDS = ("select", "number", "labels")

_TERM_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*(?:\*\s*(\d+(?:\.\d+)?))?$")

USAGE = (
    "usage:\n"
    "  python scripts/prioritize.py inputs [--backend <kind>] [--support] [--json]\n"
    "  python scripts/prioritize.py score --value <name>=<value> "
    "[--backend <kind>] [--support] [--ask] [--record <path>] [--json]\n"
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


def mode_of(config: dict) -> str:
    """The calculator mode: ``sum`` when formula or weights override, else
    ``preset``. Empty strings and empty mappings ship and mean preset."""
    priority = config.get("priority")
    if isinstance(priority, dict) and str(priority.get("formula") or "").strip():
        return "sum"
    if _mapping(config, "priority.weights"):
        return "sum"
    return "preset"


def backend_of(config: dict, backend: str | None) -> str:
    """The effective backend kind: the flag wins, then ``tracker.kind``.

    An empty flag and an empty ``tracker.kind`` give "" (the preset path
    with no backend mapping). A non-empty flag must be a shipped kind
    (exit 2 otherwise).
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
                "values list for kind " + kind
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
    """The resolved input set in printed order: name, weight, scale, rule.

    The resolution order is documented in the module docstring; every
    branch is a pure function of the config. A weight that is not a
    number raises exit 2. In preset mode a mapping naming a
    non-criterion input raises exit 2.
    """
    rules = field_rules(config, backend)
    if mode_of(config) == "sum":
        weights_raw = _mapping(config, "priority.weights")
        weights: dict[str, float] = {}
        for name, value in weights_raw.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UsageError(f"priority.weights.{name} must be a number; got {value!r}")
            weights[str(name)] = float(value)
        formula = str(config.get("priority", {}).get("formula") or "").strip() \
            if isinstance(config.get("priority"), dict) else ""
        inputs: list[dict] = []
        if formula:
            for name, explicit in _parse_formula(formula):
                weight = explicit if explicit is not None else weights.get(name, 1.0)
                inputs.append(
                    {"name": name, "weight": weight, "scale": SUM_SCALE, "rule": rules.get(name)}
                )
        else:
            ordered = list(rules.keys()) + [n for n in weights if n not in rules]
            for name in ordered:
                inputs.append(
                    {
                        "name": name,
                        "weight": weights.get(name, 1.0),
                        "scale": SUM_SCALE,
                        "rule": rules.get(name),
                    }
                )
        if not inputs:
            raise UsageError("no calculator inputs resolve from the configuration")
        return inputs
    unknown = sorted(set(rules) - set(PRESET_NAMES))
    if unknown:
        raise UsageError(
            "prioritization.fields names non-preset input(s): " + ", ".join(unknown)
            + "; the preset criteria: " + ", ".join(PRESET_NAMES)
            + " (to score other inputs, set priority.weights or priority.formula)"
        )
    return [
        {
            "name": str(criterion["name"]),
            "weight": 1.0,
            "scale": PRESET_SCALE,
            "rule": rules.get(str(criterion["name"])),
        }
        for criterion in PRESET_CRITERIA
    ]


def formula_text(config: dict, inputs: list[dict]) -> str:
    """The formula as one string: the preset mean, the override when set,
    else the resolved weighted sum."""
    if mode_of(config) == "preset":
        return PRESET_FORMULA
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


def _norm_token(text: str) -> str:
    """One token normalized for matching: case-folded, spaced, stripped."""
    return " ".join(str(text).strip().lower().split())


def _normalized_of_position(position: int, count: int, scale: int) -> int:
    """Map a 0-based position in an ordinal list of length count onto 1..scale."""
    if count <= 1:
        return 1
    scaled = round(1 + (scale - 1) * position / (count - 1))
    return max(1, min(scale, int(scaled)))


def _match_token(token: str, values: list[str]) -> int | None:
    """The position of the first values entry the token equals (without case)."""
    low = _norm_token(token)
    for position, entry in enumerate(values):
        if _norm_token(entry) == low:
            return position
    return None


def normalize_input(item: dict, raw: str) -> int:
    """Normalize one raw value onto the input's scale, per the documented law."""
    name = item["name"]
    rule = item.get("rule")
    scale = int(item.get("scale", SUM_SCALE))
    text = str(raw).strip()
    if rule is None:
        try:
            value = float(text)
        except ValueError as exc:
            raise NormalizeError(
                f"{name}: {text!r} has no mapping rule and is not a 1 to {scale} number"
            ) from exc
        rounded = round(value)
        if rounded not in range(1, scale + 1) or abs(value - rounded) > 1e-9:
            raise NormalizeError(
                f"{name}: {text!r} has no mapping rule; answer it 1 to {scale} "
                "(1 = most urgent) or map it in prioritization.fields"
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
        return _normalized_of_position(position, len(rule["values"]), scale)
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
        return _normalized_of_position(best, len(rule["values"]), scale)
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
        return int(round(1 + (scale - 1) * share))
    return max(1, min(scale, int(round(value))))


def band_of(mean: float) -> str:
    """The band name for one preset mean, verbatim (MO ruling 2026-11-24)."""
    for upper, name in PRESET_BANDS:
        if upper is None or mean <= upper:
            return name
    return PRESET_BANDS[-1][1]


def support_points(name: str, raw: str) -> tuple[int, str]:
    """One support criterion value as ``(points, choice)``.

    The answer is a 1-based choice number or a choice name (without
    case); anything else is a value error.
    """
    criterion = next((c for c in SUPPORT_CRITERIA if str(c["name"]) == name), None)
    if criterion is None:
        raise UsageError(f"unknown support criterion {name!r}")
    choices = [(str(label), int(points)) for label, points in criterion["choices"]]
    token = _norm_token(raw)
    picked: tuple[str, int] | None = None
    if token.isdigit():
        index = int(token)
        if 1 <= index <= len(choices):
            picked = choices[index - 1]
    else:
        picked = next((c for c in choices if _norm_token(c[0]) == token), None)
    if picked is None:
        raise NormalizeError(
            f"{name}: {raw!r} is not one of the choices ("
            + " | ".join(label for label, _ in choices)
            + ") or a choice number 1 to " + str(len(choices))
        )
    return picked[1], picked[0]


def support_level(percent: float) -> str:
    """The level label for one support percentage (MO renames, 2026-11-24).

    The law: above 80 percent is ``UXR to Lead``; above 50 through 80 is
    ``UXR to Support``; 50 and below is ``UXR to Review``. The real
    percentages are multiples of 100/17 (sum / 17), so the CLI lands on
    82.35, 76.47, 52.94, and 47.06 around the named bounds 80, 51, and
    50.
    """
    if percent > 80.0:
        return "UXR to Lead"
    if percent > 50.0:
        return "UXR to Support"
    return "UXR to Review"


def score(config: dict, backend: str, raw_values: dict[str, str],
          asked: dict[str, str] | None = None) -> dict:
    """Score one request: resolved inputs, normalized values, aggregate.

    Preset mode aggregates the unweighted mean and names the band;
    weighted-sum mode sums the weighted terms. ``asked`` carries the
    runtime-asked answers (already on the scale, so a number bypasses
    the rule; a rule token normalizes through it).
    """
    asked = asked or {}
    inputs = resolve_inputs(config, backend)
    names = [item["name"] for item in inputs]
    unknown = sorted(set(raw_values) - set(names))
    if unknown:
        raise UsageError(
            "unknown input name(s): " + ", ".join(unknown)
            + f"; configured inputs: {', '.join(names)}"
        )
    missing = [item["name"] for item in inputs if item["name"] not in raw_values]
    if missing:
        raise UsageError(
            "missing input value(s): " + ", ".join(missing)
            + " (pass --ask to answer the missing ones at runtime)"
        )
    mode = mode_of(config)
    terms: list[dict] = []
    aggregate = 0.0
    for item in inputs:
        raw = raw_values[item["name"]]
        if item["name"] in asked and str(raw).strip().isdigit():
            # The ask's numbered answer is already the scale value (the
            # ask validated the range); a rule token normalizes below.
            normalized = int(str(raw).strip())
        else:
            normalized = normalize_input(item, raw)
        product = normalized * float(item["weight"])
        aggregate += product
        terms.append(
            {
                "input": item["name"],
                "raw": raw,
                "normalized": normalized,
                "weight": float(item["weight"]),
                "product": product,
            }
        )
    if mode == "preset":
        mean = round(aggregate / len(inputs), 4)
        return {
            "mode": "preset",
            "backend": backend,
            "source": PRESET_URL,
            "formula": PRESET_FORMULA,
            "terms": terms,
            "total": aggregate,
            "mean": mean,
            "band": band_of(aggregate / len(inputs)),
            "asked": [item["name"] for item in inputs if item["name"] in asked],
        }
    return {
        "mode": "sum",
        "backend": backend,
        "formula": formula_text(config, inputs),
        "terms": terms,
        "score": aggregate,
        "asked": [item["name"] for item in inputs if item["name"] in asked],
    }


def support_score(raw_values: dict[str, str],
                  asked: dict[str, str] | None = None) -> dict:
    """Score one request in support mode: points, percentage, level."""
    asked = asked or {}
    unknown = sorted(set(raw_values) - set(SUPPORT_NAMES))
    if unknown:
        raise UsageError(
            "unknown support criterion/criteria: " + ", ".join(unknown)
            + f"; the six: {', '.join(SUPPORT_NAMES)}"
        )
    missing = [name for name in SUPPORT_NAMES if name not in raw_values]
    if missing:
        raise UsageError(
            "missing support criterion value(s): " + ", ".join(missing)
            + " (pass --ask to answer the missing ones at runtime)"
        )
    terms: list[dict] = []
    total = 0
    for criterion in SUPPORT_CRITERIA:
        name = str(criterion["name"])
        raw = raw_values[name]
        points, choice = support_points(name, raw)
        total += points
        terms.append(
            {
                "input": name,
                "label": str(criterion["label"]),
                "raw": raw,
                "choice": choice,
                "points": points,
            }
        )
    percent = round(total / SUPPORT_TOTAL * 100.0, 2)
    return {
        "mode": "support",
        "formula": f"sum of the six criteria / {SUPPORT_TOTAL}",
        "terms": terms,
        "total": total,
        "possible": SUPPORT_TOTAL,
        "percent": percent,
        "level": support_level(total / SUPPORT_TOTAL * 100.0),
        "asked": [str(c["name"]) for c in SUPPORT_CRITERIA if str(c["name"]) in asked],
    }


# ---------------------------------------------------------------------------
# the runtime ask (deterministic, zero-LLM; one bounded re-ask)
# ---------------------------------------------------------------------------


def _ask(name: str, header: list[str], low: int, high: int,
         tokens: dict[str, str] | None = None) -> str:
    """One deterministic numbered ask; one bounded re-ask, then exit 3.

    The header lists the numbered options (the handbook scale wording,
    or the support choices). A number in range is accepted verbatim; a
    token matching ``tokens`` (without case) is accepted as its mapped
    canonical value. The ask never invents a value. The prompts print on
    stderr, so stdout stays parseable (``--json`` stays pure JSON).
    """
    prompt = "\n".join(header) + f"\nanswer {low}-{high}: "
    answer = ""
    for attempt in range(2):
        print(prompt, end="", file=sys.stderr, flush=True)
        try:
            answer = input().strip()
        except EOFError as exc:
            print(file=sys.stderr)
            raise NormalizeError(f"{name}: the ask ended without an answer") from exc
        if answer.isdigit() and low <= int(answer) <= high:
            print(file=sys.stderr)
            return str(int(answer))
        if tokens is not None:
            hit = tokens.get(_norm_token(answer))
            if hit is not None:
                print(file=sys.stderr)
                return hit
        prompt = f"answer {low}-{high} (one of the numbered options above): "
    print(file=sys.stderr)
    raise NormalizeError(
        f"{name}: {answer!r} is not an answer the ask accepts "
        f"(expected a number {low} to {high})"
        + ("" if not tokens else " or one of: " + " | ".join(sorted(set(tokens.values()))))
    )


def _criterion_of(name: str) -> dict | None:
    return next((c for c in PRESET_CRITERIA if str(c["name"]) == name), None)


def _scale_lines(criterion: dict | None) -> list[str]:
    if criterion is None:
        return []
    return [
        f"  {position} = {wording}"
        for position, wording in enumerate(criterion["scale"], start=1)
    ]


def ask_missing_preset(inputs: list[dict]) -> dict[str, str]:
    """Ask every preset criterion with no supplied value (exit 3 on refusal).

    The prompt prints the criterion's handbook scale wording verbatim; a
    mapped criterion's tracker-side values print as accepted tokens too.
    """
    answered: dict[str, str] = {}
    for item in inputs:
        name = item["name"]
        rule = item.get("rule")
        criterion = _criterion_of(name)
        header = [f"{name}: {criterion['question']}"] if criterion else [f"{name}:"]
        header.extend(_scale_lines(criterion))
        tokens: dict[str, str] | None = None
        if rule is not None:
            header.append(f"  tracker values: {' | '.join(rule['values'])}")
            tokens = {_norm_token(v): str(v) for v in rule["values"]}
        answered[name] = _ask(name, header, 1, int(item.get("scale", PRESET_SCALE)), tokens)
    return answered


def ask_missing_support(skip: set[str] | None = None) -> dict[str, str]:
    """Ask every support criterion with no supplied value (exit 3 on refusal).

    ``skip`` names the criteria already answered; they are never prompted.
    """
    answered: dict[str, str] = {}
    for criterion in SUPPORT_CRITERIA:
        name = str(criterion["name"])
        if name in (skip or set()):
            continue
        header = [f"{criterion['label']}: {criterion['question']}"]
        for position, (label, points) in enumerate(criterion["choices"], start=1):
            header.append(f"  {position} = {label} ({points} points)")
        answered[name] = _ask(name, header, 1, len(criterion["choices"]))
    return answered


def write_record(path: str, result: dict) -> None:
    """Write the deterministic result record (``--record``); OSError raises."""
    record = dict(result)
    record["record_format"] = 1
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_plain(result: dict) -> None:
    if result["mode"] == "support":
        print("prioritize: support mode")
        print(f"formula: {result['formula']}")
        for term in result["terms"]:
            print(f"{term['label']}: {term['choice']} = {term['points']} points")
        print(f"total {result['total']} of {result['possible']} "
              f"-> {_fmt(result['percent'])}% -> {result['level']}")
    elif result["mode"] == "preset":
        header = result["backend"] or "no backend mapping"
        print(f"prioritize: preset backend {header}")
        print(f"formula: {result['formula']}")
        for term in result["terms"]:
            print(f"{term['input']}: raw {term['raw']} -> {term['normalized']}")
        print(f"mean {_fmt(result['mean'])} -> {result['band']}")
    else:
        header = result["backend"] or "no backend configured"
        print(f"prioritize: backend {header}")
        print(f"formula: {result['formula']}")
        for term in result["terms"]:
            print(
                f"{term['input']}: raw {term['raw']} -> normalized {term['normalized']}"
                f" x weight {_fmt(term['weight'])} = {_fmt(term['product'])}"
            )
        print(f"score {_fmt(result['score'])}")
    if result.get("asked"):
        print(f"asked at runtime: {', '.join(result['asked'])}")


def _print_preset_inputs(inputs: list[dict]) -> None:
    print("prioritize inputs: preset (GitLab handbook priority calculator)")
    print(f"source: {PRESET_URL}")
    print(f"formula: {PRESET_FORMULA}")
    print("bands: <=1.5 P1 Must Do | <=2.4 P2 Should Do | <=3.5 P3 Nice to Do "
          "| <=4.5 P4 Backlog | >4.5 Will Not Do")
    for item in inputs:
        criterion = _criterion_of(item["name"])
        if criterion:
            print(f"{item['name']}: {criterion['question']}")
            for line in _scale_lines(criterion):
                print(line)
        else:
            print(f"{item['name']}: weight {_fmt(item['weight'])}")
        rule = item["rule"]
        if rule is not None:
            source = f" id {rule['id']}" if rule["id"] else ""
            detail = (
                f"number (low {rule.get('low')}, high {rule.get('high')})"
                if rule["kind"] == "number"
                else f"{rule['kind']}: {' | '.join(rule['values'])}"
            )
            print(f"  mapped: {detail}{source}")
        else:
            print("  not mapped: answered 1 to 5 at scoring time, or asked at runtime")


def _print_support_inputs() -> None:
    print(f"prioritize inputs: support mode (sum / {SUPPORT_TOTAL})")
    for criterion in SUPPORT_CRITERIA:
        print(f"{criterion['label']}: {criterion['question']}")
        for position, (label, points) in enumerate(criterion["choices"], start=1):
            print(f"  {position} = {label} ({points} points)")
    print(f"total possible: {SUPPORT_TOTAL}")
    print("levels: >80% UXR to Lead (the researcher drives the study end to end) "
          "| 51-80% UXR to Support (the researcher takes specified tasks within "
          "the study) | <=50% UXR to Review (the researcher is consulted and "
          "reviews the team's work)")


def _print_sum_inputs(config: dict, kind: str) -> None:
    inputs = resolve_inputs(config, kind)
    print(f"prioritize inputs: weighted sum, backend {kind or 'none'}")
    print(f"formula: {formula_text(config, inputs)}")
    for item in inputs:
        rule = item["rule"]
        if rule is None:
            detail = f"no mapping rule: answer 1 to {item['scale']}"
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
    as_support = False
    do_ask = False
    record_to = ""
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
        elif arg == "--support":
            as_support = True
        elif arg == "--ask":
            do_ask = True
        elif arg == "--record":
            index += 1
            if index >= len(rest):
                print("--record needs a path", file=sys.stderr)
                return 2
            record_to = rest[index]
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
        elif arg.startswith("--record="):
            record_to = arg[len("--record="):]
        else:
            print(f"unknown argument {arg!r}\n\n{USAGE}", file=sys.stderr)
            return 2
        index += 1
    if command == "score" and not values and not do_ask:
        print("score needs --value name=value pairs or --ask\n\n" + USAGE, file=sys.stderr)
        return 2
    if command == "inputs" and (do_ask or record_to):
        print("--ask and --record apply to score\n\n" + USAGE, file=sys.stderr)
        return 2
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"prioritize: config error: {exc}", file=sys.stderr)
        return 2
    try:
        kind = backend_of(config, backend)
        if command == "inputs":
            if as_support:
                if as_json:
                    print(json.dumps(
                        {
                            "mode": "support",
                            "criteria": [
                                {
                                    "name": str(c["name"]),
                                    "label": str(c["label"]),
                                    "question": str(c["question"]),
                                    "choices": [
                                        {"choice": label, "points": points}
                                        for label, points in c["choices"]
                                    ],
                                }
                                for c in SUPPORT_CRITERIA
                            ],
                            "possible": SUPPORT_TOTAL,
                        },
                        ensure_ascii=False,
                    ))
                else:
                    _print_support_inputs()
                return 0
            inputs = resolve_inputs(config, kind)
            if as_json:
                print(json.dumps(
                    {
                        "mode": mode_of(config),
                        "backend": kind,
                        "formula": (
                            PRESET_FORMULA if mode_of(config) == "preset"
                            else formula_text(config, inputs)
                        ),
                        "inputs": [
                            {
                                "name": item["name"],
                                "weight": item["weight"],
                                "scale": item["scale"],
                                "rule": item["rule"],
                            }
                            for item in inputs
                        ],
                    },
                    ensure_ascii=False,
                ))
            else:
                if mode_of(config) == "preset":
                    _print_preset_inputs(inputs)
                else:
                    _print_sum_inputs(config, kind)
            return 0
        asked: dict[str, str] = {}
        if as_support:
            if do_ask:
                asked = ask_missing_support(skip=set(values))
                values.update(a for a in asked.items() if a[0] not in values)
            result = support_score(values, asked)
        else:
            if do_ask:
                if mode_of(config) != "preset":
                    raise UsageError(
                        "--ask applies to the preset and support modes; the "
                        "weighted-sum override keeps the missing-input usage error"
                    )
                inputs = resolve_inputs(config, kind)
                still = [i for i in inputs if i["name"] not in values]
                asked = ask_missing_preset(still)
                values.update(a for a in asked.items() if a[0] not in values)
            result = score(config, kind, values, asked)
        if as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            _print_plain(result)
        if record_to:
            try:
                write_record(record_to, result)
            except OSError as exc:
                print(f"prioritize: cannot write the record at {record_to} ({exc})",
                      file=sys.stderr)
                return 3
            if not as_json:
                print(f"record written: {record_to}")
        return 0
    except UsageError as exc:
        print(f"prioritize: {exc}", file=sys.stderr)
        return 2
    except NormalizeError as exc:
        print(f"prioritize: value error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
